import re

from pyspark.sql.functions import (
    array,
    col,
    concat,
    date_format,
    explode,
    length,
    lit,
    lpad,
    rpad,
    substring,
    trim,
    udf,
    when,
)
from pyspark.sql.types import ArrayType, StringType

from wd.qtr.gsi_builder.logger import Logger

# GSI format constants
GSI_LINE_MAX_LENGTH = 160
GSI_CODE_LENGTH = 2
EMPLOYEE_LINE_PREFIX = "******      "
EMPLOYEE_PREFIX_LENGTH = len(EMPLOYEE_LINE_PREFIX)
QTD_FIELD_LENGTH = 12
YTD_FIELD_LENGTH = 14
RATE_FIELD_LENGTH = 8
DEFAULT_DECIMAL_PLACES = 2
RATE_DECIMAL_PLACES = 4
HOURS_DECIMAL_PLACES = 0
TAX_JURISDICTION_LENGTH = 6
TAX_LINE_PREFIX = "******"


def split_gsi_line_at_160(line):
    """Split GSI line at 160 characters, keeping GSI codes intact."""
    if not line or len(line) <= GSI_LINE_MAX_LENGTH:
        return [line] if line else []

    lines = []
    current_pos = 0

    while current_pos < len(line):
        if current_pos == 0:
            split_pos = GSI_LINE_MAX_LENGTH
            for i in range(
                min(GSI_LINE_MAX_LENGTH - GSI_CODE_LENGTH, len(line) - GSI_CODE_LENGTH),
                -1,
                -1,
            ):
                if line[i : i + GSI_CODE_LENGTH].isupper() and line[i : i + GSI_CODE_LENGTH].isalnum():
                    split_pos = i
                    break
            lines.append(line[:split_pos])
            current_pos = split_pos
        else:
            remaining = line[current_pos:]
            available_space = GSI_LINE_MAX_LENGTH - EMPLOYEE_PREFIX_LENGTH
            if len(remaining) <= available_space:
                lines.append(EMPLOYEE_LINE_PREFIX + remaining)
                break
            split_pos = available_space
            for i in range(
                min(available_space - GSI_CODE_LENGTH, len(remaining) - GSI_CODE_LENGTH),
                -1,
                -1,
            ):
                if remaining[i : i + GSI_CODE_LENGTH].isupper() and remaining[i : i + GSI_CODE_LENGTH].isalnum():
                    split_pos = i
                    break
            lines.append(EMPLOYEE_LINE_PREFIX + remaining[:split_pos])
            current_pos += split_pos

    return lines


def build_employee_lines_with_limit(gsi_fields, max_length=GSI_LINE_MAX_LENGTH):
    """Build employee lines with 160-char limit, keeping GSI codes with values."""
    if not gsi_fields:
        return [EMPLOYEE_LINE_PREFIX]

    lines = []
    current_line = EMPLOYEE_LINE_PREFIX

    for gsi_field in gsi_fields:
        if not gsi_field:
            continue
        if len(current_line + gsi_field) > max_length:
            if len(current_line) > EMPLOYEE_PREFIX_LENGTH:
                lines.append(current_line)
            current_line = EMPLOYEE_LINE_PREFIX + gsi_field
        else:
            current_line += gsi_field

    if len(current_line) > EMPLOYEE_PREFIX_LENGTH:
        lines.append(current_line)

    return lines if lines else [EMPLOYEE_LINE_PREFIX]


def build_employee_lines_udf():
    return udf(build_employee_lines_with_limit, ArrayType(StringType()))


def format_gsi_field(df, source_col, target_col, format_type, field_length=None, **kwargs):
    """Format field based on GSI requirements."""
    gsi_code = kwargs.get("gsi_code", "")
    pad_direction = kwargs.get("pad_direction", "right")
    date_format_type = kwargs.get("date_format", "yyyyMMdd")
    pattern = kwargs.get("pattern")
    signed_indicator = kwargs.get("signed_indicator", False)
    decimal_places = kwargs.get("decimal_places", 2)

    if field_length is not None:
        field_length = int(field_length)
        if field_length <= 0:
            field_length = None
    if decimal_places is not None:
        decimal_places = int(decimal_places)
    if isinstance(signed_indicator, str):
        signed_indicator = signed_indicator.upper() == "Y"

    if format_type == "text":
        df = df.withColumn(
            target_col,
            when(col(source_col).isNull(), lit(None)).otherwise(trim(col(source_col))),
        )

        if pattern and r"\d{3}-\d{2}-\d{4}" in pattern:
            def format_ssn(value):
                if value is None:
                    return None
                digits_only = "".join(filter(str.isdigit, str(value)))
                if len(digits_only) == 9:
                    return f"{digits_only[:3]}-{digits_only[3:5]}-{digits_only[5:]}"
                return str(value)

            ssn_udf = udf(format_ssn, StringType())
            df = df.withColumn(
                target_col,
                when(col(target_col).isNull(), lit(None)).otherwise(ssn_udf(col(target_col))),
            )
        elif pattern and field_length and field_length > 0:
            def apply_pattern_overflow(value, pattern_str, max_len):
                if value is None:
                    return None
                value = str(value)
                if len(value) <= max_len:
                    return value.ljust(max_len, " ")
                if "A1" in pattern_str:
                    return value[:12] + "A1" + value[12:20].ljust(8, " ")
                if "A2" in pattern_str:
                    return value[:14] + "A2" + value[14:20].ljust(6, " ")
                return value[:max_len]

            pattern_udf = udf(lambda x: apply_pattern_overflow(x, pattern, field_length), StringType())
            df = df.withColumn(
                target_col,
                when(col(target_col).isNull(), lit(None)).otherwise(pattern_udf(col(target_col))),
            )
        elif field_length and field_length > 0:
            if pad_direction == "left":
                df = df.withColumn(
                    target_col,
                    when(col(target_col).isNull(), lit(None)).otherwise(
                        when(length(col(target_col)) >= field_length, substring(col(target_col), 1, field_length)).otherwise(
                            lpad(col(target_col), field_length, " ")
                        )
                    ),
                )
            else:
                df = df.withColumn(
                    target_col,
                    when(col(target_col).isNull(), lit(None)).otherwise(
                        when(length(col(target_col)) >= field_length, substring(col(target_col), 1, field_length)).otherwise(
                            rpad(col(target_col), field_length, " ")
                        )
                    ),
                )

        df = df.withColumn(
            target_col,
            when(col(target_col).isNull(), lit(None)).otherwise(concat(lit(gsi_code), col(target_col))),
        )

    elif format_type == "number":
        field_length = int(field_length) if field_length is not None else 0
        if signed_indicator:
            sign_char = when(col(source_col) >= 0, lit("+")).otherwise(lit("-"))
            abs_value = when(col(source_col) < 0, -col(source_col)).otherwise(col(source_col))
            numeric_length = field_length - 1
            formatted_value = lpad(abs_value.cast("string"), numeric_length, "0")
            df = df.withColumn(
                target_col,
                when(col(source_col).isNull(), lit(None)).otherwise(concat(lit(gsi_code), sign_char, formatted_value)),
            )
        else:
            df = df.withColumn(
                target_col,
                when(col(source_col).isNull(), lit(None)).otherwise(
                    concat(lit(gsi_code), lpad(col(source_col).cast("string"), field_length, "0"))
                ),
            )
    elif format_type == "decimal":
        field_length = int(field_length) if field_length is not None else 0
        multiplier = lit(10**decimal_places)
        if signed_indicator:
            sign_char = when(col(source_col) >= 0, lit("+")).otherwise(lit("-"))
            abs_value = when(col(source_col) < 0, -col(source_col)).otherwise(col(source_col))
            scaled_value = (abs_value * multiplier).cast("long")
            numeric_length = field_length - 1
            formatted_value = lpad(scaled_value.cast("string"), numeric_length, "0")
            df = df.withColumn(
                target_col,
                when(col(source_col).isNull(), lit(None)).otherwise(concat(lit(gsi_code), sign_char, formatted_value)),
            )
        else:
            scaled_value = (col(source_col) * multiplier).cast("long")
            formatted_value = lpad(scaled_value.cast("string"), field_length, "0")
            df = df.withColumn(
                target_col,
                when(col(source_col).isNull(), lit(None)).otherwise(concat(lit(gsi_code), formatted_value)),
            )
    elif format_type == "date":
        df = df.withColumn(
            target_col,
            when(col(source_col).isNull(), lit(None)).otherwise(
                concat(lit(gsi_code), date_format(col(source_col), date_format_type))
            ),
        )
    return df


def apply_gsi_mappings(df, gsi_mappings, address_mappings):
    """Apply GSI mappings to worker data and return (df, level_cols)."""
    import time

    logger = Logger.get_logger(__name__)
    mapping_start = time.time()
    logger.info(
        f"Starting GSI mappings application with {len(gsi_mappings)} GSI mappings and {len(address_mappings)} address mappings"
    )

    level_cols = {"EE": [], "F": [], "S": [], "L": []}
    processed_fields = 0

    for field, metadata in gsi_mappings.items():
        if field in df.columns and all(key in metadata for key in ["gsi_code", "format", "length"]):
            field_start = time.time()
            kwargs = {"gsi_code": metadata["gsi_code"]}
            for optional_key in ["date_format", "pad_direction", "pattern", "decimal_places", "signed_indicator"]:
                if optional_key in metadata:
                    kwargs[optional_key] = metadata[optional_key]
            df = format_gsi_field(
                df,
                field,
                metadata["gsi_code"],
                metadata["format"],
                metadata["length"],
                **kwargs,
            )
            gsi_level = metadata.get("gsi_level", "EE")
            level_cols.setdefault(gsi_level, []).append(metadata["gsi_code"])
            processed_fields += 1
            field_time = time.time() - field_start
            if field_time > 1.0:
                logger.info(f"GSI field {field} -> {metadata['gsi_code']} took {field_time:.2f}s")

    processed_addresses = 0
    for field, type_mappings in address_mappings.items():
        for addr_type in ["Work", "Home"]:
            col_name = f"{addr_type.lower()}_{field}"
            if col_name in df.columns and addr_type in type_mappings:
                metadata = type_mappings[addr_type]
                if all(key in metadata for key in ["gsi_code", "format", "length"]):
                    kwargs = {
                        "gsi_code": metadata["gsi_code"],
                        "pad_direction": metadata.get("pad_direction", "right"),
                    }
                    df = format_gsi_field(
                        df,
                        col_name,
                        metadata["gsi_code"],
                        metadata["format"],
                        metadata["length"],
                        **kwargs,
                    )
                    gsi_level = metadata.get("gsi_level", "EE")
                    level_cols.setdefault(gsi_level, []).append(metadata["gsi_code"])
                    processed_addresses += 1

    logger.info(f"Processed {processed_fields} GSI fields and {processed_addresses} address fields")
    logger.info(f"GSI mappings application completed in {time.time() - mapping_start:.2f}s")
    logger.info(
        f"Level columns: EE={len(level_cols['EE'])}, F={len(level_cols['F'])}, S={len(level_cols['S'])}, L={len(level_cols['L'])}"
    )
    return df, level_cols


def get_default_value_for_field(field_name, config):
    """Generate default value based on field type and GI1 configuration."""
    length_value = int(config.get("length", 12))
    signed_indicator = config.get("signed_indicator", True)
    if signed_indicator:
        return "+" + "0" * (length_value - 1)
    return "0" * length_value


def format_tax_data_df(tax_df, worker_level_df=None):
    """Format tax data using DataFrame operations with tax type mapping."""
    import time

    from pyspark.sql.functions import abs as spark_abs
    from pyspark.sql.functions import coalesce, collect_list, first, struct
    from pyspark.sql.window import Window

    from wd.qtr.gsi_builder.gsi_mappings import TAX_MAPPINGS, TAX_TYPE_MAPPINGS

    logger = Logger.get_logger(__name__)
    tax_format_start = time.time()
    logger.info("Starting tax data formatting")

    for base_type, mapping in TAX_TYPE_MAPPINGS.items():
        tax_df = tax_df.withColumn(
            "tax_type",
            when(
                col("tax_type") == base_type,
                when(col("is_employer_tax") == True, lit(mapping[True])).otherwise(lit(mapping[False])),
            ).otherwise(col("tax_type")),
        )

    tax_df = tax_df.withColumn("state_order", when(col("jurisdiction") == "F", lit(0)).otherwise(lit(1)))
    tax_df = tax_df.withColumn(
        "jurisdiction_fmt",
        rpad(coalesce(col("jurisdiction"), lit("")), TAX_JURISDICTION_LENGTH, " "),
    )

    def get_gsi_code(field_name, tax_type_col):
        return when(col(tax_type_col).isNull(), lit("")).otherwise(
            coalesce(
                *[
                    when(col(tax_type_col) == tax_key, lit(tax_config["gsi_code"]))
                    for tax_key, tax_config in TAX_MAPPINGS.get(field_name, {}).items()
                ],
                lit(""),
            )
        )

    def format_decimal_field_dynamic(df, field_name, default_length=12, default_decimal_places=2):
        if field_name not in df.columns:
            return lit("")
        gsi_code = get_gsi_code(field_name, "tax_type")
        has_gsi = when(gsi_code == "", False).otherwise(True)
        field_length_map = TAX_MAPPINGS.get(field_name, {})
        length_expr = lit(default_length)
        for tax_config in field_length_map.values():
            if "gsi_code" in tax_config and "length" in tax_config:
                length_expr = when(gsi_code == tax_config["gsi_code"], lit(int(tax_config["length"]))).otherwise(length_expr)
        is_mandatory = lit(False)
        for tax_config in field_length_map.values():
            if tax_config.get("mandatory", False):
                is_mandatory = when(gsi_code == tax_config["gsi_code"], lit(True)).otherwise(is_mandatory)
        sign = when(col(field_name).isNull(), lit("")).otherwise(
            when(col(field_name) >= 0, lit("+")).otherwise(lit("-"))
        )
        abs_val = when(col(field_name).isNull(), lit(0)).otherwise(spark_abs(col(field_name)))
        numeric_length = length_expr - 1
        should_skip = (~has_gsi) | col(field_name).isNull() | ((col(field_name) == 0) & (~is_mandatory))
        return when(should_skip, lit("")).otherwise(
            concat(
                gsi_code,
                sign,
                lpad((abs_val * lit(10**default_decimal_places)).cast("long").cast("string"), numeric_length, "0"),
            )
        )

    decimal_fields = [
        ("qtd_amount", "f_qtd_amount", QTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("qtd_taxable_amount", "f_qtd_taxable", QTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("qtd_subject_amount", "f_qtd_subject", QTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("qtd_gross_wages", "f_qtd_gross", QTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("ytd_amount", "f_ytd_amount", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("ytd_taxable_amount", "f_ytd_taxable", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("ytd_subject_amount", "f_ytd_subject", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("ytd_gross_wages", "f_ytd_gross", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("tax_rate", "f_tax_rate", RATE_FIELD_LENGTH, RATE_DECIMAL_PLACES),
        ("hours_worked", "f_hours_worked", RATE_FIELD_LENGTH, HOURS_DECIMAL_PLACES),
        ("qtd_overtime_amount", "f_qtd_overtime", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("ytd_overtime_amount", "f_ytd_overtime", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("oos_qtd_gross_wages", "f_oos_qtd_gross", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("oos_ytd_gross_wages", "f_oos_ytd_gross", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("oos_qtd_taxable_amount", "f_oos_qtd_taxable", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("oos_ytd_taxable_amount", "f_oos_ytd_taxable", YTD_FIELD_LENGTH, DEFAULT_DECIMAL_PLACES),
        ("qtd_amount_count", "f_qtd_amount_count", 7, 0),
        ("ytd_amount_count", "f_ytd_amount_count", 7, 0),
    ]
    for source, target, default_length, decimals in decimal_fields:
        tax_df = tax_df.withColumn(target, format_decimal_field_dynamic(tax_df, source, default_length, decimals))

    def format_text_field_dynamic(df, field_name, default_length=1):
        if field_name not in df.columns:
            return lit("")
        gsi_code = get_gsi_code(field_name, "tax_type")
        return when((gsi_code == "") | col(field_name).isNull(), lit("")).otherwise(
            concat(gsi_code, rpad(trim(col(field_name).cast("string")), default_length, " "))
        )

    def format_unsigned_decimal_field_dynamic(df, field_name, default_length=2):
        if field_name not in df.columns:
            return lit("")
        gsi_code = get_gsi_code(field_name, "tax_type")
        return when((gsi_code == "") | col(field_name).isNull(), lit("")).otherwise(
            concat(gsi_code, lpad(col(field_name).cast("long").cast("string"), default_length, "0"))
        )

    tax_df = tax_df.withColumn("f_filing_status", format_text_field_dynamic(tax_df, "filing_status", 1))
    tax_df = tax_df.withColumn("f_number_of_allowances", format_unsigned_decimal_field_dynamic(tax_df, "number_of_allowances", 2))
    tax_df = tax_df.withColumn("f_sui_exempt_flag", format_text_field_dynamic(tax_df, "sui_exempt_flag", 1))
    tax_df = tax_df.withColumn("f_sdi_exempt_flag", format_text_field_dynamic(tax_df, "sdi_exempt_flag", 1))

    if "lived_in_code" in tax_df.columns:
        tax_df = tax_df.withColumn(
            "f_lived_in_code",
            when(col("lived_in_code").isNotNull() & (trim(col("lived_in_code")) != lit("")),
                 concat(lit("X1"), lpad(trim(col("lived_in_code")), 6, "0"))).otherwise(lit("")),
        )
    else:
        tax_df = tax_df.withColumn("f_lived_in_code", lit(""))

    tax_df = tax_df.withColumn(
        "gsi_fields",
        array(
            col("f_lived_in_code"), col("f_qtd_amount"), col("f_qtd_taxable"), col("f_qtd_subject"),
            col("f_qtd_gross"), col("f_ytd_amount"), col("f_ytd_taxable"), col("f_ytd_subject"),
            col("f_ytd_gross"), col("f_tax_rate"), col("f_hours_worked"), col("f_qtd_overtime"),
            col("f_ytd_overtime"), col("f_oos_qtd_gross"), col("f_oos_ytd_gross"),
            col("f_oos_qtd_taxable"), col("f_oos_ytd_taxable"), col("f_qtd_amount_count"),
            col("f_ytd_amount_count"), col("f_filing_status"), col("f_number_of_allowances"),
            col("f_sui_exempt_flag"), col("f_sdi_exempt_flag"),
        ),
    )

    tax_df = (
        tax_df.groupBy("worker_sk", "jurisdiction_fmt", "state_order")
        .agg(collect_list("gsi_fields").alias("all_gsi_fields"))
        .orderBy("worker_sk", "state_order", "jurisdiction_fmt")
    )

    if worker_level_df is not None:
        from pyspark.sql.functions import trim as spark_trim

        worker_level_df = worker_level_df.withColumnRenamed("worker_sk", "wl_worker_sk")
        is_federal = tax_df["state_order"] == 0
        is_state = (tax_df["state_order"] == 1) & (length(spark_trim(tax_df["jurisdiction_fmt"])) <= 2)
        is_local = (tax_df["state_order"] == 1) & (length(spark_trim(tax_df["jurisdiction_fmt"])) > 2)
        tax_df = tax_df.join(
            worker_level_df,
            (tax_df["worker_sk"] == worker_level_df["wl_worker_sk"])
            & (
                ((worker_level_df["level_type"] == "F") & is_federal)
                | ((worker_level_df["level_type"] == "S") & is_state)
                | ((worker_level_df["level_type"] == "L") & is_local)
            ),
            "left",
        ).drop("wl_worker_sk", "level_type")
        tax_df = tax_df.withColumn(
            "all_gsi_fields",
            when(col("level_gsi_fields").isNotNull(), concat(array(col("level_gsi_fields")), col("all_gsi_fields"))).otherwise(
                col("all_gsi_fields")
            ),
        ).drop("level_gsi_fields")
        tax_df = (
            tax_df.groupBy("worker_sk", "jurisdiction_fmt", "state_order")
            .agg(first("all_gsi_fields").alias("all_gsi_fields"))
            .orderBy("worker_sk", "state_order", "jurisdiction_fmt")
        )

    def build_tax_lines_with_split(jurisdiction_fmt, all_gsi_fields):
        if not all_gsi_fields:
            return []
        prefix = TAX_LINE_PREFIX + jurisdiction_fmt
        lines = []
        current_line = prefix
        all_fields = []
        for item in all_gsi_fields:
            fields = item if isinstance(item, list) else [item]
            for gsi_field in fields:
                if gsi_field:
                    all_fields.append(gsi_field)
        for gsi_field in all_fields:
            if len(current_line + gsi_field) > GSI_LINE_MAX_LENGTH:
                if len(current_line) > len(prefix):
                    lines.append(current_line)
                current_line = prefix + gsi_field
            else:
                current_line += gsi_field
        if len(current_line) > len(prefix):
            lines.append(current_line)
        return lines

    build_lines_udf = udf(build_tax_lines_with_split, ArrayType(StringType()))
    tax_df = tax_df.withColumn("tax_lines", build_lines_udf(col("jurisdiction_fmt"), col("all_gsi_fields")))
    tax_df = tax_df.select(col("worker_sk"), explode(col("tax_lines")).alias("tax_line"))
    tax_df = tax_df.filter(length(col("tax_line")) > 12)
    logger.info(f"Tax data formatting completed in {time.time() - tax_format_start:.2f}s")
    return tax_df.select("worker_sk", "tax_line")
