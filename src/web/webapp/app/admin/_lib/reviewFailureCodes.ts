/**
 * 검수 반려코드 F1~F8 (ADMIN-18) — 클라이언트 표시용 상수.
 *
 * 정본은 서버 `GenerationFailureCode`(`schema/enums.py`)와 `docs/standards/eos_verification_design_v1.md` §4
 * (폐쇄 8종 · G0 동결 후 12월까지 추가·삭제·의미 변경 금지)다. 아래 라벨은 그 enum의 docstring을
 * 그대로 옮긴 것이며 판정 로직이 아니다(어떤 코드가 *맞는지*는 검수자가, 허용 여부는 서버가 정한다).
 * 값집합이 서버와 어긋나지 않는지는 `tests/infra/test_webapp_admin_review_governance.py`가 enum과
 * 이 파일을 정규식으로 대조해 동결한다.
 */

export const REVIEW_FAILURE_CODES = [
  { code: "F1", label: "수식·파싱 실패", detail: "LaTeX/AST 파싱 불가, 수식 문법 오류" },
  { code: "F2", label: "정답 불일치", detail: "SymPy/수치 검증에서 정답·해설 모순" },
  { code: "F3", label: "풀이 논리 비약", detail: "인접 단계 비동치·근거 없는 도약" },
  { code: "F4", label: "성취기준 이탈", detail: "지정 성취기준 코드 범위 밖 내용" },
  { code: "F5", label: "난이도 미스", detail: "요청 난이도와 실제 난이도의 불일치" },
  { code: "F6", label: "오개념 오연결", detail: "예상 오답의 op-code/오개념 매핑 오류" },
  { code: "F7", label: "언어 수준 부적합", detail: "학교급 어휘·문장 수준 불일치" },
  { code: "F8", label: "힌트 정답 누설", detail: "L1·L2 힌트에 최종 정답 포함(무관용)" },
] as const;

export type ReviewFailureCode = (typeof REVIEW_FAILURE_CODES)[number]["code"];

/** 서버가 아는 코드만 통과시킨다 — 모르는 코드는 UI에 노출도, 요청에 싣지도 않는다. */
export function isReviewFailureCode(value: unknown): value is ReviewFailureCode {
  return typeof value === "string" && REVIEW_FAILURE_CODES.some((entry) => entry.code === value);
}
