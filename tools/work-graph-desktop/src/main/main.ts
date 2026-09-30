/* Electron 메인 프로세스 (HARN-206).
   - 보안: contextIsolation true · sandbox true · nodeIntegration false · HTTP 서버 0 · 외부 요청 0
   - IPC는 ipcMain.handle 화이트리스트만. 렌더러는 workspaceId로만 작업공간을 가리킨다(임의 경로 금지).
   - 쓰기는 backlog.py CLI 단일 창구(actions.ts). 앱은 backlog/ 파일을 직접 쓰지 않는다. */
import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";
import type { ActionRequest, AddWorkspaceInput, Layout, Snapshot, WorkspaceOptions } from "../shared/types";
import { runAction } from "./actions";
import { runCommand } from "./adapters/exec";
import { collectSnapshot } from "./collect";
import { LayoutStore } from "./store/layouts";
import { SettingsStore } from "./store/settings";
import { SnapshotStore } from "./store/snapshots";

const userData = () => app.getPath("userData");
let settings: SettingsStore;
let snapshots: SnapshotStore;
let layouts: LayoutStore;

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

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1480, height: 920, minWidth: 900, minHeight: 600,
    title: "WhyMath 작업 지도",
    backgroundColor: "#0d1116",
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
  return win;
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
  }));
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

/** 환경변수 WORK_GRAPH_WORKSPACE로 작업공간 자동 등록(스모크·최초 실행용). 실패는 stderr에 사유. */
async function autoRegister(): Promise<void> {
  const p = process.env.WORK_GRAPH_WORKSPACE;
  if (!p) return;
  const r = await settings.add({ path: p });
  if (!r.ok) console.error(`[work-graph] WORK_GRAPH_WORKSPACE 등록 거부: ${r.reason}`);
}

app.whenReady().then(async () => {
  if (process.env.WORK_GRAPH_USER_DATA) app.setPath("userData", process.env.WORK_GRAPH_USER_DATA);
  settings = new SettingsStore(userData());
  snapshots = new SnapshotStore(userData());
  layouts = new LayoutStore(userData());
  await autoRegister();
  registerIpc();
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}).catch((e: Error) => {
  console.error(`[work-graph] 시작 실패 ${e.name}: ${e.message}`);
  app.exit(1);
});

app.on("window-all-closed", () => { app.quit(); });
