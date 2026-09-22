import type { Metadata, Viewport } from "next";

import { SITE_DESCRIPTION, SITE_NAME, SITE_URL, SLOGAN_KR } from "@/lib/site";

import "./globals.css";

/**
 * 루트 레이아웃 — 전 라우트 공통 문서 골격.
 *
 * `lang="ko"`는 접근성 필수 항목이다(스크린리더 발음 언어 결정 — KWCAG 2.2 "기본 언어 표시").
 * 메타데이터는 정적 export 시 빌드 타임에 `<head>`로 박힌다(런타임 조회 없음).
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} — ${SLOGAN_KR}`,
    template: `%s | ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: SITE_NAME,
    title: `${SITE_NAME} — ${SLOGAN_KR}`,
    description: SITE_DESCRIPTION,
    url: "/",
  },
  twitter: {
    card: "summary",
    title: `${SITE_NAME} — ${SLOGAN_KR}`,
    description: SITE_DESCRIPTION,
  },
  alternates: { canonical: "/" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // maximumScale·userScalable 제한 금지 — 확대를 막으면 저시력 사용자가 읽을 수 없다.
  themeColor: "#1d3f6e",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
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
