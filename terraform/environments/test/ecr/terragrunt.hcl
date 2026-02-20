include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/ecr"
}

inputs = {
  name = "cloud-native-user-api"
}
