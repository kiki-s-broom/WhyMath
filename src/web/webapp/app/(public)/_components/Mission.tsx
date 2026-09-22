import styles from "../landing.module.css";

/**
 * 문제의식 — 사교육 격차(PRD 특성 #87).
 * 카피 가드: 격차를 "해소한다"는 완료형 단정 대신 지향(목표)으로 쓴다. 효과는 미검증이다.
 */
export function Mission() {
  return (
    <section className={styles.section} aria-labelledby="mission-title">
      <div className={styles.inner}>
        <p className={styles.eyebrow}>왜 만드나</p>
        <h2 id="mission-title" className={styles.sectionTitle}>
          질문을 받아 줄 사람이 있는지가, 배움의 차이를 만듭니다
        </h2>
        <p className={styles.prose}>
          막혔을 때 &ldquo;여기까지는 어떻게 생각했어?&rdquo;라고 물어봐 줄 사람이 곁에 있는
          학생과 그렇지 않은 학생의 하루는 다릅니다. 그 차이는 대개 학생의 노력이 아니라
          환경에서 옵니다.
        </p>
        <p className={styles.prose}>
          와이매스가 만들려는 것은 <strong>그 질문을 대신 던지는 도구</strong>입니다. 답을 빨리
          알려 주는 일은 이미 잘하는 서비스가 많습니다. 저희가 붙잡고 있는 문제는 그 반대편,
          <strong> 학생이 스스로 생각하는 시간을 어떻게 지켜 주는가</strong>입니다.
        </p>
      </div>
    </section>
  );
}
