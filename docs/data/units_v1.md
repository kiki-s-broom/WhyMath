# 소단원 DSL v1 — 데이터 카드

> **요약**: 소단원(unit) 명세 DSL(`unit/0.1`) 코퍼스. 두 묶음으로 이뤄진다.
> ① **이차함수 최대·최소 파일럿**(2026-07-24) — 공통수학1 `[10공수1-02-06]`을 4목표
> (CONCEPT/PROCEDURE/REPRESENT/MODELING)로 분해한 소단원 1편. 컴파일러 E2E 확인용이다.
> ② **미적분Ⅰ '미분' 대단원 초안**(2026-10-07 · P3-03) — Phase 3 범위 명세
> (`data/corpus/phase3_scope_v1/scope_spec.yaml`)의 핵심 개념 10개(`[12미적Ⅰ-02-01]`~`[12미적Ⅰ-02-10]`)를
> 소단원 10편·학습목표 30개로 분해했다. **초안이며 교수학 사람 검토 전**이다(§4).
> `docs/architecture/01_data_foundation.md` 원칙("모든 데이터셋은 `docs/data/[name].md`에 카드 작성")에
> 대응한다.

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 와이매스 자체 저작 소단원 명세 DSL(YAML) |
| 성취기준 코드 인용 | `[10공수1-02-06]`·`[12미적Ⅰ-02-01]`~`[12미적Ⅰ-02-10]` — NCIC 공공누리 제1유형 사실정보 인용(`data/corpus/standards_v1/standards.json`) |
| 소단원 제목 | 미적분Ⅰ 10편은 성취기준의 NCIC 소영역명(`sub_domain`)을 제목으로 썼다 — 공공 사실정보 |
| 개념 노드 인용 | 원자 백본(`data/corpus/atom_graph_v1/graph.json`) code — 32개 전부 실측 확인 |
| 저작(목표 서술) | 와이매스 자체 저작(학습목표 서술은 성취기준 유래 자체 분해 — 검정교과서·평가원·EBS 본문·학습목표 텍스트 미포함) |
| 산출물 | `data/corpus/units_v1/` — `quadratic_maxmin.unit.yaml`, `calc1_diff_01…10_*.unit.yaml`, `_provenance.json` (**커밋됨**) |
| 컴파일러 | `soraw-dsl/0.1`(`src/backend/whymath_backend/l1/pedagogy/unit_compiler.py`) — 11편 전부 드라이런 exit 0 |

---

## 2. 스키마 (DSL → 모델)

| DSL 필드 | 모델(`db/models/pedagogy_dsl.py`) | 비고 |
|---|---|---|
| `unit_id`, `unit_version` | `UnitSpec` 복합 PK | 버전 보존(비교 연산은 없음 — `curriculum_module_gap_review.md` §4-①) |
| `standard_codes[]`, `concept_nodes[]` | `UnitSpec.standard_codes[]`·`concept_nodes[]` | 성취기준·원자 백본 느슨참조 |
| `objectives[].suffix/statement/standard_code/source_verb/k_type/k_type_secondary/concept_nodes` | `LearningObjective` | `id` = `{unit_id}:{suffix}`(컴파일러 `compile_unit` 실측 — 종전 카드의 `{unit_id}:{unit_version}:{suffix}` 표기는 코드와 달라 2026-10-07 정정) |

## 3. 규모와 분해 규칙 (실측)

`_provenance.json`: `{"units": 11, "objectives": 34}` — 성취기준 895건 중 **11건**이 이 DSL로 분해됐다.

| 묶음 | 소단원 | 목표 | k_type 분포 |
|---|---|---|---|
| 이차함수 파일럿 | 1 | 4 | CONCEPT 1 · PROCEDURE 1 · REPRESENT 1 · MODELING 1 |
| 미적분Ⅰ 미분 초안 | 10 | 30 | CONCEPT 9 · PROCEDURE 10 · REPRESENT 10 · MODELING 1 |

### 3.1 미적분Ⅰ 초안의 분해 규칙

- **소단원 단위 = 성취기준 1개.** 스키마가 "한 파일 = 소단원 1개"이고, 파일럿도 원자 백본의 소단원
  `공수1-U2-S3`(이차함수 — `[10공수1-02-05]`·`[10공수1-02-06]` 두 성취기준)을 통째로 담지 않고 성취기준
  하나만 담았다. 같은 입도를 따라 10편으로 나눴다. 원자 백본의 소단원(`미적1-U2-S1`~`S8`, 8개 — `S3`
  도함수와 `S8` 미분의 활용이 성취기준 2개씩)으로 묶는 대안도 있으나, 단원 위계의 정본은 아직 선언되지
  않았다(`CONST-11` 대기).
- **목표 = 원자 1개.** 원자 백본은 미분 대단원의 성취기준마다 원자 3개를 개념/절차/표상으로 나눠 두었다.
  이를 그대로 CONCEPT/PROCEDURE/REPRESENT 목표로 옮겼다. 목표의 k_type은 원자 라벨을 기계적으로 옮긴 것이
  아니라, 그 원자의 오개념이 교수 팩의 전략과 맞는지를 목표마다 주석으로 적었다(예: 반례로 경계를 시험하는
  오개념 → CONCEPT 팩의 COUNTEREXAMPLE_GEN).
- **MODELING은 실생활 맥락이 있는 성취기준에만.** `[12미적Ⅰ-02-10]`("유용성 인식")에만 MODELING 목표를 1개
  더했다. `[12미적Ⅰ-02-09]`의 "문제를 해결"은 수학 내부 문제라 MODELING으로 두지 않았다. MODELING 팩은
  stub이므로 이 목표 하나로는 Phase 3 계측기의 교수 경로 연결(pedagogy)로 세지 않는다 — 그 개념의 연결은
  같은 소단원의 CONCEPT/PROCEDURE/REPRESENT 목표가 만든다. 연결을 위해 k_type을 바꾸지 않았다.
- **부 유형은 1곳만.** `[12미적Ⅰ-02-02]` OBJ-01(미분가능 ⇒ 연속, 역은 거짓)에만 `k_type_secondary: PROOF`를
  기록했다 — 앞 절반이 정당화(논증)이기 때문이다. 기록만이며 계측에 쓰이지 않는다.
- **의도적 제외 1건.** 원자 `12미적Ⅰ-02-08-2`(이계도함수와 볼록)는 목표로 두지 않았다. 이계도함수와
  오목·볼록은 미적분Ⅱ `[12미적Ⅱ-02-09]`(원자 `12미적Ⅱ-02-09-1` "함수의 그래프 개형(2차 도함수)") 소관으로
  보인다. 그래서 `[12미적Ⅰ-02-08]` 소단원에는 CONCEPT 목표가 없다(원자 백본은 고치지 않았다).
- **오개념 id는 비워 뒀다.** `misconception_ids`는 파일럿처럼 미지정이다 — 오개념은 초기 컨텍스트에
  미리 싣지 않고 반응형으로 가져온다는 원칙(CLAUDE.md 구조 붕괴 금기)과 컴파일러 v0.1의 미채움 방침을 따랐다.

### 3.2 Phase 3 계측기에 준 효과

`python -m whymath_backend.l1.standards.phase3_coverage --json`(2026-10-07 실측):

| 수치 | 전 | 후 |
|---|---|---|
| Concept Completeness 연결 `pedagogy` linked | 0/10 | 10/10 |
| Graph Connectivity Coverage | 0/10 | 3/10 |
| 측정 가능한 연결만 본 완전 비율(보조) | 0/10 | 2/10 |

계측기의 exit code는 1 그대로다 — Content Coverage(3/10)와 Concept Completeness(힌트 좌석 부재로 측정 불가)
목표가 남아 있다.

## 4. 사람 검토가 필요한 지점 (초안의 한계)

1. **k_type 1:1 매핑 자체.** 원자 백본의 개념/절차/표상 라벨은 AI 추정(`crosswalk` `review_status: ai_estimated`)
   위에 있다. 목표마다 주석을 달았지만 라벨이 틀리면 목표도 같이 틀린다.
2. **`source_verb`가 k_type을 확정하지 못하는 목표 6개.** 검수 기계(`l3/pedagogy/review.py::_VERB_KTYPE`)는
   이해한다→CONCEPT·구한다→PROCEDURE·해석한다→REPRESENT만 확정한다. 성취기준 서술어를 살려 `설명한다`
   (02-02·02-06·02-07 OBJ-01), `판정한다`(02-02·02-07 OBJ-02), `그린다`(02-08 OBJ-01)를 쓴 목표는 그 기계로는
   `k_type_verified`가 켜지지 않는다. 동사를 표에 맞추려 바꾸지 않았다 — 사람이 확정할 몫이다. (MODELING
   목표 02-10 OBJ-04의 `해결한다`는 그 표가 설계상 제외하는 유형이라 별도다 — 파일럿 OBJ-04와 같다.)
3. **원자 `12미적Ⅰ-02-08-2`의 교육과정 귀속.** 미적분Ⅰ 원자로 둔 것이 맞는지(§3.1 제외 근거) 확인이 필요하다.
   원자 `12미적Ⅰ-02-08-1`의 오개념 서술에도 "변곡점"이 들어 있다.
4. **'활용' 축의 분리 여부.** `[12미적Ⅰ-02-02]`·`[12미적Ⅰ-02-06]`의 "활용할 수 있다"를 별도 목표로 나누지 않고
   절차 목표에 흡수했다.
5. **문항 형태와의 관계.** `[12미적Ⅰ-02-08]`(파생 판정형만 — G-p318·G-p321)과 `[12미적Ⅰ-02-09]`(매개변수 범위형
   보류 — P3-20)의 문항 제약은 목표 문장이 아니라 문항 저작 쪽에서 집행된다. 목표 문장은 "학생이 무엇을 할 수
   있어야 하는가"만 적는다.

## 5. 커버리지 확대 계획

확대 파이프라인(자동 생성 여부·순서)은 `docs/architecture/curriculum_module_gap_review.md` §3 D2
(`CUR-02-objective-coverage-observability`)·§4-⑤·§5-⑥에서 다룬다. 미적분Ⅰ 초안은 P3-03(Phase 3 Coverage
채우기)의 산출물이며, 이 카드는 그 데이터의 스냅샷 기록이다.
