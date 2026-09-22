/**
 * admin 타깃 빌드 실행기 — `WHYMATH_WEB_TARGET=admin next build`의 **이식 가능한** 형태.
 *
 * 왜 npm script에 환경변수를 인라인하지 않는가: `VAR=값 명령` 접두는 POSIX 셸 문법이라
 * Windows(cmd·PowerShell)에서 실행되지 않는다. CI는 ubuntu지만 이 저장소의 사람 작업 환경은
 * Windows PowerShell이 기본이다(CLAUDE.md 실행 환경 규칙) — 한쪽에서만 도는 빌드 명령은
 * 런북에 쓸 수 없다. `cross-env` 의존성을 새로 들이는 대신 Node 한 파일로 끝낸다.
 *
 * **종료 코드를 그대로 돌려준다.** 래퍼가 마지막에 다른 일을 해서 exit 0으로 끝나면 빌드
 * 실패가 성공으로 보고된다(CLAUDE.md "래퍼가 종료 코드를 가리는 축") — 이 파일의 마지막
 * 행위가 `process.exit(코드)`인 이유다.
 */
import { spawnSync } from "node:child_process";

const result = spawnSync("next", ["build"], {
  stdio: "inherit",
  env: { ...process.env, WHYMATH_WEB_TARGET: "admin" },
  // Windows에서 `next`는 `next.cmd`라 셸 없이는 실행되지 않는다. POSIX에서는 셸을 끼우지
  // 않는다(인자 재해석 방지).
  shell: process.platform === "win32",
});

if (result.error) {
  console.error("[build:admin] next 실행 자체가 실패했습니다:", result.error.message);
  process.exit(1);
}
if (result.signal) {
  console.error("[build:admin] next가 시그널로 종료됐습니다:", result.signal);
  process.exit(1);
}
process.exit(result.status ?? 1);
