#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Insert generated batches into the existing lake.events table over Quack."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from typing import TextIO

from common import (
    ROOT,
    compose,
    duckdb_executable,
    quack_connection,
    quack_session_sql,
    wait_for_quack,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate batched server-side rows in lake.events over Quack."
    )
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--checkpoint-every", type=int, default=0)
    args = parser.parse_args()

    if min(args.rows, args.batch_size, args.checkpoint_every) < 0:
        parser.error(
            "rows, batch-size, and checkpoint-every must be non-negative integers"
        )
    if args.rows == 0:
        parser.error("--rows must be positive")
    if args.batch_size == 0:
        parser.error("--batch-size must be positive")
    return args


def build_load_sql(
    output: TextIO, *, rows: int, batch_size: int, checkpoint_every: int
) -> None:
    """Write each batch incrementally to the DuckDB command stream."""
    start = 0
    batch = 0
    while start < rows:
        end = min(start + batch_size, rows)
        count = end - start
        output.write(
            "BEGIN;\n"
            "INSERT INTO lake.events\n"
            "SELECT i,\n"
            "       TIMESTAMP '2026-01-01 00:00:00' + i * INTERVAL 1 SECOND,\n"
            "       'customer-' || (i % 10000),\n"
            "       random() * 100\n"
            f"FROM range({start}, {end}) AS r(i);\n"
            "COMMIT;\n"
            f"SELECT {count} AS inserted_rows;\n"
        )
        batch += 1
        start = end

        if checkpoint_every and batch % checkpoint_every == 0:
            output.write(f"CHECKPOINT;\nSELECT {start} AS checkpointed_rows;\n")

    output.write("SELECT count() AS total_rows FROM lake.events;\n")


def main() -> int:
    args = parse_args()
    duckdb = duckdb_executable()
    token, port = quack_connection()

    compose("up", "-d", "rustfs", "bucket-init", "duckdb-server")
    if not wait_for_quack(
        duckdb,
        token,
        port,
        error_message="DuckDB server did not become ready through local DuckDB",
    ):
        return 1

    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as sql_file:
        sql_file.write(quack_session_sql(token, port))
        sql_file.write("\n")
        build_load_sql(
            sql_file,
            rows=args.rows,
            batch_size=args.batch_size,
            checkpoint_every=args.checkpoint_every,
        )
        sql_file.seek(0)
        subprocess.run(
            [duckdb, "-csv", ":memory:"],
            cwd=ROOT,
            stdin=sql_file,
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
