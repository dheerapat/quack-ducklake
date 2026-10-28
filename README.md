# Quack Ducklake Demo

```text
DuckDB client --Quack/HTTP--> DuckDB server --DuckLake/S3--> RustFS
                                  |
                                  +-- /catalog/db.duckdb
```

The server image defaults to DuckDB 2.0.0 LTS. Host clients use the 2.0 `ATTACH` + `CONNECT` workflow over the polished Quack protocol. The client never mounts the catalog or RustFS data; only the single `duckdb-server` process opens the catalog.

## Start

Prerequisites: Docker Compose, [uv](https://docs.astral.sh/uv/) for the helper scripts, and DuckDB CLI 2.0.0+ for host-side Quack queries. The helper scripts use only the Python standard library.

```bash
cp .env.example .env
# Change RUSTFS_SECRET_KEY and QUACK_TOKEN for anything beyond local testing.
docker compose up -d
```

Compose automatically reads `.env` from the project directory, so `docker compose up -d` does not need an `--env-file` flag. For a different file, use `docker compose --env-file /path/to/settings.env up -d`.

The local scripts read shell environment variables rather than sourcing `.env`. If `.env` changes `QUACK_TOKEN` or `QUACK_PORT`, export those values before running them, for example:

```bash
export QUACK_TOKEN=change-me-quack-token
export QUACK_PORT=9494
uv run scripts/smoke-test.py
```

The RustFS S3 API is at <http://localhost:9000>; its console is at <http://localhost:9001>. Quack listens at `localhost:9494`.

## How it works

```text
local duckdb CLI --Quack/HTTP--> duckdb-server --DuckLake/S3--> RustFS
                                      |
                                      +-- /catalog/db.duckdb
```

`compose.yaml` starts four services in dependency order:

1. `rustfs-perms` prepares the RustFS volume permissions and exits.
2. `rustfs` provides S3-compatible object storage for Parquet files.
3. `bucket-init` waits for RustFS and creates the `lakehouse` bucket if needed, then exits.
4. `duckdb-server` is the only process that opens the DuckLake catalog and serves Quack on port `9494`.

The local DuckDB 2.0.0+ CLI attaches to `127.0.0.1:9494` through Quack and uses `CONNECT` to route queries to the server. It does not open `/catalog/db.duckdb` or mount RustFS data. Inside the Compose network, DuckDB reaches RustFS at `http://rustfs:9000`; the catalog is persisted in `duckdb-catalog`, while Parquet data is persisted in `rustfs-data`.

`rustfs-perms` and `bucket-init` are one-shot setup services, so their `Exited` status is expected. `rustfs` and `duckdb-server` should remain running.

## Validate

Run the smoke test. It creates `lake.events`, inserts two rows, verifies a Parquet object in RustFS, restarts DuckDB, and checks the row count again:

```bash
uv run scripts/smoke-test.py
```

Generate server-side batches through one local DuckDB client process. The generator defaults to 1M rows:

```bash
uv run scripts/generate-load.py --rows 1000000 --batch-size 100000
uv run scripts/generate-load.py --rows 10000000 --batch-size 250000 --checkpoint-every 10
```

Run `uv run scripts/smoke-test.py` first on a fresh stack so it creates `lake.events`; `generate-load` uses the host `duckdb` CLI (2.0.0 or newer) to route requests through Quack with `CONNECT` and inserts into that existing table.

`DATA_INLINING_ROW_LIMIT` is set to `0`, so inserts go to Parquet rather than DuckLake catalog inlining.

The smoke test and load generator use the host `duckdb` executable. `generate-load` opens one local DuckDB process and sends batch SQL through Quack; the `range()` and `INSERT` execute inside `duckdb-server`, so rows are not loaded into the local client first. The table must exist before running `generate-load`, so run the smoke test first after a reset.

## Query through Quack

```bash
duckdb -c \
  "INSTALL quack; LOAD quack; ATTACH 'quack:127.0.0.1:9494' AS qk (TOKEN 'local-quack-token'); CONNECT qk; SELECT count() FROM lake.events;"
```

Use a host DuckDB CLI version 2.0.0 or newer. DuckDB 2.0.0 adds the `CONNECT` statement for session routing and ships a polished Quack protocol with performance and stability improvements. See the [DuckDB 2.0.0 announcement](https://duckdb.org/2026/10/21/announcing-duckdb-200) and [Quack documentation](https://duckdb.org/docs/2.0/quack/overview.html). Set `DUCKDB_BIN` if the executable is not named `duckdb` or is outside `PATH`.

## Stop/reset

```bash
docker compose down                  # keep catalog and object data

docker compose down -v               # delete the simulation data
```

The `-v` form permanently removes both the DuckLake catalog and RustFS Parquet data. After a reset, run `uv run scripts/smoke-test.py` to recreate `lake.events` and validate the fresh stack.

## Caveats

- DuckDB 2.0.0 ships a polished Quack protocol with performance and stability improvements. Quack still exposes the server's broad SQL surface, so protect the endpoint.
- RustFS is single-node/single-disk here; it has no redundancy.
- `/catalog/db.duckdb` is a single point of failure. Back it up in a real deployment.
- Quack is exposed directly with `allow_other_hostname` and plain HTTP only for this local test simulation. The DuckDB 2.0.0 guidance recommends a localhost-bound server behind a TLS-terminating reverse proxy for deployments; do not expose this Compose endpoint to an untrusted network.
- This intentionally omits observability, TLS, and multi-node RustFS from the initial simulation.
