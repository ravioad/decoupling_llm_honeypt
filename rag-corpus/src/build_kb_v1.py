import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW_CORRECTED = ROOT / "out" / "raw_outputs_v1_corrected.jsonl"
RAW_DEFAULT = ROOT / "out" / "raw_outputs_v1.jsonl"
RAW = RAW_CORRECTED if RAW_CORRECTED.exists() else RAW_DEFAULT

KB = ROOT / "out" / "kb_docs_v1.jsonl"

_PATH_RE = re.compile(r"(/[^ \n\t'\":]+)+")
_WS_RE = re.compile(r"\s+")


def normalize_paths(text: str) -> str:
    return _PATH_RE.sub("<path>", text)


def clean_line(line: str) -> str:
    line = (line or "").strip()
    if not line:
        return ""
    line = normalize_paths(line)
    line = _WS_RE.sub(" ", line).strip()
    return line


def to_scalar_metadata(value: Any) -> Any:
    #Chroma metadata values must be str/int/float/bool (or None).
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return ",".join(map(str, value))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def sanitize_metadata(md: dict) -> dict:
    return {k: to_scalar_metadata(v) for k, v in md.items()}


def doc(doc_id: str, text: str, metadata: dict) -> dict:
    return {"doc_id": doc_id, "text": text, "metadata": sanitize_metadata(metadata)}


def make_error_phrase_docs(rec: dict) -> list[dict]:
    stderr = rec.get("stderr", "") or ""
    if not stderr.strip():
        return []

    out = []
    family = rec.get("family", "unknown")
    outcome = rec.get(
        "outcome", rec.get("inferred_outcome", rec.get("declared_outcome", "unknown"))
    )
    tags = rec.get("tags", [])
    exit_code = rec.get("exit_code")

    for i, raw in enumerate(stderr.splitlines()):
        line = clean_line(raw)
        if not line:
            continue
        out.append(
            doc(
                f"{rec['id']}::err::{i}",
                line,
                {
                    "type": "error_phrase",
                    "family": family,
                    "outcome": outcome,
                    "exit_code": exit_code,
                    "tags": tags,
                    "source_case": rec["id"],
                },
            )
        )
    return out


FORMAT_HINTS = {
    # Small single-line commands
    "whoami": ["whoami outputs the effective username as a single line."],
    "pwd": [
        "pwd outputs the current working directory as a single absolute path line."
    ],
    "hostname": ["hostname outputs the system hostname as a single line."],
    "uname": [
        "uname -a outputs a single line containing kernel and system information."
    ],
    # Environment / key-value shapes
    "env": ["env typically prints multiple lines of KEY=value pairs."],
    "id": ["id output is typically one line: uid=... gid=... groups=...."],
    # Listings and tables
    "ls": [
        "ls -l typically prints: permissions, link count, owner, group, size, mtime, name."
    ],
    "ps": [
        "ps outputs a header row and columns such as PID, TTY, TIME, CMD depending on flags.",
        "ps output is table-like with aligned whitespace columns.",
    ],
    "df": [
        "df outputs a header row and a table of filesystem usage columns (e.g., Filesystem, 1K-blocks, Used, Available, Use%, Mounted on).",
        "df output is table-like with aligned whitespace columns.",
    ],
    "free": [
        "free outputs a small table with memory totals (e.g., total, used, free, shared, buff/cache, available).",
        "free output is table-like with aligned whitespace columns.",
    ],
    # Network
    "ip": [
        "ip addr outputs a numbered list of network interfaces, each with inet/inet6 addresses and link details.",
    ],
    "ifconfig": [
        "ifconfig outputs interface entries separated by blank lines, each with flags, inet, netmask, broadcast, and ether fields.",
    ],
}


def make_format_hint_docs(rec: dict) -> list[dict]:
    family = rec.get("family", "unknown")
    outcome = rec.get(
        "outcome", rec.get("inferred_outcome", rec.get("declared_outcome", "unknown"))
    )

    if outcome != "success":
        return []

    hints = FORMAT_HINTS.get(family, [])
    if not hints:
        return []

    out = []
    for i, hint in enumerate(hints):
        out.append(
            doc(
                f"{rec['id']}::fmt::{family}::{i}",
                hint,
                {
                    "type": "format_hint",
                    "family": family,
                    "outcome": outcome,
                    "tags": ["format_hint"],
                    "source_case": rec["id"],
                },
            )
        )
    return out


def make_docs_from_record(rec: dict) -> list[dict]:
    docs = []
    docs.extend(make_error_phrase_docs(rec))
    docs.extend(make_format_hint_docs(rec))
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

    from collections import Counter

    types = Counter(d["metadata"]["type"] for d in all_docs)
    fams = Counter(d["metadata"]["family"] for d in all_docs)

    print(f"Wrote KB docs: {KB} ({len(all_docs)} docs)")
    print("Types:", dict(types))
    print("Top families:", fams.most_common(10))


if __name__ == "__main__":
    main()
