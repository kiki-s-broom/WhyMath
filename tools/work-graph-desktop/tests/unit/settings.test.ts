/* 작업공간 레지스트리 — 원자 저장·복원·종류 판정 (HARN-206) */
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SettingsStore, detectKind } from "../../src/main/store/settings";

let tmp: string;
beforeEach(async () => { tmp = await fs.mkdtemp(path.join(os.tmpdir(), "wg-settings-")); });
afterEach(async () => { await fs.rm(tmp, { recursive: true, force: true }); });

async function mkRepo(kind: "harness" | "git" | "none"): Promise<string> {
  const root = path.join(tmp, "repo-" + kind);
  await fs.mkdir(root, { recursive: true });
  if (kind === "harness") { await fs.mkdir(path.join(root, "scripts", "harness"), { recursive: true }); await fs.writeFile(path.join(root, "scripts", "harness", "work_graph.py"), "# stub\n"); }
  if (kind === "git") await fs.mkdir(path.join(root, ".git"), { recursive: true });
  return root;
}

describe("detectKind", () => {
  it("work_graph.py가 있으면 harness", async () => { expect(await detectKind(await mkRepo("harness"))).toEqual({ kind: "harness" }); });
  it(".git만 있으면 git", async () => { expect(await detectKind(await mkRepo("git"))).toEqual({ kind: "git" }); });
  it("둘 다 없으면 거부 사유", async () => {
    const r = await detectKind(await mkRepo("none"));
    expect(r.kind).toBeNull(); expect((r as { reason: string }).reason).toMatch(/work_graph\.py/);
  });
  it("없는 폴더는 거부", async () => { const r = await detectKind(path.join(tmp, "nope")); expect(r.kind).toBeNull(); });
});

describe("SettingsStore", () => {
  it("추가 → 파일에 원자 저장 → 새 인스턴스에서 복원", async () => {
    const dir = path.join(tmp, "userData");
    const s = new SettingsStore(dir);
    const root = await mkRepo("harness");
    const r = await s.add({ path: root, name: "  ", options: { github: true } });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.workspace.kind).toBe("harness");
    expect(r.workspace.name).toBe(path.basename(root));   // 빈 이름 → 폴더 이름
    expect(r.workspace.options).toEqual({ remote: true, github: true, source: "trunk" });
    expect(r.workspace.id).toMatch(/^ws_[0-9a-f]{12}$/);
    const files = await fs.readdir(dir);
    expect(files).toEqual(["settings.json"]);              // 임시 파일이 남지 않는다
    const again = new SettingsStore(dir);
    const list = await again.list();
    expect(list).toHaveLength(1);
    expect(list[0]).toEqual(r.workspace);
  });
  it("같은 root를 다시 추가하면 기존 항목을 돌려준다(중복 없음)", async () => {
    const s = new SettingsStore(path.join(tmp, "ud"));
    const root = await mkRepo("git");
    const a = await s.add({ path: root }); const b = await s.add({ path: root + path.sep });
    expect(a.ok && b.ok && a.workspace.id === b.workspace.id).toBe(true);
    expect(await s.list()).toHaveLength(1);
  });
  it("거부된 폴더는 저장하지 않는다", async () => {
    const dir = path.join(tmp, "ud2");
    const s = new SettingsStore(dir);
    const r = await s.add({ path: await mkRepo("none") });
    expect(r.ok).toBe(false);
    await expect(fs.access(path.join(dir, "settings.json"))).rejects.toThrow();
  });
  it("update·remove", async () => {
    const s = new SettingsStore(path.join(tmp, "ud3"));
    const r = await s.add({ path: await mkRepo("harness") });
    if (!r.ok) throw new Error("add 실패");
    const u = await s.update(r.workspace.id, { name: "이름", options: { remote: true, python: "C:\\py\\python.exe" } });
    expect(u?.name).toBe("이름"); expect(u?.options).toEqual({ remote: true, github: false, source: "trunk", python: "C:\\py\\python.exe" });
    expect(await s.update("ws_000000000000", { name: "x" })).toBeNull();
    expect(await s.remove(r.workspace.id)).toBe(true);
    expect(await s.remove(r.workspace.id)).toBe(false);
    expect(await s.list()).toEqual([]);
  });
  it("손상된 settings.json은 조용히 빈 목록으로 접지 않고 예외 타입명을 붙여 던진다", async () => {
    const dir = path.join(tmp, "ud4");
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, "settings.json"), "{ 깨진 json");
    await expect(new SettingsStore(dir).list()).rejects.toThrow(/SyntaxError/);
  });
});
