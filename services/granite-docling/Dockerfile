# Granite-Docling-258M vLLM Server
# =================================
# Production-ready VLM inference server for document processing

FROM vllm/vllm-openai:latest

# Environment variables
ENV MODEL_NAME="ibm-granite/granite-docling-258M" \
    MODEL_REVISION="untied" \
    PORT=8000 \
    MAX_MODEL_LEN=8192 \
    GPU_MEMORY_UTILIZATION=0.85 \
    MAX_NUM_SEQS=256 \
    DTYPE="auto"

# Create cache directories
RUN mkdir -p /root/.cache/huggingface

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start vLLM OpenAI-compatible server
CMD python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_NAME} \
    --revision ${MODEL_REVISION} \
    --port ${PORT} \
    --max-model-len ${MAX_MODEL_LEN} \
    --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} \
    --max-num-seqs ${MAX_NUM_SEQS} \
    --dtype ${DTYPE} \
    --trust-remote-code
