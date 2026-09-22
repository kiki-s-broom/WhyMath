import path from "node:path";

import type { NextConfig } from "next";

/**
 * WhyMath 별도 웹 — Next.js 설정 (단일 앱 · **2 빌드 타깃**).
 *
 * 왜 타깃이 둘인가 (web_strategy §2 배포 요건)
 * -------------------------------------------
 * 랜딩(공개)과 백오피스(내부망)는 **한 코드베이스**를 쓰되(04 §1 "스택·컴포넌트 공유,
 * 배포·인증 도메인만 분리") **산출물은 섞이면 안 된다** — 공개 산출물에 admin 번들이 실리면
 * 내부망 한정(04 §5)이 파일 배포만으로 무너진다.
 *
 * 분리 수단 = `pageExtensions`
 * ---------------------------
 * Next는 라우트 파일(`page`·`layout`·`route`·`robots`·`sitemap` …)을 **파일명 확장자 목록**으로
 * 식별한다. 그래서 admin 라우트 파일에만 `.admin.tsx` 접미를 주고, 타깃별로 이 목록을 바꾼다:
 *
 *   · 공개 타깃(기본) `["tsx","ts"]`      → `app/(public)/page.tsx`·`robots.ts`·`sitemap.ts`만 라우트.
 *                                            `page.admin.tsx`는 **라우트가 아니므로 번들되지 않는다**.
 *   · admin 타깃      `["admin.tsx","admin.ts"]` → `app/layout.admin.tsx`가 루트 레이아웃이 되고
 *                                            `app/admin/**`만 라우트. 랜딩·robots·sitemap은 빠진다.
 *
 * 실측(2026-09-22 · Next 15.5.25): 공개 빌드 라우트 = `/`·`/robots.txt`·`/sitemap.xml`·`/_not-found`
 * (`/admin` 0건) · admin 빌드 라우트 = `/admin`·`/_not-found`(`/` 0건). 양방향으로 실제 갈린다.
 *
 * 이 분리는 **관례가 아니라 계약**이다 — `tests/infra/test_webapp_admin_shell_governance.py`가
 * 접미 규칙·역방향 import 부재를 정적으로 동결하고, CI `webapp` 잡이 두 산출물을 각각 검사한다
 * (접미를 뗀 `app/admin/page.tsx`가 생기는 순간 공개 산출물에 `/admin`이 실리고 CI가 red).
 *
 * 그 밖의 값
 * ---------
 * `output: "export"` = 서버 런타임 없는 정적 산출물(`out/`). 랜딩은 백엔드 호출 0이고, admin
 *   셸도 **브라우저에서** BFF를 호출하는 CSR이라 둘 다 서버가 필요 없다(04 §5 내부망 docker에
 *   정적 파일 서빙만 올리면 된다).
 * `images.unoptimized` = 정적 export에는 이미지 최적화 서버가 없다. 빼면 빌드가 실패한다.
 * `trailingSlash` = 정적 호스팅의 디렉터리 인덱스 관례(`/admin/` → `/admin/index.html`).
 */

/** `WHYMATH_WEB_TARGET=admin`일 때만 백오피스 빌드. 미설정·오타는 **공개 빌드**로 수렴한다 */
const isAdminTarget = process.env.WHYMATH_WEB_TARGET === "admin";

const nextConfig: NextConfig = {
  // 공개 타깃에 `admin.*`가 **없다**는 것이 배포 요건의 집행 지점이다(위 주석 참조).
  pageExtensions: isAdminTarget ? ["admin.tsx", "admin.ts"] : ["tsx", "ts"],
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // 저장소 루트에도 package-lock.json이 있어 Next가 워크스페이스 루트를 잘못 추론한다.
  // 이 앱 디렉터리로 못박아 추론 경고와 잘못된 파일 추적을 없앤다.
  outputFileTracingRoot: path.resolve(import.meta.dirname),
};

export default nextConfig;
