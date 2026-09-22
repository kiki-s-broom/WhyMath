import styles from "../landing.module.css";

/**
 * 대상 — 페르소나 A(일반고 고3) 우선 메시지 + 학부모·교사 안내(PRD §3·web_strategy §3.1).
 * 카피 가드: 대상별 "이런 분께 도움이 됩니다" 같은 효과 암시 대신 "무엇을 볼 수 있는가"로 쓴다.
 */
export function Audience() {
  return (
    <section className={styles.section} aria-labelledby="audience-title">
      <div className={styles.inner}>
        <p className={styles.eyebrow}>누구를 위해</p>
        <h2 id="audience-title" className={styles.sectionTitle}>
          먼저 일반계 고등학교 3학년과 함께 시작합니다
        </h2>
        <p className={styles.prose}>
          첫 버전은 수능·내신을 함께 준비하는 고3 학생의 하루에 맞춰 만들고 있습니다. 다른
          학년과 과정은 이후 단계에서 넓혀 갑니다.
        </p>
        <dl className={styles.audienceList}>
          <div className={styles.card}>
            <dt className={styles.audienceTerm}>학생</dt>
            <dd className={styles.cardBody} style={{ margin: 0 }}>
              손으로 푼 풀이를 단계별로 확인하고, 막힌 지점에서 힌트가 아니라 질문을 받습니다.
            </dd>
          </div>
          <div className={styles.card}>
            <dt className={styles.audienceTerm}>학부모</dt>
            <dd className={styles.cardBody} style={{ margin: 0 }}>
              점수 순위가 아니라 어떤 개념을 붙잡고 있는지를 봅니다. 미성년자 개인정보 처리
              기준은 공개 시점에 처리방침으로 함께 안내합니다.
            </dd>
          </div>
          <div className={styles.card}>
            <dt className={styles.audienceTerm}>교사 · 학원</dt>
            <dd className={styles.cardBody} style={{ margin: 0 }}>
              성취기준 코드 기준으로 학습 현황을 정리합니다. 교사용 화면은 이후 단계에서
              준비합니다.
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
