/**
 * pack.yaml 로더(파서) — Compiler 파이프라인 ①의 입력 단계.
 *
 * 새 문법을 만들지 않고 YAML 그대로 읽는다(문서 §7 "YAML + JSON Schema"). 이 모듈은
 * 파일을 찾고 YAML을 객체로 바꾸는 일만 하며, 내용이 맞는지는 validate.ts가 본다.
 * 결정론(§8): 파일 탐색 결과를 항상 정렬해 같은 입력에 같은 순서를 보장한다.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { parse as parseYaml, YAMLParseError } from "yaml";

import type { Diagnostic, LoadedPack } from "./types.js";

/** Pack 선언 파일의 고정 이름. */
export const PACK_FILE_NAME = "pack.yaml";

/** 탐색에서 건너뛸 디렉터리. 의존성·VCS·산출물 폴더는 Pack 선언이 있을 자리가 아니다. */
const SKIPPED_DIRS = new Set(["node_modules", ".git", "generated", "dist"]);

/**
 * 루트 아래의 모든 pack.yaml 경로를 찾는다.
 * 재귀 탐색 결과를 문자열 순으로 정렬해 돌려준다(결정론).
 */
export function findPackFiles(rootDir: string): string[] {
  const found: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      const st = statSync(full);
      if (st.isDirectory()) {
        if (!SKIPPED_DIRS.has(name)) walk(full);
      } else if (name === PACK_FILE_NAME) {
        found.push(full);
      }
    }
  };
  walk(rootDir);
  return found.sort();
}

/** 검사 루트 기준 상대 경로를 `/` 구분자로 만든다. Windows에서도 같은 출력이 나오게 한다. */
export function toPosixRelative(rootDir: string, file: string): string {
  return relative(rootDir, file).split("\\").join("/");
}

/**
 * pack.yaml 한 개를 읽어 객체로 바꾼다.
 * YAML 문법 오류(중복 키 포함)는 예외를 던지지 않고 PACK_YAML_INVALID 진단으로 돌려준다.
 */
export function loadPackFile(
  file: string,
  rootDir: string,
): { pack?: LoadedPack; diagnostics: Diagnostic[] } {
  const rel = toPosixRelative(rootDir, file);
  // BOM(파일 머리의 보이지 않는 표식)은 Windows 편집기가 붙이곤 하므로 떼어 낸다.
  const text = readFileSync(file, "utf8").replace(/^\uFEFF/, "");
  try {
    // uniqueKeys: 같은 키가 두 번 나오면 오류. 조용히 덮어쓰는 것은 결정론에 반한다.
    const doc: unknown = parseYaml(text, { uniqueKeys: true });
    return { pack: { file: rel, doc }, diagnostics: [] };
  } catch (err) {
    const message = err instanceof YAMLParseError ? err.message.split("\n")[0] : String(err);
    return {
      diagnostics: [
        { level: "error", code: "PACK_YAML_INVALID", file: rel, path: "", message: `YAML 문법 오류: ${message}` },
      ],
    };
  }
}

/** 루트 아래 pack.yaml을 전부 로드한다. 한 파일의 문법 오류가 다른 파일 로드를 막지 않는다. */
export function loadPackDir(rootDir: string): { packs: LoadedPack[]; diagnostics: Diagnostic[] } {
  const packs: LoadedPack[] = [];
  const diagnostics: Diagnostic[] = [];
  for (const file of findPackFiles(rootDir)) {
    const result = loadPackFile(file, rootDir);
    if (result.pack) packs.push(result.pack);
    diagnostics.push(...result.diagnostics);
  }
  return { packs, diagnostics };
}
