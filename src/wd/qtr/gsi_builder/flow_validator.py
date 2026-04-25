"""Flow validation utilities."""

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)


def validate_config(config):
    """Validate configuration completeness, types, and non-empty values."""
    required_keys = {
        "redshift": ["host", "port", "database", "schema", "user", "password"],
        "kafka": ["bootstrap_servers", "input_topic", "consumer_group", "checkpoint_location"],
        "s3": ["volume_path"],
        "app": ["name", "batch_size", "max_workers"],
    }
    expected_types = {
        "redshift.port": int,
        "app.batch_size": int,
        "app.max_workers": int,
    }
    missing = []
    for section, keys in required_keys.items():
        if section not in config:
            missing.append(f"Missing section: {section}")
            continue
        for key in keys:
            if key not in config[section]:
                missing.append(f"Missing {section}.{key}")
            elif config[section][key] is None:
                missing.append(f"Null value for {section}.{key}")
            elif isinstance(config[section][key], str) and not config[section][key].strip():
                missing.append(f"Empty value for {section}.{key}")
            else:
                type_key = f"{section}.{key}"
                if type_key in expected_types and not isinstance(config[section][key], expected_types[type_key]):
                    missing.append(
                        f"Invalid type for {section}.{key}: expected {expected_types[type_key].__name__}, got {type(config[section][key]).__name__}"
                    )
    if missing:
        error_msg = f"Configuration validation failed: {', '.join(missing)}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    logger.info("Configuration validation passed")
    return True


def validate_dataframe_columns(df, required_columns, context="DataFrame"):
    """Validate DataFrame has required columns."""
    if df is None:
        error_msg = f"{context} is None"
        logger.error(error_msg)
        raise ValueError(error_msg)
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        error_msg = f"{context} missing columns: {missing_cols}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    return True
