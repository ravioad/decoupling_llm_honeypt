from __future__ import annotations
from .types import RenderSpec


def render_fallback(spec: RenderSpec) -> tuple[str, str]:
    stdout = spec.stdout if spec.allow_stdout else ""
    stderr = spec.stderr if spec.allow_stderr else ""
    return stdout, stderr
