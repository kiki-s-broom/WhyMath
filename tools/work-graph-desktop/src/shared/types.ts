/* 메인·프리로드·렌더러가 공유하는 계약 타입 (HARN-206).
   페이로드(work_graph.py --json)는 여기서 "형태만" 적는다 — 앱은 판정을 재계산하지 않고
   nodes·edges·frames·counts를 그대로 그린다. */

export type SourceStatus = "ok" | "missing_tool" | "error" | "timeout" | "skipped";

/** 어댑터 결과 공통 껍데기 — 실패를 빈 결과로 위장하지 않는다(status·reason이 항상 남는다). */
export interface SourceResult<T = unknown> {
  status: SourceStatus;
  /** 실패 사유 — 예외면 `<타입명>: <메시지>` 형태. 시크릿·필드값은 싣지 않는다. */
  reason?: string;
  /** 실행한(또는 찾지 못한) 도구 이름 — 예: python3, git, gh */
  tool?: string;
  /** 수집 시각(ISO 8601) */
  at: string;
  /** stderr 등 부수 경고 — 성공했어도 남긴다 */
  warnings?: string[];
  data?: T;
}

export type WorkspaceKind = "harness" | "git";

export interface WorkspaceOptions {
  /** 원격 조회(미머지 done·원격 claim·고립 브랜치)를 수행할지 — false면 --no-remote */
  remote: boolean;
  /** gh로 열린 PR 목록을 덧붙일지 */
  github: boolean;
  /** python 실행 파일 지정(없으면 python3 → python → py -3 순 탐색) */
  python?: string;
}

export interface Workspace {
  id: string;
  name: string;
  root: string;
  kind: WorkspaceKind;
  options: WorkspaceOptions;
}

export interface Settings {
  version: 1;
  workspaces: Workspace[];
}

/* ── 페이로드 형태 (work_graph.py) ── */
export type NodeKind = "task" | "gate" | "branch";
export type NodeState =
  | "ready" | "in_progress" | "review" | "waiting" | "blocked" | "human"
  | "gate_turn" | "gate_verdict" | "gate_wait" | "branch";

export interface NodeLink {
  key: string;
  id: string;
  kind: NodeKind;
  title: string;
  status: string;
  open: boolean;
  edge: string;
}

export interface GraphNode {
  key: string;
  kind: NodeKind;
  id: string;
  short: string;
  title: string;
  state: NodeState;
  label: string;
  reason: string;
  detail: string;
  preds: NodeLink[];
  succs: NodeLink[];
  unlocks: number;
  wait_chain: string[];
  excerpt: string[];
  acceptance: string[];
  notes: string;
  cmd?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  frame: string;
  flow?: number;
  // task
  stage?: string;
  layer?: string;
  track?: string;
  subject?: string;
  priority?: number;
  owner?: string;
  session?: string;
  updated?: string;
  overdue?: boolean;
  // gate
  gate_kind?: string;
  assignee?: string;
  requested?: string;
  days?: number | null;
  // branch
  verdict?: string;
  done_tasks?: string[];
  claimed_tasks?: string[];
  foreign_tasks?: string[];
  ahead?: number | null;
  age_days?: number | null;
  last_commit_at?: string;
  disposal_labels?: string[];
  synthetic?: boolean;
}

export interface GraphEdge {
  src: string;
  dst: string;
  kind: string;
  back: boolean;
  points: [number, number][];
  frame: string;
}

export interface GraphFrame {
  kind: "flow" | "group";
  id: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  size: number;
  keys: string[];
  index?: number;
  depth?: number;
  hint?: string;
  counts?: Record<string, number>;
}

export interface ScanStatus {
  status: string;
  count?: number;
  [k: string]: unknown;
}

export interface Payload {
  generated: string;
  base: string;
  current_stage: string;
  open_tasks: number;
  open_gates: number;
  branch_total: number;
  edge_total: number;
  counts: Record<string, number>;
  flow_count: number;
  flow_node_total: number;
  independent_total: number;
  canvas: { w: number; h: number; win_w: number; win_h: number };
  frames: GraphFrame[];
  edges: GraphEdge[];
  ready_order: string[];
  stages: string[];
  scans: Record<string, ScanStatus>;
  errors: string[];
  nodes: Record<string, GraphNode>;
}

/* ── 부가 사실(판정을 바꾸지 않는다) ── */
export interface GitFacts {
  branch: string;
  changedFiles: number;
  /** 기준 브랜치 대비 앞선 커밋 수 — 기준을 못 찾으면 "undeterminable" */
  ahead: number | "undeterminable";
  aheadReason?: string;
  baseRef?: string;
  worktrees: { path: string; head?: string; branch?: string }[];
}

export interface PullRequestFact {
  number: number;
  title: string;
  url: string;
  headRefName: string;
  isDraft: boolean;
  reviewDecision: string;
  checks?: string;
}

export interface Snapshot {
  workspaceId: string;
  collectedAt: string;
  sources: {
    harness: SourceResult<null>;
    git: SourceResult<GitFacts>;
    github: SourceResult<PullRequestFact[]>;
  };
  payload: Payload | null;
  /** collectedAt이 24시간을 넘었는가 — 메인이 계산해 넘긴다 */
  stale: boolean;
}

/* ── 동작(쓰기) — backlog.py CLI 단일 창구 ── */
export type ActionKind = "start" | "gates_clear" | "done";

export interface ActionRequest {
  workspaceId: string;
  kind: ActionKind;
  args: {
    id: string;
    evidence?: string;
    assignee?: string;
    noBase?: string;
    artifacts?: string[];
  };
}

export interface ActionResult {
  ok: boolean;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  command: string[];
  /** 실행 자체가 불가했을 때(파이썬 없음·인자 거부) 사유 */
  reason?: string;
}

/* ── 레이아웃(사용자 배치) ── */
export interface Layout {
  positions: Record<string, { x: number; y: number }>;
  view: { x: number; y: number; scale: number } | null;
  notes: Record<string, string>;
}

/* ── 프리로드가 노출하는 API — 렌더러는 이것만 쓴다 ── */
export interface AddWorkspaceInput {
  path?: string;
  name?: string;
  options?: Partial<WorkspaceOptions>;
}

export interface WorkGraphApi {
  listWorkspaces(): Promise<Workspace[]>;
  pickFolder(): Promise<string | null>;
  addWorkspace(input: AddWorkspaceInput): Promise<{ ok: true; workspace: Workspace } | { ok: false; reason: string }>;
  updateWorkspace(id: string, patch: { name?: string; options?: Partial<WorkspaceOptions> }): Promise<Workspace | null>;
  removeWorkspace(id: string): Promise<boolean>;
  loadSnapshot(id: string): Promise<Snapshot | null>;
  refresh(id: string): Promise<Snapshot>;
  runAction(req: ActionRequest): Promise<ActionResult>;
  loadLayout(id: string): Promise<Layout>;
  saveLayout(id: string, layout: Layout): Promise<void>;
  resetLayout(id: string): Promise<void>;
  openExternal(url: string): Promise<boolean>;
  openTaskFile(id: string, nodeKey: string): Promise<{ ok: boolean; reason?: string; path?: string }>;
  /** 실행 환경 — 픽스처 모드인지(Electron 없이 브라우저에서 열렸는지) */
  mode(): "electron" | "fixture";
}
