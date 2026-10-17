/* GitHub 어댑터 (HARN-206) — options.github=true일 때만 gh로 열린 PR 목록을 가져온다.
   브랜치 창에 "PR 사실"로 덧붙일 뿐 상태 판정을 바꾸지 않는다. gh 부재·인증 실패는 사유 그대로. */
import type { PullRequestFact, SourceResult } from "../../shared/types";
import type { Exec } from "./exec";

export const GH_TIMEOUT_MS = 60_000;
const FIELDS = "number,title,url,headRefName,isDraft,reviewDecision,statusCheckRollup";

interface RawPr {
  number: number; title: string; url: string; headRefName: string; isDraft: boolean;
  reviewDecision: string; statusCheckRollup?: { conclusion?: string; state?: string; status?: string }[];
}

export function summarizeChecks(rollup: RawPr["statusCheckRollup"]): string | undefined {
  if (!rollup || !rollup.length) return undefined;
  const c = { pass: 0, fail: 0, pending: 0 };
  for (const r of rollup) {
    const v = (r.conclusion || r.state || "").toUpperCase();
    if (v === "SUCCESS" || v === "NEUTRAL" || v === "SKIPPED") c.pass++;
    else if (v === "FAILURE" || v === "ERROR" || v === "CANCELLED" || v === "TIMED_OUT") c.fail++;
    else c.pending++;
  }
  return `통과 ${c.pass} · 실패 ${c.fail} · 진행 ${c.pending}`;
}

export async function collectGithub(root: string, enabled: boolean, exec: Exec): Promise<SourceResult<PullRequestFact[]>> {
  const at = new Date().toISOString();
  if (!enabled) return { status: "skipped", tool: "gh", at, reason: "작업공간 설정에서 GitHub 조회가 꺼져 있다" };
  const r = await exec("gh", ["pr", "list", "--state", "open", "--json", FIELDS, "--limit", "100"],
    { cwd: root, timeoutMs: GH_TIMEOUT_MS });
  if (r.status !== "ok") {
    const hint = r.stderr.trim().split(/\r?\n/).slice(0, 3).join(" / ");
    return { status: r.status, tool: "gh", at, reason: [r.reason, hint].filter(Boolean).join(" — ") };
  }
  try {
    const raw = JSON.parse(r.stdout) as RawPr[];
    const data: PullRequestFact[] = raw.map((p) => ({
      number: p.number, title: p.title, url: p.url, headRefName: p.headRefName,
      isDraft: !!p.isDraft, reviewDecision: p.reviewDecision || "", checks: summarizeChecks(p.statusCheckRollup),
    }));
    return { status: "ok", tool: "gh", at, data };
  } catch (e) {
    const ex = e as Error;
    return { status: "error", tool: "gh", at, reason: `${ex.name}: gh 출력을 JSON으로 읽지 못했다 — ${ex.message}` };
  }
}
