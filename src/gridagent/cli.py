import argparse
import json

from rich.console import Console
from rich.markdown import Markdown

from .agent import build_agent, model_from_env, stream_task
from .simulator import AndesSimulator


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
    status = data.get("status", "ok")
    result = f"{message.name}: {status}"
    if data.get("run_id"):
        result += f" | run {data['run_id']}"
    if status != "ok":
        result += f" | {data.get('reason', 'unknown error')}"
    return result


def main():
    parser = argparse.ArgumentParser(description="GridAgent offline research assistant")
    parser.add_argument("--ask", help="Run one research task without TUI")
    parser.add_argument("--budget", type=int, default=3, choices=range(0, 31), metavar="0..30")
    args = parser.parse_args()
    try:
        graph = build_agent(model_from_env(), AndesSimulator(), budget=args.budget)
    except ValueError as exc:
        parser.error(str(exc))
    if args.ask:
        console = Console()
        for event in stream_task(graph, args.ask):
            for node, update in event.items():
                for message in update.get("messages", []):
                    if node == "tools":
                        console.print(tool_summary(message), markup=False)
                    elif text_content(message):
                        console.print(Markdown(text_content(message)))
        return
    from .tui import GridApp
    GridApp(graph, args.budget).run()
