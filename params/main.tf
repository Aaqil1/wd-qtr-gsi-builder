terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "1.51.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      ACRONYM          = var.app_name
      Resource_Owner_1 = var.lead_email
      Resource_Owner_2 = var.team_email
      Application      = var.app_name
      Domain           = "wd-qtr-gsi"
    }
  }
}
