FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set working directory
WORKDIR /app

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.11 and system dependencies
# Added Python 3.11 (not included in CUDA base image)
# Kept tesseract-ocr and libtesseract-dev for widespread OCR support compatibility
# Kept poppler-utils and GL libs which are common for vision/pdf tasks
# Kept LibreOffice and Java for legacy format conversion
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3-pip \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    tesseract-ocr \
    libtesseract-dev \
    libreoffice-writer \
    libreoffice-calc \
    default-jre \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with GPU support
# Use uv for faster installation with PyTorch CUDA index
# Use unsafe-best-match to allow resolution from both PyTorch and PyPI indexes
RUN uv pip install --system --no-cache-dir \
    --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
# GPU Configuration
ENV CUDA_VISIBLE_DEVICES=0
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
# Optimized for higher memory usage of ML models if needed
ENV OMP_NUM_THREADS=1 

# Run the main script
CMD ["python", "main.py"]
