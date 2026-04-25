# WD Quarterly GSI Builder

PySpark application for processing quarterly employee data and generating GSI files.

## Description

This application processes quarterly worker data from Redshift and generates GSI (General System Interface) files for tax reporting purposes.

## Features

- Processes quarterly employee data
- Generates GSI formatted output files
- Supports multiple environments: `dit`, `fit`, `iat`, `prod`
- AWS Secrets Manager integration for runtime credentials
- Databricks job deployment through Terraform
- S3/Databricks Volume output storage

## IntelliJ Import

Open this repository as an existing project in IntelliJ IDEA. The included `wd-qtr-gsi-builder.iml` marks `src` as a source folder.

## Installation

```bash
poetry install --with dev
```

or:

```bash
pip install -r requirements.txt
```

## Usage

The application is designed to run in Databricks environments with proper AWS and Databricks configuration.

```bash
export ENV=dit
poetry run main
```
