import { AdminShell } from "./_components/AdminShell";

/**
 * `/admin` 서브트리 공통 크롬. 셸(헤더·좌측 내비·인증 상태)을 여기에 두는 이유는, 앞으로
 * 붙을 모듈 화면(ADMIN-07 검수 큐 등)이 크롬을 각자 다시 만들지 않게 하기 위해서다 —
 * 그리고 그때도 내비는 여전히 `GET /v1/admin/menu` 하나에서 파생된다(04 §2 원칙7).
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
