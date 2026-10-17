/* 창 크기·위치 기억 window.json (HARN-208) — userData 아래에 원자적으로 저장한다.
   모니터 구성이 바뀌어 저장된 자리가 화면 밖이면 버리고 기본 크기로 연다(보이지 않는 창 방지). */
import path from "node:path";
import { atomicWriteJson, atomicWriteJsonSync, readJson } from "./atomic";

export interface Rect { x: number; y: number; width: number; height: number }
export interface WindowState { bounds: Rect; maximized: boolean }

export const DEFAULT_SIZE = { width: 1480, height: 920 };
export const MIN_SIZE = { width: 900, height: 600 };

function isRect(v: unknown): v is Rect {
  const r = v as Rect;
  return !!r && [r.x, r.y, r.width, r.height].every((n) => typeof n === "number" && Number.isFinite(n));
}

/** 저장된 자리를 쓸 수 있는지 — 창의 제목 막대(왼쪽 위에서 조금 안쪽)가 어느 화면 작업 영역 안에 있어야 한다.
    크기는 최소 크기 이상·그 화면 크기 이하로, 위치는 창이 그 화면 안에 들어오게 맞춘다. 쓸 수 없으면 null. */
export function fitBounds(saved: Rect, workAreas: Rect[]): Rect | null {
  const px = saved.x + Math.min(saved.width / 2, 120);
  const py = saved.y + 16;
  const area = workAreas.find((a) => px >= a.x && px < a.x + a.width && py >= a.y && py < a.y + a.height);
  if (!area) return null;
  const width = Math.min(Math.max(saved.width, MIN_SIZE.width), area.width);
  const height = Math.min(Math.max(saved.height, MIN_SIZE.height), area.height);
  const x = Math.min(Math.max(saved.x, area.x), area.x + area.width - width);
  const y = Math.min(Math.max(saved.y, area.y), area.y + area.height - height);
  return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
}

export class WindowStateStore {
  readonly file: string;
  constructor(dir: string) { this.file = path.join(dir, "window.json"); }

  /** 손상·형식 오류는 기본값으로 연다 — 창 자리는 편의 기능이라 앱 기동을 막지 않는다(사유는 stderr). */
  async load(): Promise<WindowState | null> {
    try {
      const raw = await readJson<Partial<WindowState>>(this.file);
      if (!raw || !isRect(raw.bounds)) return null;
      return { bounds: raw.bounds, maximized: raw.maximized === true };
    } catch (e) {
      console.error(`[work-graph] 창 자리 읽기 실패 ${(e as Error).name}: ${(e as Error).message}`);
      return null;
    }
  }

  async save(state: WindowState): Promise<void> {
    await atomicWriteJson(this.file, state);
  }

  /** 창 close 이벤트용 — 곧 프로세스가 끝나므로 동기로 쓴다. 실패는 사유를 남기고 종료를 막지 않는다. */
  saveSync(state: WindowState): boolean {
    try {
      atomicWriteJsonSync(this.file, state);
      return true;
    } catch (e) {
      console.error(`[work-graph] 창 자리 저장 실패 ${(e as Error).name}: ${(e as Error).message}`);
      return false;
    }
  }
}
