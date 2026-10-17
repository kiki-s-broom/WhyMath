/* 캔버스 엔진 (HARN-206) — scripts/harness/work_graph_page.html(HARN-182)의 vanilla JS 엔진을 TS로 옮겼다.
   world transform · 휠/버튼 확대축소 · 끌어 이동 · 창 드래그(좌표는 호출자가 저장) · 프레임 · 연결선 SVG ·
   미니맵 · 선택 시 선행/후속 사슬 강조(나머지 dim). 그리는 것은 페이로드의 nodes·edges·frames 그대로다. */
import type { GraphEdge, GraphNode, Payload } from "../shared/types";

export const KIND_LABEL: Record<string, string> = { task: "작업", gate: "게이트", branch: "브랜치" };
const STATE_VAR: Record<string, string> = {
  ready: "--ready", in_progress: "--run", review: "--run", waiting: "--wait", blocked: "--block",
  human: "--human", gate_turn: "--human", gate_verdict: "--block", gate_wait: "--human", branch: "--branch",
};
const Z_MIN = 0.06, Z_MAX = 1.6, LOD_Z = 0.42;

export const esc = (s: unknown): string => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

export interface View { x: number; y: number; z: number }
export type Positions = Record<string, { x: number; y: number }>;

export interface CanvasHandlers {
  onSelect: (key: string | null) => void;
  onMoved: (positions: Positions) => void;
  onView: (view: View) => void;
}

export class GraphCanvas {
  readonly view: View = { x: 40, y: 40, z: 0.6 };
  private data: Payload | null = null;
  private keys: string[] = [];
  private positions: Positions = {};
  private notes: Record<string, string> = {};
  private edgeByNode: Record<string, number[]> = {};
  private selected: string | null = null;
  private upSet = new Set<string>();
  private downSet = new Set<string>();
  private matchFn: ((n: GraphNode) => boolean) | null = null;
  private queryOn = false;
  private miniBase: HTMLCanvasElement | null = null;
  private miniQueued = false;
  private miniScale = 1;
  private pointers = new Map<number, { x: number; y: number }>();
  private gesture: Record<string, unknown> | null = null;

  constructor(
    private readonly stage: HTMLElement,
    private readonly world: HTMLElement,
    private readonly mini: HTMLCanvasElement,
    private readonly zoomrd: HTMLElement,
    private readonly h: CanvasHandlers,
  ) {
    this.bindPointer();
    this.bindMini();
    window.addEventListener("resize", () => this.scheduleMini());
    window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => this.scheduleMini(true));
  }

  /* ── 데이터 ── */
  setData(data: Payload | null, positions: Positions, notes: Record<string, string>): void {
    this.data = data;
    this.keys = data ? Object.keys(data.nodes) : [];
    this.positions = {};
    for (const [k, p] of Object.entries(positions)) if (data && data.nodes[k]) this.positions[k] = { x: p.x, y: p.y };
    this.notes = notes;
    this.edgeByNode = {};
    (data?.edges ?? []).forEach((e, i) => {
      (this.edgeByNode[e.src] ||= []).push(i);
      (this.edgeByNode[e.dst] ||= []).push(i);
    });
    this.selected = null; this.upSet = new Set(); this.downSet = new Set();
    this.drawWorld();
    this.applyClasses();
    this.scheduleMini(true);
  }

  get nodes(): Record<string, GraphNode> { return this.data?.nodes ?? {}; }
  get positionsCopy(): Positions { return JSON.parse(JSON.stringify(this.positions)) as Positions; }
  get selectedKey(): string | null { return this.selected; }
  get chain(): { up: Set<string>; down: Set<string> } { return { up: this.upSet, down: this.downSet }; }

  pos(k: string): { x: number; y: number } {
    const p = this.positions[k];
    const n = this.nodes[k];
    return p ? { x: p.x, y: p.y } : { x: n.x, y: n.y };
  }

  resetPositions(): void {
    this.positions = {};
    this.drawWorld();
    this.applyClasses();
    this.scheduleMini(true);
  }

  /* ── 그리기 ── */
  private winHtml(k: string): string {
    const n = this.nodes[k];
    const p = this.pos(k);
    const meta: (string | { cls: string; text: string })[] = [];
    if (n.kind === "task") {
      meta.push(n.stage ?? "", n.layer ?? "");
      if ((n.priority ?? 9) <= 2) meta.push({ cls: "p" + n.priority, text: "P" + n.priority });
      if (n.owner && n.owner !== "claude") meta.push(`담당 ${n.owner}`);
    } else if (n.kind === "gate") {
      meta.push(`담당 ${n.assignee ?? ""}`);
      if (n.days != null) meta.push(`${n.days}일 경과`);
    } else {
      if (n.ahead != null) meta.push(`+${n.ahead}커밋`);
      if (n.age_days != null) meta.push(`${Math.round(n.age_days)}일`);
      meta.push(n.reason);
    }
    if (n.unlocks > 0) meta.push({ cls: "un", text: `↳ ${n.unlocks}건 풀림` });
    if (this.notes[k]) meta.push({ cls: "memo", text: "메모" });
    const metaHtml = meta.filter(Boolean).map((m) => typeof m === "object"
      ? `<span class="${m.cls}">${esc(m.text)}</span>` : `<span>${esc(m)}</span>`).join("");
    const hasIn = n.preds.some((l) => l.open && this.nodes[l.key]);
    const hasOut = n.succs.some((l) => l.open && this.nodes[l.key]);
    const title = n.kind === "branch" ? n.id : n.title;
    const ex = (n.excerpt || []).map((e) => `<li>${esc(e)}</li>`).join("");
    return `<div class="win k-${n.kind} s-${n.state}${n.overdue ? " overdue" : ""}" tabindex="0" role="button" data-key="${esc(k)}"
      data-state="${esc(n.state)}" style="left:${p.x}px;top:${p.y}px;width:${n.w}px;height:${n.h}px"
      aria-label="${esc(KIND_LABEL[n.kind] + " " + n.id + " — " + n.label + " — " + n.title)}">
      <div class="bar"><span class="kd">${KIND_LABEL[n.kind]}</span><span class="sid">${esc(n.short)}</span>
        <span class="pill">${esc(n.label)}</span></div>
      <div class="bd"><div class="ti">${esc(title)}</div>
        ${ex ? `<ul class="ex">${ex}</ul>` : '<div style="flex:1"></div>'}
        <div class="mt">${metaHtml}</div></div>
      ${hasIn ? '<span class="port in"></span>' : ""}${hasOut ? '<span class="port out"></span>' : ""}
      <div class="big">${esc(n.short)}</div></div>`;
  }

  private frameHtml(f: Payload["frames"][number]): string {
    const isFlow = f.kind === "flow";
    const c = f.counts || {};
    let count: string;
    if (isFlow) {
      const bits = [`창 ${f.size}`, `깊이 ${f.depth}`];
      if (c.ready) bits.push(`시작 가능 ${c.ready}`);
      const human = (c.human || 0) + (c.gate_turn || 0);
      if (human) bits.push(`사람 ${human}`);
      if (c.gate_verdict) bits.push(`판정 미기록 ${c.gate_verdict}`);
      if (c.branch) bits.push(`미머지 ${c.branch}`);
      count = bits.join(" · ");
    } else {
      count = `${f.size}건 · ${f.hint ?? ""}`;
    }
    return `<div class="frame ${f.kind}" data-frame="${esc(f.id)}" style="left:${f.x}px;top:${f.y}px;width:${f.w}px;height:${f.h}px">
      <div class="fh"><span class="fk">${isFlow ? "흐름 " + f.index : "묶음"}</span>
      <span class="ft">${esc(f.title)}</span><span class="fc">${esc(count)}</span></div></div>`;
  }

  // 연결선 — points = [출력 포트, (빈자리 입구, 빈자리 출구)*, 입력 포트]. 옮긴 창이 끼면 포트끼리 곧게 잇는다.
  private wirePath(e: GraphEdge): string {
    let pts: number[][] = e.points;
    if (this.positions[e.src] || this.positions[e.dst]) {
      const s = this.pos(e.src), d = this.pos(e.dst), sn = this.nodes[e.src], dn = this.nodes[e.dst];
      pts = [[s.x + sn.w, s.y + sn.h / 2], [d.x, d.y + dn.h / 2]];
    }
    let dpath = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i + 1 < pts.length; i += 2) {
      const a = pts[i], b = pts[i + 1];
      if (i > 0) dpath += ` L${a[0]},${a[1]}`;
      const dx = Math.max(40, Math.abs(b[0] - a[0]) / 2);
      dpath += ` C${a[0] + dx},${a[1]} ${b[0] - dx},${b[1]} ${b[0]},${b[1]}`;
    }
    return dpath;
  }

  private markerOf(e: GraphEdge, hi: boolean): string {
    if (hi) return "url(#ah-hi)";
    if (e.kind === "done_on_branch" || e.kind === "claimed_on_branch") return "url(#ah-b)";
    if (e.kind === "requires_gates" || e.kind === "entry_gate" || e.kind === "gate_input") return "url(#ah-h)";
    return "url(#ah)";
  }

  private drawWorld(): void {
    if (!this.data) { this.world.innerHTML = ""; return; }
    const W = this.data.canvas.w, H = this.data.canvas.h;
    const defs = `<defs>
      <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="ah" d="M0,0L10,5L0,10z"/></marker>
      <marker id="ah-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path class="ah-hi" d="M0,0L10,5L0,10z"/></marker>
      <marker id="ah-h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="ah-h" d="M0,0L10,5L0,10z"/></marker>
      <marker id="ah-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="ah-b" d="M0,0L10,5L0,10z"/></marker>
    </defs>`;
    const wires = this.data.edges.map((e, i) =>
      `<path class="w k-${esc(e.kind)}${e.back ? " back" : ""}" data-i="${i}" d="${this.wirePath(e)}" marker-end="${this.markerOf(e, false)}"/>`).join("");
    this.world.style.width = W + "px";
    this.world.style.height = H + "px";
    this.world.innerHTML = this.data.frames.map((f) => this.frameHtml(f)).join("")
      + `<svg class="wires" id="wires" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${defs}${wires}</svg>`
      + this.keys.map((k) => this.winHtml(k)).join("");
  }

  /* ── 선택·걸러 보기 ── */
  private walk(start: string, dir: "preds" | "succs"): Set<string> {
    const out = new Set([start]);
    const stack = [start];
    while (stack.length) {
      const k = stack.pop() as string;
      for (const l of this.nodes[k][dir]) {
        if (l.open && this.nodes[l.key] && !out.has(l.key)) { out.add(l.key); stack.push(l.key); }
      }
    }
    return out;
  }

  setFilter(fn: ((n: GraphNode) => boolean) | null, queryOn: boolean): void {
    this.matchFn = fn; this.queryOn = queryOn;
    this.applyClasses();
  }

  select(k: string | null, focus: boolean): void {
    if (!k || !this.nodes[k]) { this.clearSelection(); return; }
    this.selected = k;
    this.upSet = this.walk(k, "preds");
    this.downSet = this.walk(k, "succs");
    this.applyClasses();
    if (focus) this.focusOn(k);
    this.h.onSelect(k);
  }

  clearSelection(): void {
    this.selected = null; this.upSet = new Set(); this.downSet = new Set();
    this.applyClasses();
    this.h.onSelect(null);
  }

  applyClasses(): void {
    const f = !!this.matchFn;
    const m = this.matchFn ?? (() => true);
    this.world.querySelectorAll<HTMLElement>(".win").forEach((el) => {
      const k = el.dataset.key as string, n = this.nodes[k];
      const inChain = !this.selected || this.upSet.has(k) || this.downSet.has(k);
      const hit = !f || m(n);
      el.classList.toggle("dim", !inChain || !hit);
      el.classList.toggle("sel", k === this.selected);
      el.classList.toggle("hit", f && hit && this.queryOn);
    });
    const edges = this.data?.edges ?? [];
    this.world.querySelectorAll<SVGPathElement>("#wires path.w").forEach((p) => {
      const e = edges[Number(p.dataset.i)];
      const hi = !!this.selected && ((this.upSet.has(e.src) && this.upSet.has(e.dst)) || (this.downSet.has(e.src) && this.downSet.has(e.dst)));
      const visible = (!this.selected || hi) && (!f || (m(this.nodes[e.src]) && m(this.nodes[e.dst])));
      p.classList.toggle("hi", hi);
      p.classList.toggle("dim", !visible);
      p.setAttribute("marker-end", this.markerOf(e, hi));
    });
  }

  /* ── 보기 변환 ── */
  applyView(animate: boolean): void {
    this.world.classList.toggle("anim", !!animate);
    this.world.style.transform = `translate(${this.view.x}px,${this.view.y}px) scale(${this.view.z})`;
    this.world.classList.toggle("lod", this.view.z < LOD_Z);
    const g = 22 * this.view.z;
    this.stage.style.backgroundSize = `${g}px ${g}px`;
    this.stage.style.backgroundPosition = `${this.view.x}px ${this.view.y}px`;
    this.zoomrd.textContent = Math.round(this.view.z * 100) + "%";
    this.scheduleMini();
    this.h.onView({ ...this.view });
  }

  setView(v: View, animate = false): void {
    this.view.x = v.x; this.view.y = v.y; this.view.z = Math.min(Z_MAX, Math.max(Z_MIN, v.z));
    this.applyView(animate);
  }

  zoomAt(factor: number, cx: number, cy: number, animate: boolean): void {
    const z = Math.min(Z_MAX, Math.max(Z_MIN, this.view.z * factor));
    this.view.x = cx - (cx - this.view.x) * (z / this.view.z);
    this.view.y = cy - (cy - this.view.y) * (z / this.view.z);
    this.view.z = z;
    this.applyView(animate);
  }

  zoomCenter(factor: number): void {
    const r = this.stage.getBoundingClientRect();
    this.zoomAt(factor, r.width / 2, r.height / 2, true);
  }

  focusOn(k: string): void {
    const n = this.nodes[k]; if (!n) return;
    const p = this.pos(k), r = this.stage.getBoundingClientRect();
    const usableW = r.width - (r.width > 900 ? 440 : 0);
    this.view.z = Math.max(this.view.z, 0.72);
    this.view.x = usableW / 2 - (p.x + n.w / 2) * this.view.z;
    this.view.y = r.height / 2 - (p.y + n.h / 2) * this.view.z;
    this.applyView(true);
  }

  fitAll(): void {
    if (!this.data) return;
    const r = this.stage.getBoundingClientRect();
    const z = Math.min(r.width / (this.data.canvas.w + 80), r.height / (this.data.canvas.h + 80));
    this.view.z = Math.max(Z_MIN, Math.min(Z_MAX, z));
    this.view.x = (r.width - this.data.canvas.w * this.view.z) / 2;
    this.view.y = (r.height - this.data.canvas.h * this.view.z) / 2;
    this.applyView(true);
  }

  focusFrame(id: string): void {
    const f = this.data?.frames.find((x) => x.id === id);
    if (!f) return;
    const r = this.stage.getBoundingClientRect();
    const z = Math.min(1, Math.max(0.3, Math.min((r.width - 60) / f.w, (r.height - 60) / f.h)));
    this.view.z = z; this.view.x = 30 - f.x * z; this.view.y = 30 - f.y * z;
    this.applyView(true);
  }

  /** 첫 화면 — 첫 흐름이 읽히는 배율 */
  initialView(): void {
    const first = this.data?.frames[0];
    if (!first) { this.applyView(false); return; }
    const r = this.stage.getBoundingClientRect();
    this.view.z = Math.min(0.9, Math.max(0.62, (r.width - 60) / Math.min(first.w, 2600)));
    this.view.x = 30 - first.x * this.view.z;
    this.view.y = 24 - first.y * this.view.z;
    this.applyView(false);
  }

  /* ── 포인터: 배경 끌기=이동 · 창 끌기=옮기기 · 짧게 누르기=선택 · 두 손가락=확대 ── */
  private bindPointer(): void {
    const stage = this.stage;
    stage.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 && ev.pointerType === "mouse") return;
      this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      const target = ev.target as HTMLElement;
      const win = target.closest(".win") as HTMLElement | null;
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.gesture = { type: "pinch", d: Math.hypot(a.x - b.x, a.y - b.y), z: this.view.z };
        return;
      }
      if (target.closest(".notice,.legend,.mini,.zoomrd,.empty")) { this.pointers.delete(ev.pointerId); return; }
      stage.setPointerCapture(ev.pointerId);
      if (win) {
        const k = win.dataset.key as string, p = this.pos(k);
        this.gesture = { type: "win", k, el: win, sx: ev.clientX, sy: ev.clientY, ox: p.x, oy: p.y, moved: false };
      } else {
        this.gesture = { type: "pan", sx: ev.clientX, sy: ev.clientY, vx: this.view.x, vy: this.view.y, moved: false };
      }
    });
    stage.addEventListener("pointermove", (ev) => {
      if (!this.pointers.has(ev.pointerId)) return;
      this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      const g = this.gesture; if (!g) return;
      if (g.type === "pinch" && this.pointers.size >= 2) {
        const [a, b] = [...this.pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const r = stage.getBoundingClientRect();
        this.zoomAt(((g.z as number) * d / (g.d as number)) / this.view.z, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, false);
        return;
      }
      const dx = ev.clientX - (g.sx as number), dy = ev.clientY - (g.sy as number);
      if (!g.moved && Math.hypot(dx, dy) < 4) return;
      g.moved = true;
      if (g.type === "pan") {
        stage.classList.add("panning");
        this.view.x = (g.vx as number) + dx; this.view.y = (g.vy as number) + dy;
        this.applyView(false);
      } else if (g.type === "win") {
        const el = g.el as HTMLElement, k = g.k as string;
        el.classList.add("dragging");
        const nx = Math.round((g.ox as number) + dx / this.view.z), ny = Math.round((g.oy as number) + dy / this.view.z);
        this.positions[k] = { x: nx, y: ny };
        el.style.left = nx + "px"; el.style.top = ny + "px";
        for (const i of this.edgeByNode[k] || []) {
          const p = this.world.querySelector(`#wires path[data-i="${i}"]`);
          if (p && this.data) p.setAttribute("d", this.wirePath(this.data.edges[i]));
        }
      }
    });
    const end = (ev: PointerEvent) => {
      this.pointers.delete(ev.pointerId);
      const g = this.gesture; if (!g) return;
      if (g.type === "pinch") { if (this.pointers.size === 0) this.gesture = null; return; }
      this.gesture = null;
      stage.classList.remove("panning");
      if (g.type === "win") {
        (g.el as HTMLElement).classList.remove("dragging");
        if (g.moved) { this.h.onMoved(this.positionsCopy); this.scheduleMini(true); }
        else this.select(g.k as string, false);
      } else if (g.type === "pan" && !g.moved && ev.type === "pointerup") {
        this.clearSelection();
      }
    };
    stage.addEventListener("pointerup", end);
    stage.addEventListener("pointercancel", end);
    stage.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const r = stage.getBoundingClientRect();
      if (ev.ctrlKey || ev.metaKey || !ev.shiftKey) {
        const factor = Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0018));
        this.zoomAt(factor, ev.clientX - r.left, ev.clientY - r.top, false);
      } else {
        this.view.x -= ev.deltaY; this.applyView(false);
      }
    }, { passive: false });
    stage.addEventListener("keydown", (ev) => {
      const win = (ev.target as HTMLElement).closest?.(".win") as HTMLElement | null;
      if (win && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); this.select(win.dataset.key as string, true); }
    });
  }

  /* ── 미니맵 ── */
  private css(name: string): string { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  private buildMini(): void {
    if (!this.data) return;
    const W = this.data.canvas.w, H = this.data.canvas.h;
    this.miniScale = Math.min(230 / W, 170 / H);
    const w = Math.max(60, Math.round(W * this.miniScale)), h = Math.max(40, Math.round(H * this.miniScale));
    const dpr = window.devicePixelRatio || 1;
    this.mini.width = w * dpr; this.mini.height = h * dpr;
    this.mini.style.width = w + "px"; this.mini.style.height = h + "px";
    const base = document.createElement("canvas");
    base.width = this.mini.width; base.height = this.mini.height;
    const c = base.getContext("2d"); if (!c) return;
    c.scale(dpr * this.miniScale, dpr * this.miniScale);
    c.fillStyle = this.css("--stage"); c.fillRect(0, 0, W, H);
    c.strokeStyle = this.css("--frame-line"); c.lineWidth = 2 / this.miniScale;
    for (const f of this.data.frames) c.strokeRect(f.x, f.y, f.w, f.h);
    for (const k of this.keys) {
      const n = this.nodes[k], p = this.pos(k);
      c.fillStyle = this.css(STATE_VAR[n.state] || "--wait");
      c.fillRect(p.x, p.y, n.w, n.h);
    }
    this.miniBase = base;
  }

  private drawMini = (): void => {
    this.miniQueued = false;
    if (!this.data) return;
    if (!this.miniBase) this.buildMini();
    if (!this.miniBase) return;
    const c = this.mini.getContext("2d"), dpr = window.devicePixelRatio || 1;
    if (!c) return;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, this.mini.width, this.mini.height);
    c.drawImage(this.miniBase, 0, 0);
    const r = this.stage.getBoundingClientRect();
    const s = this.miniScale * dpr;
    c.strokeStyle = this.css("--accent"); c.lineWidth = 2 * dpr;
    c.strokeRect(-this.view.x / this.view.z * s, -this.view.y / this.view.z * s, r.width / this.view.z * s, r.height / this.view.z * s);
  };

  scheduleMini(rebuild = false): void {
    if (rebuild) this.miniBase = null;
    if (!this.miniQueued) { this.miniQueued = true; requestAnimationFrame(this.drawMini); }
  }

  private bindMini(): void {
    const jump = (ev: PointerEvent) => {
      if (!this.data) return;
      const b = this.mini.getBoundingClientRect(), r = this.stage.getBoundingClientRect();
      const s = b.width / this.data.canvas.w;
      const cx = (ev.clientX - b.left) / s, cy = (ev.clientY - b.top) / s;
      this.view.x = r.width / 2 - cx * this.view.z; this.view.y = r.height / 2 - cy * this.view.z;
      this.applyView(false);
    };
    let drag = false;
    this.mini.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); drag = true; this.mini.setPointerCapture(ev.pointerId); jump(ev); });
    this.mini.addEventListener("pointermove", (ev) => { if (drag) jump(ev); });
    this.mini.addEventListener("pointerup", () => { drag = false; });
  }
}
