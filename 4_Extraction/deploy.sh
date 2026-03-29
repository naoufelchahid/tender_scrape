#!/bin/bash
set -e

# Configuration
# Usage: ./deploy.sh [AWS_ACCOUNT_ID] [AWS_REGION]
AWS_ACCOUNT_ID=${1:-$AWS_ACCOUNT_ID}
AWS_REGION=${2:-${AWS_REGION:-eu-west-3}}
REPO_NAME="extraction-container"
IMAGE_TAG="latest"

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "Error: AWS_ACCOUNT_ID is not set."
    echo "Usage: ./deploy.sh <AWS_ACCOUNT_ID> [AWS_REGION]"
    exit 1
fi

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
FULL_IMAGE_NAME="${ECR_URI}/${REPO_NAME}:${IMAGE_TAG}"

echo "🚀 Starting Deployment for ${REPO_NAME}..."
echo "📍 Region: ${AWS_REGION}"
echo "🏭 Registry: ${ECR_URI}"

# 1. Login to ECR
echo "🔑 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# 2. Build Image (from root context)
echo "🏗️  Building Docker Image..."
# We must run from project root to access ../database
cd ..
docker build -t ${REPO_NAME}:${IMAGE_TAG} -f extraction_container/Dockerfile .

# 3. Tag Image
echo "🏷️  Tagging Image..."
docker tag ${REPO_NAME}:${IMAGE_TAG} ${FULL_IMAGE_NAME}

# 4. Push Image
echo "⬆️  Pushing to ECR..."
docker push ${FULL_IMAGE_NAME}

echo "✅ Deployment Complete!"
echo "Image available at: ${FULL_IMAGE_NAME}"
echo "You can now update your ECS Service to force a new deployment."
