/* 스냅샷 snapshots/<workspaceId>.json (HARN-206) — 마지막 수집 결과를 그대로 보관한다.
   페이로드는 손대지 않는다(판정 재계산 금지). stale은 읽을 때 계산한다. */
import path from "node:path";
import type { Snapshot } from "../../shared/types";
import { atomicWriteJson, readJson } from "./atomic";

export const STALE_HOURS = 24;

/** collectedAt이 now 기준 24시간을 *넘었는가*(경계값 정확히 24h는 stale 아님). 파싱 불가면 stale. */
export function isStale(collectedAt: string, now: Date = new Date(), hours: number = STALE_HOURS): boolean {
  const t = Date.parse(collectedAt);
  if (Number.isNaN(t)) return true;
  return now.getTime() - t > hours * 3600 * 1000;
}

export class SnapshotStore {
  constructor(private readonly dir: string) {}

  file(id: string): string {
    return path.join(this.dir, "snapshots", `${id}.json`);
  }

  async load(id: string, now: Date = new Date()): Promise<Snapshot | null> {
    const raw = await readJson<Snapshot>(this.file(id));
    if (!raw || typeof raw.collectedAt !== "string") return null;
    return { ...raw, workspaceId: id, stale: isStale(raw.collectedAt, now) };
  }

  async save(snapshot: Snapshot): Promise<void> {
    await atomicWriteJson(this.file(snapshot.workspaceId), snapshot);
  }
}
