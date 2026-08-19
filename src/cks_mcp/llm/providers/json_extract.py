"""JSON extraction from LLM output, shared by every provider caller."""

from __future__ import annotations


def extract_json(raw: str) -> str:
    """
    Strip any accidental markdown fences the LLM may have emitted and
    return the first *balanced* JSON object found in *raw*, starting
    from the first ``{``.

    Brace-matching always runs -- even when ``raw`` already starts
    with ``{`` -- so that truncated output (e.g. cut off by
    ``max_tokens``) is reported as "unbalanced braces" instead of
    being passed through unchecked and failing later with a more
    confusing parse error, and so that trailing commentary after the
    JSON object (e.g. "Hope this helps!") is trimmed off rather than
    returned as part of the "extracted" JSON.
    """
    stripped = raw.strip()

    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM output.")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]

    raise ValueError("Unbalanced braces in LLM output -- could not extract JSON.")
