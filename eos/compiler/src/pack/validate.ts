/**
 * pack.yaml 검증기 — Compiler 파이프라인 ①(구조)·③(의미 규칙).
 *
 * 1) 구조: JSON Schema(eos.pack.v1.schema.json)를 Ajv로 검사한다. 문서 §7 "DSL 자체도 JSON Schema로 정의".
 * 2) 의미: 스키마로는 적을 수 없는 규칙 — 중복·순환·소유권 충돌 — 을 코드로 검사한다.
 *
 * 순수 함수만 둔다. LLM·AI SDK import 금지(§15 ARCH-005). 같은 입력에는 항상 같은 출력(§8 결정론)이며,
 * 그래서 모든 결과를 마지막에 정렬한다.
 */
import { readFileSync } from "node:fs";
import { Ajv2020, type ErrorObject } from "ajv/dist/2020.js";

import { loadPackDir } from "./load.js";
import type { Diagnostic, LoadedPack, PackManifest, ValidPack } from "./types.js";

/** Kernel 전용 스키마 이름. Pack이 가져가면 안 된다(§9 표: eos_kernel.*). */
const RESERVED_DB_SCHEMAS = new Set(["eos_kernel"]);

/** capability Pack의 Small App 적정 개수(§5 표). 범위 밖은 경고만 한다(검토 W1). */
const APPS_RANGE = { min: 5, max: 7 };

// 스키마 파일을 한 번만 읽어 컴파일한다. 검증기 전체가 공유한다.
const schemaUrl = new URL("../schemas/eos.pack.v1.schema.json", import.meta.url);
const packSchema = JSON.parse(readFileSync(schemaUrl, "utf8")) as object;
const ajv = new Ajv2020({ allErrors: true, strict: true });
const validateAgainstSchema = ajv.compile(packSchema);

/** 진단 1건을 만드는 짧은 도우미. 매번 객체 리터럴을 쓰는 반복을 줄인다. */
function diag(
  level: Diagnostic["level"],
  code: string,
  file: string,
  path: string,
  message: string,
): Diagnostic {
  return { level, code, file, path, message };
}

/**
 * Ajv 오류 1건을 EOS 오류 코드로 번역한다.
 * Ajv의 keyword(어떤 규칙이 깨졌나)와 instancePath(어디서)를 보고 문서 §8 형식의 코드를 고른다.
 */
function translateAjvError(err: ErrorObject, file: string): Diagnostic {
  const path = err.instancePath;
  const params = err.params as Record<string, unknown>;
  switch (err.keyword) {
    case "const":
      if (path === "/schema") {
        return diag("error", "PACK_SCHEMA_UNSUPPORTED", file, path, "schema는 eos.pack/v1만 지원한다. 필드가 바뀌면 v2 스키마를 먼저 만든다(§7)");
      }
      break;
    case "additionalProperties":
      return diag("error", "PACK_UNKNOWN_FIELD", file, `${path}/${String(params.additionalProperty)}`, `정의되지 않은 키 '${String(params.additionalProperty)}'. v0.1은 구조만 선언하고 논리(if·flow·goal)를 넣지 않는다(§7)`);
    case "required":
      return diag("error", "PACK_FIELD_MISSING", file, `${path}/${String(params.missingProperty)}`, `필수 키 '${String(params.missingProperty)}'가 없다`);
    case "enum":
      if (path === "/kind") return diag("error", "PACK_KIND_INVALID", file, path, "kind는 capability 또는 domain이어야 한다. content는 content.yaml로 선언한다(검토 F3)");
      if (path === "/subject_adapter") return diag("error", "PACK_ADAPTER_INVALID", file, path, "subject_adapter는 required 또는 none이어야 한다(검토 F5)");
      break;
    case "pattern":
      if (path === "/id") return diag("error", "PACK_ID_INVALID", file, path, "id는 소문자 kebab-case여야 한다. 예: assessment, math-concept-graph");
      if (path.startsWith("/apps/")) return diag("error", "PACK_APP_NAME_INVALID", file, path, "apps 항목은 소문자 kebab-case여야 한다. 전체 App ID는 <pack id>.<app>으로 파생된다(검토 F4)");
      if (path.startsWith("/requires/")) return diag("error", "PACK_ID_INVALID", file, path, "requires 항목은 Pack ID(소문자 kebab-case)여야 한다");
      if (path === "/db_schema") return diag("error", "PACK_DB_SCHEMA_INVALID", file, path, "db_schema는 PostgreSQL 스키마 이름(소문자·숫자·_)이어야 한다");
      break;
    case "type":
      return diag("error", "PACK_TYPE_INVALID", file, path, `값의 형이 틀렸다: ${String(params.type)}이어야 한다`);
    default:
      break;
  }
  return diag("error", "PACK_SCHEMA_VIOLATION", file, path, err.message ?? "스키마 위반");
}

/**
 * 구조 검증(Compiler ①). YAML 객체가 eos.pack/v1 스키마에 맞는지 본다.
 * 통과하면 manifest를, 실패하면 진단 목록을 돌려준다. 오류는 첫 건에서 멈추지 않고 전부 모은다.
 */
export function validateStructure(pack: LoadedPack): { manifest?: PackManifest; diagnostics: Diagnostic[] } {
  if (validateAgainstSchema(pack.doc)) {
    return { manifest: pack.doc as PackManifest, diagnostics: [] };
  }
  const diagnostics = (validateAgainstSchema.errors ?? []).map((e: ErrorObject) => translateAjvError(e, pack.file));
  return { diagnostics };
}

/**
 * 파일 하나만 보고 판단할 수 있는 의미 규칙.
 * - apps 중복 금지
 * - capability Pack의 apps 5~7개는 경고(§5 "적정 크기" — 실패 조건이 아니다)
 * - 자기 자신을 requires에 적지 않는다(§7 순환 금지의 가장 짧은 형태)
 */
export function validatePackLocal(p: ValidPack): Diagnostic[] {
  const out: Diagnostic[] = [];
  const { manifest: m, file } = p;

  const seen = new Set<string>();
  m.apps.forEach((app, i) => {
    if (seen.has(app)) out.push(diag("error", "PACK_APPS_DUPLICATE", file, `/apps/${i}`, `app '${app}'이 두 번 선언됐다`));
    seen.add(app);
  });

  if (m.kind === "capability" && (m.apps.length < APPS_RANGE.min || m.apps.length > APPS_RANGE.max)) {
    out.push(diag("warning", "PACK_APPS_RANGE", file, "/apps", `capability Pack의 Small App은 ${APPS_RANGE.min}~${APPS_RANGE.max}개가 적정이다(§5). 현재 ${m.apps.length}개`));
  }

  m.requires.forEach((req, i) => {
    if (req === m.id) out.push(diag("error", "PACK_REQUIRES_SELF", file, `/requires/${i}`, `Pack '${m.id}'이 자기 자신을 요구한다`));
  });
  return out;
}

/**
 * Tarjan 알고리즘으로 강하게 연결된 성분(SCC)을 찾는다.
 * 쉽게 말해 "서로 돌아서 다시 만나는 Pack 묶음"을 찾는 것이며, 크기 2 이상이면 순환이다.
 * 자기 자신 간선은 validatePackLocal이 따로 보고하므로 여기서는 뺀다.
 */
function findCycles(graph: Map<string, string[]>): string[][] {
  let index = 0;
  const indexOf = new Map<string, number>();
  const lowOf = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const cycles: string[][] = [];

  const visit = (v: string): void => {
    indexOf.set(v, index);
    lowOf.set(v, index);
    index += 1;
    stack.push(v);
    onStack.add(v);
    for (const w of graph.get(v) ?? []) {
      if (w === v) continue;
      if (!indexOf.has(w)) {
        visit(w);
        lowOf.set(v, Math.min(lowOf.get(v)!, lowOf.get(w)!));
      } else if (onStack.has(w)) {
        lowOf.set(v, Math.min(lowOf.get(v)!, indexOf.get(w)!));
      }
    }
    if (lowOf.get(v) === indexOf.get(v)) {
      const component: string[] = [];
      let w: string;
      do {
        w = stack.pop()!;
        onStack.delete(w);
        component.push(w);
      } while (w !== v);
      if (component.length > 1) cycles.push(component.sort());
    }
  };

  for (const v of [...graph.keys()].sort()) {
    if (!indexOf.has(v)) visit(v);
  }
  return cycles;
}

/**
 * 여러 pack.yaml을 함께 봐야 알 수 있는 의미 규칙(검토 §4 결론: 검사 단위는 디렉터리).
 * - Pack ID 중복
 * - requires가 가리키는 Pack이 실제로 있는가
 * - requires 순환(§7)
 * - capability Pack이 domain Pack을 직접 요구하지 않는가 — 과목 의존은 subject_adapter로만(§12 ARCH-004).
 *   ※ 추론 규칙: ARCH-004 원문은 코드 import 금지이며 pack.yaml requires 금지라고 명시하지 않았다. 문서 확정 필요.
 * - db_schema 소유권: 예약어 금지, 두 Pack이 같은 스키마를 갖지 않는다(§9 DATA-001)
 */
export function validatePackSet(packs: ValidPack[]): Diagnostic[] {
  const out: Diagnostic[] = [];
  const byId = new Map<string, ValidPack[]>();
  for (const p of packs) {
    const list = byId.get(p.manifest.id) ?? [];
    list.push(p);
    byId.set(p.manifest.id, list);
  }

  for (const [id, list] of byId) {
    if (list.length > 1) {
      for (const p of list) out.push(diag("error", "PACK_ID_DUPLICATE", p.file, "/id", `Pack ID '${id}'가 파일 ${list.length}개에 선언됐다`));
    }
  }

  // ID 중복이 있으면 그래프가 모호하므로, 그래프 검사는 첫 선언만 대표로 쓴다.
  const rep = new Map<string, ValidPack>([...byId].map(([id, list]) => [id, list[0]]));
  const graph = new Map<string, string[]>();

  for (const p of packs) {
    const m = p.manifest;
    const edges: string[] = [];
    m.requires.forEach((req, i) => {
      const target = rep.get(req);
      if (!target) {
        out.push(diag("error", "PACK_REQUIRES_UNKNOWN", p.file, `/requires/${i}`, `요구한 Pack '${req}'이 검사 범위 안에 없다`));
        return;
      }
      if (m.kind === "capability" && target.manifest.kind === "domain") {
        out.push(diag("error", "PACK_REQUIRES_DOMAIN", p.file, `/requires/${i}`, `capability Pack '${m.id}'이 domain Pack '${req}'을 직접 요구한다. 과목 의존은 subject_adapter: required로만 표현한다(§12 ARCH-004, 추론 규칙)`));
      }
      edges.push(req);
    });
    if (rep.get(m.id) === p) graph.set(m.id, edges);
  }

  for (const cycle of findCycles(graph)) {
    const chain = [...cycle, cycle[0]].join(" → ");
    for (const id of cycle) {
      out.push(diag("error", "PACK_REQUIRES_CYCLE", rep.get(id)!.file, "/requires", `requires 순환: ${chain} (§7 순환 금지)`));
    }
  }

  const bySchema = new Map<string, ValidPack[]>();
  for (const p of packs) {
    const s = p.manifest.db_schema;
    if (RESERVED_DB_SCHEMAS.has(s)) {
      out.push(diag("error", "PACK_DB_SCHEMA_RESERVED", p.file, "/db_schema", `'${s}'는 Kernel 전용 스키마다(§9)`));
    }
    const list = bySchema.get(s) ?? [];
    list.push(p);
    bySchema.set(s, list);
  }
  for (const [s, list] of bySchema) {
    if (list.length > 1) {
      const owners = list.map((p) => p.manifest.id).sort().join(", ");
      for (const p of list) out.push(diag("error", "PACK_DB_SCHEMA_CONFLICT", p.file, "/db_schema", `스키마 '${s}'를 Pack ${list.length}개(${owners})가 소유한다. Pack마다 하나씩이어야 한다(§9 DATA-001)`));
    }
  }
  return out;
}

/** 진단을 파일 → 경로 → 코드 → 메시지 순으로 정렬한다. 출력 순서를 고정해 결정론을 지킨다. */
export function sortDiagnostics(diagnostics: Diagnostic[]): Diagnostic[] {
  const key = (d: Diagnostic): string => `${d.file}\u0000${d.path}\u0000${d.code}\u0000${d.message}`;
  return [...diagnostics].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

/** checkPacks의 결과. errorCount가 0이면 통과다. */
export interface CheckResult {
  diagnostics: Diagnostic[];
  packs: PackManifest[];
  errorCount: number;
  warningCount: number;
}

/**
 * 전체 파이프라인: 디렉터리 로드 → 구조 검증 → 파일 단위 의미 → 집합 단위 의미 → 정렬.
 * 구조 검증에 실패한 파일은 의미 검사에서 제외한다(깨진 형태로는 규칙을 판단할 수 없다).
 */
export function checkPacks(rootDir: string): CheckResult {
  const loaded = loadPackDir(rootDir);
  const diagnostics: Diagnostic[] = [...loaded.diagnostics];
  const valid: ValidPack[] = [];

  for (const pack of loaded.packs) {
    const r = validateStructure(pack);
    diagnostics.push(...r.diagnostics);
    if (r.manifest) valid.push({ file: pack.file, manifest: r.manifest });
  }
  for (const p of valid) diagnostics.push(...validatePackLocal(p));
  diagnostics.push(...validatePackSet(valid));

  const sorted = sortDiagnostics(diagnostics);
  return {
    diagnostics: sorted,
    packs: valid.map((p) => p.manifest),
    errorCount: sorted.filter((d) => d.level === "error").length,
    warningCount: sorted.filter((d) => d.level === "warning").length,
  };
}
