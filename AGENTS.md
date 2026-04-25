# Project Notes

This repository contains the `wd-qtr-gsi-builder` PySpark/Databricks project.

## Layout

- `src/wd/qtr/gsi_builder`: application source package
- `src/wd/qtr/gsi_builder/config`: environment-specific runtime config
- `params`: deployment YAML, Terraform and environment tfvars
- `tests`: pytest tests

## Local Development

Use Python 3.11 and Poetry when available:

```bash
poetry install --with dev
poetry run pytest
```

The application is intended to run in Databricks with AWS Secrets Manager access for environment credentials.
