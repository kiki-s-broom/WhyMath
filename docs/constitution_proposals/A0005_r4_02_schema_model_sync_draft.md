# 개정 기록 A0005 — 규칙 R4-02 문구 개정: "자동 생성" → "스키마 YAML ↔ 모델 필드 일치 검사" (초안)

- 상태: **초안 — 채택 전** (헌법 제11조: 개정은 사람만 한다. 이 문서는 AI가 작성한 초안이다)
- 일자: 2026-10-06 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
- 결정 근거: 2026-10-06 Kiki 결정 — R4-02 를 (나)안(규칙 문구 개정)으로 진행
- 대상: `constitution/rules.yaml` 의 규칙 `R4-02` 1건(`statement`·`check`·`run`). 조문·단계·다른 규칙은 불변
- 정정분 파일: `docs/constitution_proposals/rules_R4-02_schema_model_sync.yaml`
- 집행 장치: `tests/constitution/test_schema_model_sync.py` (이미 CI `헌법 집행 테스트` 스텝이 `pytest -q tests/constitution` 으로 돈다)

## 왜 문구를 바꾸나

현 문구는 "Python·Dart 데이터 모델은 `schemas/` 의 JSON Schema 에서 자동 생성되며, 재생성 결과가
커밋된 것과 같아야 한다"이다. 이 저장소의 실제 상태(2026-10-06 실측)는 다르다.

- `schemas/v1.1/*.schema.yaml` 9개는 JSON Schema 가 아니라 **이 저장소의 자체 명세 YAML**(`entity`·`fields`·`required`)이다.
- Python 모델(`src/backend/whymath_backend/schema/*.py` 등)은 **손으로 쓴 Pydantic**이다. 생성기(`datamodel-codegen` 등)도 `scripts/check_generated.sh` 도 없다.
- Dart 모델이 스키마에서 나온다는 증거는 확인하지 못했다("내가 찾은 방법으로는 0건" — 범위 밖).

그래서 현 문구는 어떤 상태에서도 통과할 수 없다. 문구를 현실에 맞추되 **목적(스키마와 모델이
조용히 어긋나지 않게 한다)** 은 지킨다.

## 실측 — 일치 현황 (9개 엔티티)

판정 기준: YAML `fields` 의 이름이 대응 Pydantic 모델의 `model_fields` 에 있는가(YAML 에만 있는 필드 = 어긋남).

| 엔티티 | 대응 모델 | YAML 에만 있는 필드 | 상태 |
|---|---|---|---|
| CurriculumEntry | `schema/curriculum_entry.py` | 0 | 일치 |
| TextbookMapping | `schema/textbook_mapping.py` | 0 | 일치 |
| SolutionPath | `l3/solution_path.py` | 1 (`embedding`) | 어긋남 |
| Concept | `schema/concept.py` | 7 | 어긋남(YAML 이 낡음) |
| ConceptEdge | `schema/concept.py` | 6 | 어긋남(YAML 이 낡음 — 파일 머리 "런타임 드리프트 노트") |
| Problem | `schema/problem.py` | 12 | 어긋남(모델 83필드로 확장) |
| Hint | `l4/hint_content/models.py` | 2 (`created_at`·`generated_by_tier`) | 어긋남 |
| MasteryState | 없음 | — | 대응 모델 미확정 |
| StudentProfile | 없음 | — | 대응 모델 미확정 |

즉 **"전건 일치"를 요구하면 첫날부터 7건이 빨갛다.** 이것이 "생성기를 도입(가)"하지 않고
"문구를 개정(나)"하면서도 **래칫(더 나빠지지 않게)** 으로 시작하는 이유다.

## 개정 문구 (제안)

> **R4-02**: 스키마 명세 YAML(`schemas/`)의 모든 필드는 대응 데이터 모델에 존재해야 한다.
> 어긋남은 등록부에 만료일과 함께 동결하며, 동결 목록은 늘지 않고 줄기만 한다.

- 검사: `tests/constitution/test_schema_model_sync.py`
- 실행: `pytest -q tests/constitution/test_schema_model_sync.py`
- 단계: 3 (불변)

## 검사가 하는 것 / 못 하는 것

하는 것
1. **일치 엔티티**(CurriculumEntry·TextbookMapping): YAML 필드가 모델에서 빠지면 RED.
2. **어긋남 엔티티**: 현재의 "YAML 에만 있는 필드" 집합을 동결한다. 새 어긋남이 생기면 RED(래칫).
   어긋남이 해소됐는데 동결 목록에 남아 있어도 RED(동결이 거짓 유예로 굳지 않게 — 줄어드는 방향만 허용).
3. **만료**: 어긋남·미확정 등록에는 만료일(2026-12-31)이 있다. 지나면 RED — 유예가 만료 없이 굳지 않는다.
4. **스캔 0건은 실패**: YAML 을 하나도 못 찾으면 RED. 등록부에 없는 새 YAML 이 생겨도 RED(귀속 강제).

못 하는 것(정직한 공백)
- **타입·필수 여부·enum 값의 일치는 보지 않는다** — 필드 *이름*만 본다. 다음 단계 후보다.
- **DB 컬럼(SQLAlchemy 모델)과의 일치는 보지 않는다.** Pydantic 모델만 본다.
- **Dart 모델은 보지 않는다.** 규칙 문구에서 "Python·Dart"를 "데이터 모델"로 일반화한 이유다.
- 모델이 YAML 보다 *넓은* 것(모델에만 있는 필드)은 허용한다 — 모델이 확장되는 것이 정상 진화이기 때문이다.

## 판단을 Kiki 에게 남긴 것

1. **Dart 를 문구에서 뺄지** — 이 초안은 뺐다. Dart 모델이 스키마에서 나오는 경로가 확인되면 별도 규칙으로 되살린다.
2. **만료일 2026-12-31** — 12월 검증(G0~G5) 직전에 동결 목록을 재확인하는 시점으로 잡았다. 늦추려면 테스트 상수만 고친다.
3. **어긋남 7건의 처분**(YAML 을 모델에 맞춰 갱신 vs 모델을 YAML 에 맞춰 수정)은 이 개정의 범위가 아니다. 실측상
   `Concept`·`ConceptEdge`·`Problem` 은 모델 쪽이 현행이고 YAML 이 낡았다. 갱신은 별도 태스크로 등재한다.

## 반영 절차 (Kiki)

1. `constitution/rules.yaml` 의 `R4-02` 블록을 `rules_R4-02_schema_model_sync.yaml` 내용으로 바꾼다(`statement`·`check`·`run` 3줄).
2. `python scripts/constitution/audit.py --stage 3` 에서 R4-02 가 통과로 바뀌는지 확인한다.
3. 채택일·서명을 이 문서 머리에 적는다.
