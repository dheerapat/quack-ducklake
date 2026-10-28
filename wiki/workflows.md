# Operator and workload workflows

## Startup and bootstrap

From the repository root:

```bash
cp .env.example .env
docker compose up -d
```

Compose starts the stack in this order:

1. `rustfs-perms` prepares `rustfs-data` ownership.
2. `rustfs` starts the single-node object store.
3. `bucket-init` polls `s3api list-buckets`, then creates `LAKEHOUSE_BUCKET` if `head-bucket` cannot find it.
4. `duckdb-server` builds/starts after bucket initialization succeeds and attaches the catalog to RustFS.
5. The host DuckDB 2.0.0+ CLI attaches to the published Quack endpoint and uses `CONNECT` to route queries; it is not a Compose service.

Bucket creation is safe to repeat. The server entrypoint is not a migration runner: it installs extensions and attaches the existing catalog on every start.

## Smoke test

```bash
uv run scripts/smoke-test.py
```

The script changes to the repository root, uses the host `duckdb` CLI (or `DUCKDB_BIN`), and performs this sequence:

1. Starts `rustfs`, `bucket-init`, and `duckdb-server`.
2. Polls Quack up to 30 times, sleeping two seconds between failures.
3. Creates `lake.events` if needed and inserts two fixed rows.
4. Lists the configured bucket recursively through AWS CLI and requires a `.parquet` object.
5. Restarts `duckdb-server`, waits three seconds, polls Quack again, and queries the persisted row count.

The Python script reads `QUACK_TOKEN` from the environment, defaulting to `local-quack-token`, and applies the same printable-ASCII/quote restrictions needed by the server SQL call.

## Generate load

```bash
uv run scripts/generate-load.py [--rows N] [--batch-size N] [--checkpoint-every N]
```

Defaults are 1,000,000 rows, batches of 100,000, and no periodic checkpoint. Options must be non-negative integers; `--rows` and `--batch-size` must be positive. The Python script starts only the server-side Compose services, then uses the host `duckdb` CLI (DuckDB 2.0.0 or newer) as one client process. Each batch runs a `BEGIN`/`INSERT`/`COMMIT` transaction through the connected Quack session. Rows use:

- `i` as the ID,
- a timestamp beginning at `2026-01-01 00:00:00` plus `i` seconds,
- `customer-<i % 10000>` as the customer,
- `random() * 100` as the amount.

`--checkpoint-every N` sends `CHECKPOINT` after every N committed batches, then the script queries the final `count()`. Because data inlining is disabled, this exercises Parquet-backed ingestion rather than catalog-only rows.

## Ad-hoc queries

Run the host DuckDB 2.0.0+ CLI, attach to Quack, and route the session with `CONNECT`:

```bash
duckdb -c \
  "INSTALL quack; LOAD quack; ATTACH 'quack:127.0.0.1:9494' AS qk (TOKEN 'local-quack-token'); CONNECT qk; SELECT count() FROM lake.events;"
```

Use the token from `.env` when it differs from the example. The server allows other hostnames and disables SSL because this is an internal local simulation; DuckDB documents this direct exposure mode as testing-only. For deployments, bind Quack to localhost and use a TLS-terminating reverse proxy.

## Persistence and reset checks

To verify persistence without deleting data:

```bash
uv run scripts/smoke-test.py
docker compose restart duckdb-server
```

To stop while retaining both named volumes:

```bash
docker compose down
```

To intentionally discard the catalog and object data:

```bash
docker compose down -v
```

## Change-oriented guidance

- Change service topology, ports, volumes, startup dependencies, or defaults in `compose.yaml` and mirror operator-facing values in `.env.example`.
- Change catalog/S3/Quack bootstrap behavior in `docker/duckdb/server-entrypoint`; preserve its validation and single-process lifetime.
- Change reproducible server image assembly in `docker/duckdb/Dockerfile`.
- Change test data or persistence assertions in `scripts/smoke-test.py`.
- Change workload size, batch, or checkpoint behavior in `scripts/generate-load.py`.

No unit-test suite or CI configuration is present in the repository. The smoke test is the checked-in end-to-end validation path; validate Python syntax with `uv run python -m py_compile scripts/*.py` before running Docker-based tests. `generate-load.py` requires a host DuckDB CLI with Quack support; set `DUCKDB_BIN` to override the `duckdb` executable.
