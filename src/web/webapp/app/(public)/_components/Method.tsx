import styles from "../landing.module.css";

/**
 * 방법론 소개 — **소개만, 기능 데모 아님**(web_strategy §3.1).
 * 학습 기능·수학 판정은 이 페이지에 0이다(ARCH-10 무-수학로직 원칙).
 */
const METHODS = [
  {
    title: "답을 미룹니다",
    body:
      "막혔다고 바로 풀이를 보여 주지 않습니다. 먼저 지금까지 생각한 곳을 묻고, 그다음 한 걸음만 좁혀 갑니다.",
  },
  {
    title: "폴리아 4단계로 걷습니다",
    body:
      "이해 · 계획 · 실행 · 되돌아보기. 수학 교육에서 오래 쓰여 온 문제 해결 4단계를 학습 경로의 뼈대로 씁니다.",
  },
  {
    title: "아는 것과 모르는 것을 나눕니다",
    body:
      "틀린 답을 점수로만 남기지 않고, 어느 개념에서 어긋났는지를 함께 정리합니다(메타인지).",
  },
] as const;

export function Method() {
  return (
    <section className={styles.section} aria-labelledby="method-title">
      <div className={styles.inner}>
        <p className={styles.eyebrow}>어떻게 다른가</p>
        <h2 id="method-title" className={styles.sectionTitle}>
          정답 대신 과정을 먼저 봅니다
        </h2>
        <p className={styles.prose}>
          아래는 와이매스가 학습을 설계하는 방식에 대한 소개입니다. 실제 학습은 앱에서
          이루어집니다.
        </p>
        <ul className={styles.cards}>
          {METHODS.map((m) => (
            <li key={m.title} className={styles.card}>
              <h3 className={styles.cardTitle}>{m.title}</h3>
              <p className={styles.cardBody}>{m.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
