# Pinned so a plan is reproducible: unconstrained providers resolve to whatever
# is newest at init time, which silently changes plan output and has already
# broken this repo once (the generated helm provider block was v2 syntax and
# helm 3.x rejects it).
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
