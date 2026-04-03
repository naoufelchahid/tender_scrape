# Kubernetes Local Cluster Design — Tender Data Pipeline

**Date**: 2026-04-01
**Status**: Approved

## Context

The tender scrape pipeline consists of 5 stages connected via AWS SQS queues and S3 storage. Stages 2–5 are long-running SQS consumer services that currently run as standalone Docker containers or ECS tasks. The goal is to unify stages 2–5 under a local Kubernetes cluster (minikube) for easier orchestration, resource management, and local development. Stage 1 (web scraper) is excluded because it requires `headless=False` Playwright and runs best on the host machine directly.

## Cluster

- **Tool**: minikube
- **Profile name** (node name): `tender-data-pipeline`
- **Start command**: `minikube start -p tender-data-pipeline --cpus=6 --memory=12288 --disk-size=20g`
- **Namespace**: `tender-pipeline`

## Workloads

| Workload | Kind | Image Source | Replicas | CPU Request | Memory Request |
|----------|------|-------------|----------|-------------|----------------|
| `ocr` | Deployment | `2_Ocr/Dockerfile` | 1 | 2000m | 8Gi |
| `classification` | Deployment | `3_Classification/Dockerfile` | 1 | 250m | 512Mi |
| `extraction` | Deployment | `4_Extraction/Dockerfile` | 1 | 500m | 1Gi |
| `ingestion` | Deployment | `5_Ingestion/Dockerfile` | 1 | 250m | 1Gi |
| `fuseki` | StatefulSet | `stain/jena-fuseki:latest` | 1 | 500m | 2.5Gi |

**Total resource budget**: ~3500m CPU / ~13Gi RAM (fits within minikube 6 CPU / 12Gi allocation with headroom for system pods).

### Fuseki

- Exposed as **two Services**:
  - `ClusterIP` (port 3030) — for in-cluster access by the ingestion pod (`JENA_ENDPOINT=http://fuseki:3030`)
  - `NodePort` (nodePort: 30030) — for external access by other machines/clusters on the LAN at `http://<host-LAN-IP>:30030`
- PersistentVolumeClaim (5Gi) mounts to `/fuseki` — survives pod restarts
- JVM args: `-Xmx2g` (matches existing docker-compose config)
- Ingestion deployment has `initContainer` that waits for Fuseki healthcheck before starting
- **Production migration path**: replace `NodePort` with a cloud `LoadBalancer` + TLS termination — no other manifest changes required

## Configuration

### ConfigMap — `pipeline-config`

Non-sensitive shared values injected as env vars into all pods:

```
AWS_REGION=eu-west-3
S3_BUCKET_NAME=my-tender-documents-bucket
MARKDOWN_PREFIX=markdown_tender/
OCR_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/034791378578/OCR_QUEUE
CLASSIFICATION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/034791378578/CLASSIFICATION_QUEUE
EXTRACTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/034791378578/EXTRACTION_QUEUE
KB_INGESTION_QUEUE_URL=https://sqs.eu-west-3.amazonaws.com/034791378578/KB_INGESTION_QUEUE_URL
JENA_ENDPOINT=http://fuseki:3030
JENA_DATASET=tenders
VECTOR_S3_BUCKET=my-tender-vectors-bucket
VECTOR_S3_PREFIX=index/tender-index/
EMBEDDING_MODEL=openai/text-embedding-3-small
```

### Secrets (never committed to git)

Three `Secret` objects created manually via `kubectl`:

| Secret Name | Keys |
|-------------|------|
| `aws-credentials` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| `api-keys` | `OPENROUTER_API_KEY` |
| `fuseki-auth` | `JENA_USERNAME`, `JENA_PASSWORD` |

A `secrets.yaml.example` (with placeholder values) is committed for reference.

## File Layout

```
k8s/
├── namespace.yaml
├── configmap.yaml
├── secrets/
│   └── secrets.yaml.example        ← committed (placeholder values only)
├── fuseki/
│   ├── pvc.yaml
│   ├── statefulset.yaml
│   ├── service-internal.yaml       ← ClusterIP for in-cluster access
│   └── service-external.yaml      ← NodePort for LAN/cross-cluster access
├── ocr/
│   └── deployment.yaml
├── classification/
│   └── deployment.yaml
├── extraction/
│   └── deployment.yaml
└── ingestion/
    └── deployment.yaml
```

## Image Build Strategy

Images are built locally and loaded directly into minikube's Docker daemon:

```bash
eval $(minikube -p tender-data-pipeline docker-env)
docker build -t tender-ocr:latest ./2_Ocr
docker build -t tender-classification:latest ./3_Classification
docker build -t tender-extraction:latest ./4_Extraction
docker build -t tender-ingestion:latest ./5_Ingestion
```

All Deployment manifests use `imagePullPolicy: Never` so minikube uses the locally built images.

## Apply Order

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
# Create secrets manually (see secrets.yaml.example)
kubectl apply -f k8s/fuseki/
kubectl apply -f k8s/ingestion/    # depends on fuseki
kubectl apply -f k8s/extraction/
kubectl apply -f k8s/classification/
kubectl apply -f k8s/ocr/
```

## Verification

```bash
# Check all pods running
kubectl get pods -n tender-pipeline

# Check Fuseki is reachable from ingestion pod
kubectl exec -n tender-pipeline deploy/ingestion -- curl http://fuseki:3030/$/ping

# Check OCR pod logs (SQS polling)
kubectl logs -n tender-pipeline deploy/ocr -f

# Run 5_Ingestion tests against live Fuseki
kubectl exec -n tender-pipeline deploy/ingestion -- pytest tests/
```

## Multi-Cluster Roadmap

This cluster is the first of three planned clusters sharing a single Fuseki instance:

| Cluster | Location | Role | Fuseki access |
|---------|----------|------|---------------|
| `tender-data-pipeline` | Local minikube | Stages 2-5 scraping pipeline | write |
| `results-processing` | Local → Cloud | Results scraping + processing | write |
| `app-backend` | Local → Cloud | API backend serving queries | read |

All future clusters connect to Fuseki via the NodePort (local) or LoadBalancer (cloud) endpoint. The `JENA_ENDPOINT` env var in their ConfigMaps will point to `http://<host-IP>:30030` locally.

## Out of Scope

- Stage 1 (`1_Update`) — runs on host machine, pushes to AWS SQS/S3 as today
- GitOps / ArgoCD — not needed for local dev
- Horizontal autoscaling — single replica per stage is sufficient locally
- TLS / authentication on Fuseki NodePort — deferred to production phase
