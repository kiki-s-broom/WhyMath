// esbuild 번들 스크립트 — main·preload·renderer를 각각 묶는다 (HARN-206).
// 외부 CDN·폰트 요청 0: 렌더러는 자기완결 번들 하나 + index.html + style.css만 쓴다.
import { build, context } from "esbuild";
import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const watch = process.argv.includes("--watch");

const common = { bundle: true, sourcemap: true, logLevel: "info", absWorkingDir: root };
const targets = [
  { entryPoints: ["src/main/main.ts"], outfile: "dist/main/main.js", platform: "node",
    format: "cjs", target: "node22", external: ["electron"] },
  { entryPoints: ["src/preload/preload.ts"], outfile: "dist/preload/preload.js", platform: "node",
    format: "cjs", target: "node22", external: ["electron"] },
  { entryPoints: ["src/renderer/app.ts"], outfile: "dist/renderer/app.js", platform: "browser",
    format: "iife", target: "chrome140" },
];

function copyStatic() {
  mkdirSync(join(root, "dist/renderer"), { recursive: true });
  cpSync(join(root, "src/renderer/index.html"), join(root, "dist/renderer/index.html"));
  cpSync(join(root, "src/renderer/style.css"), join(root, "dist/renderer/style.css"));
  // 개발 모드 창 아이콘 (HARN-208) — 설치본은 EXE에 심긴 assets/icon.ico를 쓴다
  cpSync(join(root, "assets/icon.png"), join(root, "dist/icon.png"));
}

copyStatic();
if (watch) {
  for (const t of targets) (await context({ ...common, ...t })).watch();
} else {
  for (const t of targets) await build({ ...common, ...t });
}
