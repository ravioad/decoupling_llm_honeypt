#!/usr/bin/env bash
# Run the honeypot SSH server locally (no Docker)
# Prerequisites: ChromaDB running (docker run -p 8000:8000 chromadb/chroma)
#
# Usage: ./run_local.sh
#   --new-session   Start a fresh session (default: resume latest existing session)

set -euo pipefail
cd "$(dirname "$0")"


if [[ -f .env ]]; then
  set -a
  source .env
  set +a
  echo "[run_local] loaded .env"
fi


CHROMA_HOST="${CHROMA_HOST:-localhost}"
CHROMA_PORT="${CHROMA_PORT:-8000}"
CHROMA_URL="http://${CHROMA_HOST}:${CHROMA_PORT}"
echo "[run_local] checking Chroma at ${CHROMA_URL}"
for i in $(seq 1 30); do
  if curl -sf "${CHROMA_URL}/api/v2/heartbeat" >/dev/null 2>&1; then
    echo "[run_local] Chroma is up"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "[run_local] ERROR: Chroma not reachable. Start it first:"
    echo "  docker run -d -p 8000:8000 chromadb/chroma"
    exit 1
  fi
  sleep 1
done

USE_LLM_RENDERER="${USE_LLM_RENDERER:-false}"
if [[ "${USE_LLM_RENDERER}" == "true" ]]; then
  OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
  OLLAMA_URL="${OLLAMA_URL%/}"  # strip trailing slash
  OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
  echo "[run_local] checking Ollama at ${OLLAMA_URL} (model: ${OLLAMA_MODEL})"
  if ! curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    echo "[run_local] ERROR: Ollama not reachable at ${OLLAMA_URL}"
    echo "  Start Ollama first: docker-compose up -d ollama   (or: ollama serve)"
    echo "  Then pull the model: ollama pull ${OLLAMA_MODEL}"
    exit 1
  fi
  if ! curl -sf "${OLLAMA_URL}/api/show" -d "{\"model\": \"${OLLAMA_MODEL}\"}" -H "Content-Type: application/json" >/dev/null 2>&1; then
    echo "[run_local] WARN: Model '${OLLAMA_MODEL}' may not be pulled."
    echo "  Run: ollama pull ${OLLAMA_MODEL}"
  else
    echo "[run_local] Ollama is up, model ${OLLAMA_MODEL} available"
  fi
fi

KB_PATH="${KB_PATH:-../rag-corpus/out/kb_docs_v1.jsonl}"
if [[ -f "$KB_PATH" ]]; then
  echo "[run_local] ingesting RAG corpus from ${KB_PATH}"
  KB_PATH="$KB_PATH" CHROMA_HOST="$CHROMA_HOST" CHROMA_PORT="$CHROMA_PORT" \
    python ../rag-corpus/src/ingest_chroma.py
else
  echo "[run_local] WARN: KB_PATH not found (${KB_PATH}), RAG will return empty. Create it first."
fi

echo "[run_local] starting SSH server on port ${PORT:-2222}"
python ssh_server.py "$@"
