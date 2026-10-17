/* 레이아웃 layouts/<workspaceId>.json (HARN-206) — 끌어 옮긴 창 좌표·보기·메모. */
import path from "node:path";
import type { Layout } from "../../shared/types";
import { atomicWriteJson, readJson, removeFile } from "./atomic";

export const EMPTY_LAYOUT: Layout = { positions: {}, view: null, notes: {} };

export function sanitizeLayout(raw: unknown): Layout {
  const r = (raw && typeof raw === "object" ? raw : {}) as Partial<Layout>;
  const positions: Layout["positions"] = {};
  for (const [k, v] of Object.entries(r.positions || {})) {
    if (v && Number.isFinite(v.x) && Number.isFinite(v.y)) positions[k] = { x: Math.round(v.x), y: Math.round(v.y) };
  }
  const notes: Layout["notes"] = {};
  for (const [k, v] of Object.entries(r.notes || {})) if (typeof v === "string" && v.trim()) notes[k] = v.slice(0, 4000);
  const v = r.view;
  const view = v && Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.scale) && v.scale > 0
    ? { x: v.x, y: v.y, scale: v.scale } : null;
  return { positions, view, notes };
}

export class LayoutStore {
  constructor(private readonly dir: string) {}

  file(id: string): string {
    return path.join(this.dir, "layouts", `${id}.json`);
  }

  async load(id: string): Promise<Layout> {
    return sanitizeLayout(await readJson(this.file(id)));
  }

  async save(id: string, layout: unknown): Promise<void> {
    await atomicWriteJson(this.file(id), sanitizeLayout(layout));
  }

  async reset(id: string): Promise<void> {
    await removeFile(this.file(id));
  }
}
