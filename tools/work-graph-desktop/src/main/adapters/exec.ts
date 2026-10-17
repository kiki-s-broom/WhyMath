/* 외부 명령 실행 (HARN-206) — 셸을 거치지 않는 spawn(인자 배열). 모든 호출에 타임아웃.
   결과는 status로 구분한다: ok · missing_tool(ENOENT) · timeout · error(비-0 종료·스폰 실패). */
import { spawn } from "node:child_process";

export type ExecStatus = "ok" | "missing_tool" | "timeout" | "error";

export interface ExecResult {
  status: ExecStatus;
  code: number | null;
  stdout: string;
  stderr: string;
  /** 실패 사유(예외 타입명 포함) */
  reason?: string;
}

export interface ExecOptions {
  cwd: string;
  timeoutMs: number;
  env?: NodeJS.ProcessEnv;
  /** 표준출력 상한(바이트) — 넘으면 error. 페이로드는 수 MB일 수 있으니 넉넉히 */
  maxBytes?: number;
}

export type Exec = (cmd: string, args: string[], opts: ExecOptions) => Promise<ExecResult>;

export const runCommand: Exec = (cmd, args, opts) =>
  new Promise<ExecResult>((resolve) => {
    const maxBytes = opts.maxBytes ?? 64 * 1024 * 1024;
    let out: Buffer[] = [], err: Buffer[] = [], outLen = 0, errLen = 0;
    let settled = false, timedOut = false;
    const finish = (r: ExecResult) => { if (!settled) { settled = true; resolve(r); } };
    let child;
    try {
      child = spawn(cmd, args, {
        cwd: opts.cwd, shell: false, windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", ...(opts.env || {}) },
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (e) {
      const ex = e as Error;
      return finish({ status: "error", code: null, stdout: "", stderr: "", reason: `${ex.name}: ${ex.message}` });
    }
    const timer = setTimeout(() => { timedOut = true; try { child.kill("SIGKILL"); } catch { /* 이미 종료 */ } }, opts.timeoutMs);
    child.stdout.on("data", (b: Buffer) => { outLen += b.length; if (outLen <= maxBytes) out.push(b); });
    child.stderr.on("data", (b: Buffer) => { errLen += b.length; if (errLen <= 1024 * 1024) err.push(b); });
    child.on("error", (e: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      const status: ExecStatus = e.code === "ENOENT" ? "missing_tool" : "error";
      finish({ status, code: null, stdout: "", stderr: "", reason: `${e.name}: ${e.message}` });
    });
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      const stdout = Buffer.concat(out).toString("utf8");
      const stderr = Buffer.concat(err).toString("utf8");
      if (timedOut) return finish({ status: "timeout", code, stdout, stderr, reason: `TimeoutError: ${opts.timeoutMs}ms 안에 끝나지 않아 종료했다 (${cmd})` });
      if (outLen > maxBytes) return finish({ status: "error", code, stdout, stderr, reason: `OutputTooLarge: 표준출력 ${outLen}바이트 > 상한 ${maxBytes}` });
      if (code !== 0) return finish({ status: "error", code, stdout, stderr, reason: `ExitError: ${cmd} 종료 코드 ${code}${signal ? ` (신호 ${signal})` : ""}` });
      finish({ status: "ok", code, stdout, stderr });
    });
  });
