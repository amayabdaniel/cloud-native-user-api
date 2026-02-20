include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/aurora"
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id                     = "vpc-mock"
    database_subnets           = ["subnet-mock-1", "subnet-mock-2"]
    database_subnet_group_name = "mock-db-subnet-group"
  }
}

dependency "eks" {
  config_path = "../eks"

  mock_outputs = {
    node_security_group_id = "sg-mock"
  }
}

inputs = {
  name                 = "cloud-native-user-api-test"
  vpc_id               = dependency.vpc.outputs.vpc_id
  db_subnet_group_name = dependency.vpc.outputs.database_subnet_group_name
  eks_node_sg_id       = dependency.eks.outputs.node_security_group_id
  engine_version       = "17.4"
  master_username      = "postgres"
  database_name        = "db1"
  min_capacity         = 0.5
  max_capacity         = 1.0
}
