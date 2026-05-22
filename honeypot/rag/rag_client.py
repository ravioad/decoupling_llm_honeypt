from __future__ import annotations

import os
import time
from typing import Any, Optional, Tuple

from .rag_query import RagQuery


def _build_where(q: RagQuery) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []

    if q.family:
        clauses.append({"family": q.family})

    if q.wanted_types:
        if len(q.wanted_types) == 1:
            clauses.append({"type": q.wanted_types[0]})
        else:
            clauses.append({"type": {"$in": q.wanted_types}})

    if q.outcome and ("error_phrase" in q.wanted_types):
        clauses.append({"outcome": q.outcome})

    if not clauses:
        return None

    if len(clauses) == 1:
        return clauses[0]

    return {"$and": clauses}


def retrieve_rag_context(
    q: RagQuery,
    *,
    host: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    """Query ChromaDB and return a ragctx.v1 dict; sets status='error' on failure."""
    os.environ.setdefault("CHROMA_TELEMETRY", "false")
    host = host or os.getenv("CHROMA_HOST", "localhost")
    port = port or int(os.getenv("CHROMA_PORT", "8000"))

    t0 = time.time()
    where = _build_where(q)

    ctx: dict[str, Any] = {
        "schema_version": "ragctx.v1",
        "status": "error",
        "query": {
            "collection": q.collection,
            "family": q.family,
            "outcome": q.outcome,
            "wanted_types": q.wanted_types,
            "query_text": q.query_text,
            "k": q.k,
            "where": where,
        },
        "results": [],
        "stats": {"took_ms": 0, "returned": 0},
    }

    try:
        import chromadb

        client = chromadb.HttpClient(host=host, port=port)
        col = client.get_collection(q.collection)

        res = col.query(
            query_texts=[q.query_text],
            n_results=q.k,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        docs = res.get("documents", [[]])[0] or []
        metas = res.get("metadatas", [[]])[0] or []
        dists = res.get("distances", [[]])[0] or []
        ids = res.get("ids", [[]])[0] or []

        results = []
        for doc_id, text, meta, dist in zip(ids, docs, metas, dists):
            results.append(
                {
                    "doc_id": doc_id,
                    "text": text,
                    "metadata": meta,
                    "distance": float(dist) if dist is not None else None,
                }
            )

        ctx["results"] = results
        ctx["stats"]["returned"] = len(results)

        if len(results) == 0:
            ctx["status"] = "empty"
        else:
            ctx["status"] = "ok"

    except Exception as e:
        ctx["status"] = "error"
        ctx["error"] = {"type": type(e).__name__, "message": str(e)}

    finally:
        ctx["stats"]["took_ms"] = int((time.time() - t0) * 1000)

    return ctx


def get_ragctx(
    *,
    collection: str,
    family: str,
    outcome: str,
    wanted_types: list[str],
    query_text: str,
    k: int = 3,
) -> dict[str, Any]:
    """Build a RagQuery and return the ragctx.v1 result dict."""
    try:
        q = RagQuery(
            collection=collection,
            family=family,
            outcome=outcome,
            wanted_types=wanted_types,
            query_text=query_text,
            k=k,
        )
        ctx = retrieve_rag_context(q)
        if not isinstance(ctx, dict):
            return {
                "schema_version": "ragctx.v1",
                "status": "error",
                "error": {"message": "retrieve_rag_context returned non-dict"},
            }
        return ctx
    except Exception as e:
        return {
            "schema_version": "ragctx.v1",
            "status": "error",
            "error": {"message": str(e)},
        }


def pick_first_text(ctx: dict[str, Any], wanted_type: str) -> Optional[str]:
    if ctx.get("status") != "ok":
        return None
    for r in ctx.get("results") or []:
        md = r.get("metadata") or {}
        if md.get("type") == wanted_type:
            return r.get("text")
    return None


def extract_rag_phrases(ragctx: Any) -> Tuple[Optional[str], Optional[str]]:
    """Extract (rag_error_phrase, rag_format_hint) from a ragctx.v1 dict."""
    try:
        if not isinstance(ragctx, dict):
            return None, None
        if ragctx.get("schema_version") != "ragctx.v1":
            return None, None
        if ragctx.get("status") != "ok":
            return None, None

        results = ragctx.get("results") or []
        if not isinstance(results, list):
            return None, None

        err: Optional[str] = None
        hint: Optional[str] = None

        for item in results:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") or {}
            if not isinstance(meta, dict):
                continue
            t = meta.get("type")
            text = item.get("text")
            if not isinstance(text, str) or not text:
                continue

            if t == "error_phrase" and err is None:
                err = text
            elif t == "format_hint" and hint is None:
                hint = text

            if err is not None and hint is not None:
                break

        return err, hint
    except Exception:
        return None, None
