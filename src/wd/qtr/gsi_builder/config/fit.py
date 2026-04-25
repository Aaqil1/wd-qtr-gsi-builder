import json
import os

import boto3

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)

REGION = os.getenv("AWS_REGION", "us-east-1")
REDSHIFT_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:172116238148:secret:onetax-redshift-appuser-60FjdC"
POSTGRES_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:172116238148:secret:onetax-rds-user-fit-bf7wdZ"
SERVICE_CREDENTIAL_NAME = "service-cred-scs-n8-dev-fit"


def _get_secret(secret_arn):
    try:
        from pyspark.dbutils import DBUtils
        from pyspark.sql import SparkSession

        spark = SparkSession.getActiveSession()
        if spark:
            dbutils = DBUtils(spark)
            boto3_session = boto3.Session(
                botocore_session=dbutils.credentials.getServiceCredentialsProvider(
                    SERVICE_CREDENTIAL_NAME
                ),
                region_name=REGION,
            )
            sm = boto3_session.client("secretsmanager")
            response = sm.get_secret_value(SecretId=secret_arn)
            return json.loads(response["SecretString"])
    except Exception as e:
        logger.warning(f"Service credentials secret fetch failed: {e}")

    try:
        client = boto3.client("secretsmanager", region_name=REGION)
        response = client.get_secret_value(SecretId=secret_arn)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.error(f"Regular boto3 secret fetch failed: {e}")
        return None


def get_redshift_credentials():
    return _get_secret(REDSHIFT_SECRET_ARN)


def get_postgres_secret():
    return _get_secret(POSTGRES_SECRET_ARN)


creds = get_redshift_credentials()
if not creds:
    if os.getenv("GSI_ALLOW_MISSING_SECRETS", "false").lower() == "true":
        creds = {
            "host": "localhost",
            "port": 5439,
            "dbname": "onetax",
            "schemaname": "onetax",
            "username": "local",
            "password": "local",
        }
    else:
        raise RuntimeError("Failed to retrieve Redshift credentials from Secrets Manager")

redshift_secret = {
    "host": creds["host"],
    "port": str(creds["port"]),
    "database": creds["dbname"],
    "schema": creds["schemaname"],
    "username": creds["username"],
    "password": creds["password"],
}

kafka_secret = {
    "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "csinternet-fit-confluent-kafka.cs.oneadp.com:9092"),
    "username": os.getenv("KAFKA_USERNAME"),
    "password": os.getenv("KAFKA_PASSWORD"),
}

fit = {
    "api": {
        "base_url": "https://scp-tax-filing-fit.cs.oneadp.com",
        "endpoint": "/wd-payroll-tax-code-mapping/api/v1/tax-code-mappings/gsi-code",
        "source_type": "quarter",
    },
    "redshift": {
        "host": redshift_secret["host"],
        "port": int(redshift_secret["port"]),
        "database": redshift_secret["database"],
        "schema": redshift_secret["schema"],
        "user": redshift_secret["username"],
        "password": redshift_secret["password"],
        "iam_role": "arn:aws:iam::377284622922:role/RedshiftS3AccessRole",
        "temp_s3_path": "redshift-unload-temp",
    },
    "s3": {
        "bucket": "wd-qtr-gsi-bucket-fit",
        "results_path": "quarterly-results",
        "region": REGION,
        "volume_path": "/Volumes/onedata_us_east_1_shared_fit/ssot_raw_scs_n8_fit/wd-quarter-outbound-fit/",
    },
    "kafka": {
        "bootstrap_servers": kafka_secret["bootstrap_servers"],
        "input_topic": "avs.document.authorizationdocumentupload",
        "output_topic": "qtr-gsi-events-fit",
        "consumer_group": "wd-qtr-gsi-consumer-group-fit",
        "checkpoint_location": "/tmp/kafka_checkpoints_fit",
        "security_protocol": kafka_secret.get("security_protocol", "SASL_SSL"),
        "sasl_mechanism": kafka_secret.get("sasl_mechanism", "PLAIN"),
        "sasl_username": kafka_secret.get("username"),
        "sasl_password": kafka_secret.get("password"),
    },
    "app": {
        "name": "WD_QTR_GSI_Builder_FIT",
        "max_parallel_tasks": 50,
        "batch_size": 50,
        "max_workers": 25,
    },
    "splunk": {
        "hec_url": "https://http-inputs-adpdev.splunkcloud.com/services/collector/event",
        "hec_token": os.getenv("FIT_SPLUNK_HEC_TOKEN", ""),
        "index": "onetax_main",
    },
}

postgres_secret = get_postgres_secret()
if postgres_secret:
    fit["postgres"] = {
        "host": "onetax-fitclus.cluster-ro-cbymtpu9qype.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "database": "onetax_s01",
        "schema": "onetax",
        "user": postgres_secret.get("onetax-db-username", postgres_secret.get("user", postgres_secret.get("username"))),
        "password": postgres_secret.get("onetax-db-password", postgres_secret.get("password")),
    }
