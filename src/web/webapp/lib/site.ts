/**
 * 랜딩이 쓰는 사이트 상수 — **런타임 조회 없음**(정적 export·백엔드 호출 0).
 *
 * 값이 아직 확정되지 않은 것(도메인·베타 폼·법정 표시)은 **가짜 값을 박지 않고**
 * 환경변수로 비워 둔다. 미설정이면 UI가 "준비 중"으로 정직하게 표시한다 —
 * 죽은 링크를 내보내는 것보다 낫고, 확정 주체가 사람(Kiki·법무)이라는 사실도 드러난다.
 *
 *  · NEXT_PUBLIC_SITE_URL      : 배포 도메인. WEB-02(배포 배선·Kiki 확정)가 주입한다.
 *  · NEXT_PUBLIC_BETA_FORM_URL : 베타 신청 외부 폼 링크(web_strategy §3.2 v1).
 *                                외부 폼 채택 자체가 개인정보 처리위탁 고지 대상이라
 *                                변호사 검토 게이트 통과 전에는 비워 둔다.
 */

/** 배포 도메인 미확정 — 빌드 산출물의 절대 URL 기준점(sitemap·OG)만 잡는 개발 기본값. */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

/** 확정 전에는 빈 문자열 — CTA가 링크가 아니라 "준비 중" 안내로 렌더된다. */
export const BETA_FORM_URL = process.env.NEXT_PUBLIC_BETA_FORM_URL || "";

export const SITE_NAME = "WhyMath (와이매스)";
export const SLOGAN_KR = "답이 아닌, 이유를 묻는 수학";
export const SLOGAN_EN = "The math that asks why.";

/**
 * 한 줄 소개. **효과 단정 금지**(web_strategy §3.4 카피 가드 1줄 규칙):
 * 성적·점수·등급이 오른다는 서술, 경쟁 서비스 대비 우위 단정을 랜딩 어디에도 쓰지 않는다.
 * RCT 검증 전까지는 "무엇을 하는 앱인가"만 말한다.
 */
export const SITE_DESCRIPTION =
  "WhyMath(와이매스)는 한국 중·고등학생을 위한 AI 수학 학습 앱입니다. " +
  "정답을 먼저 알려주는 대신, 학생이 스스로 다음 한 걸음을 찾도록 묻습니다.";
