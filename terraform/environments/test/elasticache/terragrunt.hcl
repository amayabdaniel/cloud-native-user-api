include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/elasticache"
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id           = "vpc-mock"
    database_subnets = ["subnet-mock-1", "subnet-mock-2"]
  }
}

dependency "eks" {
  config_path = "../eks"

  mock_outputs = {
    node_security_group_id = "sg-mock"
  }
}

inputs = {
  name           = "cloud-native-user-api-test"
  vpc_id         = dependency.vpc.outputs.vpc_id
  subnet_ids     = dependency.vpc.outputs.database_subnets
  eks_node_sg_id = dependency.eks.outputs.node_security_group_id
  engine_version = "7.1"
  node_type      = "cache.t3.micro"
}
