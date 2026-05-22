#!/usr/bin/env bash
set -euo pipefail

echo "[honeypot] starting entrypoint"

# Wait for chroma
CHROMA_URL="${CHROMA_URL:-http://chromadb:8000}"
echo "[honeypot] waiting for chroma at ${CHROMA_URL}"
for i in $(seq 1 60); do
  if wget -qO- "${CHROMA_URL}/api/v2/heartbeat" >/dev/null 2>&1; then
    echo "[honeypot] chroma is up"
    break
  fi
  sleep 1
done

if [[ "${RUN_CHROMA_INGEST_ON_STARTUP:-false}" == "true" ]]; then
  echo "[honeypot] ingest on startup enabled"

  KB_PATH="/app/rag-corpus/out/kb_docs_v1.jsonl" \
  CHROMA_HOST="chromadb" \
  CHROMA_PORT="8000" \
  CHROMA_COLLECTION="shell_context" \
  python /app/rag-corpus/src/ingest_chroma.py
  echo "[honeypot] ingest complete"
else
  echo "[honeypot] ingest on startup disabled"
fi

echo "[honeypot] starting ssh server"
python ssh_server.py