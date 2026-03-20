FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ontology/ ./ontology/
COPY src/ ./src/
COPY tests/ ./tests/
COPY main.py .
CMD ["python", "main.py"]
