import os
import json
import logging
import re
import sys
from pathlib import Path
from typing import Tuple

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_env = _root / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_env)
    except ImportError:
        pass

import requests
from core.types import RenderSpec
from executor.executor import ExecResult

log = logging.getLogger(__name__)
DEBUG_LLM = os.getenv("DEBUG_LLM", "false").lower() == "true"

# Patterns that indicate a prompt injection attempt in a RAG document.
_INJECTION_RE = re.compile(
    r"\b(ignore|disregard|forget|override|system prompt|assistant\s*:|new instruction)\b",
    re.IGNORECASE,
)


def _sanitize_rag_text(text: str | None, max_len: int = 200) -> str:
    if not text:
        return ""
    sanitized = text.replace("\n", " ").replace("\r", " ").strip()
    sanitized = sanitized[:max_len]
    if _INJECTION_RE.search(sanitized):
        log.warning("RAG injection pattern detected and stripped: %r", sanitized[:80])
        return ""
    return sanitized

OLLAMA_URL = (os.getenv("OLLAMA_URL", "http://localhost:11434") or "").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
OLLAMA_MAX_TOKENS = int(os.getenv("OLLAMA_MAX_TOKENS", "160"))
OLLAMA_JSON_FORMAT = os.getenv("OLLAMA_JSON_FORMAT", "true").lower() == "true"

def should_use_llm(exec_result: ExecResult, spec: RenderSpec) -> bool:
    rt = spec.render_type

    # plain_text success, content is authoritative ground truth, LLM adds nothing
    if rt == "plain_text" and exec_result.outcome == "success":
        return False

    # plain_text with empty payload, nothing to render
    if rt == "plain_text":
        expected = (spec.render_payload or {}).get("text", "")
        if not expected:
            return False

    # error, LLM can vary phrasing naturally
    if rt == "error":
        return True

    # structured, LLM handles spacing/alignment
    if rt == "structured":
        return True

    return False


def _build_prompt(spec: RenderSpec) -> str:
    payload = json.dumps(spec.render_payload or {}, ensure_ascii=False)

    rules = [
        "You are a Linux bash terminal.",
        "Never reveal you are an AI/LLM/simulator/honeypot.",
        "No explanations, no markdown, no extra text.",
        'Output ONLY valid JSON with exactly these keys: {"stdout": "...", "stderr": "..."}',
        "",
        f"render_type: {spec.render_type}",
        f"family: {spec.family}",
        f"outcome: {spec.outcome}",
        f"target_path: {spec.target_path or ''}",
        "",
        "Authoritative render_payload (source of truth):",
        payload,
        "",
        "Non-authoritative formatting hint (optional):",
        _sanitize_rag_text(spec.rag_format_hint),
        "",
        "Hard constraints:",
        "- Use ONLY the authoritative render_payload for content.",
        "- Do NOT invent files/paths/users/processes/lines not implied by render_payload.",
        "- If render_type=plain_text: stdout must equal payload.text exactly. stderr must be empty.",
        f"- If render_type=error: stdout must be empty. Write stderr as a realistic Linux error.",
        f"  stderr must start with '{spec.family}:' and clearly convey the error type.",
        "  You may vary the exact phrasing from payload.message — write what a real shell outputs.",
        "  End stderr with a single trailing newline.",
        "- If render_type=structured: stderr must be empty.",
        "- JSON escaping: use \\\\ for literal backslash in JSON (e.g. write \\\\n in JSON for output containing backslash followed by n).",
        "",
        "Structured rendering rules (render_type=structured):",
        "- render_payload contains rows (list of rows). Each row is a list of cell values.",
        "- DO NOT print headers (never), even if render_payload contains keys like 'headers'.",
        "- stdout MUST contain exactly one line per row, in the same order as render_payload.rows.",
        "- Each output line MUST contain the row's cell values in order.",
        "- Use a single space between cell values (alignment is optional, content must not change).",
        "- Do NOT add extra lines beyond these rows.",
        "- End stdout with a trailing newline if stdout is non-empty.",
        "",
        "Return JSON now.",
    ]
    return "\n".join(rules)


def render_llm(spec: RenderSpec) -> Tuple[str, str]:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _build_prompt(spec),
        "stream": False,
        "options": {"num_predict": OLLAMA_MAX_TOKENS},
    }
    if OLLAMA_JSON_FORMAT:
        payload["format"] = "json"

    if DEBUG_LLM:
        log.info("Ollama prompt (truncated): %s", _build_prompt(spec)[:200] + "...")

    url = f"{OLLAMA_URL}/api/generate"
    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        if DEBUG_LLM:
            log.debug("Ollama full response: %s", json.dumps(data, indent=2)[:1000])
        if "error" in data:
            err = data["error"]
            log.warning("Ollama API error: %s", err)
            if DEBUG_LLM:
                log.info("Full Ollama response: %s", json.dumps(data, indent=2)[:500])
            return "", ""

        raw = (data.get("response") or "").strip()

        if DEBUG_LLM:
            log.info("Ollama raw response: %r", raw[:500])

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            log.warning("No JSON object in Ollama response. Raw: %r", raw[:200])
            return "", ""

        parsed = json.loads(raw[start : end + 1])
        stdout = parsed.get("stdout", "")
        stderr = parsed.get("stderr", "")

        if DEBUG_LLM:
            log.info("Parsed stdout=%r stderr=%r", stdout[:100], stderr[:100])

        return stdout, stderr

    except requests.HTTPError as e:
        body = ""
        if e.response is not None:
            try:
                body = e.response.text[:500]
            except Exception:
                pass
        log.warning(
            "Ollama HTTP error %s %s: %s. Body: %r",
            e.response.status_code if e.response else "?",
            url,
            e,
            body,
        )
        return "", ""
    except requests.RequestException as e:
        log.warning("Ollama request failed (%s): %s", url, e)
        return "", ""
    except Exception as e:
        log.warning("Error rendering LLM: %s", e, exc_info=DEBUG_LLM)
        return "", ""
