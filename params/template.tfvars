# Environment Configuration Template
# Copy this file to <env>.tfvars and fill in the values

# Redshift Configuration
redshift_host         = "<redshift-host>"
redshift_port         = "5439"
redshift_database     = "onetaxredshift"
redshift_schema       = "onetax"
redshift_username     = "<username>"
redshift_password     = "<password>"
redshift_iam_role     = "arn:aws:iam::<account-id>:role/RedshiftS3AccessRole"
redshift_temp_s3_path = "redshift-unload-temp"

# Kafka Configuration
kafka_bootstrap_servers = "<kafka-broker-1>:9092,<kafka-broker-2>:9092"
kafka_input_topic       = "qtr-employee-commands"
kafka_output_topic      = "qtr-gsi-events"

# S3 Configuration
s3_bucket       = "<s3-bucket-name>"
s3_results_path = "quarterly-results"

# Application Configuration
app_name           = "WD_QTR_GSI_Builder_<ENV>"
max_parallel_tasks = 100
batch_size         = 100
max_workers        = 50

# AWS Configuration
aws_region = "us-east-1"
