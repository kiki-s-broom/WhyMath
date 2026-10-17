/* Electron 스모크 (HARN-206) — 실제 앱을 띄운다. 실행: npm run e2e:electron (xvfb-run 경유).
   WORK_GRAPH_WORKSPACE로 저장소를 자동 등록하고, 새로고침(--no-remote)으로 수집해 창 수 > 0을 확인한다. */
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../..");
const WORKSPACE = process.env.WORK_GRAPH_WORKSPACE ?? path.resolve(ROOT, "../..");
// eslint 없음 — electron 패키지를 Node에서 require하면 실행 파일 경로(문자열)가 나온다
const ELECTRON_BIN = require("electron") as unknown as string;

/** 임시 폴더 정리 — Windows는 막 끝난 앱이 파일을 잠깐 잡고 있어 재시도한다. 정리 실패는 검증이 아니므로 경고만. */
function cleanup(dir: string): void {
  try { rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); }
  catch (e) { console.warn(`[cleanup] ${(e as Error).name}: ${dir} 삭제 실패 — ${(e as Error).message}`); }
}

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
    cleanup(userData);
  }
});

/* ── Windows 프로그램 실행 형식 (HARN-208) ──
   바로가기로 켠 상황을 흉내 낸다: 작업 폴더(cwd)와 홈(HOME·USERPROFILE)을 저장소와 무관한 임시 폴더로 두고
   WORK_GRAPH_WORKSPACE 없이 띄운다. */
function shortcutEnv(userData: string, home: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (v !== undefined && k !== "WORK_GRAPH_WORKSPACE") env[k] = v;
  return { ...env, WORK_GRAPH_USER_DATA: userData, HOME: home, USERPROFILE: home };
}

async function launch(appDir: string, env: Record<string, string>, cwd: string): Promise<ElectronApplication> {
  return electron.launch({ args: [appDir, "--no-sandbox"], env, cwd });
}

test("바로가기 실행 — 환경변수 없이도 앱 위치에서 WhyMath 저장소를 찾아 자동 연결한다", async () => {
  test.setTimeout(120_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-shortcut-"));
  const app = await launch(ROOT, shortcutEnv(path.join(tmp, "ud"), tmp), tmp);
  try {
    const win = await app.firstWindow();
    await expect(win.locator("#ws-list .ws")).toHaveCount(1);
    await expect(win.locator("#ws-list .ws .nm")).toHaveText(path.basename(WORKSPACE));
    await expect(win.getByTestId("welcome")).toHaveCount(0);
    const settings = JSON.parse(readFileSync(path.join(tmp, "ud", "settings.json"), "utf8"));
    expect(settings.workspaces.map((w: { root: string }) => w.root)).toEqual([WORKSPACE]);
  } finally {
    await app.close();
    cleanup(tmp);
  }
});

test("저장소를 못 찾으면 첫 화면 → 저장소 아닌 폴더는 거부 → WhyMath 폴더를 고르면 연결·수집", async () => {
  test.setTimeout(240_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-first-"));
  // 저장소 밖에 둔 앱 사본 — 앱 위치의 조상에서도 저장소를 찾을 수 없게 한다
  const appCopy = path.join(tmp, "app");
  mkdirSync(appCopy);
  cpSync(path.join(ROOT, "package.json"), path.join(appCopy, "package.json"));
  cpSync(path.join(ROOT, "dist"), path.join(appCopy, "dist"), { recursive: true });
  const gitOnly = path.join(tmp, "git-only");
  mkdirSync(path.join(gitOnly, ".git"), { recursive: true });
  const app = await launch(appCopy, shortcutEnv(path.join(tmp, "ud"), tmp), tmp);
  try {
    const win = await app.firstWindow();
    const welcome = win.getByTestId("welcome");
    await expect(welcome).toBeVisible();
    await expect(welcome).toContainText("찾아봤지만 찾지 못했습니다");
    await win.locator("#empty details summary").click();
    await expect(win.getByTestId("welcome-tried").locator("li").first()).toBeVisible();
    // 폴더 선택 대화상자를 흉내 낸다 — 메인 프로세스의 dialog를 바꿔 끼운다(렌더러는 IPC만 부른다)
    const answer = (p: string) => app.evaluate(({ dialog }, chosen) => {
      (dialog as unknown as { showOpenDialog: () => Promise<unknown> }).showOpenDialog = async () => ({ canceled: false, filePaths: [chosen] });
    }, p);
    await answer(gitOnly);
    await win.getByTestId("welcome-pick").click();
    await expect(win.getByTestId("welcome-err")).toContainText("WhyMath 저장소가 아니다");
    await expect(win.locator("#ws-list .ws")).toHaveCount(0);
    expect(existsSync(path.join(tmp, "ud", "settings.json"))).toBe(false);   // 거부는 아무것도 저장하지 않는다
    await answer(WORKSPACE);
    await win.getByTestId("welcome-pick").click();
    await expect(win.locator("#ws-list .ws")).toHaveCount(1);
    await expect(win.getByTestId("welcome")).toHaveCount(0);
    // 연결 직후 자동으로 한 번 수집한다
    await expect(win.locator("#snap-line")).toContainText("work_graph.py ok", { timeout: 200_000 });
    expect(await win.locator(".win").count()).toBeGreaterThan(0);
  } finally {
    await app.close();
    cleanup(tmp);
  }
});

test("두 번째 실행은 새 창을 만들지 않고 곧바로 끝난다 — 켜져 있던 창이 second-instance를 받는다", async () => {
  test.setTimeout(120_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-single-"));
  const env = { ...shortcutEnv(path.join(tmp, "ud"), tmp), WORK_GRAPH_WORKSPACE: WORKSPACE };
  const app = await launch(ROOT, env, tmp);
  try {
    await app.firstWindow();
    await app.evaluate(({ app: a }) => {
      const g = globalThis as unknown as { __second: number };
      g.__second = 0;
      a.on("second-instance", () => { g.__second++; });
    });
    const second = spawnSync(ELECTRON_BIN, [ROOT, "--no-sandbox"], { env, cwd: tmp, timeout: 60_000, encoding: "utf8" });
    expect(second.error, "두 번째 프로세스가 제한 시간 안에 끝난다").toBeUndefined();
    expect(second.status).toBe(0);
    expect(await app.evaluate(() => (globalThis as unknown as { __second: number }).__second)).toBe(1);
    expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)).toBe(1);
  } finally {
    await app.close();
    cleanup(tmp);
  }
});

test("창 크기·위치를 기억한다 — 닫을 때 저장하고 다음 실행에 되돌린다", async () => {
  test.setTimeout(120_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-bounds-"));
  const env = { ...shortcutEnv(path.join(tmp, "ud"), tmp), WORK_GRAPH_WORKSPACE: WORKSPACE };
  try {
    const first = await launch(ROOT, env, tmp);
    await first.firstWindow();
    // 좌표는 실제 화면 작업 영역 안에서 정한다 — Windows CI 러너 화면은 1024×768이라 고정 좌표는 fitBounds가 당겨 온다(설계대로)
    const want = await first.evaluate(({ screen }) => {
      const a = screen.getPrimaryDisplay().workArea;
      return { x: a.x + 30, y: a.y + 30, width: Math.min(920, a.width - 60), height: Math.min(620, a.height - 60) };
    });
    await first.evaluate(({ BrowserWindow }, b) => { BrowserWindow.getAllWindows()[0].setBounds(b); }, want);
    await first.close();
    const saved = JSON.parse(readFileSync(path.join(tmp, "ud", "window.json"), "utf8"));
    expect(saved.bounds.width).toBe(want.width);
    expect(saved.bounds.height).toBe(want.height);
    const again = await launch(ROOT, env, tmp);
    try {
      await again.firstWindow();
      const b = await again.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getBounds());
      expect(b.width).toBe(want.width);
      expect(b.height).toBe(want.height);
      expect(Math.abs(b.x - want.x)).toBeLessThanOrEqual(8);
      expect(Math.abs(b.y - want.y)).toBeLessThanOrEqual(40);   // 창 관리자가 제목 막대 높이만큼 내릴 수 있다
    } finally {
      await again.close();
    }
  } finally {
    cleanup(tmp);
  }
});

test("앱 데이터는 appData\\whymath-work-graph-desktop에 모인다 — 한글 제품명이 appData 루트로 새지 않는다", async () => {
  test.setTimeout(120_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-appdata-"));
  // 홈(USERPROFILE)은 바꾸지 않는다 — Windows는 appData를 %USERPROFILE% 아래 알려진 폴더로 풀므로, 임시 홈이면
  // getPath("appData")가 예외를 던져 이 테스트가 보려는 것(실제 appData 아래 폴더 이름)을 볼 수 없다
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (v !== undefined && k !== "WORK_GRAPH_USER_DATA") env[k] = v;
  env.XDG_CONFIG_HOME = path.join(tmp, ".config");   // 리눅스 appData — Windows는 알려진 폴더 API라 env로 못 바꾼다
  env.WORK_GRAPH_WORKSPACE = WORKSPACE;
  const app = await launch(ROOT, env, tmp);
  let userData = "";
  try {
    await app.firstWindow();
    const p = await app.evaluate(({ app: a }) => ({ userData: a.getPath("userData"), appData: a.getPath("appData") }));
    userData = p.userData;
    expect(p.userData).toBe(path.join(p.appData, "whymath-work-graph-desktop"));
    await expect.poll(() => existsSync(path.join(p.userData, "settings.json"))).toBe(true);
    expect(existsSync(path.join(p.appData, "settings.json")), "appData 루트에 설정 파일이 새지 않는다").toBe(false);
  } finally {
    await app.close();
    cleanup(tmp);
    // Windows CI는 실제 %APPDATA% 아래에 만들어진다 — 러너는 일회용이지만 흔적을 지운다
    if (userData && !userData.startsWith(tmp)) cleanup(userData);
  }
});

/* 패키징된 EXE 자체를 띄운다 (HARN-208) — asar에 묶인 앱이 실제 Windows에서 뜨고, 파이썬을 찾아
   work_graph.py를 돌려 그래프를 그리는지. 컨테이너(리눅스)에서는 Windows EXE를 실행할 수 없으므로
   WG_PACKAGED_EXE가 주어질 때만 돈다 — Windows CI(.github/workflows/work-graph-desktop.yml)가 패키징 뒤에 준다. */
test("패키징된 EXE 기동 → 저장소 수집 → 창 수 > 0", async () => {
  const exe = process.env.WG_PACKAGED_EXE;
  test.skip(!exe, "WG_PACKAGED_EXE 없음 — 패키징된 Windows EXE는 Windows CI에서만 실행한다");
  test.setTimeout(240_000);
  const tmp = mkdtempSync(path.join(os.tmpdir(), "wg-packaged-"));
  const env = { ...shortcutEnv(path.join(tmp, "ud"), tmp), WORK_GRAPH_WORKSPACE: WORKSPACE };
  // 리눅스에서 테스트 논리를 확인할 때만 샌드박스를 끈다(컨테이너 root) — Windows CI는 인자 없이 띄운다
  const args = process.platform === "linux" ? ["--no-sandbox"] : [];
  const app = await electron.launch({ executablePath: exe as string, args, env, cwd: tmp });
  try {
    const win = await app.firstWindow();
    await expect.poll(() => win.title()).toBe("WhyMath 작업 지도");
    expect(await app.evaluate(({ app: a }) => a.isPackaged)).toBe(true);
    await expect(win.locator("#ws-list .ws")).toHaveCount(1);
    await win.locator("#refresh").click();
    await expect(win.locator("#snap-line")).toContainText("work_graph.py ok", { timeout: 200_000 });
    expect(await win.locator(".win").count()).toBeGreaterThan(0);
  } finally {
    await app.close();
    cleanup(tmp);
  }
});
