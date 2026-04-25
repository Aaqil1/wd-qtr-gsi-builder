import re

from pyspark.sql import DataFrame

from wd.qtr.gsi_builder.cache_utils import cached_gsi_query
from wd.qtr.gsi_builder.logger import Logger
from wd.qtr.gsi_builder.outbound_file_status import OutboundFileStatus

logger = Logger.get_logger(__name__)


class RedshiftConnection:
    def __init__(self, spark, host, port, database, schema, username, password):
        self.spark = spark
        self.host = host
        self.port = port
        self.database = database
        self.schema = schema
        self.username = username
        self.password = password
        self.jdbc_url = f"jdbc:redshift://{host}:{port}/{database}"
        self._write_conn = None

    def _sanitize_input(self, value):
        return self._validate_input(value)

    @staticmethod
    def _validate_input(value, max_length=50):
        """Validate input against allowlist to reduce SQL injection risk."""
        if not isinstance(value, str):
            value = str(value)
        if len(value) > max_length:
            raise ValueError(f"Input exceeds max length of {max_length}")
        if not re.match(r"^[a-zA-Z0-9_\-\.\s:/&]+$", value):
            raise ValueError(f"Input contains disallowed characters: {value[:20]}")
        return value

    def _execute_query(self, query, timeout_seconds=300):
        import time

        logger.info(f"Executing Redshift query: {query[:100]}...")
        query_start = time.time()
        try:
            result = (
                self.spark.read.format("jdbc")
                .option("url", self.jdbc_url)
                .option("query", query)
                .option("user", self.username)
                .option("password", self.password)
                .option("driver", "com.amazon.redshift.jdbc42.Driver")
                .option("connectTimeout", "30")
                .option("socketTimeout", str(timeout_seconds))
                .option("loginTimeout", "30")
                .option("queryTimeout", str(timeout_seconds))
                .option("fetchsize", "1000")
                .option("tcpKeepAlive", "true")
                .load()
            )
            logger.info(f"Redshift query execution completed in {time.time() - query_start:.2f}s")
            return result
        except Exception as e:
            logger.error(f"Redshift query failed after {time.time() - query_start:.2f}s: {e}")
            raise

    def query_workers(self, branch_code, company_code, year, quarter) -> DataFrame:
        """Query worker data with pivoted addresses."""
        company_code = self._validate_input(company_code)
        branch_code = self._validate_input(branch_code)
        logger.info(
            f"Starting worker query for branch={branch_code}, company={company_code}, year={year}, quarter={quarter}"
        )

        count_query = (
            f"SELECT COUNT(*) as worker_count FROM {self.schema}.worker w "
            f"WHERE w.company_code = '{company_code}' AND w.branch_code = '{branch_code}' "
            f"AND EXISTS(SELECT 1 FROM {self.schema}.worker_tax_qtr_snapshot wt "
            f"WHERE wt.worker_sk=w.worker_sk AND wt.year={year} AND wt.quarter={quarter})"
        )
        count_result = self._execute_query(count_query, timeout_seconds=60)
        worker_count = count_result.collect()[0]["worker_count"]
        logger.info(f"Found {worker_count} workers for {branch_code}/{company_code}")

        query = f"""
        SELECT
            w.worker_sk, w.branch_code, w.company_code, upper(w.family_name) as family_name, upper(w.given_name) as given_name,
            MAX(CASE WHEN wa.type = 'Work' THEN upper(wa.line_one) END) as work_line_one,
            MAX(CASE WHEN wa.type = 'Work' THEN upper(wa.city_name) END) as work_city_name,
            MAX(CASE WHEN wa.type = 'Work' THEN wa.state_code END) as work_state_code,
            MAX(CASE WHEN wa.type = 'Work' THEN wa.postal_code END) as work_postal_code,
            MAX(CASE WHEN wa.type = 'Home' THEN upper(wa.line_one) END) as home_line_one,
            MAX(CASE WHEN wa.type = 'Home' THEN upper(wa.city_name) END) as home_city_name,
            MAX(CASE WHEN wa.type = 'Home' THEN wa.state_code END) as home_state_code,
            MAX(CASE WHEN wa.type = 'Home' THEN wa.postal_code END) as home_postal_code,
            w.ssn, w.birth_date, w.hire_date, w.termination_date, w.gender, w.department_code,
            upper(LEFT(w.middle_name, 1)) AS middle_name,
            CASE WHEN w.retirement_plan_indicator THEN 'Y' ELSE 'N' END as retirement_plan_indicator,
            CASE WHEN w.third_party_sick_pay_indicator THEN 'Y' ELSE 'N' END as third_party_sick_pay_indicator,
            CASE WHEN w.replacement_worker THEN 'Y' ELSE 'N' END as replacement_worker,
            CASE WHEN w.corporate_officer_indicator THEN 'Y' ELSE 'N' END as corporate_officer_indicator,
            CASE WHEN w.w2_special_handle_indicator THEN 'P' ELSE 'M' END AS pull_indicator,
            CASE WHEN w.medical_coverage_indicator THEN '3' ELSE '1' END AS medical_coverage_indicator,
            CASE WHEN w.suppress_w2_print_indicator THEN 'P' ELSE 'N' END AS print_suppress_flag,
            CASE WHEN w.worker_type='Contractor' THEN 'Y' ELSE 'N' END AS independent_contractor,
            CASE WHEN w.worker_type='Seasonal' THEN 'Y' ELSE 'N' END AS seasonal_employee,
            CASE WHEN w.worker_type='Seasonal' THEN 'Y' ELSE 'N' END AS seasonal_employee_local,
            CASE WHEN w.work_from_home_flag THEN 'Y' ELSE 'N' END AS wfh_indicator,
            CASE WHEN w.post_w2_indicator THEN 'Y' ELSE 'N' END AS ee_post_indicator,
            CASE WHEN w.statutory_flag THEN 'Y' ELSE 'N' END AS statutory_flag,
            DECODE(w.remuneration_basis,'Hourly' ,'H','Salaried','S') AS remuneration_basis,
            CASE WHEN w.ownership_percent>50 THEN 'Y'  ELSE 'N' END AS family_status,
            w.employee_id, w.pay_rate_amount, w.job_title
        FROM {self.schema}.worker w
        LEFT JOIN {self.schema}.worker_address wa ON w.worker_sk = wa.worker_sk AND wa.type IN ('Work', 'Home')
        WHERE w.company_code = '{company_code}' AND w.branch_code = '{branch_code}'
        AND EXISTS(SELECT 1 FROM {self.schema}.worker_tax_qtr_snapshot wt WHERE wt.worker_sk=w.worker_sk AND wt.year={year} AND wt.quarter={quarter})
        GROUP BY w.worker_sk, w.branch_code, w.company_code, w.family_name, w.given_name,
                 w.ssn, w.birth_date, w.hire_date, w.termination_date, w.gender, w.department_code, w.middle_name,
                 w.retirement_plan_indicator, w.third_party_sick_pay_indicator, w.replacement_worker,
                 w.corporate_officer_indicator, w.w2_special_handle_indicator, w.medical_coverage_indicator,
                 w.suppress_w2_print_indicator, w.worker_type,w.work_from_home_flag,w.employee_id,w.pay_rate_amount,
                 w.post_w2_indicator,w.remuneration_basis,w.job_title,w.ownership_percent,w.statutory_flag
        """
        return self._execute_query(query, timeout_seconds=180)

    def query_all_worker_tax(self, company_code, year, quarter) -> DataFrame:
        """Query tax data for company with latest payroll_run_sk for QTD/YTD amounts."""
        company_code = self._validate_input(company_code)
        year = self._validate_input(str(year), max_length=4)
        quarter = self._validate_input(str(quarter), max_length=1)
        query = f"""
        WITH latest_payroll AS (
            SELECT wt.worker_sk, wt.organization_unit_sk, wt.state_code, wt.local_code,
                   wt.tax_type, wt.is_employer_tax, wt.year, wt.quarter,
                   MAX(wt.payroll_run_sk) as max_payroll_run_sk
            FROM {self.schema}.worker_tax_qtr_snapshot wt
            INNER JOIN {self.schema}.worker w ON wt.worker_sk = w.worker_sk
            WHERE w.company_code = '{company_code}'
                AND wt.year = '{year}'
                AND wt.quarter = '{quarter}'
            GROUP BY wt.worker_sk, wt.organization_unit_sk, wt.state_code, wt.local_code,
                     wt.tax_type, wt.year, wt.quarter, wt.is_employer_tax
        ),
        latest_qtd_ytd AS (
            SELECT wt.worker_sk, wt.state_code, wt.local_code, wt.tax_type,
                CASE
                    WHEN wt.state_code IS NULL THEN 'F'
                    WHEN wt.local_code IS NULL THEN wt.state_code
                    ELSE wt.state_code || RIGHT(wt.local_code, 4)
                END AS jurisdiction, wt.year, wt.quarter, wt.branch_code, wt.company_code,
                wt.is_employer_tax, wt.out_of_state,
                wt.tax_rate, wt.hours_worked,
                wt.qtd_amount, wt.qtd_taxable_amount, wt.qtd_subject_amount, wt.qtd_gross_wages,
                wt.ytd_amount, wt.ytd_taxable_amount, wt.ytd_subject_amount, wt.ytd_gross_wages,
                wt.qtd_overtime_amount, wt.ytd_overtime_amount, wt.lived_in_code
            FROM {self.schema}.worker_tax_qtr_snapshot wt
            INNER JOIN latest_payroll lp
                ON wt.worker_sk = lp.worker_sk
                AND wt.payroll_run_sk = lp.max_payroll_run_sk
                AND wt.organization_unit_sk = lp.organization_unit_sk
                AND COALESCE(wt.state_code, '') = COALESCE(lp.state_code, '')
                AND COALESCE(wt.local_code, '') = COALESCE(lp.local_code, '')
                AND wt.tax_type = lp.tax_type
                AND wt.is_employer_tax = lp.is_employer_tax
                AND wt.year = lp.year
                AND wt.quarter = lp.quarter
        )
        SELECT lqy.worker_sk, lqy.jurisdiction, lqy.tax_type, lqy.year, lqy.quarter,
               DECODE(wtp.filing_status, 'MarriedFilingJointly', 'M', 'HeadOfHousehold', 'H', 'S') as filing_status,
               wtp.number_of_allowances, wtp.sui_exempt_flag, wtp.sdi_exempt_flag,
               COALESCE(lqy.qtd_amount, 0) as qtd_amount,
               COALESCE(lqy.qtd_taxable_amount, 0) as qtd_taxable_amount,
               COALESCE(lqy.qtd_subject_amount, 0) as qtd_subject_amount,
               COALESCE(lqy.qtd_gross_wages, 0) as qtd_gross_wages,
               COALESCE(lqy.qtd_overtime_amount, 0) as qtd_overtime_amount,
               COALESCE(lqy.ytd_amount, 0) as ytd_amount,
               COALESCE(lqy.ytd_taxable_amount, 0) as ytd_taxable_amount,
               COALESCE(lqy.ytd_subject_amount, 0) as ytd_subject_amount,
               COALESCE(lqy.ytd_gross_wages, 0) as ytd_gross_wages,
               COALESCE(lqy.ytd_overtime_amount, 0) as ytd_overtime_amount,
               CASE WHEN COALESCE(lqy.qtd_amount, 0) != 0 THEN 1 ELSE NULL END as qtd_amount_count,
               CASE WHEN COALESCE(lqy.ytd_amount, 0) != 0 THEN 1 ELSE NULL END as ytd_amount_count,
               lqy.tax_rate, lqy.hours_worked, lqy.is_employer_tax, lqy.lived_in_code,
               COALESCE(CASE WHEN lqy.out_of_state IS NOT NULL
                   THEN JSON_EXTRACT_PATH_TEXT(lqy.out_of_state::VARCHAR, 'qtdGrossWages')
               END, '0') as oos_qtd_gross_wages,
               COALESCE(CASE WHEN lqy.out_of_state IS NOT NULL
                   THEN JSON_EXTRACT_PATH_TEXT(lqy.out_of_state::VARCHAR, 'ytdGrossWages')
               END, '0') as oos_ytd_gross_wages,
               COALESCE(CASE WHEN lqy.out_of_state IS NOT NULL
                   THEN JSON_EXTRACT_PATH_TEXT(lqy.out_of_state::VARCHAR, 'qtdTaxableAmount')
               END, '0') as oos_qtd_taxable_amount,
               COALESCE(CASE WHEN lqy.out_of_state IS NOT NULL
                   THEN JSON_EXTRACT_PATH_TEXT(lqy.out_of_state::VARCHAR, 'ytdTaxableAmount')
               END, '0') as oos_ytd_taxable_amount
        FROM latest_qtd_ytd lqy
        LEFT JOIN {self.schema}.worker_tax_profile wtp ON wtp.worker_sk = lqy.worker_sk
            AND COALESCE(wtp.state_code, '') = COALESCE(lqy.state_code, '')
            AND COALESCE(wtp.local_code, '') = COALESCE(lqy.local_code, '')
            AND wtp.branch_code = lqy.branch_code
            AND wtp.company_code = lqy.company_code
        ORDER BY lqy.worker_sk, lqy.state_code NULLS FIRST, lqy.local_code
        """
        return self._execute_query(query, timeout_seconds=300)

    def query_organization(self, company_code):
        company_code = self._validate_input(company_code)
        query = (
            f"SELECT branch_code, company_code FROM {self.schema}.organization_unit "
            f"WHERE company_code = '{company_code}' LIMIT 1"
        )
        try:
            df = self._execute_query(query)
            if not df.isEmpty():
                row = df.first()
                return row["branch_code"], row["company_code"]
        except Exception as e:
            logger.error(f"Error querying organization: {e}")
        return None, None

    def query_queued_outbound_files(self) -> DataFrame:
        query = (
            f"SELECT batch_id, site_id, year, quarter, window_start, window_end "
            f"FROM {self.schema}.outbound_file "
            f"WHERE status = '{OutboundFileStatus.QUEUED}' AND file_type = 'QUARTER'"
        )
        return self._execute_query(query)

    def query_site_organizations(self, site_ids) -> DataFrame:
        site_ids_str = "','".join([self._validate_input(str(sid)) for sid in site_ids])
        query = (
            f"SELECT DISTINCT branch_code, company_code, site_id "
            f"FROM {self.schema}.organization_unit WHERE site_id IN ('{site_ids_str}')"
        )
        return self._execute_query(query)

    def _get_write_connection(self):
        if self._write_conn is None or self._write_conn.isClosed():
            from py4j.java_gateway import java_import

            java_import(self.spark._jvm, "java.sql.DriverManager")
            connection_props = self.spark._jvm.java.util.Properties()
            connection_props.setProperty("user", self.username)
            connection_props.setProperty("password", self.password)
            connection_props.setProperty("loginTimeout", "30")
            connection_props.setProperty("connectTimeout", "30000")
            connection_props.setProperty("socketTimeout", "300000")
            self._write_conn = self.spark._jvm.DriverManager.getConnection(self.jdbc_url, connection_props)
            self._write_conn.setAutoCommit(False)
            logger.info("Created new JDBC write connection")
        return self._write_conn

    def _execute_write(self, query, params=None):
        import time

        write_start = time.time()
        stmt = None
        try:
            conn = self._get_write_connection()
            timeout_stmt = conn.createStatement()
            timeout_stmt.execute("SET statement_timeout = 120000")
            timeout_stmt.close()
            if params:
                stmt = conn.prepareStatement(query)
                for i, param in enumerate(params, 1):
                    if isinstance(param, int):
                        stmt.setInt(i, param)
                    else:
                        stmt.setString(i, str(param))
                stmt.execute()
            else:
                stmt = conn.createStatement()
                stmt.execute(query)
            conn.commit()
            logger.info(f"Write operation completed successfully in {time.time() - write_start:.2f}s")
        except Exception as e:
            logger.error(f"Write operation failed after {time.time() - write_start:.2f}s: {e}")
            try:
                if self._write_conn:
                    self._write_conn.rollback()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {rollback_error}")
            self.close_write_connection()
            raise
        finally:
            if stmt:
                try:
                    stmt.close()
                except Exception as close_error:
                    logger.warning(f"Failed to close statement: {close_error}")

    def close_write_connection(self):
        if self._write_conn is not None:
            try:
                self._write_conn.close()
            except Exception:
                pass
            self._write_conn = None

    def create_outbound_file_entry(self, batch_id, site_id, year, quarter, window_start, window_end):
        query = (
            f"INSERT INTO {self.schema}.outbound_file"
            f" (batch_id, site_id, window_start, window_end, status, file_type, year, quarter, created_timestamp, updated_timestamp)"
            f" VALUES (?, ?, ?, ?, '{OutboundFileStatus.GENERATING}', 'QUARTER', ?, ?, GETDATE(), GETDATE())"
        )
        self._execute_write(query, [str(batch_id), str(site_id), str(window_start), str(window_end), int(year), int(quarter)])

    def update_outbound_file_success(self, batch_id, site_id, year, quarter, file_path, record_count, file_name, s3_key=None):
        s3_key_value = s3_key if s3_key else file_path
        query = (
            f"UPDATE {self.schema}.outbound_file"
            f" SET status = '{OutboundFileStatus.GENERATED}', s3_key = ?, record_count = ?, outbound_file_name = ?, updated_timestamp = GETDATE()"
            f" WHERE batch_id = ? AND site_id = ? AND year = ? AND quarter = ?"
        )
        self._execute_write(query, [str(s3_key_value), int(record_count), str(file_name), str(batch_id), str(site_id), int(year), int(quarter)])

    def update_outbound_file_failure(self, batch_id, site_id, year, quarter, error_message):
        error_message = str(error_message)[:2000]
        query = (
            f"UPDATE {self.schema}.outbound_file"
            f" SET status = '{OutboundFileStatus.FAILED}', error_message = ?, updated_timestamp = GETDATE()"
            f" WHERE batch_id = ? AND site_id = ? AND year = ? AND quarter = ?"
        )
        self._execute_write(query, [error_message, str(batch_id), str(site_id), int(year), int(quarter)])

    def update_outbound_file_status(self, batch_id, site_id, year, quarter, status):
        query = (
            f"UPDATE {self.schema}.outbound_file"
            f" SET status = ?, updated_timestamp = GETDATE()"
            f" WHERE batch_id = ? AND site_id = ? AND year = ? AND quarter = ?"
        )
        self._execute_write(query, [str(status), str(batch_id), str(site_id), int(year), int(quarter)])

    def update_outbound_file_complete(self, batch_id, site_id, year, quarter, file_path, record_count, file_name, s3_key=None):
        self.update_outbound_file_success(batch_id, site_id, year, quarter, file_path, record_count, file_name, s3_key)


class PostgresConnection:
    def __init__(self, spark, host, port, database, schema, username, password):
        self.spark = spark
        self.host = host
        self.port = port
        self.database = database
        self.schema = schema
        self.username = username
        self.password = password
        self.jdbc_url = f"jdbc:postgresql://{host}:{port}/{database}"

    @staticmethod
    def _validate_input(value, max_length=50):
        if not isinstance(value, str):
            value = str(value)
        if len(value) > max_length:
            raise ValueError(f"Input exceeds max length of {max_length}")
        if not re.match(r"^[a-zA-Z0-9_\-\.\s:/&]+$", value):
            raise ValueError(f"Input contains disallowed characters: {value[:20]}")
        return value

    def _execute_query(self, query):
        import time

        logger.info(f"Executing PostgreSQL query: {query[:100]}...")
        query_start = time.time()
        try:
            result = (
                self.spark.read.format("jdbc")
                .option("url", self.jdbc_url)
                .option("query", query)
                .option("user", self.username)
                .option("password", self.password)
                .option("driver", "org.postgresql.Driver")
                .option("connectTimeout", "30")
                .option("socketTimeout", "120")
                .option("loginTimeout", "30")
                .load()
            )
            logger.info(f"PostgreSQL query execution completed in {time.time() - query_start:.2f}s")
            return result
        except Exception as e:
            logger.error(f"PostgreSQL query failed after {time.time() - query_start:.2f}s: {e}")
            raise

    def query_table_count(self, table_name) -> int:
        table_name = self._validate_input(table_name, max_length=100)
        query = f"SELECT COUNT(*) as row_count FROM {table_name}"
        df = self._execute_query(query)
        return df.first()["row_count"]

    @cached_gsi_query(ttl_seconds=4 * 3600)
    def query_gsi_field_mappings(self) -> DataFrame:
        query = f"""
        SELECT DISTINCT
            field_code,
            field_length,
            data_type,
            decimal_places,
            signed,
            category_1,
            category_2
        FROM {self.schema}.GI1
        ORDER BY field_code
        """
        df = self._execute_query(query)
        count = df.count()
        logger.info(f"Retrieved {count} GSI field mappings from database")
        return df

    @cached_gsi_query(ttl_seconds=4 * 3600)
    def query_gsi_level_mappings(self, field_codes) -> DataFrame:
        codes_str = ",".join([f"'{self._validate_input(c)}'" for c in field_codes])
        query = f"""
        SELECT DISTINCT field_code, record_code
        FROM {self.schema}.GI2
        WHERE file_code = 'Q' AND field_code IN ({codes_str})
        ORDER BY field_code
        """
        df = self._execute_query(query)
        count = df.count()
        logger.info(f"Retrieved {count} GI2 level mappings from database")
        return df
