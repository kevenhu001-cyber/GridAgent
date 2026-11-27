import { createReadTool, createWriteTool, createEditTool, createBashTool, createPowerShellTool,
  createFindTool, createLsTool, createGrepTool } from "@earendil-works/pi-coding-agent";
import { resolve, relative, isAbsolute, sep, matchesGlob } from "node:path";

const MAX_FILE = 1024 * 1024;

/** Pi's tool schemas and editing implementation; all actual file I/O is scoped IPC. */
export function defaultTools(client, {workspace, allowTasks = false, runShell} = {}) {
  const cwd = resolve(workspace, "scientific-project");
  const revisions = new Map();
  function projectPath(absolute, allowRoot = false) {
    const path = relative(cwd, resolve(cwd, absolute));
    if (path === "" && allowRoot) return "";
    if (!path || isAbsolute(path) || path === ".." || path.startsWith(".." + sep))
      throw new Error("Path is outside the authorized scientific project");
    return path.split(sep).join("/");
  }
  async function files() {
    const result = await client.request("workspace.files");
    return result.files.map(row => row.path);
  }
  async function readFile(absolute) {
    const path = projectPath(absolute);
    let offset = 0, hash, bytes = 0;
    const chunks = [];
    while (offset !== null) {
      const page = await client.request("workspace.read", {path, offset, limit: 12000});
      if (hash && hash !== page.sha256) throw new Error("File changed during read");
      hash = page.sha256;
      const data = Buffer.from(page.text, "utf8");
      bytes += data.length;
      if (bytes > MAX_FILE || (page.next_offset !== null &&
          (!Number.isSafeInteger(page.next_offset) || page.next_offset <= offset)))
        throw new Error("Invalid file pagination");
      chunks.push(data);
      offset = page.next_offset;
    }
    revisions.set(path, hash);
    return Buffer.concat(chunks);
  }
  async function access(absolute) {
    const path = projectPath(absolute);
    if (!(await files()).includes(path)) throw new Error("Project file not found");
  }
  async function writeFile(absolute, content) {
    if (!allowTasks) throw new Error("Workspace mutation is disabled");
    const path = projectPath(absolute);
    // A write to an existing file requires a prior read. The backend's
    // compare-and-swap rejects concurrent edits and unexpected overwrites.
    const result = await client.request("workspace.write", {
      path, text: content, expected_sha256: revisions.get(path) ?? null,
    });
    revisions.set(path, result.sha256);
  }
  async function entries(absolute) {
    const path = projectPath(absolute, true);
    const prefix = path ? path + "/" : "";
    return (await files()).filter(file => file.startsWith(prefix)).map(file => file.slice(prefix.length));
  }
  async function stat(absolute) {
    const path = projectPath(absolute, true);
    if (!path) return {isDirectory: () => true};
    const all = await files();
    if (all.includes(path)) return {isDirectory: () => false};
    if (all.some(file => file.startsWith(path + "/"))) return {isDirectory: () => true};
    throw new Error("Path not found");
  }
  const exists = async (path) => {try {await stat(path); return true;} catch {return false;}};
  const read = createReadTool(cwd, {operations: {readFile, access}});
  const ls = createLsTool(cwd, {operations: {exists, stat,
    readdir: async path => [...new Set((await entries(path)).map(file => file.split("/")[0]))]}});
  const find = createFindTool(cwd, {operations: {exists, glob: async (pattern, path, options) =>
    (await entries(path)).filter(file => matchesGlob(file, pattern) ||
      matchesGlob(file.split("/").at(-1), pattern)).slice(0, Math.min(options.limit, 500))}});
  // Pi grep normally starts ripgrep on the host, even with custom operations.
  // Keep its tool schema but route search through scoped reads; literal search
  // only until an isolated ripgrep backend is available.
  const grep = createGrepTool(cwd);
  grep.description = "Search authorized project text for a literal pattern, with bounded matches. Regex and context are not yet supported.";
  grep.execute = async (_id, params, signal) => {
    if (params.literal === false || params.context) throw new Error("Only literal search is supported in the scoped backend");
    const base = resolve(cwd, params.path ?? ".");
    const info = await stat(base);
    const candidates = info.isDirectory() ? await entries(base) : [""];
    const matches = [];
    const limit = Math.min(100, Math.max(1, params.limit ?? 50));
    const needle = params.ignoreCase ? params.pattern.toLowerCase() : params.pattern;
    for (const file of candidates.slice(0, 100)) {
      if (signal?.aborted) throw new Error("Search aborted");
      if (params.glob && !matchesGlob(file || base.split(sep).at(-1), params.glob)) continue;
      const path = file ? resolve(base, file) : base;
      const content = (await readFile(path)).toString("utf8");
      for (const [index, line] of content.split("\n").entries()) {
        if ((params.ignoreCase ? line.toLowerCase() : line).includes(needle))
          matches.push(projectPath(path) + ":" + (index + 1) + ": " + line.slice(0, 500));
        if (matches.length >= limit) break;
      }
      if (matches.length >= limit) break;
    }
    return {content: [{type: "text", text: matches.join("\n").slice(0, 24000) || "No matches"}],
      details: {scope: "scientific-project", literal: true, filesCapped: candidates.length > 100}};
  };
  const tools = [read, ls, find, grep];
  if (allowTasks) {
    tools.push(createWriteTool(cwd, {operations: {writeFile, mkdir: async path => {projectPath(path, true);}}}),
      createEditTool(cwd, {operations: {readFile, writeFile, access}}));
    // Shell factories are retained, but cannot use Pi's default local process
    // execution. Supply only an OS-isolated, host-authorized backend.
    const operations = shell => ({exec: async (command, _cwd, options) => {
      if (!runShell) throw new Error("Isolated shell backend is unavailable; use execute_python");
      return runShell(shell, command, options);
    }});
    tools.push(createBashTool(cwd, {operations: operations("bash"), exposeSessionEnvironment: false}),
      createPowerShellTool(cwd, {operations: operations("powershell"), exposeSessionEnvironment: false}));
  }
  return tools;
}
