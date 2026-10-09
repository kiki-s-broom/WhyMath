/* 새로고침이 최신 main을 그린다 (HARN-306) — 진짜 git 원격 픽스처.
   사고(2026-10-09): Kiki 작업 사본이 낡은 브랜치에 있어 새로고침해도 그래프가 바뀌지 않았다.
   여기서는 작업 사본을 일부러 낡은 브랜치 + 미커밋 변경 상태로 두고, 원격에 새 태스크를 올린 뒤
   새로고침하면 그래프가 바뀌는지, 그리고 작업 사본은 그대로인지 본다. */
import { execFileSync } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { runCommand } from "../../src/main/adapters/exec";
import { prepareTrunk, samePath } from "../../src/main/adapters/trunk";
import { collectSnapshot } from "../../src/main/collect";
import { DEFAULT_OPTIONS, migrateOptions } from "../../src/main/store/settings";
import type { Workspace } from "../../src/shared/types";

// 가짜 work_graph.py — 자기가 돌고 있는 트리의 backlog/tasks/*.yaml 이름을 창으로 낸다
const STUB = `import json, pathlib, subprocess
root = pathlib.Path.cwd()
names = sorted(p.stem for p in (root / "backlog" / "tasks").glob("*.yaml"))
base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print(json.dumps({"base": base, "nodes": {"t:" + n: {"key": "t:" + n} for n in names}, "edges": []}))
`;

let tmp: string;
const git = (cwd: string, ...args: string[]) =>
  execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", ...args], { cwd, encoding: "utf8" }).trim();

async function addTask(repo: string, name: string): Promise<void> {
  await fs.writeFile(path.join(repo, "backlog", "tasks", `${name}.yaml`), `id: ${name}\n`);
  git(repo, "add", "-A"); git(repo, "commit", "-qm", `add ${name}`); git(repo, "push", "-q", "origin", "main");
}

let origin: string, seed: string, work: string, mirror: string;
beforeEach(async () => {
  tmp = await fs.mkdtemp(path.join(os.tmpdir(), "wg-trunk-"));
  origin = path.join(tmp, "origin.git"); seed = path.join(tmp, "seed"); work = path.join(tmp, "work");
  mirror = path.join(tmp, "userData", "trunk", "ws_000000000306");
  git(tmp, "init", "-q", "--bare", origin);
  git(tmp, "clone", "-q", origin, seed);
  await fs.mkdir(path.join(seed, "backlog", "tasks"), { recursive: true });
  await fs.mkdir(path.join(seed, "scripts", "harness"), { recursive: true });
  await fs.writeFile(path.join(seed, "scripts", "harness", "work_graph.py"), STUB);
  git(seed, "checkout", "-qb", "main");
  await addTask(seed, "A");
  git(tmp, "clone", "-q", origin, work);
  // 공유 작업 사본 재현 — 다른 세션이 남긴 낡은 브랜치 + 미커밋 변경
  git(work, "checkout", "-qb", "old-session-branch");
  await fs.writeFile(path.join(work, "backlog", "tasks", "A.yaml"), "id: A\n# 미커밋 편집\n");
});
afterEach(async () => { await fs.rm(tmp, { recursive: true, force: true }); });

const ws = (source?: "trunk" | "worktree"): Workspace => ({
  id: "ws_000000000306", name: "w", root: work, kind: "harness",
  options: { ...DEFAULT_OPTIONS, remote: false, ...(source ? { source } : {}) },
});
const names = (snap: Awaited<ReturnType<typeof collectSnapshot>>) => Object.keys(snap.payload?.nodes ?? {}).sort();

describe("새로고침 = 최신 main", () => {
  it("원격에 새 태스크가 올라오면 다음 새로고침이 그것을 그린다 · 작업 사본은 그대로", async () => {
    const statusBefore = git(work, "status", "--porcelain"); const headBefore = git(work, "rev-parse", "HEAD");
    const s1 = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    expect(s1.sources.harness.status).toBe("ok");
    expect(names(s1)).toEqual(["t:A"]);
    expect(s1.sources.trunk).toMatchObject({ status: "ok", data: { ref: "origin/main", fetched: true } });

    await addTask(seed, "B");   // 다른 세션이 main에 머지한 것과 같다
    const s2 = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    expect(names(s2)).toEqual(["t:A", "t:B"]);
    expect(s2.sources.trunk?.data?.sha).toBe(git(seed, "rev-parse", "HEAD"));
    expect(s2.payload?.base).toBe(git(seed, "rev-parse", "HEAD"));   // 그래프를 그린 트리가 정말 그 커밋이다

    // 원 작업 사본: 브랜치·HEAD·미커밋 변경 전부 그대로
    expect(git(work, "rev-parse", "--abbrev-ref", "HEAD")).toBe("old-session-branch");
    expect(git(work, "rev-parse", "HEAD")).toBe(headBefore);
    expect(git(work, "status", "--porcelain")).toBe(statusBefore);
    // 앱이 만든 거울은 작업 사본 목록에 끼지 않는다
    expect(s2.sources.git.data?.worktrees.some((w) => samePath(w.path, mirror))).toBe(false);
    expect(s2.sources.git.data?.branch).toBe("old-session-branch");
  });

  it("대조군 — 작업 트리 모드는 원격의 새 태스크를 보지 못한다(옛 동작이 실제로 결함이었다)", async () => {
    await addTask(seed, "B");
    const s = await collectSnapshot(ws("worktree"), runCommand, process.platform, mirror);
    expect(names(s)).toEqual(["t:A"]);
    expect(s.sources.trunk?.status).toBe("skipped");
  });

  it("원격을 못 받으면 마지막으로 받은 main으로 그리되 받지 못했다고 말한다", async () => {
    const s1 = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    git(work, "remote", "set-url", "origin", path.join(tmp, "no-such-remote.git"));
    const s2 = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    expect(s2.sources.trunk).toMatchObject({ status: "ok", data: { fetched: false, sha: s1.sources.trunk?.data?.sha } });
    expect(s2.sources.trunk?.data?.fetchReason).toMatch(/ExitError/);
    expect(s2.sources.trunk?.warnings?.join("\n")).toMatch(/git fetch 실패/);
    expect(names(s2)).toEqual(["t:A"]);
  });

  it("거울 폴더가 지워졌거나 등록만 남아도 다시 만든다", async () => {
    await collectSnapshot(ws(), runCommand, process.platform, mirror);
    await fs.rm(mirror, { recursive: true, force: true });
    const s = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    expect(s.sources.trunk?.status).toBe("ok");
    expect(names(s)).toEqual(["t:A"]);
  });

  it("거울에 남은 부산물은 다음 새로고침에서 지워진다(판정에 섞이지 않는다)", async () => {
    await collectSnapshot(ws(), runCommand, process.platform, mirror);
    await fs.writeFile(path.join(mirror, "backlog", "tasks", "STRAY.yaml"), "id: STRAY\n");
    const s = await collectSnapshot(ws(), runCommand, process.platform, mirror);
    expect(names(s)).toEqual(["t:A"]);
  });

  it("거울 폴더가 저장소 안이면 거부하고 그래프를 그리지 않는다(작업 트리로 몰래 물러서지 않는다)", async () => {
    const r = await prepareTrunk(work, path.join(work, "inner"), runCommand);
    expect(r.dir).toBeNull();
    expect(r.result.reason).toMatch(/저장소 안/);
    const s = await collectSnapshot(ws(), runCommand, process.platform, path.join(work, "inner"));
    expect(s.payload).toBeNull();
    expect(s.sources.harness).toMatchObject({ status: "skipped", reason: /최신 main을 준비하지 못해/ });
  });

  it("origin/main이 없으면 오류 + 사유", async () => {
    git(work, "update-ref", "-d", "refs/remotes/origin/main");
    git(work, "remote", "set-url", "origin", path.join(tmp, "no-such-remote.git"));
    const r = await prepareTrunk(work, mirror, runCommand);
    expect(r.dir).toBeNull();
    expect(r.result).toMatchObject({ status: "error", reason: /origin\/main을 찾지 못했다/ });
  });
});

describe("저장된 설정 옮기기", () => {
  it("HARN-306 이전 항목(source 없음)은 최신 main + 원격 조회로 옮기고 python·github는 보존한다", () => {
    expect(migrateOptions({ remote: false, github: true, python: "C:\\py.exe" }))
      .toEqual({ remote: true, github: true, python: "C:\\py.exe", source: "trunk" });
    expect(migrateOptions(undefined)).toEqual({ remote: true, github: false, source: "trunk" });
  });
  it("이미 고른 설정은 그대로 둔다", () => {
    expect(migrateOptions({ remote: false, github: false, source: "worktree" })).toEqual({ remote: false, github: false, source: "worktree" });
  });
});
