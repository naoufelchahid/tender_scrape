FROM python:3.11-slim

# Install system dependencies for psycopg2 and other tools
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY extraction_container/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy database models (shared dependency)
COPY database /app/database

# Copy application code
COPY extraction_container .

# Set Python path to include src
ENV PYTHONPATH=/app

# Entrypoint
CMD ["python", "main.py"]
