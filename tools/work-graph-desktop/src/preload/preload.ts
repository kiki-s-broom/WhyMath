/* 프리로드 (HARN-206) — contextBridge로 좁은 API만 노출한다. 렌더러는 Node·ipcRenderer에 직접
   닿지 못하고 여기 열거된 채널만 호출할 수 있다. */
import { contextBridge, ipcRenderer } from "electron";
import type { ActionRequest, AddWorkspaceInput, Layout, WorkGraphApi, WorkspaceOptions } from "../shared/types";

const api: WorkGraphApi = {
  listWorkspaces: () => ipcRenderer.invoke("ws:list"),
  pickFolder: () => ipcRenderer.invoke("ws:pick"),
  addWorkspace: (input: AddWorkspaceInput) => ipcRenderer.invoke("ws:add", input),
  updateWorkspace: (id: string, patch: { name?: string; options?: Partial<WorkspaceOptions> }) => ipcRenderer.invoke("ws:update", id, patch),
  removeWorkspace: (id: string) => ipcRenderer.invoke("ws:remove", id),
  loadSnapshot: (id: string) => ipcRenderer.invoke("snapshot:load", id),
  refresh: (id: string) => ipcRenderer.invoke("snapshot:refresh", id),
  runAction: (req: ActionRequest) => ipcRenderer.invoke("action:run", req),
  loadLayout: (id: string) => ipcRenderer.invoke("layout:load", id),
  saveLayout: (id: string, layout: Layout) => ipcRenderer.invoke("layout:save", id, layout),
  resetLayout: (id: string) => ipcRenderer.invoke("layout:reset", id),
  openExternal: (url: string) => ipcRenderer.invoke("shell:openExternal", url),
  openTaskFile: (id: string, nodeKey: string) => ipcRenderer.invoke("shell:openTaskFile", id, nodeKey),
  discovery: () => ipcRenderer.invoke("ws:discovery"),
  mode: () => "electron",
};

contextBridge.exposeInMainWorld("workGraph", api);
