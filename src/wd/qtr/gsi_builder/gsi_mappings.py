# GSI Mappings Configuration
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wd.qtr.gsi_builder.logger import Logger

logger = Logger.get_logger(__name__)

FIELD_CODE_TO_DB_FIELD = {
    "CS": "given_name",
    "CU": "family_name",
    "DD": "ssn",
    "SY": "birth_date",
    "NZ": "hire_date",
    "PF": "termination_date",
    "EG": "gender",
    "DZ": "retirement_plan_indicator",
    "B2": "third_party_sick_pay_indicator",
    "8R": "replacement_worker",
    "G6": "pull_indicator",
    "G5": "print_suppress_flag",
    "ED": "corporate_officer_indicator",
    "G4": "department_code",
    "32": "independent_contractor",
    "CT": "middle_name",
    "EF": "seasonal_employee",
    "85": "seasonal_employee_local",
    "EC": "medical_coverage_indicator",
    "9F": "wfh_indicator",
    "Q9": "ee_post_indicator",
    "V9": "employee_id",
    "Z3": "job_title",
    "A8": "remuneration_basis",
    "QG": "family_status",
    "EE": "statutory_flag",
    "A7": "pay_rate_amount",
    "JZ": "work_postal_code",
}

ADDRESS_FIELD_MAPPINGS = {
    "SQ": ("line_one", "Work"),
    "Z5": ("line_one", "Home"),
    "CY": ("city_name", "Work"),
    "Z7": ("city_name", "Home"),
    "DA": ("state_code", "Work"),
    "Z8": ("state_code", "Home"),
    "DB": ("postal_code", "Work"),
    "Z9": ("postal_code", "Home"),
}

GSI_LEVEL_MAPPINGS = {
    "F": ["G6", "G5", "G4", "Q9", "V9"],
    "S": ["ED", "EF", "EC", "Z3", "QG", "A7", "JZ"],
    "L": ["85", "9F"],
    "EE": ["CS", "CU", "DD", "SY", "NZ", "PF", "EG", "DZ", "B2", "8R", "32", "CT", "A8", "EE"],
}

FIELD_CODE_PATTERNS = {
    "CS": r"\s{12}A1\s{8}",
    "CU": r"\s{14}A2\s{6}",
    "DD": r"\d{3}-\d{2}-\d{4}",
}

_GI2_RECORD_CODE_TO_LEVEL = {"EEF": "F", "EES": "S", "EEL": "L"}

TOKEN_MAPPINGS = {
    "QTDT": "qtd_amount",
    "YTDT": "ytd_amount",
    "QTDTAXW": "qtd_taxable_amount",
    "YTDTAXW": "ytd_taxable_amount",
    "QTDW": "qtd_taxable_amount",
    "YTDW": "ytd_taxable_amount",
    "QTDSUBJW": "qtd_subject_amount",
    "YTDSUBJW": "ytd_subject_amount",
    "QTDG": "qtd_gross_wages",
    "YTDG": "ytd_gross_wages",
    "QTD-EXEMPT-OVERTIME-INCOME": "qtd_overtime_amount",
    "YTD-EXEMPT-OVERTIME-INCOME": "ytd_overtime_amount",
    "QTDG-OOS": "oos_qtd_gross_wages",
    "YTDG-OOS": "oos_ytd_gross_wages",
    "QTDTAXW-OOS": "oos_qtd_taxable_amount",
    "YTDTAXW-OOS": "oos_ytd_taxable_amount",
    "QTD-HOUR-WORK": "hours_worked",
    "YTD-HOUR-WORK": "hours_worked",
    "QTD-QUALIFY-CNT": "qtd_amount_count",
    "YTD-QUALIFY-CNT": "ytd_amount_count",
    "CD-MARITAL-STS": "filing_status",
    "CD-2-BYTE-EXEMPT": "number_of_allowances",
    "CD-SDIEE-EXEMPT": "sdi_exempt_flag",
    "CD-SUIER-EXEMPT": "sui_exempt_flag",
    "CD-PSD": "lived_in_code",
}

_gi1_gi2_cache = None


def _build_gsi_level_mappings_from_gi2(pg_conn):
    field_codes = list(FIELD_CODE_TO_DB_FIELD.keys()) + list(ADDRESS_FIELD_MAPPINGS.keys())
    try:
        gi2_df = pg_conn.query_gsi_level_mappings(field_codes)
        gi2_data = gi2_df.collect()
        level_mappings = {"F": [], "S": [], "L": [], "EE": []}
        seen_codes = set()
        for row in gi2_data:
            code = row["field_code"]
            record_code = row["record_code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)
            level = _GI2_RECORD_CODE_TO_LEVEL.get(record_code, "EE")
            level_mappings[level].append(code)
        for code in field_codes:
            if code not in seen_codes:
                level_mappings["EE"].append(code)
        logger.info(
            f"Built GSI_LEVEL_MAPPINGS from GI2: F={len(level_mappings['F'])}, S={len(level_mappings['S'])}, L={len(level_mappings['L'])}, EE={len(level_mappings['EE'])}"
        )
        return level_mappings
    except Exception as e:
        logger.error(f"Failed to build level mappings from GI2: {e}")
        logger.warning("Using static fallback GSI_LEVEL_MAPPINGS")
        return GSI_LEVEL_MAPPINGS


def _fetch_api(base_url, endpoint, source_type):
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            )
        ),
    )
    try:
        response = session.get(
            f"{base_url}{endpoint}?sourceType={source_type}",
            headers={"User-Agent": "WD-QTR-GSI-Builder/1.0", "Accept": "application/json"},
            timeout=(10, 30),
            verify=True,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API failed: {e}")
        return None
    finally:
        session.close()


def _validate_postgres_config(config):
    if "postgres" not in config:
        return False
    required_keys = ["host", "port", "database", "schema", "user", "password"]
    postgres_config = config["postgres"]
    missing_keys = [key for key in required_keys if key not in postgres_config or not postgres_config[key]]
    if missing_keys:
        logger.warning(f"Missing PostgreSQL configuration keys: {missing_keys}")
        return False
    return True


def _get_level_for_code(code, level_mappings):
    for level, codes in level_mappings.items():
        if code in codes:
            return level
    return "EE"


def _build_gsi_mappings_from_database():
    global _gi1_gi2_cache
    if _gi1_gi2_cache is not None:
        return _gi1_gi2_cache
    result = _build_gsi_mappings_from_database_impl()
    _gi1_gi2_cache = result
    return result


def _build_gsi_mappings_from_database_impl():
    import time

    start_time = time.time()
    try:
        from pyspark.sql import SparkSession

        from wd.qtr.gsi_builder.config.loader import get_config
        from wd.qtr.gsi_builder.db_connection import PostgresConnection

        config = get_config()
        if not _validate_postgres_config(config):
            logger.warning("PostgreSQL configuration invalid, using static fallback")
            fallback = _get_static_fallback_mappings()
            return fallback[0], fallback[1], {}

        spark = SparkSession.getActiveSession()
        if not spark:
            logger.warning("No active Spark session, using static fallback")
            fallback = _get_static_fallback_mappings()
            return fallback[0], fallback[1], {}

        pg_conn = PostgresConnection(
            spark,
            config["postgres"]["host"],
            config["postgres"]["port"],
            config["postgres"]["database"],
            config["postgres"]["schema"],
            config["postgres"]["user"],
            config["postgres"]["password"],
        )

        gi1_rows = pg_conn.query_gsi_field_mappings().collect()
        dynamic_level_mappings = _build_gsi_level_mappings_from_gi2(pg_conn)
        gsi_mappings = {}
        address_mappings = {"line_one": {}, "city_name": {}, "state_code": {}, "postal_code": {}}
        gi1_field_configs = {}

        for row in gi1_rows:
            field_code = row["field_code"]
            field_length = row["field_length"]
            data_type = row["data_type"]
            decimal_places = int(row["decimal_places"] or 0)
            signed = row["signed"]
            category_1 = row["category_1"]
            mapping = {"gsi_code": field_code}

            if data_type == "N":
                mapping.update({
                    "format": "decimal",
                    "decimal_places": decimal_places,
                    "pad_direction": "left",
                    "signed_indicator": signed == "Y",
                    "length": field_length,
                })
            elif data_type == "X" and category_1 == "DATE":
                mapping.update({
                    "format": "date",
                    "length": 8,
                    "date_format": "yyyyMMdd" if field_code == "SY" else "MMddyyyy",
                })
            elif data_type == "X":
                mapping.update({"format": "text", "pad_direction": "right", "length": field_length})

            mapping["gsi_level"] = _get_level_for_code(field_code, dynamic_level_mappings)
            if field_code in FIELD_CODE_PATTERNS:
                mapping["pattern"] = FIELD_CODE_PATTERNS[field_code]
            gi1_field_configs[field_code] = mapping

            if field_code in FIELD_CODE_TO_DB_FIELD:
                gsi_mappings[FIELD_CODE_TO_DB_FIELD[field_code]] = mapping
            elif field_code in ADDRESS_FIELD_MAPPINGS:
                addr_field, addr_type = ADDRESS_FIELD_MAPPINGS[field_code]
                address_mappings[addr_field][addr_type] = mapping

        logger.info(
            f"Built {len(gsi_mappings)} GSI + {sum(len(v) for v in address_mappings.values())} address mappings + {len(gi1_field_configs)} field configs from GI1 in {time.time() - start_time:.2f}s"
        )
        if not gsi_mappings and not any(address_mappings.values()):
            fallback = _get_static_fallback_mappings()
            return fallback[0], fallback[1], gi1_field_configs
        return gsi_mappings, address_mappings, gi1_field_configs
    except Exception as e:
        logger.error(f"Failed to build mappings from database after {time.time() - start_time:.2f}s: {e}")
        fallback = _get_static_fallback_mappings()
        return fallback[0], fallback[1], {}


def _static_field(gsi_code, fmt="text", length=1, level="EE", **extra):
    mapping = {"gsi_code": gsi_code, "format": fmt, "length": length, "gsi_level": level}
    if fmt == "text":
        mapping["pad_direction"] = "right"
    if fmt == "decimal":
        mapping.setdefault("decimal_places", extra.pop("decimal_places", 2))
        mapping.setdefault("signed_indicator", extra.pop("signed_indicator", True))
    mapping.update(extra)
    return mapping


def _get_static_fallback_mappings():
    logger.info("Using static fallback GSI mappings")
    static_gsi_mappings = {
        "given_name": _static_field("CS", "text", 12, "EE", pattern=FIELD_CODE_PATTERNS["CS"]),
        "family_name": _static_field("CU", "text", 14, "EE", pattern=FIELD_CODE_PATTERNS["CU"]),
        "ssn": _static_field("DD", "text", 0, "EE", pattern=FIELD_CODE_PATTERNS["DD"]),
        "birth_date": _static_field("SY", "date", 10, "EE", date_format="yyyyMMdd"),
        "hire_date": _static_field("NZ", "date", 10, "EE", date_format="MMddyyyy"),
        "termination_date": _static_field("PF", "date", 10, "EE", date_format="MMddyyyy"),
        "gender": _static_field("EG"),
        "retirement_plan_indicator": _static_field("DZ"),
        "third_party_sick_pay_indicator": _static_field("B2"),
        "replacement_worker": _static_field("8R"),
        "pull_indicator": _static_field("G6", level="F"),
        "print_suppress_flag": _static_field("G5", level="F"),
        "corporate_officer_indicator": _static_field("ED", level="S"),
        "department_code": _static_field("G4", "text", 6, "F"),
        "independent_contractor": _static_field("32"),
        "middle_name": _static_field("CT"),
        "seasonal_employee": _static_field("EF", level="S"),
        "seasonal_employee_local": _static_field("85", level="L"),
        "medical_coverage_indicator": _static_field("EC", level="S"),
        "wfh_indicator": _static_field("9F", level="L"),
        "ee_post_indicator": _static_field("Q9", level="F"),
        "work_postal_code": _static_field("JZ", "text", 9, "S"),
        "employee_id": _static_field("V9", "text", 10, "F"),
        "job_title": _static_field("Z3", "text", 80, "S"),
        "remuneration_basis": _static_field("A8"),
        "family_status": _static_field("QG", level="S"),
        "statutory_flag": _static_field("EE"),
        "pay_rate_amount": _static_field("A7", "decimal", 10, "S", decimal_places=4, signed_indicator=False),
    }
    static_address_mappings = {
        "line_one": {
            "Work": _static_field("SQ", "text", 30),
            "Home": _static_field("Z5", "text", 40),
        },
        "city_name": {
            "Work": _static_field("CY", "text", 18),
            "Home": _static_field("Z7", "text", 30),
        },
        "state_code": {
            "Work": _static_field("DA", "text", 2),
            "Home": _static_field("Z8", "text", 2),
        },
        "postal_code": {
            "Work": _static_field("DB", "text", 9),
            "Home": _static_field("Z9", "text", 9),
        },
    }
    return static_gsi_mappings, static_address_mappings


def _generate_mappings(api_data, gi1_field_configs=None):
    if gi1_field_configs is None:
        gi1_field_configs = {}
    tax_mappings = {k: {} for k in TOKEN_MAPPINGS.values()}
    tax_mappings.setdefault("lived_in_code", {})

    for item in api_data:
        adp_code = item.get("adpCode", {}).get("code")
        gsi_code = item.get("gsiCode", {}).get("code")
        token_code = item.get("token", {}).get("code")
        if all([adp_code, gsi_code, token_code]) and token_code in TOKEN_MAPPINGS:
            field_config = gi1_field_configs.get(gsi_code)
            if not field_config:
                logger.warning(f"GSI code {gsi_code} not found in GI1 table - skipping")
                continue
            mapping = {
                "gsi_code": gsi_code,
                "format": field_config.get("format", "decimal"),
                "length": field_config["length"],
                "decimal_places": field_config.get("decimal_places", 2),
                "signed_indicator": field_config.get("signed_indicator", True),
                "mandatory": gsi_code in ["7H", "5E"],
            }
            if mapping["format"] == "text":
                mapping["pad_direction"] = field_config.get("pad_direction", "right")
            if "gsi_level" in field_config:
                mapping["gsi_level"] = field_config["gsi_level"]
            tax_mappings[TOKEN_MAPPINGS[token_code]][adp_code] = mapping

    adp_codes = {item.get("adpCode", {}).get("code") for item in api_data if item.get("adpCode", {}).get("code")}
    tax_type_mappings = {
        code[:-2]: {False: code, True: code[:-2] + "ER"}
        for code in adp_codes
        if code and code.endswith("EE") and code[:-2] + "ER" in adp_codes
    }
    logger.info(f"Generated {sum(len(v) for v in tax_mappings.values())} tax mappings from API")
    return tax_mappings, tax_type_mappings


def _static_tax_fallback():
    return {
        "qtd_amount": {
            "FIT": {"gsi_code": "EJ", "format": "decimal", "length": 12, "decimal_places": 2, "signed_indicator": True},
            "SSEE-QTD": {"gsi_code": "7H", "format": "decimal", "length": 12, "decimal_places": 2, "signed_indicator": True, "mandatory": True},
        },
        "ytd_amount": {
            "FIT": {"gsi_code": "EK", "format": "decimal", "length": 14, "decimal_places": 2, "signed_indicator": True},
            "SSEE": {"gsi_code": "5H", "format": "decimal", "length": 14, "decimal_places": 2, "signed_indicator": True, "mandatory": True},
            "MEDEE": {"gsi_code": "5E", "format": "decimal", "length": 14, "decimal_places": 2, "signed_indicator": True, "mandatory": True},
        },
        "qtd_taxable_amount": {},
        "ytd_taxable_amount": {},
        "qtd_subject_amount": {},
        "ytd_subject_amount": {},
        "qtd_gross_wages": {"SIT": {"gsi_code": "MV", "format": "decimal", "length": 12, "decimal_places": 2, "signed_indicator": True}},
        "ytd_gross_wages": {"SIT": {"gsi_code": "NT", "format": "decimal", "length": 12, "decimal_places": 2, "signed_indicator": True}},
        "hours_worked": {},
        "qtd_overtime_amount": {},
        "ytd_overtime_amount": {},
        "oos_qtd_gross_wages": {},
        "oos_ytd_gross_wages": {},
        "oos_qtd_taxable_amount": {},
        "oos_ytd_taxable_amount": {},
        "qtd_amount_count": {"COBRA-CR": {"gsi_code": "V7", "format": "decimal", "length": 7, "decimal_places": 0, "signed_indicator": False}},
        "ytd_amount_count": {"COBRA-CR": {"gsi_code": "V8", "format": "decimal", "length": 7, "decimal_places": 0, "signed_indicator": False}},
        "filing_status": {
            "FIT": {"gsi_code": "DF", "format": "text", "length": 1, "pad_direction": "right", "gsi_level": "F"},
            "SIT": {"gsi_code": "DH", "format": "text", "length": 1, "pad_direction": "right", "gsi_level": "S"},
            "CIT": {"gsi_code": "DK", "format": "text", "length": 1, "pad_direction": "right", "gsi_level": "L"},
        },
        "number_of_allowances": {
            "FIT": {"gsi_code": "DG", "format": "decimal", "length": 2, "decimal_places": 0, "signed_indicator": False},
            "SIT": {"gsi_code": "DI", "format": "decimal", "length": 2, "decimal_places": 0, "signed_indicator": False},
            "CIT": {"gsi_code": "DL", "format": "decimal", "length": 2, "decimal_places": 0, "signed_indicator": False},
        },
        "sdi_exempt_flag": {"SDIEE": {"gsi_code": "EB", "format": "text", "length": 1, "pad_direction": "right", "gsi_level": "S"}},
        "sui_exempt_flag": {"SUIER": {"gsi_code": "EA", "format": "text", "length": 1, "pad_direction": "right", "gsi_level": "S"}},
        "lived_in_code": {},
    }, {
        "SocialSecurity": {False: "SSEE", True: "SSER"},
        "MEDICARE": {False: "MEDEE", True: "MEDER"},
        "SUI": {False: "SUIEE", True: "SUIER"},
        "SDI": {False: "SDIEE", True: "SDIER"},
        "FICA": {False: "FICAEE", True: "FICAER"},
    }


def _init_mappings():
    _, _, gi1_field_configs = _build_gsi_mappings_from_database()
    try:
        from wd.qtr.gsi_builder.config.loader import get_config

        config = get_config()
        api_data = _fetch_api(config["api"]["base_url"], config["api"]["endpoint"], config["api"]["source_type"])
        if api_data:
            logger.info(f"Loaded {len(api_data)} mappings from API")
            return _generate_mappings(api_data, gi1_field_configs)
        logger.warning("API returned no data, using static fallback mappings")
    except Exception as e:
        logger.warning(f"Using static mappings: {e}")
    return _static_tax_fallback()


def clear_all_caches():
    global _gi1_gi2_cache, _TAX_MAPPINGS, _TAX_TYPE_MAPPINGS
    logger.info("Clearing module-level GSI/API mapping caches")
    _gi1_gi2_cache = None
    _TAX_MAPPINGS = None
    _TAX_TYPE_MAPPINGS = None


def get_all_cache_info():
    return {
        "gi1_gi2_cache_loaded": _gi1_gi2_cache is not None,
        "tax_mappings_loaded": _TAX_MAPPINGS is not None,
        "tax_type_mappings_loaded": _TAX_TYPE_MAPPINGS is not None,
    }


def load_mappings():
    try:
        result = _build_gsi_mappings_from_database()
        if isinstance(result, tuple) and len(result) >= 2:
            gsi, addr = result[0], result[1]
            logger.info(f"Mappings loaded - GSI: {len(gsi)}, ADDR: {len(addr)}")
            return gsi, addr
    except Exception as e:
        logger.error(f"Failed to load mappings: {e}")
    logger.info("Using static fallback mappings")
    return _get_static_fallback_mappings()


def get_gsi_mappings():
    return load_mappings()[0]


def get_address_mappings():
    return load_mappings()[1]


def _ensure_mappings_loaded():
    return load_mappings()


_TAX_MAPPINGS = None
_TAX_TYPE_MAPPINGS = None


def _get_tax_mappings():
    global _TAX_MAPPINGS, _TAX_TYPE_MAPPINGS
    if _TAX_MAPPINGS is None:
        _TAX_MAPPINGS, _TAX_TYPE_MAPPINGS = _init_mappings()
    return _TAX_MAPPINGS, _TAX_TYPE_MAPPINGS


class _LazyTaxMappings:
    """Lazy proxy that defers _init_mappings until first dict access."""

    def __init__(self, index):
        self._index = index

    def _resolve(self):
        return _get_tax_mappings()[self._index]

    def __getattr__(self, name):
        return getattr(self._resolve(), name)

    def __getitem__(self, key):
        return self._resolve()[key]

    def __contains__(self, key):
        return key in self._resolve()

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self):
        return len(self._resolve())

    def __bool__(self):
        return bool(self._resolve())

    @property
    def __class__(self):
        return dict

    def get(self, key, default=None):
        return self._resolve().get(key, default)

    def items(self):
        return self._resolve().items()

    def keys(self):
        return self._resolve().keys()

    def values(self):
        return self._resolve().values()


TAX_MAPPINGS = _LazyTaxMappings(0)
TAX_TYPE_MAPPINGS = _LazyTaxMappings(1)
