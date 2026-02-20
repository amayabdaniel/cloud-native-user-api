locals {
  env_vars = read_terragrunt_config(find_in_parent_folders("env.hcl"))

  environment  = local.env_vars.locals.environment
  project_name = local.env_vars.locals.project_name
  aws_region   = local.env_vars.locals.aws_region
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"

  default_tags {
    tags = {
      Project     = "${local.project_name}"
      Environment = "${local.environment}"
      ManagedBy   = "terragrunt"
    }
  }
}
EOF
}

remote_state {
  backend = "s3"
  config = {
    bucket         = "${local.project_name}-tfstate-${local.environment}"
    key            = "${path_relative_to_include()}/terraform.tfstate"
    region         = local.aws_region
    encrypt        = true
    dynamodb_table = "${local.project_name}-tflock-${local.environment}"
  }
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
}

inputs = {
  environment  = local.environment
  project_name = local.project_name
  aws_region   = local.aws_region
}
