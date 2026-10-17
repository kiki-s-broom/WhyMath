// Playwright 설정 (HARN-206) — renderer(Chromium · 픽스처 API · file://)와 electron(실제 앱 · xvfb) 두 프로젝트.
// 브라우저는 PLAYWRIGHT_BROWSERS_PATH(/opt/pw-browsers)의 기설치본을 쓴다 — `npx playwright install` 금지.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { trace: "retain-on-failure" },
  projects: [
    { name: "renderer", testMatch: /renderer\.spec\.ts/, use: { browserName: "chromium", viewport: { width: 1500, height: 940 } } },
    { name: "electron", testMatch: /electron\.spec\.ts/ },
  ],
});
