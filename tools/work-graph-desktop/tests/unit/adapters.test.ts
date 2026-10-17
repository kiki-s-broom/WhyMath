/* 어댑터 결과 정규화 — missing_tool / timeout / error 각각 실제 프로세스로 (HARN-206) */
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { runCommand, type Exec, type ExecResult } from "../../src/main/adapters/exec";
import { collectHarness } from "../../src/main/adapters/harness";
import { collectGit, countStatusLines, parseWorktrees } from "../../src/main/adapters/git";
import { collectGithub, summarizeChecks } from "../../src/main/adapters/github";
import { findPython, pythonCandidates } from "../../src/main/adapters/python";
import { collectSnapshot } from "../../src/main/collect";

let tmp: string;
beforeAll(async () => { tmp = await fs.mkdtemp(path.join(os.tmpdir(), "wg-adapters-")); });
afterAll(async () => { await fs.rm(tmp, { recursive: true, force: true }); });

const opts = { remote: false, github: false };

describe("runCommand", () => {
  it("없는 도구 → missing_tool + 예외 타입명", async () => {
    const r = await runCommand("definitely-not-a-tool-wg206", ["--version"], { cwd: tmp, timeoutMs: 5000 });
    expect(r.status).toBe("missing_tool");
    expect(r.reason).toMatch(/^Error: .*ENOENT/);
  });
  it("타임아웃 → timeout + 사유", async () => {
    const r = await runCommand(process.execPath, ["-e", "setTimeout(()=>{}, 10000)"], { cwd: tmp, timeoutMs: 300 });
    expect(r.status).toBe("timeout");
    expect(r.reason).toMatch(/TimeoutError/);
  });
  it("비-0 종료 → error + 종료 코드 + stderr 보존", async () => {
    const r = await runCommand(process.execPath, ["-e", "console.error('경고줄'); process.exit(3)"], { cwd: tmp, timeoutMs: 5000 });
    expect(r.status).toBe("error"); expect(r.code).toBe(3);
    expect(r.reason).toMatch(/ExitError.*3/); expect(r.stderr).toContain("경고줄");
  });
  it("정상 → ok + stdout", async () => {
    const r = await runCommand(process.execPath, ["-e", "process.stdout.write('hi')"], { cwd: tmp, timeoutMs: 5000 });
    expect(r).toMatchObject({ status: "ok", code: 0, stdout: "hi" });
  });
});

/** 가짜 exec — 명령·인자 패턴별 응답 */
function fakeExec(table: (cmd: string, args: string[]) => Partial<ExecResult> | undefined): Exec & { calls: string[][] } {
  const calls: string[][] = [];
  const fn = (async (cmd: string, args: string[]) => {
    calls.push([cmd, ...args]);
    const r = table(cmd, args);
    if (!r) return { status: "missing_tool" as const, code: null, stdout: "", stderr: "", reason: "Error: spawn ENOENT" };
    return { status: "ok" as const, code: 0, stdout: "", stderr: "", ...r };
  }) as unknown as Exec & { calls: string[][] };
  fn.calls = calls;
  return fn;
}

describe("python 탐색", () => {
  it("후보 순서: 지정 → 저장소 .venv → src/backend/.venv → python3 → python → (win32) py -3", () => {
    expect(pythonCandidates("C:/x/python.exe", "win32", "C:\\repo").map((c) => [c.cmd, ...c.prefix].join(" ")))
      .toEqual(["C:/x/python.exe", "C:\\repo\\.venv\\Scripts\\python.exe", "C:\\repo\\src\\backend\\.venv\\Scripts\\python.exe",
        "python3", "python", "py -3"]);
    expect(pythonCandidates(undefined, "linux", "/repo").map((c) => c.cmd))
      .toEqual(["/repo/.venv/bin/python", "/repo/src/backend/.venv/bin/python", "python3", "python"]);
    expect(pythonCandidates(undefined, "linux").map((c) => c.cmd)).toEqual(["python3", "python"]);
  });
  it("--version이 아니라 yaml 임포트로 찌른다 — 하네스를 돌릴 수 있는 인터프리터만 고른다", async () => {
    const ex = fakeExec((cmd) => (cmd === "python" ? { stdout: "" } : undefined));
    await findPython(ex, "/repo", undefined, "linux");
    expect(ex.calls.every((c) => c[1] === "-c" && c[2] === "import yaml")).toBe(true);
  });
  it("처음 되는 후보를 고르고, 없으면 시도 목록을 돌려준다 · 있지만 못 돌린 것은 사유를 붙인다", async () => {
    const venv = "/repo/.venv/bin/python";
    // 저장소 .venv는 실행되지만 yaml이 없다(exit 1) → 건너뛰고 python을 고른다
    const ex = fakeExec((cmd) => (cmd === "python" ? { stdout: "" }
      : cmd === venv ? { status: "error", code: 1, reason: "ExitError: 1" } : undefined));
    const r = await findPython(ex, "/repo", undefined, "linux");
    expect(r.found?.cmd).toBe("python");
    expect(r.tried).toEqual([`${venv}(실행됐지만 yaml 임포트 실패)`, "/repo/src/backend/.venv/bin/python", "python3", "python"]);
    const none = await findPython(fakeExec(() => undefined), "C:\\repo", undefined, "win32");
    expect(none.found).toBeNull();
    expect(none.tried.slice(-3)).toEqual(["python3", "python", "py -3"]);
  });
});

describe("harnessAdapter", () => {
  const payload = { generated: "2026-09-29", nodes: { "t:A": { key: "t:A" } }, edges: [], frames: [], counts: {}, scans: {}, errors: [] };
  it("파이썬 없음 → missing_tool (빈 페이로드로 위장하지 않는다)", async () => {
    const r = await collectHarness(tmp, opts, fakeExec(() => undefined), "linux");
    expect(r.payload).toBeNull(); expect(r.result.status).toBe("missing_tool"); expect(r.result.reason).toMatch(/python3, python/);
  });
  it("정상 → 페이로드 그대로 + --no-remote 전달 + stderr는 warnings", async () => {
    const ex = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { stdout: JSON.stringify(payload), stderr: "경고 1\n경고 2\n" });
    const r = await collectHarness(tmp, opts, ex, "linux");
    expect(r.result.status).toBe("ok"); expect(r.payload).toEqual(payload);
    expect(r.result.warnings).toEqual(["경고 1", "경고 2"]);
    expect(ex.calls.at(-1)).toEqual(["python3", "scripts/harness/work_graph.py", "--json", "--no-remote"]);
    const ex2 = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { stdout: JSON.stringify(payload) });
    await collectHarness(tmp, { ...opts, remote: true }, ex2, "linux");
    expect(ex2.calls.at(-1)).toEqual(["python3", "scripts/harness/work_graph.py", "--json"]);
  });
  it("타임아웃·오류·깨진 JSON은 각각 status로 남는다", async () => {
    const to = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { status: "timeout", code: null, reason: "TimeoutError: 120000ms" });
    expect((await collectHarness(tmp, opts, to, "linux")).result).toMatchObject({ status: "timeout", reason: /TimeoutError/ });
    const er = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { status: "error", code: 1, stderr: "Traceback", reason: "ExitError: python3 종료 코드 1" });
    const e = await collectHarness(tmp, opts, er, "linux");
    expect(e.result.status).toBe("error"); expect(e.result.warnings).toEqual(["Traceback"]); expect(e.payload).toBeNull();
    const bad = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { stdout: "not json" });
    expect((await collectHarness(tmp, opts, bad, "linux")).result).toMatchObject({ status: "error", reason: /SyntaxError/ });
    const schema = fakeExec((cmd, args) => args[0] === "-c" ? (cmd === "python3" ? {} : undefined) : { stdout: "{}" });
    expect((await collectHarness(tmp, opts, schema, "linux")).result).toMatchObject({ status: "error", reason: /SchemaError/ });
  });
});

describe("gitAdapter", () => {
  it("worktree porcelain·status 파싱", () => {
    expect(parseWorktrees("worktree /a\nHEAD abc\nbranch refs/heads/main\n\nworktree /b\nHEAD def\ndetached\n"))
      .toEqual([{ path: "/a", head: "abc", branch: "main" }, { path: "/b", head: "def" }]);
    expect(countStatusLines(" M a.py\n?? b\n\n")).toBe(2);
  });
  it("git 없음 → missing_tool", async () => {
    expect(await collectGit(tmp, fakeExec(() => undefined))).toMatchObject({ status: "missing_tool", tool: "git" });
  });
  it("기준 브랜치를 못 찾으면 ahead=undeterminable + 사유", async () => {
    const ex = fakeExec((cmd, args) => {
      if (args[0] === "rev-parse" && args[1] === "--verify") return { status: "error", code: 1, reason: "ExitError: git 종료 코드 1" };
      if (args[0] === "rev-parse" && args[1] === "--is-inside-work-tree") return { stdout: "true\n" };
      if (args[0] === "rev-parse") return { stdout: "feature\n" };
      if (args[0] === "status") return { stdout: " M x\n" };
      if (args[0] === "worktree") return { stdout: "worktree /r\nHEAD 1\nbranch refs/heads/feature\n" };
      return {};
    });
    const r = await collectGit("/r", ex);
    expect(r.status).toBe("ok");
    expect(r.data).toMatchObject({ branch: "feature", changedFiles: 1, ahead: "undeterminable" });
    expect(r.data?.aheadReason).toMatch(/origin\/main, origin\/master, main/);
  });
  it("실제 git 저장소에서 ok (이 저장소)", async () => {
    const r = await collectGit(path.resolve(__dirname, "../../../.."), runCommand);
    expect(r.status).toBe("ok"); expect(typeof r.data?.branch).toBe("string");
  });
});

describe("githubAdapter", () => {
  it("꺼져 있으면 skipped + 사유", async () => {
    expect(await collectGithub(tmp, false, fakeExec(() => undefined))).toMatchObject({ status: "skipped", reason: /꺼져/ });
  });
  it("gh 없음 → missing_tool · 인증 실패 → error + stderr 첫 줄", async () => {
    expect(await collectGithub(tmp, true, fakeExec(() => undefined))).toMatchObject({ status: "missing_tool", tool: "gh" });
    const auth = fakeExec(() => ({ status: "error", code: 4, stderr: "To get started with GitHub CLI, please run: gh auth login", reason: "ExitError: gh 종료 코드 4" }));
    const r = await collectGithub(tmp, true, auth);
    expect(r.status).toBe("error"); expect(r.reason).toMatch(/gh auth login/);
  });
  it("정상 → PR 사실 목록(판정 없음)", async () => {
    const ex = fakeExec(() => ({ stdout: JSON.stringify([{ number: 7, title: "t", url: "https://x/pull/7", headRefName: "claude/b", isDraft: false, reviewDecision: "", statusCheckRollup: [{ conclusion: "SUCCESS" }, { state: "PENDING" }] }]) }));
    const r = await collectGithub(tmp, true, ex);
    expect(r.status).toBe("ok"); expect(r.data?.[0]).toMatchObject({ number: 7, headRefName: "claude/b", checks: "통과 1 · 실패 0 · 진행 1" });
    expect(summarizeChecks([])).toBeUndefined();
  });
});

describe("collectSnapshot", () => {
  it("어댑터 실패가 sources에 그대로 남고 페이로드는 null", async () => {
    const ws = { id: "ws_000000000001", name: "x", root: tmp, kind: "harness" as const, options: { remote: false, github: true } };
    const snap = await collectSnapshot(ws, fakeExec(() => undefined), "linux");
    expect(snap.sources.harness.status).toBe("missing_tool");
    expect(snap.sources.git.status).toBe("missing_tool");
    expect(snap.sources.github.status).toBe("missing_tool");
    expect(snap.payload).toBeNull();
    expect(snap.stale).toBe(false);
    expect(Date.parse(snap.collectedAt)).not.toBeNaN();
  });
  it("git 전용 작업공간은 하네스를 skipped로 표시한다(빈 그래프로 위장 안 함)", async () => {
    const ws = { id: "ws_000000000002", name: "x", root: tmp, kind: "git" as const, options: { remote: false, github: false } };
    const snap = await collectSnapshot(ws, fakeExec(() => ({ stdout: "true\n" })), "linux");
    expect(snap.sources.harness).toMatchObject({ status: "skipped", reason: /work_graph\.py/ });
  });
});
