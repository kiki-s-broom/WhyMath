/* 작업공간 자동 찾기 (HARN-208) — 바로가기·시작 메뉴로 켜면 작업 폴더(cwd)가 저장소가 아니다.
   그래서 첫 실행에는 알려진 자리를 순서대로 찔러 WhyMath 저장소(scripts/harness/work_graph.py가
   있는 폴더)를 찾는다. 찾지 못하면 무엇을 어디서 찾았는지를 그대로 돌려준다(없음으로 위장하지 않는다). */
import path from "node:path";
import type { DiscoveryReport } from "../shared/types";
import { detectKind } from "./store/settings";

export interface DiscoverInput {
  env: Record<string, string | undefined>;
  platform: NodeJS.Platform;
  /** 사용자 홈 (os.homedir) */
  home: string;
  /** 실제 바탕화면 경로 (app.getPath("desktop")) — OneDrive로 옮겨진 바탕화면도 이것이 맞다 */
  desktop?: string;
  /** 앱 코드 위치 (app.getAppPath) — 개발 모드(npm start)면 저장소 안이다 */
  appDir: string;
}

/** 저장소 안에서 앱이 도는 경우(개발 모드 · 저장소 안에 둔 무설치 EXE)를 잡기 위해 올라갈 최대 단계 */
export const ANCESTOR_DEPTH = 4;

/** 이 프로젝트의 고정 작업 장소는 바탕화면\__AI\WhyMath다 (CLAUDE.md · Kiki 머신). */
const DESKTOP_REL = ["__AI", "WhyMath"];

function ancestors(p: path.PlatformPath, start: string, depth: number): string[] {
  const out: string[] = [];
  let cur = p.resolve(start);
  for (let i = 0; i <= depth; i++) {
    out.push(cur);
    const up = p.dirname(cur);
    if (up === cur) break;
    cur = up;
  }
  return out;
}

/** 찾아볼 자리를 우선순위대로. 같은 폴더는 한 번만(Windows는 대소문자 무시). */
export function workspaceCandidates(input: DiscoverInput): string[] {
  // 경로 규칙은 대상 플랫폼 것을 쓴다(Windows 경로를 posix로 잇지 않게 — 테스트는 리눅스에서도 돈다)
  const p = input.platform === "win32" ? path.win32 : path.posix;
  const list: string[] = [];
  const portable = input.env.PORTABLE_EXECUTABLE_DIR;   // electron-builder 무설치 EXE가 넣어 주는 원래 위치
  if (portable) list.push(...ancestors(p, portable, ANCESTOR_DEPTH));
  list.push(...ancestors(p, input.appDir, ANCESTOR_DEPTH));
  if (input.desktop) list.push(p.join(input.desktop, ...DESKTOP_REL));
  list.push(p.join(input.home, "Desktop", ...DESKTOP_REL));
  list.push(p.join(input.home, "WhyMath"));
  const seen = new Set<string>();
  const key = (x: string) => (input.platform === "win32" ? x.toLowerCase() : x);
  return list.filter((x) => {
    const k = key(p.resolve(x));
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/** 후보 중 처음으로 harness 저장소인 곳. git 전용 폴더는 자동 연결하지 않는다(그래프가 없다). */
export async function discoverWorkspace(
  candidates: string[],
  detect: typeof detectKind = detectKind,
): Promise<DiscoveryReport> {
  const tried: DiscoveryReport["tried"] = [];
  for (const p of candidates) {
    const d = await detect(p);
    if (d.kind === "harness") return { found: p, tried };
    tried.push({ path: p, reason: d.kind === null ? d.reason : "git 저장소지만 scripts/harness/work_graph.py가 없다" });
  }
  return { found: null, tried };
}
