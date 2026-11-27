"""Tool registration for the primary LLM; no engineering decision policy."""
from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

from . import scientific_runtime as runtime
from . import scientific_workspace as workspace


def scientific_tools(root):
    @tool
    def scientific_environment() -> dict:
        """Discover authorization, isolated Python availability and optional managed libraries."""
        return runtime.status(root)

    @tool
    def list_project_files() -> dict:
        """List files in the explicitly authorized persistent scientific project only."""
        return workspace.list_project(root)

    @tool
    def read_project_file(path: str) -> dict:
        """Read UTF-8 project source or data with the content fingerprint."""
        return workspace.read_project(root, path)

    @tool
    def write_project_file(path: str, text: Annotated[str, Field(max_length=1048576)],
                           expected_sha256: str | None = None) -> dict:
        """Create a project text file or replace it after reading its current SHA-256."""
        return workspace.write_project(root, path, text, expected_sha256)

    @tool
    def execute_python(entry: str, plugin: str | None = None) -> dict:
        """Execute an LLM-authored project Python file in an authorized isolated environment.
        Native library APIs are available; optionally select one installed managed plugin.
        Read project files normally; write deliverables to GRIDAGENT_OUTPUT_DIR.
        Returns actual exit status, output/error log tail, run ID and artifact manifest.
        Execution alone does not verify physical correctness.
        """
        try:
            return runtime.execute(root, entry, plugin)
        except (OSError, ValueError, SyntaxError) as exc:
            return {"status": "failed", "reason": str(exc)[:500]}

    @tool
    def read_scientific_artifact(run_id: str, path: str, offset: int = 0,
                                 limit: Annotated[int, Field(ge=1, le=24000)] = 12000) -> dict:
        """Read a committed UTF-8 scientific run artifact page, with hash verification."""
        return workspace.read_artifact(root, run_id, path, offset, limit)

    return [scientific_environment, list_project_files, read_project_file, write_project_file,
            execute_python, read_scientific_artifact]
