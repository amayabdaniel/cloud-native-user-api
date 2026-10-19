# Pinned so a plan is reproducible. The helm constraint is load-bearing: helm 2.x
# took a nested `kubernetes { }` block while 3.x takes a `kubernetes = { }`
# attribute, so an unpinned provider decides whether the generated provider
# config in k8s-provider.tf parses at all.
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
    }
  }
}
