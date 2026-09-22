import path from "node:path";

import type { NextConfig } from "next";

/**
 * WhyMath 별도 웹 — Next.js 설정.
 *
 * `output: "export"`  = 서버 런타임 없는 **완전 정적 산출물**(`out/`).
 *   랜딩은 백엔드 호출 0(외부 폼 *링크*만 — web_strategy §3.2)이므로 서버가 필요 없다.
 *   정적 export는 관리형 CDN·정적 버킷 어디에나 그대로 올라간다(배포 확정은 WEB-02·Kiki).
 *
 * `images.unoptimized` = 정적 export에는 이미지 최적화 서버가 없다. 랜딩은 SVG·CSS만 쓰므로
 *   비용이 없고, 이 값을 빼면 `next build`가 실패한다.
 *
 * `trailingSlash` = 정적 호스팅의 디렉터리 인덱스 관례(`/beta/` → `/beta/index.html`)에 맞춘다.
 */
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // 저장소 루트에도 package-lock.json이 있어 Next가 워크스페이스 루트를 잘못 추론한다.
  // 이 앱 디렉터리로 못박아 추론 경고와 잘못된 파일 추적을 없앤다.
  outputFileTracingRoot: path.resolve(import.meta.dirname),
};

export default nextConfig;
