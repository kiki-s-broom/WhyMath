/* 최신 main 거울 (HARN-306) — 새로고침이 "공유 작업 사본의 지금 상태"가 아니라 "원격의 최신 main"을
   그리게 한다. Kiki 클론은 여러 세션이 같이 쓰는 작업 사본이라 낡은 브랜치에 머물러 있을 수 있고,
   거기서 work_graph.py를 돌리면 새로고침해도 그래프가 바뀌지 않는다(2026-10-09 실측).

   절차: ① git fetch origin(실패해도 계속 — 이전에 받아 둔 origin/main으로 그리고 사유를 남긴다)
        ② origin/main 해시 확인 ③ 앱 전용 detached worktree를 그 해시로 맞춘다.
   원 작업 사본의 브랜치·파일·스테이징은 건드리지 않는다. 바뀌는 것은 저장소의 worktree 메타데이터
   (`.git/worktrees/<이름>`)와 앱 데이터 폴더 아래 거울 폴더뿐이다. */
import { promises as fs } from "node:fs";
import path from "node:path";
import type { SourceResult, TrunkFacts } from "../../shared/types";
import { resetOwnedDir } from "../store/atomic";
import type { Exec } from "./exec";

export const TRUNK_REF = "origin/main";
export const FETCH_TIMEOUT_MS = 90_000;
export const CHECKOUT_TIMEOUT_MS = 180_000;
const GIT_TIMEOUT_MS = 30_000;

export interface TrunkPrepared { result: SourceResult<TrunkFacts>; dir: string | null }

/** 같은 폴더인가 — Windows는 대소문자·구분자 차이를 무시한다 */
export function samePath(a: string, b: string, platform: NodeJS.Platform = process.platform): boolean {
  const norm = (p: string) => {
    const r = path.resolve(p).replace(/[\\/]+$/, "");
    return platform === "win32" ? r.replace(/\//g, "\\").toLowerCase() : r;
  };
  return norm(a) === norm(b);
}

export async function prepareTrunk(root: string, dir: string, exec: Exec, platform: NodeJS.Platform = process.platform): Promise<TrunkPrepared> {
  const at = new Date().toISOString();
  const git = (args: string[], cwd = root, timeoutMs = GIT_TIMEOUT_MS) => exec("git", args, { cwd, timeoutMs });
  const fail = (status: SourceResult["status"], reason: string, warnings: string[] = []): TrunkPrepared =>
    ({ dir: null, result: { status, tool: "git", at, reason, warnings: warnings.length ? warnings : undefined } });

  // 거울 폴더는 앱 데이터 아래여야 한다 — 저장소 안이나 저장소 자신이면 지우기 단계가 원본을 건드린다
  const rel = path.relative(path.resolve(root), path.resolve(dir));
  if (samePath(root, dir, platform) || (!rel.startsWith("..") && !path.isAbsolute(rel))) {
    return fail("error", `거울 폴더가 저장소 안에 있다 — 거부: ${dir}`);
  }
  // ① 원격의 최신 상태를 받는다. 실패는 치명적이지 않다 — 다만 "최신"이라고 말하지 않는다.
  const warnings: string[] = [];
  const fetch = await git(["fetch", "--prune", "origin"], root, FETCH_TIMEOUT_MS);
  if (fetch.status === "missing_tool") return fail("missing_tool", fetch.reason ?? "git을 찾지 못했다");
  const fetched = fetch.status === "ok";
  const fetchReason = fetched ? undefined : `${fetch.reason ?? fetch.status}${fetch.stderr.trim() ? ` — ${fetch.stderr.trim().split(/\r?\n/).slice(-1)[0]}` : ""}`;
  if (!fetched) warnings.push(`git fetch 실패 — 마지막으로 받아 둔 ${TRUNK_REF}로 그렸다: ${fetchReason}`);

  // ② 기준 해시
  const rev = await git(["rev-parse", "--verify", "--quiet", `${TRUNK_REF}^{commit}`]);
  const sha = rev.stdout.trim();
  if (rev.status !== "ok" || !/^[0-9a-f]{40}$/.test(sha)) {
    return fail("error", `${TRUNK_REF}을 찾지 못했다 — 원격 origin에서 main을 받은 적이 없다${fetchReason ? ` (fetch: ${fetchReason})` : ""}`, warnings);
  }

  // ③ 거울 worktree — 우리 것이 이미 있으면 해시만 옮기고, 아니면 새로 만든다
  const list = await git(["worktree", "list", "--porcelain"]);
  if (list.status !== "ok") return fail("error", `worktree list 실패: ${list.reason}`, warnings);
  const registered = list.stdout.split(/\r?\n/).filter((l) => l.startsWith("worktree "))
    .some((l) => samePath(l.slice(9), dir, platform));
  let exists = false;
  try { await fs.access(path.join(dir, ".git")); exists = true; } catch { /* 없음 */ }

  if (registered && exists) {
    const co = await git(["checkout", "--detach", "--force", sha], dir, CHECKOUT_TIMEOUT_MS);
    if (co.status !== "ok") return fail(co.status === "timeout" ? "timeout" : "error", `거울 갱신 실패(checkout): ${co.reason}`, warnings);
    // 거울은 읽기 전용이지만 하네스가 남긴 부산물이 다음 판정에 섞이지 않게 추적 밖 파일을 지운다
    const clean = await git(["clean", "-fdq"], dir);
    if (clean.status !== "ok") warnings.push(`거울 정리(git clean) 실패: ${clean.reason}`);
  } else {
    // 등록만 남고 폴더가 사라졌거나, 폴더만 남고 등록이 없으면 둘 다 치우고 다시 만든다
    if (registered) await git(["worktree", "remove", "--force", dir]);
    await git(["worktree", "prune"]);
    await resetOwnedDir(dir);
    const add = await git(["worktree", "add", "--detach", "--force", dir, sha], root, CHECKOUT_TIMEOUT_MS);
    if (add.status !== "ok") return fail(add.status === "timeout" ? "timeout" : "error", `거울 만들기 실패(worktree add): ${add.reason}`, warnings);
  }

  // 거울이 정말 그 해시인가 — 간접 신호(명령 성공)가 아니라 결과를 확인한다
  const head = await git(["rev-parse", "HEAD"], dir);
  if (head.status !== "ok" || head.stdout.trim() !== sha) {
    return fail("error", `거울 HEAD가 ${sha.slice(0, 8)}이 아니다 (${head.stdout.trim().slice(0, 8) || head.reason})`, warnings);
  }
  return {
    dir,
    result: {
      status: "ok", tool: "git", at,
      warnings: warnings.length ? warnings : undefined,
      data: { ref: TRUNK_REF, sha, fetched, fetchReason, dir },
    },
  };
}
