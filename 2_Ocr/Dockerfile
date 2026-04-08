FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.11 + system dependencies:
# - poppler-utils: PDF utilities used by Docling
# - libgl1, libglib2.0-0, libsm6, libxext6, libxrender-dev: vision/image libs for Docling
# - libreoffice-writer, libreoffice-calc, default-jre: legacy .doc/.xls conversion via soffice
# - curl: used by uv installer
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    python3.11-venv \
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

# Make python3.11 the default python/python3
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create temp directory with proper permissions
RUN mkdir -p /app/temp && chmod 777 /app/temp

COPY requirements.txt .

# Install Python dependencies with CUDA 12.1 PyTorch wheels (compatible with CUDA 12.2 driver)
RUN uv pip install --system --no-cache-dir \
    --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r requirements.txt

# Pre-download Docling layout models (avoids HuggingFace download on first run)
RUN python -c "\
from docling.document_converter import DocumentConverter, PdfFormatOption; \
from docling.datamodel.pipeline_options import PdfPipelineOptions; \
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend; \
opts = PdfPipelineOptions(do_ocr=True, do_table_structure=True); \
DocumentConverter(format_options={__import__('docling.datamodel.base_models', fromlist=['InputFormat']).InputFormat.PDF: PdfFormatOption(pipeline_options=opts, backend=PyPdfiumDocumentBackend)}); \
print('Docling models cached')" || echo "Docling model pre-cache skipped (non-fatal)"

# Pre-download RapidOCR models (~40MB, avoids modelscope download on first run)
# Note: This may fail if modelscope.cn is unreachable, but it's OK — models will be cached on first use
# If network access is available during build, models are cached; if not, they'll be downloaded at runtime
RUN timeout 60 python -c "\
from rapidocr import RapidOCR; \
ocr = RapidOCR(); \
print('✅ RapidOCR models pre-cached successfully')" 2>/dev/null || echo "⚠️  RapidOCR pre-cache skipped (will download at runtime if needed)"

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
