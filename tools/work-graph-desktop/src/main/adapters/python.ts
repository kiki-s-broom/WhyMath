/* 파이썬 실행 파일 탐색 (HARN-206 · HARN-208)
   순서: options.python → 저장소 가상환경(.venv · src/backend/.venv) → python3 → python → (Windows) py -3.
   바로가기로 켜면 PATH의 첫 파이썬이 하네스 의존성(PyYAML)이 없는 다른 환경일 수 있다(conda base +
   .venv 동시 존재 — CLAUDE.md 실측). 그래서 `--version`이 아니라 yaml 임포트로 찔러 **하네스를 실제로
   돌릴 수 있는** 첫 인터프리터를 고른다. */
import path from "node:path";
import type { Exec } from "./exec";

export interface PythonCandidate { cmd: string; prefix: string[] }

/** 하네스(work_graph.py → store.py)가 요구하는 것 — 이것이 되면 그래프를 만들 수 있다 */
export const PROBE_ARGS = ["-c", "import yaml"];

export function pythonCandidates(
  configured: string | undefined, platform: NodeJS.Platform = process.platform, root?: string,
): PythonCandidate[] {
  const out: PythonCandidate[] = [];
  if (configured && configured.trim()) out.push({ cmd: configured.trim(), prefix: [] });
  if (root) {
    const p = platform === "win32" ? path.win32 : path.posix;
    const rel = platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"];
    out.push({ cmd: p.join(root, ".venv", ...rel), prefix: [] });
    out.push({ cmd: p.join(root, "src", "backend", ".venv", ...rel), prefix: [] });
  }
  out.push({ cmd: "python3", prefix: [] }, { cmd: "python", prefix: [] });
  if (platform === "win32") out.push({ cmd: "py", prefix: ["-3"] });
  return out;
}

/** 후보를 차례로 찔러 보고 처음 되는 것을 돌려준다. 하나도 없으면 null + 시도 목록(실패 사유 병기). */
export async function findPython(
  exec: Exec, cwd: string, configured?: string, platform: NodeJS.Platform = process.platform,
): Promise<{ found: PythonCandidate | null; tried: string[] }> {
  const tried: string[] = [];
  for (const c of pythonCandidates(configured, platform, cwd)) {
    const label = [c.cmd, ...c.prefix].join(" ");
    const r = await exec(c.cmd, [...c.prefix, ...PROBE_ARGS], { cwd, timeoutMs: 15000 });
    if (r.status === "ok") { tried.push(label); return { found: c, tried }; }
    // 없음과 '있지만 못 돌림'을 구분해 남긴다 — 후자는 PyYAML이 없는 환경일 가능성이 크다
    tried.push(r.status === "missing_tool" ? label : `${label}(실행됐지만 yaml 임포트 실패)`);
  }
  return { found: null, tried };
}
