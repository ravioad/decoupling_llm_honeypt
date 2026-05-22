from __future__ import annotations

try:
    from honeypot.rag.rag_client import extract_rag_phrases
except ModuleNotFoundError:
    from rag.rag_client import extract_rag_phrases

from .types import ExecResult, RenderSpec

# Maps exec outcome to the canonical Linux error keyword for semantic validation.
_OUTCOME_KEYWORDS: dict[str, str] = {
    "missing_path": "No such file or directory",
    "permission_denied": "Permission denied",
    "is_a_directory": "Is a directory",
    "invalid_cmd": "command not found",
    "error": "",  # generic, no keyword enforced
}


def _semantic_error_constraints(
    family: str, outcome: str, target_path: str | None
) -> dict:
    return {
        "must_start_with_family": True,
        "must_contain_path": target_path is not None,
        "error_keyword": _OUTCOME_KEYWORDS.get(outcome, ""),
    }


def _fill(template: str, path: str | None) -> str:
    if path is None:
        return template
    return template.replace("<path>", path)


def _ensure_nl(s: str) -> str:
    return s if s.endswith("\n") else s + "\n"


def build_render_spec(exec_result: ExecResult, ragctx: object | None) -> RenderSpec:
    rag_error_phrase, rag_format_hint = extract_rag_phrases(ragctx)

    family = exec_result.family
    outcome = exec_result.outcome
    target_path = exec_result.target_path

    allow_stdout = True
    allow_stderr = True
    stdout = ""
    stderr = ""

    def _payload_plain(text: str) -> dict:
        return {"text": text}

    def _payload_error(msg: str) -> dict:
        return {
            "family": family,
            "outcome": outcome,
            "target_path": target_path,
            "message": msg,
        }


    if outcome == "success":
        if family == "id":
            meta = exec_result.meta or {}
            headers = meta.get("headers")
            rows = meta.get("rows")

            if isinstance(headers, list) and isinstance(rows, list) and rows:
                return RenderSpec(
                    schema_version="render_spec.v1",
                    family=family,
                    outcome=outcome,
                    target_path=target_path,
                    allow_stdout=True,
                    allow_stderr=False,
                    render_type="structured",
                    render_payload={
                        "headers": headers,
                        "rows": rows,
                        "notes": {"align": "space", "trailing_newline": True},
                    },
                    stdout=exec_result.stdout_ground_truth,
                    stderr="",
                    rag_error_phrase=rag_error_phrase,
                    rag_format_hint=rag_format_hint,
                )
        if family == "ls" and outcome == "success":
            # Only structured-render long format (-l) outputs.
            lines_raw = exec_result.stdout_ground_truth.strip("\n")
            if lines_raw:
                lines = lines_raw.split("\n")
            else:
                lines = []

            def _looks_like_ls_long(line: str) -> bool:
                s = line.strip()
                return (
                    len(s) >= 10
                    and (s[0] in {"-", "d"})
                    and (
                        s[1:10].count("-")
                        + s[1:10].count("r")
                        + s[1:10].count("w")
                        + s[1:10].count("x")
                        >= 9
                    )
                )

            if lines and all(_looks_like_ls_long(line) for line in lines):
                rows = []

                for line in lines:
                    parts = line.split()
                    if len(parts) < 6:
                        # If a line is malformed, fall back to plain_text behavior
                        rows = []
                        break

                    mode = parts[0]
                    links = parts[1]
                    owner = parts[2]
                    group = parts[3]
                    size = parts[4]
                    name = " ".join(parts[5:])

                    rows.append([mode, links, owner, group, size, name])

                if rows:
                    return RenderSpec(
                        schema_version="render_spec.v1",
                        family=family,
                        outcome=outcome,
                        target_path=target_path,
                        allow_stdout=True,
                        allow_stderr=False,
                        render_type="structured",
                        render_payload={
                            "kind": "table",
                            "rows": rows,
                            "notes": {"align": "space", "trailing_newline": True},
                        },
                        stdout=exec_result.stdout_ground_truth,
                        stderr="",
                        rag_error_phrase=rag_error_phrase,
                        rag_format_hint=rag_format_hint,
                    )
        stdout = exec_result.stdout_ground_truth
        stderr = exec_result.stderr_ground_truth
        allow_stderr = False

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=allow_stdout,
            allow_stderr=allow_stderr,
            render_type="plain_text",
            render_payload=_payload_plain(stdout),
            stdout=stdout,
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
        )


    if outcome == "invalid_cmd":
        allow_stdout = False
        stderr = exec_result.stderr_ground_truth or f"{family}: command not found\n"

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=allow_stdout,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )

    if family == "rm":
        allow_stdout = False

        if outcome == "missing_path":
            stderr = _ensure_nl(
                f"rm: cannot remove '{target_path}': No such file or directory"
            )
        elif outcome == "permission_denied":
            stderr = _ensure_nl(f"rm: cannot remove '{target_path}': Permission denied")
        elif outcome == "is_a_directory":
            stderr = _ensure_nl(f"rm: cannot remove '{target_path}': Is a directory")
        elif outcome == "error":
            stderr = _ensure_nl(exec_result.stderr_ground_truth or "rm: error")
        else:
            stderr = ""

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=False,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )

    if family == "mkdir":
        allow_stdout = False

        if outcome == "missing_path":
            stderr = _ensure_nl(
                f"mkdir: cannot create directory '{target_path}': No such file or directory"
            )
        elif outcome == "permission_denied":
            stderr = _ensure_nl(
                f"mkdir: cannot create directory '{target_path}': Permission denied"
            )
        elif outcome == "error":
            stderr = _ensure_nl(exec_result.stderr_ground_truth or "mkdir: error")
        else:
            stderr = ""

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=False,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )

    if family == "mv":
        allow_stdout = False

        if outcome == "missing_path":
            stderr = _ensure_nl(
                f"mv: cannot stat '{target_path}': No such file or directory"
            )
        elif outcome == "permission_denied":
            stderr = _ensure_nl(
                f"mv: cannot move to '{target_path}': Permission denied"
            )
        elif outcome == "error":
            stderr = _ensure_nl(exec_result.stderr_ground_truth or "mv: error")
        else:
            stderr = ""

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=False,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )

    if family == "cp":
        allow_stdout = False

        if outcome == "missing_path":
            stderr = _ensure_nl(
                f"cp: cannot stat '{target_path}': No such file or directory"
            )
        elif outcome == "permission_denied":
            stderr = _ensure_nl(
                f"cp: cannot create regular file '{target_path}': Permission denied"
            )
        elif outcome == "error":
            stderr = _ensure_nl(exec_result.stderr_ground_truth or "cp: error")
        else:
            stderr = ""

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=False,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )


    if family == "cd":
        allow_stdout = False

        if outcome == "missing_path":
            stderr = _ensure_nl(f"cd: {target_path}: No such file or directory")
        elif outcome == "permission_denied":
            stderr = _ensure_nl(f"cd: {target_path}: Permission denied")
        elif outcome == "error":
            stderr = _ensure_nl(f"cd: {target_path}: Not a directory")
        else:
            stderr = ""  # any other non-success case

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=allow_stdout,
            allow_stderr=True,
            render_type="error",
            render_payload=_payload_error(stderr),
            stdout="",
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
            semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
        )



    allow_stdout = False

    if outcome == "missing_path":
        phrase = (
            rag_error_phrase
            or f"{family}: cannot access '<path>': No such file or directory"
        )
        stderr = _ensure_nl(_fill(phrase, target_path))

    elif outcome == "permission_denied":
        phrase = (
            rag_error_phrase
            or f"{family}: '<path>': Permission denied"
        )
        stderr = _ensure_nl(_fill(phrase, target_path))

    elif outcome == "is_a_directory":
        phrase = rag_error_phrase or f"{family}: <path>: Is a directory"
        stderr = _ensure_nl(_fill(phrase, target_path))

    elif outcome == "error":
        if exec_result.stderr_ground_truth is not None:
            stderr = _ensure_nl(exec_result.stderr_ground_truth)
        else:
            phrase = rag_error_phrase or f"{family}: error"
            stderr = _ensure_nl(_fill(phrase, target_path))

    else:
        stdout = exec_result.stdout_ground_truth
        stderr = exec_result.stderr_ground_truth
        allow_stdout = True
        allow_stderr = True

        return RenderSpec(
            schema_version="render_spec.v1",
            family=family,
            outcome=outcome,
            target_path=target_path,
            allow_stdout=allow_stdout,
            allow_stderr=allow_stderr,
            render_type="plain_text",
            render_payload=_payload_plain(stdout),
            stdout=stdout,
            stderr=stderr,
            rag_error_phrase=rag_error_phrase,
            rag_format_hint=rag_format_hint,
        )

    # Default for non-success outcomes is error-type
    return RenderSpec(
        schema_version="render_spec.v1",
        family=family,
        outcome=outcome,
        target_path=target_path,
        allow_stdout=allow_stdout,
        allow_stderr=allow_stderr,
        render_type="error",
        render_payload=_payload_error(stderr),
        stdout=stdout,
        stderr=stderr,
        rag_error_phrase=rag_error_phrase,
        rag_format_hint=rag_format_hint,
        semantic_constraints=_semantic_error_constraints(family, outcome, target_path),
    )
