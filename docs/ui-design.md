# GridAgent desktop UI design contract

The selected Proliferate desktop and shared design system are the baseline.
Preserve its layout, typography, spacing, interaction and component styling.
Do not recreate the retired WinUI/WPF UI or build another desktop shell.

- Reuse existing product components, their behavior, and state contracts before
  creating anything new. See [the source inventory](proliferate-reuse-audit.md).
  Model picker, API-key management/dialogs, chat composer/transcript, history,
  tabs, settings, file tree/editor, tool cards and search are existing features,
  not new UI milestones. Adapt their data/transport owners; do not recreate
  controls to work around an old backend. No broad layout or visual redesign
  without separate owner approval.
- Temporary native Pi preview is for qualification only; restore original
  ChatView/ChatInput/SessionTranscriptPane behavior through the shared contracts,
  then retire parallel preview UI/state.
- Use shared design tokens, accessible controls and restrained visual hierarchy.
- Keep the assistant primary; scientific workspaces, files, model data and
  execution results should extend the existing workbench rather than compete
  with the main conversation.
- Keep tool activity compact and progressively disclosed. Never expose hidden
  reasoning, raw provider payloads, tool arguments or stack traces by default.
- Render scientific results from committed artifacts, with units, provenance,
  clear validation status and accessible numerical alternatives.
- Preserve source data, distinguish downsampled previews, and never execute
  model-generated UI code.
- Explicitly authorize dependency changes, sandbox execution and repair scope;
  never confuse terminal permissions with an OS-level scientific sandbox.
- Validate light/dark themes, DPI, keyboard navigation, accessibility, long
  histories, narrow windows, streaming and error states with real desktop
  screenshots and interaction tests.

See [ADR 0002](adr/0002-proliferate-desktop.md) for the migration and
[integration guide](../integration/proliferate/README.md) for current status.
