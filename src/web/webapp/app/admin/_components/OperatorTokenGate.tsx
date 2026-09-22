"use client";

import { useState } from "react";

import { writeOperatorToken } from "../_lib/adminSession";

import styles from "../admin.module.css";

/**
 * 운영자 토큰 입력 — 셸이 자격증명을 얻는 유일한 입구(04 §4 "콘솔은 실 신원 필수").
 *
 * 왜 여기서 로그인 화면을 만들지 않는가 (범위의 정직한 표시)
 * ------------------------------------------------------
 * 실 신원 발급 경로는 이미 있다 — 카카오·네이버 OAuth(`GET /v1/auth/{provider}/state` →
 * `POST /v1/auth/{provider}/callback`). 그 왕복을 정적 export SPA 안에 다시 구현하면 리다이렉트
 * URI 화이트리스트·state 보관·토큰 갱신까지 **인증 경로가 둘**이 되고, 그것은 셸 태스크가
 * 감당할 범위도 아니고 보안상 좋은 거래도 아니다. 그래서 셸은 발급 경로를 대체하지 않고,
 * 기존 경로가 발급한 토큰을 이 탭에서 받아 쓴다.
 *
 * 데모 토큰: 서버가 막는다
 * -----------------------
 * 클라는 데모 토큰을 식별할 수 없다(JWT에 발급 출처 표식이 없다 — `adminSession.ts` 참조).
 * 데모 계정이면 백엔드가 403을 내고 셸은 그 사유를 그대로 보여 준다. 여기서 흉내 검사를
 * 붙이면 "막고 있다"는 거짓 안심만 생긴다.
 *
 * 취급 규칙: 값을 로그·URL·화면에 다시 쓰지 않는다. 입력은 `type="password"`이고, 저장은
 * 탭 수명 저장소뿐이다.
 */
export function OperatorTokenGate({ onSubmitted }: { onSubmitted: (token: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      className={styles.gate}
      onSubmit={(event) => {
        event.preventDefault();
        const token = value.trim();
        if (token.length === 0) {
          setError("토큰이 비어 있습니다.");
          return;
        }
        if (!writeOperatorToken(token)) {
          // 저장 실패를 성공으로 위장하지 않는다 — 새로고침하면 토큰이 사라질 상태다.
          setError(
            "이 브라우저가 탭 저장소를 막고 있어 토큰을 보관하지 못했습니다(프라이빗 모드·" +
              "사이트 데이터 차단). 설정을 푼 뒤 다시 시도하세요.",
          );
          return;
        }
        setError(null);
        setValue("");
        onSubmitted(token);
      }}
    >
      <h2 className={styles.gateTitle}>운영자 인증</h2>
      <p className={styles.gateNote}>
        실 신원 로그인(카카오·네이버)으로 발급받은 액세스 토큰을 붙여 넣으세요. 시연용 데모
        계정의 토큰은 서버가 거부합니다. 토큰은 <strong>이 탭에서만</strong> 보관되며 탭을 닫으면
        사라집니다.
      </p>
      <label className={styles.gateLabel} htmlFor="wm-operator-token">
        액세스 토큰
      </label>
      <input
        id="wm-operator-token"
        className={styles.gateInput}
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      {error !== null && (
        <p className={styles.gateError} role="alert">
          {error}
        </p>
      )}
      <button className={styles.gateSubmit} type="submit">
        콘솔 열기
      </button>
    </form>
  );
}
