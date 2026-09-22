"use client";

import { useEffect, useState } from "react";

import { fetchAdminMenu, type AdminMenuResult } from "../_lib/adminApi";
import { clearOperatorToken, readOperatorToken } from "../_lib/adminSession";
import { ADMIN_BUNDLE_MARKER } from "../_lib/marker";

import { AdminNav } from "./AdminNav";
import { OperatorTokenGate } from "./OperatorTokenGate";

import styles from "../admin.module.css";

/**
 * 백오피스 셸 — 크롬(헤더·좌측 내비) + 상태 표시 + 자격증명 수명.
 *
 * 흐름은 하나다: 탭 저장소에서 토큰을 읽고 → 있으면 `GET /v1/admin/menu`를 **1회** 불러
 * 내비를 그린다(04 §2 원칙7). 토큰이 없으면 입력 화면을 대신 띄운다.
 *
 * 왜 상태를 이렇게 장황하게 나누는가 (04 §2 원칙6)
 * ----------------------------------------------
 * 메뉴가 안 보이는 이유는 최소 여섯 가지이고(`adminApi.ts`), 운영자가 해야 할 행동이 전부
 * 다르다 — 주소를 안 박았으면 재빌드, CORS면 서버 설정, 403이면 계정, 빈 메뉴면 역할 부여.
 * 전부 "메뉴 없음"으로 접으면 그 화면은 *측정 실패를 0건으로 위장*하는 전형이 된다.
 * 그래서 사유마다 다른 문장과 **다음 행동**을 함께 낸다.
 */

interface Notice {
  title: string;
  detail: string;
  action: string;
}

/** 실패 사유 → 화면 문구. 여기서만 사람 말로 번역한다(판정은 전부 서버·`adminApi`가 끝냈다). */
function noticeFor(result: Exclude<AdminMenuResult, { kind: "ok" }>): Notice {
  switch (result.kind) {
    case "no-api-base":
      return {
        title: "백엔드 주소가 이 빌드에 없습니다",
        detail:
          "정적 빌드에 API 주소가 박히지 않아 어디에도 요청하지 않았습니다(상대 경로로 " +
          "몰래 대체하지 않습니다).",
        action:
          "NEXT_PUBLIC_WHYMATH_API_BASE_URL 을 내부망 API 주소로 지정해 admin 빌드를 다시 만드세요.",
      };
    case "unreachable":
      return {
        title: "백엔드에 닿지 못했습니다",
        detail:
          "브라우저가 응답을 받지 못했습니다(실패 종류: " +
          result.reason +
          "). 서버가 200을 돌려줬어도 CORS로 차단되면 브라우저는 응답을 넘겨주지 않으므로 " +
          "여기에 나타납니다.",
        action:
          "백엔드의 WHYMATH_CORS_ALLOWED_ORIGINS 에 이 콘솔의 origin이 들어 있는지, API 주소와 " +
          "내부망 경로가 살아 있는지 확인하세요.",
      };
    case "unauthenticated":
      return {
        title: "토큰이 유효하지 않습니다 (401)",
        detail: "만료됐거나 이 백엔드가 발급한 토큰이 아닙니다.",
        action: "로그아웃 후 실 신원 로그인으로 새 액세스 토큰을 받아 다시 입력하세요.",
      };
    case "forbidden":
      return {
        title: "이 계정으로는 콘솔을 열 수 없습니다 (403)",
        detail:
          result.detail.length > 0
            ? "서버 사유: " + result.detail
            : "서버가 사유를 주지 않았습니다.",
        action:
          "시연용 데모 계정은 관리 콘솔에서 거부됩니다(04 §4). 실 신원 운영자 계정으로 " +
          "로그인하세요.",
      };
    case "empty":
      return {
        title: "볼 수 있는 모듈이 0건입니다",
        detail:
          "인증은 됐지만 이 계정의 역할로 열람 가능한 관리 모듈이 없습니다 — 모듈이 없는 " +
          "것이 아니라 권한이 없는 것입니다.",
        action: "운영자 좌석(CONTENT_ADMIN) 부여 여부를 확인하세요.",
      };
    case "http-error":
      return {
        title: "백엔드가 오류를 돌려줬습니다 (HTTP " + String(result.status) + ")",
        detail: "메뉴를 받지 못했습니다.",
        action: "백엔드 로그를 확인하세요.",
      };
    case "malformed":
      return {
        title: "응답을 해석하지 못했습니다",
        detail: "사유: " + result.reason,
        action:
          "프런트와 백엔드의 메뉴 계약이 어긋났을 수 있습니다(GET /v1/admin/menu 응답 스키마).",
      };
  }
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  // `null` = 아직 안 읽음. 서버 렌더와 첫 클라 렌더가 같아야 하므로 저장소는 effect에서 읽는다.
  const [tokenState, setTokenState] = useState<{ token: string | null } | null>(null);
  const [menu, setMenu] = useState<AdminMenuResult | null>(null);

  useEffect(() => {
    setTokenState({ token: readOperatorToken() });
  }, []);

  const token = tokenState?.token ?? null;

  useEffect(() => {
    if (token === null) {
      setMenu(null);
      return;
    }
    let cancelled = false;
    setMenu(null);
    void fetchAdminMenu(token).then((result) => {
      if (!cancelled) setMenu(result);
    });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const signedIn = token !== null;
  // 화면마다 세 번 부르지 않는다 — 같은 입력에 같은 결과인 순수 변환이다.
  const notice = menu !== null && menu.kind !== "ok" ? noticeFor(menu) : null;

  return (
    <div className={styles.shell} data-wm-bundle={ADMIN_BUNDLE_MARKER}>
      <header className={styles.header}>
        {/* 문서의 유일한 h1. 콘솔은 인증 전에도 제목이 있어야 한다(제목 계층 건너뜀 방지). */}
        <h1 className={styles.brand}>
          WhyMath <span className={styles.brandTag}>운영 콘솔</span>
        </h1>
        <p className={styles.headerNote}>내부망 전용 · 공개 인터넷 노출 금지</p>
        {signedIn && (
          <button
            className={styles.signOut}
            type="button"
            onClick={() => {
              clearOperatorToken();
              setTokenState({ token: null });
            }}
          >
            로그아웃
          </button>
        )}
      </header>

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          {tokenState === null ? (
            <p className={styles.sidebarNote}>세션 확인 중…</p>
          ) : !signedIn ? (
            <p className={styles.sidebarNote}>인증 후 모듈 목록이 표시됩니다.</p>
          ) : menu === null ? (
            <p className={styles.sidebarNote}>모듈 목록을 불러오는 중…</p>
          ) : menu.kind === "ok" ? (
            <AdminNav sections={menu.sections} />
          ) : (
            <p className={styles.sidebarNote}>{notice?.title}</p>
          )}
        </aside>

        <main className={styles.main} id="main">
          {tokenState === null ? null : !signedIn ? (
            <OperatorTokenGate onSubmitted={(next) => setTokenState({ token: next })} />
          ) : (
            <>
              {notice !== null && (
                <section className={styles.notice} role="status">
                  <h2 className={styles.noticeTitle}>{notice.title}</h2>
                  <p className={styles.noticeDetail}>{notice.detail}</p>
                  <p className={styles.noticeAction}>{notice.action}</p>
                </section>
              )}
              {children}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
