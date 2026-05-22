from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any

Outcome = Literal[
    "success",
    "missing_path",
    "permission_denied",
    "is_a_directory",
    "error",
    "invalid_cmd",
]


@dataclass(frozen=True)
class ExecResult:
    schema_version: str
    raw: str
    family: str
    outcome: Outcome
    exit_code: int
    stdout_ground_truth: str
    stderr_ground_truth: Optional[str] = None
    target_path: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

RenderType = Literal["plain_text", "structured", "error"]


@dataclass(frozen=True)
class RenderSpec:
    schema_version: str
    family: str
    outcome: Outcome
    target_path: Optional[str]

    allow_stdout: bool
    allow_stderr: bool

    render_type: RenderType
    render_payload: Optional[Dict[str, Any]] = None

    stdout: str = ""
    stderr: str = ""

    # Optional RAG context (non-authoritative)
    rag_error_phrase: Optional[str] = None
    rag_format_hint: Optional[str] = None

    # Semantic validation constraints for render_type="error"
    # Keys: must_start_with_family (bool), must_contain_path (bool), error_keyword (str)
    semantic_constraints: Optional[Dict[str, Any]] = None
