# P3-99 — 원자 개념 오개념 상속 복구 리허설 (2026-11-04)

> **판정 기준: main `e58dfa56`** + 이 PR · 측정 환경 = 클라우드 세션의 로컬 PostgreSQL 16(운영 아님 · P3-97 리허설 DB
> `whymath_p97` · 문항 2,563행) · 스키마 `a8c4e1f7b3d9`
> 태스크: `P3-99` · 런북 `docs/ops/eos194_publish_measure_runbook.md`

## 1. 무엇이 막혀 있었나

발행 게이트의 오개념 서명 상속은 `concept.source_id` ↔ `misconception_catalog.concept_src_id`만 봤다. 원자 백본 개념
2,683행은 `source_id`가 전부 비어 있어서, 힌트가 붙은 노출 문항 979건이 전부 `misconception_signature` 결손이었다.

## 2. 무엇을 바꿨나 (해소 방향 판정 ③)

원자 유래 오개념 적재기(`l1/misconception/atom_catalog.py`)는 이미 `concept_src_id`에 원자 `code`를 적는다(설계상
`atom_node.code`와 같은 공간). 그래서 상속 조회 키에 개념 `code`를 더했다(`l3/problem_metadata_evidence.py`).

- 고르지 않은 방향: (나) 원자 행에 `source_id`를 채우기 — 원천 src_id가 원자 백본에 없어서 지어내야 한다. (가) 크로스워크
  경유 — 구 437 개념 기준이라 원자 리프 1:1 오개념보다 거칠다. (다) 문항 저작에 서명 넣기 — 979건 재저작이 필요하다.
- 지킨 원칙: 7계층(l3은 DB만 읽는다·l4 import 없음) · 오개념 유발 슬롯 문항은 여전히 문항 자체 서명이 필요하다
  (Kiki 결정 2026-10-14) · 상속 출처는 `misconception_source`에 남는다.
- 알려진 한계: 원자 유래 오개념은 원자마다 1건이라 변별력이 낮다(`p3_01_scope_candidates_2026-09-30.md` §2.3). 상속
  인정은 "개념에 등록된 오개념이 있다"는 뜻이지 그 문항이 그 오개념을 겨냥한다는 보증이 아니다.

## 3. 결과

| 단계 | 결과 |
|---|---|
| 원자 오개념 적재(`populate_atom`) | 1,823건 · exit 0 |
| `preflight` | `ATOM_MISCONCEPTION_ROWS=1823` · `SCANNED=979` · `SCAN_TRUNCATED=False` · **`PUBLISHABLE=861`** · `NOT_PUBLISHABLE_REASONS={"misconception_signature": 118}` |
| 남은 118건 | 전부 `p3-slot:misconception_trigger` 문항(같은 DB의 슬롯 태그 수 118과 일치) — 규칙상 정상 거부 |
| `publish` | 판 1개 발행 · 시도 1건 · `LOG_OUTCOME_PINNED=True` · `PROBLEM_POINTER_MATCH=True` · `ATTEMPT_PIN_MATCH=True` · `AFTER_EXPOSED_WITH_POINTER=1` / `AFTER_EXPOSED=2563` · **`EOS194_ACCEPTANCE3_OK=True`** |
| `deprecate` | `UNDO_OK=True` · `POINTER_AFTER_UNDO=None` |

## 4. 운영에서 다를 수 있는 것

- 운영 DB에 원자 유래 오개념 행이 있는지 모른다. `preflight`가 이제 `ATOM_MISCONCEPTION_ROWS`를 출력하고, 0이면 런북
  [C2](백업 후 `populate_atom`)로 적재한다.
- 완료 판정(인수 조건 ④)은 운영 DB의 `PUBLISHABLE ≥ 1`이다 — 이 리허설은 그 근거가 아니다.
