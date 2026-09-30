/* 거버넌스 — 소스 스캔 (HARN-206).
   ① src/main/** 에서 backlog/ 경로를 쓰는 fs 호출 0건: 파일 쓰기 식별자는 store/atomic.ts에만 있고,
      atomic.ts는 'backlog'를 언급하지 않으며, 'backlog'를 언급하는 파일은 쓰기 식별자·atomic 임포트를 갖지 않는다.
   ② nodeIntegration: true 0건 · contextIsolation: false 0건 · sandbox: false 0건.
   ③ 렌더러 번들에 Node 접근·원격 URL 없음. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "../..");
const MAIN = path.join(ROOT, "src", "main");
const WRITE_IDS = /\b(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|rename|renameSync|unlink|unlinkSync|rm|rmSync|rmdir|truncate|copyFile|copyFileSync|mkdir|mkdirSync|openSync|writeSync|outputFile|writeJson|dump|safeDump)\s*\(/;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const e of readdirSync(dir)) {
    const p = path.join(dir, e);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (p.endsWith(".ts")) out.push(p);
  }
  return out;
}
const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

describe("main 프로세스는 backlog/를 직접 쓰지 않는다", () => {
  const files = walk(MAIN);
  it("스캔 대상이 있다(0건이면 검사가 공허하다)", () => { expect(files.length).toBeGreaterThanOrEqual(8); });
  it("파일 쓰기 식별자는 store/atomic.ts에만 있다", () => {
    const offenders = files.filter((f) => !f.endsWith(path.join("store", "atomic.ts")) && WRITE_IDS.test(stripComments(readFileSync(f, "utf8"))));
    expect(offenders.map((f) => path.relative(ROOT, f))).toEqual([]);
  });
  it("atomic.ts는 backlog를 모른다", () => {
    expect(stripComments(readFileSync(path.join(MAIN, "store", "atomic.ts"), "utf8"))).not.toMatch(/backlog/i);
  });
  it("backlog를 언급하는 파일은 atomic 쓰기 함수를 임포트하지 않는다", () => {
    const offenders = files.filter((f) => {
      const src = stripComments(readFileSync(f, "utf8"));
      return /backlog/i.test(src) && /atomicWriteJson|removeFile|from ["'].*store\/atomic["']/.test(src);
    });
    expect(offenders.map((f) => path.relative(ROOT, f))).toEqual([]);
  });
  it("YAML 라이브러리·백로그 파서를 쓰지 않는다(판정 재구현 금지)", () => {
    const offenders = files.filter((f) => /from ["'](js-)?yaml["']|require\(["'](js-)?yaml["']\)/.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
    const pkg = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8"));
    expect(Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).filter((d) => /yaml/i.test(d))).toEqual([]);
  });
});

describe("BrowserWindow 보안 설정", () => {
  const main = stripComments(readFileSync(path.join(MAIN, "main.ts"), "utf8"));
  it("nodeIntegration: true 0건", () => { expect(main).not.toMatch(/nodeIntegration\s*:\s*true/); expect(main).toMatch(/nodeIntegration\s*:\s*false/); });
  it("contextIsolation: false 0건", () => { expect(main).not.toMatch(/contextIsolation\s*:\s*false/); expect(main).toMatch(/contextIsolation\s*:\s*true/); });
  it("sandbox: false 0건", () => { expect(main).not.toMatch(/sandbox\s*:\s*false/); expect(main).toMatch(/sandbox\s*:\s*true/); });
  it("webSecurity: false 0건 · 새 창·이동 차단", () => {
    expect(main).not.toMatch(/webSecurity\s*:\s*false/);
    expect(main).toMatch(/setWindowOpenHandler/); expect(main).toMatch(/will-navigate/);
  });
  it("openExternal은 http(s)만", () => { expect(main).toMatch(/\^https\?:/); });
});

describe("렌더러·프리로드", () => {
  it("렌더러 소스에 require·process·원격 URL 참조가 없다", () => {
    for (const f of walk(path.join(ROOT, "src", "renderer"))) {
      const src = stripComments(readFileSync(f, "utf8"));
      expect(src, f).not.toMatch(/\brequire\s*\(/);
      expect(src, f).not.toMatch(/\bprocess\.[a-z]/);
      expect(src, f).not.toMatch(/https?:\/\/(?!x\/)/);   // 테스트용 자리표시(https://x/)만 허용
    }
    const html = readFileSync(path.join(ROOT, "src", "renderer", "index.html"), "utf8");
    expect(html).toMatch(/Content-Security-Policy/);
    expect(html).not.toMatch(/https?:\/\//);
  });
  it("프리로드는 contextBridge로만 노출하고 ipcRenderer를 그대로 넘기지 않는다", () => {
    const src = stripComments(readFileSync(path.join(ROOT, "src", "preload", "preload.ts"), "utf8"));
    expect(src).toMatch(/contextBridge\.exposeInMainWorld\("workGraph"/);
    expect(src).not.toMatch(/exposeInMainWorld\([^)]*ipcRenderer\s*\)/);
    expect(src).not.toMatch(/ipcRenderer\.(on|send)\b/);
  });
});
