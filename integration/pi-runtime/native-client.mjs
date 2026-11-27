import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { dirname, isAbsolute } from "node:path";

const MAX_REQUEST = 64 * 1024;
const MAX_RESPONSE = 4 * 1024 * 1024 + 1;
const ALLOWED_ENV = new Set(["PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR",
  "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "LD_LIBRARY_PATH",
  "COMSPEC", "PATHEXT", "GRIDAGENT_SANDBOX_RUNTIME", "GRIDAGENT_PLUGIN_ROOT"]);

/** Trusted host configuration only. Model tools cannot select the executable or workspace. */
export function openNativeClient({ python, workspace, allowTasks = false }) {
  if (!isAbsolute(python) || !isAbsolute(workspace)) throw new Error("Absolute host paths required");
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    ALLOWED_ENV.has(key.toUpperCase())));
  const args = ["-I", "-X", "utf8", "-m", "gridagent.native_service", workspace];
  if (allowTasks) args.push("--tasks");
  const child = spawn(python, args, {
    cwd: dirname(python), env, shell: false, windowsHide: true,
    stdio: ["pipe", "pipe", "ignore"],
  });
  let pending;
  let buffer = Buffer.alloc(0);
  let closed = false;
  function fail(error) {
    if (closed) return;
    closed = true;
    const current = pending;
    pending = undefined;
    if (current) {
      clearTimeout(current.timer);
      current.reject(error);
    }
    child.kill();
  }
  child.on("error", () => fail(new Error("Scientific service launch failed")));
  child.on("exit", () => fail(new Error("Scientific service exited; operation not replayed")));
  child.stdin.on("error", () => fail(new Error("Scientific IPC write failed")));
  child.stdout.on("data", (chunk) => {
    if (closed) return;
    if (buffer.length + chunk.length > MAX_RESPONSE) {
      fail(new Error("Scientific response exceeded limit"));
      return;
    }
    buffer = Buffer.concat([buffer, chunk]);
    const newline = buffer.indexOf(10);
    if (newline < 0) return;
    const current = pending;
    try {
      if (!current || newline !== buffer.length - 1) throw new Error("Unexpected scientific frame");
      const response = JSON.parse(buffer.subarray(0, newline).toString("utf8"));
      if (response.version !== 1 || response.id !== current.id || typeof response.ok !== "boolean") {
        throw new Error("Scientific protocol mismatch");
      }
      buffer = Buffer.alloc(0);
      pending = undefined;
      clearTimeout(current.timer);
      if (response.ok) current.resolve(response.result);
      else current.reject(new Error("Scientific request rejected: " + (response.error?.code ?? "unknown")));
    } catch {
      fail(new Error("Invalid scientific response; operation not replayed"));
    }
  });
  return {
    async request(method, params = {}) {
      if (closed || pending) throw new Error("Scientific connection unavailable or busy");
      const id = randomUUID().replaceAll("-", "");
      const frame = JSON.stringify({version: 1, id, method, params}) + "\n";
      if (Buffer.byteLength(frame) > MAX_REQUEST) throw new Error("Scientific request exceeded limit");
      return new Promise((resolve, reject) => {
        pending = {id, resolve, reject, timer: setTimeout(() =>
          fail(new Error("Scientific request timed out; operation not replayed")), 30000)};
        child.stdin.write(frame);
      });
    },
    close() { fail(new Error("Scientific client closed")); },
  };
}
