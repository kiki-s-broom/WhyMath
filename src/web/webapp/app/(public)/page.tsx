import { Audience } from "./_components/Audience";
import { BetaCta } from "./_components/BetaCta";
import { Hero } from "./_components/Hero";
import { LegalFooter } from "./_components/LegalFooter";
import { Method } from "./_components/Method";
import { Mission } from "./_components/Mission";

import styles from "./landing.module.css";

/**
 * 공개 랜딩 v1 (WEB-01) — 단일 페이지, 라우트 `/`.
 *
 * 경계(web_strategy §1·CLAUDE.md 슬89):
 *   · 학생 *학습 경험*이 아니라 **유입·소개 표면**이다 — 학습 기능 0.
 *   · 수학 판정·채점 로직 0 (ARCH-10). 계산·동치 판정의 단일 권위는 백엔드 L3다.
 *   · v1은 백엔드 호출 0 — 베타 신청은 외부 폼 *링크*(§3.2).
 * 이 세 경계는 tests/infra/test_webapp_landing_governance.py가 기계로 동결한다.
 */
export default function LandingPage() {
  return (
    <div className={styles.page}>
      <Hero />
      <main id="main">
        <Mission />
        <Method />
        <Audience />
        <BetaCta />
      </main>
      <LegalFooter />
    </div>
  );
}
