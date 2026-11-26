from typing import ClassVar

from langchain_core.messages import HumanMessage, ToolMessage
from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from .cli import text_content, tool_summary
from .store import recorded_task


class GridApp(App):
    TITLE = "GridAgent"
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #top { height: 3; padding: 1 2; background: $surface; }
    #brand { width: 1fr; text-style: bold; color: $text; }
    #status { width: auto; color: $text-muted; }
    #workspace { height: 1fr; padding: 0 2; }
    #session { height: 1; color: $text-muted; }
    RichLog { height: 1fr; padding: 1 0; background: $surface; border: none; }
    Input { margin: 0 0 1 0; border: round $primary; background: $surface; }
    Footer { background: $surface; }
    """
    BINDINGS: ClassVar = [("ctrl+q", "quit", "Quit"), ("ctrl+l", "new_session", "New session")]

    def __init__(self, graph, budget, store, sid, dsr_runner=None):
        super().__init__()
        self.graph, self.budget, self.store, self.sid = graph, budget, store, sid
        self.busy = False
        self.dsr_runner = dsr_runner

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("GridAgent", id="brand")
            yield Static("Ready", id="status")
        with Vertical(id="workspace"):
            yield Static("", id="session", markup=False)
            yield RichLog(markup=False, wrap=True, id="chat")
            yield Input(placeholder="Ask an engineering question…  /help", id="prompt")
        yield Footer()

    def on_mount(self):
        self._load_session()
        self.query_one("#prompt", Input).focus()

    def _load_session(self):
        chat = self.query_one("#chat", RichLog)
        chat.clear()
        self.query_one("#session", Static).update(
            f"Offline research · ANDES · {self.budget} simulations/task · {self.sid[:8]}")
        history = self.store.history(self.sid)
        if not history:
            chat.write(Text("Start a power-system study. Try asking for a baseline power flow.", style="dim"))
        for msg in history:
            if isinstance(msg, HumanMessage):
                chat.write(Text("You  " + text_content(msg), style="bold"))
            elif isinstance(msg, ToolMessage):
                chat.write(Text("  " + tool_summary(msg), style="dim"))
            elif text_content(msg):
                chat.write(Markdown(text_content(msg)))
        for task in self.store.tasks(self.sid):
            if task["status"] != "completed":
                chat.write(Text(f"Previous task {task['id'][:8]}: {task['status']} (audit retained)", style="dim"))

    def action_new_session(self):
        if not self.busy:
            self.sid = self.store.create_session()
            self._load_session()

    def on_input_submitted(self, event: Input.Submitted):
        question = event.value.strip()
        if not question or self.busy:
            return
        event.input.value = ""
        chat = self.query_one("#chat", RichLog)
        if question == "/help":
            chat.write(Text("/new · new session | /sessions · list | /open ID · reopen | /dsr PATH · screen faults | Ctrl+Q · quit"))
            return
        if question == "/new":
            self.action_new_session()
            return
        if question == "/sessions":
            for row in self.store.sessions():
                chat.write(Text(f"{row['id']}  {row['title']}  ({row['tasks']} tasks)"))
            return
        if question.startswith("/open "):
            try:
                self.sid = self.store.require_session(question.split(maxsplit=1)[1])
            except ValueError:
                chat.write(Text("Session not found.", style="red"))
                return
            self._load_session()
            return
        if question.startswith("/dsr "):
            if self.dsr_runner is None:
                chat.write(Text("DSR unavailable.", style="dim"))
                return
            self.busy = True
            event.input.disabled = True
            self._status("DSR · running")
            path = question.split(maxsplit=1)[1]
            self.run_worker(lambda: self._run_dsr(path), thread=True, exit_on_error=False)
            return
        chat.write(Text("You  " + question, style="bold"))
        self.busy = True
        event.input.disabled = True
        self.query_one("#status", Static).update("Working")
        self.run_worker(lambda: self._run_task(question), thread=True, exit_on_error=False)

    def _run_task(self, question):
        try:
            for event in recorded_task(self.graph, self.store, self.sid, question):
                for node, update in event.items():
                    if "used" in update:
                        self.call_from_thread(self._status, f"Working · {update['used']}/{self.budget} runs")
                    for msg in update.get("messages", []):
                        if node == "tools":
                            self.call_from_thread(self._write, Text("  " + tool_summary(msg), style="dim"))
                        elif text_content(msg):
                            self.call_from_thread(self._write, Markdown(text_content(msg)))
        except Exception as exc:  # noqa: BLE001 - client boundary, task already recorded
            self.call_from_thread(self._write, Text("Task failed: " + type(exc).__name__, style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _run_dsr(self, path):
        from .dsr import format_update
        try:
            for node, value in self.dsr_runner(path):
                self.call_from_thread(self._write, Text(format_update(node, value)))
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self.call_from_thread(self._write, Text("DSR failed: " + type(exc).__name__, style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _status(self, text):
        self.query_one("#status", Static).update(text)

    def _write(self, value):
        self.query_one("#chat", RichLog).write(value)

    def _finish(self):
        self.busy = False
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._status("Ready")
