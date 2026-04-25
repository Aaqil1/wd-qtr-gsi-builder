CREATE SCHEMA IF NOT EXISTS onetax;

SET search_path TO onetax, public;

CREATE TABLE IF NOT EXISTS GI1 (
  field_code varchar(10) PRIMARY KEY,
  field_length integer NOT NULL,
  data_type varchar(5) NOT NULL,
  decimal_places integer,
  signed varchar(1),
  category_1 varchar(100),
  category_2 varchar(100)
);

CREATE TABLE IF NOT EXISTS GI2 (
  gi2_sk bigserial PRIMARY KEY,
  file_code varchar(10) NOT NULL,
  field_code varchar(10) NOT NULL,
  record_code varchar(10) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gi2_file_field
  ON GI2(file_code, field_code);

CREATE UNIQUE INDEX IF NOT EXISTS ux_gi2_seed
  ON GI2(file_code, field_code, record_code);
