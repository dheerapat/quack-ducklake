#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Exercise Quack, DuckLake persistence, and RustFS from the host CLI."""

from __future__ import annotations

import subprocess
import sys
import time

from common import (
    ROOT,
    compose,
    duckdb_executable,
    quack_connection,
    quack_session_sql,
    wait_for_quack,
)


def main() -> int:
    duckdb = duckdb_executable()
    token, port = quack_connection()

    compose("up", "-d", "rustfs")
    compose("up", "-d", "bucket-init")
    compose("up", "-d", "duckdb-server")

    if not wait_for_quack(
        duckdb,
        token,
        port,
        error_message="DuckDB server did not become ready",
    ):
        return 1

    setup_and_insert = quack_session_sql(token, port) + """
CREATE TABLE IF NOT EXISTS lake.events (
    id BIGINT,
    event_ts TIMESTAMP,
    customer VARCHAR,
    amount DOUBLE
);
INSERT INTO lake.events
SELECT * FROM (
    VALUES
        (1, TIMESTAMP '2026-01-01 00:00:00', 'smoke', 42.0),
        (2, TIMESTAMP '2026-01-01 00:00:01', 'smoke', 7.5)
) AS t(id, event_ts, customer, amount);
SELECT count() AS rows FROM lake.events;
"""
    subprocess.run(
        [duckdb, "-csv", ":memory:", "-c", setup_and_insert],
        cwd=ROOT,
        check=True,
    )

    objects = compose(
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "/bin/sh",
        "bucket-init",
        "-c",
        'aws --endpoint-url http://rustfs:9000 s3 ls "s3://$LAKEHOUSE_BUCKET" --recursive',
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    object_listing = objects.stdout or ""
    print(object_listing, end="")
    if objects.returncode != 0 or ".parquet" not in object_listing:
        print("Smoke test found no Parquet object in RustFS", file=sys.stderr)
        return 1

    compose("restart", "duckdb-server", stdout=subprocess.DEVNULL)
    time.sleep(3)
    if not wait_for_quack(
        duckdb,
        token,
        port,
        error_message="DuckDB server did not become ready after restart",
    ):
        return 1

    verify_persistence = quack_session_sql(token, port) + (
        "SELECT count() AS rows FROM lake.events;"
    )
    subprocess.run(
        [duckdb, "-csv", ":memory:", "-c", verify_persistence],
        cwd=ROOT,
        check=True,
    )
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
