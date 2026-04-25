# Databricks notebook source
import os
import time
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql.functions import array, col, concat, explode, lit

from wd.qtr.gsi_builder.config.loader import get_config, get_spark_config
from wd.qtr.gsi_builder.db_connection import PostgresConnection, RedshiftConnection
from wd.qtr.gsi_builder.email_notifier import EmailNotifier
from wd.qtr.gsi_builder.flow_validator import validate_config
from wd.qtr.gsi_builder.gsi_formatter import apply_gsi_mappings, format_tax_data_df
from wd.qtr.gsi_builder.gsi_mappings import load_mappings
from wd.qtr.gsi_builder.logger import Logger, MDC
from wd.qtr.gsi_builder.mandatory_fields_validator import (
    ensure_mandatory_fields,
    log_mandatory_fields_summary,
    validate_mandatory_fields,
)
from wd.qtr.gsi_builder.outbound_file_status import OutboundFileStatus
from wd.qtr.gsi_builder.s3_writer import S3Writer

try:
    config = get_config()
    validate_config(config)
    Logger.initialize(config)
    logger = Logger.get_logger(__name__)
    logger.info(f"Loaded configuration for environment: {os.getenv('ENV', 'dit').upper()}")
except Exception as e:
    print(f"Failed to load configuration: {e}")
    raise

try:
    from wd.qtr.gsi_builder.cache_utils import clear_all_caches

    clear_all_caches()
    logger.info("Cleared all caches at job startup")
except Exception as e:
    logger.warning(f"Failed to clear caches at startup: {e}")

spark_configs = get_spark_config(config)
spark_builder = SparkSession.builder.appName(config["app"]["name"])
for key, value in spark_configs.items():
    spark_builder = spark_builder.config(key, value)

spark = spark_builder.getOrCreate()
PROGRAM_START_TIME = datetime.now(timezone.utc)
logger.info(f"Spark session created at {PROGRAM_START_TIME.strftime('%Y-%m-%d %H:%M:%S')}")

try:
    db_conn = RedshiftConnection(
        spark,
        config["redshift"]["host"],
        config["redshift"]["port"],
        config["redshift"]["database"],
        config["redshift"]["schema"],
        config["redshift"]["user"],
        config["redshift"]["password"],
    )

    pg_conn = None
    if "postgres" in config:
        try:
            pg_conn = PostgresConnection(
                spark,
                config["postgres"]["host"],
                config["postgres"]["port"],
                config["postgres"]["database"],
                config["postgres"]["schema"],
                config["postgres"]["user"],
                config["postgres"]["password"],
            )
            logger.info("Postgres connection initialized")
            try:
                gi1_count = pg_conn.query_table_count("onetax.GI1")
                logger.info(f"Postgres onetax.GI1 row count: {gi1_count}")
            except Exception as e:
                logger.warning(f"Could not query onetax.GI1: {e}")
        except Exception as e:
            logger.warning(f"Failed to initialize Postgres connection, skipping postgres operations: {e}")
    else:
        logger.warning("Postgres config not available, skipping postgres operations")

    s3_writer = S3Writer(spark, config["s3"]["volume_path"], PROGRAM_START_TIME)
    email_notifier = EmailNotifier()
    logger.info("All modules initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize modules: {e}")
    raise


def get_job_url():
    """Get Databricks job URL from environment/context."""
    workspace_url = None
    job_id = None
    run_id = None
    try:
        try:
            from dbruntime.databricks_repl_context import get_context

            ctx = get_context()
            workspace_url = getattr(ctx, "browserHostName", None) or getattr(ctx, "workspaceUrl", None)
            job_id = getattr(ctx, "jobId", None) or getattr(ctx, "job_id", None)
            run_id = getattr(ctx, "currentRunId", None) or getattr(ctx, "runId", None) or getattr(ctx, "run_id", None)
        except Exception as ctx_error:
            logger.info(f"Context error: {ctx_error}")

        workspace_url = workspace_url or os.getenv("DATABRICKS_WORKSPACE_URL", "")
        job_id = job_id or os.getenv("DATABRICKS_JOB_ID", "")
        run_id = run_id or os.getenv("DATABRICKS_RUN_ID", "")

        if job_id:
            MDC.put("jobId", str(job_id))
        if run_id:
            MDC.put("runId", str(run_id))

        logger.info(
            f"Databricks Environment - Workspace: {workspace_url or 'N/A'}, Job ID: {job_id or 'N/A'}, Run ID: {run_id or 'N/A'}"
        )
        if workspace_url and job_id and run_id:
            return f"https://{workspace_url}/#job/{job_id}/run/{run_id}"
    except Exception as e:
        logger.warning(f"Could not retrieve job URL: {e}")
    return None


def process_site_event(batch_id, site_id, year, quarter, window_start, window_end, gsi_mappings, address_mappings):
    """Process site event and generate one GSI file per site with all companies."""
    event_start = datetime.now(timezone.utc)
    env = os.getenv("ENV", "dit").upper()
    job_url = get_job_url()
    event = {"site_id": site_id, "year": year, "quarter": quarter}
    logger.info(f"Started Processing Site: {site_id}, Year: {year}, Quarter: {quarter}")

    try:
        db_conn.update_outbound_file_status(batch_id, site_id, year, quarter, OutboundFileStatus.GENERATING)
        file_name = f"GSI_{site_id}_{year}_Q{quarter}.txt"
        org_df = db_conn.query_site_organizations([site_id])
        companies = org_df.select("branch_code", "company_code").distinct().orderBy("branch_code", "company_code").collect()
        if not companies:
            raise Exception(f"No companies found for site_id: {site_id}")

        all_worker_lines = []
        all_tax_lines = []
        total_record_count = 0

        for idx, company_row in enumerate(companies, 1):
            branch_code = company_row["branch_code"]
            company_code = company_row["company_code"]
            company_start_time = time.time()
            logger.info(f"[{idx}/{len(companies)}] Processing branch: {branch_code}, company: {company_code}")

            try:
                df = db_conn.query_workers(branch_code, company_code, year, quarter)
                if df is None or df.isEmpty():
                    logger.warning(f"No workers found for {branch_code}/{company_code}")
                    continue
            except Exception as e:
                logger.error(f"Worker query failed for {branch_code}/{company_code}: {e}")
                continue

            try:
                df_gsi, level_cols = apply_gsi_mappings(df, gsi_mappings, address_mappings)
            except Exception as e:
                logger.error(f"GSI mapping failed for {branch_code}/{company_code}: {e}")
                continue

            available_gsi_cols = [
                metadata["gsi_code"]
                for field, metadata in gsi_mappings.items()
                if field in df_gsi.columns and metadata.get("gsi_level", "EE") == "EE"
            ]
            available_addr_cols = []
            for field, type_mappings in address_mappings.items():
                for addr_type in ["Work", "Home"]:
                    col_name = f"{addr_type.lower()}_{field}"
                    if col_name in df.columns and addr_type in type_mappings:
                        metadata = type_mappings[addr_type]
                        if metadata.get("gsi_level", "EE") == "EE":
                            available_addr_cols.append(metadata["gsi_code"])

            all_gsi_columns = available_gsi_cols + available_addr_cols
            worker_level_df = None
            fsl_levels = {lvl: cols for lvl, cols in level_cols.items() if lvl in ("F", "S", "L") and cols}
            if fsl_levels:
                from functools import reduce as functools_reduce
                from pyspark.sql import DataFrame as SparkDF
                from pyspark.sql.functions import array as spark_array

                level_dfs = []
                for lvl, cols_list in fsl_levels.items():
                    valid_cols = [c for c in cols_list if c in df_gsi.columns]
                    if valid_cols:
                        lvl_df = df_gsi.select(
                            col("worker_sk"),
                            lit(lvl).alias("level_type"),
                            spark_array(*[col(c) for c in valid_cols]).alias("level_gsi_fields"),
                        )
                        level_dfs.append(lvl_df)
                if level_dfs:
                    worker_level_df = functools_reduce(SparkDF.union, level_dfs)

            if all_gsi_columns:
                df_gsi = df_gsi.withColumn("gsi_fields_array", array(*all_gsi_columns))
                from wd.qtr.gsi_builder.gsi_formatter import build_employee_lines_udf

                build_lines_udf = build_employee_lines_udf()
                df_gsi = df_gsi.withColumn("emp_lines_array", build_lines_udf(col("gsi_fields_array")))
            else:
                df_gsi = df_gsi.withColumn("emp_lines_array", array(lit("******      ")))

            df_gsi = df_gsi.select(
                col("worker_sk"), col("branch_code"), col("company_code"), explode(col("emp_lines_array")).alias("emp_line")
            )
            all_worker_lines.append(df_gsi)

            try:
                tax_df = db_conn.query_all_worker_tax(company_code, year, quarter)
                if tax_df is not None and not tax_df.isEmpty():
                    try:
                        tax_df_validated, validation_results = validate_mandatory_fields(tax_df, df)
                        log_mandatory_fields_summary(validation_results)
                        tax_df_with_mandatory = ensure_mandatory_fields(tax_df_validated, df)
                        tax_formatted = format_tax_data_df(tax_df_with_mandatory, worker_level_df)
                    except Exception as mf_error:
                        logger.warning(f"Mandatory fields processing failed: {mf_error}")
                        tax_formatted = format_tax_data_df(tax_df, worker_level_df)
                    tax_formatted = tax_formatted.join(
                        df.select("worker_sk", "branch_code", "company_code"), "worker_sk", "left"
                    )
                    all_tax_lines.append(tax_formatted)
            except Exception as e:
                logger.error(f"Tax processing failed for {branch_code}/{company_code}: {e}")

            logger.info(f"[{idx}/{len(companies)}] Company {branch_code}/{company_code} completed in {time.time() - company_start_time:.2f}s")

        if not all_worker_lines:
            raise Exception(f"No worker data found for site: {site_id}")

        from functools import reduce
        from pyspark.sql import DataFrame

        worker_combined = reduce(DataFrame.union, all_worker_lines).withColumn("line_type", lit("worker"))
        worker_lines = worker_combined.select(
            col("worker_sk"), col("branch_code"), col("company_code"), col("emp_line").alias("value"), col("line_type")
        )

        if all_tax_lines:
            tax_combined = reduce(DataFrame.union, all_tax_lines).withColumn("line_type", lit("tax"))
            tax_lines = tax_combined.select(
                col("worker_sk"), col("branch_code"), col("company_code"), col("tax_line").alias("value"), col("line_type")
            )
            df_combined = worker_lines.union(tax_lines).orderBy(
                col("branch_code"), col("company_code"), col("worker_sk"), col("line_type").desc()
            )
        else:
            df_combined = worker_lines.orderBy(col("branch_code"), col("company_code"), col("worker_sk"))

        company_headers = (
            df_combined.select("branch_code", "company_code")
            .distinct()
            .withColumn("header_value", concat(lit("      "), col("branch_code"), col("company_code"), lit("10000NN             Y")))
            .withColumn("line_type", lit("header"))
            .withColumn("worker_sk", lit(-1))
            .select(col("header_value").alias("value"), col("branch_code"), col("company_code"), col("worker_sk"), col("line_type"))
        )

        df_combined = (
            company_headers.union(
                df_combined.select(col("value"), col("branch_code"), col("company_code"), col("worker_sk"), col("line_type"))
            )
            .orderBy(col("branch_code"), col("company_code"), col("worker_sk"), col("line_type").desc())
            .select("value")
        )

        file_header = s3_writer.generate_gsi_header(year, quarter)
        header_df = spark.createDataFrame([(file_header,)], ["value"])
        output_df = header_df.union(df_combined)
        final_count = output_df.count() + 1
        trailer_record = s3_writer.generate_trailer_record(final_count)
        trailer_df = spark.createDataFrame([(trailer_record,)], ["value"])
        output_df = output_df.union(trailer_df)
        final_count_with_trailer = output_df.count()

        output_file = s3_writer.write_gsi_dataframe(output_df, year, quarter, site_id)
        s3_key = f"worker-detail/{output_file.split('/')[-1]}" if output_file else f"worker-detail/{file_name}"
        db_conn.update_outbound_file_complete(batch_id, site_id, year, quarter, output_file, final_count_with_trailer, file_name, s3_key)

        processing_time = (datetime.now(timezone.utc) - event_start).total_seconds()
        email_notifier.send_notification(event_start, event, "SUCCESS", None, env, job_url)
        return {
            "site_id": site_id,
            "year": year,
            "quarter": quarter,
            "processed": True,
            "record_count": final_count_with_trailer,
            "output_file": output_file,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_time": processing_time,
            "message": f"Successfully processed {total_record_count} records for site {site_id} Q{quarter} {year} in {processing_time:.2f}s",
        }
    except Exception as e:
        error = str(e)
        logger.error(f"Exception processing site {site_id}: {error}")
        try:
            db_conn.update_outbound_file_status(batch_id, site_id, year, quarter, OutboundFileStatus.FAILED)
        except Exception as db_error:
            logger.error(f"Failed to update outbound_file failure status: {db_error}")
        processing_time = (datetime.now(timezone.utc) - event_start).total_seconds()
        email_notifier.send_notification(event_start, event, "FAILED", error, env, job_url)
        return {
            "site_id": site_id,
            "processed": False,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_time": processing_time,
        }


def main():
    """Main entry point: queries QUEUED records and processes sites in parallel."""
    from wd.qtr.gsi_builder.orchestrator import process_sites_parallel

    start = time.time()
    try:
        queued_df = db_conn.query_queued_outbound_files()
        queued_records = queued_df.collect()
        queued_df.unpersist()
        if not queued_records:
            logger.info("No queued files to process")
            return
        logger.info(f"Found {len(queued_records)} queued records")
        results = process_sites_parallel(spark, queued_records, db_conn, s3_writer, email_notifier)
        total_success = sum(1 for r in results if r.get("success"))
        logger.info(f"Completed: {total_success}/{len(queued_records)} sites succeeded in {time.time() - start:.2f}s")
    finally:
        db_conn.close_write_connection()


if __name__ == "__main__":
    main()
