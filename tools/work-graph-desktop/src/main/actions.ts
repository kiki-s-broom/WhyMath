/* 동작(쓰기) 실행 (HARN-206) — 유일한 쓰기 창구는 `backlog.py` CLI다.
   허용된 인자만 배열로 조립해 셸 없이 spawn 한다(문자열 결합 금지). 이 모듈은 backlog/ 파일을
   읽지도 쓰지도 않는다 — 결과(exit code·stdout·stderr·command)를 그대로 렌더러에 돌려준다. */
import type { ActionRequest, ActionResult, WorkspaceOptions } from "../shared/types";
import type { Exec } from "./adapters/exec";
import { findPython } from "./adapters/python";

export const ACTION_TIMEOUT_MS = 120_000;
const BACKLOG_CLI = "scripts/harness/backlog.py";
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$/;
/** backlog.py `--as` 선택지 — models.OWNERS 중 claude 제외 */
const AS_OWNERS = new Set(["kiki", "partner"]);

export type BuildResult = { ok: true; args: string[] } | { ok: false; reason: string };

function freeText(v: unknown, label: string, max = 4000): string | { error: string } {
  if (typeof v !== "string" || !v.trim()) return { error: `${label}이(가) 비어 있다` };
  if (v.length > max) return { error: `${label}이(가) ${max}자를 넘는다` };
  if (v.trimStart().startsWith("-")) return { error: `${label}은(는) '-'로 시작할 수 없다(플래그로 해석된다)` };
  if (/[\0\r\n]/.test(v)) return { error: `${label}에 줄바꿈·NUL을 넣을 수 없다` };
  return v.trim();
}

/** 요청 → backlog.py 인자 배열. 허용 인자만, 나머지는 거부. */
export function buildActionArgs(req: ActionRequest): BuildResult {
  const a = req.args || ({} as ActionRequest["args"]);
  if (typeof a.id !== "string" || !ID_RE.test(a.id)) return { ok: false, reason: `ID 형식이 아니다: ${JSON.stringify(a.id)}` };
  switch (req.kind) {
    case "start":
      return { ok: true, args: [BACKLOG_CLI, "start", a.id] };
    case "gates_clear": {
      const ev = freeText(a.evidence, "근거(--evidence)");
      if (typeof ev !== "string") return { ok: false, reason: ev.error };
      const args = [BACKLOG_CLI, "gates", "clear", a.id];
      if (a.assignee && a.assignee !== "claude") {
        if (!AS_OWNERS.has(a.assignee)) return { ok: false, reason: `--as 선택지가 아니다: ${a.assignee}` };
        args.push("--as", a.assignee);
      }
      args.push("--evidence", ev);
      if (a.noBase !== undefined && a.noBase !== "") {
        const nb = freeText(a.noBase, "--no-base 사유");
        if (typeof nb !== "string") return { ok: false, reason: nb.error };
        args.push("--no-base", nb);
      }
      return { ok: true, args };
    }
    case "done": {
      const arts = Array.isArray(a.artifacts) ? a.artifacts : [];
      if (!arts.length) return { ok: false, reason: "증적(--artifact)이 하나 이상 필요하다" };
      const args = [BACKLOG_CLI, "done", a.id];
      for (const art of arts) {
        const t = freeText(art, "증적(--artifact)", 1000);
        if (typeof t !== "string") return { ok: false, reason: t.error };
        args.push("--artifact", t);
      }
      return { ok: true, args };
    }
    default:
      return { ok: false, reason: `허용되지 않은 동작: ${String((req as { kind: unknown }).kind)}` };
  }
}

export async function runAction(
  req: ActionRequest, root: string, options: WorkspaceOptions, exec: Exec, platform: NodeJS.Platform = process.platform,
): Promise<ActionResult> {
  const built = buildActionArgs(req);
  if (!built.ok) return { ok: false, exitCode: null, stdout: "", stderr: "", command: [], reason: built.reason };
  const py = await findPython(exec, root, options.python, platform);
  if (!py.found) {
    return { ok: false, exitCode: null, stdout: "", stderr: "", command: built.args,
      reason: `파이썬 실행 파일을 찾지 못했다 — 시도: ${py.tried.join(", ")}` };
  }
  const argv = [...py.found.prefix, ...built.args];
  const r = await exec(py.found.cmd, argv, { cwd: root, timeoutMs: ACTION_TIMEOUT_MS });
  return {
    ok: r.status === "ok",
    exitCode: r.code,
    stdout: r.stdout,
    stderr: r.stderr,
    command: [py.found.cmd, ...argv],
    reason: r.status === "ok" ? undefined : r.reason,
  };
}
