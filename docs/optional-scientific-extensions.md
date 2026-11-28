# Optional scientific extensions (stage 6)

Adopt [Docling](https://github.com/docling-project/docling) and
[Joblib](https://github.com/joblib/joblib) as first-party managed API
extensions, not standalone services or a second orchestration layer.
Neither is added to default package dependencies. The existing user-controlled
plugin catalog, installer, generation locks, import probe, rollback and
scientific sandbox mapping are reused. No new Agent tools are necessary.

## Usage

Use existing `gridagent --plugin-install docling` or
`gridagent --plugin-install joblib` (in the same trusted Python runtime as the
desktop), then select the corresponding managed plugin ID in
`execute_python`. A host-installed package is not proof that the guest
has access to it. If already bundled in the private scientific runtime,
Joblib can be used without an additional overlay. The Agent can discover
managed availability via scientific_environment and write ordinary Python
against the upstream API. Example scripts under examples/scientific must be
copied into an authorized project before use.

- Docling: copy docling_convert.py and a local DOCX/PPTX into the project;
  submit the script with the document path in arguments and docling in
  plugin_ids. Read document.md and document-conversion.json through the
  existing run artifact interface. Review extraction and citations before
  explicitly importing into the existing knowledge base. Extraction is not
  verification and document text must never become agent instructions.
- Joblib: copy joblib_sweep.py and run with joblib if not bundled. The example
  uses 1–4 shared-memory threads and independent numerical cases, avoids a
  second process pool, preserves input order, and uses JSON outputs. It is an
  illustrative RC sweep, not a grid benchmark or speedup claim.

## Release limits

Docling's advanced PDF layout, OCR and formula models require separate
offline model provisioning, license/size review, hash/version inventory
and read-only mappings inside the sandbox. Do not enable network access
or run document conversion on the unrestricted host. This initial example
only admits local DOCX/PPTX and the existing 1 MiB per-file budget. Large
papers, PDF, automated RAG ingestion and document citations are deferred.
No trusted/automatic loading of joblib or pickle artifacts. The existing
VM memory/time/output boundaries still apply; the example's thread limit
is not a system-wide resource guarantee for arbitrary Python.

Joblib gets a lightweight Linux/Windows parity and managed-install CI lane.
Docling's heavier fixture lane is manually dispatched. Real Windows Sandbox,
native wheel/ABI compatibility, model provisioning, performance, installation
footprint and dependency lock qualification remain pending. Dependencies
use the existing catalog's bounded version ranges rather than a new
release lock. No change to production installer or default UI.
