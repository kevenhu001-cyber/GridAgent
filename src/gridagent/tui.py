import shlex
from pathlib import Path
from typing import ClassVar

from langchain_core.messages import HumanMessage, ToolMessage
from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, RichLog, Static

from .cli import text_content, tool_summary
from .commands import workspace_command
from .store import recorded_task


class StudyBrowser(ModalScreen):
    """Keyboard-driven experiment picker; only reads local artifact metadata."""

    BINDINGS: ClassVar = [("escape", "dismiss_browser", "Close")]
    CSS = """
    StudyBrowser { align: center middle; background: $background 70%; }
    #study-dialog { width: 90%; max-width: 100; height: 70%; background: $surface; padding: 1 2; border: round $primary; }
    #study-heading { height: 2; text-style: bold; }
    #study-table { height: 1fr; }
    """

    def __init__(self, root):
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(id="study-dialog"):
            yield Static("Research studies  ·  Enter to open  ·  Esc to close", id="study-heading")
            yield DataTable(id="study-table", cursor_type="row")

    def on_mount(self):
        from .dsr import list_studies

        table = self.query_one(DataTable)
        table.add_columns("Study ID", "Status")
        for row in list_studies(self.root):
            table.add_row(row["id"], row["status"], key=row["id"])
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.dismiss(str(event.row_key.value))

    def action_dismiss_browser(self):
        self.dismiss(None)


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
    BINDINGS: ClassVar = [("ctrl+q", "quit", "Quit"), ("ctrl+l", "new_session", "New session"),
                          Binding("ctrl+e", "browse_studies", "Studies", priority=True)]

    def __init__(self, graph, budget, store, sid, dsr_runner=None, studies_root=None, dmq_runner=None, workspace=Path(".gridagent")):
        super().__init__()
        self.graph, self.budget, self.store, self.sid = graph, budget, store, sid
        self.busy = False
        self.dsr_runner = dsr_runner
        self.dmq_runner = dmq_runner
        self.studies_root = studies_root
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("GridAgent", id="brand")
            yield Static("Ready", id="status", markup=False)
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
            f"{'Offline workspace' if self.graph is None else 'Research agent'} · ANDES · {self.sid[:8]}")
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

    def action_browse_studies(self):
        if not self.busy and self.studies_root is not None:
            self.push_screen(StudyBrowser(self.studies_root), self._study_selected)

    def _study_selected(self, identifier):
        if identifier is not None:
            try:
                for line in workspace_command(self.workspace, "study", [identifier]):
                    self._write(Text(line))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self._write(Text(str(exc), style="red"))

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
            chat.write(Text("/new · new session | /sessions · list | /open ID · reopen | /dsr PATH · screen faults | /dmq · model review | /studies · list | /runs | /study ID | /wave ID CHANNEL | /study-wave ID PATH CHANNEL | /eigen | /sweep BUS DURATIONS | /resume-dsr ID | /optimize [BUDGET] | /paper-dmq PROFILE | /paper-dsr PROFILE | /paper-mitigate PROFILE | /paper-trials TASK COUNT [PROFILE] | /knowledge | /import-knowledge JSON | /models | /import-model PATH | /paper-rank | /paper-kpi CSV CLEARING_S | /paper-edit Kqp Kqi Kvp Kvi | Ctrl+E Studies | Ctrl+Q · quit"))
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
        if question == "/studies":
            from .dsr import list_studies
            rows = list_studies(self.studies_root) if self.studies_root else []
            if not rows:
                chat.write(Text("No saved studies.", style="dim"))
            for row in rows:
                chat.write(Text(f"{row['id']}  {row['status']}"))
            return
        if question.split()[0] in {"/runs", "/study", "/wave", "/study-wave", "/eigen", "/sweep", "/resume-dsr", "/optimize", "/paper-rank", "/paper-kpi", "/paper-edit", "/paper-dmq", "/paper-dsr", "/paper-mitigate", "/paper-trials", "/models", "/import-model", "/knowledge", "/import-knowledge"}:
            try:
                parts = shlex.split(question)
            except ValueError:
                chat.write(Text("Invalid command quoting.", style="red"))
                return
            self.busy = True
            event.input.disabled = True
            self._status("Research · working")
            self.run_worker(lambda: self._workspace_command(parts), thread=True, exit_on_error=False)
            return
        if question == "/dmq":
            if self.dmq_runner is None:
                chat.write(Text("DMQ unavailable.", style="dim"))
                return
            self.busy = True
            event.input.disabled = True
            self._status("DMQ · running")
            self.run_worker(self._run_dmq, thread=True, exit_on_error=False)
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
        if self.graph is None:
            chat.write(Text("Offline workspace. Configure a model to start agent tasks.", style="dim"))
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

    def _run_dmq(self):
        from .dmq import format_update
        try:
            for node, value in self.dmq_runner():
                self.call_from_thread(self._write, Text(format_update(node, value)))
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self.call_from_thread(self._write, Text("DMQ failed: " + type(exc).__name__, style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _workspace_command(self, parts):
        try:
            for line in workspace_command(self.workspace, parts[0][1:], parts[1:]):
                self.call_from_thread(self._write, Text(line))
        except (OSError, ValueError, TypeError) as exc:
            self.call_from_thread(self._write, Text(str(exc), style="red"))
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
