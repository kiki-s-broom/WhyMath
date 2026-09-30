/* git 어댑터 (HARN-206) — 작업 트리·브랜치·변경 파일 수·기준 브랜치 대비 앞선 커밋 수.
   페이로드의 판정과 무관한 *별도 사실*이다. 기준 브랜치를 못 찾으면 undeterminable + 사유. */
import type { GitFacts, SourceResult } from "../../shared/types";
import type { Exec } from "./exec";

export const GIT_TIMEOUT_MS = 30_000;
const BASE_CANDIDATES = ["origin/main", "origin/master", "main"];

export function parseWorktrees(porcelain: string): GitFacts["worktrees"] {
  const out: GitFacts["worktrees"] = [];
  let cur: { path: string; head?: string; branch?: string } | null = null;
  for (const line of porcelain.split(/\r?\n/)) {
    if (line.startsWith("worktree ")) { if (cur) out.push(cur); cur = { path: line.slice(9) }; }
    else if (cur && line.startsWith("HEAD ")) cur.head = line.slice(5);
    else if (cur && line.startsWith("branch ")) cur.branch = line.slice(7).replace(/^refs\/heads\//, "");
  }
  if (cur) out.push(cur);
  return out;
}

export function countStatusLines(porcelain: string): number {
  return porcelain.split(/\r?\n/).filter((l) => l.trim().length > 0).length;
}

export async function collectGit(root: string, exec: Exec): Promise<SourceResult<GitFacts>> {
  const at = new Date().toISOString();
  const git = (args: string[]) => exec("git", args, { cwd: root, timeoutMs: GIT_TIMEOUT_MS });
  const inside = await git(["rev-parse", "--is-inside-work-tree"]);
  if (inside.status !== "ok") {
    return { status: inside.status, tool: "git", at, reason: inside.reason ?? "git rev-parse 실패" };
  }
  const warnings: string[] = [];
  const wt = await git(["worktree", "list", "--porcelain"]);
  if (wt.status !== "ok") warnings.push(`worktree list: ${wt.reason}`);
  const st = await git(["status", "--porcelain"]);
  if (st.status !== "ok") warnings.push(`status: ${st.reason}`);
  const br = await git(["rev-parse", "--abbrev-ref", "HEAD"]);
  if (br.status !== "ok") warnings.push(`branch: ${br.reason}`);

  let ahead: GitFacts["ahead"] = "undeterminable";
  let aheadReason: string | undefined;
  let baseRef: string | undefined;
  for (const cand of BASE_CANDIDATES) {
    const v = await git(["rev-parse", "--verify", "--quiet", cand]);
    if (v.status !== "ok") continue;
    const c = await git(["rev-list", "--count", `${cand}..HEAD`]);
    if (c.status === "ok" && /^\d+$/.test(c.stdout.trim())) { ahead = Number(c.stdout.trim()); baseRef = cand; break; }
    aheadReason = c.reason;
  }
  if (ahead === "undeterminable" && !aheadReason) aheadReason = `기준 브랜치를 찾지 못했다 — 후보: ${BASE_CANDIDATES.join(", ")}`;
  const data: GitFacts = {
    branch: br.status === "ok" ? br.stdout.trim() : "(미상)",
    changedFiles: st.status === "ok" ? countStatusLines(st.stdout) : -1,
    ahead, aheadReason, baseRef,
    worktrees: wt.status === "ok" ? parseWorktrees(wt.stdout) : [],
  };
  return { status: "ok", tool: "git", at, data, warnings: warnings.length ? warnings : undefined };
}
