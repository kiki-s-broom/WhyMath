import { ReviewQueue } from "../_components/ReviewQueue";

/**
 * 검수 큐 화면 (ADMIN-07) — `/admin/review`.
 *
 * 크롬(헤더·좌측 내비·토큰 게이트)은 `layout.admin.tsx`의 `AdminShell`이 이미 그린다.
 * 이 페이지는 게이트 안쪽에서만 마운트되며, 내비 항목은 `GET /v1/admin/menu`가 정한다
 * (이 파일에는 메뉴 정의가 없다).
 */
export default function ReviewQueuePage() {
  return <ReviewQueue />;
}
