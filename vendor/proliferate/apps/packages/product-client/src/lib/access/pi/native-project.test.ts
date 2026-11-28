import { describe, expect, it } from "vitest";
import { nativeProjectWorkspace } from "./native-project";
import { buildLogicalWorkspaces } from "#product/lib/domain/workspaces/cloud/logical-workspaces";

describe("native scientific project inventory", () => {
  const id = "gridagent-scientific:" + "a".repeat(64);
  it("preserves Pi authorization root and native ID through logical projection", () => {
    const workspace = nativeProjectWorkspace({id, workspacePath:"C:\\Studies\\Grid", projectPath:"C:\\Studies\\Grid\\scientific-project"});
    expect(workspace.path).toBe("C:\\Studies\\Grid");
    expect(workspace.displayName).toBe("Grid");
    const logical = buildLogicalWorkspaces({localWorkspaces:[workspace],repoRoots:[],cloudWorkspaces:[]});
    expect(logical).toHaveLength(1);
    expect(logical[0].id).toBe(id);
    expect(logical[0].localWorkspace?.id).toBe(id);
  });
  it("rejects legacy and malformed identifiers", () => {
    expect(() => nativeProjectWorkspace({id:"legacy",workspacePath:"/study",projectPath:"/study/scientific-project"})).toThrow();
  });
});
