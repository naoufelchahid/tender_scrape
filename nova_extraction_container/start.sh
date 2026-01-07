#!/bin/bash

# Build and start Nova Extraction Container

echo "=================================="
echo "Nova Extraction Container - Start"
echo "=================================="

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please copy .env.example to .env and configure it."
    exit 1
fi

# Build Docker image
echo "🔨 Building Docker image..."
docker build -t nova-extraction:latest .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed!"
    exit 1
fi

echo "✅ Docker image built successfully"

# Start container
echo "🚀 Starting container..."
docker-compose up -d

if [ $? -ne 0 ]; then
    echo "❌ Failed to start container!"
    exit 1
fi

echo "✅ Container started successfully"
echo ""
echo "📊 View logs with: docker logs -f nova-extraction-container"
echo "🛑 Stop with: docker-compose down"
echo ""
