SET search_path TO onetax, public;

INSERT INTO organization_unit (
  organization_unit_sk,
  branch_code,
  company_code,
  site_id,
  organization_name
) VALUES
  (227, 'ST', 'GE59', 'GE59', 'Global Modern Services Inc')
ON CONFLICT (organization_unit_sk) DO NOTHING;

INSERT INTO worker (
  worker_sk,
  branch_code,
  company_code,
  family_name,
  given_name,
  middle_name,
  ssn,
  birth_date,
  hire_date,
  termination_date,
  gender,
  department_code,
  retirement_plan_indicator,
  third_party_sick_pay_indicator,
  replacement_worker,
  corporate_officer_indicator,
  w2_special_handle_indicator,
  medical_coverage_indicator,
  suppress_w2_print_indicator,
  worker_type,
  work_from_home_flag,
  post_w2_indicator,
  statutory_flag,
  remuneration_basis,
  ownership_percent,
  employee_id,
  pay_rate_amount,
  job_title
) VALUES
  (
    361, 'ST', 'GE59', 'Jackson', 'Cuneal', 'A', '123456789',
    DATE '1986-01-31', DATE '2023-12-31', NULL, 'M', 'D01',
    false, false, false, false, false, true, false, 'Employee',
    true, false, false, 'Salaried', 0, 'EMP361', 42.5000,
    'Regional Sales Manager, Central US'
  )
ON CONFLICT (worker_sk) DO NOTHING;

INSERT INTO worker_address (
  worker_sk,
  type,
  line_one,
  city_name,
  state_code,
  postal_code
) VALUES
  (361, 'Work', '200 East Randolph Street', 'Chicago', 'IL', '60605-0002'),
  (361, 'Home', '75401 Barrett Street', 'Cypress', 'CA', '90630')
ON CONFLICT DO NOTHING;

INSERT INTO worker_tax_qtr_snapshot (
  worker_sk,
  organization_unit_sk,
  payroll_run_sk,
  state_code,
  local_code,
  tax_type,
  is_employer_tax,
  year,
  quarter,
  branch_code,
  company_code,
  out_of_state,
  tax_rate,
  hours_worked,
  qtd_amount,
  qtd_taxable_amount,
  qtd_subject_amount,
  qtd_gross_wages,
  ytd_amount,
  ytd_taxable_amount,
  ytd_subject_amount,
  ytd_gross_wages,
  qtd_overtime_amount,
  ytd_overtime_amount,
  lived_in_code
) VALUES
  (361, 227, 95, NULL, NULL, 'FIT', false, 2026, 1, 'ST', 'GE59', NULL, 0.0000, 40.00, 123.45, 3456.67, 3456.67, 3456.67, 456.78, 4567.89, 4567.89, 4567.89, 0, 0, NULL),
  (361, 227, 95, NULL, NULL, 'SocialSecurity', false, 2026, 1, 'ST', 'GE59', NULL, 0.0620, 40.00, 44.45, 1200.00, 1200.00, 1200.00, 100.00, 1500.00, 1500.00, 1500.00, 0, 0, NULL),
  (361, 227, 95, 'CA', NULL, 'SIT', false, 2026, 1, 'ST', 'GE59', NULL, 0.0000, 40.00, 0.00, 2345.67, 2345.67, 2345.67, 0.00, 7000.00, 7000.00, 7000.00, 0, 0, NULL),
  (361, 227, 95, 'IL', NULL, 'SIT', false, 2026, 1, 'ST', 'GE59', NULL, 0.0000, 40.00, 0.00, 1457.86, 1457.86, 1457.86, 0.00, 9304.56, 9304.56, 9304.56, 0, 0, NULL),
  (361, 227, 95, 'PA', '0001234567', 'CIT', false, 2026, 1, 'ST', 'GE59', '{"qtdGrossWages":"346.36","ytdGrossWages":"346.36","qtdTaxableAmount":"238.67","ytdTaxableAmount":"238.67"}', 0.0100, 40.00, 0.00, 238.67, 238.67, 346.36, 0.00, 700.00, 700.00, 700.00, 0, 0, '01461046')
ON CONFLICT DO NOTHING;

INSERT INTO worker_tax_profile (
  worker_sk,
  state_code,
  local_code,
  branch_code,
  company_code,
  filing_status,
  number_of_allowances,
  sui_exempt_flag,
  sdi_exempt_flag
) VALUES
  (361, NULL, NULL, 'ST', 'GE59', 'Single', 0, 'N', 'N'),
  (361, 'CA', NULL, 'ST', 'GE59', 'Single', 1, 'N', 'N'),
  (361, 'IL', NULL, 'ST', 'GE59', 'Single', 1, 'N', 'N'),
  (361, 'PA', '0001234567', 'ST', 'GE59', 'Single', 0, 'N', 'N')
ON CONFLICT DO NOTHING;

INSERT INTO outbound_file (
  batch_id,
  site_id,
  window_start,
  window_end,
  status,
  file_type,
  year,
  quarter
) VALUES
  ('BATCH-LOCAL-001', 'GE59', TIMESTAMP '2026-01-01 00:00:00', TIMESTAMP '2026-03-31 23:59:59', 'QUEUED', 'QUARTER', 2026, 1)
ON CONFLICT DO NOTHING;

INSERT INTO error_catalog (
  error_code,
  legacy_error_code,
  name,
  error_type,
  category,
  impacts_deposit,
  impacts_filing,
  effective_from
) VALUES
  ('FEIN_IS_MISSING', 'E02', 'FEIN is missing', 'TAX_ID', 'Registration', false, true, DATE '2026-01-01'),
  ('FEIN_NOT_CORRECT', '57', 'FEIN is incorrect', 'TAX_ID', 'Registration', false, false, DATE '2026-01-01'),
  ('CA_WAGE_PLAN_MISSING', 'E01', 'California wage plan code is missing', 'CA_WAGE_PLAN', 'WagePlan', false, true, DATE '2026-01-01'),
  ('SSN_INVALID', '02', 'SSN invalid', 'SSN', 'Validation', false, true, DATE '2026-01-01')
ON CONFLICT (error_code) DO NOTHING;

INSERT INTO company_errors (
  company_error_sk,
  organization_unit_sk,
  payroll_run_sk,
  error_code,
  impacted_count,
  resolution_status,
  write_status,
  state_code,
  local_code,
  tax_type,
  created_date_time
) VALUES
  (1, 227, 95, 'FEIN_IS_MISSING', 1, 'Open', 'PENDING', NULL, NULL, NULL, TIMESTAMP '2026-03-13 10:00:00'),
  (2, 227, 95, 'CA_WAGE_PLAN_MISSING', 1, 'Open', 'PENDING', 'CA', NULL, 'SIT', TIMESTAMP '2026-03-13 10:05:00')
ON CONFLICT (company_error_sk) DO NOTHING;
