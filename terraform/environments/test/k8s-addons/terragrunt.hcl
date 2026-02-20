include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/k8s-addons"
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id = "vpc-mock"
  }
}

dependency "eks" {
  config_path = "../eks"

  mock_outputs = {
    cluster_name                       = "mock-cluster"
    cluster_endpoint                   = "https://mock-endpoint"
    cluster_certificate_authority_data = "bW9jaw=="
    oidc_provider_arn                  = "arn:aws:iam::123456789012:oidc-provider/mock"
    oidc_provider                      = "oidc.eks.us-east-1.amazonaws.com/id/MOCK"
  }
}

dependency "aurora" {
  config_path = "../aurora"

  mock_outputs = {
    cluster_endpoint         = "mock-aurora.cluster-xxx.us-east-1.rds.amazonaws.com"
    cluster_database_name    = "db1"
    cluster_master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock" }]
  }
}

dependency "elasticache" {
  config_path = "../elasticache"

  mock_outputs = {
    redis_endpoint = "mock-redis.xxx.0001.use1.cache.amazonaws.com"
    redis_port     = 6379
  }
}

generate "k8s_provider" {
  path      = "k8s-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
data "aws_eks_cluster_auth" "this" {
  name = var.cluster_name
}

provider "kubernetes" {
  host                   = var.cluster_endpoint
  cluster_ca_certificate = base64decode(var.cluster_ca_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = var.cluster_endpoint
    cluster_ca_certificate = base64decode(var.cluster_ca_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}
EOF
}

inputs = {
  cluster_name    = dependency.eks.outputs.cluster_name
  cluster_endpoint = dependency.eks.outputs.cluster_endpoint
  cluster_ca_data = dependency.eks.outputs.cluster_certificate_authority_data
  oidc_provider_arn = dependency.eks.outputs.oidc_provider_arn
  oidc_provider     = dependency.eks.outputs.oidc_provider
  vpc_id            = dependency.vpc.outputs.vpc_id

  aurora_endpoint          = dependency.aurora.outputs.cluster_endpoint
  aurora_database_name     = dependency.aurora.outputs.cluster_database_name
  aurora_master_secret_arn = dependency.aurora.outputs.cluster_master_user_secret[0].secret_arn

  redis_endpoint = dependency.elasticache.outputs.redis_endpoint
  redis_port     = dependency.elasticache.outputs.redis_port

  tags = {
    Project     = "cloud-native-user-api"
    Environment = "test"
    ManagedBy   = "terragrunt"
  }
}
