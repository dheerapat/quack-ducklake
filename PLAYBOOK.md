# Managed Lakehouse Service — One-Person Company Playbook

This playbook turns the current DuckDB/DuckLake demo into a small, managed data service operated by one person with help from AI coding agents.

The operating principle is:

> Sell reliable business reporting, not database infrastructure.

Customers should not need to understand DuckDB, DuckLake, S3, SQL, containers, or pipelines.

---

## 1. Product decision

### 1.1 Initial customer

Start with **one company containing multiple invited users**.

Do not start with a public self-service multi-tenant platform. Treat each company as one tenant.

```text
Company / tenant
  ├── one DuckDB server process
  ├── one DuckLake catalog
  ├── one storage bucket
  ├── multiple invited users
  └── multiple ingestion pipelines
```

### 1.2 Customer promise

Use this positioning:

> Reliable business reporting for small companies without a dedicated data team.

The service connects a company’s existing tools, cleans and models the data, and delivers reports and answers that the company can use.

### 1.3 Initial deliverables

Offer:

- CSV and Parquet uploads
- A small number of supported API or database sources
- Daily or hourly batch refreshes
- Clean raw, staging, and curated tables
- One recurring dashboard or report
- Basic data-quality checks
- Human support from the operator

Do not promise initially:

- Real-time streaming
- High availability
- Unlimited custom connectors
- Public unrestricted SQL access
- Kubernetes-scale elasticity
- A replacement for a full enterprise data department

### 1.4 Commercial model

Use a productized service rather than unlimited consulting:

1. Paid setup or pilot.
2. Monthly managed service fee.
3. Explicit limits on data sources, refresh frequency, storage, and support.
4. Paid custom connectors, reports, or analysis.

The first sale should be a small, defined pilot:

> Connect up to three sources and deliver one reliable business report.

---

## 2. Current repository and what it already does

Read these files before changing the repository:

- `openwiki/quickstart.md` — startup and validation.
- `openwiki/architecture.md` — service ownership and storage boundaries.
- `openwiki/workflows.md` — smoke testing and load generation.
- `compose.yaml` — current local infrastructure.
- `docker/duckdb/server-entrypoint` — DuckDB, DuckLake, S3, and Quack bootstrap.
- `scripts/smoke-test` — end-to-end persistence check.
- `scripts/generate-load` — server-side batch ingestion example.
- `docker/duckdb/Dockerfile` — server image assembly.
- `.env.example` — configuration contract.

### 2.1 Current architecture

```text
Host DuckDB client
        │ Quack/HTTP
        ▼
duckdb-server
        ├── DuckLake catalog: /catalog/db.duckdb
        └── Parquet data: RustFS S3
```

The current repository is a local simulation, not a SaaS application. It has:

- One static DuckDB catalog file.
- One static S3 bucket.
- One global Quack token.
- One DuckDB server process.
- No users or tenants.
- No API or web application.
- No ingestion scheduler.
- No pipeline metadata store.
- No billing, quotas, or customer support workflow.
- No unit-test suite or CI configuration.

### 2.2 Important existing boundary

Only the `duckdb-server` process opens the catalog. Client scripts connect through Quack.

Preserve this boundary for pipeline jobs. Pipeline workers must not mount or directly open tenant catalog files.

### 2.3 Current local limitations

The current Compose setup intentionally uses:

- `disable_ssl: true`
- A configurable static Quack token
- `allow_other_hostname: true`
- Single-node RustFS
- A single catalog volume

These are acceptable for local simulation only. They are not a production SaaS security model.

---

## 3. Target architecture by stage

Do not build the final architecture before validating the service.

### Stage A — local development

Use the current Compose stack:

```text
docker compose
  ├── RustFS
  ├── bucket-init
  └── duckdb-server
```

Purpose:

- Develop DuckLake SQL.
- Test ingestion behavior.
- Validate persistence and restart behavior.
- Run smoke tests.

### Stage B — first paid pilot

Use one reliable VM and one tenant environment:

```text
One VM
  ├── Reverse proxy with TLS
  ├── API or admin service
  ├── Current DuckDB/RustFS Compose stack
  ├── Pipeline runner
  └── Monitoring and backup jobs
```

The first customer can be manually provisioned. Automate only repeatable steps.

### Stage C — a few customers

Use one isolated DuckDB environment per company:

```text
Shared host or small fleet
  ├── tenant-a DuckDB server + catalog-a
  ├── tenant-b DuckDB server + catalog-b
  └── tenant-c DuckDB server + catalog-c
```

Prefer shared managed S3/R2 with one bucket per tenant. Keep the tenant DuckDB process separate.

The provisioning unit is a **tenant/company**, not an individual user.

### Stage D — growth

Only after manual provisioning becomes painful:

```text
Control plane
  ├── PostgreSQL tenant database
  ├── provisioning worker
  ├── API gateway
  └── monitoring

Tenant workloads
  ├── one DuckDB Deployment per tenant
  ├── one persistent catalog volume per tenant
  └── one storage bucket per tenant
```

Use managed Kubernetes if multiple hosts, rescheduling, quotas, and automated lifecycle become necessary.

Do not use OpenShift unless a customer or hosting environment specifically requires it.

Use Terraform for long-lived cloud infrastructure, not for individual customer signups.

---

## 4. Data pipeline design

The first pipeline architecture should be boring and batch-oriented:

```text
Source API / database / file
        ▼
Python ingestion job
        ▼
Raw JSON, CSV, or Parquet in object storage
        ▼
Controlled SQL sent through Quack
        ▼
DuckLake raw tables
        ▼
Versioned SQL transformations
        ▼
Staging and curated business tables
        ▼
Reports, dashboards, or API responses
```

### 4.1 Recommended tools

| Need | Initial choice |
|---|---|
| API and database connectors | Python |
| API pagination and incremental loading | `dlt` where useful; small custom connectors otherwise |
| Landing zone | S3-compatible object storage |
| Lakehouse | Existing DuckDB + DuckLake server |
| Remote loading | DuckDB SQL through Quack |
| Transformations | Versioned SQL files |
| Scheduling | `systemd` timers or cron |
| Pipeline state | PostgreSQL or a small control database |
| Alerts | Email or Slack |

Do not start with Kafka, Airflow, a large connector platform, or Kubernetes jobs.

If many source types are required quickly, evaluate a managed connector service such as Airbyte Cloud instead of operating a large self-hosted platform.

### 4.2 Required pipeline behavior

Every pipeline must have:

- A source cursor or watermark.
- Retry behavior.
- Idempotent loads.
- Raw-file retention for replay.
- Row-count checks.
- Freshness checks.
- Null and duplicate checks where relevant.
- A run status and error message.
- A notification on failure.

### 4.3 Data layers

Use a consistent three-layer convention:

```text
raw       Immutable source-shaped data
staging   Cleaned and typed source data
curated   Business-ready tables and metrics
```

Do not overwrite raw data unless the customer explicitly accepts that behavior.

### 4.4 First supported sources

Choose sources based on the first customer’s real systems. Start with no more than three:

- File upload: CSV or Parquet.
- One common SaaS API.
- One database source such as PostgreSQL or MySQL.

Add a connector only when it supports a paying customer or a repeated sales opportunity.

---

## 5. Customer-facing service

### 5.1 Do not expose raw Quack

The current Quack endpoint exposes the server’s broad SQL surface. Never expose it directly to an untrusted customer in production.

Use one of these approaches:

- A small API that exposes approved operations.
- A trusted internal reporting tool.
- A private, tenant-scoped gateway with strict authorization.

The API must resolve the authenticated user to a tenant before any query or pipeline action.

### 5.2 Initial customer experience

For the pilot, the customer needs:

1. A secure way to provide source credentials or upload files.
2. A status page for pipeline freshness.
3. A report or dashboard.
4. A way to request changes or ask questions.
5. A clear support contact.

Do not build a large frontend before one customer uses the workflow.

### 5.3 Landing page message

Use plain business language:

> Stop building weekly reports by hand.
>
> We connect your business tools, clean the data, and deliver reliable reports without requiring a dedicated data team.

Primary call to action:

> Book a 30-minute data workflow review.

Do not lead with DuckDB, DuckLake, S3, or Kubernetes.

---

## 6. One-person operating model

### 6.1 Weekly customer workflow

1. Review pipeline health and freshness.
2. Check failed or suspicious loads.
3. Review one customer report or dashboard.
4. Confirm upcoming source or metric changes.
5. Send a short customer update.

### 6.2 Onboarding workflow

1. Identify the customer’s key business decisions.
2. Document sources, owners, credentials, refresh needs, and metrics.
3. Define the pilot report before connecting everything.
4. Provision one tenant environment.
5. Run an initial full load.
6. Add incremental refresh behavior.
7. Validate the report with the customer.
8. Start the recurring service schedule.

### 6.3 Support boundaries

Document:

- Supported sources.
- Refresh schedule.
- Support hours.
- Expected response time.
- Data retention.
- Backup policy.
- What counts as a custom request.

Do not silently absorb unlimited customer-specific engineering work.

---

## 7. Security and data protection

Minimum production rules:

- TLS for all customer-facing traffic.
- Quack private to the internal network.
- Separate tenant catalog files.
- Separate tenant storage buckets or tightly restricted prefixes.
- Separate tenant credentials.
- Secrets stored in a secret manager, not committed `.env` files.
- No customer-controlled strings interpolated into SQL or filesystem paths without validation.
- No direct catalog mounts for API or pipeline workers.
- Backups tested by restoring them.
- Audit pipeline runs and administrative actions.
- Confirm destructive operations before execution.

The current local token and disabled SSL settings must not be copied into production unchanged.

---

## 8. Reliability and backup policy

### 8.1 What must be backed up

- DuckLake catalog file.
- Raw landing files.
- Curated Parquet data.
- Pipeline configuration.
- SQL transformations.
- Tenant configuration and credentials metadata.

### 8.2 Restore test

A backup is not trusted until it has been restored successfully.

The restore procedure should:

1. Stop writes.
2. Restore the catalog to a new location.
3. Restore or verify object data.
4. Start a temporary DuckDB server.
5. Run a row-count and sample-query check.
6. Record the result.

Never use `docker compose down -v` on a production environment.

---

## 9. Agent team structure

Use AI agents as specialists with small, bounded tasks. One lead agent owns integration and final review.

### Agent 1 — Lead / architect

Owns:

- Repository context.
- Decisions and trade-offs.
- Cross-agent integration.
- Architecture records.
- Final acceptance.

Must read:

- `AGENTS.md`
- `openwiki/quickstart.md`
- `openwiki/architecture.md`
- `openwiki/workflows.md`
- `PLAYBOOK.md`

### Agent 2 — Product and customer

Owns:

- ICP.
- Pilot definition.
- Supported sources.
- Report deliverables.
- Landing-page and outreach copy.
- Customer onboarding checklist.

Must not change infrastructure code.

### Agent 3 — Platform and security

Owns:

- Compose changes.
- Container images.
- Secrets handling.
- Tenant environment boundaries.
- TLS and private networking.
- Backup and restore runbooks.

Must preserve single-writer catalog ownership.

### Agent 4 — Pipeline engineer

Owns:

- Source connector contracts.
- Raw landing format.
- Incremental state.
- Pipeline retries and idempotency.
- SQL transformation runner.
- Pipeline quality checks.

Must connect through Quack rather than opening catalog files.

### Agent 5 — API/application engineer

Owns:

- Authentication.
- Tenant lookup.
- Approved query and report API.
- Pipeline status API.
- Admin provisioning interface.

Must not expose unrestricted Quack to customers.

### Agent 6 — QA/release/operations

Owns:

- Smoke tests.
- Tenant isolation tests.
- Pipeline failure tests.
- Restore tests.
- Release checklist.
- Incident runbooks.

No change is complete without a reproducible validation command.

---

## 10. AI agent working rules

Every agent task must include:

```text
Objective:
Relevant files:
Files allowed to change:
Files explicitly off-limits:
Acceptance checks:
Known assumptions:
Rollback or failure plan:
```

Agents must:

1. Read the relevant OpenWiki documentation first.
2. Inspect existing code before proposing new abstractions.
3. Make the smallest change that satisfies the task.
4. Avoid adding dependencies without a specific need.
5. Run focused validation after changes.
6. Report changed files, checks run, and remaining risks.
7. Never modify another agent’s owned files without coordination.

The lead agent merges work only after acceptance checks pass.

---

## 11. Phased implementation plan

### Phase 0 — validate the offer

Deliverables:

- One selected customer niche.
- One pilot customer profile.
- Three supported sources.
- One recurring report.
- Pilot scope and pricing.
- Landing page copy.

Exit condition:

- At least one real customer agrees to the pilot or provides representative data.

### Phase 1 — harden the current demo

Deliverables:

- Reproducible local startup.
- Passing smoke test.
- Documented backup and restore.
- Production-safe configuration checklist.
- No public direct Quack exposure.

Validation:

```bash
sh -n scripts/smoke-test scripts/generate-load docker/duckdb/server-entrypoint
docker compose config --quiet
scripts/smoke-test
```

The Docker command requires Docker Desktop WSL integration or an available Docker Engine.

### Phase 2 — build the first pipeline

Deliverables:

- One source connector.
- Raw landing files.
- Incremental state.
- Remote DuckDB load through Quack.
- Staging and curated SQL.
- Freshness and row-count checks.
- Failure notification.

Exit condition:

- The pipeline can be stopped, retried, and rerun without duplicating customer data.

### Phase 3 — deliver the pilot

Deliverables:

- Tenant environment.
- Customer access path.
- One report or dashboard.
- Onboarding documentation.
- Support process.
- Weekly operating checklist.

Exit condition:

- Customer can use the report and you can operate it without manual database repair.

### Phase 4 — repeat provisioning

Only after the first pilot works:

- Create a tenant configuration format.
- Add a provisioning script.
- Add tenant health checks.
- Add backup automation.
- Add destroy/archive workflow with confirmation.
- Add an admin-only status view.

### Phase 5 — self-service and orchestration

Only when manual operations are a proven bottleneck:

- Add control-plane PostgreSQL tables.
- Add a provisioning worker.
- Add API-driven tenant lifecycle.
- Add per-tenant resource limits.
- Evaluate managed Kubernetes.
- Use Terraform for base cloud infrastructure.

Do not start this phase because it feels architecturally complete. Start it because real customer volume requires it.

---

## 12. Release checklist

Before a release:

- `git diff` reviewed.
- Shell syntax checked.
- Compose configuration checked.
- Smoke test passed.
- Restart persistence checked.
- Pipeline retry behavior checked.
- Tenant access boundary checked.
- Backup/restore status known.
- `.env` and credentials excluded from Git.
- Customer-facing change documented.

Before a destructive operation:

- Confirm the tenant and target.
- Confirm the backup exists.
- Confirm the restore path.
- Ask for explicit approval when customer data could be deleted.

---

## 13. Success metrics

Track only metrics that guide decisions:

- Time from signed pilot to first useful report.
- Pipeline success rate.
- Report freshness.
- Manual operator hours per customer per week.
- Number of recurring support issues.
- Customer retention or renewal.
- Gross infrastructure cost per tenant.

The key scaling signal is **operator hours per customer**, not container count.

When a customer takes more operator time than the monthly service supports, either standardize the work, raise the price, or decline the custom request.

---

## 14. Immediate next actions

1. Choose one customer niche.
2. Define one paid pilot and one report.
3. Select three initial source types.
4. Run the current stack locally and pass `scripts/smoke-test`.
5. Build one complete ingestion-to-report path.
6. Talk to customers before building Kubernetes or self-service provisioning.

The first objective is not a multi-tenant platform. It is one repeatable customer outcome.
