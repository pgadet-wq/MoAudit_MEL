# MoAudit_MEL - Production Dockerfile
# ====================================

FROM python:3.11-slim

# Metadata
LABEL maintainer="MoAudit Team"
LABEL description="MEL/MMEL Audit Pipeline for Aviation Compliance"
LABEL version="1.0.0"

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

# Create non-root user for security
RUN groupadd -r moaudit && useradd -r -g moaudit moaudit

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY data/ ./data/

# Create output directories with proper permissions
RUN mkdir -p outputs data/uploads logs \
    && chown -R moaudit:moaudit /app

# Switch to non-root user
USER moaudit

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
