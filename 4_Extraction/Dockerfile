FROM python:3.11-slim

# Install system dependencies for psycopg2 and other tools
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy stage-specific requirements and install Python dependencies
COPY 4_Extraction/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (4_Extraction/* → /app/*)
COPY 4_Extraction/ .

# Copy monitor.py from root (after 4_Extraction to avoid being overwritten)
COPY monitor.py .

# Set Python path to include src
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Entrypoint
CMD ["python", "main.py"]

