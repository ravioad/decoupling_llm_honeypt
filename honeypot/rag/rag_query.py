from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RagQuery:
    collection: str
    family: str | None
    outcome: str | None
    wanted_types: list[str]  # ["error_phrase"] or ["format_hint"]
    query_text: str
    k: int = 3
