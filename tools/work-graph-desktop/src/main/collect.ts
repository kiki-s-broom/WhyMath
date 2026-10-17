/* 스냅샷 수집 (HARN-206) — 어댑터 3종을 돌려 하나의 스냅샷으로 묶는다. 어댑터 실패는 그대로
   sources에 남고(빈 결과로 위장하지 않는다), 페이로드는 하네스가 낸 것을 그대로 싣는다. */
import type { Snapshot, SourceResult, TrunkFacts, Workspace } from "../shared/types";
import type { Exec } from "./adapters/exec";
import { collectGit } from "./adapters/git";
import { collectGithub } from "./adapters/github";
import { collectHarness, type HarnessCollect } from "./adapters/harness";
import { prepareTrunk, samePath } from "./adapters/trunk";

/** `trunkDir` = 최신 main 거울 폴더(HARN-306 · 앱 데이터 아래). source가 worktree이거나 주지 않으면 저장소 폴더를 그린다. */
export async function collectSnapshot(
  ws: Workspace, exec: Exec, platform: NodeJS.Platform = process.platform, trunkDir?: string,
): Promise<Snapshot> {
  const at = new Date().toISOString();
  const useTrunk = ws.kind === "harness" && ws.options.source !== "worktree" && !!trunkDir;
  let trunk: SourceResult<TrunkFacts> = { status: "skipped", tool: "git", at,
    reason: ws.kind !== "harness" ? "git 전용 작업공간" : "설정이 '작업 트리' — 저장소 폴더의 지금 상태를 그린다(원격의 새 커밋은 반영되지 않는다)" };
  let graphDir = ws.root;
  let harnessP: Promise<HarnessCollect>;
  if (useTrunk) {
    const prep = await prepareTrunk(ws.root, trunkDir!, exec, platform);
    trunk = prep.result;
    // 거울을 못 만들면 작업 트리로 몰래 물러서지 않는다 — 그게 "새로고침해도 안 바뀌는" 원래 결함이다
    harnessP = prep.dir
      ? collectHarness(ws.root, ws.options, exec, platform, (graphDir = prep.dir))
      : Promise.resolve({ payload: null, result: { status: "skipped" as const, tool: "python", at,
          reason: `최신 main을 준비하지 못해 그래프를 그리지 않았다 — ${prep.result.reason ?? prep.result.status}` } });
  } else if (ws.kind === "harness") {
    harnessP = collectHarness(ws.root, ws.options, exec, platform);
  } else {
    harnessP = Promise.resolve({ payload: null, result: { status: "skipped" as const, tool: "python", at,
      reason: "git 전용 작업공간 — scripts/harness/work_graph.py가 없어 그래프를 만들 수 없다" } });
  }
  const [harness, gitRaw, github] = await Promise.all([
    harnessP, collectGit(ws.root, exec), collectGithub(ws.root, ws.options.github, exec),
  ]);
  // 거울 폴더는 저장소의 작업 사본 목록에서 뺀다(앱이 만든 것이다)
  const git = gitRaw.data && graphDir !== ws.root
    ? { ...gitRaw, data: { ...gitRaw.data, worktrees: gitRaw.data.worktrees.filter((w) => !samePath(w.path, graphDir, platform)) } }
    : gitRaw;
  return {
    workspaceId: ws.id,
    collectedAt: at,
    sources: { trunk, harness: harness.result, git, github },
    payload: harness.payload,
    stale: false,
  };
}
