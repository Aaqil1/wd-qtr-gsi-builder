data "aws_vpc" "main" {
  state = "available"

  tags = {
    Name = "vpc-*"
  }
}

data "aws_secretsmanager_secret" "databricks_token" {
  name = var.databricks_token_secret_name
}

data "aws_secretsmanager_secret_version" "databricks_token" {
  secret_id = data.aws_secretsmanager_secret.databricks_token.id
}

data "aws_secretsmanager_secret" "app_token" {
  name = var.app_token
}

data "aws_secretsmanager_secret_version" "app_token" {
  secret_id = data.aws_secretsmanager_secret.app_token.id
}
