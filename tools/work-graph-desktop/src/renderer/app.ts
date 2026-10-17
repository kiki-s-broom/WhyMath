/* 렌더러 껍데기 (HARN-206) — 레일·집계 카드·도구·캔버스/표·상세·모달.
   원칙: 페이로드의 nodes·edges·frames·counts를 **그대로** 그린다(창 수 = nodes 수 · 연결선 수 = edges 수 ·
   집계 = counts). 앱이 스스로 계산하는 것은 '확인 필요' 사유 개수뿐이다. 쓰기는 preload API의 runAction
   (backlog.py CLI)으로만 나가고 결과(exit code·stdout·stderr)는 그대로 보여 준다. */
import type {
  ActionKind, ActionResult, DiscoveryReport, GraphNode, Layout, NodeLink, Snapshot, SourceResult, WorkGraphApi, Workspace,
} from "../shared/types";
import { chooseApi } from "./api";
import { esc, GraphCanvas, KIND_LABEL, type View } from "./canvas";

type Group = "ready" | "in_progress" | "waiting" | "blocked" | "human" | "gate" | "branch";
type ViewName = "map" | "ready" | "human" | "branch" | "list";

const $ = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
const SCAN_NAME: Record<string, string> = { remote_done: "완료분", remote_claim: "claim", stale_branches: "고립" };
const SOURCE_NAME: Record<string, string> = { harness: "work_graph.py", git: "git", github: "gh" };
const GROUP_RANK: Record<Group, number> = { ready: 0, in_progress: 1, gate: 2, human: 3, blocked: 4, waiting: 5, branch: 6 };
const GROUP_NAME: Record<Group, string> = {
  ready: "처리 가능", in_progress: "진행 중", waiting: "선행 대기", blocked: "차단", human: "사람 작업", gate: "게이트", branch: "미머지 브랜치",
};

/** 상태 → 집계 카드 묶음. counts의 키와 같은 축이다(카드 값은 counts에서 그대로 온다). */
export function stateGroup(n: GraphNode): Group {
  switch (n.state) {
    case "ready": return "ready";
    case "in_progress": case "review": return "in_progress";
    case "waiting": return "waiting";
    case "blocked": return "blocked";
    case "human": return "human";
    case "gate_turn": case "gate_verdict": case "gate_wait": return "gate";
    case "branch": return "branch";
    default: return "waiting";
  }
}

/** '확인 필요' 사유 — 앱이 계산하는 유일한 집계. 빈 목록으로 위장하지 않는다. */
export function attentionReasons(snap: Snapshot | null): { kind: string; text: string }[] {
  if (!snap) return [{ kind: "snapshot", text: "스냅샷이 없다 — 새로고침으로 수집하라" }];
  const out: { kind: string; text: string }[] = [];
  for (const [k, s] of Object.entries(snap.sources)) {
    const r = s as SourceResult;
    if (r.status === "ok") continue;
    if (k === "github" && r.status === "skipped") continue; // 설정으로 끈 것은 실패가 아니다(상태 줄에 따로 보인다)
    out.push({ kind: "source", text: `${SOURCE_NAME[k] ?? k} ${r.status}${r.tool ? ` (${r.tool})` : ""} — ${r.reason ?? "사유 없음"}` });
  }
  if (snap.stale) out.push({ kind: "stale", text: `스냅샷이 24시간을 넘었다 — 수집 시각 ${fmtTime(snap.collectedAt)}. 새로고침하라` });
  const p = snap.payload;
  if (p) {
    for (const [k, s] of Object.entries(p.scans || {})) {
      if (s.status === "ok") continue;
      out.push({ kind: "scan", text: `원격 조회 ${SCAN_NAME[k] ?? k}: ${s.status} — 이번 수집에서 이 축은 측정되지 않았다`
        + (k === "stale_branches" ? " (미머지 브랜치 창의 고립·PR 여부가 비어 있을 수 있다)" : " ('처리 가능'에 다른 세션이 이미 잡았거나 끝낸 작업이 섞였을 수 있다)") });
    }
    for (const e of p.errors || []) out.push({ kind: "validate", text: `정합성 경고(backlog.py validate): ${e}` });
  } else if (snap.sources.harness.status === "ok") {
    out.push({ kind: "payload", text: "페이로드가 비어 있다 — work_graph.py 출력을 확인하라" });
  }
  return out;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number): (...a: A) => void {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...a: A) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ── 앱 상태 ── */
interface State {
  api: WorkGraphApi;
  workspaces: Workspace[];
  ws: Workspace | null;
  snap: Snapshot | null;
  layout: Layout;
  view: ViewName;
  groups: Set<Group>;
  query: string;
  stage: string;
  layer: string;
  track: string;
  kind: string;
  selected: string | null;
  attentionOpen: boolean;
  busy: boolean;
  lastResult: { key: string; result: ActionResult } | null;
  /** 첫 실행 저장소 자동 찾기 결과 (HARN-208) — 찾기를 안 했으면 null */
  discovery: DiscoveryReport | null;
}

const st: State = {
  api: chooseApi(), workspaces: [], ws: null, snap: null, layout: { positions: {}, view: null, notes: {} },
  view: "map", groups: new Set(), query: "", stage: "", layer: "", track: "", kind: "",
  selected: null, attentionOpen: false, busy: false, lastResult: null, discovery: null,
};

const canvas = new GraphCanvas($("stage"), $("world"), $<HTMLCanvasElement>("mini"), $("zoomrd"), {
  onSelect: (k) => { st.selected = k; renderDetail(); markTableSel(); },
  onMoved: () => scheduleLayoutSave(),
  onView: () => scheduleViewSave(),
});

const nodes = () => st.snap?.payload?.nodes ?? {};
const keys = () => Object.keys(nodes());

/* ── 걸러 보기 ── */
function matches(n: GraphNode): boolean {
  if (st.groups.size && !st.groups.has(stateGroup(n))) return false;
  if (st.stage && n.stage !== st.stage) return false;
  if (st.layer && n.layer !== st.layer) return false;
  if (st.track && n.track !== st.track) return false;
  if (st.kind && n.kind !== st.kind) return false;
  if (st.query) {
    const hay = [n.id, n.short, n.title, n.session, n.reason, n.detail, (n.excerpt || []).join(" ")].join(" ").toLowerCase();
    if (!st.query.split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}
const filtering = () => !!(st.groups.size || st.query || st.stage || st.layer || st.track || st.kind);

/** 목록·키보드 이동 순서 — 묶음 순위 → 풀림 수 → ID */
function orderedKeys(): string[] {
  const N = nodes();
  return keys().filter((k) => matches(N[k])).sort((a, b) => {
    const ga = GROUP_RANK[stateGroup(N[a])], gb = GROUP_RANK[stateGroup(N[b])];
    return ga - gb || (N[b].unlocks - N[a].unlocks) || a.localeCompare(b);
  });
}

function applyFilter(): void {
  const f = filtering();
  canvas.setFilter(f ? matches : null, !!st.query);
  const hits = f ? orderedKeys().length : keys().length;
  $("hits").textContent = f ? `걸러 본 결과 ${hits} / ${keys().length}` : `창 ${keys().length} · 연결선 ${st.snap?.payload?.edges.length ?? 0}`;
  renderCards();
  if (st.view === "list") renderTable();
}

/* ── 레일 ── */
function renderRail(): void {
  $("mode").textContent = st.api.mode() === "fixture" ? "픽스처 모드 — 브라우저 미리보기(명령 실행 없음)" : "Electron";
  $("ws-list").innerHTML = st.workspaces.map((w) => `<button class="rail-btn ws${st.ws?.id === w.id ? " active" : ""}" type="button" data-ws="${esc(w.id)}" title="${esc(w.root)}">
    <span class="nm">${esc(w.name)}</span><span class="pt">${esc(w.root)}</span></button>`).join("")
    || '<p class="rail-btn add" style="cursor:default">등록된 작업공간이 없다</p>';
  $("ws-list").querySelectorAll<HTMLElement>("[data-ws]").forEach((b) => b.onclick = () => void selectWorkspace(b.dataset.ws as string));
  $("views").querySelectorAll<HTMLElement>("[data-view]").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.view === st.view));
    b.onclick = () => setView(b.dataset.view as ViewName);
  });
}

function setView(v: ViewName): void {
  st.view = v;
  st.groups = v === "ready" ? new Set<Group>(["ready"]) : v === "human" ? new Set<Group>(["human", "gate"])
    : v === "branch" ? new Set<Group>(["branch"]) : new Set<Group>();
  const list = v === "list";
  $("table").hidden = !list;
  $("stage").hidden = list;
  renderRail();
  applyFilter();
  if (list) renderTable(); else canvas.scheduleMini(true);
}

/* ── 집계 카드 ── */
function renderCards(): void {
  const p = st.snap?.payload;
  const c = p?.counts ?? {};
  const reasons = attentionReasons(st.snap);
  const gt = c.gate_turn ?? 0, gv = c.gate_verdict ?? 0, gw = c.gate_wait ?? 0;
  const cards: { id: Group | "attention"; label: string; value: number; cls?: string; sub?: string }[] = [
    { id: "ready", label: "처리 가능", value: c.ready ?? 0, cls: "c-ready" },
    { id: "in_progress", label: "진행 중", value: c.in_progress ?? 0, cls: "c-in_progress" },
    { id: "waiting", label: "선행 대기", value: c.waiting ?? 0, cls: "c-waiting" },
    { id: "blocked", label: "차단", value: c.blocked ?? 0, cls: "c-blocked" },
    { id: "human", label: "사람 작업", value: c.human ?? 0, cls: "c-human" },
    { id: "gate", label: "게이트", value: gt + gv + gw, cls: "c-gate_turn", sub: `사람 차례 ${gt} · 판정 미기록 ${gv} · 선행 대기 ${gw}` },
    { id: "branch", label: "미머지 브랜치", value: c.branch ?? 0, cls: "c-branch" },
    { id: "attention", label: "확인 필요", value: reasons.length, sub: reasons.length ? "사유 목록 보기" : "판정 불가 축 없음" },
  ];
  $("cards").innerHTML = cards.map((k) => {
    const pressed = k.id === "attention" ? st.attentionOpen : st.groups.has(k.id as Group);
    const extra = k.id === "attention" ? ` attn${k.value ? "" : " zero"}` : "";
    return `<button class="card${extra}" type="button" data-card="${k.id}" data-testid="card-${k.id}" aria-pressed="${pressed}">
      <span class="lb">${k.cls ? `<i class="${k.cls}"></i>` : ""}${esc(k.label)}</span>
      <span class="vl" data-testid="card-${k.id}-value">${p || k.id === "attention" ? k.value : "–"}</span>
      ${k.sub ? `<span class="sb">${esc(k.sub)}</span>` : ""}</button>`;
  }).join("");
  $("cards").querySelectorAll<HTMLElement>("[data-card]").forEach((b) => b.onclick = () => {
    const id = b.dataset.card as Group | "attention";
    if (id === "attention") { st.attentionOpen = !st.attentionOpen; renderAttention(); renderCards(); return; }
    if (st.groups.has(id)) st.groups.delete(id); else st.groups.add(id);
    applyFilter();
  });
}

function renderAttention(): void {
  const el = $("attention");
  el.hidden = !st.attentionOpen;
  if (!st.attentionOpen) return;
  const reasons = attentionReasons(st.snap);
  el.innerHTML = reasons.length
    ? `<h3>확인 필요 ${reasons.length}건 — 이번 스냅샷에서 판정되지 않았거나 실패한 축</h3><ul data-testid="attention-list">${reasons.map((r) => `<li data-kind="${esc(r.kind)}"><b>[${esc(r.kind)}]</b> ${esc(r.text)}</li>`).join("")}</ul>`
    : '<p class="okline" data-testid="attention-list">확인 필요 0건 — 원격 조회 3종 ok · 어댑터 ok · 스냅샷 24시간 이내 · 정합성 경고 없음</p>';
}

/* ── 상태 줄 ── */
function renderStatus(): void {
  const s = st.snap;
  const el = $("snap-line");
  if (!st.ws) { el.textContent = "작업공간을 추가하라"; return; }
  if (!s) { el.innerHTML = `<b>${esc(st.ws.name)}</b> · 저장된 스냅샷 없음 — 새로고침으로 수집`; return; }
  const scans = s.payload ? Object.entries(s.payload.scans || {}).map(([k, v]) => `${SCAN_NAME[k] ?? k} ${esc(v.status)}`).join(" · ") : "페이로드 없음";
  const src = (k: keyof Snapshot["sources"]) => `${SOURCE_NAME[k]} ${esc(s.sources[k].status)}`;
  el.innerHTML = `저장된 스냅샷 · <b>${fmtTime(s.collectedAt)}</b>${s.stale ? ' · <span class="stale">24시간 초과</span>' : ""}`
    + ` · 원격 조회: ${scans} · ${src("harness")} · ${src("git")} · ${src("github")}`
    + (s.payload ? ` · 기준 커밋 ${esc(s.payload.base || "미상")} · 스테이지 ${esc(s.payload.current_stage)}` : "");
  $<HTMLButtonElement>("refresh").disabled = st.busy;
  $("refresh").textContent = st.busy ? "수집 중…" : "새로고침";
}

/* ── 도구(필터 선택지) ── */
function renderTools(): void {
  const N = nodes();
  const uniq = (key: keyof GraphNode) => [...new Set(keys().map((k) => N[k][key] as string | undefined).filter(Boolean))].sort() as string[];
  const opts = (el: HTMLSelectElement, label: string, values: string[], cur: string) => {
    el.innerHTML = `<option value="">${label} 전체</option>` + values.map((v) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
  };
  const stages = (st.snap?.payload?.stages ?? []).filter((s) => uniq("stage").includes(s));
  opts($<HTMLSelectElement>("fstage"), "스테이지", stages, st.stage);
  opts($<HTMLSelectElement>("flayer"), "레이어", uniq("layer"), st.layer);
  opts($<HTMLSelectElement>("ftrack"), "트랙", uniq("track"), st.track);
}

/* ── 목록 보기(표) ── */
function renderTable(): void {
  const N = nodes();
  const ks = orderedKeys();
  const row = (k: string) => {
    const n = N[k];
    const who = n.kind === "task" ? (n.owner && n.owner !== "claude" ? `담당 ${n.owner}` : "") : n.kind === "gate" ? `담당 ${n.assignee ?? ""}` : (n.reason ?? "");
    return `<tr data-key="${esc(k)}" tabindex="0" class="${k === st.selected ? "sel" : ""}"><td>${KIND_LABEL[n.kind]}</td>
      <td class="id">${esc(n.kind === "branch" ? n.id : n.short)}</td>
      <td class="st"><span class="sw c-${esc(n.state)}"></span>${esc(n.label)}</td>
      <td>${esc(n.title)}</td><td>${esc(n.stage ?? "")}</td><td>${esc(n.layer ?? "")}</td><td>${esc(who)}</td>
      <td class="num">${n.unlocks || ""}</td></tr>`;
  };
  $("table").innerHTML = `<div class="cap">${ks.length}건${filtering() ? ` (전체 ${keys().length})` : ""} · ↑↓ 이동 · Enter 상세 · Esc 해제</div>
    <table><thead><tr><th>종류</th><th>ID</th><th>상태</th><th>제목</th><th>스테이지</th><th>레이어</th><th>담당·사유</th><th>풀림</th></tr></thead>
    <tbody>${ks.map(row).join("")}</tbody></table>`;
  $("table").querySelectorAll<HTMLElement>("tr[data-key]").forEach((tr) => {
    tr.onclick = () => canvas.select(tr.dataset.key as string, false);
    tr.onkeydown = (ev) => { if (ev.key === "Enter") canvas.select(tr.dataset.key as string, false); };
  });
}
function markTableSel(): void {
  $("table").querySelectorAll<HTMLElement>("tr[data-key]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.key === st.selected));
}

/* ── 상세 패널 ── */
function linkList(list: NodeLink[], empty: string): string {
  const N = nodes();
  if (!list.length) return `<p class="none">${empty}</p>`;
  return `<ul>${list.map((l) => {
    const live = l.open && N[l.key];
    const stx = l.kind === "branch" ? "미머지" : (l.open ? (N[l.key] ? N[l.key].label : l.status) : "완료·해소");
    return `<li><button class="link${live ? "" : " off"}" type="button" ${live ? `data-key="${esc(l.key)}"` : "disabled"}>`
      + `<span class="sw ${live ? "c-" + N[l.key].state : ""}"></span><b class="mono">${esc(l.id)}</b></button>`
      + ` <span class="none">${esc(stx)} · ${esc(l.edge)}</span><span class="lt" title="${esc(l.title)}">${esc(l.title)}</span></li>`;
  }).join("")}</ul>`;
}

function prFactsFor(n: GraphNode): { number: number; url: string; title: string; isDraft: boolean; reviewDecision: string; checks?: string }[] {
  const gh = st.snap?.sources.github;
  if (!gh || gh.status !== "ok" || !gh.data) return [];
  const branch = n.kind === "branch" ? n.id : (n.session || "");
  if (!branch) return [];
  return gh.data.filter((p) => p.headRefName === branch);
}

function renderDetail(): void {
  const d = $("detail");
  const k = st.selected;
  const N = nodes();
  if (!k || !N[k]) { d.classList.remove("open"); d.innerHTML = ""; return; }
  const n = N[k];
  const tags: string[] = [];
  if (n.kind === "task") {
    tags.push(`스테이지 ${n.stage}`, `레이어 ${n.layer}`, `트랙 ${n.track}`, `과목 ${n.subject}`, `우선순위 P${n.priority}`, `담당 ${n.owner}`);
    if (n.updated) tags.push(`갱신 ${n.updated}`);
  } else if (n.kind === "gate") {
    tags.push(`종류 ${n.gate_kind}`, `담당 ${n.assignee}`);
    if (n.requested) tags.push(`요청 ${n.requested}`);
    if (n.days != null) tags.push(`${n.days}일 경과${n.overdue ? " · 리마인드 초과" : ""}`);
  } else {
    if (n.ahead != null) tags.push(`트렁크보다 ${n.ahead}커밋 앞`);
    if (n.age_days != null) tags.push(`마지막 커밋 ${n.age_days}일 전`);
    (n.disposal_labels || []).forEach((l) => tags.push(`라벨 ${l}`));
    if (n.synthetic) tags.push("합성 픽스처");
  }
  const { up, down } = canvas.chain;
  let body = `<button class="btn icon close" type="button" id="close-detail" title="닫기 (Esc)">×</button>
    <div class="kk">${KIND_LABEL[n.kind]}${n.flow ? ` · 흐름 ${n.flow}` : ""}</div>
    <h2>${esc(n.title)}</h2><div class="fid">${esc(n.id)}</div>
    <div class="row"><span class="tag st c-${esc(n.state)}" data-testid="detail-state">${esc(n.label)}</span>${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    <p class="none" data-testid="chain-count">선행 사슬 ${up.size - 1} · 후속 사슬 ${down.size - 1}</p>`;
  const why = [n.reason, n.detail].filter(Boolean);
  if (n.session) why.push(`브랜치 ${n.session}`);
  if (why.length) body += `<h3>지금 상태의 이유</h3><div class="why">${why.map(esc).join("<br>")}</div>`;
  if (n.wait_chain && n.wait_chain.length) body += `<h3>기다리는 경로</h3><div class="chain">${n.wait_chain.map(esc).join(" ← ")}</div>`;
  if (n.kind === "branch") {
    const tl = (label: string, ids: string[]) => ids.length ? `<h3>${label}</h3><ul>${ids.map((id) => {
      const key = "t:" + id;
      return N[key] ? `<li><button class="link" type="button" data-key="${esc(key)}"><b class="mono">${esc(id)}</b></button> ${esc(N[key].title)}</li>`
        : `<li><b class="mono">${esc(id)}</b> <span class="none">— 트렁크 대장에 없는 태스크(이 브랜치에만 있다)</span></li>`;
    }).join("")}</ul>` : "";
    body += tl("이 브랜치에 완료분이 있는 태스크 (머지되면 풀린다)", n.done_tasks ?? [])
      + tl("이 브랜치의 세션이 진행 중인 태스크", (n.claimed_tasks ?? []).concat(n.foreign_tasks ?? []));
    if (n.last_commit_at) body += `<h3>마지막 커밋</h3><p class="none">${esc(n.last_commit_at)}</p>`;
  } else {
    body += `<h3>먼저 끝나야 하는 것 (선행)</h3>${linkList(n.preds, "선행 없음 — 이 창 앞에 걸린 것이 없다")}`;
    body += `<h3>끝나면 풀리는 것 (후속)</h3>` + (n.unlocks ? `<p class="none">끝까지 따라가면 미종결 작업 ${n.unlocks}건이 이것을 기다린다.</p>` : "") + linkList(n.succs, "후속 없음");
  }
  // PR 사실 — gh 어댑터가 준 것을 덧붙일 뿐 상태 판정을 바꾸지 않는다
  const prs = prFactsFor(n);
  const gh = st.snap?.sources.github;
  if (n.kind === "branch" || n.session) {
    body += `<h3>PR 사실 (gh)</h3>` + (prs.length
      ? `<ul class="pr">${prs.map((p) => `<li><button class="link" type="button" data-url="${esc(p.url)}">#${p.number}</button> ${esc(p.title)}${p.isDraft ? " · 초안" : ""}${p.reviewDecision ? ` · ${esc(p.reviewDecision)}` : ""}${p.checks ? ` · 검사 ${esc(p.checks)}` : ""}</li>`).join("")}</ul>`
      : `<p class="none">${gh?.status === "ok" ? "이 브랜치의 열린 PR 없음" : `조회 안 됨 (gh ${esc(gh?.status ?? "없음")}${gh?.reason ? ` — ${esc(gh.reason)}` : ""})`}</p>`);
  }
  if (n.acceptance && n.acceptance.length) body += `<h3>완료 조건 ${n.acceptance.length}개</h3><ol>${n.acceptance.map((a) => `<li>${esc(a)}</li>`).join("")}</ol>`;
  if (n.notes) body += `<h3>노트</h3><pre class="note">${esc(n.notes)}</pre>`;
  body += `<h3>내 메모 (앱에만 저장)</h3><textarea id="memo" data-testid="memo" placeholder="이 창에 대한 메모 — 대장에는 쓰지 않는다">${esc(st.layout.notes[k] ?? "")}</textarea>`;
  if (n.cmd) {
    const cmdLabel = n.kind === "gate" ? "해소 명령 (근거를 채워 실행)" : n.kind === "branch" ? "확인 명령 (읽기 전용)" : "착수 명령";
    body += `<h3>${cmdLabel}</h3><div class="cmd"><code id="cmdtext">${esc(n.cmd)}</code><button class="btn" type="button" id="copy">복사</button></div>`;
  }
  body += `<h3>원본</h3><div class="links">`;
  if (n.kind !== "branch") body += `<button class="btn" type="button" id="open-file">${n.kind === "task" ? "태스크 YAML 열기" : "gates.yaml 열기"}</button>`;
  body += `</div>`;
  // 동작 버튼 — 확인 대화 → backlog.py 실행 → 결과 그대로 표시
  const actions: string[] = [];
  if (n.kind === "task" && n.state === "ready") actions.push(`<button class="btn primary" type="button" data-action="start">착수 (backlog.py start)</button>`);
  if (n.kind === "task" && (n.state === "in_progress" || n.state === "review")) actions.push(`<button class="btn primary" type="button" data-action="done">완료 (backlog.py done)</button>`);
  if (n.kind === "gate" && n.state === "gate_turn") actions.push(`<button class="btn primary" type="button" data-action="gates_clear">게이트 해소 (gates clear)</button>`);
  if (n.kind === "gate" && n.state === "gate_verdict") actions.push(`<p class="none">판정 결과 미기록 — 판정문이 있으면 <code>backlog.py gates amend --verdict</code>로 먼저 기록한다(이 앱은 그 명령을 대신 실행하지 않는다).</p>`);
  body += `<h3>동작</h3><div class="actions">${actions.join("") || '<p class="none">이 상태에서 앱이 대신 실행할 동작이 없다</p>'}</div>`;
  if (st.lastResult && st.lastResult.key === k) body += resultHtml(st.lastResult.result);
  d.innerHTML = body;
  d.classList.add("open");
  d.scrollTop = 0;
  $("close-detail").onclick = () => canvas.clearSelection();
  d.querySelectorAll<HTMLElement>(".link[data-key]").forEach((b) => b.onclick = () => canvas.select(b.dataset.key as string, true));
  d.querySelectorAll<HTMLElement>(".link[data-url]").forEach((b) => b.onclick = () => void st.api.openExternal(b.dataset.url as string));
  const copy = document.getElementById("copy");
  if (copy && n.cmd) copy.onclick = () => copyText(n.cmd as string, copy);
  const of = document.getElementById("open-file");
  if (of && st.ws) of.onclick = async () => {
    const r = await st.api.openTaskFile(st.ws!.id, k);
    of.textContent = r.ok ? "열었다" : `열 수 없음 — ${r.reason ?? ""}`;
  };
  const memo = document.getElementById("memo") as HTMLTextAreaElement | null;
  if (memo) memo.oninput = () => { const v = memo.value; if (v.trim()) st.layout.notes[k] = v; else delete st.layout.notes[k]; scheduleLayoutSave(); };
  d.querySelectorAll<HTMLElement>("[data-action]").forEach((b) => b.onclick = () => openActionModal(n, b.dataset.action as ActionKind));
}

function resultHtml(r: ActionResult): string {
  return `<div class="result ${r.ok ? "ok" : "fail"}" data-testid="action-result">
    <b>${r.ok ? "성공" : "실패"}</b> · exit code ${r.exitCode == null ? "없음" : r.exitCode}${r.reason ? ` · ${esc(r.reason)}` : ""}
    ${r.command.length ? `<pre>$ ${esc(r.command.join(" "))}</pre>` : ""}
    ${r.stdout ? `<pre>${esc(r.stdout)}</pre>` : ""}${r.stderr ? `<pre>${esc(r.stderr)}</pre>` : ""}</div>`;
}

function copyText(text: string, btn: HTMLElement): void {
  const done = () => { btn.textContent = "복사됨"; setTimeout(() => { btn.textContent = "복사"; }, 1400); };
  const fallback = () => {
    const el = document.getElementById("cmdtext"); if (!el) return;
    const r = document.createRange(); r.selectNodeContents(el);
    const s = getSelection(); s?.removeAllRanges(); s?.addRange(r);
    btn.textContent = "선택됨 — Ctrl+C";
  };
  try { navigator.clipboard.writeText(text).then(done, fallback); } catch { fallback(); }
}

/* ── 모달 ── */
function closeModal(): void { $("modal").hidden = true; $("modal").innerHTML = ""; }
function openModal(html: string): HTMLElement {
  const m = $("modal");
  m.innerHTML = `<div class="box" role="dialog" aria-modal="true">${html}</div>`;
  m.hidden = false;
  m.onclick = (ev) => { if (ev.target === m) closeModal(); };
  return m.querySelector(".box") as HTMLElement;
}

function openActionModal(n: GraphNode, kind: ActionKind): void {
  if (!st.ws) return;
  const asFlag = n.kind === "gate" && n.assignee && n.assignee !== "claude" ? ` --as ${n.assignee}` : "";
  const preview = kind === "start" ? `backlog.py start ${n.id}`
    : kind === "gates_clear" ? `backlog.py gates clear ${n.id}${asFlag} --evidence "…"`
    : `backlog.py done ${n.id} --artifact "…"`;
  const title = kind === "start" ? "착수" : kind === "gates_clear" ? "게이트 해소" : "완료";
  const box = openModal(`<h2>${title} — ${esc(n.short)}</h2>
    <p class="hint">앱은 대장을 직접 쓰지 않는다. 아래 명령을 작업공간(${esc(st.ws.root)})에서 실행하고 결과를 그대로 보여 준다.</p>
    <code class="cmdline">${esc(preview)}</code>
    ${kind === "gates_clear" ? `<label>근거 (--evidence · 커밋 해시·PR 참조 필수)<textarea id="f-evidence" data-testid="f-evidence"></textarea></label>
      <label>--no-base 사유 (커밋과 무관한 근거일 때만 · 비우면 생략)<input type="text" id="f-nobase"></label>` : ""}
    ${kind === "done" ? `<label>증적 (--artifact · 한 줄에 하나 · PR 참조 포함)<textarea id="f-artifacts" data-testid="f-artifacts"></textarea></label>` : ""}
    <div class="err" id="f-err"></div>
    <div class="foot"><button class="btn" type="button" id="f-cancel">취소</button><button class="btn primary" type="button" id="f-run" data-testid="f-run">실행</button></div>`);
  (box.querySelector("#f-cancel") as HTMLElement).onclick = closeModal;
  (box.querySelector("#f-run") as HTMLButtonElement).onclick = async () => {
    const ev = (box.querySelector("#f-evidence") as HTMLTextAreaElement | null)?.value ?? "";
    const nb = (box.querySelector("#f-nobase") as HTMLInputElement | null)?.value ?? "";
    const arts = ((box.querySelector("#f-artifacts") as HTMLTextAreaElement | null)?.value ?? "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    const err = box.querySelector("#f-err") as HTMLElement;
    if (kind === "gates_clear" && !ev.trim()) { err.textContent = "근거가 비어 있다"; return; }
    if (kind === "done" && !arts.length) { err.textContent = "증적이 하나 이상 필요하다"; return; }
    (box.querySelector("#f-run") as HTMLButtonElement).disabled = true;
    const result = await st.api.runAction({ workspaceId: st.ws!.id, kind, args: {
      id: n.id, evidence: kind === "gates_clear" ? ev : undefined, assignee: kind === "gates_clear" ? n.assignee : undefined,
      noBase: kind === "gates_clear" && nb.trim() ? nb : undefined, artifacts: kind === "done" ? arts : undefined } });
    st.lastResult = { key: n.key, result };
    closeModal();
    renderDetail();
    if (result.ok) setTimeout(() => void refreshNow(), 400);   // 성공 시 자동 새로고침
  };
}

function openWorkspaceModal(edit: Workspace | null): void {
  const electron = st.api.mode() === "electron";
  const w = edit;
  const box = openModal(`<h2>${w ? "연결 및 설정 — " + esc(w.name) : "작업공간 추가"}</h2>
    ${w ? `<p class="hint">경로 <code>${esc(w.root)}</code> · 종류 ${w.kind === "harness" ? "harness(work_graph.py 있음)" : "git(그래프 없음)"}</p>`
      : `<label>폴더 경로 (scripts/harness/work_graph.py 또는 .git이 있어야 한다)<div class="pathrow"><input type="text" id="f-path" data-testid="f-path" placeholder="C:\\Users\\kiki\\Desktop\\__AI\\WhyMath">${electron ? '<button class="btn" type="button" id="f-pick">폴더 선택…</button>' : ""}</div></label>`}
    <label>이름<input type="text" id="f-name" value="${esc(w?.name ?? "")}" placeholder="비우면 폴더 이름"></label>
    <label class="row"><input type="checkbox" id="f-remote"${w?.options.remote ? " checked" : ""}> 원격 조회 포함(미머지 done·원격 claim·고립 브랜치 — 느리고 네트워크 필요; 끄면 --no-remote)</label>
    <label class="row"><input type="checkbox" id="f-github"${w?.options.github ? " checked" : ""}> gh로 열린 PR 목록 덧붙이기</label>
    <label>python 실행 파일 (비우면 python3 → python → py -3 순 탐색)<input type="text" id="f-python" value="${esc(w?.options.python ?? "")}"></label>
    <p class="hint">${electron ? "" : "픽스처 모드 — 여기서는 추가·변경이 저장되지 않는다."}</p>
    <div class="err" id="f-err"></div>
    <div class="foot">${w ? '<button class="btn danger" type="button" id="f-remove">이 작업공간 제거</button>' : ""}
      <button class="btn" type="button" id="f-cancel">취소</button><button class="btn primary" type="button" id="f-save" data-testid="f-save">${w ? "저장" : "추가"}</button></div>`);
  (box.querySelector("#f-cancel") as HTMLElement).onclick = closeModal;
  const pick = box.querySelector("#f-pick") as HTMLElement | null;
  if (pick) pick.onclick = async () => { const p = await st.api.pickFolder(); if (p) (box.querySelector("#f-path") as HTMLInputElement).value = p; };
  const rm = box.querySelector("#f-remove") as HTMLElement | null;
  if (rm && w) rm.onclick = async () => {
    if (!confirm(`작업공간 "${w.name}"을(를) 목록에서 제거할까? (폴더는 건드리지 않는다)`)) return;
    await st.api.removeWorkspace(w.id);
    closeModal();
    st.workspaces = await st.api.listWorkspaces();
    st.ws = null; st.snap = null;
    await selectWorkspace(st.workspaces[0]?.id ?? null);
  };
  (box.querySelector("#f-save") as HTMLElement).onclick = async () => {
    const err = box.querySelector("#f-err") as HTMLElement;
    const options = {
      remote: (box.querySelector("#f-remote") as HTMLInputElement).checked,
      github: (box.querySelector("#f-github") as HTMLInputElement).checked,
      python: (box.querySelector("#f-python") as HTMLInputElement).value.trim() || undefined,
    };
    const name = (box.querySelector("#f-name") as HTMLInputElement).value;
    if (w) {
      await st.api.updateWorkspace(w.id, { name, options });
      st.workspaces = await st.api.listWorkspaces();
      st.ws = st.workspaces.find((x) => x.id === w.id) ?? null;
      closeModal(); renderRail(); renderStatus();
      return;
    }
    const path = (box.querySelector("#f-path") as HTMLInputElement).value.trim();
    const r = await st.api.addWorkspace({ path, name, options });
    if (!r.ok) { err.textContent = r.reason; return; }
    closeModal();
    st.workspaces = await st.api.listWorkspaces();
    await selectWorkspace(r.workspace.id);
  };
}

/* ── 작업공간 선택·스냅샷 적용 ── */
async function selectWorkspace(id: string | null): Promise<void> {
  st.ws = st.workspaces.find((w) => w.id === id) ?? null;
  st.selected = null; st.lastResult = null; st.attentionOpen = false;
  try { if (st.ws) localStorage.setItem("wg:ws", st.ws.id); } catch { /* 저장 불가 — 무시(편의 기능) */ }
  if (!st.ws) { st.snap = null; st.layout = { positions: {}, view: null, notes: {} }; applySnapshot(); return; }
  try {
    st.snap = await st.api.loadSnapshot(st.ws.id);
    st.layout = await st.api.loadLayout(st.ws.id);
  } catch (e) {
    const ex = e as Error;
    st.snap = null;
    showEmpty(`저장된 스냅샷을 읽지 못했다\n${ex.name}: ${ex.message}`);
  }
  applySnapshot();
}

function showEmpty(text: string | null): void {
  const el = $("empty");
  el.hidden = !text;
  el.innerHTML = text ? text.split("\n").map((l, i) => i === 0 ? `<b>${esc(l)}</b>` : esc(l)).join("<br>") : "";
}

/** 첫 화면 (HARN-208) — 작업공간이 하나도 없을 때. 자동 찾기가 실패했으면 찾아본 자리와 사유를 그대로 보이고,
    'WhyMath 폴더 선택' 한 번으로 연결한다. WhyMath 저장소가 아닌 폴더는 거부하고 사유를 보인다. */
function showWelcome(): void {
  const el = $("empty");
  const electron = st.api.mode() === "electron";
  const tried = st.discovery?.tried ?? [];
  el.hidden = false;
  el.innerHTML = `<div class="welcome" data-testid="welcome">
    <b>WhyMath 저장소를 연결하세요</b>
    <p>${st.discovery ? `처음 실행이라 저장소 폴더를 ${tried.length}곳에서 찾아봤지만 찾지 못했습니다.` : "등록된 작업공간이 없습니다."}
    <br>WhyMath 폴더(안에 <code>scripts\\harness\\work_graph.py</code>가 있는 폴더)를 한 번 골라 주세요. 다음부터는 바로 열립니다.</p>
    ${electron ? '<button class="btn primary" type="button" id="welcome-pick" data-testid="welcome-pick">WhyMath 폴더 선택…</button>'
      : "<p>픽스처 모드 — 여기서는 폴더를 연결할 수 없습니다(설치한 앱에서만).</p>"}
    <div class="err" id="welcome-err" data-testid="welcome-err"></div>
    ${tried.length ? `<details><summary>찾아본 자리 ${tried.length}곳</summary><ul data-testid="welcome-tried">${
      tried.map((t) => `<li><code>${esc(t.path)}</code> — ${esc(t.reason)}</li>`).join("")}</ul></details>` : ""}
  </div>`;
  const pick = el.querySelector("#welcome-pick") as HTMLElement | null;
  if (!pick) return;
  pick.onclick = async () => {
    const err = el.querySelector("#welcome-err") as HTMLElement;
    err.textContent = "";
    const p = await st.api.pickFolder();
    if (!p) return;   // 대화상자를 닫았다 — 아무것도 바꾸지 않는다
    const r = await st.api.addWorkspace({ path: p, requireHarness: true });
    if (!r.ok) { err.textContent = r.reason; return; }
    st.workspaces = await st.api.listWorkspaces();
    await selectWorkspace(r.workspace.id);
    if (!st.snap) void refreshNow();   // 연결 직후 한 번 수집한다 — 빈 화면에서 새로고침을 찾게 하지 않는다
  };
}

function applySnapshot(): void {
  const p = st.snap?.payload ?? null;
  canvas.setData(p, st.layout.positions, st.layout.notes);
  renderRail(); renderTools(); renderStatus(); renderAttention(); renderCards(); renderDetail();
  applyFilter();
  if (st.view === "list") renderTable();
  if (!st.ws) showWelcome();
  else if (!st.snap) showEmpty(`저장된 스냅샷이 없다\n오른쪽 위 '새로고침'을 누르면 ${st.ws.root}에서 work_graph.py를 실행해 수집한다`);
  else if (!p) showEmpty(`이 스냅샷에는 그래프가 없다\n${SOURCE_NAME.harness} ${st.snap.sources.harness.status} — ${st.snap.sources.harness.reason ?? ""}`);
  else showEmpty(null);
  if (p) { if (st.layout.view) canvas.setView({ x: st.layout.view.x, y: st.layout.view.y, z: st.layout.view.scale }); else canvas.initialView(); }
}

async function refreshNow(): Promise<void> {
  if (!st.ws || st.busy) return;
  st.busy = true; renderStatus();
  try {
    st.snap = await st.api.refresh(st.ws.id);
    st.layout = await st.api.loadLayout(st.ws.id);   // 창 좌표·메모는 API가 돌려준 것을 쓴다(브라우저 저장소 아님)
  } catch (e) {
    const ex = e as Error;
    showEmpty(`수집 실패\n${ex.name}: ${ex.message}`);
  } finally {
    st.busy = false;
  }
  const keep = st.selected;
  applySnapshot();
  if (keep && nodes()[keep]) canvas.select(keep, false);
}

/* ── 레이아웃 저장(디바운스) ── */
const scheduleLayoutSave = debounce(() => {
  if (!st.ws) return;
  st.layout.positions = canvas.positionsCopy;
  void st.api.saveLayout(st.ws.id, st.layout);
}, 250);
const scheduleViewSave = debounce(() => {
  if (!st.ws || !st.snap?.payload) return;
  const v: View = canvas.view;
  st.layout.view = { x: v.x, y: v.y, scale: v.z };
  void st.api.saveLayout(st.ws.id, st.layout);
}, 600);

/* ── 조작 연결 ── */
function bind(): void {
  $("refresh").onclick = () => void refreshNow();
  $("ws-add").onclick = () => openWorkspaceModal(null);
  $("ws-settings").onclick = () => openWorkspaceModal(st.ws);
  $<HTMLInputElement>("q").addEventListener("input", (ev) => { st.query = (ev.target as HTMLInputElement).value.trim().toLowerCase(); applyFilter(); });
  $<HTMLInputElement>("q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { const hit = orderedKeys()[0]; if (hit) canvas.select(hit, st.view !== "list"); }
  });
  $<HTMLSelectElement>("fstage").onchange = (ev) => { st.stage = (ev.target as HTMLSelectElement).value; applyFilter(); };
  $<HTMLSelectElement>("flayer").onchange = (ev) => { st.layer = (ev.target as HTMLSelectElement).value; applyFilter(); };
  $<HTMLSelectElement>("ftrack").onchange = (ev) => { st.track = (ev.target as HTMLSelectElement).value; applyFilter(); };
  $<HTMLSelectElement>("fkind").onchange = (ev) => { st.kind = (ev.target as HTMLSelectElement).value; applyFilter(); };
  $("zoom-in").onclick = () => canvas.zoomCenter(1.25);
  $("zoom-out").onclick = () => canvas.zoomCenter(0.8);
  $("fit").onclick = () => canvas.fitAll();
  $("reset-pos").onclick = async () => {
    if (!st.ws) return;
    st.layout.positions = {};
    await st.api.resetLayout(st.ws.id);
    st.layout = await st.api.loadLayout(st.ws.id);
    canvas.resetPositions();
    if (st.selected) canvas.select(st.selected, false);
  };
  $("legend").addEventListener("toggle", () => { try { localStorage.setItem("wg:legend", String(($("legend") as HTMLDetailsElement).open)); } catch { /* 무시 */ } });
  try { const lg = localStorage.getItem("wg:legend"); if (lg != null) ($("legend") as HTMLDetailsElement).open = lg === "true"; } catch { /* 무시 */ }
  document.addEventListener("keydown", (ev) => {
    const tag = (ev.target as HTMLElement).tagName;
    const typing = /INPUT|SELECT|TEXTAREA/.test(tag);
    if (ev.key === "Escape") {
      if (!$("modal").hidden) { closeModal(); return; }
      if (typing) (ev.target as HTMLElement).blur();
      canvas.clearSelection(); return;
    }
    if (typing || !$("modal").hidden) return;
    if (ev.key === "/") { ev.preventDefault(); $("q").focus(); }
    else if (ev.key === "+" || ev.key === "=") canvas.zoomCenter(1.25);
    else if (ev.key === "-") canvas.zoomCenter(0.8);
    else if (ev.key === "0") canvas.fitAll();
    else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const ks = orderedKeys(); if (!ks.length) return;
      const i = st.selected ? ks.indexOf(st.selected) : -1;
      const next = ev.key === "ArrowDown" ? ks[Math.min(ks.length - 1, i + 1)] : ks[Math.max(0, i <= 0 ? 0 : i - 1)];
      canvas.select(next, st.view !== "list");
      const tr = $("table").querySelector<HTMLElement>(`tr[data-key="${CSS.escape(next)}"]`); tr?.scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter" && st.selected) canvas.select(st.selected, st.view !== "list");
    else if ((ev.key === "f" || ev.key === "F") && st.selected) canvas.focusOn(st.selected);
  });
}

async function boot(): Promise<void> {
  bind();
  st.workspaces = await st.api.listWorkspaces();
  try { st.discovery = await st.api.discovery(); } catch { st.discovery = null; }
  let remembered: string | null = null;
  try { remembered = localStorage.getItem("wg:ws"); } catch { /* 무시 */ }
  const first = st.workspaces.find((w) => w.id === remembered) ?? st.workspaces[0] ?? null;
  await selectWorkspace(first?.id ?? null);
}

void boot();
