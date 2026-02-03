#!/bin/bash
# Stage: Infrastructure Deployment
# Deploy OCR container to AWS ECS with GPU support

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}=== OCR Container ECS Deployment ===${NC}"

# Load environment variables from .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${YELLOW}Loading environment variables from .env...${NC}"
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
else
    echo -e "${RED}Error: .env file not found!${NC}"
    exit 1
fi

# Verify required variables
required_vars=("AWS_REGION" "AWS_ACCESS_KEY_ID" "AWS_SECRET_ACCESS_KEY" "S3_BUCKET_NAME" "OCR_QUEUE_URL" "CLASSIFICATION_QUEUE_URL")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}Error: $var not set in .env${NC}"
        exit 1
    fi
done

# Configuration
REPOSITORY_NAME="ocr-cuda-container"
CLUSTER_NAME="ocr-gpu-cluster"
TASK_FAMILY="ocr-cuda-task"
SERVICE_NAME="ocr-cuda-service"

echo -e "${GREEN}Configuration:${NC}"
echo "  Region: $AWS_REGION"
echo "  Repository: $REPOSITORY_NAME"
echo "  Cluster: $CLUSTER_NAME"
echo ""

# Step 1: Create ECR repository if it doesn't exist
echo -e "${YELLOW}Step 1: Checking/Creating ECR repository...${NC}"
if aws ecr describe-repositories --repository-names "$REPOSITORY_NAME" --region "$AWS_REGION" 2>/dev/null; then
    echo "  ✓ Repository exists"
else
    echo "  Creating repository..."
    aws ecr create-repository \
        --repository-name "$REPOSITORY_NAME" \
        --region "$AWS_REGION" \
        --image-scanning-configuration scanOnPush=true \
        --tags Key=Project,Value=TenderScraper Key=Component,Value=OCR
    echo "  ✓ Repository created"
fi

# Get repository URI
ECR_REPO_URI=$(aws ecr describe-repositories \
    --repository-names "$REPOSITORY_NAME" \
    --region "$AWS_REGION" \
    --query 'repositories[0].repositoryUri' \
    --output text)
echo "  ECR URI: $ECR_REPO_URI"

# Step 2: Authenticate Docker with ECR
echo -e "${YELLOW}Step 2: Authenticating Docker with ECR...${NC}"
aws ecr get-login-password --region "$AWS_REGION" | \
    docker login --username AWS --password-stdin "${ECR_REPO_URI%/*}"
echo "  ✓ Docker authenticated"

# Step 3: Build Docker image
echo -e "${YELLOW}Step 3: Building Docker image...${NC}"
docker build -t "$REPOSITORY_NAME:latest" "$SCRIPT_DIR"
echo "  ✓ Image built"

# Step 4: Tag and push to ECR
echo -e "${YELLOW}Step 4: Pushing image to ECR...${NC}"
VERSION_TAG="v$(date +%Y%m%d-%H%M%S)"
docker tag "$REPOSITORY_NAME:latest" "$ECR_REPO_URI:latest"
docker tag "$REPOSITORY_NAME:latest" "$ECR_REPO_URI:$VERSION_TAG"

docker push "$ECR_REPO_URI:latest"
docker push "$ECR_REPO_URI:$VERSION_TAG"
echo "  ✓ Image pushed with tags: latest, $VERSION_TAG"

# Step 5: Create ECS cluster if it doesn't exist
echo -e "${YELLOW}Step 5: Checking/Creating ECS cluster...${NC}"
if aws ecs describe-clusters --clusters "$CLUSTER_NAME" --region "$AWS_REGION" \
    --query 'clusters[0].status' --output text | grep -q "ACTIVE" 2>/dev/null; then
    echo "  ✓ Cluster exists"
else
    echo "  Creating cluster..."
    aws ecs create-cluster \
        --cluster-name "$CLUSTER_NAME" \
        --region "$AWS_REGION" \
        --tags key=Project,value=TenderScraper
    echo "  ✓ Cluster created"
fi

# Step 6: Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Step 7: Create IAM roles
echo -e "${YELLOW}Step 6: Setting up IAM roles...${NC}"

# Create trust policy
cat > /tmp/ecs-task-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Task Execution Role
if aws iam get-role --role-name ecsOCRTaskExecutionRole 2>/dev/null; then
    echo "  ✓ Task execution role exists"
else
    echo "  Creating task execution role..."
    aws iam create-role \
        --role-name ecsOCRTaskExecutionRole \
        --assume-role-policy-document file:///tmp/ecs-task-trust-policy.json
    
    aws iam attach-role-policy \
        --role-name ecsOCRTaskExecutionRole \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    echo "  ✓ Task execution role created"
fi

# Task Role with S3/SQS permissions
if aws iam get-role --role-name ecsOCRTaskRole 2>/dev/null; then
    echo "  ✓ Task role exists"
else
    echo "  Creating task role..."
    aws iam create-role \
        --role-name ecsOCRTaskRole \
        --assume-role-policy-document file:///tmp/ecs-task-trust-policy.json
    
    # Create inline policy
    cat > /tmp/ocr-task-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::${S3_BUCKET_NAME}/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:SendMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": [
        "arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:OCR_QUEUE",
        "arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:CLASSIFICATION_QUEUE"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
EOF
    
    aws iam put-role-policy \
        --role-name ecsOCRTaskRole \
        --policy-name OCRTaskPermissions \
        --policy-document file:///tmp/ocr-task-policy.json
    echo "  ✓ Task role created"
fi

# Step 8: Create CloudWatch Log Group
echo -e "${YELLOW}Step 7: Setting up CloudWatch logs...${NC}"
if aws logs describe-log-groups \
    --log-group-name-prefix "/ecs/$TASK_FAMILY" \
    --region "$AWS_REGION" 2>/dev/null | grep -q "$TASK_FAMILY"; then
    echo "  ✓ Log group exists"
else
    aws logs create-log-group \
        --log-group-name "/ecs/$TASK_FAMILY" \
        --region "$AWS_REGION"
    echo "  ✓ Log group created"
fi

# Step 9: Register task definition
echo -e "${YELLOW}Step 8: Registering ECS task definition...${NC}"

cat > /tmp/task-definition.json <<EOF
{
  "family": "${TASK_FAMILY}",
  "networkMode": "bridge",
  "requiresCompatibilities": ["EC2"],
  "cpu": "4096",
  "memory": "16384",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsOCRTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsOCRTaskRole",
  "containerDefinitions": [
    {
      "name": "${REPOSITORY_NAME}",
      "image": "${ECR_REPO_URI}:latest",
      "cpu": 4096,
      "memory": 16384,
      "essential": true,
      "resourceRequirements": [
        {
          "type": "GPU",
          "value": "1"
        }
      ],
      "environment": [
        {"name": "AWS_REGION", "value": "${AWS_REGION}"},
        {"name": "S3_BUCKET_NAME", "value": "${S3_BUCKET_NAME}"},
        {"name": "OCR_QUEUE_URL", "value": "${OCR_QUEUE_URL}"},
        {"name": "CLASSIFICATION_QUEUE_URL", "value": "${CLASSIFICATION_QUEUE_URL}"},
        {"name": "OPENROUTER_API_KEY", "value": "${OPENROUTER_API_KEY}"},
        {"name": "PRIMARY_MODEL", "value": "${PRIMARY_MODEL:-meta-llama/llama-4-maverick}"},
        {"name": "FALLBACK_MODEL_1", "value": "${FALLBACK_MODEL_1:-meta-llama/llama-guard-4-12b}"},
        {"name": "FALLBACK_MODEL_2", "value": "${FALLBACK_MODEL_2:-meta-llama/llama-4-scout}"},
        {"name": "MAX_RETRIES", "value": "${MAX_RETRIES:-3}"},
        {"name": "VISIBILITY_TIMEOUT", "value": "${VISIBILITY_TIMEOUT:-900}"},
        {"name": "BATCH_SIZE", "value": "${BATCH_SIZE:-10}"},
        {"name": "ENABLE_TABLE_ENHANCEMENT", "value": "${ENABLE_TABLE_ENHANCEMENT:-true}"},
        {"name": "MAX_WORKERS", "value": "${MAX_WORKERS:-10}"},
        {"name": "CUDA_VISIBLE_DEVICES", "value": "0"},
        {"name": "PYTORCH_CUDA_ALLOC_CONF", "value": "max_split_size_mb:512"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${TASK_FAMILY}",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ocr"
        }
      }
    }
  ]
}
EOF

aws ecs register-task-definition \
    --cli-input-json file:///tmp/task-definition.json \
    --region "$AWS_REGION" > /dev/null
echo "  ✓ Task definition registered"

# Cleanup temp files
rm -f /tmp/ecs-task-trust-policy.json /tmp/ocr-task-policy.json /tmp/task-definition.json

echo ""
echo -e "${GREEN}=== Deployment Summary ===${NC}"
echo "  ✓ ECR Repository: $ECR_REPO_URI"
echo "  ✓ Image Tags: latest, $VERSION_TAG"
echo "  ✓ ECS Cluster: $CLUSTER_NAME"
echo "  ✓ Task Definition: $TASK_FAMILY"
echo ""
echo -e "${YELLOW}=== Next Steps ===${NC}"
echo ""
echo "To run this container, you need a GPU-enabled EC2 instance:"
echo ""
echo "1. Launch a GPU instance (g4dn.xlarge recommended):"
echo "   - Use ECS-optimized GPU AMI"
echo "   - Configure it to join cluster: $CLUSTER_NAME"
echo ""
echo "2. Run the task:"
echo "   aws ecs run-task \\"
echo "       --cluster $CLUSTER_NAME \\"
echo "       --task-definition $TASK_FAMILY \\"
echo "       --count 1 \\"
echo "       --region $AWS_REGION"
echo ""
echo "3. Or create a service:"
echo "   aws ecs create-service \\"
echo "       --cluster $CLUSTER_NAME \\"
echo "       --service-name $SERVICE_NAME \\"
echo "       --task-definition $TASK_FAMILY \\"
echo "       --desired-count 1 \\"
echo "       --region $AWS_REGION"
echo ""
echo "4. Monitor logs:"
echo "   aws logs tail /ecs/$TASK_FAMILY --follow --region $AWS_REGION"
echo ""
echo -e "${GREEN}Deployment completed successfully!${NC}"
