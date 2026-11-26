"""Headless Textual smoke test for the offline research workspace."""
import asyncio

from textual.widgets import Input, RichLog

from gridagent.store import ResearchStore
from gridagent.tui import GridApp


def test_offline_workspace_mount_and_commands(tmp_path):
    store = ResearchStore(tmp_path / "research.sqlite3")
    sid = store.create_session()

    async def exercise():
        app = GridApp(None, 3, store, sid, studies_root=tmp_path / "studies", workspace=tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/sessions"
            await pilot.press("enter")
            await pilot.pause()
            assert len(app.query_one("#chat", RichLog).lines) > 0
            prompt.value = "/new"
            await pilot.press("enter")
            await pilot.pause()
            assert app.sid != sid
            assert len(store.sessions()) == 2
            prompt.value = "Research task"
            await pilot.press("enter")
            await pilot.pause()
            assert not app.busy
            assert not prompt.disabled

    asyncio.run(exercise())
