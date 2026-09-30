/* Electron 스모크 (HARN-206) — 실제 앱을 띄운다. 실행: npm run e2e:electron (xvfb-run 경유).
   WORK_GRAPH_WORKSPACE로 저장소를 자동 등록하고, 새로고침(--no-remote)으로 수집해 창 수 > 0을 확인한다. */
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../..");
const WORKSPACE = process.env.WORK_GRAPH_WORKSPACE ?? path.resolve(ROOT, "../..");

test("앱 기동 → 작업공간 자동 등록 → 수집 → 창 수 > 0 · 스냅샷 저장", async () => {
  test.setTimeout(180_000);
  const userData = mkdtempSync(path.join(os.tmpdir(), "wg-electron-"));
  const app = await electron.launch({
    args: [ROOT, "--no-sandbox"],   // 컨테이너(root)에서 Chromium 샌드박스가 불가해 테스트에서만 끈다
    env: { ...process.env, WORK_GRAPH_WORKSPACE: WORKSPACE, WORK_GRAPH_USER_DATA: userData },
  });
  try {
    const win = await app.firstWindow();
    await win.waitForLoadState("domcontentloaded");
    await expect.poll(() => win.title()).toBe("WhyMath 작업 지도");
    await expect(win.locator("#mode")).toHaveText("Electron");
    const prefs = await app.evaluate(({ BrowserWindow }) => {
      const w = BrowserWindow.getAllWindows()[0];
      const p = w.webContents.getLastWebPreferences?.() ?? {};
      return { contextIsolation: p.contextIsolation, sandbox: p.sandbox, nodeIntegration: p.nodeIntegration };
    });
    expect(prefs).toEqual({ contextIsolation: true, sandbox: true, nodeIntegration: false });
    await expect(win.locator("#ws-list .ws")).toHaveCount(1);
    await expect(win.locator("#ws-list .ws .nm")).toHaveText(path.basename(WORKSPACE));
    await expect(win.locator("#snap-line")).toContainText("저장된 스냅샷 없음");
    await win.locator("#refresh").click();
    await expect(win.locator("#refresh")).toHaveText("새로고침", { timeout: 150_000 });
    await expect(win.locator("#snap-line")).toContainText("work_graph.py ok");
    await expect(win.locator("#snap-line")).toContainText("git ok");
    const wins = await win.locator(".win").count();
    expect(wins).toBeGreaterThan(0);
    const value = await win.getByTestId("card-ready-value").textContent();
    expect(Number(value)).toBeGreaterThan(0);
    // --no-remote이므로 원격 조회 3종은 skipped → 확인 필요에 나열된다(은폐 없음)
    await expect(win.getByTestId("card-attention-value")).toHaveText("3");
    // 스냅샷·설정 파일이 userData에 원자적으로 남는다
    expect(await app.evaluate(({ app: a }) => a.getPath("userData"))).toBe(userData);
    expect(existsSync(path.join(userData, "settings.json"))).toBe(true);
    const snapshots = readdirSync(path.join(userData, "snapshots"));
    expect(snapshots).toHaveLength(1);
    expect(snapshots[0]).toMatch(/^ws_[0-9a-f]{12}\.json$/);
    const saved = JSON.parse(readFileSync(path.join(userData, "snapshots", snapshots[0]), "utf8"));
    expect(Object.keys(saved.payload.nodes).length).toBe(wins);   // 저장된 페이로드의 창 수 = 화면 창 수
  } finally {
    await app.close();
    rmSync(userData, { recursive: true, force: true });
  }
});
