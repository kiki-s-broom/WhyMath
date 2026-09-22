import { BETA_FORM_URL } from "@/lib/site";

import styles from "../landing.module.css";

/**
 * 베타 모집 CTA — v1은 **외부 폼 링크**만(web_strategy §3.2). 이 페이지는 폼을 직접 두지
 * 않으며 백엔드도 호출하지 않는다(개인정보 수집 표면 0).
 *
 * 폼 URL이 비어 있으면 죽은 링크 대신 "준비 중"을 렌더한다 — 외부 폼 채택은 개인정보
 * 처리위탁 고지 대상이라 변호사 검토 게이트 통과 전에는 링크 자체가 존재하면 안 된다.
 */
export function BetaCta() {
  return (
    <section className={styles.section} aria-labelledby="beta-title">
      <div className={styles.inner}>
        <p className={styles.eyebrow}>베타</p>
        <h2 id="beta-title" className={styles.sectionTitle}>
          함께 만들어 갈 베타 참여자를 모집합니다
        </h2>
        <div className={styles.ctaBox}>
          <p className={styles.prose} style={{ marginBottom: 0 }}>
            아직 만들어 가는 중인 제품입니다. 먼저 써 보고 불편한 점을 말해 주실 학생·학부모,
            그리고 함께 시험해 볼 학원·학교를 찾고 있습니다.
          </p>
          {BETA_FORM_URL ? (
            <a className={styles.ctaButton} href={BETA_FORM_URL} rel="noopener noreferrer">
              베타 신청하기
            </a>
          ) : (
            <p className={styles.ctaPending}>
              신청 창구는 준비 중입니다. 열리는 대로 이 자리에 안내드리겠습니다.
            </p>
          )}
          <p className={styles.note}>
            신청 과정에서 받는 정보와 그 처리 방식은 신청 창구를 여는 시점에 함께 안내합니다.
          </p>
        </div>
      </div>
    </section>
  );
}
