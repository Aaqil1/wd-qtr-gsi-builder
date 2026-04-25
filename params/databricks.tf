provider "databricks" {
  host  = var.databricks_host
  token = local.token
}

provider "local" {}

data "external" "pom_version" {
  program = ["bash", "-c", <<EOT
    version=$(awk -F'"' '/version *= */ {print $2; exit}' pyproject.toml)
    echo "{\"version\": \"$${version}\"}"
  EOT
  ]
}

locals {
  job_full_name    = format("%s_job_%s", var.databricks_job_name, var.env)
  pom_value        = data.external.pom_version.result["version"]
  version          = regex("([0-9]+\\.[0-9]+\\.[0-9]+)(-snapshot)?", local.pom_value)[0]
  profile_name     = var.uc_enabled ? "uci-datacloud-dataplatform-unitycatalog_automation" : "scs-n8-dev"
  databricks_env   = replace(var.env, "/[0-9]+/", "")
  permission_level = "CAN_MANAGE"
  token            = jsondecode(data.aws_secretsmanager_secret_version.databricks_token.secret_string).token
  cluster_log_conf = {
    s3 = {
      destination = "s3://${var.bucket}/databricks/scs/scs-n8-dev"
      region      = "us-east-1"
    }
  }
}

resource "databricks_job" "wd_qtr_gsi_builder_job" {
  name = local.job_full_name

  run_as {
    service_principal_name = var.service_principal_name
  }

  job_cluster {
    job_cluster_key = format("%s_job_cluster_%s", var.databricks_job_name, var.env)

    new_cluster {
      num_workers            = 1
      spark_version          = var.spark_version
      node_type_id           = var.databricks_node_type_id
      driver_node_type_id    = var.databricks_driver_type_id
      enable_elastic_disk    = true
      data_security_mode     = var.uc_enabled ? "SINGLE_USER" : "NONE"
      policy_id              = var.uc_enabled ? var.databricks_nc_policy : var.databricks_policy_id

      dynamic "cluster_log_conf" {
        for_each = [local.cluster_log_conf]
        content {
          s3 {
            destination = cluster_log_conf.value.s3.destination
            region      = cluster_log_conf.value.s3.region
          }
        }
      }

      custom_tags = {
        Function       = "wd-qtr-gsi-builder"
        Environment    = var.env
        ResourceOwner1 = "Datacloud DS Architecture"
        OwnerDetails   = "DS.ARCH@ADP.COM"
        Group          = "scs-n8-dev"
      }

      spark_conf = {
        "spark.speculation"                       = true
        "spark.streaming.stopGracefullyOnShutdown" = true
      }

      spark_env_vars = {
        ENV             = var.env
        LIFECYCLE_ENV   = var.env
        KINESIS_DS_POLL = "Y"
        ADP_APP_NAME    = var.app_name
        AWS_REGION      = var.region
      }

      aws_attributes {
        availability           = "SPOT_WITH_FALLBACK"
        zone_id                = "auto"
        instance_profile_arn   = "arn:aws:iam::${var.databricks_account_id}:instance-profile/${local.databricks_env}-${local.profile_name}-cdktf"
        spot_bid_price_percent = 80
        ebs_volume_count       = 0
        first_on_demand        = 2
      }

      autoscale {
        max_workers = var.max_workers
        min_workers = var.min_workers
      }
    }
  }

  email_notifications {
    on_start   = [var.notification_email]
    on_success = [var.notification_email]
    on_failure = [var.notification_email]
  }

  tags = {
    DatabricksGroup = "scs-n8-dev"
    BusinessUnit    = "scs"
    Application     = "scs-n8-dev"
    Environment     = local.databricks_env
  }

  max_concurrent_runs = 10
  format              = "MULTI_TASK"

  task {
    task_key                   = format("%s_task_%s", var.databricks_job_name, var.env)
    job_cluster_key            = format("%s_job_cluster_%s", var.databricks_job_name, var.env)
    min_retry_interval_millis  = 25000

    python_wheel_task {
      package_name = "wd_qtr_gsi_builder"
      entry_point  = "main"
    }

    library {
      pypi {
        package = "wd-qtr-gsi-builder==${local.version}"
        repo    = "https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/cs-pypi/simple/"
      }
    }

    library {
      maven {
        coordinates = "com.amazon.redshift:redshift-jdbc42:2.1.0.30"
        repo        = "https://artifactory.us.caas.oneadp.com/artifactory/cs-maven"
      }
    }

    description = "WD Quarterly GSI Builder - ${var.env}"
  }
}

resource "databricks_permissions" "job_permission" {
  job_id = databricks_job.wd_qtr_gsi_builder_job.id

  access_control {
    group_name       = "scs-n8-dev-cdktf"
    permission_level = local.permission_level
  }

  access_control {
    group_name       = "admins-scs-n8-dev-cdktf"
    permission_level = local.permission_level
  }
}
