# Cloud Native User API

A production-ready FastAPI application deployed on AWS EKS with Aurora PostgreSQL, ElastiCache Redis, and Kubernetes Gateway API for ingress.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          AWS Cloud                              │
│                                                                 │
│  ┌──────────────────────── VPC ───────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌─ Public Subnets ─────────────────────────────────────┐  │ │
│  │  │  ALB (via Gateway API + AWS LB Controller)           │  │ │
│  │  └──────────────────────┬───────────────────────────────┘  │ │
│  │                         │                                  │ │
│  │  ┌─ Private Subnets ───┬┴──────────────────────────────┐  │ │
│  │  │                     ▼                                │  │ │
│  │  │  ┌─── EKS Cluster ───────────────────────────────┐   │  │ │
│  │  │  │                                               │   │  │ │
│  │  │  │  ┌─────────────┐    ┌──────────────────────┐  │   │  │ │
│  │  │  │  │  FastAPI     │    │  Init Container      │  │   │  │ │
│  │  │  │  │  (User API)  │    │  (Schema Migration)  │  │   │  │ │
│  │  │  │  └──────┬───────┘    └──────────────────────┘  │   │  │ │
│  │  │  │         │                                      │   │  │ │
│  │  │  └─────────┼──────────────────────────────────────┘   │  │ │
│  │  └────────────┼──────────────────────────────────────────┘  │ │
│  │               │                                             │ │
│  │  ┌─ Database Subnets ───────────────────────────────────┐   │ │
│  │  │  ┌──────────────────┐    ┌────────────────────────┐  │   │ │
│  │  │  │ Aurora Serverless │    │ ElastiCache Redis      │  │   │ │
│  │  │  │ v2 (PostgreSQL)  │    │ (cache.t3.micro)       │  │   │ │
│  │  │  └──────────────────┘    └────────────────────────┘  │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
cloud-native-user-api/
├── code/
│   ├── main.py              # FastAPI application
│   ├── Dockerfile           # Container image (python:3.13-slim)
│   └── requirements.txt     # Pinned Python dependencies
├── sql/
│   └── schema.sql           # Database schema
├── terraform/
│   ├── root.hcl             # Shared Terragrunt config (S3 backend, providers)
│   ├── environments/
│   │   └── test/
│   │       ├── env.hcl      # Environment variables (region, project name)
│   │       ├── vpc/         # VPC with public/private/database subnets
│   │       ├── eks/         # EKS 1.32 cluster with managed node group
│   │       ├── aurora/      # Aurora Serverless v2 (PostgreSQL 17)
│   │       ├── elasticache/ # ElastiCache Redis 7.1
│   │       ├── ecr/         # ECR repository
│   │       └── k8s-addons/  # AWS LB Controller, Gateway API CRDs, K8s secrets
│   └── modules/
│       ├── vpc/             # terraform-aws-modules/vpc/aws ~> 6.0
│       ├── eks/             # terraform-aws-modules/eks/aws ~> 21.0
│       ├── aurora/          # terraform-aws-modules/rds-aurora/aws ~> 10.0
│       ├── elasticache/     # Native AWS resources
│       ├── ecr/             # ECR repo + lifecycle policy
│       └── k8s-addons/      # IRSA, Helm releases, K8s secrets
├── helm/
│   └── fastapi-app/         # Helm chart with Gateway API
├── notebooks/
│   └── api-test.ipynb       # API integration tests
├── docker-compose.yml       # Local development stack
└── README.md
```

## Prerequisites

- Docker & Docker Compose
- Terraform >= 1.14
- Terragrunt >= 0.99
- AWS CLI v2 (configured with credentials)
- kubectl
- Helm 3
- Python 3.12+ (for notebook)

## Local Development

```bash
# Start the full stack (API + PostgreSQL + Redis)
docker compose up --build

# Test endpoints
curl http://localhost:8000/           # {"company":"Acme Corp","status":"running"}
curl http://localhost:8000/healthz    # {"status":"ok"}
curl http://localhost:8000/readyz     # {"status":"ready"}
curl http://localhost:8000/docs       # Swagger UI

# Create a user
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com"}'

# Get users
curl http://localhost:8000/users      # List all
curl http://localhost:8000/users/1    # By ID

# Stop
docker compose down -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Root — returns company name and status |
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe (pings DB + Redis) |
| GET | `/docs` | Swagger UI |
| POST | `/users` | Create a user (invalidates list cache) |
| GET | `/users` | List all users (cached 60s in Redis) |
| GET | `/users/{id}` | Get user by ID (cached 60s in Redis) |

## Infrastructure Deployment

### 1. Deploy infrastructure with Terragrunt

```bash
cd terraform/environments/test

# Deploy in dependency order (VPC → EKS → Aurora → ElastiCache → ECR → k8s-addons)
terragrunt run-all apply

# Or deploy individually
cd vpc && terragrunt apply
cd ../eks && terragrunt apply
cd ../aurora && terragrunt apply
cd ../elasticache && terragrunt apply
cd ../ecr && terragrunt apply
cd ../k8s-addons && terragrunt apply
```

### 2. Configure kubectl

```bash
aws eks update-kubeconfig --name cloud-native-user-api-test --region us-east-1
```

### 3. Build and push container image

```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t cloud-native-user-api ./code
docker tag cloud-native-user-api:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/cloud-native-user-api-test:latest
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/cloud-native-user-api-test:latest
```

### 4. Deploy with Helm

```bash
helm install user-api helm/fastapi-app/ \
  --set image.repository=<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/cloud-native-user-api-test \
  --set image.tag=latest \
  --set companyName="Acme Corp"
```

### 5. Access the API

```bash
# Wait for ALB to provision
kubectl get gateway user-api-fastapi-app -o jsonpath='{.status.addresses[0].value}'

# Test
curl http://<ALB_DNS>/
curl http://<ALB_DNS>/docs
curl http://<ALB_DNS>/users
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Ingress | Kubernetes Gateway API | Modern replacement for Ingress, native ALB integration via AWS LB Controller |
| Database | Aurora Serverless v2 | Auto-scaling, pay-per-use (0.5–1.0 ACU), managed passwords via Secrets Manager |
| Caching | ElastiCache Redis | Sub-millisecond latency, TTL-based cache with invalidation on writes |
| IaC | Terraform + Terragrunt | Modular infrastructure, DRY configuration, S3 remote state |
| NAT Gateway | Single | Cost optimization (~$32/month saved vs multi-AZ NAT) |
| Schema migration | Init container | Runs `schema.sql` before app starts, no extra tooling needed |

## Teardown

```bash
# Remove Helm release
helm uninstall user-api

# Destroy infrastructure (reverse dependency order)
cd terraform/environments/test
terragrunt run-all destroy
```

## Estimated Cost

~$6.40/day ($0.27/hr) for the test environment:
- EKS control plane: $0.10/hr
- t3.small node: $0.021/hr
- Aurora Serverless v2 (0.5 ACU): $0.06/hr
- ElastiCache cache.t3.micro: $0.017/hr
- NAT Gateway: $0.045/hr + data
- ALB: $0.023/hr
