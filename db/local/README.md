# Local Database Setup

This folder provides a local database sandbox for the `wd-qtr-gsi-builder` project.

It creates two local PostgreSQL containers:

| Service | Local Port | Purpose |
|---------|------------|---------|
| `onetax-redshift-local` | `5439` | Redshift-style operational schema: workers, tax snapshots, organization units, outbound files, and error tables. |
| `onetax-metadata-local` | `55432` | PostgreSQL metadata schema: GI1/GI2 GSI metadata tables. |

Important limitation: this is a **local schema sandbox**, not a full AWS Redshift emulator. The production job uses Redshift JDBC behavior. Local PostgreSQL is useful for understanding tables, developing queries, and testing future design logic, but the current Spark job is not fully wired for local PostgreSQL execution.

## Start The Databases

Start Docker Desktop first. Then run this from the repository root:

```bash
docker compose -f db/local/docker-compose.yml up -d
```

Check health:

```bash
docker compose -f db/local/docker-compose.yml ps
```

## Connect From IntelliJ

Use IntelliJ's Database tool window and add two PostgreSQL data sources:

| Name | Host | Port | Database | User | Password |
|------|------|------|----------|------|----------|
| `onetax-redshift-local` | `localhost` | `5439` | `onetax` | `onetax` | `onetax` |
| `onetax-metadata-local` | `localhost` | `55432` | `onetax_metadata` | `onetax` | `onetax` |

After connecting, set the default schema to `onetax` or run `SET search_path TO onetax, public;`.

## Connect To The Operational Database

Use Docker exec, so you do not need local `psql` installed:

```bash
docker exec -it onetax-redshift-local psql -U onetax -d onetax
```

Useful checks:

```sql
SET search_path TO onetax, public;

SELECT * FROM outbound_file;
SELECT * FROM organization_unit;
SELECT worker_sk, branch_code, company_code, given_name, family_name FROM worker;
SELECT worker_sk, jurisdiction, tax_type
FROM (
  SELECT
    wt.worker_sk,
    CASE
      WHEN wt.state_code IS NULL THEN 'F'
      WHEN wt.local_code IS NULL THEN wt.state_code
      ELSE wt.state_code || RIGHT(wt.local_code, 4)
    END AS jurisdiction,
    wt.tax_type
  FROM worker_tax_qtr_snapshot wt
) q;
SELECT ce.*, ec.category, ec.impacts_deposit, ec.impacts_filing
FROM company_errors ce
JOIN error_catalog ec ON ce.error_code = ec.error_code;
```

## Connect To The Metadata Database

```bash
docker exec -it onetax-metadata-local psql -U onetax -d onetax_metadata
```

Useful checks:

```sql
SET search_path TO onetax, public;

SELECT COUNT(*) FROM GI1;
SELECT * FROM GI2 ORDER BY field_code;
```

## Reset The Databases

This deletes local data and recreates from the init scripts:

```bash
docker compose -f db/local/docker-compose.yml down -v
docker compose -f db/local/docker-compose.yml up -d
```

## What Tables Are Included

Operational database:

- `onetax.organization_unit`
- `onetax.worker`
- `onetax.worker_address`
- `onetax.worker_tax_qtr_snapshot`
- `onetax.worker_tax_profile`
- `onetax.outbound_file`
- `onetax.error_catalog`
- `onetax.company_errors`

Metadata database:

- `onetax.GI1`
- `onetax.GI2`

## How This Maps To The Code

| Code Function | Local Table(s) |
|---------------|----------------|
| `RedshiftConnection.query_queued_outbound_files()` | `outbound_file` |
| `RedshiftConnection.query_site_organizations()` | `organization_unit` |
| `RedshiftConnection.query_workers()` | `worker`, `worker_address`, `worker_tax_qtr_snapshot` |
| `RedshiftConnection.query_all_worker_tax()` | `worker_tax_qtr_snapshot`, `worker`, `worker_tax_profile` |
| `PostgresConnection.query_gsi_field_mappings()` | `GI1` |
| `PostgresConnection.query_gsi_level_mappings()` | `GI2` |
| Future error skip design | `company_errors`, `error_catalog` |

## Suggested Local Environment Values

For future local wiring, the database values are:

Operational database:

- host: `localhost`
- port: `5439`
- database: `onetax`
- schema: `onetax`
- username: `onetax`
- password: `onetax`

Metadata database:

- host: `localhost`
- port: `55432`
- database: `onetax_metadata`
- schema: `onetax`
- username: `onetax`
- password: `onetax`

## Production Reality

Production-like environments use:

- AWS Secrets Manager for credentials
- Redshift for operational worker/tax/outbound data
- PostgreSQL metadata access for GI1/GI2
- Databricks Volumes for output

This local setup gives you a complete table model and seed data for development discussions and design work, but it does not replace the real AWS/Databricks database setup.
