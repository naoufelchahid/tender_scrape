# Kubernetes Local Cluster — Tender Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy stages 2–5 of the tender scrape pipeline into a local minikube cluster named `tender-data-pipeline`, with Fuseki exposed on NodePort 30030 for cross-cluster/LAN access.

**Architecture:** A single minikube profile hosts one Kubernetes namespace (`tender-pipeline`) containing four SQS-consumer Deployments (ocr, classification, extraction, ingestion) and one Fuseki StatefulSet backed by a PersistentVolumeClaim. Fuseki is accessible in-cluster via ClusterIP (`fuseki:3030`) and externally via NodePort 30030. All pods pull AWS credentials and API keys from Kubernetes Secrets; non-sensitive config comes from a shared ConfigMap. Stage 1 (scraper) continues running on the host machine unchanged.

**Tech Stack:** minikube, kubectl, Docker (minikube daemon), Kubernetes 1.29+, Apache Jena Fuseki (`stain/jena-fuseki:latest`), Python 3.11 slim images.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `k8s/namespace.yaml` | Create | `tender-pipeline` namespace |
| `k8s/configmap.yaml` | Create | Non-sensitive env vars shared by all pods |
| `k8s/secrets/secrets.yaml.example` | Create | Placeholder Secret manifests (committed) |
| `k8s/fuseki/pvc.yaml` | Create | 5Gi PersistentVolumeClaim for Fuseki data |
| `k8s/fuseki/statefulset.yaml` | Create | Fuseki pod with JVM config and health probes |
| `k8s/fuseki/service-internal.yaml` | Create | ClusterIP Service for in-cluster access |
| `k8s/fuseki/service-external.yaml` | Create | NodePort 30030 for LAN/cross-cluster access |
| `k8s/ingestion/deployment.yaml` | Create | Stage 5 — KBIngestor SQS consumer |
| `k8s/extraction/deployment.yaml` | Create | Stage 4 — DocumentChunker SQS consumer |
| `k8s/classification/deployment.yaml` | Create | Stage 3 — Classifier SQS consumer |
| `k8s/ocr/deployment.yaml` | Create | Stage 2 — Docling OCR SQS consumer |

---

## Task 1: Start minikube cluster

**Files:** none (host setup)

- [ ] **Step 1: Start the cluster**

```bash
minikube start -p tender-data-pipeline \
  --cpus=6 \
  --memory=12288 \
  --disk-size=20g \
  --driver=docker
```

Expected output: `Done! kubectl is now configured to use "tender-data-pipeline" profile`

- [ ] **Step 2: Verify node is ready**

```bash
kubectl get nodes --context=tender-data-pipeline
```

Expected output:
```
NAME                    STATUS   ROLES           AGE   VERSION
tender-data-pipeline    Ready    control-plane   Xm    v1.29.x
```

- [ ] **Step 3: Point Docker CLI to minikube's daemon**

```bash
eval $(minikube -p tender-data-pipeline docker-env)
```

Run this in every terminal session before building images. Verify with:
```bash
docker info | grep "Name"
# Expected: Name: tender-data-pipeline
```

---

## Task 2: Create namespace

**Files:**
- Create: `k8s/namespace.yaml`

- [ ] **Step 1: Write manifest**

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tender-pipeline
  labels:
    app.kubernetes.io/part-of: tender-scrape
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/namespace.yaml
```

Expected: `namespace/tender-pipeline configured (dry run)`

- [ ] **Step 3: Apply**

```bash
kubectl apply -f k8s/namespace.yaml
```

- [ ] **Step 4: Verify**

```bash
kubectl get namespace tender-pipeline
```

Expected: `tender-pipeline   Active   Xs`

- [ ] **Step 5: Commit**

```bash
git add k8s/namespace.yaml
git commit -m "feat(k8s): add tender-pipeline namespace"
```

---

## Task 3: Create ConfigMap

**Files:**
- Create: `k8s/configmap.yaml`

- [ ] **Step 1: Write manifest**

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: pipeline-config
  namespace: tender-pipeline
data:
  AWS_REGION: "eu-west-3"
  S3_BUCKET_NAME: "my-tender-documents-bucket"
  MARKDOWN_PREFIX: "markdown_tender/"
  OCR_QUEUE_URL: "https://sqs.eu-west-3.amazonaws.com/034791378578/OCR_QUEUE"
  CLASSIFICATION_QUEUE_URL: "https://sqs.eu-west-3.amazonaws.com/034791378578/CLASSIFICATION_QUEUE"
  EXTRACTION_QUEUE_URL: "https://sqs.eu-west-3.amazonaws.com/034791378578/EXTRACTION_QUEUE"
  KB_INGESTION_QUEUE_URL: "https://sqs.eu-west-3.amazonaws.com/034791378578/KB_INGESTION_QUEUE_URL"
  JENA_ENDPOINT: "http://fuseki:3030"
  JENA_DATASET: "tenders"
  VECTOR_S3_BUCKET: "my-tender-vectors-bucket"
  VECTOR_S3_PREFIX: "index/tender-index/"
  EMBEDDING_MODEL: "openai/text-embedding-3-small"
  PYTHONUNBUFFERED: "1"
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/configmap.yaml
```

Expected: `configmap/pipeline-config configured (dry run)`

- [ ] **Step 3: Apply**

```bash
kubectl apply -f k8s/configmap.yaml
```

- [ ] **Step 4: Verify values are present**

```bash
kubectl get configmap pipeline-config -n tender-pipeline -o yaml | grep JENA_ENDPOINT
```

Expected: `  JENA_ENDPOINT: http://fuseki:3030`

- [ ] **Step 5: Commit**

```bash
git add k8s/configmap.yaml
git commit -m "feat(k8s): add pipeline-config ConfigMap"
```

---

## Task 4: Create Secrets example and apply real secrets

**Files:**
- Create: `k8s/secrets/secrets.yaml.example`

- [ ] **Step 1: Write example file (committed — placeholder values)**

```yaml
# k8s/secrets/secrets.yaml.example
# Copy this file to secrets.yaml, fill in real values, then apply.
# NEVER commit secrets.yaml to git.
---
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials
  namespace: tender-pipeline
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "AKIAIOSFODNN7EXAMPLE"
  AWS_SECRET_ACCESS_KEY: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
---
apiVersion: v1
kind: Secret
metadata:
  name: api-keys
  namespace: tender-pipeline
type: Opaque
stringData:
  OPENROUTER_API_KEY: "sk-or-v1-your-key-here"
---
apiVersion: v1
kind: Secret
metadata:
  name: fuseki-auth
  namespace: tender-pipeline
type: Opaque
stringData:
  JENA_USERNAME: "admin"
  JENA_PASSWORD: "change-me"
```

- [ ] **Step 2: Add secrets.yaml to .gitignore**

```bash
echo "k8s/secrets/secrets.yaml" >> .gitignore
```

- [ ] **Step 3: Create real secrets.yaml from the example**

```bash
cp k8s/secrets/secrets.yaml.example k8s/secrets/secrets.yaml
```

Edit `k8s/secrets/secrets.yaml` with your actual values:
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` — from your AWS IAM user
- `OPENROUTER_API_KEY` — from openrouter.ai
- `JENA_PASSWORD` — any password you choose for Fuseki admin

- [ ] **Step 4: Apply real secrets**

```bash
kubectl apply -f k8s/secrets/secrets.yaml
```

- [ ] **Step 5: Verify secrets exist (without showing values)**

```bash
kubectl get secrets -n tender-pipeline
```

Expected:
```
NAME               TYPE     DATA   AGE
aws-credentials    Opaque   2      Xs
api-keys           Opaque   1      Xs
fuseki-auth        Opaque   2      Xs
```

- [ ] **Step 6: Commit example file and .gitignore update**

```bash
git add k8s/secrets/secrets.yaml.example .gitignore
git commit -m "feat(k8s): add secrets example and gitignore for real secrets"
```

---

## Task 5: Deploy Fuseki StatefulSet

**Files:**
- Create: `k8s/fuseki/pvc.yaml`
- Create: `k8s/fuseki/statefulset.yaml`
- Create: `k8s/fuseki/service-internal.yaml`
- Create: `k8s/fuseki/service-external.yaml`

- [ ] **Step 1: Write PVC**

```yaml
# k8s/fuseki/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fuseki-data
  namespace: tender-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

- [ ] **Step 2: Write StatefulSet**

```yaml
# k8s/fuseki/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: fuseki
  namespace: tender-pipeline
spec:
  serviceName: fuseki
  replicas: 1
  selector:
    matchLabels:
      app: fuseki
  template:
    metadata:
      labels:
        app: fuseki
    spec:
      containers:
        - name: fuseki
          image: stain/jena-fuseki:latest
          imagePullPolicy: Always
          env:
            - name: JVM_ARGS
              value: "-Xmx2g"
            - name: ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: fuseki-auth
                  key: JENA_PASSWORD
          ports:
            - containerPort: 3030
              name: sparql
          resources:
            requests:
              cpu: "500m"
              memory: "2.5Gi"
            limits:
              cpu: "1000m"
              memory: "3Gi"
          volumeMounts:
            - name: fuseki-storage
              mountPath: /fuseki
          livenessProbe:
            httpGet:
              path: /$/ping
              port: 3030
            initialDelaySeconds: 40
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /$/ping
              port: 3030
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
      volumes:
        - name: fuseki-storage
          persistentVolumeClaim:
            claimName: fuseki-data
```

- [ ] **Step 3: Write internal ClusterIP Service**

```yaml
# k8s/fuseki/service-internal.yaml
apiVersion: v1
kind: Service
metadata:
  name: fuseki
  namespace: tender-pipeline
  labels:
    app: fuseki
spec:
  selector:
    app: fuseki
  ports:
    - name: sparql
      port: 3030
      targetPort: 3030
  type: ClusterIP
```

- [ ] **Step 4: Write external NodePort Service**

```yaml
# k8s/fuseki/service-external.yaml
apiVersion: v1
kind: Service
metadata:
  name: fuseki-external
  namespace: tender-pipeline
  labels:
    app: fuseki
spec:
  selector:
    app: fuseki
  ports:
    - name: sparql
      port: 3030
      targetPort: 3030
      nodePort: 30030
  type: NodePort
```

- [ ] **Step 5: Dry-run all Fuseki manifests**

```bash
kubectl apply --dry-run=client -f k8s/fuseki/
```

Expected: 4 lines each ending `(dry run)`

- [ ] **Step 6: Apply**

```bash
kubectl apply -f k8s/fuseki/
```

- [ ] **Step 7: Wait for Fuseki to become ready**

```bash
kubectl rollout status statefulset/fuseki -n tender-pipeline --timeout=120s
```

Expected: `statefulset rolling update complete 1 pods at revision fuseki-xxx`

- [ ] **Step 8: Verify Fuseki responds**

```bash
kubectl exec -n tender-pipeline statefulset/fuseki -- \
  wget -qO- http://localhost:3030/$/ping
```

Expected: `{"uptime": ..., "server": "Fuseki"...}` or just `200 OK`

- [ ] **Step 9: Get the NodePort external URL**

```bash
minikube -p tender-data-pipeline service fuseki-external -n tender-pipeline --url
```

Note the URL (e.g., `http://192.168.49.2:30030`). This is what other clusters will use as `JENA_ENDPOINT`.

- [ ] **Step 10: Commit**

```bash
git add k8s/fuseki/
git commit -m "feat(k8s): add Fuseki StatefulSet, PVC, and Services (ClusterIP + NodePort 30030)"
```

---

## Task 6: Build pipeline images into minikube

**Files:** none (Docker build steps)

- [ ] **Step 1: Ensure Docker CLI points to minikube daemon**

```bash
eval $(minikube -p tender-data-pipeline docker-env)
docker info | grep "Name"
# Must show: Name: tender-data-pipeline
```

- [ ] **Step 2: Build OCR image**

```bash
docker build -t tender-ocr:latest ./2_Ocr
```

Expected: `Successfully tagged tender-ocr:latest`

- [ ] **Step 3: Build Classification image**

```bash
docker build -t tender-classification:latest ./3_Classification
```

Expected: `Successfully tagged tender-classification:latest`

- [ ] **Step 4: Build Extraction image**

```bash
docker build -t tender-extraction:latest ./4_Extraction
```

Expected: `Successfully tagged tender-extraction:latest`

- [ ] **Step 5: Build Ingestion image**

```bash
docker build -t tender-ingestion:latest ./5_Ingestion
```

Expected: `Successfully tagged tender-ingestion:latest`

- [ ] **Step 6: Verify images are present in minikube**

```bash
docker images | grep tender-
```

Expected: 4 rows with `tender-ocr`, `tender-classification`, `tender-extraction`, `tender-ingestion`.

---

## Task 7: Deploy Ingestion (stage 5)

**Files:**
- Create: `k8s/ingestion/deployment.yaml`

- [ ] **Step 1: Write Deployment**

```yaml
# k8s/ingestion/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingestion
  namespace: tender-pipeline
  labels:
    app: ingestion
    stage: "5"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ingestion
  template:
    metadata:
      labels:
        app: ingestion
        stage: "5"
    spec:
      initContainers:
        - name: wait-for-fuseki
          image: busybox:1.36
          command:
            - sh
            - -c
            - |
              until wget -qO- http://fuseki:3030/$/ping > /dev/null 2>&1; do
                echo "Waiting for Fuseki..."; sleep 5;
              done
              echo "Fuseki is ready."
      containers:
        - name: ingestion
          image: tender-ingestion:latest
          imagePullPolicy: Never
          resources:
            requests:
              cpu: "250m"
              memory: "1Gi"
            limits:
              cpu: "500m"
              memory: "1.5Gi"
          envFrom:
            - configMapRef:
                name: pipeline-config
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_SECRET_ACCESS_KEY
            - name: OPENROUTER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: api-keys
                  key: OPENROUTER_API_KEY
            - name: JENA_USERNAME
              valueFrom:
                secretKeyRef:
                  name: fuseki-auth
                  key: JENA_USERNAME
            - name: JENA_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: fuseki-auth
                  key: JENA_PASSWORD
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/ingestion/deployment.yaml
```

Expected: `deployment.apps/ingestion configured (dry run)`

- [ ] **Step 3: Apply**

```bash
kubectl apply -f k8s/ingestion/deployment.yaml
```

- [ ] **Step 4: Wait for rollout**

```bash
kubectl rollout status deployment/ingestion -n tender-pipeline --timeout=120s
```

- [ ] **Step 5: Verify pod is running and Fuseki init passed**

```bash
kubectl logs -n tender-pipeline deployment/ingestion -c wait-for-fuseki
# Expected: "Fuseki is ready."

kubectl logs -n tender-pipeline deployment/ingestion
# Expected: SQS polling log lines
```

- [ ] **Step 6: Commit**

```bash
git add k8s/ingestion/deployment.yaml
git commit -m "feat(k8s): add ingestion Deployment with Fuseki initContainer"
```

---

## Task 8: Deploy Extraction (stage 4)

**Files:**
- Create: `k8s/extraction/deployment.yaml`

- [ ] **Step 1: Write Deployment**

```yaml
# k8s/extraction/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: extraction
  namespace: tender-pipeline
  labels:
    app: extraction
    stage: "4"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: extraction
  template:
    metadata:
      labels:
        app: extraction
        stage: "4"
    spec:
      containers:
        - name: extraction
          image: tender-extraction:latest
          imagePullPolicy: Never
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "1000m"
              memory: "2Gi"
          envFrom:
            - configMapRef:
                name: pipeline-config
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_SECRET_ACCESS_KEY
            - name: OPENROUTER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: api-keys
                  key: OPENROUTER_API_KEY
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/extraction/deployment.yaml
```

- [ ] **Step 3: Apply and verify**

```bash
kubectl apply -f k8s/extraction/deployment.yaml
kubectl rollout status deployment/extraction -n tender-pipeline --timeout=60s
kubectl logs -n tender-pipeline deployment/extraction --tail=20
# Expected: SQS polling log lines for EXTRACTION_QUEUE
```

- [ ] **Step 4: Commit**

```bash
git add k8s/extraction/deployment.yaml
git commit -m "feat(k8s): add extraction Deployment"
```

---

## Task 9: Deploy Classification (stage 3)

**Files:**
- Create: `k8s/classification/deployment.yaml`

- [ ] **Step 1: Write Deployment**

```yaml
# k8s/classification/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: classification
  namespace: tender-pipeline
  labels:
    app: classification
    stage: "3"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: classification
  template:
    metadata:
      labels:
        app: classification
        stage: "3"
    spec:
      containers:
        - name: classification
          image: tender-classification:latest
          imagePullPolicy: Never
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "500m"
              memory: "1Gi"
          envFrom:
            - configMapRef:
                name: pipeline-config
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_SECRET_ACCESS_KEY
            - name: OPENROUTER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: api-keys
                  key: OPENROUTER_API_KEY
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/classification/deployment.yaml
```

- [ ] **Step 3: Apply and verify**

```bash
kubectl apply -f k8s/classification/deployment.yaml
kubectl rollout status deployment/classification -n tender-pipeline --timeout=60s
kubectl logs -n tender-pipeline deployment/classification --tail=20
# Expected: SQS polling log lines for CLASSIFICATION_QUEUE
```

- [ ] **Step 4: Commit**

```bash
git add k8s/classification/deployment.yaml
git commit -m "feat(k8s): add classification Deployment"
```

---

## Task 10: Deploy OCR (stage 2)

**Files:**
- Create: `k8s/ocr/deployment.yaml`

- [ ] **Step 1: Write Deployment**

```yaml
# k8s/ocr/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ocr
  namespace: tender-pipeline
  labels:
    app: ocr
    stage: "2"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ocr
  template:
    metadata:
      labels:
        app: ocr
        stage: "2"
    spec:
      containers:
        - name: ocr
          image: tender-ocr:latest
          imagePullPolicy: Never
          resources:
            requests:
              cpu: "2000m"
              memory: "8Gi"
            limits:
              cpu: "2000m"
              memory: "8Gi"
          envFrom:
            - configMapRef:
                name: pipeline-config
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: AWS_SECRET_ACCESS_KEY
            - name: CUDA_VISIBLE_DEVICES
              value: ""
            - name: OMP_NUM_THREADS
              value: "2"
```

- [ ] **Step 2: Dry-run validate**

```bash
kubectl apply --dry-run=client -f k8s/ocr/deployment.yaml
```

- [ ] **Step 3: Apply and verify**

```bash
kubectl apply -f k8s/ocr/deployment.yaml
kubectl rollout status deployment/ocr -n tender-pipeline --timeout=120s
kubectl logs -n tender-pipeline deployment/ocr --tail=20
# Expected: SQS polling log lines for OCR_QUEUE
```

- [ ] **Step 4: Commit**

```bash
git add k8s/ocr/deployment.yaml
git commit -m "feat(k8s): add ocr Deployment (2 vCPU, 8Gi)"
```

---

## Task 11: End-to-end verification

- [ ] **Step 1: All pods running**

```bash
kubectl get pods -n tender-pipeline
```

Expected: 5 pods all in `Running` state:
```
NAME                              READY   STATUS    RESTARTS
fuseki-0                          1/1     Running   0
ingestion-xxxxxxxxx-xxxxx         1/1     Running   0
extraction-xxxxxxxxx-xxxxx        1/1     Running   0
classification-xxxxxxxxx-xxxxx    1/1     Running   0
ocr-xxxxxxxxx-xxxxx               1/1     Running   0
```

- [ ] **Step 2: Fuseki reachable from ingestion pod**

```bash
kubectl exec -n tender-pipeline deployment/ingestion -- \
  wget -qO- http://fuseki:3030/$/ping
```

Expected: JSON ping response from Fuseki.

- [ ] **Step 3: Fuseki reachable externally via NodePort**

```bash
MINIKUBE_IP=$(minikube -p tender-data-pipeline ip)
curl http://${MINIKUBE_IP}:30030/$/ping
```

Expected: JSON ping response. Note `http://${MINIKUBE_IP}:30030` — this is the `JENA_ENDPOINT` for external clusters on the same LAN.

- [ ] **Step 4: Run ingestion tests against live Fuseki**

```bash
kubectl exec -n tender-pipeline deployment/ingestion -- \
  pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 5: Verify SQS consumers are polling (no crash loops)**

```bash
kubectl logs -n tender-pipeline deployment/ocr --tail=5
kubectl logs -n tender-pipeline deployment/classification --tail=5
kubectl logs -n tender-pipeline deployment/extraction --tail=5
kubectl logs -n tender-pipeline deployment/ingestion --tail=5
```

Each should show polling activity, not crash traces.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat(k8s): complete tender-data-pipeline cluster — all 5 services running"
```

---

## Reference: useful kubectl commands

```bash
# Tail logs for any stage
kubectl logs -n tender-pipeline deployment/<stage> -f

# Restart a deployment (e.g. after rebuilding image)
eval $(minikube -p tender-data-pipeline docker-env)
docker build -t tender-ocr:latest ./2_Ocr
kubectl rollout restart deployment/ocr -n tender-pipeline

# Open Fuseki UI in browser
minikube -p tender-data-pipeline service fuseki-external -n tender-pipeline

# Get minikube node IP (for external clusters JENA_ENDPOINT)
minikube -p tender-data-pipeline ip

# Stop / resume cluster
minikube stop -p tender-data-pipeline
minikube start -p tender-data-pipeline
```
