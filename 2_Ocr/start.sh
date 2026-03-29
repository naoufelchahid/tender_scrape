#!/bin/bash
# Quick start script for OCR container

echo "🚀 Starting OCR Container Setup..."
echo ""

# Check if .env file exists and has required variables
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create .env file from .env.example and configure it."
    exit 1
fi

# Check if required variables are set
echo "✓ Checking .env configuration..."
grep -q "OCR_QUEUE_URL=" .env && echo "  ✓ OCR_QUEUE_URL is set" || echo "  ❌ OCR_QUEUE_URL is missing"
grep -q "EXTRACTION_QUEUE_URL=" .env && echo "  ✓ EXTRACTION_QUEUE_URL is set" || echo "  ❌ EXTRACTION_QUEUE_URL is missing"
grep -q "OPENROUTER_API_KEY=" .env && echo "  ✓ OPENROUTER_API_KEY is set" || echo "  ❌ OPENROUTER_API_KEY is missing"
grep -q "AWS_ACCESS_KEY_ID=" .env && echo "  ✓ AWS_ACCESS_KEY_ID is set" || echo "  ❌ AWS_ACCESS_KEY_ID is missing"
echo ""

# Build Docker image
echo "🔨 Building Docker image..."
docker build -t ocr-service:latest .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed!"
    exit 1
fi

echo "✓ Docker image built successfully!"
echo ""

# Create temp and logs directories
echo "📁 Creating directories..."
mkdir -p temp logs
echo "✓ Directories created"
echo ""

# Run container
echo "🐳 Starting OCR container..."
echo ""
docker run -d \
  --name ocr-container \
  --env-file .env \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/temp:/app/temp" \
  --restart unless-stopped \
  ocr-service:latest

if [ $? -ne 0 ]; then
    echo "❌ Failed to start container!"
    exit 1
fi

echo "✅ OCR Container started successfully!"
echo ""
echo "📋 Useful commands:"
echo "  View logs:     docker logs -f ocr-container"
echo "  Stop container: docker stop ocr-container"
echo "  Remove container: docker rm ocr-container"
echo "  Restart container: docker restart ocr-container"
echo ""
echo "🔍 Viewing initial logs..."
sleep 2
docker logs ocr-container
