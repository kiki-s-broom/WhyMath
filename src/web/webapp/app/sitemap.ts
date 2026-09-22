import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

// 정적 export에서는 이 라우트도 빌드 타임에 한 번 구워야 한다(미지정 시 `next build`가 거부한다).
export const dynamic = "force-static";

/** sitemap.xml — 현재 공개 라우트는 랜딩 1페이지뿐이다(web_strategy §3.1). */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${SITE_URL}/`,
      changeFrequency: "monthly",
      priority: 1,
    },
  ];
}
