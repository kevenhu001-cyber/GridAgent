from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static

from .agent import stream_task
from .cli import text_content, tool_summary


class GridApp(App):
    TITLE = "GridAgent"
    CSS = """
    Screen { layout: vertical; }
    #status { height: 2; padding: 0 2; color: $text-muted; }
    RichLog { height: 1fr; padding: 1 2; }
    Input { margin: 0 1 1 1; }
    """
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+l", "clear_chat", "New session")]

    def __init__(self, graph, budget: int):
        super().__init__()
        self.graph, self.budget = graph, budget
        self.history = []
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Offline research | ANDES | {self.budget} simulations per task", id="status")
        yield RichLog(markup=False, wrap=True, id="chat")
        yield Input(placeholder="Ask a research question or /help", id="prompt")
        yield Footer()

    def on_mount(self):
        self.query_one("#chat", RichLog).write(Text("GridAgent — offline power-system research."))
        self.query_one("#prompt", Input).focus()

    def action_clear_chat(self):
        if not self.busy:
            self.history.clear()
            self.query_one("#chat", RichLog).clear()

    def on_input_submitted(self, event: Input.Submitted):
        question = event.value.strip()
        if not question or self.busy:
            return
        event.input.value = ""
        chat = self.query_one("#chat", RichLog)
        if question == "/help":
            chat.write(Text("Enter a question. Ctrl+L starts a new session; Ctrl+Q quits."))
            return
        chat.write(Text("You: " + question, style="bold"))
        self.busy = True
        event.input.disabled = True
        self.query_one("#status", Static).update("Running research task...")
        self.run_worker(lambda: self._run_task(question), thread=True, exit_on_error=False)

    def _run_task(self, question):
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=question)]
        try:
            for event in stream_task(self.graph, question, self.history):
                for node, update in event.items():
                    for msg in update.get("messages", []):
                        messages.append(msg)
                        if node == "tools":
                            self.call_from_thread(self._write, Text(tool_summary(msg), style="dim"))
                        elif text_content(msg):
                            self.call_from_thread(self._write, Markdown(text_content(msg)))
            self.call_from_thread(self.history.extend, messages)
        except Exception as exc:
            self.call_from_thread(self._write, Text("Task failed: " + type(exc).__name__, style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _write(self, value):
        self.query_one("#chat", RichLog).write(value)

    def _finish(self):
        self.busy = False
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self.query_one("#status", Static).update(f"Ready | {self.budget} simulations per task")
