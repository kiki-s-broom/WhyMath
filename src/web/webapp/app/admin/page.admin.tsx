import styles from "./admin.module.css";

/**
 * 콘솔 홈 — 셸이 무엇이고 무엇이 아닌지를 운영자에게 **먼저** 말한다.
 *
 * 이 화면에 지표를 띄우지 않는 이유: Phase A는 read-only 관측이고(04 §7), 지표 화면은
 * 레지스트리에 `dashboard_kpi`로 이미 좌석이 있다. 좌석이 있는 것을 셸이 미리 흉내 내면
 * 그 화면이 생길 때 두 곳이 된다. 셸은 셸의 일만 한다.
 */
export default function AdminHome() {
  return (
    <section className={styles.home}>
      <h2 className={styles.homeTitle}>콘솔 개요</h2>
      <p className={styles.homeLead}>
        왼쪽 목록은 서버의 모듈 레지스트리에서 그대로 받아 옵니다. 이 화면에는 메뉴 정의가
        없으므로, 백엔드에 관리 모듈이 하나 늘면 별도 작업 없이 목록에 나타납니다.
      </p>
      <h3 className={styles.homeSubTitle}>지금 열 수 있는 것</h3>
      <p className={styles.homeBody}>
        현재 단계에서 각 모듈은 <strong>데이터·엔진은 있고 화면이 아직 없는</strong> 상태입니다.
        그래서 목록에는 보이되 눌리지 않습니다 — 없는 기능을 숨기지 않고, 있는 것처럼 보이게
        하지도 않기 위해서입니다. 화면이 실제로 올라간 모듈만 링크가 살아납니다.
      </p>
      <h3 className={styles.homeSubTitle}>취급 주의</h3>
      <p className={styles.homeBody}>
        이 콘솔은 내부망에서만 사용합니다. 학생·보호자 정보는 서버에서 이미 집계·마스킹된 뒤
        전달되며, 원자료는 이 화면에 오지 않습니다. 열람 자체가 감사 기록으로 남습니다.
      </p>
    </section>
  );
}
