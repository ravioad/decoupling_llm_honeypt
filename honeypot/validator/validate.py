from __future__ import annotations

import logging

from core.types import RenderSpec

log = logging.getLogger(__name__)


def validate_output(
    spec: RenderSpec, stdout: str, stderr: str
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    def _norm_trailing_newline(s: str) -> str:
        if not s:
            return ""
        return s if s.endswith("\n") else s + "\n"

    if not spec.allow_stdout and stdout:
        errors.append("stdout_not_allowed")
    if not spec.allow_stderr and stderr:
        errors.append("stderr_not_allowed")

    payload = spec.render_payload or {}
    rt = getattr(spec, "render_type", None)

    if rt == "plain_text":
        expected_stdout = payload.get("text", "")
        if _norm_trailing_newline(stdout) != _norm_trailing_newline(expected_stdout):
            errors.append("plain_text_stdout_mismatch")
        if stderr != "":
            errors.append("plain_text_stderr_must_be_empty")

    elif rt == "error":
        # stdout must always be empty for errors
        if stdout != "":
            errors.append("error_stdout_must_be_empty")

        # stderr must be non-empty
        if not stderr.strip():
            errors.append("error_stderr_empty")
        else:
            constraints = spec.semantic_constraints or {}
            family = spec.family or ""
            target_path = spec.target_path or ""

            if constraints.get("must_start_with_family"):
                prefix = f"{family}:"
                if not stderr.lstrip().startswith(prefix):
                    errors.append(f"error_missing_family_prefix:{prefix}")

            if constraints.get("must_contain_path") and target_path:
                if target_path not in stderr:
                    errors.append(f"error_missing_path:{target_path}")

            keyword = constraints.get("error_keyword", "")
            if keyword and keyword.lower() not in stderr.lower():
                errors.append(f"error_missing_keyword:{keyword}")

    elif rt == "structured":
        rows = payload.get("rows") or []

        if stderr != "":
            errors.append("structured_stderr_must_be_empty")

        if spec.allow_stdout and stdout == "":
            errors.append("structured_missing_stdout")

        def _norm_ws(s: str) -> str:
            return " ".join((s or "").split())

        out_lines = [_norm_ws(line) for line in (stdout or "").splitlines()]
        out_lines = [ln for ln in out_lines if ln != ""]

        expected_lines: list[str] = []
        for row in rows:
            row_line = _norm_ws(" ".join(str(c) for c in row if c is not None))
            if row_line:
                expected_lines.append(row_line)

        if len(out_lines) < len(expected_lines):
            errors.append("structured_too_few_lines")
        else:
            mismatches = []
            for i, exp in enumerate(expected_lines):
                got = out_lines[i] if i < len(out_lines) else ""
                if got != exp:
                    mismatches.append((i, exp, got))
                    if len(mismatches) >= 3:
                        break

            if mismatches:
                parts = [f"{i}:{exp}!= {got}" for (i, exp, got) in mismatches]
                errors.append("structured_line_mismatch:" + " | ".join(parts))

            extra = out_lines[len(expected_lines):]
            if extra:
                errors.append("structured_extra_lines:" + " | ".join(extra[:3]))

    else:
        if stdout != (spec.stdout or ""):
            errors.append("stdout_mismatch")
        if stderr != (spec.stderr or ""):
            errors.append("stderr_mismatch")

    return (len(errors) == 0), errors
