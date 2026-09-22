import { SITE_NAME, SLOGAN_EN, SLOGAN_KR } from "@/lib/site";

import styles from "../landing.module.css";

/**
 * 히어로 — 슬로건 그대로(CLAUDE.md 브랜드 정본).
 * 카피 가드: 효과·성적 단정 금지. "무엇을 하는 앱인가"만 말한다.
 */
export function Hero() {
  return (
    <header className={styles.hero}>
      <div className={styles.inner}>
        <p className={styles.eyebrow}>{SITE_NAME}</p>
        <h1 className={styles.heroTitle}>{SLOGAN_KR}</h1>
        <p className={styles.heroSlogan}>{SLOGAN_EN}</p>
        <p className={styles.heroLead}>
          막힌 문제 앞에서 가장 먼저 필요한 것은 정답이 아니라 <strong>다음 한 걸음</strong>입니다.
          와이매스는 풀이를 대신해 주는 대신, 학생이 지금 무엇을 알고 무엇을 모르는지 스스로
          확인하도록 질문합니다.
        </p>
      </div>
    </header>
  );
}
