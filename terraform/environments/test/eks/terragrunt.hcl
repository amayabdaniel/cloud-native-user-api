include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/eks"
}

dependency "vpc" {
  config_path = "../vpc"

  mock_outputs = {
    vpc_id          = "vpc-mock"
    private_subnets = ["subnet-mock-1", "subnet-mock-2"]
  }
}

inputs = {
  cluster_name       = "cloud-native-user-api-test"
  cluster_version    = "1.32"
  vpc_id             = dependency.vpc.outputs.vpc_id
  private_subnet_ids = dependency.vpc.outputs.private_subnets
  node_instance_type = "t3.small"
  node_desired_size  = 1
  node_min_size      = 1
  node_max_size      = 2
}
