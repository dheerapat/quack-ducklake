ARG DUCKDB_IMAGE=duckdb/duckdb:1.5.3
FROM ${DUCKDB_IMAGE} AS duckdb
FROM ghcr.io/astral-sh/uv:0.10.11 AS uv

FROM python:3.12-slim
COPY --from=duckdb /duckdb /usr/local/bin/duckdb
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --locked --no-dev
COPY api/server.py .
RUN mkdir -p /var/lib/ducan/secrets && chmod 700 /var/lib/ducan/secrets
EXPOSE 8080
CMD ["uv", "run", "--frozen", "--no-dev", "python", "server.py"]
