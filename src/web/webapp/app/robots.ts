import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

// 정적 export에서는 이 라우트도 빌드 타임에 한 번 구워야 한다(미지정 시 `next build`가 거부한다).
export const dynamic = "force-static";

/**
 * robots.txt — 정적 export 시 `out/robots.txt`로 구워진다(web_strategy §3.3).
 *
 * 실제 색인은 **배포된 뒤에만** 일어난다. 배포 자체가 WEB-02이고 그 선결이 변호사 검토
 * 게이트이므로, 이 파일이 공개 전에 색인을 유발할 경로는 없다.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
