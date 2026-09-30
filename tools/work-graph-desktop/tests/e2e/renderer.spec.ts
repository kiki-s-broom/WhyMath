/* 렌더러 화면 계약 (HARN-206) — Electron 없이 file:// + 픽스처 API로 연다.
   계약: 창 수 = nodes 수 · 연결선 수 = edges 수 · 집계 카드 = counts · 선택 강조(선행/후속) · 필터 · 검색 ·
   좌표 드래그 후 새로고침 복원(API 경유) · 확인 필요 카드가 scans skipped를 사유로 나열 · 목록 보기. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../..");
const PAGE = `file://${path.join(ROOT, "dist", "renderer", "index.html")}`;
type Fixture = { nodes: Record<string, { key: string; state: string; preds: { key: string; open: boolean }[]; succs: { key: string; open: boolean }[]; x: number; y: number; kind: string; stage?: string; title: string; short: string }>; edges: unknown[]; counts: Record<string, number>; scans: Record<string, { status: string }> };
const sample = JSON.parse(readFileSync(path.join(ROOT, "fixtures", "sample.json"), "utf8")) as Fixture;

async function open(page: Page, fixture = "sample", extra = ""): Promise<void> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${PAGE}?fixture=${fixture}${extra}`);
  await expect(page.locator(".win").first()).toBeVisible();
  expect(errors, "페이지 오류 0건").toEqual([]);
}

/** 선행/후속 사슬 — 테스트가 독립적으로 계산한다(렌더러의 walk와 같은 정의) */
function walk(start: string, dir: "preds" | "succs"): Set<string> {
  const out = new Set([start]); const stack = [start];
  while (stack.length) { const k = stack.pop() as string; for (const l of sample.nodes[k][dir]) if (l.open && sample.nodes[l.key] && !out.has(l.key)) { out.add(l.key); stack.push(l.key); } }
  return out;
}

test("창 수 = nodes 수 · 연결선 수 = edges 수", async ({ page }) => {
  await open(page);
  await expect(page.locator(".win")).toHaveCount(Object.keys(sample.nodes).length);
  await expect(page.locator("#wires path.w")).toHaveCount(sample.edges.length);
  await expect(page.locator(".frame")).toHaveCount(10);
});

test("창의 상태 라벨은 페이로드의 state/label 그대로다(앱 판정 없음)", async ({ page }) => {
  await open(page);
  for (const [k, n] of Object.entries(sample.nodes)) {
    const el = page.locator(`.win[data-key="${k}"]`);
    await expect(el).toHaveAttribute("data-state", n.state);
    await expect(el).toHaveClass(new RegExp(`\\bs-${n.state}\\b`));
  }
});

test("집계 카드 8종 = counts 그대로 · 게이트 카드는 세 상태 합", async ({ page }) => {
  await open(page);
  const c = sample.counts;
  const v = (id: string) => page.getByTestId(`card-${id}-value`);
  await expect(v("ready")).toHaveText(String(c.ready));
  await expect(v("in_progress")).toHaveText(String(c.in_progress));
  await expect(v("waiting")).toHaveText(String(c.waiting));
  await expect(v("blocked")).toHaveText(String(c.blocked));
  await expect(v("human")).toHaveText(String(c.human));
  await expect(v("gate")).toHaveText(String(c.gate_turn + c.gate_verdict + c.gate_wait));
  await expect(v("branch")).toHaveText(String(c.branch));
  await expect(page.locator(".card")).toHaveCount(8);
});

test("확인 필요 카드 — scans skipped 3건을 사유로 나열하고, ok 픽스처에서는 0건이라고 말한다", async ({ page }) => {
  await open(page);
  const skipped = Object.values(sample.scans).filter((s) => s.status !== "ok").length;
  expect(skipped).toBe(3);
  await expect(page.getByTestId("card-attention-value")).toHaveText("3");
  await page.getByTestId("card-attention").click();
  const items = page.getByTestId("attention-list").locator("li");
  await expect(items).toHaveCount(3);
  for (const name of ["완료분", "claim", "고립"]) await expect(items.filter({ hasText: `원격 조회 ${name}: skipped` })).toHaveCount(1);
  await page.goto(`${PAGE}?fixture=sample_ok`);
  await expect(page.locator(".win").first()).toBeVisible();
  await expect(page.getByTestId("card-attention-value")).toHaveText("0");
  await page.getByTestId("card-attention").click();
  await expect(page.getByTestId("attention-list")).toContainText("확인 필요 0건");
});

test("스냅샷 24시간 초과는 확인 필요 사유와 상태 줄에 나온다", async ({ page }) => {
  await open(page, "sample", "&stale=1");
  await expect(page.getByTestId("card-attention-value")).toHaveText("4");
  await expect(page.locator("#snap-line .stale")).toHaveText("24시간 초과");
  await page.getByTestId("card-attention").click();
  await expect(page.getByTestId("attention-list").locator("li[data-kind=stale]")).toHaveCount(1);
});

test("선택 → 선행/후속 사슬 강조, 나머지 dim, 상세 패널의 사슬 개수 일치", async ({ page }) => {
  await open(page);
  // 선행·후속이 모두 있는 창을 고른다
  const key = Object.keys(sample.nodes).find((k) => walk(k, "preds").size > 1 && walk(k, "succs").size > 1) as string;
  expect(key).toBeTruthy();
  const up = walk(key, "preds"), down = walk(key, "succs");
  await page.locator(`.win[data-key="${key}"]`).dispatchEvent("pointerdown", { button: 0, pointerId: 1, clientX: 10, clientY: 10, isPrimary: true });
  await page.locator(`.win[data-key="${key}"]`).dispatchEvent("pointerup", { button: 0, pointerId: 1, clientX: 10, clientY: 10, isPrimary: true });
  await expect(page.locator(`.win[data-key="${key}"]`)).toHaveClass(/\bsel\b/);
  await expect(page.locator("#detail")).toHaveClass(/\bopen\b/);
  await expect(page.getByTestId("chain-count")).toHaveText(`선행 사슬 ${up.size - 1} · 후속 사슬 ${down.size - 1}`);
  const chain = new Set([...up, ...down]);
  for (const k of Object.keys(sample.nodes)) {
    const el = page.locator(`.win[data-key="${k}"]`);
    if (chain.has(k)) await expect(el).not.toHaveClass(/\bdim\b/); else await expect(el).toHaveClass(/\bdim\b/);
  }
  const hi = await page.locator("#wires path.w.hi").count();
  expect(hi).toBeGreaterThan(0);
  await page.keyboard.press("Escape");
  await expect(page.locator(".win.dim")).toHaveCount(0);
  await expect(page.locator("#detail")).not.toHaveClass(/\bopen\b/);
});

test("카드 클릭 = 필터 토글 · 스테이지·종류 필터 · 검색", async ({ page }) => {
  await open(page);
  const N = sample.nodes;
  const ready = Object.values(N).filter((n) => n.state === "ready").length;
  await page.getByTestId("card-ready").click();
  await expect(page.getByTestId("card-ready")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".win:not(.dim)")).toHaveCount(ready);
  await expect(page.locator("#hits")).toContainText(`걸러 본 결과 ${ready}`);
  await page.getByTestId("card-ready").click();   // 다시 누르면 해제
  await expect(page.locator(".win.dim")).toHaveCount(0);
  await page.locator("#fkind").selectOption("gate");
  const gates = Object.values(N).filter((n) => n.kind === "gate").length;
  await expect(page.locator(".win:not(.dim)")).toHaveCount(gates);
  await page.locator("#fkind").selectOption("");
  const stage = Object.values(N).find((n) => n.stage)?.stage as string;
  await page.locator("#fstage").selectOption(stage);
  await expect(page.locator(".win:not(.dim)")).toHaveCount(Object.values(N).filter((n) => n.stage === stage).length);
  await page.locator("#fstage").selectOption("");
  const target = Object.values(N).find((n) => n.kind === "task")!;
  await page.locator("#q").fill(target.short.toLowerCase());
  const hits = Object.values(N).filter((n) => [n.key.split(":")[1], n.short, n.title].join(" ").toLowerCase().includes(target.short.toLowerCase())).length;
  await expect(page.locator(".win.hit")).toHaveCount(hits);
  await page.locator("#q").press("Enter");
  await expect(page.locator("#detail")).toHaveClass(/\bopen\b/);
});

test("창을 끌어 옮긴 좌표는 API에 저장되고 새로고침 뒤 복원된다(브라우저 저장소 아님)", async ({ page }) => {
  await open(page);
  const key = Object.keys(sample.nodes)[0];
  const win = page.locator(`.win[data-key="${key}"]`);
  const before = await win.evaluate((el) => ({ x: parseFloat((el as HTMLElement).style.left), y: parseFloat((el as HTMLElement).style.top) }));
  await page.keyboard.press("0");   // 전체 맞춤 — 첫 창이 화면 안에 들어온다
  await page.waitForTimeout(400);
  const z = Number((await page.locator("#zoomrd").textContent())!.replace("%", "")) / 100;
  const box = (await win.boundingBox())!;
  expect(box.x).toBeGreaterThan(0);
  await page.mouse.move(box.x + 10, box.y + 6);
  await page.mouse.down();
  await page.mouse.move(box.x + 110, box.y + 86, { steps: 6 });
  await page.mouse.up();
  const after = await win.evaluate((el) => ({ x: parseFloat((el as HTMLElement).style.left), y: parseFloat((el as HTMLElement).style.top) }));
  // 화면 100px·80px 이동 = 월드 100/z·80/z (반올림 오차 허용)
  expect(Math.abs(after.x - before.x - 100 / z)).toBeLessThan(3);
  expect(Math.abs(after.y - before.y - 80 / z)).toBeLessThan(3);
  await page.waitForTimeout(400);   // 디바운스 저장
  const ls = await page.evaluate(() => Object.keys(localStorage).filter((k) => k !== "wg:ws" && k !== "wg:legend"));
  expect(ls, "좌표를 localStorage에 두지 않는다").toEqual([]);
  await page.locator("#refresh").click();
  await expect(page.locator("#refresh")).toHaveText("새로고침");
  await expect(page.locator(".win")).toHaveCount(Object.keys(sample.nodes).length);
  const restored = await page.locator(`.win[data-key="${key}"]`).evaluate((el) => ({ x: parseFloat((el as HTMLElement).style.left), y: parseFloat((el as HTMLElement).style.top) }));
  expect(restored).toEqual(after);
  await page.locator("#reset-pos").click();
  const reset = await page.locator(`.win[data-key="${key}"]`).evaluate((el) => ({ x: parseFloat((el as HTMLElement).style.left), y: parseFloat((el as HTMLElement).style.top) }));
  expect(reset).toEqual(before);
});

test("목록 보기 — 표 행 수 = 창 수 · ↑↓ 이동 · Enter 상세", async ({ page }) => {
  await open(page);
  await page.locator('[data-view="list"]').click();
  await expect(page.locator("#stage")).toBeHidden();
  await expect(page.locator("#table tbody tr")).toHaveCount(Object.keys(sample.nodes).length);
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#table tr.sel")).toHaveCount(1);
  const first = await page.locator("#table tr.sel").getAttribute("data-key");
  await page.keyboard.press("ArrowDown");
  const second = await page.locator("#table tr.sel").getAttribute("data-key");
  expect(second).not.toBe(first);
  await page.keyboard.press("ArrowUp");
  await expect(page.locator("#table tr.sel")).toHaveAttribute("data-key", first as string);
  await expect(page.locator("#detail")).toHaveClass(/\bopen\b/);
  await page.locator('[data-view="ready"]').click();
  await expect(page.locator("#stage")).toBeVisible();
  await expect(page.getByTestId("card-ready")).toHaveAttribute("aria-pressed", "true");
});

test("브랜치 창·게이트 창의 상세와 동작 버튼 — 실행 결과는 그대로 표시된다", async ({ page }) => {
  await open(page);
  const gate = Object.values(sample.nodes).find((n) => n.state === "gate_turn")!;
  await page.locator('[data-view="list"]').click();
  await page.locator(`#table tr[data-key="${gate.key}"]`).click();
  await expect(page.getByTestId("detail-state")).toHaveText("사람 차례");
  await page.locator('[data-action="gates_clear"]').click();
  await page.getByTestId("f-evidence").fill("PR #1");
  await page.getByTestId("f-run").click();
  await expect(page.getByTestId("action-result")).toContainText("실패");
  await expect(page.getByTestId("action-result")).toContainText("픽스처 모드");
  const branch = Object.values(sample.nodes).find((n) => n.kind === "branch")!;
  await page.locator(`#table tr[data-key="${branch.key}"]`).click();
  await expect(page.locator("#detail")).toContainText("미머지 브랜치");
  await expect(page.locator("#detail")).toContainText("확인 명령 (읽기 전용)");
  await expect(page.locator("#detail")).toContainText("PR 사실 (gh)");
});
