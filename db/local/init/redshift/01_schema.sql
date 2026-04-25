CREATE SCHEMA IF NOT EXISTS onetax;

SET search_path TO onetax, public;

CREATE OR REPLACE FUNCTION public.getdate()
RETURNS timestamp
LANGUAGE sql
AS $$
  SELECT CURRENT_TIMESTAMP::timestamp;
$$;

CREATE OR REPLACE FUNCTION public.decode(
  expr text,
  search1 text,
  result1 text,
  search2 text,
  result2 text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN expr = search1 THEN result1
    WHEN expr = search2 THEN result2
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION public.decode(
  expr text,
  search1 text,
  result1 text,
  search2 text,
  result2 text,
  default_result text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN expr = search1 THEN result1
    WHEN expr = search2 THEN result2
    ELSE default_result
  END;
$$;

CREATE OR REPLACE FUNCTION public.json_extract_path_text(json_text text, key text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN json_text IS NULL OR btrim(json_text) = '' THEN NULL
    ELSE json_text::jsonb ->> key
  END;
$$;

CREATE TABLE IF NOT EXISTS organization_unit (
  organization_unit_sk bigint PRIMARY KEY,
  branch_code varchar(10) NOT NULL,
  company_code varchar(20) NOT NULL,
  site_id varchar(50) NOT NULL,
  organization_name varchar(255),
  created_timestamp timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS worker (
  worker_sk bigint PRIMARY KEY,
  branch_code varchar(10) NOT NULL,
  company_code varchar(20) NOT NULL,
  family_name varchar(100),
  given_name varchar(100),
  middle_name varchar(100),
  ssn varchar(20),
  birth_date date,
  hire_date date,
  termination_date date,
  gender varchar(20),
  department_code varchar(50),
  retirement_plan_indicator boolean DEFAULT false,
  third_party_sick_pay_indicator boolean DEFAULT false,
  replacement_worker boolean DEFAULT false,
  corporate_officer_indicator boolean DEFAULT false,
  w2_special_handle_indicator boolean DEFAULT false,
  medical_coverage_indicator boolean DEFAULT false,
  suppress_w2_print_indicator boolean DEFAULT false,
  worker_type varchar(50),
  work_from_home_flag boolean DEFAULT false,
  post_w2_indicator boolean DEFAULT false,
  statutory_flag boolean DEFAULT false,
  remuneration_basis varchar(50),
  ownership_percent numeric(5,2) DEFAULT 0,
  employee_id varchar(50),
  pay_rate_amount numeric(18,4),
  job_title varchar(255)
);

CREATE TABLE IF NOT EXISTS worker_address (
  worker_address_sk bigserial PRIMARY KEY,
  worker_sk bigint NOT NULL REFERENCES worker(worker_sk),
  type varchar(20) NOT NULL,
  line_one varchar(255),
  city_name varchar(100),
  state_code varchar(10),
  postal_code varchar(20)
);

CREATE TABLE IF NOT EXISTS worker_tax_qtr_snapshot (
  worker_tax_qtr_snapshot_sk bigserial PRIMARY KEY,
  worker_sk bigint NOT NULL REFERENCES worker(worker_sk),
  organization_unit_sk bigint NOT NULL REFERENCES organization_unit(organization_unit_sk),
  payroll_run_sk bigint NOT NULL,
  state_code varchar(10),
  local_code varchar(50),
  tax_type varchar(100) NOT NULL,
  is_employer_tax boolean DEFAULT false,
  year integer NOT NULL,
  quarter integer NOT NULL,
  branch_code varchar(10) NOT NULL,
  company_code varchar(20) NOT NULL,
  out_of_state jsonb,
  tax_rate numeric(18,6),
  hours_worked numeric(18,2),
  qtd_amount numeric(18,2),
  qtd_taxable_amount numeric(18,2),
  qtd_subject_amount numeric(18,2),
  qtd_gross_wages numeric(18,2),
  ytd_amount numeric(18,2),
  ytd_taxable_amount numeric(18,2),
  ytd_subject_amount numeric(18,2),
  ytd_gross_wages numeric(18,2),
  qtd_overtime_amount numeric(18,2),
  ytd_overtime_amount numeric(18,2),
  lived_in_code varchar(50)
);

CREATE TABLE IF NOT EXISTS worker_tax_profile (
  worker_tax_profile_sk bigserial PRIMARY KEY,
  worker_sk bigint NOT NULL REFERENCES worker(worker_sk),
  state_code varchar(10),
  local_code varchar(50),
  branch_code varchar(10) NOT NULL,
  company_code varchar(20) NOT NULL,
  filing_status varchar(50),
  number_of_allowances integer,
  sui_exempt_flag varchar(5),
  sdi_exempt_flag varchar(5)
);

CREATE TABLE IF NOT EXISTS outbound_file (
  outbound_file_sk bigserial PRIMARY KEY,
  batch_id varchar(100) NOT NULL,
  site_id varchar(50) NOT NULL,
  window_start timestamp,
  window_end timestamp,
  status varchar(50) NOT NULL,
  file_type varchar(50) NOT NULL,
  year integer NOT NULL,
  quarter integer NOT NULL,
  s3_key varchar(1024),
  record_count integer,
  outbound_file_name varchar(255),
  error_message varchar(4000),
  created_timestamp timestamp DEFAULT CURRENT_TIMESTAMP,
  updated_timestamp timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS error_catalog (
  error_code varchar(100) PRIMARY KEY,
  legacy_error_code varchar(50),
  name varchar(255) NOT NULL,
  error_type varchar(100),
  category varchar(100),
  impacts_deposit boolean DEFAULT false,
  impacts_filing boolean DEFAULT false,
  created_date_time timestamp DEFAULT CURRENT_TIMESTAMP,
  updated_date_time timestamp DEFAULT CURRENT_TIMESTAMP,
  effective_from date
);

CREATE TABLE IF NOT EXISTS company_errors (
  company_error_sk bigint PRIMARY KEY,
  organization_unit_sk bigint REFERENCES organization_unit(organization_unit_sk),
  payroll_run_sk bigint,
  error_code varchar(100) REFERENCES error_catalog(error_code),
  impacted_count integer,
  resolution_status varchar(50),
  write_status varchar(50),
  state_code varchar(10),
  local_code varchar(50),
  tax_type varchar(100),
  created_date_time timestamp DEFAULT CURRENT_TIMESTAMP,
  resolved_date_time timestamp
);

CREATE INDEX IF NOT EXISTS idx_outbound_file_status
  ON outbound_file(status, file_type, site_id, year, quarter);

CREATE INDEX IF NOT EXISTS idx_organization_unit_site
  ON organization_unit(site_id, branch_code, company_code);

CREATE INDEX IF NOT EXISTS idx_worker_branch_company
  ON worker(branch_code, company_code);

CREATE INDEX IF NOT EXISTS idx_worker_tax_qtr_lookup
  ON worker_tax_qtr_snapshot(company_code, branch_code, year, quarter, worker_sk);

CREATE INDEX IF NOT EXISTS idx_worker_tax_profile_lookup
  ON worker_tax_profile(worker_sk, branch_code, company_code, state_code, local_code);

CREATE INDEX IF NOT EXISTS idx_company_errors_context
  ON company_errors(organization_unit_sk, payroll_run_sk, resolution_status, write_status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_address_seed
  ON worker_address(worker_sk, type, line_one, city_name, state_code, postal_code);

CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_tax_qtr_snapshot_seed
  ON worker_tax_qtr_snapshot(
    worker_sk,
    organization_unit_sk,
    payroll_run_sk,
    COALESCE(state_code, ''),
    COALESCE(local_code, ''),
    tax_type,
    is_employer_tax,
    year,
    quarter
  );

CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_tax_profile_seed
  ON worker_tax_profile(
    worker_sk,
    COALESCE(state_code, ''),
    COALESCE(local_code, ''),
    branch_code,
    company_code
  );

CREATE UNIQUE INDEX IF NOT EXISTS ux_outbound_file_seed
  ON outbound_file(batch_id, site_id, year, quarter);
