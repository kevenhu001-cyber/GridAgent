import { randomUUID } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";

/** Pi shell operation: submit once to isolated guest, await actual terminal status. */
export function isolatedShell(client) {
  return async (shell, command, {onData, signal, timeout} = {}) => {
    if (signal?.aborted) throw new Error("Shell cancelled before submission");
    const job_id = randomUUID().replaceAll("-", "");
    const deadline = Date.now() + Math.min(240, Math.max(1, timeout ?? 240)) * 1000;
    let job;
    try {
      job = await client.request("job.submit_shell", {job_id, shell, command});
      while (job.status === "queued" || job.status === "running") {
        if (signal?.aborted || Date.now() >= deadline) {
          await client.request("job.cancel", {job_id});
          throw new Error("Cancellation requested for isolated job " + job_id + "; inspect its status.");
        }
        await delay(350);
        job = await client.request("job.status", {job_id});
      }
    } catch {
      throw new Error("Isolated shell interrupted or rejected; inspect job " + job_id + " before retrying.");
    }
    if (job.stdout_stderr_tail) onData?.(Buffer.from(job.stdout_stderr_tail, "utf8"));
    if (!Number.isInteger(job.exit_code) || !["ok", "failed"].includes(job.status))
      throw new Error("Isolated shell ended without confirmed exit code: " + job.status + " (job " + job_id + ")");
    return {exitCode: job.exit_code};
  };
}
