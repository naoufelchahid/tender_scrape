# Kubernetes Deployment Infrastructure

This directory contains the manifests required to deploy the Tender Scrape pipeline onto a Kubernetes (K8s) cluster.

## Structure

```
k8s/
├── namespace.yaml           # Pipeline namespace definition
├── configmap.yaml           # Shared environment variables
├── secrets/                 # (External) AWS and API credentials
├── fuseki/                  # Apache Jena Fuseki deployment
├── ocr/                     # Stage 2 (OCR) deployment
├── classification/          # Stage 3 (Classification) deployment
├── extraction/              # Stage 4 (Extraction) deployment
└── ingestion/               # Stage 5 (Ingestion) deployment
```

## Deployment Order

1. **Namespace & Config**:
   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/configmap.yaml
   ```
2. **Infrastructure**:
   ```bash
   kubectl apply -f k8s/fuseki/
   ```
3. **Pipeline Stages**:
   ```bash
   kubectl apply -f k8s/ocr/
   kubectl apply -f k8s/classification/
   kubectl apply -f k8s/extraction/
   kubectl apply -f k8s/ingestion/
   ```

## Key Components

- **Namespace**: All components run in the `tender-scrape` namespace for isolation.
- **ConfigMap**: Centralizes non-sensitive configuration like S3 bucket names, SQS queue URLs, and Jena endpoints.
- **Resource Limits**: Each stage has CPU and Memory limits defined to ensure cluster stability. OCR and Extraction stages are configured with higher memory limits (4GB+) due to ML model requirements.

## Monitoring

Kubernetes health checks (liveness and readiness probes) are configured for each microservice to ensure they are automatically restarted if they hang or fail.
