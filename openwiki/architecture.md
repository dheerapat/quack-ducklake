# Runtime architecture

## Service graph

`compose.yaml` defines four services and two named volumes:

```text
rustfs-perms -> rustfs -> bucket-init -> duckdb-server
                   |                         |
                   +-- rustfs-data           +-- duckdb-catalog:/catalog/db.duckdb
                                              +-- s3://<bucket>/data/ in RustFS
```

- **`rustfs-perms`** runs as root in `alpine:3.22` and changes the `rustfs-data` volume ownership to UID/GID `10001`.
- **`rustfs`** runs `rustfs/rustfs:latest` by default, exposes the S3 API on container port 9000 and the console on 9001, and stores objects in `/data`.
- **`bucket-init`** uses `amazon/aws-cli:2.36.8` to poll RustFS and idempotently create the configured bucket. It talks to `http://rustfs:9000`, not the host-published address.
- **`duckdb-server`** builds a small image from the configured DuckDB image and starts the server entrypoint. It owns the catalog and the Quack listener.
Compose `depends_on` conditions enforce permission setup, bucket initialization, and then server startup. The smoke test and load generator use the host DuckDB CLI over the published Quack port and poll Quack readiness themselves.

## Catalog and data ownership

The server entrypoint (`docker/duckdb/server-entrypoint`) runs one in-memory DuckDB process with an initialization SQL file. It:

1. Installs and loads `httpfs`, `ducklake`, and `quack`.
2. Creates an S3 secret using the RustFS credentials, `RUSTFS_ENDPOINT`, path-style URLs, and `USE_SSL false`.
3. Attaches `ducklake:${DUCKDB_CATALOG_PATH}` as `lake`, with `DATA_PATH` set to the RustFS S3 location.
4. Sets `DATA_INLINING_ROW_LIMIT 0`, forcing inserted table data into Parquet objects rather than DuckLake catalog inlining.
5. Calls `quack_serve('quack:0.0.0.0:9494', ...)` with the configured token and disabled SSL.
6. Keeps the same process alive with a FIFO and `tail -f`; this is important because the attached catalog and Quack listener belong to that process.

The persistent catalog volume contains `/catalog/db.duckdb`. RustFS owns the Parquet data volume. The host DuckDB client only connects over Quack and does not open either volume, preserving the single-writer catalog boundary.

## Configuration contract

`.env.example` is the operator-facing variable list. Compose defaults are also embedded in `compose.yaml`:

| Variable | Role | Default |
| --- | --- | --- |
| `DUCKDB_IMAGE` | source image for the DuckDB server binary | `duckdb/duckdb:1.5.3` |
| `RUSTFS_IMAGE` | object-store image | `rustfs/rustfs:latest` |
| `AWS_CLI_IMAGE` | bucket bootstrap image | `amazon/aws-cli:2.36.8` |
| `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY` | S3 credentials | `ducklake_access`, `ducklake_secret` |
| `RUSTFS_REGION` | S3 region passed to DuckDB/AWS CLI | `us-east-1` |
| `RUSTFS_ENDPOINT` | endpoint used by DuckDB | `rustfs:9000` |
| `LAKEHOUSE_BUCKET` | bucket and first segment of `DUCKLAKE_DATA_PATH` | `lakehouse` |
| `QUACK_TOKEN` | Quack authentication token | `local-quack-token` |
| `RUSTFS_API_PORT`, `RUSTFS_CONSOLE_PORT`, `QUACK_PORT` | host-published ports | `9000`, `9001`, `9494` |

The entrypoint rejects credentials/tokens containing quotes, backslashes, or non-printable/non-ASCII characters because values are interpolated into SQL. It also requires a Quack token of at least four characters. `RUSTFS_REGION` is optional to the entrypoint and defaults to `us-east-1` there.

## Design boundaries

This is a simulation, not a production HA deployment. It intentionally omits TLS, metrics/tracing, Grafana/Prometheus/Jaeger, and multi-node RustFS. The catalog file is a single point of failure. If independent writers or high availability become requirements, `PLAN.md` identifies PostgreSQL as the stronger future catalog direction.
