/* 하네스 어댑터 (HARN-206) — `<python> scripts/harness/work_graph.py --json [--no-remote]`.
   stdout JSON을 **그대로** 페이로드로 쓴다. 판정 재계산 금지. stderr는 warnings로 보존. */
import type { Payload, SourceResult, WorkspaceOptions } from "../../shared/types";
import type { Exec } from "./exec";
import { findPython } from "./python";

export const HARNESS_TIMEOUT_MS = 120_000;
const WORK_GRAPH = "scripts/harness/work_graph.py";

export interface HarnessCollect { result: SourceResult<null>; payload: Payload | null }

function splitLines(s: string): string[] {
  return s.split(/\r?\n/).map((l) => l.trimEnd()).filter(Boolean).slice(0, 200);
}

/** `root` = 파이썬(.venv)을 찾을 저장소 · `cwd` = work_graph.py를 돌릴 트리(HARN-306: 최신 main 거울이면 거울 폴더) */
export async function collectHarness(
  root: string, options: WorkspaceOptions, exec: Exec, platform: NodeJS.Platform = process.platform, cwd: string = root,
): Promise<HarnessCollect> {
  const at = new Date().toISOString();
  const py = await findPython(exec, root, options.python, platform);
  if (!py.found) {
    return { payload: null, result: { status: "missing_tool", tool: "python", at,
      reason: `파이썬 실행 파일을 찾지 못했다 — 시도: ${py.tried.join(", ")}. 작업공간 설정에서 경로를 지정하라` } };
  }
  const tool = [py.found.cmd, ...py.found.prefix].join(" ");
  const args = [...py.found.prefix, WORK_GRAPH, "--json"];
  if (!options.remote) args.push("--no-remote");
  const r = await exec(py.found.cmd, args, { cwd, timeoutMs: HARNESS_TIMEOUT_MS });
  const warnings = splitLines(r.stderr);
  if (r.status !== "ok") {
    return { payload: null, result: { status: r.status, tool, at, reason: r.reason, warnings } };
  }
  let payload: Payload;
  try {
    payload = JSON.parse(r.stdout) as Payload;
  } catch (e) {
    const ex = e as Error;
    return { payload: null, result: { status: "error", tool, at, warnings,
      reason: `${ex.name}: work_graph.py 표준출력을 JSON으로 읽지 못했다 — ${ex.message}` } };
  }
  if (!payload || typeof payload !== "object" || !payload.nodes || !Array.isArray(payload.edges)) {
    return { payload: null, result: { status: "error", tool, at, warnings,
      reason: "SchemaError: 페이로드에 nodes/edges가 없다 — work_graph.py 버전을 확인하라" } };
  }
  return { payload, result: { status: "ok", tool, at, warnings: warnings.length ? warnings : undefined, data: null } };
}
