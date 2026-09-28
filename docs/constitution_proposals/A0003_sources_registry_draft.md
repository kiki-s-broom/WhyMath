# 개정 기록 A0003 — 원본 등록부(sources) 실제 경로 정정 (초안)

- 상태: **초안 — 채택 전** (헌법 제11조: 개정은 사람만 한다. 이 문서는 AI가 작성한 초안이다)
- 일자: 2026-09-28 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
- 대상: `constitution/rules.yaml` v1.0 → v1.0.1 — `sources:` 9건과 `version` 줄만 바꾼다(규칙 14건은 바이트 동일)
- 정정안 파일: `docs/constitution_proposals/rules_v1.0.1_sources_fixed.yaml`
- 태스크·게이트: `CONST-02` · `G-const-sources-registry-adopt`

## 사유

헌법 v1.0 제정(A0001) 때 원본 등록부의 경로는 **제안 경로**였다(rules.yaml 머리말 ⚠ 주석). 이 저장소에
설치하고 위헌 심사를 돌리자 9건 중 7건이 차단됐다 — 제안 경로 6건이 저장소에 없고(`content/*.yaml`·
`schemas/item.schema.json`·`docs/copyright/…`·`docs/planning/…xlsx`), 외부 원본 1건의 판 표기가
자리표시자("고시 번호·판 확인 후 기입")였다. 제7조("원본은 한 곳, 등록되지 않은 원본은 인정하지 않는다")를
지키려면 등록부가 **실제 정본 위치**를 가리켜야 한다.

## 정정 내역 (근거는 모두 코드가 실제로 읽는 경로 — 1차 조사 + 독립 재검증)

| 원본 | 제안 경로 (v1.0) | 정정 경로 (v1.0.1) | 근거 (증거 등급) |
|---|---|---|---|
| 성취기준 | 교육부 고시 원문 (외부·판 미기입) | `data/corpus/standards_v1/standards.json` | 적재기가 읽는 경로 `l1/standards/populate.py:31` · 895건 실측 · 고시 제2022-33호·제2015-74호 (E3) |
| 개념 그래프 | `content/concept_graph.yaml` | `data/corpus/atom_graph_v1/graph.json` | 런타임 정본(원자 2,683·엣지 2,210) · 437개념판은 `_provenance` 가 감사 전용 스냅샷으로 격하 (E3) |
| 오개념 DB | `content/misconceptions.yaml` | `data/corpus/misconceptions_v1/misconceptions.json` | M-id 843건 실측 · kebab 67종·op-code 10종은 version 칸에 병기 (E3) |
| 수능 시그니처 패턴 | `content/csat_patterns.yaml` | `src/backend/whymath_backend/schema/enums.py` | `SignaturePattern` 10종 폐쇄 enum — 데이터 파일을 새로 만들면 enum·DDL·YAML 3중 정본이 된다 (E3) |
| 문항 데이터 구조 | `schemas/item.schema.json` | `src/backend/whymath_backend/schema/problem.py` | Pydantic 이 검증 정본(ORM·Dart 가 "정본: schema/problem.py" 명시) · `schemas/v1.1/problem.schema.yaml` 은 자기 머리말이 "비정본" (E2) |
| 파이프라인 실행 순서 | `pipeline.yaml` | `pipeline.yaml` (신설 · 28노드) | `CONST-02` 가 코드 기반으로 작성 · `pipeline_check.py` 통과 (E3) |
| 저작권 허용 기준 | `docs/copyright/…v2.0.md` | `docs/data/licensing_safety.md` | `docs/legal/copyright_gradient.md:7` 이 매트릭스 정본으로 지정 · 원문은 `docs/legal/copyright_guide_v2.md` (E2) |
| EOS 기능 목록 | `docs/planning/…기능재배치.xlsx` (저장소 밖) | `scripts/analysis/eos_feature_inventory_v2.py` | 저장소는 "재현 가능한 정의로 기계 도출한 장부"를 정본으로 결정(생성기 docstring) — 외부 xlsx 수치와의 개수 정합은 판정 대상 아님 (E2) |
| 학습자 응답 상태 | PostgreSQL (외부) | 외부 유지 · 판 표기 실값화 | 코드 head `8c19e8a611e4` · 운영 DB 스탬프 `d6e7f8a9b0c1` (E2) |

## 영향 범위

- 위헌 심사 원본 등록부 차단: 7건 → **0건**(모의 사본 실측 · `audit.py --sources-only` exit 0).
- 규칙 14건·조문·단계 사다리는 바뀌지 않는다.
- 채택 후 `STAGE` 를 2로 올릴 수 있다 — 2단계 규칙 R0-01(헌법 보호 훅)의 집행 장치 `.claude/hooks/guard_constitution.py` 가 이미 있다.
- 래칫 기준선은 `python scripts/constitution/audit_ratchet.py --update-baseline` 으로 새 단계·0건으로 옮긴다(새 차단이 없을 때만 허용된다).

## 판단을 Kiki에게 남긴 것 (정정안에 넣지 않았다)

정본이 두 곳 이상인 데이터 종류 3건 — 등록부에 추가할지 결정이 필요하다:
① 규칙 등록부(CLAUDE.md 원문 · `backlog/rules.ndjson` · `docs/standards/rule_index.md` · `constitution/rules.yaml`)
② LLM 모델 핀(`l3/router.py` · `config.py` · CLAUDE.md 스택 표)
③ 단원·소단원 위계(원자 백본 단원 217·소단원 643 · 성취수준 코퍼스 · `units_v1` · 교과서 단원)

## 근거

- 표준북 4장(단일 진실 원천) · 헌법 제7조 · 규칙 R4-01
- 대조 문서 `docs/reviews/coding_constitution_crosswalk_2026-09-27.md` §2
