data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_secretsmanager_secret_version" "aurora" {
  secret_id = var.aurora_master_secret_arn
}

locals {
  aurora_creds = jsondecode(data.aws_secretsmanager_secret_version.aurora.secret_string)
}

# --- IRSA for AWS Load Balancer Controller ---

data "aws_iam_policy_document" "lb_controller_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "lb_controller" {
  name               = "${var.cluster_name}-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.lb_controller_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "lb_controller" {
  role       = aws_iam_role.lb_controller.name
  policy_arn = aws_iam_policy.lb_controller.arn
}

resource "aws_iam_policy" "lb_controller" {
  name   = "${var.cluster_name}-lb-controller"
  policy = file("${path.module}/lb-controller-policy.json")
  tags   = var.tags
}

# --- Helm: AWS Load Balancer Controller ---

resource "helm_release" "lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "3.0.0"

  values = [yamlencode({
    clusterName = var.cluster_name
    region      = data.aws_region.current.id
    vpcId       = var.vpc_id
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller"
      annotations = {
        "eks.amazonaws.com/role-arn" = aws_iam_role.lb_controller.arn
      }
    }
    enableServiceMutatorWebhook = false
    featureGates = {
      ALBGatewayAPI = true
    }
  })]

  depends_on = [aws_iam_role_policy_attachment.lb_controller]
}

# --- Helm: Gateway API CRDs ---

resource "helm_release" "gateway_api_crds" {
  name       = "gateway-api-crds"
  repository = "https://kubernetes-sigs.github.io/gateway-api"
  chart      = "gateway-api"
  namespace  = "kube-system"
  version    = "1.4.1"

  values = [yamlencode({
    installCRDs = true
  })]
}

# --- Kubernetes Secret for app credentials ---

resource "kubernetes_secret_v1" "app_credentials" {
  metadata {
    name      = "app-credentials"
    namespace = var.app_namespace
  }

  data = {
    POSTGRES_HOST     = var.aurora_endpoint
    POSTGRES_DB       = var.aurora_database_name
    POSTGRES_USER     = local.aurora_creds["username"]
    POSTGRES_PASSWORD = local.aurora_creds["password"]
    REDIS_HOST        = var.redis_endpoint
    REDIS_PORT        = tostring(var.redis_port)
  }
}
