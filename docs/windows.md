# Windows desktop status

The former WinUI 3 and WPF clients and their packaging pipeline are retired
by owner direction. The current desktop migration reuses Proliferate 0.4.27
(Tauri/React), with the Python GridAgent scientific core exposed through MCP.
A validated Windows installer is not yet available from this migration.

For current developer setup and acceptance gates see
[Proliferate integration](../integration/proliferate/README.md).
The Python CLI/TUI and scientific engine remain available on Windows.
Windows Sandbox requirements for scientific execution are independent of
the retired UI; see [scientific workspace](scientific-workspace.md).
