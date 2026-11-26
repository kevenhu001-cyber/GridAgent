"""Shared user-facing message summaries, independent of solver imports."""
import json


def text_content(message):
    if isinstance(message.content, str):
        return message.content
    return "\n".join(block.get("text", "") for block in message.content
                     if isinstance(block, dict) and block.get("type") == "text")


def tool_summary(message):
    try:
        data = json.loads(message.content)
    except (ValueError, TypeError):
        return f"{message.name}: result received"
    if not isinstance(data, dict):
        return f"{message.name}: result received"
    status = data.get("status", "ok")
    result = f"{message.name}: {status}"
    if message.name == "research_plan" and status == "ok":
        return "Research plan: " + data["objective"] + "\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(data["steps"])) + "\nVerify: " + data["verification"]
    quality = data.get("quality")
    if isinstance(quality, dict):
        result += f" | quality {quality.get('passed_count', 0)}/{quality.get('test_count', 0)} · {'passed' if quality.get('passed') else 'not passed'}"
    if data.get("run_id"):
        result += f" | run {data['run_id']}"
    if status != "ok":
        result += f" | {data.get('reason', 'unknown error')}"
    return result
