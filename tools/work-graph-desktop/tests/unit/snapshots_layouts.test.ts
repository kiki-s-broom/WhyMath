/* 스냅샷 stale 판정(24h 경계)·저장/복원 · 레이아웃 정리 (HARN-206) */
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { isStale, SnapshotStore } from "../../src/main/store/snapshots";
import { LayoutStore, sanitizeLayout } from "../../src/main/store/layouts";
import type { Snapshot } from "../../src/shared/types";

let tmp: string;
beforeAll(async () => { tmp = await fs.mkdtemp(path.join(os.tmpdir(), "wg-snap-")); });
afterAll(async () => { await fs.rm(tmp, { recursive: true, force: true }); });

describe("isStale", () => {
  const now = new Date("2026-09-30T12:00:00Z");
  it("정확히 24시간은 stale이 아니고, 1ms 넘으면 stale", () => {
    expect(isStale("2026-09-29T12:00:00.000Z", now)).toBe(false);
    expect(isStale("2026-09-29T11:59:59.999Z", now)).toBe(true);
    expect(isStale("2026-09-30T11:00:00Z", now)).toBe(false);
  });
  it("파싱 불가한 시각은 stale(모름 ≠ 아니다 — 안전 쪽)", () => { expect(isStale("언제", now)).toBe(true); });
});

describe("SnapshotStore", () => {
  it("저장 → 복원 시 stale 재계산, 페이로드는 바이트 단위로 그대로", async () => {
    const s = new SnapshotStore(tmp);
    const snap: Snapshot = {
      workspaceId: "ws_000000000009", collectedAt: "2026-09-01T00:00:00Z",
      sources: { harness: { status: "ok", at: "x", data: null }, git: { status: "missing_tool", at: "x", reason: "Error: ENOENT" }, github: { status: "skipped", at: "x" } },
      payload: { nodes: { "t:A": { key: "t:A", state: "ready" } }, edges: [{ src: "a", dst: "b" }], counts: { ready: 99 } } as unknown as Snapshot["payload"],
      stale: false,
    };
    await s.save(snap);
    const back = await s.load("ws_000000000009", new Date("2026-09-29T00:00:00Z"));
    expect(back?.stale).toBe(true);
    expect(back?.payload).toEqual(snap.payload);
    expect(back?.sources.git).toEqual(snap.sources.git);
    expect(await s.load("ws_000000000000")).toBeNull();
  });
});

describe("Layout", () => {
  it("sanitize — 숫자 아닌 좌표·빈 메모·잘못된 view 제거", () => {
    expect(sanitizeLayout({ positions: { a: { x: 1.4, y: 2 }, b: { x: "x", y: 1 } }, notes: { a: " ", b: "메모" }, view: { x: 1, y: 2, scale: 0 } }))
      .toEqual({ positions: { a: { x: 1, y: 2 } }, notes: { b: "메모" }, view: null });
    expect(sanitizeLayout(null)).toEqual({ positions: {}, view: null, notes: {} });
  });
  it("save → load → reset", async () => {
    const l = new LayoutStore(tmp);
    await l.save("ws_000000000001", { positions: { "t:A": { x: 10, y: 20 } }, view: { x: 1, y: 2, scale: 0.5 }, notes: {} });
    expect(await l.load("ws_000000000001")).toEqual({ positions: { "t:A": { x: 10, y: 20 } }, view: { x: 1, y: 2, scale: 0.5 }, notes: {} });
    await l.reset("ws_000000000001");
    expect(await l.load("ws_000000000001")).toEqual({ positions: {}, view: null, notes: {} });
    await l.reset("ws_000000000001");   // 없는 파일 reset은 조용히 통과
  });
});
