variable "cluster_name" {
  type = string
}

variable "cluster_endpoint" {
  type = string
}

variable "cluster_ca_data" {
  type = string
}

variable "oidc_provider_arn" {
  type = string
}

variable "oidc_provider" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "aurora_endpoint" {
  type = string
}

variable "aurora_database_name" {
  type = string
}

variable "aurora_master_secret_arn" {
  type = string
}

variable "redis_endpoint" {
  type = string
}

variable "redis_port" {
  type    = number
  default = 6379
}

variable "app_namespace" {
  type    = string
  default = "default"
}

variable "tags" {
  type    = map(string)
  default = {}
}
