/* 렌더러 API 선택 (HARN-206) — Electron이면 preload가 만든 window.workGraph, 아니면 픽스처 API.
   픽스처 API는 fixtures/*.json을 번들에 실어 두고 메모리에만 저장한다(브라우저·Playwright에서
   Electron 없이 화면 계약을 검사하기 위한 것). 판정은 두 경로 모두 페이로드가 낸 그대로다. */
import type { ActionRequest, ActionResult, Layout, Payload, Snapshot, WorkGraphApi, Workspace } from "../shared/types";
import sample from "../../fixtures/sample.json";
import sampleOk from "../../fixtures/sample_ok.json";

declare global {
  interface Window { workGraph?: WorkGraphApi }
}

const FIXTURES: Record<string, Payload> = {
  sample: sample as unknown as Payload,
  sample_ok: sampleOk as unknown as Payload,
};

export function fixtureNames(): string[] {
  return Object.keys(FIXTURES);
}

/** 픽스처 API — 메모리 저장. `?fixture=<이름>`으로 페이로드를 고른다. */
export function fixtureApi(name: string, opts: { stale?: boolean; collectedAt?: string } = {}): WorkGraphApi {
  const payload = FIXTURES[name] ?? FIXTURES.sample;
  const ws: Workspace = {
    id: "ws_fixture00000", name: `픽스처 ${name in FIXTURES ? name : "sample"}`, root: "(fixture)",
    kind: "harness", options: { remote: false, github: false },
  };
  const layouts = new Map<string, Layout>();
  const emptyLayout = (): Layout => ({ positions: {}, view: null, notes: {} });
  let collectedAt = opts.collectedAt ?? new Date().toISOString();
  const snapshot = (): Snapshot => ({
    workspaceId: ws.id,
    collectedAt,
    sources: {
      harness: { status: "ok", tool: "python3 (fixture)", at: collectedAt, data: null },
      git: { status: "ok", tool: "git (fixture)", at: collectedAt,
        data: { branch: "claude/fixture", changedFiles: 2, ahead: 3, baseRef: "origin/main", worktrees: [{ path: "(fixture)", branch: "claude/fixture" }] } },
      github: { status: "skipped", tool: "gh", at: collectedAt, reason: "작업공간 설정에서 GitHub 조회가 꺼져 있다" },
    },
    payload: JSON.parse(JSON.stringify(payload)) as Payload,
    stale: !!opts.stale,
  });
  return {
    mode: () => "fixture",
    listWorkspaces: async () => [ws],
    pickFolder: async () => null,
    addWorkspace: async () => ({ ok: false, reason: "픽스처 모드 — 작업공간을 추가할 수 없다(Electron에서만)" }),
    updateWorkspace: async () => ws,
    removeWorkspace: async () => false,
    loadSnapshot: async () => snapshot(),
    refresh: async () => { collectedAt = new Date().toISOString(); return snapshot(); },
    runAction: async (req: ActionRequest): Promise<ActionResult> => ({
      ok: false, exitCode: null, stdout: "", stderr: "", command: [],
      reason: `픽스처 모드 — ${req.kind} ${req.args.id} 명령을 실행하지 않는다(Electron에서만 실행된다)`,
    }),
    loadLayout: async (id) => JSON.parse(JSON.stringify(layouts.get(id) ?? emptyLayout())) as Layout,
    saveLayout: async (id, layout) => { layouts.set(id, JSON.parse(JSON.stringify(layout)) as Layout); },
    resetLayout: async (id) => { layouts.delete(id); },
    openExternal: async () => false,
    openTaskFile: async () => ({ ok: false, reason: "픽스처 모드 — 파일을 열 수 없다" }),
  };
}

export function chooseApi(): WorkGraphApi {
  if (window.workGraph) return window.workGraph;
  const q = new URLSearchParams(location.search);
  return fixtureApi(q.get("fixture") ?? "sample", { stale: q.get("stale") === "1" });
}
