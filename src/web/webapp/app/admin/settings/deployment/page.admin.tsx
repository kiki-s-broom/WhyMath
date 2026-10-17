import { CmsConceptWorkspace } from "../../_components/CmsConceptWorkspace";

/**
 * 발행·폐기·롤백 (P3-12 CMS).
 *
 * 크롬은 `layout.admin.tsx`의 `AdminShell`이 그린다. 모드는 *어느 패널을 보일지*만 고른다 — 가능한
 * 처리는 서버가 준 값과 서버의 권한 검사가 정한다(모드를 바꿔도 권한은 늘지 않는다).
 */
export default function Page() {
  return <CmsConceptWorkspace mode="deploy" />;
}
