/* 작업공간 레지스트리 settings.json (HARN-206).
   {version:1, workspaces:[{id,name,root,kind,options}]} — userData 아래에 원자적으로 저장한다. */
import { promises as fs } from "node:fs";
import path from "node:path";
import { randomBytes } from "node:crypto";
import type { AddWorkspaceInput, Settings, Workspace, WorkspaceKind, WorkspaceOptions } from "../../shared/types";
import { atomicWriteJson, readJson } from "./atomic";

export const DEFAULT_OPTIONS: WorkspaceOptions = { remote: true, github: false, source: "trunk" };

/** 저장된 옵션 읽기. `source`가 없는 항목은 HARN-306 이전에 저장된 것이다 — 그때 기본값(remote=false·작업 트리)은
    "새로고침해도 변하지 않는" 원인이었으므로 새 기본값(최신 main + 원격 조회)으로 옮긴다. python·github 지정은 보존. */
export function migrateOptions(o: Partial<WorkspaceOptions> | undefined): WorkspaceOptions {
  const stored = o || {};
  if (stored.source === undefined) return { ...DEFAULT_OPTIONS, ...stored, remote: true, source: "trunk" };
  return { ...DEFAULT_OPTIONS, ...stored };
}

/** 폴더 종류 판정 — harness(scripts/harness/work_graph.py 있음) → git(.git 있음) → 거부 */
export async function detectKind(root: string): Promise<{ kind: WorkspaceKind } | { kind: null; reason: string }> {
  const exists = async (p: string) => { try { await fs.access(p); return true; } catch { return false; } };
  if (!(await exists(root))) return { kind: null, reason: `폴더가 없다: ${root}` };
  if (await exists(path.join(root, "scripts", "harness", "work_graph.py"))) return { kind: "harness" };
  if (await exists(path.join(root, ".git"))) return { kind: "git" };
  return { kind: null, reason: "scripts/harness/work_graph.py도 .git도 없는 폴더 — 작업공간으로 등록할 수 없다" };
}

export function newWorkspaceId(): string {
  return "ws_" + randomBytes(6).toString("hex");
}

export class SettingsStore {
  readonly file: string;
  private cache: Settings | null = null;

  constructor(dir: string) {
    this.file = path.join(dir, "settings.json");
  }

  async load(): Promise<Settings> {
    if (this.cache) return this.cache;
    const raw = await readJson<Partial<Settings>>(this.file);
    const workspaces = Array.isArray(raw?.workspaces) ? raw!.workspaces! : [];
    this.cache = {
      version: 1,
      workspaces: workspaces
        .filter((w) => w && typeof w.id === "string" && typeof w.root === "string")
        .map((w) => ({
          id: w.id,
          name: w.name || path.basename(w.root),
          root: w.root,
          kind: w.kind === "git" ? "git" : "harness",
          options: migrateOptions(w.options),
        })),
    };
    return this.cache;
  }

  async save(settings: Settings): Promise<void> {
    this.cache = settings;
    await atomicWriteJson(this.file, settings);
  }

  async list(): Promise<Workspace[]> {
    return (await this.load()).workspaces;
  }

  async get(id: string): Promise<Workspace | null> {
    return (await this.list()).find((w) => w.id === id) ?? null;
  }

  /** 같은 root가 이미 있으면 그 항목을 돌려준다(중복 등록 없음). */
  async add(input: AddWorkspaceInput): Promise<{ ok: true; workspace: Workspace } | { ok: false; reason: string }> {
    if (!input.path || typeof input.path !== "string") return { ok: false, reason: "경로가 비어 있다" };
    const root = path.resolve(input.path);
    const detected = await detectKind(root);
    if (detected.kind === null) return { ok: false, reason: detected.reason };
    if (input.requireHarness && detected.kind !== "harness") {
      return { ok: false, reason: `WhyMath 저장소가 아니다 — ${root}에 scripts/harness/work_graph.py가 없다` };
    }
    const settings = await this.load();
    const existing = settings.workspaces.find((w) => path.resolve(w.root) === root);
    if (existing) return { ok: true, workspace: existing };
    const workspace: Workspace = {
      id: newWorkspaceId(),
      name: (input.name || "").trim() || path.basename(root),
      root,
      kind: detected.kind,
      options: { ...DEFAULT_OPTIONS, ...(input.options || {}) },
    };
    await this.save({ ...settings, workspaces: [...settings.workspaces, workspace] });
    return { ok: true, workspace };
  }

  async update(id: string, patch: { name?: string; options?: Partial<WorkspaceOptions> }): Promise<Workspace | null> {
    const settings = await this.load();
    const idx = settings.workspaces.findIndex((w) => w.id === id);
    if (idx < 0) return null;
    const cur = settings.workspaces[idx];
    const next: Workspace = {
      ...cur,
      name: patch.name !== undefined ? (patch.name.trim() || cur.name) : cur.name,
      options: { ...cur.options, ...(patch.options || {}) },
    };
    const workspaces = settings.workspaces.slice();
    workspaces[idx] = next;
    await this.save({ ...settings, workspaces });
    return next;
  }

  async remove(id: string): Promise<boolean> {
    const settings = await this.load();
    const workspaces = settings.workspaces.filter((w) => w.id !== id);
    if (workspaces.length === settings.workspaces.length) return false;
    await this.save({ ...settings, workspaces });
    return true;
  }
}
