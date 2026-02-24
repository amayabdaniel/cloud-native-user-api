# Cloud Native AI Q&A Service

A production-ready AI question-answering service deployed on AWS EKS. The service accepts user questions via a REST API and returns AI-generated responses using SmolLM2-135M-Instruct served through vLLM. Built with FastAPI, Kubernetes Gateway API, Aurora PostgreSQL, and ElastiCache Redis.

## Architecture

### Network Topology

The VPC uses a three-tier subnet architecture across two Availability Zones (us-east-1a, us-east-1b):

- **Public subnets** host the Application Load Balancer provisioned by the AWS Gateway API controller. Subnets are tagged with `kubernetes.io/role/elb = 1` for automatic ALB discovery.
- **Private subnets** run the EKS managed node group. Pods access the internet through a single NAT Gateway (cost-optimized for non-production). Subnets are tagged with `kubernetes.io/role/internal-elb = 1`.
- **Database subnets** isolate Aurora PostgreSQL and ElastiCache Redis with no direct internet access. Traffic is restricted to EKS node security groups only.

External traffic enters via the ALB in public subnets, which routes to FastAPI pods in private subnets through the Kubernetes Gateway API HTTPRoute. The FastAPI pods communicate with vLLM pods via Kubernetes ClusterIP Services (internal networking), and with Aurora/ElastiCache through security-group-controlled access to the database subnets.

### Security & IAM

**IAM Roles:**

| Role | Purpose | Trust Policy |
|------|---------|-------------|
| EKS Cluster Role | Managed by `terraform-aws-modules/eks`, allows EKS to manage AWS resources | AWS EKS service |
| EKS Node Group Role | EC2 instances in the managed node group, includes ECR pull, SSM, CNI policies | EC2 service |
| AWS LB Controller (IRSA) | Allows the in-cluster LB controller to create/manage ALBs | OIDC federation scoped to `kube-system:aws-load-balancer-controller` |

**Security Groups:**

| Security Group | Ingress Rule | Source |
|---------------|-------------|--------|
| EKS Cluster SG | API server access | Managed by EKS module |
| EKS Node SG | Node-to-node, control plane communication | Managed by EKS module |
| Aurora SG | TCP 5432 | EKS Node Security Group |
| ElastiCache SG | TCP 6379 | EKS Node Security Group |

**Secrets Management:**
- Aurora master credentials are auto-managed via AWS Secrets Manager (`manage_master_user_password = true`)
- Credentials are injected into the Kubernetes `app-credentials` Secret by the `k8s-addons` Terraform module
- Application pods consume credentials via `envFrom: secretRef`

## Project Structure

```
cloud-native-user-api/
├── code/
│   ├── main.py              # FastAPI application (Q&A + user management)
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
│   │       ├── eks/         # EKS 1.35 cluster with managed node group
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
│   ├── fastapi-app/         # Helm chart — API with Gateway API ingress
│   └── vllm/                # Helm chart — vLLM inference server (SmolLM2-135M-Instruct)
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
# Start the core stack (API + PostgreSQL + Redis)
docker compose up --build

# Start with vLLM for local LLM testing (requires significant CPU/RAM or GPU)
docker compose --profile llm up --build

# Test endpoints
curl http://localhost:8000/           # {"company":"My Company","status":"running"}
curl http://localhost:8000/healthz    # {"status":"ok"}
curl http://localhost:8000/readyz     # {"status":"ready"}
curl http://localhost:8000/docs       # Swagger UI

# Ask a question (requires vLLM running)
curl -X POST http://localhost:8000/question \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Kubernetes?"}'

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
| POST | `/question` | Accept a question, return AI-generated answer from vLLM |
| GET | `/` | Root — returns company name and status |
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe (pings DB + Redis) |
| GET | `/docs` | Swagger UI |
| POST | `/users` | Create a user (invalidates list cache) |
| GET | `/users` | List all users (cached 60s in Redis) |
| GET | `/users/{id}` | Get user by ID (cached 60s in Redis) |

### POST /question

**Request:**
```json
{
  "question": "What is Kubernetes?"
}
```

**Response:**
```json
{
  "question": "What is Kubernetes?",
  "answer": "Kubernetes is an open-source container orchestration platform...",
  "model": "HuggingFaceTB/SmolLM2-135M-Instruct"
}
```

The FastAPI service forwards the question to the vLLM pod via its Kubernetes ClusterIP Service (`http://vllm:8000/v1/chat/completions`), using the OpenAI-compatible API that vLLM exposes.

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

### 4. Deploy vLLM (SmolLM2-135M-Instruct)

```bash
helm install vllm helm/vllm/ \
  --set fullnameOverride=vllm
```

Wait for the model to download and load:

```bash
kubectl rollout status deployment/vllm --timeout=600s
```

### 5. Deploy FastAPI application

```bash
helm install user-api helm/fastapi-app/ \
  --set image.repository=<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/cloud-native-user-api-test \
  --set image.tag=latest \
  --set vllm.url=http://vllm:8000
```

### 6. Access the API

```bash
# Wait for ALB to provision
kubectl get gateway user-api-fastapi-app -o jsonpath='{.status.addresses[0].value}'

# Test
curl http://<ALB_DNS>/
curl http://<ALB_DNS>/docs
curl -X POST http://<ALB_DNS>/question \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Kubernetes?"}'
```

## Scaling Strategies for LLM Workloads on EKS

### Horizontal Pod Autoscaling (HPA)

Both the FastAPI and vLLM deployments include HPA configurations:

```yaml
# vLLM HPA (helm/vllm/values.yaml)
hpa:
  enabled: true
  minReplicas: 1
  maxReplicas: 4
  targetCPUUtilizationPercentage: 70
```

For production LLM workloads, consider custom metrics beyond CPU utilization:

- **Request queue depth** — scale when pending inference requests exceed a threshold, using KEDA or Prometheus adapter to expose vLLM's `/metrics` endpoint (`vllm:num_requests_waiting`)
- **GPU utilization** — use DCGM exporter with `DCGM_FI_DEV_GPU_UTIL` as a custom HPA metric
- **Time-to-first-token (TTFT)** — scale proactively when latency degrades, using vLLM's built-in Prometheus metrics

### Cluster Autoscaler / Karpenter

The EKS managed node group defines `min_size=1` and `max_size=2` for the test environment. For production:

- **Karpenter** (recommended) provisions right-sized nodes on demand, with NodePool CRDs that specify instance families, GPU types, and capacity constraints:
  ```yaml
  apiVersion: karpenter.sh/v1
  kind: NodePool
  spec:
    template:
      spec:
        requirements:
          - key: node.kubernetes.io/instance-type
            operator: In
            values: ["g5.xlarge", "g5.2xlarge"]
          - key: karpenter.sh/capacity-type
            operator: In
            values: ["on-demand", "spot"]
        nodeClassRef:
          name: default
    limits:
      cpu: "100"
      nvidia.com/gpu: "8"
  ```
- **Cluster Autoscaler** — alternative for simpler setups, adjusts node group size based on pending pod scheduling. Configure `--scale-down-delay-after-add=10m` to avoid premature scale-down during model loading.

### GPU Node Groups

For production vLLM deployment, add a dedicated GPU node group in Terraform:

```hcl
# In terraform/modules/eks/main.tf — add to eks_managed_node_groups:
gpu = {
  ami_type       = "AL2023_x86_64_GPU"
  instance_types = ["g5.xlarge"]   # 1x NVIDIA A10G, 24GB VRAM
  min_size       = 0
  max_size       = 4
  desired_size   = 1

  labels = {
    "workload-type" = "gpu-inference"
  }

  taints = [{
    key    = "nvidia.com/gpu"
    value  = "true"
    effect = "NO_SCHEDULE"
  }]
}
```

The vLLM Helm chart supports GPU scheduling via `nodeSelector` and `tolerations` in values.yaml. When GPU nodes are provisioned, enable them:

```yaml
# helm/vllm/values.yaml — production GPU config
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  workload-type: gpu-inference
tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
```

### vLLM-Specific Optimizations

vLLM includes several built-in features that maximize inference throughput:

- **Continuous batching** — dynamically batches incoming requests rather than waiting for a fixed batch to fill, reducing latency under variable load
- **PagedAttention** — manages KV-cache memory in fixed-size pages (like OS virtual memory), eliminating memory fragmentation and enabling higher concurrency. SmolLM2-135M with `max-model-len=2048` requires ~0.5GB KV-cache per concurrent request
- **Tensor parallelism** — for larger models, splits model layers across multiple GPUs with `--tensor-parallel-size N`. Not needed for SmolLM2-135M but critical for 7B+ models
- **Speculative decoding** — uses a smaller draft model to propose tokens, verified in parallel by the main model. Can improve throughput 2-3x for latency-sensitive workloads
- **Prefix caching** — caches computed KV-cache for common prompt prefixes, reducing redundant computation for repeated system prompts

### Memory Management

LLM inference is memory-bound. Key considerations:

- **Model weights** — SmolLM2-135M in fp16 requires ~270MB GPU/system memory. Larger models scale linearly (7B ≈ 14GB, 70B ≈ 140GB)
- **KV-cache** — grows with `batch_size × sequence_length × num_layers × head_dim`. vLLM's PagedAttention manages this automatically, but set `--gpu-memory-utilization 0.9` to reserve 10% for overhead
- **Resource limits** — always set Kubernetes memory limits to prevent OOM kills from affecting other pods. For GPU workloads, `nvidia.com/gpu` limits ensure exclusive GPU access
- **Swap space** — vLLM supports CPU offloading of KV-cache when GPU memory is exhausted (`--swap-space`), trading latency for higher concurrency

### Production Recommendations

| Concern | Recommendation |
|---------|---------------|
| Availability | Run 2+ vLLM replicas with pod anti-affinity across AZs |
| Cost | Use Spot instances for GPU nodes (60-70% savings) with Karpenter consolidation |
| Model updates | Use rolling deployments with `maxSurge=1, maxUnavailable=0` to avoid downtime during model upgrades |
| Monitoring | Deploy Prometheus + Grafana; scrape vLLM `/metrics` for request latency, queue depth, GPU utilization |
| Rate limiting | Implement API-level rate limiting in FastAPI or at the ALB/Gateway level to protect vLLM from traffic spikes |
| Cold start | Pre-pull vLLM images and cache model weights on persistent volumes (EBS) to reduce startup time from minutes to seconds |
| Multi-model | Deploy separate vLLM instances per model with dedicated Helm releases and resource quotas |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Serving | vLLM | OpenAI-compatible API, continuous batching, PagedAttention for efficient memory |
| Model | SmolLM2-135M-Instruct | Lightweight instruct model, suitable for Q&A, fast inference |
| Ingress | Kubernetes Gateway API | Modern replacement for Ingress, native ALB integration via AWS LB Controller |
| Database | Aurora Serverless v2 | Auto-scaling, pay-per-use (0.5–1.0 ACU), managed passwords via Secrets Manager |
| Caching | ElastiCache Redis | Sub-millisecond latency, TTL-based cache with invalidation on writes |
| IaC | Terraform + Terragrunt | Modular infrastructure, DRY configuration, S3 remote state |
| Internal Comms | Kubernetes Services | vLLM and FastAPI communicate via ClusterIP Services (zero-trust network) |
| NAT Gateway | Single | Cost optimization (~$32/month saved vs multi-AZ NAT) |
| Schema migration | Init container | Runs `schema.sql` before app starts, no extra tooling needed |

## Teardown

```bash
# Remove Helm releases
helm uninstall user-api
helm uninstall vllm

# Destroy infrastructure (reverse dependency order)
cd terraform/environments/test
terragrunt run-all destroy
```

## Estimated Cost

~$6.40/day ($0.27/hr) for the test environment (CPU-only):
- EKS control plane: $0.10/hr
- t3.small node: $0.021/hr
- Aurora Serverless v2 (0.5 ACU): $0.06/hr
- ElastiCache cache.t3.micro: $0.017/hr
- NAT Gateway: $0.045/hr + data
- ALB: $0.023/hr

For production with GPU (g5.xlarge):
- Add ~$1.006/hr per GPU node ($24.14/day)
- Consider Spot instances for 60-70% savings
