FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libreoffice-writer \
    libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create temp directory
RUN mkdir -p /app/temp /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "main.py"]
