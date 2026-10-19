/**
 * pack.yaml 로더·검증기 테스트 — 승인된 테스트 케이스 15개(정상 10 · 잘못된 입력 5).
 * 픽스처는 tests/fixtures/<케이스>/<pack>/pack.yaml 구조이며, 검사 단위는 디렉터리다.
 */
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

import { runCli } from "../src/cli.js";
import { loadPackDir } from "../src/pack/load.js";
import type { Diagnostic } from "../src/pack/types.js";
import { checkPacks } from "../src/pack/validate.js";

const FIXTURES = fileURLToPath(new URL("./fixtures/", import.meta.url));

/** 픽스처 이름으로 절대 경로를 만든다. */
const fx = (name: string): string => join(FIXTURES, name);

/** 진단 목록에서 코드만 뽑는다. 단언을 짧게 쓰기 위한 도우미. */
const codes = (ds: Diagnostic[]): string[] => ds.map((d) => d.code);

/** 테스트가 만든 임시 디렉터리. 끝나면 지운다. */
const tempDirs: string[] = [];
afterAll(() => {
  for (const d of tempDirs) rmSync(d, { recursive: true, force: true });
});

describe("정상 입력 · 동작 (T01~T10)", () => {
  it("T01 문서 §7 ② 예시 그대로 — 오류·경고 0건", () => {
    const r = checkPacks(fx("T01-doc-example"));
    expect(r.diagnostics).toEqual([]);
    expect(r.packs.map((p) => p.id)).toEqual(["assessment", "foundation", "knowledge"]);
    const assessment = r.packs.find((p) => p.id === "assessment")!;
    expect(assessment.apps).toHaveLength(6);
    expect(assessment.requires).toEqual(["foundation", "knowledge"]);
  });

  it("T02 WhyMath 초기 구성(capability 5 + domain 1) — 통과, requires 그래프 비순환", () => {
    const r = checkPacks(fx("T02-whymath-initial"));
    expect(r.diagnostics).toEqual([]);
    expect(r.packs).toHaveLength(6);
    expect(r.packs.filter((p) => p.kind === "domain").map((p) => p.id)).toEqual(["math"]);
  });

  it("T03 최소 Pack — requires 비어 있고 subject_adapter: none", () => {
    const r = checkPacks(fx("T03-minimal"));
    expect(r.errorCount).toBe(0);
    expect(r.warningCount).toBe(0);
    expect(r.packs[0]).toMatchObject({ id: "foundation", requires: [], subject_adapter: "none" });
  });

  it("T04 apps 5~7 범위 — domain은 미적용, capability는 경고(오류 아님)", () => {
    const r = checkPacks(fx("T04-apps-range"));
    expect(r.errorCount).toBe(0);
    expect(r.diagnostics).toEqual([
      expect.objectContaining({ level: "warning", code: "PACK_APPS_RANGE", file: "tiny/pack.yaml", path: "/apps" }),
    ]);
  });

  it("T05 흐름식 [a, b]와 블록식 '- a' 리스트 — 같은 AST", () => {
    const flow = loadPackDir(fx("T05-style-flow")).packs[0].doc;
    const block = loadPackDir(fx("T05-style-block")).packs[0].doc;
    expect(block).toEqual(flow);
  });

  it("T06 주석·CRLF·BOM — LF 파일과 같은 결과", () => {
    const dir = mkdtempSync(join(tmpdir(), "eos-pack-crlf-"));
    tempDirs.push(dir);
    mkdirSync(join(dir, "foundation"));
    const lf = readFileSync(fx("T05-style-flow/foundation/pack.yaml"), "utf8");
    const crlf = "﻿" + lf.replace(/\n/g, "\r\n").replace("kind: capability", "kind: capability  # 줄 끝 주석");
    writeFileSync(join(dir, "foundation", "pack.yaml"), crlf, "utf8");
    const a = checkPacks(dir);
    const b = checkPacks(fx("T05-style-flow"));
    expect(a.diagnostics).toEqual(b.diagnostics);
    expect(a.packs).toEqual(b.packs);
  });

  it("T07 결정론 — 같은 디렉터리를 두 번 검사하면 JSON이 바이트 단위로 같다", () => {
    const a = JSON.stringify(checkPacks(fx("T02-whymath-initial")));
    const b = JSON.stringify(checkPacks(fx("T02-whymath-initial")));
    expect(a).toBe(b);
    const e1 = JSON.stringify(checkPacks(fx("T09-multi-error")));
    const e2 = JSON.stringify(checkPacks(fx("T09-multi-error")));
    expect(e1).toBe(e2);
  });

  it("T08 오류 위치 — file과 JSON Pointer path(/requires/1)를 가리킨다", () => {
    const r = checkPacks(fx("T08-error-path"));
    expect(r.diagnostics).toEqual([
      expect.objectContaining({ code: "PACK_ID_INVALID", file: "broken/pack.yaml", path: "/requires/1" }),
    ]);
  });

  it("T09 복수 오류 동시 보고 — 3건 모두, 경로 순 정렬 고정", () => {
    const r = checkPacks(fx("T09-multi-error"));
    expect(r.diagnostics.map((d) => [d.path, d.code])).toEqual([
      ["/flow", "PACK_UNKNOWN_FIELD"],
      ["/id", "PACK_ID_INVALID"],
      ["/schema", "PACK_SCHEMA_UNSUPPORTED"],
    ]);
  });

  it("T10 CLI — 정상 디렉터리 exit 0, 오류 디렉터리 exit 1, 사용법 오류 exit 2, 요약 1줄", () => {
    const ok = runCli(["check", fx("T02-whymath-initial")]);
    expect(ok.code).toBe(0);
    expect(ok.lines).toEqual(["pack 6개 검사 — 오류 0건, 경고 0건"]);

    const bad = runCli(["check", fx("E03-cycle")]);
    expect(bad.code).toBe(1);
    expect(bad.lines.at(-1)).toMatch(/^pack 4개 검사 — 오류 2건/);
    expect(bad.lines[0]).toMatch(/^ERROR PACK_REQUIRES_CYCLE assessment\/pack\.yaml:\/requires /);

    expect(runCli([]).code).toBe(2);
    expect(runCli(["check", fx("없는-디렉터리")]).code).toBe(2);
  });
});

describe("잘못된 입력 (E01~E05) — 반드시 거부", () => {
  it("E01 schema: eos.pack/v2 → PACK_SCHEMA_UNSUPPORTED", () => {
    const r = checkPacks(fx("E01-schema-v2"));
    expect(codes(r.diagnostics)).toEqual(["PACK_SCHEMA_UNSUPPORTED"]);
    expect(r.diagnostics[0]).toMatchObject({ file: "assessment/pack.yaml", path: "/schema" });
    // 구조 검증에 실패한 파일은 의미 검사·packs 목록에서 빠진다.
    expect(r.packs.map((p) => p.id)).toEqual(["foundation", "knowledge"]);
  });

  it("E02 논리 혼입(flow 키) → PACK_UNKNOWN_FIELD", () => {
    const r = checkPacks(fx("E02-unknown-field"));
    expect(r.diagnostics).toEqual([
      expect.objectContaining({ code: "PACK_UNKNOWN_FIELD", file: "assessment/pack.yaml", path: "/flow" }),
    ]);
  });

  it("E03 순환 assessment → learning → assessment → PACK_REQUIRES_CYCLE (두 파일 모두)", () => {
    const r = checkPacks(fx("E03-cycle"));
    expect(codes(r.diagnostics)).toEqual(["PACK_REQUIRES_CYCLE", "PACK_REQUIRES_CYCLE"]);
    expect(r.diagnostics.map((d) => d.file)).toEqual(["assessment/pack.yaml", "learning/pack.yaml"]);
    expect(r.diagnostics[0].message).toContain("assessment → learning → assessment");
  });

  it("E04 미존재 Pack 요구 → PACK_REQUIRES_UNKNOWN", () => {
    const r = checkPacks(fx("E04-requires-unknown"));
    expect(r.diagnostics).toEqual([
      expect.objectContaining({ code: "PACK_REQUIRES_UNKNOWN", file: "assessment/pack.yaml", path: "/requires/2" }),
    ]);
  });

  it("E05 db_schema 소유권 충돌 → PACK_DB_SCHEMA_CONFLICT (두 파일 모두)", () => {
    const r = checkPacks(fx("E05-db-schema-conflict"));
    expect(codes(r.diagnostics)).toEqual(["PACK_DB_SCHEMA_CONFLICT", "PACK_DB_SCHEMA_CONFLICT"]);
    expect(r.diagnostics.map((d) => d.file)).toEqual(["learning/pack.yaml", "tutor/pack.yaml"]);
  });
});
