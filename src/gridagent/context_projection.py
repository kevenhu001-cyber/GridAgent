"""Bounded model-facing projections; full public messages remain in the audit trail."""
import json

from langchain_core.messages import ToolMessage

CONTEXT_TARGET = 96000
RECENT_TOOL_RESULTS = 4
PREVIEW_CHARS = 1000
EVIDENCE_FIELDS = ("status", "reason", "error_code", "next_action", "run_id", "study_id", "task_id",
                   "path", "sha256", "exit_code", "verification", "next_offset", "plugin_ids")


def _size(message):
    return len(json.dumps(message.content, ensure_ascii=False, default=str)) + len(
        json.dumps(getattr(message, "tool_calls", []), ensure_ascii=False, default=str))


def _preview(message):
    raw = message.content
    if not isinstance(raw, str):
        return message
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {}
    fields = {}
    if isinstance(data, dict):
        for key in EVIDENCE_FIELDS:
            value = data.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None and key in data:
                fields[key] = value[:300] if isinstance(value, str) else value
        artifacts = data.get("artifacts")
        if isinstance(artifacts, list):
            fields["artifact_paths"] = [item["path"][:160] for item in artifacts[:8]
                                        if isinstance(item, dict) and isinstance(item.get("path"), str)]
    content = json.dumps({"context_projection": True, "original_chars": len(raw),
                          "tool_call_id": message.tool_call_id, "evidence_fields": fields,
                          "excerpt": raw[:PREVIEW_CHARS],
                          "note": "Partial historical result, not a new execution. Use session evidence or run artifacts for details."},
                         ensure_ascii=False, allow_nan=False)
    if len(content) >= len(raw):
        return message
    return message.model_copy(update={"content": content})


def project_context(messages, target=CONTEXT_TARGET):
    """Compact old tool payloads only, preserving roles, call IDs, arguments and user requests.

    A soft character target, not a tokenizer or provider context guarantee. Recent results and
    non-tool messages are retained verbatim. If insufficient, report that limit rather than
    silently dropping user requirements or modifying historical tool arguments.
    """
    if target < 1:
        raise ValueError("Context target must be positive")
    projected = list(messages)
    original = sum(_size(message) for message in messages)
    remaining = original
    indices = [index for index, message in enumerate(messages) if isinstance(message, ToolMessage)]
    compacted = 0
    for index in indices[:-RECENT_TOOL_RESULTS]:
        if remaining <= target:
            break
        old = projected[index]
        new = _preview(old)
        if new is old:
            continue
        remaining += _size(new) - _size(old)
        projected[index] = new
        compacted += 1
    return projected, {"original_chars": original, "projected_chars": remaining,
                       "compacted_tool_results": compacted, "target_chars": target,
                       "target_exceeded": remaining > target}
