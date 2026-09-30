/* 파이썬 실행 파일 탐색 (HARN-206) — options.python → python3 → python → (Windows) py -3 */
import type { Exec } from "./exec";

export interface PythonCandidate { cmd: string; prefix: string[] }

export function pythonCandidates(configured: string | undefined, platform: NodeJS.Platform = process.platform): PythonCandidate[] {
  const out: PythonCandidate[] = [];
  if (configured && configured.trim()) out.push({ cmd: configured.trim(), prefix: [] });
  out.push({ cmd: "python3", prefix: [] }, { cmd: "python", prefix: [] });
  if (platform === "win32") out.push({ cmd: "py", prefix: ["-3"] });
  return out;
}

/** 후보를 차례로 `--version`으로 찔러 보고 처음 되는 것을 돌려준다. 하나도 없으면 null + 시도 목록. */
export async function findPython(
  exec: Exec, cwd: string, configured?: string, platform: NodeJS.Platform = process.platform,
): Promise<{ found: PythonCandidate | null; tried: string[] }> {
  const tried: string[] = [];
  for (const c of pythonCandidates(configured, platform)) {
    const label = [c.cmd, ...c.prefix].join(" ");
    tried.push(label);
    const r = await exec(c.cmd, [...c.prefix, "--version"], { cwd, timeoutMs: 15000 });
    if (r.status === "ok") return { found: c, tried };
  }
  return { found: null, tried };
}
