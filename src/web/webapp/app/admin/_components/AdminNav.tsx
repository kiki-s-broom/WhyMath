import Link from "next/link";

import type { AdminMenuSection, AdminModuleStatus } from "../_lib/adminApi";

import styles from "../admin.module.css";

/**
 * 좌측 내비 — **입력이 전부다**.
 *
 * 이 컴포넌트에는 메뉴 항목도, 섹션 키도, 섹션 순서도 없다. `sections`를 받은 순서대로
 * 그대로 그린다(04 §2 원칙7 — "프런트가 순서 배열을 들고 있으면 그것이 곧 하드코딩 nav의
 * 재발"). 그래서 백엔드 레지스트리에 모듈이 하나 늘면 이 파일은 **한 글자도 바뀌지 않는다**.
 * 그 부재를 `tests/infra/test_webapp_admin_shell_governance.py`가 정적으로 동결한다.
 *
 * 여기서 프런트가 *정하는* 것은 표현뿐이다(`admin_menu.py` docstring — "렌더 방식(아이콘·색·
 * 비활성 표기)은 클라가 정한다"): 3값 상태를 어떤 배지로 보일지, 어느 것을 누를 수 있게 할지.
 *
 * 누를 수 있는 조건 = `status === "live"`
 * --------------------------------------
 * `live`의 정의가 "데이터+UI 모두 실동작"이므로, 그것이 곧 "이 빌드에 화면이 있다"와 같은
 * 뜻이다. 별도의 '구현된 라우트 목록'을 프런트에 두면 그 목록이 두 번째 하드코딩 nav가 되고
 * 레지스트리와 드리프트한다. **2026-09-22 현재 `live`는 0건**이라 실제로 눌리는 항목은 아직
 * 없다 — 링크가 깨진 것이 아니라 화면이 아직 없다는 사실의 정직한 표시이며, ADMIN-07이 검수
 * 큐 화면을 올리면서 그 엔트리를 `live`로 바꾸면 이 파일을 고치지 않고 링크가 살아난다.
 */

/** 3값 상태의 *표시* 규약. 값 자체는 서버 계약, 문구·비활성 여부는 여기의 표현 결정이다. */
const STATUS_BADGE: Record<AdminModuleStatus, string> = {
  live: "사용 가능",
  partial: "화면 준비 중",
  planned: "계획",
};

export function AdminNav({ sections }: { sections: AdminMenuSection[] }) {
  return (
    <nav className={styles.nav} aria-label="관리 모듈">
      {sections.map((section) => (
        <section key={section.key} className={styles.navSection}>
          <h2 className={styles.navSectionTitle}>{section.label_ko}</h2>
          <ul className={styles.navList}>
            {section.items.map((item) => (
              <li key={item.id} className={styles.navItem}>
                {item.status === "live" ? (
                  <Link className={styles.navLink} href={item.route}>
                    {item.label_ko}
                  </Link>
                ) : (
                  <span className={styles.navLinkDisabled} aria-disabled="true">
                    {item.label_ko}
                  </span>
                )}
                <span className={styles.navBadge} data-status={item.status}>
                  {STATUS_BADGE[item.status]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
