import { SITE_NAME } from "@/lib/site";

import styles from "../landing.module.css";

/**
 * 법정 표시 푸터 — 사업자 정보·약관·개인정보처리방침의 **자리**(web_strategy §3.1).
 *
 * 실제 문구·링크는 법무 산출물이 확정된 뒤 채운다. 확정 전에 그럴듯한 값을 박으면
 * *없는 사실을 표시하는 것*이 되므로, 비어 있음을 비어 있다고 적는다.
 */
export function LegalFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <p style={{ margin: 0 }}>
          {SITE_NAME} — 답이 아닌, 이유를 묻는 수학
        </p>
        <ul className={styles.footerList}>
          <li>사업자 정보: 공개 시점에 표시합니다.</li>
          <li>이용약관 · 개인정보처리방침: 공개 시점에 링크합니다.</li>
          <li>문의: 공개 시점에 안내합니다.</li>
        </ul>
      </div>
    </footer>
  );
}
