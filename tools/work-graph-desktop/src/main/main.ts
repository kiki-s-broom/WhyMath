/* Electron 메인 프로세스 (HARN-206 · HARN-208).
   - 보안: contextIsolation true · sandbox true · nodeIntegration false · HTTP 서버 0 · 외부 요청 0
   - IPC는 ipcMain.handle 화이트리스트만. 렌더러는 workspaceId로만 작업공간을 가리킨다(임의 경로 금지).
   - 쓰기는 backlog.py CLI 단일 창구(actions.ts). 앱은 backlog/ 파일을 직접 쓰지 않는다.
   - Windows 프로그램 실행 형식(HARN-208): 단일 인스턴스 · 창 자리 기억 · 첫 실행 저장소 자동 찾기. */
import { app, BrowserWindow, dialog, ipcMain, screen, shell } from "electron";
import { existsSync, promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ActionRequest, AddWorkspaceInput, DiscoveryReport, Layout, Snapshot, WorkspaceOptions } from "../shared/types";
import { runAction } from "./actions";
import { runCommand } from "./adapters/exec";
import { collectSnapshot } from "./collect";
import { discoverWorkspace, workspaceCandidates } from "./discover";
import { LayoutStore } from "./store/layouts";
import { SettingsStore } from "./store/settings";
import { SnapshotStore } from "./store/snapshots";
import { DEFAULT_SIZE, MIN_SIZE, WindowStateStore, fitBounds } from "./store/windowState";

const userData = () => app.getPath("userData");
let settings: SettingsStore;
let snapshots: SnapshotStore;
let layouts: LayoutStore;
let windowState: WindowStateStore;
let mainWindow: BrowserWindow | null = null;
/** 첫 실행 자동 찾기 결과 — 찾기를 하지 않았으면 null (렌더러 첫 화면이 사유를 보인다) */
let discovery: DiscoveryReport | null = null;

/** 렌더러가 넘긴 값이 workspaceId 형태인지 — 경로·명령을 넘길 수 없게 여기서 자른다 */
function wsId(v: unknown): string {
  if (typeof v !== "string" || !/^ws_[0-9a-f]{12}$/.test(v)) throw new Error("InvalidWorkspaceId: 작업공간 ID 형식이 아니다");
  return v;
}

async function workspaceOf(id: string) {
  const ws = await settings.get(wsId(id));
  if (!ws) throw new Error(`UnknownWorkspace: 등록되지 않은 작업공간 ${id}`);
  return ws;
}

async function createWindow(): Promise<BrowserWindow> {
  const saved = await windowState.load();
  const fitted = saved ? fitBounds(saved.bounds, screen.getAllDisplays().map((d) => d.workArea)) : null;
  const icon = path.join(__dirname, "..", "icon.png");   // 개발 모드용 — 설치본은 EXE에 박힌 아이콘을 쓴다
  const win = new BrowserWindow({
    ...(fitted ?? DEFAULT_SIZE), minWidth: MIN_SIZE.width, minHeight: MIN_SIZE.height,
    title: "WhyMath 작업 지도",
    backgroundColor: "#0d1116",
    icon: existsSync(icon) ? icon : undefined,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  win.setMenuBarVisibility(false);
  // 렌더러가 다른 곳으로 이동하거나 새 창을 여는 것을 막는다 — 외부 링크는 openExternal 경유만
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (ev) => ev.preventDefault());
  void win.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
  if (saved?.maximized && fitted) win.maximize();
  // 닫는 순간의 자리를 남긴다 — 최대화 상태면 최대화 전(normal) 크기를 저장해 다음에 되돌릴 수 있게
  win.on("close", () => {
    windowState.saveSync({ bounds: win.getNormalBounds(), maximized: win.isMaximized() });
  });
  win.on("closed", () => { if (mainWindow === win) mainWindow = null; });
  mainWindow = win;
  return win;
}

/** 두 번째 실행은 새 창을 만들지 않고 이미 켜진 창을 앞으로 가져온다 */
function focusMainWindow(): void {
  const win = mainWindow;
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function registerIpc(): void {
  ipcMain.handle("ws:list", () => settings.list());
  ipcMain.handle("ws:pick", async () => {
    const r = await dialog.showOpenDialog({ properties: ["openDirectory"], title: "작업공간 폴더 선택" });
    return r.canceled || !r.filePaths.length ? null : r.filePaths[0];
  });
  ipcMain.handle("ws:add", (_e, input: AddWorkspaceInput) => settings.add({
    path: typeof input?.path === "string" ? input.path : undefined,
    name: typeof input?.name === "string" ? input.name : undefined,
    options: sanitizeOptions(input?.options),
    requireHarness: input?.requireHarness === true,
  }));
  ipcMain.handle("ws:discovery", () => discovery);
  ipcMain.handle("ws:update", (_e, id: string, patch: { name?: string; options?: Partial<WorkspaceOptions> }) =>
    settings.update(wsId(id), { name: typeof patch?.name === "string" ? patch.name : undefined, options: sanitizeOptions(patch?.options) }));
  ipcMain.handle("ws:remove", (_e, id: string) => settings.remove(wsId(id)));

  ipcMain.handle("snapshot:load", (_e, id: string) => snapshots.load(wsId(id)));
  ipcMain.handle("snapshot:refresh", async (_e, id: string): Promise<Snapshot> => {
    const ws = await workspaceOf(id);
    const snap = await collectSnapshot(ws, runCommand);
    await snapshots.save(snap);
    return snap;
  });

  ipcMain.handle("action:run", async (_e, req: ActionRequest) => {
    const ws = await workspaceOf(req?.workspaceId);
    return runAction({ workspaceId: ws.id, kind: req.kind, args: req.args }, ws.root, ws.options, runCommand);
  });

  ipcMain.handle("layout:load", (_e, id: string) => layouts.load(wsId(id)));
  ipcMain.handle("layout:save", (_e, id: string, layout: Layout) => layouts.save(wsId(id), layout));
  ipcMain.handle("layout:reset", (_e, id: string) => layouts.reset(wsId(id)));

  ipcMain.handle("shell:openExternal", async (_e, url: string) => {
    if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return false;
    await shell.openExternal(url);
    return true;
  });
  // 태스크 YAML 열기 — 읽기 전용(shell.openPath). 경로는 workspaceId + 노드 키에서 메인이 조립한다.
  ipcMain.handle("shell:openTaskFile", async (_e, id: string, nodeKey: string) => {
    const ws = await workspaceOf(id);
    if (typeof nodeKey !== "string") return { ok: false, reason: "노드 키가 아니다" };
    const m = /^([tg]):([A-Za-z0-9][A-Za-z0-9._-]{0,200})$/.exec(nodeKey);
    if (!m) return { ok: false, reason: "태스크·게이트 창만 원본 파일을 연다" };
    const rel = m[1] === "t" ? path.join("backlog", "tasks", `${m[2]}.yaml`) : path.join("backlog", "gates.yaml");
    const file = path.join(ws.root, rel);
    try { await fs.access(file); } catch (e) { return { ok: false, reason: `${(e as Error).name}: ${rel} 없음` }; }
    const err = await shell.openPath(file);
    return err ? { ok: false, reason: err, path: file } : { ok: true, path: file };
  });
}

function sanitizeOptions(o: unknown): Partial<WorkspaceOptions> | undefined {
  if (!o || typeof o !== "object") return undefined;
  const r = o as Record<string, unknown>;
  const out: Partial<WorkspaceOptions> = {};
  if (typeof r.remote === "boolean") out.remote = r.remote;
  if (typeof r.github === "boolean") out.github = r.github;
  if (typeof r.python === "string") out.python = r.python.trim() || undefined;
  return out;
}

/** app.getPath가 던지면 undefined — 알려진 폴더를 풀지 못하면 Electron이 예외를 던진다(2026-09-30 Windows CI 실측:
    USERPROFILE 아래 Desktop이 없으면 getPath("desktop") 예외 → 시작 실패 대화상자가 메인 프로세스를 막아 앱이 뜨지 않았다).
    바탕화면은 저장소 후보 하나일 뿐이므로 못 구하면 그 후보만 빼고 계속한다. 사유는 stderr에 남긴다. */
function tryGetPath(name: Parameters<typeof app.getPath>[0]): string | undefined {
  try { return app.getPath(name); }
  catch (e) { console.error(`[work-graph] ${name} 경로를 구하지 못해 후보에서 뺀다 ${(e as Error).name}: ${(e as Error).message}`); return undefined; }
}

/** 작업공간 준비.
    ① 환경변수 WORK_GRAPH_WORKSPACE가 있으면 그것을 등록한다(스모크·명시 지정).
    ② 없고 등록된 작업공간도 없으면(첫 실행) 알려진 자리에서 WhyMath 저장소를 찾아 등록한다 —
       바로가기로 켜면 작업 폴더가 저장소가 아니기 때문이다. 못 찾으면 찾아본 자리를 렌더러 첫 화면이 보인다. */
async function ensureWorkspace(): Promise<void> {
  const explicit = process.env.WORK_GRAPH_WORKSPACE;
  if (explicit) {
    const r = await settings.add({ path: explicit });
    if (!r.ok) console.error(`[work-graph] WORK_GRAPH_WORKSPACE 등록 거부: ${r.reason}`);
    return;
  }
  if ((await settings.list()).length) return;
  discovery = await discoverWorkspace(workspaceCandidates({
    env: process.env, platform: process.platform, home: os.homedir(),
    desktop: tryGetPath("desktop"), appDir: app.getAppPath(),
  }));
  if (!discovery.found) return;
  const r = await settings.add({ path: discovery.found, requireHarness: true });
  if (!r.ok) {
    discovery = { found: null, tried: [...discovery.tried, { path: discovery.found, reason: r.reason }] };
    console.error(`[work-graph] 자동 찾은 저장소 등록 거부: ${r.reason}`);
  }
}

/** 앱 데이터 폴더 이름 (HARN-208) — 영문으로 고정한다. Electron 기본값은 appData\<제품명>인데 제품명이 한글이라
    결과가 로캘에 따라 갈린다(2026-09-30 실측 · 리눅스: C.UTF-8이면 ".config/WhyMath 작업 지도", 로캘 없음·미설치
    로캘이면 이름을 버리고 appData 루트 그대로 — 설정·스냅샷이 루트에 흩어지고 단일 인스턴스 잠금도 appData 전체에
    걸린다). Windows는 한글 폴더가 된다. 어느 쪽이든 런북이 안내하는 경로와 어긋나므로 이름을 박아 둔다. */
export const USER_DATA_DIR = "whymath-work-graph-desktop";

// userData는 단일 인스턴스 잠금보다 먼저 정한다 — 잠금이 userData 폴더 단위라서다
app.setPath("userData", process.env.WORK_GRAPH_USER_DATA || path.join(app.getPath("appData"), USER_DATA_DIR));

if (!app.requestSingleInstanceLock()) {
  // 이미 켜진 앱이 있다 — 그쪽이 second-instance를 받아 창을 앞으로 가져온다. 이 프로세스는 조용히 끝낸다.
  app.quit();
} else {
  app.on("second-instance", focusMainWindow);
  app.whenReady().then(async () => {
    settings = new SettingsStore(userData());
    snapshots = new SnapshotStore(userData());
    layouts = new LayoutStore(userData());
    windowState = new WindowStateStore(userData());
    await ensureWorkspace();
    registerIpc();
    await createWindow();
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
  }).catch((e: Error) => {
    console.error(`[work-graph] 시작 실패 ${e.name}: ${e.message}`);
    dialog.showErrorBox("WhyMath 작업 지도 — 시작 실패", `${e.name}: ${e.message}`);
    app.exit(1);
  });
  app.on("window-all-closed", () => { app.quit(); });
}
