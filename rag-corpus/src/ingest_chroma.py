import json
import os
from pathlib import Path

import chromadb


ROOT = Path(__file__).resolve().parents[1]
KB = Path(os.getenv("KB_PATH", str(ROOT / "out" / "kb_docs_v1.jsonl")))

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = os.getenv("CHROMA_COLLECTION", "shell_context")


def main() -> None:
    if not KB.exists():
        raise FileNotFoundError(f"Missing KB docs: {KB}")

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass

    col = client.create_collection(name=COLLECTION)

    ids, docs, metas = [], [], []
    with open(KB, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            ids.append(obj["doc_id"])
            docs.append(obj["text"])
            metas.append(obj["metadata"])

    col.add(ids=ids, documents=docs, metadatas=metas)

    print(f"Ingested {len(ids)} docs into Chroma collection '{COLLECTION}'")

if __name__ == "__main__":
    main()
