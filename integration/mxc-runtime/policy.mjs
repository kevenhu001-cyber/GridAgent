import { win32 } from "node:path";

export const SDK_VERSION = "1.1.0";

// Only host-created synthetic fixtures are accepted by this qualification tool.
// This is NOT a model-facing execution API.
export function vmRequest({input, output, privateFile}) {
  const paths = [input, output, privateFile];
  if (paths.some(p => typeof p !== "string" || !/^[a-z]:\\[^\\]/i.test(p) ||
      /[\x00-\x1f]/.test(p) || win32.normalize(p) !== p)) {
    throw new Error("Canonical local Windows fixture paths required");
  }
  const root = win32.dirname(input);
  if (win32.dirname(output) !== root || win32.dirname(privateFile) !== root ||
      win32.basename(input) !== "input" || win32.basename(output) !== "output" ||
      win32.basename(privateFile) !== "private.txt") {
    throw new Error("Unexpected fixture layout");
  }
  const quote = value => "'" + value.replaceAll("'", "''") + "'";
  const source = [
    "$ErrorActionPreference = 'Stop'",
    "$inputFile = " + quote(win32.join(input, "sample.txt")),
    "$outputFile = " + quote(win32.join(output, "result.txt")),
    "$privateFile = " + quote(privateFile),
    "$value = [IO.File]::ReadAllText($inputFile)",
    "if ($value -ne 'gridagent-fixture') { throw 'input mismatch' }",
    "$readonly = $false",
    "try { [IO.File]::WriteAllText($inputFile, 'modified') } catch { $readonly = $true }",
    "if (-not $readonly) { throw 'read-only input was writable' }",
    "$hidden = $false",
    "try { [void][IO.File]::ReadAllText($privateFile) } catch { $hidden = $true }",
    "if (-not $hidden) { throw 'unshared host file was readable' }",
    "[IO.File]::WriteAllText($outputFile, 'gridagent-qualified')",
    "Write-Output 'gridagent-qualified'",
  ].join("\r\n");
  return {
    version: "1.1.0-alpha",
    containment: "windows_sandbox",
    filesystem: {readonlyPaths: [input], readwritePaths: [output]},
    process: {
      commandLine: "powershell.exe -NoProfile -NonInteractive -EncodedCommand " +
        Buffer.from(source, "utf16le").toString("base64"),
      timeout: 120000,
    },
    // The pinned VM backend rejects explicit network sections; its guest
    // firewall denies external network access by default. Test separately.
  };
}
