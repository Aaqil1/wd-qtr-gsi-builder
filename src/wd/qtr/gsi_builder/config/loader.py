import importlib
import os

ALLOWED_ENVS = {"dit", "fit", "iat", "prod"}


def get_config(env=None):
    """Load configuration for specified environment."""
    if env is None:
        env = os.getenv("ENV", "dit").lower()

    if env not in ALLOWED_ENVS:
        raise ValueError(f"Invalid environment: {env}. Allowed: {ALLOWED_ENVS}")

    module = importlib.import_module(f"wd.qtr.gsi_builder.config.{env}")

    if not hasattr(module, env):
        raise ValueError(f"Configuration variable '{env}' not found in config module")

    return getattr(module, env)


def get_spark_config(config):
    """Get Spark configuration with Redshift settings."""
    base_config = {
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.coalescePartitions.enabled": "true",
        "spark.jars.packages": "io.github.spark-redshift-community:spark-redshift_2.12:6.2.0",
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.aws.credentials.provider": "com.amazonaws.auth.DefaultAWSCredentialsProviderChain",
        "spark.sql.execution.arrow.pyspark.enabled": "true",
    }

    try:
        if "redshift" in config and "temp_s3_path" in config["redshift"]:
            base_config["spark.hadoop.fs.s3a.bucket"] = config["s3"]["bucket"]
            base_config["spark.hadoop.fs.s3a.endpoint"] = (
                f"s3.{config['s3']['region']}.amazonaws.com"
            )
    except (KeyError, TypeError):
        pass

    return base_config
