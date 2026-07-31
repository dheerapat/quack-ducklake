#!/usr/bin/env python3
"""Small, dependency-free Ducan control plane for the local appliance."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
TERMINAL = {"succeeded", "failed"}
WORKER_LOCK = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a letter/underscore followed by letters, numbers, or underscores")
    return value


def port(value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError("port must be a number") from None
    if not 1 <= result <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return result


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def redact(message: str, dsn: str = "", password: str = "") -> str:
    if password:
        message = message.replace(password, "[REDACTED]")
    if dsn:
        message = message.replace(dsn, "[REDACTED CONNECTION]")
    return message[-2000:]


def config() -> dict[str, str]:
    return {
        "db": os.environ.get("DUCAN_CONTROL_DB", "/var/lib/ducan/control.db"),
        "secret_dir": os.environ.get("DUCAN_SECRET_DIR", "/var/lib/ducan/secrets"),
        "quack_url": os.environ.get("DUCAN_QUACK_URL", "quack:127.0.0.1:9494"),
        "quack_token": os.environ.get("QUACK_TOKEN", "local-quack-token"),
        "api_token": os.environ.get("DUCAN_API_TOKEN", "local-ducan-token"),
        "duckdb": os.environ.get("DUCKDB_BIN", "duckdb"),
        "host": os.environ.get("DUCAN_API_HOST", "0.0.0.0"),
        "port": os.environ.get("DUCAN_API_INTERNAL_PORT", "8080"),
        "query_timeout": os.environ.get("DUCAN_QUERY_TIMEOUT", "300"),
    }


CONFIG = config()
Path(CONFIG["secret_dir"]).mkdir(parents=True, exist_ok=True)
Path(CONFIG["db"]).parent.mkdir(parents=True, exist_ok=True)


def connection() -> sqlite3.Connection:
    db = sqlite3.connect(CONFIG["db"], timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              type TEXT NOT NULL,
              host TEXT NOT NULL,
              port INTEGER NOT NULL,
              database_name TEXT NOT NULL,
              username TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              source_name TEXT NOT NULL,
              source_schema TEXT NOT NULL,
              source_table TEXT NOT NULL,
              target_table TEXT NOT NULL,
              mode TEXT NOT NULL,
              status TEXT NOT NULL,
              rows_imported INTEGER,
              error TEXT,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT
            );
            """
        )
        db.execute(
            "UPDATE jobs SET status = 'failed', error = 'API restarted before job completed', finished_at = ? WHERE status IN ('queued', 'running')",
            (now(),),
        )


def row_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else {}


def source_public(row: sqlite3.Row) -> dict:
    return row_dict(row)


def get_source(source_id: str | None = None, name: str | None = None) -> sqlite3.Row | None:
    with connection() as db:
        if source_id:
            return db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return db.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()


def save_secret(source_id: str, password: str) -> None:
    path = Path(CONFIG["secret_dir"]) / f"{source_id}.secret"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, password.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def read_secret(source_id: str) -> str:
    return (Path(CONFIG["secret_dir"]) / f"{source_id}.secret").read_text().rstrip("\n")


def delete_secret(source_id: str) -> None:
    try:
        (Path(CONFIG["secret_dir"]) / f"{source_id}.secret").unlink()
    except FileNotFoundError:
        pass


def dsn_for(source: sqlite3.Row) -> tuple[str, str]:
    password = read_secret(source["id"])
    user = urllib.parse.quote(source["username"], safe="")
    encoded_password = urllib.parse.quote(password, safe="")
    database = urllib.parse.quote(source["database_name"], safe="")
    dsn = f"postgresql://{user}:{encoded_password}@{source['host']}:{source['port']}/{database}"
    return dsn, password


def quack_script(remote_sql: str) -> str:
    return "\n".join(
        [
            "INSTALL quack;",
            "LOAD quack;",
            "SELECT * FROM quack_query(",
            f"  {sql_literal(CONFIG['quack_url'])},",
            f"  {sql_literal(remote_sql)},",
            f"  token => {sql_literal(CONFIG['quack_token'])},",
            "  disable_ssl => true",
            ");",
        ]
    )


def run_quack(remote_sql: str) -> list[dict]:
    command = [CONFIG["duckdb"], "-json", ":memory:", "-c", quack_script(remote_sql)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=int(CONFIG["query_timeout"]),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DuckDB query timed out") from exc
    if result.returncode:
        raise RuntimeError(redact(result.stderr or result.stdout))
    output = result.stdout.strip()
    if not output:
        return []
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DuckDB returned an invalid response") from exc
    return value if isinstance(value, list) else []


def import_postgres(job_id: str) -> None:
    with WORKER_LOCK:
        with connection() as db:
            db.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?", (now(), job_id))
            job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            source = db.execute("SELECT * FROM sources WHERE id = ?", (job["source_id"],)).fetchone()
        dsn, password = dsn_for(source)
        try:
            remote_sql = " ".join(
                [
                    "CREATE SCHEMA IF NOT EXISTS lake.raw;",
                    f"CREATE OR REPLACE TABLE lake.raw.{sql_identifier(job['target_table'])} AS",
                    f"SELECT * FROM postgres_scan({sql_literal(dsn)}, {sql_literal(job['source_schema'])}, {sql_literal(job['source_table'])});",
                    f"SELECT count() AS rows_imported FROM lake.raw.{sql_identifier(job['target_table'])};",
                ]
            )
            rows = run_quack(remote_sql)
            imported = int(rows[-1]["rows_imported"]) if rows and rows[-1].get("rows_imported") is not None else None
            with connection() as db:
                db.execute(
                    "UPDATE jobs SET status = 'succeeded', rows_imported = ?, finished_at = ? WHERE id = ?",
                    (imported, now(), job_id),
                )
        except Exception as exc:
            with connection() as db:
                db.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                    (redact(str(exc), dsn, password), now(), job_id),
                )


class Handler(BaseHTTPRequestHandler):
    server_version = "Ducan/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def authorized(self) -> bool:
        expected = f"Bearer {CONFIG['api_token']}"
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def route(self) -> tuple[str, str]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path, parsed.query

    def do_GET(self) -> None:
        path, query = self.route()
        if path == "/healthz":
            return self.json(200, {"status": "ok"})
        if path == "/readyz":
            try:
                run_quack("SELECT 42 AS ready")
                return self.json(200, {"status": "ready"})
            except Exception as exc:
                return self.json(503, {"status": "not_ready", "error": redact(str(exc))})
        if not self.authorized():
            return self.json(401, {"error": "unauthorized"})
        if path == "/v1/sources":
            with connection() as db:
                rows = db.execute("SELECT * FROM sources ORDER BY name").fetchall()
            return self.json(200, [source_public(row) for row in rows])
        if path == "/v1/jobs":
            with connection() as db:
                rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
            return self.json(200, [row_dict(row) for row in rows])
        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with connection() as db:
                row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self.json(200 if row else 404, row_dict(row) if row else {"error": "job not found"})
        return self.json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path, _ = self.route()
        if not self.authorized():
            return self.json(401, {"error": "unauthorized"})
        try:
            value = self.body()
            if path == "/v1/sources":
                return self.create_source(value)
            if path == "/v1/ingestions":
                return self.create_ingestion(value)
            return self.json(404, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self.json(400, {"error": str(exc)})
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "source name already exists"})

    def do_DELETE(self) -> None:
        path, _ = self.route()
        if not self.authorized():
            return self.json(401, {"error": "unauthorized"})
        if not path.startswith("/v1/sources/"):
            return self.json(404, {"error": "not found"})
        source_id = path.rsplit("/", 1)[-1]
        with connection() as db:
            row = db.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
            if not row:
                return self.json(404, {"error": "source not found"})
            db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        delete_secret(source_id)
        return self.json(200, {"deleted": source_id})

    def create_source(self, value: dict) -> None:
        source_type = value.get("type", "postgres")
        if source_type != "postgres":
            raise ValueError("only postgres sources are supported in milestone 1")
        name = identifier(value.get("name"), "name")
        host = value.get("host")
        database = value.get("database")
        username = value.get("username")
        password = value.get("password")
        if not all(isinstance(item, str) and item for item in (host, database, username, password)):
            raise ValueError("host, database, username, and password are required")
        if len(host) > 253 or any(char.isspace() or ord(char) < 32 for char in host):
            raise ValueError("host must not contain whitespace or control characters")
        source_id = secrets.token_hex(12)
        source_port = port(value.get("port", 5432))
        save_secret(source_id, password)
        try:
            with connection() as db:
                db.execute(
                    "INSERT INTO sources VALUES (?, ?, 'postgres', ?, ?, ?, ?, ?)",
                    (source_id, name, host, source_port, database, username, now()),
                )
        except Exception:
            delete_secret(source_id)
            raise
        with connection() as db:
            row = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self.json(201, source_public(row))

    def create_ingestion(self, value: dict) -> None:
        source_name = identifier(value.get("source"), "source")
        source_schema = identifier(value.get("schema", "public"), "schema")
        source_table = identifier(value.get("table"), "table")
        target_table = identifier(value.get("target", source_table), "target")
        mode = value.get("mode", "replace")
        if mode != "replace":
            raise ValueError("only replace mode is supported in milestone 1")
        source = get_source(name=source_name)
        if not source:
            return self.json(404, {"error": "source not found"})
        job_id = secrets.token_hex(12)
        with connection() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', NULL, NULL, ?, NULL, NULL)",
                (job_id, source["id"], source_name, source_schema, source_table, target_table, mode, now()),
            )
        threading.Thread(target=import_postgres, args=(job_id,), daemon=True).start()
        return self.json(202, {"id": job_id, "status": "queued"})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((CONFIG["host"], int(CONFIG["port"])), Handler)
    print(f"Ducan API listening on {CONFIG['host']}:{CONFIG['port']}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
