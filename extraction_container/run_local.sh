#!/bin/bash
set -e

# Configuration
IMAGE_NAME="extraction-container:local"
ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Environment file $ENV_FILE not found."
    exit 1
fi

echo "🏗️  Building Docker Image..."
# Build from root context to include database folder
cd ..
docker build -t $IMAGE_NAME -f extraction_container/Dockerfile .

echo "🚀 Running Container Locally..."
# Use --network host to allow easy access to localhost DB if needed, 
# or explicit env vars if DB is remote.
# Note: We are in project root now (due to cd ..), so we point to extraction_container/.env
docker run \
    -d \
    --name extraction_service \
    --env-file extraction_container/.env \
    -e BEDROCK_MODEL_ID=qwen/qwen3-235b-a22b-2507 \
    $IMAGE_NAME "$@"
