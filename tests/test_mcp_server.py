"""Exercise real local MCP transport without credentials or host-code execution."""
import asyncio
import json
import sys

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from gridagent.scientific_workspace import set_enabled  # noqa: E402


def test_local_mcp_workspace_and_permissions(tmp_path):
    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gridagent.mcp_server", "--workspace", str(tmp_path)],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert {"list_project_files", "write_project_file", "execute_python",
                        "list_solver_backends", "read_native_table"} <= tools
                assert "run_native_program" not in tools
                denied = await session.call_tool("write_project_file",
                                                 {"path": "study.py", "text": "print(42)"})
                assert denied.isError
                denied = await session.call_tool("execute_python", {"entry": "study.py"})
                assert denied.isError
                set_enabled(tmp_path, True)
                saved = await session.call_tool("write_project_file",
                                                {"path": "study.py", "text": "print(42)"})
                assert not saved.isError
                result = await session.call_tool("read_project_file", {"path": "study.py"})
                assert not result.isError
                assert "print(42)" in json.dumps(result.model_dump())
                denied = await session.call_tool("write_project_file",
                                                 {"path": "../escape.py", "text": "bad"})
                assert denied.isError
                denied = await session.call_tool("write_project_file",
                                                 {"path": "study.py", "text": "replaced"})
                assert denied.isError
                assert not (tmp_path / "escape.py").exists()

    asyncio.run(scenario())
