/**
 * 공개 산출물 누출 탐지용 표식 — web_strategy §2 "공개 빌드에 admin 코드 0"의 *측정 수단*.
 *
 * 왜 상수 하나가 필요한가: "공개 빌드에 admin이 없다"를 파일 경로(`out/admin/` 부재)로만
 * 확인하면, admin 컴포넌트가 랜딩 쪽에서 import돼 **라우트 없이 번들에만 실리는** 누출을 못
 * 본다(경로는 안 생기고 JS 청크만 커진다). 이 문자열은 minify를 견디는 리터럴이라, CI가
 * `out/`의 산출물 전체에서 이 표식을 grep 해 **0건**임을 exit code로 판정할 수 있다.
 *
 * 값을 바꾸면 CI 검사 문자열도 함께 바꿔야 한다 —
 * `tests/infra/test_webapp_admin_shell_governance.py`가 둘의 일치를 동결한다.
 */
export const ADMIN_BUNDLE_MARKER = "wm-admin-shell-bundle";
