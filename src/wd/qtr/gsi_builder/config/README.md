# Configuration Management

Environment-specific configurations use AWS Secrets Manager for credential management.

## Usage

```bash
export ENV=dit  # or fit/iat/prod
```

Each environment contains Redshift, Kafka, S3, app and optional PostgreSQL settings.
Splunk HEC tokens are intentionally read from environment variables:

- `DIT_SPLUNK_HEC_TOKEN`
- `FIT_SPLUNK_HEC_TOKEN`
- `IAT_SPLUNK_HEC_TOKEN`
- `PROD_SPLUNK_HEC_TOKEN`

For local import-only testing, set `GSI_ALLOW_MISSING_SECRETS=true` to avoid failing when AWS Secrets Manager is unavailable.
