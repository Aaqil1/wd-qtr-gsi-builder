"""Mandatory fields validator for GSI Builder."""

from pyspark.sql.functions import col, lit

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)


def _get_mandatory_field_configs():
    """Get mandatory field configurations from tax mappings."""
    try:
        from wd.qtr.gsi_builder.gsi_mappings import TAX_MAPPINGS

        mandatory_configs = {}
        for field_name, tax_types in TAX_MAPPINGS.items():
            for tax_type, config in tax_types.items():
                if config.get("mandatory", False):
                    mandatory_configs[config["gsi_code"]] = {
                        "field_name": field_name,
                        "tax_type": tax_type,
                        "gsi_code": config["gsi_code"],
                        "length": config.get("length", 12),
                        "decimal_places": config.get("decimal_places", 2),
                        "signed_indicator": config.get("signed_indicator", True),
                    }
        return mandatory_configs
    except Exception as e:
        logger.warning(f"TAX_MAPPINGS not available, using empty mandatory configs: {e}")
        return {}


def validate_mandatory_fields(tax_df, worker_df):
    """Validate that mandatory fields are present for every worker."""
    mandatory_configs = _get_mandatory_field_configs()
    if not mandatory_configs:
        logger.info("No mandatory fields configured")
        return tax_df, {"validation_passed": True, "total_workers": worker_df.count()}

    logger.info(f"Starting mandatory fields validation for: {list(mandatory_configs.keys())}")
    validation_results = {"total_workers": 0, "validation_passed": True}
    all_workers = worker_df.select("worker_sk").distinct().collect()
    validation_results["total_workers"] = len(all_workers)
    all_worker_sks = {row["worker_sk"] for row in all_workers}

    for gsi_code, config in mandatory_configs.items():
        field_name = config["field_name"]
        tax_type = config["tax_type"]
        if field_name == "qtd_amount":
            filter_condition = col("tax_type") == tax_type
        elif field_name == "ytd_amount":
            filter_condition = (col("tax_type") == tax_type) & (col("ytd_amount").isNotNull())
        else:
            filter_condition = (col("tax_type") == tax_type) & (col(field_name).isNotNull())
        workers_with_field = tax_df.filter(filter_condition).select("worker_sk").distinct()
        workers_with_field_set = {row["worker_sk"] for row in workers_with_field.collect()}
        workers_missing_field = list(all_worker_sks - workers_with_field_set)
        validation_results[f"workers_with_{gsi_code}"] = len(workers_with_field_set)
        validation_results[f"workers_missing_{gsi_code}"] = workers_missing_field
        logger.info(f"  {gsi_code} ({tax_type}): {len(workers_with_field_set)}/{len(all_workers)} workers")
        if workers_missing_field:
            validation_results["validation_passed"] = False
            logger.warning(f"  Missing {gsi_code}: {len(workers_missing_field)} workers")

    if validation_results["validation_passed"]:
        logger.info("Mandatory fields validation passed")
    else:
        logger.warning("Mandatory fields validation failed")
    return tax_df, validation_results


def ensure_mandatory_fields(tax_df, worker_df):
    """Add default records for missing mandatory fields."""
    mandatory_configs = _get_mandatory_field_configs()
    if not mandatory_configs:
        logger.info("No mandatory fields configured")
        return tax_df

    all_workers = worker_df.select("worker_sk").distinct()
    tax_columns = tax_df.columns

    for gsi_code, config in mandatory_configs.items():
        field_name = config["field_name"]
        tax_type = config["tax_type"]
        if field_name == "qtd_amount":
            filter_condition = col("tax_type") == tax_type
        elif field_name == "ytd_amount":
            filter_condition = (col("tax_type") == tax_type) & (col("ytd_amount").isNotNull())
        else:
            filter_condition = (col("tax_type") == tax_type) & (col(field_name).isNotNull())

        workers_with_field = tax_df.filter(filter_condition).select("worker_sk").distinct()
        workers_missing_field = all_workers.join(workers_with_field, "worker_sk", "left_anti")
        missing_count = workers_missing_field.count()
        if missing_count > 0:
            logger.info(f"Adding default {gsi_code} records for {missing_count} workers")
            default_columns = []
            for column_name in tax_columns:
                if column_name == "worker_sk":
                    default_columns.append(col("worker_sk"))
                elif column_name == "jurisdiction":
                    default_columns.append(lit("F").alias("jurisdiction"))
                elif column_name == "tax_type":
                    default_columns.append(lit(tax_type).alias("tax_type"))
                elif column_name == "is_employer_tax":
                    default_columns.append(lit(False).alias("is_employer_tax"))
                elif column_name in [
                    "qtd_amount", "qtd_taxable_amount", "qtd_subject_amount", "qtd_gross_wages",
                    "ytd_amount", "ytd_taxable_amount", "ytd_subject_amount", "ytd_gross_wages",
                    "tax_rate", "hours_worked", "qtd_overtime_amount", "ytd_overtime_amount",
                    "oos_qtd_gross_wages", "oos_ytd_gross_wages", "oos_qtd_taxable_amount", "oos_ytd_taxable_amount",
                ]:
                    default_columns.append(lit(0.0).alias(column_name))
                elif column_name in ["year", "quarter"]:
                    sample_row = tax_df.select(column_name).first()
                    default_columns.append(lit(sample_row[0] if sample_row and sample_row[0] is not None else None).alias(column_name))
                else:
                    default_columns.append(lit(None).alias(column_name))
            default_record = workers_missing_field.select(*default_columns)
            tax_df = tax_df.union(default_record)
    logger.info("Mandatory fields enforcement completed")
    return tax_df


def get_default_value_for_field(field_name, config):
    """Generate default value based on field type and configuration."""
    length = int(config.get("length", 12))
    signed_indicator = config.get("signed_indicator", True)
    if signed_indicator:
        return "+" + "0" * (length - 1)
    return "0" * length


def log_mandatory_fields_summary(validation_results):
    """Log a summary of mandatory fields validation results."""
    mandatory_configs = _get_mandatory_field_configs()
    logger.info("=" * 60)
    logger.info("MANDATORY FIELDS VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total Workers Processed: {validation_results['total_workers']}")
    for gsi_code in mandatory_configs.keys():
        workers_with = validation_results.get(f"workers_with_{gsi_code}", 0)
        workers_missing = validation_results.get(f"workers_missing_{gsi_code}", [])
        logger.info(f"Workers with {gsi_code}: {workers_with}")
        if workers_missing:
            logger.warning(f"Missing {gsi_code}: {len(workers_missing)} workers")
    if validation_results["validation_passed"]:
        logger.info("STATUS: ALL WORKERS HAVE MANDATORY FIELDS")
    else:
        logger.warning("STATUS: SOME WORKERS MISSING MANDATORY FIELDS")
    logger.info("=" * 60)
