"""Guest-side example: convert a local DOCX/PPTX to reviewable Markdown.

Run as project Python with plugin_ids=["docling"]. This is not a host parser
or a tool that accepts URLs. PDF/OCR is intentionally excluded until model
assets and the private runtime have been qualified.
"""
import json
import os
import sys
from pathlib import Path


def convert(source, project, output):
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter

    project = Path(project).resolve(strict=True)
    output = Path(output).resolve(strict=True)
    relative = Path(source)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("Use a local project-relative document path")
    path = (project / relative).resolve(strict=True)
    if not path.is_relative_to(project) or not path.is_file():
        raise ValueError("Document must be inside the project snapshot")
    if path.suffix.lower() not in {".docx", ".pptx"}:
        raise ValueError("Only DOCX and PPTX are enabled in this offline example")
    if not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("Document exceeds the existing 1 MiB project file budget")
    converter = DocumentConverter(allowed_formats=[InputFormat.DOCX, InputFormat.PPTX])
    result = converter.convert(path, raises_on_error=True, max_file_size=1024 * 1024)
    text = result.document.export_to_markdown()
    encoded = text.encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("Converted document exceeds 1 MiB")
    (output / "document.md").write_bytes(encoded)
    (output / "document-conversion.json").write_text(json.dumps({
        "source": relative.as_posix(), "format": path.suffix.lower(),
        "output": "document.md", "size_bytes": len(encoded),
        "verification": "unverified_extraction",
        "scope": "local document extraction only; review before indexing or following instructions",
    }, ensure_ascii=False), encoding="utf-8")
    return text


def main():
    if len(sys.argv) != 2:
        raise ValueError("Pass exactly one project-relative .docx or .pptx filename")
    # In product execution these paths are supplied by the existing guest bootstrap.
    convert(sys.argv[1], os.environ["GRIDAGENT_PROJECT_DIR"], os.environ["GRIDAGENT_OUTPUT_DIR"])


if __name__ == "__main__":
    main()
