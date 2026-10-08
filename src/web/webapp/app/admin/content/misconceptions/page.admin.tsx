import { CmsResourceScreen } from "../../_components/CmsResourceScreen";

/**
 * 오개념 조회·수정 (P3-12 CMS).
 *
 * 크롬(헤더·좌측 내비·토큰 게이트)은 `layout.admin.tsx`의 `AdminShell`이 이미 그린다. 이 페이지에는
 * 리소스 이름도 모듈 id도 경로도 없다 — 서버가 리소스마다 내려 주는 화면 경로(`route`)와 자기
 * 경로가 같은 리소스를 `CmsResourceScreen`이 그린다(하드코딩 nav 금지의 같은 정신).
 */
export default function Page() {
  return <CmsResourceScreen />;
}
