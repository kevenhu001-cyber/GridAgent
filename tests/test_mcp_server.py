"""Exercise the real local MCP stdio transport without credentials or host-code execution.

The MCP Python SDK client deadlocks on Windows runner pipe transports
(modelcontextprotocol/python-sdk stdio/asyncio issues). This test drives the
stdio protocol directly with stdlib pipes and bounded waits so the Windows job
still verifies the server transport instead of hanging until the job timeout.
"""
import json
import queue
import subprocess
import sys
import threading

import pytest

pytest.importorskip("mcp")
from mcp.types import LATEST_PROTOCOL_VERSION

from gridagent.scientific_workspace import set_enabled


class StdioServer:
    """Minimal MCP JSON-RPC client over a real child-process stdio transport."""

    def __init__(self, workspace):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "gridagent.mcp_server", "--workspace", str(workspace)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        self.messages = queue.Queue()
        self.stderr = []
        self.next_id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.process.stdout:
            self.messages.put(line)
        self.messages.put(None)

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr.append(line.decode("utf-8", "replace"))

    def _send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=30):
        self.next_id += 1
        identifier = self.next_id
        self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}})
        while True:
            try:
                line = self.messages.get(timeout=timeout)
            except queue.Empty:
                raise AssertionError(
                    f"MCP {method} timed out; stderr: {''.join(self.stderr)[-2000:]}") from None
            if line is None:
                raise AssertionError(
                    f"MCP server exited during {method}; stderr: {''.join(self.stderr)[-2000:]}")
            message = json.loads(line)
            if message.get("id") == identifier:
                return message

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def call_tool(self, name, arguments):
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=15)


def test_local_mcp_workspace_and_permissions(tmp_path):
    server = StdioServer(tmp_path)
    try:
        initialized = server.request("initialize", {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "gridagent-test", "version": "1"},
        })
        assert "result" in initialized, initialized
        server.notify("notifications/initialized")

        listed = server.request("tools/list")
        tools = {tool["name"] for tool in listed["result"]["tools"]}
        assert {"list_project_files", "write_project_file", "execute_python",
                "list_solver_backends", "read_native_table"} <= tools
        assert "run_native_program" not in tools

        denied = server.call_tool("write_project_file", {"path": "study.py", "text": "print(42)"})
        assert denied["result"]["isError"]
        denied = server.call_tool("execute_python", {"entry": "study.py"})
        assert denied["result"]["isError"]

        set_enabled(tmp_path, True)
        saved = server.call_tool("write_project_file", {"path": "study.py", "text": "print(42)"})
        assert not saved["result"]["isError"], saved
        result = server.call_tool("read_project_file", {"path": "study.py"})
        assert not result["result"]["isError"]
        assert "print(42)" in json.dumps(result["result"])

        denied = server.call_tool("write_project_file", {"path": "../escape.py", "text": "bad"})
        assert denied["result"]["isError"]
        denied = server.call_tool("write_project_file", {"path": "study.py", "text": "replaced"})
        assert denied["result"]["isError"]
        assert not (tmp_path / "escape.py").exists()
    finally:
        server.close()
