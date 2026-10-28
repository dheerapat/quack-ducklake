"""Shared helpers for the uv-run DuckDB demo scripts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUACK_TOKEN = "local-quack-token"
DEFAULT_QUACK_PORT = 9494


def duckdb_executable() -> str:
    """Resolve the DuckDB CLI, honoring DUCKDB_BIN like the previous shell scripts."""
    requested = os.environ.get("DUCKDB_BIN", "duckdb")
    if os.sep in requested:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        executable = (
            str(candidate)
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    else:
        executable = shutil.which(requested)
    if executable is None:
        print(
            f"DuckDB CLI not found: {requested} (install DuckDB 2.0.0 or newer)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return executable


def quack_connection() -> tuple[str, int]:
    """Load and validate credentials before interpolating them into DuckDB SQL."""
    token = os.environ.get("QUACK_TOKEN", DEFAULT_QUACK_TOKEN)
    if any(char in token for char in ("'", '"', "\\")):
        print("QUACK_TOKEN contains an unsupported quote or slash", file=sys.stderr)
        raise SystemExit(2)
    if any(not 32 <= ord(char) <= 126 for char in token):
        print("QUACK_TOKEN must contain printable ASCII characters", file=sys.stderr)
        raise SystemExit(2)

    port_text = os.environ.get("QUACK_PORT", str(DEFAULT_QUACK_PORT))
    if not re.fullmatch(r"[0-9]+", port_text):
        print("QUACK_PORT must be a valid port number", file=sys.stderr)
        raise SystemExit(2)
    port = int(port_text)
    if not 1 <= port <= 65535:
        print("QUACK_PORT must be a valid port number", file=sys.stderr)
        raise SystemExit(2)
    return token, port


def quack_attach_sql(token: str, port: int) -> str:
    """Return DuckDB 2.0+ setup statements to attach the Quack database."""
    return (
        "INSTALL quack; LOAD quack; "
        f"ATTACH 'quack:127.0.0.1:{port}' AS qk (TOKEN '{token}'); "
    )


def quack_session_sql(token: str, port: int) -> str:
    """Attach and route the current DuckDB session to Quack."""
    return f"{quack_attach_sql(token, port)}CONNECT qk; "


def wait_for_quack(
    duckdb: str,
    token: str,
    port: int,
    *,
    error_message: str,
    attempts: int = 30,
    delay_seconds: int = 2,
) -> bool:
    """Poll the Quack endpoint with the host DuckDB CLI until it answers."""
    command = [
        duckdb,
        "-csv",
        ":memory:",
        "-c",
        f"{quack_session_sql(token, port)}SELECT 42 AS ready;",
    ]
    for attempt in range(attempts):
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            print(result.stdout, end="")
            return True
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    print(error_message, file=sys.stderr)
    return False


def compose(
    *args: str, check: bool = True, **kwargs: object
) -> subprocess.CompletedProcess[str]:
    """Run a Docker Compose command from the repository root."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        check=check,
        text=True,
        **kwargs,
    )

