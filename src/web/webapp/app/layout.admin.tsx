import type { Metadata, Viewport } from "next";

import "./globals.css";

/**
 * admin 빌드의 **루트 레이아웃** — `WHYMATH_WEB_TARGET=admin`일 때만 라우트 파일이 된다.
 *
 * 공개 랜딩(`app/layout.tsx`)과 왜 나눠 두는가: 두 산출물이 공유하면 안 되는 것이 `<head>`에
 * 있다. 랜딩의 루트 레이아웃은 SEO 메타데이터(OpenGraph·canonical·sitemap 연계)를 심는데,
 * 내부망 콘솔에 그것이 붙으면 색인 유도 신호를 스스로 만드는 셈이다. 디자인 토큰
 * (`globals.css`)은 그대로 공유한다 — 04 §1 "스택·컴포넌트 공유, 배포·인증 도메인만 분리".
 *
 * `robots: noindex` 는 **2차 방어**다. 1차는 배포 경계(04 §5 내부망 한정 — 공개 인터넷에
 * 올리지 않는다)이고, 이 태그는 그 경계가 실수로 무너진 순간의 완충일 뿐 경계의 대체가 아니다.
 */
export const metadata: Metadata = {
  title: "WhyMath 운영 콘솔",
  description: "WhyMath 내부 운영 백오피스.",
  robots: { index: false, follow: false, nocache: true },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1d3f6e",
};

export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <a className="wm-skip-link" href="#main">
          본문 바로가기
        </a>
        {children}
      </body>
    </html>
  );
}
