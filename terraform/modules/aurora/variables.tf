variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "db_subnet_group_name" {
  type = string
}

variable "eks_node_sg_id" {
  type = string
}

variable "engine_version" {
  type    = string
  default = "17.4"
}

variable "master_username" {
  type    = string
  default = "postgres"
}

variable "database_name" {
  type    = string
  default = "db1"
}

variable "min_capacity" {
  type    = number
  default = 0.5
}

variable "max_capacity" {
  type    = number
  default = 1.0
}

variable "tags" {
  type    = map(string)
  default = {}
}
