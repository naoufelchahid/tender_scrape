FROM python:3.11-slim-bookworm

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies:
# - poppler-utils: PDF utilities used by Docling
# - libgl1, libglib2.0-0, libsm6, libxext6, libxrender-dev: vision/image libs for Docling
# - libreoffice-writer, libreoffice-calc, default-jre: legacy .doc/.xls conversion via soffice
# - curl: used by uv installer
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libreoffice-writer \
    libreoffice-calc \
    default-jre \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements.txt .

# Install Python dependencies with CPU-only PyTorch wheels
RUN uv pip install --system --no-cache-dir \
    --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# Disable GPU explicitly and cap OpenMP threads
ENV CUDA_VISIBLE_DEVICES=""
ENV OMP_NUM_THREADS=2

CMD ["python", "main.py"]
