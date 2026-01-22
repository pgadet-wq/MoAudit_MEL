# Docling API Service Dockerfile
# ==============================
# Multi-stage build for optimized production image

# Stage 1: Builder
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For PDF processing
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    # For OCR (Tesseract)
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    # For file type detection
    libmagic1 \
    # Cleanup
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create non-root user
RUN useradd -m -u 1000 docling && \
    mkdir -p /tmp/docling-uploads /root/.cache/docling/models && \
    chown -R docling:docling /tmp/docling-uploads

# Copy application code
COPY src/ ./src/

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=4 \
    DOCLING_LOCAL_STORAGE_PATH=/tmp/docling-uploads \
    DOCLING_MODEL_CACHE_PATH=/root/.cache/docling/models \
    DOCLING_HOST=0.0.0.0 \
    DOCLING_PORT=8001

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run as non-root (optional, comment out if model download needs root)
# USER docling

# Start server
CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8001"]
