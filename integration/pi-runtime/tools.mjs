import { randomUUID } from "node:crypto";

const string = (maxLength) => ({type: "string", maxLength});
const id = {type: "string", pattern: "^[a-f0-9]{32}$"};
const page = {type: "integer", minimum: 0, maximum: 100000};
const schema = (properties = {}, required = []) =>
  ({type: "object", properties, required, additionalProperties: false});

const reads = [
  ["scientific_environment", "Scientific environment", "Discover workspace authorization and sandbox availability.", "scientific.status", schema()],
  ["list_solver_backends", "Solver libraries", "Discover installed numerical solvers and capabilities.", "solver.backends", schema()],
  ["list_project_files", "Project files", "List authorized project files.", "workspace.files", schema()],
  ["read_project_file", "Read project file", "Read a bounded page and its complete SHA-256 revision.", "workspace.read",
    schema({path: string(240), offset: page}, ["path"])],
  ["list_scientific_runs", "Scientific runs", "List persistent scientific execution runs.", "scientific.runs", schema()],
  ["read_scientific_artifact", "Read scientific artifact", "Read committed, hash-checked artifact text; results may be unverified.", "scientific.artifact",
    schema({run_id: id, path: string(240), offset: page}, ["run_id", "path"])],
  ["read_native_table", "Read solver table", "Read a bounded page of an existing solver result table.", "solver.table",
    schema({run_id: id, table: string(80), offset: page}, ["run_id", "table"])],
  ["scientific_job_status", "Scientific job status", "Inspect a durable scientific job by its returned ID.", "job.status",
    schema({job_id: id}, ["job_id"])],
  ["latest_scientific_job", "Latest scientific job", "Find this workspace's latest committed job ID and recorded state. A queued or running record leaves the outcome and worker liveness unconfirmed.", "job.latest", schema()],
];
const writes = [
  ["write_project_file", "Write project file", "Create a project file or replace it using its current SHA-256. The workspace grant is required.", "workspace.write",
    schema({path: string(240), text: string(48000), expected_sha256: {type: "string", pattern: "^[a-f0-9]{64}$"}}, ["path", "text"])],
  ["execute_python", "Execute scientific Python", "Submit project Python to the authorized scientific sandbox. Returns a durable job ID; inspect its status and artifacts. Never runs on the unrestricted host.", "job.submit",
    schema({entry: string(240), arguments: {type: "array", items: string(1024), maxItems: 32},
      plugin_ids: {type: "array", items: string(80), maxItems: 4}}, ["entry"])],
  ["cancel_scientific_job", "Cancel scientific job", "Request cooperative cancellation; poll for confirmed terminal state.", "job.cancel",
    schema({job_id: id}, ["job_id"])],
];

/** Only these product-owned native functions are ever registered with Pi. */
export function scientificTools(client, {allowTasks = false, onJob} = {}) {
  return [...reads, ...(allowTasks ? writes : [])].map(([name, label, description, method, parameters]) => ({
    name, label, description, parameters, replay: "never", executionMode: "sequential",
    async execute(_callId, params, signal) {
      if (signal?.aborted) throw new Error("Tool call cancelled before dispatch");
      const args = method === "job.submit" ?
        {...params, job_id: randomUUID().replaceAll("-", "")} : params;
      // Report the durable job ID before dispatch so an interrupted turn can
      // still be reconciled with the job it may have submitted.
      if (method === "job.submit" && typeof onJob === "function") onJob(args.job_id);
      try {
        const result = await client.request(method, args);
        const text = JSON.stringify(result);
        if (text.length > 32000) return {
          content: [{type: "text", text: "Result exceeds model context preview; request a smaller page."}],
          details: {status: "preview_limit"}, isError: true,
        };
        return {content: [{type: "text", text}], details: result};
      } catch (error) {
        // A durable submission may have succeeded before transport loss. Surface
        // its ID rather than silently issuing another calculation.
        const text = args.job_id ? "Scientific operation outcome uncertain. Inspect job " + args.job_id :
          "Scientific operation failed. Inspect authorization and environment before retrying.";
        return {content: [{type: "text", text}], details: {job_id: args.job_id ?? null}, isError: true};
      }
    },
  }));
}
