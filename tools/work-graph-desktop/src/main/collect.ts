/* 스냅샷 수집 (HARN-206) — 어댑터 3종을 돌려 하나의 스냅샷으로 묶는다. 어댑터 실패는 그대로
   sources에 남고(빈 결과로 위장하지 않는다), 페이로드는 하네스가 낸 것을 그대로 싣는다. */
import type { Snapshot, Workspace } from "../shared/types";
import type { Exec } from "./adapters/exec";
import { collectGit } from "./adapters/git";
import { collectGithub } from "./adapters/github";
import { collectHarness } from "./adapters/harness";

export async function collectSnapshot(ws: Workspace, exec: Exec, platform: NodeJS.Platform = process.platform): Promise<Snapshot> {
  const at = new Date().toISOString();
  const harnessP = ws.kind === "harness"
    ? collectHarness(ws.root, ws.options, exec, platform)
    : Promise.resolve({ payload: null, result: { status: "skipped" as const, tool: "python", at,
        reason: "git 전용 작업공간 — scripts/harness/work_graph.py가 없어 그래프를 만들 수 없다" } });
  const [harness, git, github] = await Promise.all([
    harnessP, collectGit(ws.root, exec), collectGithub(ws.root, ws.options.github, exec),
  ]);
  return {
    workspaceId: ws.id,
    collectedAt: at,
    sources: { harness: harness.result, git, github },
    payload: harness.payload,
    stale: false,
  };
}
