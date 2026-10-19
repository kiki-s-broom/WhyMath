/**
 * eos.pack/v1 — Pack 선언(pack.yaml)의 타입과 진단(오류·경고) 형식.
 *
 * 설계 정본: EOS 멀티과목 아키텍처 문서(2026-10-08) §7 ②(pack.yaml 필드) · §8(Compiler 실패 코드 형식).
 * Pack에는 버전이 없다(§4) — 저장소 커밋이 곧 버전이다.
 */

/** Pack 종류. content는 content.yaml(eos.content/v1) 전용이라 여기 없다(검토 F3). */
export type PackKind = "capability" | "domain";

/** 과목 Adapter 필요 여부. 문서는 `required`만 예시했고 반대값은 `none`으로 정했다(검토 F5). */
export type SubjectAdapter = "required" | "none";

/** 구조 검증을 통과한 pack.yaml 한 개의 내용. 키 7개, 그 외 없음. */
export interface PackManifest {
  schema: "eos.pack/v1";
  /** Pack ID. kebab-case. 예: assessment, math-concept-graph */
  id: string;
  kind: PackKind;
  /** Small App 이름 목록. 전체 App ID는 `<id>.<app>`으로 파생한다(검토 F4). */
  apps: string[];
  /** 의존하는 Pack ID 목록. 순환 금지(§7). */
  requires: string[];
  /** PostgreSQL 스키마 이름 = 테이블 소유권(§9 DATA-001). Pack마다 유일. */
  db_schema: string;
  subject_adapter: SubjectAdapter;
}

/** 진단 등급. error는 빌드 실패, warning은 보고만 한다(§6 CONTRACT_DEPRECATED와 같은 범주). */
export type DiagnosticLevel = "error" | "warning";

/**
 * 진단 1건. 문서 §8의 실패 코드 형식(UPPER_SNAKE)을 따른다.
 * path는 JSON Pointer(예: `/requires/1`)로 파일 안 위치를 가리킨다.
 */
export interface Diagnostic {
  level: DiagnosticLevel;
  code: string;
  /** 검사 루트 기준 상대 경로. OS와 무관하게 `/` 구분자. */
  file: string;
  path: string;
  message: string;
}

/** YAML 로드까지 끝난(아직 검증 전) pack.yaml 한 개. */
export interface LoadedPack {
  file: string;
  /** YAML을 그대로 객체화한 값. 검증 전이므로 어떤 형태든 올 수 있다. */
  doc: unknown;
}

/** 구조 검증까지 통과한 Pack. 집합 단위 의미 검사의 입력. */
export interface ValidPack {
  file: string;
  manifest: PackManifest;
}
