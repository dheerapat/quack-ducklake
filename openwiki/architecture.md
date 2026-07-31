# Runtime architecture

## Service graph

`compose.yaml` defines five services and three named volumes for local testing. RustFS is the local S3-compatible test backend; real deployments should use external S3-compatible storage via `compose.production.yaml`.

```text
rustfs-perms -> rustfs -> bucket-init -> duckdb-server -> api
                   |                         |             |
                   +-- rustfs-data           +-- duckdb-catalog  +-- ducan-control
                                              +-- s3://<bucket>/data/ in RustFS
```

- **`rustfs-perms`** runs as root in `alpine:3.22` and changes the `rustfs-data` volume ownership to UID/GID `10001`.
- **`rustfs`** runs `rustfs/rustfs:latest` by default, exposes the S3 API on container port 9000 and the console on 9001, and stores objects in `/data`.
- **`bucket-init`** uses `amazon/aws-cli:2.36.8` to poll RustFS and idempotently create the configured bucket. It talks to `http://rustfs:9000`, not the host-published address.
- **`duckdb-server`** builds a small image from the configured DuckDB image and starts the server entrypoint. It owns the catalog and the Quack listener.
- **`api`** runs the uv-managed, dependency-free Ducan control plane. It owns source/job metadata and secrets, then sends ingestion SQL through Quack; it never opens the catalog directly.
Compose `depends_on` conditions enforce permission setup, bucket initialization, and then server startup. The smoke test and load generator use the host DuckDB CLI over the published Quack port and poll Quack readiness themselves.

## Catalog and data ownership

The server entrypoint (`docker/duckdb/server-entrypoint`) runs one in-memory DuckDB process with an initialization SQL file. It:

1. Installs and loads `httpfs`, `ducklake`, `postgres`, and `quack`.
2. Creates each configured DuckDB secret from the semicolon-separated `DUCKDB_SECRETS` bodies.
3. Attaches `ducklake:${DUCKDB_CATALOG_PATH}` as `lake`, with `DATA_PATH` set to the configured S3-compatible location.
4. Sets `DATA_INLINING_ROW_LIMIT 0`, forcing inserted table data into Parquet objects rather than DuckLake catalog inlining.
5. Calls `quack_serve('quack:0.0.0.0:9494', ...)` with the configured token and disabled SSL.
6. Keeps the same process alive with a FIFO and `tail -f`; this is important because the attached catalog and Quack listener belong to that process.

The persistent catalog volume contains `/catalog/db.duckdb`. The configured S3-compatible object store owns the Parquet data; in local Compose that store is RustFS. The Ducan API persists control metadata in `ducan-control` and stores PostgreSQL passwords as separate mode-0600 secret files. Clients only connect through the API or Quack and do not open either data volume, preserving the single-writer catalog boundary.

## Configuration contract

`.env.example` is the operator-facing variable list. Compose defaults are also embedded in `compose.yaml`:

| Variable | Role | Default |
| --- | --- | --- |
| `DUCKDB_IMAGE` | source image for the DuckDB server binary | `duckdb/duckdb:1.5.3` |
| `RUSTFS_IMAGE` | object-store image | `rustfs/rustfs:latest` |
| `AWS_CLI_IMAGE` | bucket bootstrap image | `amazon/aws-cli:2.36.8` |
| `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY` | local RustFS bootstrap credentials | `ducklake_access`, `ducklake_secret` |
| `S3_BUCKET` | bucket and first segment of `DUCKLAKE_DATA_PATH` | `lakehouse` |
| `DUCKDB_SECRETS` | semicolon-separated DuckDB `CREATE SECRET` bodies | local RustFS secret body |
| `DUCKLAKE_DATA_PATH` | optional explicit DuckLake data path | `s3://<S3_BUCKET>/data/` |
| `LAKEHOUSE_BUCKET` | legacy local bucket alias used by bucket bootstrap | `lakehouse` |
| `QUACK_TOKEN` | Quack authentication token | `local-quack-token` |
| `DUCAN_API_TOKEN` | Ducan API bearer token | `local-ducan-token` |
| `RUSTFS_API_PORT`, `RUSTFS_CONSOLE_PORT`, `QUACK_PORT`, `DUCAN_API_PORT` | host-published ports | `9000`, `9001`, `9494`, `8080` |

The entrypoint rejects non-printable/non-ASCII values in `DUCKDB_SECRETS` and rejects quotes or backslashes in the Quack token because it is interpolated into SQL. It also requires a Quack token of at least four characters.

## Design boundaries

The default stack is a simulation, not a production HA deployment. For production, use `compose.production.yaml` with an external S3-compatible store and `.env.production.example`; do not run RustFS as the production data store. TLS, metrics/tracing, and high availability still require an external deployment boundary. The catalog file is a single point of failure. If independent writers or high availability become requirements, PostgreSQL is the stronger future catalog direction.
