ARG DUCKDB_IMAGE=duckdb/duckdb:2.0.0
FROM ${DUCKDB_IMAGE} AS duckdb

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=duckdb /duckdb /usr/local/bin/duckdb
COPY server-entrypoint /usr/local/bin/server-entrypoint

ENTRYPOINT ["duckdb"]
