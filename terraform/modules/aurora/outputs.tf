output "cluster_endpoint" {
  value = module.aurora.cluster_endpoint
}

output "cluster_reader_endpoint" {
  value = module.aurora.cluster_reader_endpoint
}

output "cluster_port" {
  value = module.aurora.cluster_port
}

output "cluster_database_name" {
  value = module.aurora.cluster_database_name
}

output "cluster_master_username" {
  value = module.aurora.cluster_master_username
}

output "cluster_master_user_secret" {
  value = module.aurora.cluster_master_user_secret
}
