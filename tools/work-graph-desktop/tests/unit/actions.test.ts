/* runAction 인자 조립 — 허용 인자만·셸 미경유·--as 규칙 (HARN-206) */
import { describe, expect, it } from "vitest";
import { buildActionArgs, runAction } from "../../src/main/actions";
import type { Exec } from "../../src/main/adapters/exec";
import type { ActionRequest } from "../../src/shared/types";

const req = (kind: ActionRequest["kind"], args: ActionRequest["args"]): ActionRequest => ({ workspaceId: "ws_000000000001", kind, args });
const CLI = "scripts/harness/backlog.py";

describe("buildActionArgs", () => {
  it("start — id만", () => {
    expect(buildActionArgs(req("start", { id: "HARN-206-work-graph-desktop-app" }))).toEqual({ ok: true, args: [CLI, "start", "HARN-206-work-graph-desktop-app"] });
  });
  it("gates_clear — --as는 담당자가 claude가 아닐 때만, --evidence 필수, --no-base 선택", () => {
    expect(buildActionArgs(req("gates_clear", { id: "G-x", evidence: "PR #12", assignee: "kiki" })))
      .toEqual({ ok: true, args: [CLI, "gates", "clear", "G-x", "--as", "kiki", "--evidence", "PR #12"] });
    expect(buildActionArgs(req("gates_clear", { id: "G-x", evidence: "abc1234", assignee: "claude" })))
      .toEqual({ ok: true, args: [CLI, "gates", "clear", "G-x", "--evidence", "abc1234"] });
    expect(buildActionArgs(req("gates_clear", { id: "G-x", evidence: "환경 생성", assignee: "kiki", noBase: "커밋과 무관" })))
      .toEqual({ ok: true, args: [CLI, "gates", "clear", "G-x", "--as", "kiki", "--evidence", "환경 생성", "--no-base", "커밋과 무관"] });
    expect(buildActionArgs(req("gates_clear", { id: "G-x", assignee: "kiki" }))).toMatchObject({ ok: false, reason: /근거/ });
    expect(buildActionArgs(req("gates_clear", { id: "G-x", evidence: "x", assignee: "root" }))).toMatchObject({ ok: false, reason: /--as/ });
  });
  it("done — --artifact 하나 이상", () => {
    expect(buildActionArgs(req("done", { id: "T-1", artifacts: ["PR #3", "커밋 abc"] }))).toEqual({ ok: true, args: [CLI, "done", "T-1", "--artifact", "PR #3", "--artifact", "커밋 abc"] });
    expect(buildActionArgs(req("done", { id: "T-1", artifacts: [] }))).toMatchObject({ ok: false, reason: /증적/ });
  });
  it("거부 — ID 형식·플래그 주입·줄바꿈·허용되지 않은 동작", () => {
    expect(buildActionArgs(req("start", { id: "../x" }))).toMatchObject({ ok: false });
    expect(buildActionArgs(req("start", { id: "T-1; rm -rf /" }))).toMatchObject({ ok: false });
    expect(buildActionArgs(req("gates_clear", { id: "G", evidence: "--no-remote", assignee: "kiki" }))).toMatchObject({ ok: false, reason: /'-'/ });
    expect(buildActionArgs(req("done", { id: "T", artifacts: ["a\nb"] }))).toMatchObject({ ok: false, reason: /줄바꿈/ });
    expect(buildActionArgs({ workspaceId: "ws_000000000001", kind: "amend" as unknown as "start", args: { id: "T" } })).toMatchObject({ ok: false, reason: /허용되지 않은/ });
  });
});

describe("runAction", () => {
  it("인자를 배열 그대로 spawn에 넘기고(셸 미경유) 결과를 그대로 돌려준다", async () => {
    const calls: { cmd: string; args: string[]; cwd: string }[] = [];
    const exec: Exec = async (cmd, args, o) => {
      calls.push({ cmd, args, cwd: o.cwd });
      if (args[0] === "--version") return { status: "ok", code: 0, stdout: "Python 3.12", stderr: "" };
      return { status: "error", code: 1, stdout: "대장 거부", stderr: "exit 1", reason: "ExitError: python3 종료 코드 1" };
    };
    const r = await runAction(req("gates_clear", { id: "G-1", evidence: "PR #9 $(echo x) `id`", assignee: "kiki" }), "/repo", { remote: false, github: false }, exec, "linux");
    expect(calls[1]).toEqual({ cmd: "python3", args: [CLI, "gates", "clear", "G-1", "--as", "kiki", "--evidence", "PR #9 $(echo x) `id`"], cwd: "/repo" });
    expect(r).toEqual({ ok: false, exitCode: 1, stdout: "대장 거부", stderr: "exit 1", command: ["python3", CLI, "gates", "clear", "G-1", "--as", "kiki", "--evidence", "PR #9 $(echo x) `id`"], reason: "ExitError: python3 종료 코드 1" });
  });
  it("파이썬 없음 → 실행하지 않고 사유", async () => {
    const exec: Exec = async () => ({ status: "missing_tool", code: null, stdout: "", stderr: "", reason: "Error: ENOENT" });
    const r = await runAction(req("start", { id: "T-1" }), "/repo", { remote: false, github: false }, exec, "win32");
    expect(r.ok).toBe(false); expect(r.exitCode).toBeNull(); expect(r.reason).toMatch(/python3, python, py -3/);
  });
  it("거부된 인자는 exec를 부르지 않는다", async () => {
    let called = 0;
    const exec: Exec = async () => { called++; return { status: "ok", code: 0, stdout: "", stderr: "" }; };
    const r = await runAction(req("done", { id: "T", artifacts: [] }), "/repo", { remote: false, github: false }, exec);
    expect(called).toBe(0); expect(r.ok).toBe(false);
  });
});
