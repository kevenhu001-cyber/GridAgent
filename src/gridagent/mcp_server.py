"""GridAgent tools for an external LLM harness via local MCP stdio.

No second LLM loop, HTTP listener, host shell, or automatic permission grants.
The host must launch this process with an explicitly selected workspace.
"""
import argparse
from pathlib import Path
from typing import Annotated

from pydantic import Field

from . import scientific_workspace as workspace


def create_server(root: Path, *, allow_native_solvers: bool = False):
    from mcp.server.fastmcp import FastMCP

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Select an existing GridAgent workspace directory")
    server = FastMCP(
        "GridAgent",
        instructions="Use engineering tools to formulate and test models. "
        "The external LLM owns decisions; tool output is evidence, not proof of correctness. "
        "Use the scoped Python sandbox, never an unrestricted host terminal for generated scientific code.",
    )

    @server.tool()
    def scientific_environment() -> dict:
        """Inspect the existing scientific execution grant and sandbox availability."""
        from .scientific_runtime import status

        return status(root)

    @server.tool()
    def list_project_files() -> dict:
        """List authorized scientific project files."""
        return workspace.list_project(root)

    @server.tool()
    def read_project_file(path: str, offset: int = 0,
                          limit: Annotated[int, Field(ge=1, le=24000)] = 12000) -> dict:
        """Read UTF-8 source with its complete SHA-256."""
        return workspace.read_project(root, path, offset, limit)

    @server.tool()
    def write_project_file(path: str, text: Annotated[str, Field(max_length=1048576)],
                           expected_sha256: str | None = None) -> dict:
        """Create or hash-guardedly replace a file in the authorized project."""
        return workspace.write_project(root, path, text, expected_sha256)

    @server.tool()
    def execute_python(entry: str, arguments: list[str] | None = None,
                       plugin_ids: Annotated[list[str] | None, Field(max_length=4)] = None) -> dict:
        """Execute authorized project Python in the existing sandbox, never on the host.
        Unsupported platforms or disabled grants fail closed; no dependency or network grants.
        """
        # Check authorization before importing the sandbox runtime; a denied
        # call must not pay the platform-specific import cost.
        workspace.require_grant(root)
        from .scientific_runtime import execute

        return execute(root, entry, None, arguments, plugin_ids=plugin_ids)

    @server.tool()
    def list_scientific_runs(limit: Annotated[int, Field(ge=1, le=50)] = 20) -> dict:
        """List persistent scientific sandbox runs."""
        workspace.require_grant(root)
        return workspace.list_scientific_runs(root, limit)

    @server.tool()
    def read_scientific_artifact(run_id: str, path: str, offset: int = 0,
                                 limit: Annotated[int, Field(ge=1, le=12000)] = 12000) -> dict:
        """Read a committed, hash-checked scientific artifact; output may be unverified."""
        workspace.require_grant(root)
        return workspace.read_artifact(root, run_id, path, offset, limit)

    @server.tool()
    def list_solver_backends() -> list[dict]:
        """Discover installed numerical libraries and their documented capabilities."""
        from .native_backends import available_backends

        return available_backends(root)

    @server.tool()
    def list_native_runs(offset: Annotated[int, Field(ge=0)] = 0,
                         limit: Annotated[int, Field(ge=1, le=50)] = 20) -> dict:
        """List existing native solver runs with bounded pagination."""
        from .workspace import list_runs

        rows = list_runs(root)
        return {"runs": rows[offset:offset + limit], "total": len(rows)}

    @server.tool()
    def read_native_table(run_id: str, table: str,
                          offset: Annotated[int, Field(ge=0, le=100000)] = 0,
                          limit: Annotated[int, Field(ge=1, le=50)] = 20) -> dict:
        """Read an existing backend-allowlisted solver output table."""
        from .native_results import read_table

        return read_table(root, run_id, table, offset, limit)

    @server.tool()
    def native_program_schema() -> dict:
        """Get the exact validated schema for optional typed pandapower/PyPSA programs."""
        from .native_backends import ADAPTER

        return ADAPTER.json_schema()

    if allow_native_solvers:
        @server.tool()
        def run_native_program(program: dict) -> dict:
            """Run a typed numerical program, persist inputs/results and report independent checks.
            This is an optional convenience, not the general-purpose scientific language.
            """
            import json

            from .native_backends import ADAPTER, run_program

            workspace.require_grant(root)
            if len(json.dumps(program, allow_nan=False).encode()) > 1024 * 1024:
                raise ValueError("Program exceeds 1 MiB")
            return run_program(root, ADAPTER.validate_python(program), timeout_s=120)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--allow-native-solvers", action="store_true",
                        help="Explicitly expose the bounded native solver mutation tool")
    args = parser.parse_args()
    create_server(args.workspace, allow_native_solvers=args.allow_native_solvers).run(transport="stdio")


if __name__ == "__main__":
    main()
