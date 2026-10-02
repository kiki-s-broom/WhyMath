/* Windows 프로그램 실행 형식 (HARN-208) — 첫 실행 저장소 찾기 · 저장소 판정 · 창 자리 기억 */
import { promises as fs, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ANCESTOR_DEPTH, discoverWorkspace, workspaceCandidates } from "../../src/main/discover";
import { SettingsStore } from "../../src/main/store/settings";
import { MIN_SIZE, WindowStateStore, fitBounds } from "../../src/main/store/windowState";

let tmp: string;
beforeEach(async () => { tmp = await fs.mkdtemp(path.join(os.tmpdir(), "wg-launch-")); });
afterEach(async () => { await fs.rm(tmp, { recursive: true, force: true }); });

async function mkRepo(name: string, kind: "harness" | "git" | "none"): Promise<string> {
  const root = path.join(tmp, name);
  await fs.mkdir(root, { recursive: true });
  if (kind === "harness") {
    await fs.mkdir(path.join(root, "scripts", "harness"), { recursive: true });
    await fs.writeFile(path.join(root, "scripts", "harness", "work_graph.py"), "# stub\n");
  }
  if (kind === "git") await fs.mkdir(path.join(root, ".git"), { recursive: true });
  return root;
}

describe("workspaceCandidates — 찾아볼 자리의 순서", () => {
  it("무설치 EXE 위치 → 앱 코드 위치의 조상 → 실제 바탕화면\\__AI\\WhyMath → 홈\\Desktop\\__AI\\WhyMath → 홈\\WhyMath", () => {
    const c = workspaceCandidates({
      env: { PORTABLE_EXECUTABLE_DIR: "/p/q" }, platform: "linux", home: "/h",
      desktop: "/h/OneDrive/바탕 화면", appDir: "/r/tools/app",
    });
    expect(c).toEqual([
      "/p/q", "/p", "/",
      "/r/tools/app", "/r/tools", "/r",
      "/h/OneDrive/바탕 화면/__AI/WhyMath", "/h/Desktop/__AI/WhyMath", "/h/WhyMath",
    ]);
  });
  it("앱 조상은 ANCESTOR_DEPTH 단계까지만 올라간다", () => {
    const deep = "/a/b/c/d/e/f/g";
    const c = workspaceCandidates({ env: {}, platform: "linux", home: "/h", appDir: deep });
    expect(c.slice(0, ANCESTOR_DEPTH + 1)).toEqual(["/a/b/c/d/e/f/g", "/a/b/c/d/e/f", "/a/b/c/d/e", "/a/b/c/d", "/a/b/c"]);
    expect(c).not.toContain("/a/b");
  });
  it("같은 폴더는 한 번만 — 실제 바탕화면이 홈\\Desktop과 같으면 중복 없음", () => {
    const c = workspaceCandidates({ env: {}, platform: "linux", home: "/h", desktop: "/h/Desktop", appDir: "/x" });
    expect(c.filter((p) => p === "/h/Desktop/__AI/WhyMath")).toHaveLength(1);
  });
  it("Windows는 대소문자만 다른 경로를 같은 폴더로 본다", () => {
    const c = workspaceCandidates({ env: {}, platform: "win32", home: "C:\\Users\\kiki", desktop: "C:\\USERS\\KIKI\\Desktop", appDir: "C:\\x" });
    expect(c.filter((p) => p.toLowerCase().endsWith("desktop\\__ai\\whymath"))).toHaveLength(1);
  });
  it("무설치 EXE가 아니면(PORTABLE_EXECUTABLE_DIR 없음) 앱 코드 위치부터", () => {
    const c = workspaceCandidates({ env: {}, platform: "linux", home: "/h", appDir: "/r" });
    expect(c[0]).toBe("/r");
  });
});

describe("discoverWorkspace — 처음으로 WhyMath 저장소인 곳", () => {
  it("git 전용·없는 폴더는 건너뛰고 사유를 남긴다 · 처음 harness를 고른다", async () => {
    const git = await mkRepo("git-only", "git");
    const none = path.join(tmp, "absent");
    const h1 = await mkRepo("h1", "harness");
    const h2 = await mkRepo("h2", "harness");
    const r = await discoverWorkspace([git, none, h1, h2]);
    expect(r.found).toBe(h1);
    expect(r.tried.map((t) => t.path)).toEqual([git, none]);
    expect(r.tried[0].reason).toMatch(/git 저장소지만.*work_graph\.py/);
    expect(r.tried[1].reason).toMatch(/폴더가 없다/);
  });
  it("못 찾으면 found=null + 찾아본 자리 전부(빈 결과로 위장하지 않는다)", async () => {
    const plain = await mkRepo("plain", "none");
    const r = await discoverWorkspace([plain, path.join(tmp, "x")]);
    expect(r.found).toBeNull();
    expect(r.tried).toHaveLength(2);
    expect(r.tried[0].reason).toMatch(/work_graph\.py/);
  });
});

describe("SettingsStore.add requireHarness — 첫 화면에서 고른 폴더", () => {
  it("git 전용 폴더는 거부하고 사유를 준다 · 레지스트리는 비어 있다", async () => {
    const s = new SettingsStore(path.join(tmp, "ud"));
    const r = await s.add({ path: await mkRepo("g", "git"), requireHarness: true });
    expect(r.ok).toBe(false);
    expect((r as { reason: string }).reason).toMatch(/WhyMath 저장소가 아니다.*work_graph\.py/);
    expect(await s.list()).toEqual([]);
  });
  it("WhyMath 저장소는 받는다", async () => {
    const s = new SettingsStore(path.join(tmp, "ud"));
    const r = await s.add({ path: await mkRepo("h", "harness"), requireHarness: true });
    expect(r.ok).toBe(true);
    expect(await s.list()).toHaveLength(1);
  });
  it("requireHarness 없이는 종전대로 git 전용도 받는다", async () => {
    const s = new SettingsStore(path.join(tmp, "ud"));
    expect((await s.add({ path: await mkRepo("g2", "git") })).ok).toBe(true);
  });
});

describe("fitBounds — 저장된 창 자리를 쓸 수 있는가", () => {
  const screen = [{ x: 0, y: 0, width: 1920, height: 1040 }];
  it("화면 안이면 그대로", () => {
    expect(fitBounds({ x: 100, y: 80, width: 1200, height: 800 }, screen)).toEqual({ x: 100, y: 80, width: 1200, height: 800 });
  });
  it("모니터를 뺐다 — 제목 막대가 어느 화면에도 없으면 버린다(보이지 않는 창 방지)", () => {
    expect(fitBounds({ x: 2400, y: 100, width: 1200, height: 800 }, screen)).toBeNull();
    expect(fitBounds({ x: 100, y: -900, width: 1200, height: 800 }, screen)).toBeNull();
  });
  it("두 번째 모니터 위 자리는 그 모니터가 있으면 쓴다", () => {
    const two = [...screen, { x: 1920, y: 0, width: 2560, height: 1400 }];
    expect(fitBounds({ x: 2400, y: 100, width: 1200, height: 800 }, two)?.x).toBe(2400);
  });
  it("최소 크기 미만은 올리고 화면보다 크면 줄인다", () => {
    expect(fitBounds({ x: 0, y: 0, width: 200, height: 100 }, screen)).toMatchObject(MIN_SIZE);
    expect(fitBounds({ x: 0, y: 0, width: 5000, height: 3000 }, screen)).toEqual({ x: 0, y: 0, width: 1920, height: 1040 });
  });
  it("오른쪽으로 삐져나간 창은 화면 안으로 당긴다(제목 막대는 보이는 경우)", () => {
    expect(fitBounds({ x: 1700, y: 900, width: 1200, height: 800 }, screen)).toEqual({ x: 720, y: 240, width: 1200, height: 800 });
  });
});

describe("WindowStateStore", () => {
  it("동기 저장 → 읽기 왕복 · 임시 파일을 남기지 않는다", async () => {
    const w = new WindowStateStore(tmp);
    expect(w.saveSync({ bounds: { x: 10, y: 20, width: 1000, height: 700 }, maximized: true })).toBe(true);
    expect(await w.load()).toEqual({ bounds: { x: 10, y: 20, width: 1000, height: 700 }, maximized: true });
    expect((await fs.readdir(tmp)).filter((f) => f.endsWith(".tmp"))).toEqual([]);
    expect(JSON.parse(readFileSync(w.file, "utf8")).maximized).toBe(true);
  });
  it("없음·손상·형식 오류는 null(기본 크기로 연다) — 앱 기동을 막지 않는다", async () => {
    const w = new WindowStateStore(tmp);
    expect(await w.load()).toBeNull();
    writeFileSync(w.file, "{깨진");
    expect(await w.load()).toBeNull();
    writeFileSync(w.file, JSON.stringify({ bounds: { x: "a", y: 0, width: 1, height: 1 } }));
    expect(await w.load()).toBeNull();
  });
  it("쓸 수 없는 자리면 saveSync는 false(예외를 던져 창 닫기를 막지 않는다)", () => {
    const blocker = path.join(tmp, "file-not-dir");
    writeFileSync(blocker, "x");
    expect(new WindowStateStore(path.join(blocker, "sub")).saveSync({ bounds: { x: 0, y: 0, width: 1, height: 1 }, maximized: false })).toBe(false);
  });
});
