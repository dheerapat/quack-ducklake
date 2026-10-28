# Wiki quickstart

This repository is a local Docker Compose simulation of a small-business DuckLake lakehouse:

```text
DuckDB client --Quack/HTTP--> duckdb-server --DuckLake/S3--> RustFS
                                  |
                                  +-- /catalog/db.duckdb
```

`duckdb-server` is the only process that opens the DuckDB catalog. Clients query it through Quack and do not mount the catalog or RustFS data directly.

## Navigate

- [Runtime architecture](architecture.md) — services, ownership, storage, and configuration boundaries.
- [Operator and workload workflows](workflows.md) — startup, smoke testing, loading data, querying, and restart checks.

## Prerequisites

- Docker with Docker Compose.
- [uv](https://docs.astral.sh/uv/) to run the repository Python scripts. They use only the Python standard library.
- Network access to pull the configured images on the first run.
- DuckDB 2.0.0 or newer for the optional local CLI. DuckDB 2.0.0 LTS includes the polished Quack protocol and the `CONNECT` statement for routing a client session to a remote database.

## Start locally

```bash
cp .env.example .env
# Set RUSTFS_SECRET_KEY and QUACK_TOKEN to non-default values outside local testing.
docker compose up -d
```

Endpoints published by Compose:

- RustFS S3 API: <http://localhost:9000>
- RustFS console: <http://localhost:9001>
- Quack: `localhost:9494`

The default internal data path is `s3://lakehouse/data/`; the catalog is persisted at `/catalog/db.duckdb` inside the `duckdb-catalog` volume. See [architecture](architecture.md) for the service dependency order.

## Validate

Run the smoke test from the repository root:

```bash
uv run scripts/smoke-test.py
```

It waits for Quack, creates `lake.events`, inserts two rows, checks that RustFS contains a Parquet object, restarts `duckdb-server`, and checks the row count again.

For larger server-side batches:

```bash
uv run scripts/generate-load.py --rows 1000000 --batch-size 100000
uv run scripts/generate-load.py --rows 10000000 --batch-size 250000 --checkpoint-every 10
```

The generator commits each batch through Quack and can issue `CHECKPOINT` after every N batches. See [workflows](workflows.md) for option validation and data assumptions.

## Query through Quack

```bash
duckdb -c \
  "INSTALL quack; LOAD quack; ATTACH 'quack:127.0.0.1:9494' AS qk (TOKEN 'local-quack-token'); CONNECT qk; SELECT count() FROM lake.events;"
```

The example uses the default token. If `.env` overrides `QUACK_TOKEN`, substitute that value or use the repository scripts, which read it from the environment.

## Stop or reset

```bash
docker compose down    # stop services; retain catalog and object data
docker compose down -v # delete the named simulation volumes and data
```

## Important limits

- DuckDB 2.0.0 ships a polished Quack protocol with performance and stability improvements. Quack still exposes the server's broad SQL surface, so protect the endpoint.
- RustFS runs single-node/single-disk with no redundancy.
- `/catalog/db.duckdb` is a single point of failure; back it up for any real deployment.
- Quack is exposed directly with `allow_other_hostname` and plain HTTP only for this local test simulation. For deployments, follow DuckDB's [Quack security guidance](https://duckdb.org/docs/2.0/quack/setup/reverse_proxy.html) and put a TLS-terminating reverse proxy in front of a localhost-bound server.
- TLS, observability, and multi-node RustFS are intentionally absent.
