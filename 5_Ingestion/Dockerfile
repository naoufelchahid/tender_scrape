FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY 5_Ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and shared dependencies
COPY 5_Ingestion/ontology/ ./ontology/
COPY 5_Ingestion/src/ ./src/
COPY 5_Ingestion/tests/ ./tests/
COPY 5_Ingestion/main.py .
COPY monitor.py .

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
