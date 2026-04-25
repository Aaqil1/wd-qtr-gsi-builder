variable "databricks_host" {
  description = "The host of the Databricks workspace"
  type        = string
  default     = "https://adpdc-tech-ingestion-dev.cloud.databricks.com/"
}

variable "databricks_env" {
  description = "The Databricks environment"
  type        = string
  default     = "dit"
}

variable "databricks_token_secret_name" {
  description = "The name of the secret in AWS Secrets Manager that contains the Databricks token"
  type        = string
  default     = "cicd-databricks"
}

variable "databricks_nc_policy" {
  description = "The policy id of the Databricks cluster in NC mode"
  type        = string
}

variable "app_token" {
  description = "The name of the secret in AWS Secrets Manager that contains the app token"
  type        = string
  default     = "filing-databricks"
}

variable "databricks_job_secret" {
  description = "The name of the secret in AWS Secrets Manager that contains the Databricks job secret"
  default     = "wd_qtr_gsi_builder_job"
}

variable "env" {
  description = "The environment of the deployment"
  type        = string
  default     = "dit"
}

variable "spark_version" {
  description = "The version of Spark"
  type        = string
  default     = "16.4.x-scala2.13"
}

variable "databricks_node_type_id" {
  description = "The node type of the Databricks cluster"
  type        = string
  default     = "r6gd.xlarge"
}

variable "databricks_driver_type_id" {
  description = "The driver node type of the Databricks cluster"
  type        = string
  default     = "r6gd.xlarge"
}

variable "databricks_account_id" {
  description = "Databricks AWS account"
  type        = string
  default     = "708035784431"
}

variable "max_workers" {
  description = "The maximum number of workers in the Databricks cluster"
  type        = number
  default     = 16
}

variable "min_workers" {
  description = "The minimum number of workers in the Databricks cluster"
  type        = number
  default     = 4
}

variable "notification_email" {
  description = "The email address for notifications"
  type        = string
  default     = "CS.SmartLeague@ADP.com"
}

variable "databricks_policy_id" {
  description = "The policy id of the Databricks cluster"
  type        = string
  default     = "001B5A91A7ACE98D"
}

variable "region" {
  description = "The region where AWS operations will take place"
  type        = string
  default     = "us-east-1"
}

variable "account_id" {
  description = "The account_id where AWS operations will take place"
  type        = string
}

variable "vpc_type" {
  description = "The vpc_type where AWS operations will take place"
  type        = string
  default     = "internal"
}

variable "app_name" {
  description = "The app_name"
  type        = string
  default     = "wd-qtr-gsi-builder"
}

variable "is_dr" {
  description = "DR boolean flag"
  type        = bool
  default     = false
}

variable "service_principal_name" {
  description = "service principal name"
  type        = string
  default     = "6c90b523-95ce-4385-8c67-e3746157ffef"
}

variable "uc_enabled" {
  description = "UC Cluster?"
  type        = bool
  default     = true
}

variable "ssh_key_kms_alias" {
  description = "KMS key alias for SSH key encryption in Secrets Manager"
  type        = string
  default     = "alias/adp/secretsmanager/one-tax"
}

variable "splunk_forwarder_version" {
  description = "The splunk forwarder version"
  type        = string
  default     = "latest"
}

variable "splunk_client" {
  description = "The splunk client"
  type        = string
  default     = "ONE-TAX-DATABRICKS-WORKER-NODE"
}

variable "splunk_host" {
  description = "The splunk host"
  type        = string
  default     = "c11dt01slvds001.es.ad.adp.com:8089"
}

variable "splunk_enabled" {
  description = "Enable or disable Splunk forwarder on Databricks clusters"
  type        = bool
  default     = true
}

variable "bucket" {
  description = "S3 bucket for Databricks logs"
  type        = string
}

variable "databricks_job_name" {
  description = "The name of the Databricks job"
  type        = string
  default     = "wd_qtr_gsi_builder"
}

variable "lead_email" {
  description = "Lead email ID for Resource_Owner_1 tag"
  type        = string
  default     = "tax-team@ADP.com"
}

variable "team_email" {
  description = "Team email ID for Resource_Owner_2 tag"
  type        = string
  default     = "tax-team@ADP.com"
}
