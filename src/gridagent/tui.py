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
from textual.widgets import Button, DataTable, Footer, Input, RichLog, Static

from .cli import text_content, tool_summary
from .commands import workspace_command
from .store import recorded_task

WORKSPACE_COMMANDS = {
    "/scientific-execution", "/scientific-cancel",
    "/runs", "/study", "/wave", "/study-wave", "/eigen", "/sweep", "/resume-dsr", "/optimize", "/andes-batch",
    "/paper-rank", "/paper-kpi", "/paper-edit", "/paper-dmq", "/paper-dsr", "/paper-mitigate", "/paper-trials",
    "/models", "/import-model", "/knowledge", "/import-knowledge", "/backends", "/native-program", "/native-table",
    "/dispatch-ir", "/dispatch-resume", "/dispatch-status", "/dispatch-cancel",
    "/optimize-ir", "/optimize-resume", "/math-program", "/math-resume", "/ac-check", "/ac-check-resume", "/diagnose-study",
    "/diagnostic-experiment", "/diagnostic-experiment-resume",
    "/ac-diagnostic-experiment", "/ac-diagnostic-experiment-resume",
    "/adaptive-ac-experiment", "/adaptive-ac-experiment-resume",
    "/ac-evidence-repair", "/ac-evidence-repair-resume", "/remember-ac-repair", "/search-ac-experience",
    "/drafts", "/model-repair", "/modeling-benchmark", "/experience", "/plugins", "/plugin-install",
    "/plugin-remove", "/plugin-check", "/plugin-update", "/plugin-rollback", "/register-ngspice", "/ngspice-rc",
}


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


class ModelSettingsScreen(ModalScreen):
    BINDINGS: ClassVar = [("escape", "close_settings", "Close")]
    CSS = """
    ModelSettingsScreen { align: center middle; background: $background 70%; }
    #model-form { width: 76; max-width: 98%; height: auto; padding: 1 2; border: round $primary; }
    #model-actions { height: 3; }
    #connection-status { height: auto; min-height: 1; }
    """

    def __init__(self, settings, session_key):
        super().__init__()
        self.settings = settings
        self.session_key = session_key

    def compose(self) -> ComposeResult:
        with Vertical(id="model-form"):
            yield Static("Model settings · OpenAI-compatible endpoint")
            yield Static("Model name")
            yield Input(value=self.settings.model, placeholder="Provider model ID", id="model-name")
            yield Static("Base URL (optional)")
            yield Input(value=self.settings.base_url, placeholder="https://provider.example/v1", id="model-url")
            yield Static("API key (this session only)")
            yield Input(placeholder="Enter a key or use the environment", password=True, id="model-key")
            with Horizontal(id="model-actions"):
                yield Button("Save", id="model-save", variant="primary")
                yield Button("Test connection", id="model-test")
                yield Button("Close", id="model-close")
            yield Static("", id="connection-status", markup=False)

    def on_button_pressed(self, event: Button.Pressed):
        from .model_settings import ModelSettings

        if event.button.id == "model-close":
            self.dismiss(None)
            return
        status = self.query_one("#connection-status", Static)
        try:
            settings = ModelSettings(model=self.query_one("#model-name", Input).value,
                                     base_url=self.query_one("#model-url", Input).value)
            if not settings.model:
                raise ValueError("Enter a model name")
        except ValueError:
            status.update("Enter a model name and a valid HTTP(S) base URL.")
            return
        existing_key = self.session_key if settings.base_url == self.settings.base_url else None
        key = self.query_one("#model-key", Input).value.strip() or existing_key
        if event.button.id == "model-save":
            self.dismiss((settings, key))
        else:
            status.update("Testing connection…")
            event.button.disabled = True
            self.run_worker(lambda: self._test_connection(settings, key), thread=True, exit_on_error=False)

    def _test_connection(self, settings, key):
        from .model_settings import check_connection

        try:
            message = check_connection(settings, key)
        except Exception as exc:  # noqa: BLE001 - avoid rendering provider errors or credentials
            message = f"Connection failed ({type(exc).__name__}). Check endpoint, model and session key."
        self.app.call_from_thread(self._show_result, message)

    def _show_result(self, message):
        if self.is_mounted:
            self.query_one("#connection-status", Static).update(message)
            self.query_one("#model-test", Button).disabled = False

    def action_close_settings(self):
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
                          Binding("ctrl+e", "browse_studies", "Studies", priority=True),
                          Binding("ctrl+p", "model_settings", "Model settings", priority=True),
                          Binding("ctrl+x", "cancel_research", "Cancel task", priority=True)]

    def __init__(self, graph, budget, store, sid, dsr_runner=None, studies_root=None, dmq_runner=None, workspace=Path(".gridagent")):
        super().__init__()
        self.graph, self.budget, self.store, self.sid = graph, budget, store, sid
        self.busy = False
        self.dsr_runner = dsr_runner
        self.dmq_runner = dmq_runner
        self.studies_root = studies_root
        self.workspace = workspace
        self.active_research = None
        self.session_key = None
        self.model_settings = None

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

    def action_model_settings(self):
        from .model_settings import active_settings

        if not self.busy:
            try:
                settings = self.model_settings or active_settings(self.workspace)
            except ValueError:
                self._write(Text("The saved model settings are invalid.", style="red"))
                return
            self.push_screen(ModelSettingsScreen(settings, self.session_key), self._save_model_settings)

    def _save_model_settings(self, result):
        if result is None:
            return
        from .agent import build_agent
        from .dmq import study_updates as dmq_updates
        from .dsr import study_updates as dsr_updates
        from .model_settings import save_settings
        from .simulator import AndesSimulator

        settings, self.session_key = result
        try:
            self.model_settings = save_settings(self.workspace, settings.model, settings.base_url)
        except (OSError, ValueError):
            self._write(Text("Unable to save workspace model settings.", style="red"))
            return
        try:
            model = self._configured_model()
        except ValueError:
            self.graph = None
            self.dsr_runner = self.dmq_runner = None
            self._write(Text("Model saved. Add a session API key to run agent tasks."))
            return
        simulator = AndesSimulator(self.workspace / "runs")
        self.graph = build_agent(model, simulator, budget=self.budget, workspace=self.workspace)
        self.dsr_runner = lambda path: dsr_updates(path, self.workspace, model, simulator)
        self.dmq_runner = lambda: dmq_updates(self.workspace, model)
        self.query_one("#session", Static).update(f"{settings.model} · {self.sid[:8]}")
        self._write(Text(f"Model saved · {settings.model} · API key kept for this session"))

    def _configured_model(self, *, settings=None):
        from .agent import model_from_env

        return model_from_env(self.workspace, settings=settings or self.model_settings, api_key=self.session_key)

    def on_input_submitted(self, event: Input.Submitted):
        question = event.value.strip()
        if not question or self.busy:
            return
        event.input.value = ""
        chat = self.query_one("#chat", RichLog)
        if question == "/help":
            chat.write(Text("/model · configure the workspace model and test the connection"))
            chat.write(Text("/research QUESTION · /research-multi QUESTION · /research-manifest PATH · "
                            "/research-ir PATH · /research-tasks · /research-status ID · /research-resume ID · "
                            "/research-cancel ID · "
                            "/research-approve ID · /research-clarify ID ANSWER · /research-report ID PATH"))
            chat.write(Text("/dispatch-ir PATH · /dispatch-resume ID · /dispatch-status ID · /dispatch-cancel ID"))
            chat.write(Text("/optimize-ir PATH · /optimize-resume ID · /math-program PATH · /math-resume ID"))
            chat.write(Text("/ac-check PATH · /ac-check-resume ID · /diagnose-study ID"))
            chat.write(Text("/diagnostic-experiment PATH · /diagnostic-experiment-resume ID"))
            chat.write(Text("/ac-diagnostic-experiment PATH · /ac-diagnostic-experiment-resume ID"))
            chat.write(Text("/adaptive-ac-experiment PATH · /adaptive-ac-experiment-resume ID"))
            chat.write(Text("/ac-evidence-repair PATH · /ac-evidence-repair-resume ID"))
            chat.write(Text("/remember-ac-repair ID · /search-ac-experience ID"))
            chat.write(Text("/scientific-execution enable|disable|status · /scientific-cancel RUN_ID"))
            chat.write(Text("/research-python MANIFEST · /research-sandbox enable|disable|status · "
                            "/research-benchmark [TASK [MODE]] · /andes-batch PATH"))
            chat.write(Text("/new · new session | /sessions · list | /open ID · reopen | /dsr PATH · screen faults | /dmq · model review | /studies · list | /runs | /study ID | /wave ID CHANNEL | /study-wave ID PATH CHANNEL | /eigen | /sweep BUS DURATIONS | /resume-dsr ID | /optimize [BUDGET] | /paper-dmq PROFILE | /paper-dsr PROFILE | /paper-mitigate PROFILE | /paper-trials TASK COUNT [PROFILE] | /modeling-benchmark TASK | /model-repair MANIFEST | /experience | /plugins | /plugin-install ID | /plugin-remove ID | /drafts | /backends | /native-program JSON | /native-table RUN TABLE | /knowledge | /import-knowledge JSON | /models | /import-model PATH | /paper-rank | /paper-kpi CSV CLEARING_S | /paper-edit Kqp Kqi Kvp Kvi | Ctrl+E Studies | Ctrl+Q · quit"))
            return
        if question == "/model":
            self.action_model_settings()
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
        command = question.split()[0]
        if command == "/research" or command.startswith("/research-"):
            try:
                if command in {"/research", "/research-multi"}:
                    parts = question.split(maxsplit=1)
                else:
                    parts = shlex.split(question)
            except ValueError:
                chat.write(Text("Invalid command quoting.", style="red"))
                return
            self.busy = True
            event.input.disabled = True
            self.run_worker(lambda: self._research_command(parts), thread=True, exit_on_error=False)
            return
        if command in WORKSPACE_COMMANDS:
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
            from .agent import build_agent
            from .simulator import AndesSimulator

            graph = build_agent(self._configured_model(), AndesSimulator(self.workspace / "runs"),
                                budget=self.budget, workspace=self.workspace)
            for event in recorded_task(graph, self.store, self.sid, question):
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
            for line in workspace_command(self.workspace, parts[0][1:], parts[1:], model_factory=self._configured_model):
                self.call_from_thread(self._write, Text(line))
        except (OSError, ValueError, TypeError) as exc:
            self.call_from_thread(self._write, Text(str(exc), style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _research_command(self, parts):
        from .research import task_command

        try:
            for row in task_command(self.workspace, parts[0][1:], parts[1:], model_factory=self._configured_model):
                self.call_from_thread(self._show_research, row)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else type(exc).__name__
            self.call_from_thread(self._write, Text(message, style="red"))
        finally:
            self.call_from_thread(self._finish)

    def _show_research(self, row):
        from .research import TERMINAL, format_status

        if isinstance(row, dict):
            initial = self.active_research != row["id"]
            self.active_research = None if row["stage"] in TERMINAL else row["id"]
            self._status(f"Research · {row['stage']} · {row['runs_used']} simulations")
            if not initial and row["stage"] not in TERMINAL | {"awaiting_input", "awaiting_approval"}:
                return
            row = format_status(row)
        self._write(Text(row))

    def action_cancel_research(self):
        from .research import ResearchTasks

        if self.active_research is not None:
            ResearchTasks(self.workspace).cancel(self.active_research)
            self._status("Cancellation requested")

    def _status(self, text):
        self.query_one("#status", Static).update(text)

    def _write(self, value):
        self.query_one("#chat", RichLog).write(value)

    def _finish(self):
        self.busy = False
        self.active_research = None
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._status("Ready")
