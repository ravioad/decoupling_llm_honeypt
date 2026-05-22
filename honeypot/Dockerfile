FROM python:3.11-slim

WORKDIR /app

RUN apt-get update -o Acquire::Retries=3 \
  && apt-get install -y --no-install-recommends \
    ca-certificates wget \
  && rm -rf /var/lib/apt/lists/*

COPY honeypot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY honeypot/ /app/
COPY rag-corpus/ /app/rag-corpus/

RUN chmod +x /app/entrypoint.sh

EXPOSE 2222
CMD ["/app/entrypoint.sh"]