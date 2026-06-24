# NeoWatch container image.
#
# Note: the spec suggested python:3.11-slim, but the project requires Python 3.12
# (pyproject `requires-python = ">=3.12"`; numpy 2.x + the 3.12 venv choice from
# Phase 1). We use 3.12-slim to match what the code is actually tested against.
FROM python:3.12-slim

# onnxruntime (ChromaDB's embedding backend) needs libgomp at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer is cached across code-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install the package itself (src layout) so `neowatch` is importable.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Gradio must bind all interfaces inside the container, on the Spaces port.
ENV GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860 \
    PYTHONUNBUFFERED=1
EXPOSE 7860

# The vector store is re-ingested on first run; no persistence is assumed.
CMD ["python", "-m", "neowatch.main"]
