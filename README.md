# Ducan

```text
DuckDB client --Quack/HTTP--> DuckDB server --DuckLake/S3--> S3-compatible storage
                                      (RustFS locally; external S3 in production)
                                  |
                                  +-- /catalog/db.duckdb
```

The client never mounts the catalog or RustFS data. Only the single `duckdb-server` process opens the catalog.

## Start

Requires Docker Compose and [uv](https://docs.astral.sh/uv/).

```bash
uv run bin/ducan init
uv run bin/ducan up
uv run bin/ducan status
```

`ducan init` creates `.env` with local secrets. Review it before starting. The API is available at `http://127.0.0.1:8080`.

For direct Compose usage:

```bash
cp .env.example .env
docker compose up -d
```

Compose automatically reads `.env` from the project directory, so `docker compose up -d` does not need an `--env-file` flag. For a different file, use `docker compose --env-file /path/to/settings.env up -d`.

The local scripts read shell environment variables rather than sourcing `.env`. If `.env` changes `QUACK_TOKEN` or `QUACK_PORT`, export those values before running them, for example:

```bash
export QUACK_TOKEN=change-me-quack-token
export QUACK_PORT=9494
./scripts/smoke-test
```

The local RustFS S3 API is at <http://localhost:9000>; its console is at <http://localhost:9001>. Quack listens at `localhost:9494`, and the Ducan API at `localhost:8080`. RustFS is for local testing only.

## How it works

```text
local duckdb CLI --Quack/HTTP--> duckdb-server --DuckLake/S3--> S3-compatible storage
                                      (RustFS locally; external S3 in production)
                                      |
                                      +-- /catalog/db.duckdb
```

`compose.yaml` starts five services in dependency order:

1. `rustfs-perms` prepares the RustFS volume permissions and exits.
2. `rustfs` provides S3-compatible object storage for Parquet files.
3. `bucket-init` waits for RustFS and creates the `lakehouse` bucket if needed, then exits.
4. `duckdb-server` is the only process that opens the DuckLake catalog and serves Quack on port `9494`.
5. `api` provides the authenticated Ducan API on port `8080` and stores control-plane state separately.

The local DuckDB CLI connects to `127.0.0.1:9494` through Quack. It does not open `/catalog/db.duckdb` or mount RustFS data. Inside the Compose network, DuckDB reaches RustFS at `http://rustfs:9000`; the catalog is persisted in `duckdb-catalog`, while Parquet data is persisted in `rustfs-data`.

`rustfs-perms` and `bucket-init` are one-shot setup services, so their `Exited` status is expected. `rustfs` and `duckdb-server` should remain running.

## Production storage

Use an external S3-compatible service—AWS S3, Cloudflare R2, MinIO, or another provider—in real deployments. RustFS is included only for local testing:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

Set `S3_BUCKET` and `DUCKDB_SECRETS` in `.env.production`. Each semicolon-separated secret body becomes a named DuckDB secret. The production Compose file does not start RustFS or the bucket bootstrap container.

## Register a source and ingest

The first platform workflow imports a PostgreSQL table into `lake.raw`:

```bash
uv run bin/ducan source add postgres \
  --name sales --host localhost --database sales --username ducan_reader
uv run bin/ducan ingest --source sales --schema public --table orders --wait
uv run bin/ducan jobs
```

Passwords are prompted for and stored outside the control database with restrictive file permissions.

## Validate

Run the smoke test. It creates `lake.events`, inserts two rows, verifies a Parquet object in RustFS, restarts DuckDB, and checks the row count again:

```bash
scripts/smoke-test
```

Generate server-side batches through one local DuckDB client process. The generator defaults to 1M rows:

```bash
scripts/generate-load --rows 1000000 --batch-size 100000
scripts/generate-load --rows 10000000 --batch-size 250000 --checkpoint-every 10
```

Run `scripts/smoke-test` first on a fresh stack so it creates `lake.events`; `generate-load` uses the host `duckdb` CLI (1.5.3 or newer) to send requests through Quack and inserts into that existing table.

`DATA_INLINING_ROW_LIMIT` is set to `0`, so inserts go to Parquet rather than DuckLake catalog inlining.

The smoke test and load generator use the host `duckdb` executable. `generate-load` opens one local DuckDB process and sends batch SQL through Quack; the `range()` and `INSERT` execute inside `duckdb-server`, so rows are not loaded into the local client first. The table must exist before running `generate-load`, so run the smoke test first after a reset.

## Query through Quack

```bash
duckdb -c \
  "INSTALL quack; LOAD quack; SELECT * FROM quack_query('quack:127.0.0.1:9494', 'SELECT count() FROM lake.events', token => 'local-quack-token', disable_ssl => true);"
```

Use the host DuckDB CLI version 1.5.3 or newer; Quack is a core extension starting with 1.5.3. Set `DUCKDB_BIN` if the executable is not named `duckdb` or is outside `PATH`.

## Stop/reset

```bash
docker compose down                  # keep catalog and object data

docker compose down -v               # delete the simulation data
```

The `-v` form permanently removes both the DuckLake catalog and RustFS Parquet data. After a reset, run `./scripts/smoke-test` to recreate `lake.events` and validate the fresh stack.

## Caveats

- Quack is beta and currently exposes the server's broad SQL surface.
- RustFS is single-node/single-disk here; it has no redundancy.
- `/catalog/db.duckdb` is a single point of failure. Back it up in a real deployment.
- This intentionally omits observability, TLS, and multi-node RustFS from the initial simulation.
