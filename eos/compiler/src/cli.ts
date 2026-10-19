/**
 * eos CLI — 지금은 `check <dir>` 하나만 있다(문서 §8의 네 명령 중 첫 번째).
 * 종료 코드: 통과 0, 오류 있음 1, 사용법 오류 2. 경고만 있으면 0이다.
 */
import { existsSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import type { Diagnostic } from "./pack/types.js";
import { checkPacks } from "./pack/validate.js";

/** 진단 1건을 한 줄 텍스트로 만든다. 예: `ERROR PACK_REQUIRES_CYCLE packs/a/pack.yaml:/requires ...` */
export function formatDiagnostic(d: Diagnostic): string {
  return `${d.level.toUpperCase()} ${d.code} ${d.file}:${d.path || "/"} ${d.message}`;
}

/**
 * CLI 본체. process.exit을 직접 부르지 않고 종료 코드와 출력 줄을 돌려준다 — 테스트에서 그대로 호출하기 위해서다.
 */
export function runCli(argv: string[]): { code: number; lines: string[] } {
  const [command, target] = argv;
  if (command !== "check" || !target) {
    return { code: 2, lines: ["사용법: eos check <packs 디렉터리>"] };
  }
  const dir = resolve(target);
  if (!existsSync(dir) || !statSync(dir).isDirectory()) {
    return { code: 2, lines: [`디렉터리가 아니다: ${dir}`] };
  }
  const result = checkPacks(dir);
  const lines = result.diagnostics.map(formatDiagnostic);
  lines.push(`pack ${result.packs.length}개 검사 — 오류 ${result.errorCount}건, 경고 ${result.warningCount}건`);
  return { code: result.errorCount > 0 ? 1 : 0, lines };
}

// 직접 실행했을 때만 진입점으로 동작한다. 테스트가 import할 때는 아무것도 하지 않는다.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { code, lines } = runCli(process.argv.slice(2));
  for (const line of lines) (code === 0 ? console.log : console.error)(line);
  process.exit(code);
}
