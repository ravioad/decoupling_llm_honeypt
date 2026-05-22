import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "out" / "raw_outputs_v1_corrected.jsonl"
KB = ROOT / "out" / "kb_docs_v1.jsonl"

_PATH_RE = re.compile(r"(/[^ \n\t'\":]+)+")


def normalize_paths(text: str) -> str:
    # Replace absolute-ish paths with <path> to prevent state-like leakage.
    return _PATH_RE.sub("<path>", text)


def to_scalar_metadata(value: Any) -> Any:
    # Chroma metadata values must be str/int/float/bool (or None).
    
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return ",".join(map(str, value))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def sanitize_metadata(md: dict) -> dict:
    return {k: to_scalar_metadata(v) for k, v in md.items()}


def clean_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    line = normalize_paths(line)
    line = re.sub(r"\s+", " ", line).strip()
    return line

def make_error_phrase_docs(rec: dict) -> list[dict]:
    docs = []
    stderr = rec.get("stderr", "") or ""
    if not stderr.strip():
        return docs

    family = rec.get("family", "unknown")
    outcome = rec.get("outcome", "unknown")
    tags = rec.get("tags", [])
    exit_code = rec.get("exit_code")

    for i, raw in enumerate(stderr.splitlines()):
        line = clean_line(raw)
        if not line:
            continue

        docs.append(
            {
                "doc_id": f"{rec['id']}::err::{i}",
                "text": line,
                "metadata": sanitize_metadata(
                    {
                        "type": "error_phrase",
                        "family": family,
                        "outcome": outcome,
                        "exit_code": exit_code,
                        "tags": tags,
                        "source_case": rec["id"],
                    }
                ),
            }
        )

    return docs


def make_format_hint_docs(rec: dict) -> list[dict]:
    docs = []
    family = rec.get("family", "unknown")
    cmd_str = " ".join(rec.get("cmd", []))
    outcome = rec.get("outcome", "unknown")

    if outcome not in ("success", "unknown"):
        return docs

    if family == "ls" and (
        "ls -l" in cmd_str or "ls -la" in cmd_str or "-l" in cmd_str
    ):
        docs.append(
            {
                "doc_id": f"{rec['id']}::fmt::ls_long",
                "text": "ls -l typically prints: permissions, link count, owner, group, size, mtime, name.",
                "metadata": sanitize_metadata(
                    {
                        "type": "format_hint",
                        "family": "ls",
                        "outcome": outcome,
                        "tags": ["format_hint"],
                        "source_case": rec["id"],
                    }
                ),
            }
        )

    if family == "id":
        docs.append(
            {
                "doc_id": f"{rec['id']}::fmt::id_shape",
                "text": "id output is typically one line: uid=... gid=... groups=....",
                "metadata": sanitize_metadata(
                    {
                        "type": "format_hint",
                        "family": "id",
                        "outcome": outcome,
                        "tags": ["format_hint"],
                        "source_case": rec["id"],
                    }
                ),
            }
        )

    if family == "ps":
        docs.append(
            {
                "doc_id": f"{rec['id']}::fmt::ps_headers",
                "text": "ps outputs a header row and columns such as PID, TTY, TIME, CMD depending on flags.",
                "metadata": sanitize_metadata(
                    {
                        "type": "format_hint",
                        "family": "ps",
                        "outcome": outcome,
                        "tags": ["format_hint"],
                        "source_case": rec["id"],
                    }
                ),
            }
        )

    return docs


def make_banner_docs(rec: dict) -> list[dict]:
    docs = []
    family = rec.get("family", "unknown")
    stdout = rec.get("stdout", "") or ""
    if not stdout.strip():
        return docs

    if family not in ("uname", "hostname"):
        return docs

    first = clean_line(stdout.splitlines()[0])
    if not first:
        return docs

    docs.append(
        {
            "doc_id": f"{rec['id']}::banner::0",
            "text": first,
            "metadata": sanitize_metadata(
                {
                    "type": "banner_sample",
                    "family": family,
                    "outcome": rec.get("outcome", "unknown"),
                    "tags": ["banner"],
                    "source_case": rec["id"],
                }
            ),
        }
    )
    return docs


def make_docs_from_record(rec: dict) -> list[dict]:
    docs = []
    docs.extend(make_error_phrase_docs(rec))
    docs.extend(make_format_hint_docs(rec))
    docs.extend(make_banner_docs(rec))
    return docs


def main() -> None:
    if not RAW.exists():
        raise FileNotFoundError(f"Missing raw dataset: {RAW}")

    all_docs: list[dict] = []
    with open(RAW, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            all_docs.extend(make_docs_from_record(rec))

    KB.parent.mkdir(exist_ok=True)
    with open(KB, "w", encoding="utf-8") as out:
        for d in all_docs:
            out.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"Wrote KB docs: {KB} ({len(all_docs)} docs)")


if __name__ == "__main__":
    main()
