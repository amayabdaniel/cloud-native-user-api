output "lb_controller_role_arn" {
  value = aws_iam_role.lb_controller.arn
}

output "secret_name" {
  value = kubernetes_secret_v1.app_credentials.metadata[0].name
}
