# 개정 기록 A0005 — 파트 I 집행 장치 정합 정정 + R4-02 결정 (초안)

- 상태: **초안 — 채택 전** (헌법 제11조: 개정은 사람만 한다. 이 문서는 AI가 작성한 초안이다)
- 일자: 2026-10-06 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
- 선행: A0003·A0002 채택 완료. **A0004 초안(원본 등록부 3건 추가)과는 독립**이다 — 번호는 초안 작성 순서일 뿐 적용 순서는 무관하다(둘 다 `rules.yaml` 의 서로 다른 줄을 건드린다).
- 대상: `constitution/rules.yaml` — 머리말 필드 설명 3줄 추가 · R4-03 경로 정정 · R2-04 단계·실행 명령 정정 · **R4-02 문구·검사 정정(Kiki 결정 (나)안)** (id·level·stage 는 불변 — R4-02·R2-04 는 문장 또는 단계가 바뀐다)
- **합본 고지(2026-10-06)**: 병렬 세션이 같은 번호로 만든 R4-02 초안(PR 1493 의 `A0005_r4_02_schema_model_sync_draft.md`·`rules_R4-02_schema_model_sync.yaml`)을 이 개정 하나로 합쳤다 — 개정 번호는 하나씩만 쓸 수 있고, 두 초안은 `rules.yaml` 의 서로 다른 줄을 고치므로 한 번에 적용된다. 집행 테스트 `tests/constitution/test_schema_model_sync.py` 는 PR 1493 이 가져온다(이 개정은 그 파일이 main 에 있다고 전제한다).
- 정정 패치: `docs/constitution_proposals/rules_A0005_part1_corrections.patch` (`patch -p1 --dry-run` 으로 현재 main 의 `rules.yaml` 에 깨끗이 적용됨을 확인)
- 태스크·게이트: `CONST-03` · `G-const-a0005-part1-corrections`(정정 채택) · `G-const-r4-02-decision`(R4-02 3택) · `G-const-protection-outside-claude`(⑦)

## 사유 — 왜 정정이 필요한가

`rules.yaml` 머리말은 "check·run의 경로는 **제안 경로**다. 실제 저장소 구조에 맞게 사람이 조정한다"고 선언한다. 3단계 집행 장치(CONST-03 P2·P3)를 실제로 착지시키자 파트 I(0~4장) 규칙 중 다음 어긋남이 드러났다.

| 규칙 | 현재 등록 | 실제 착지 | 정정 |
|---|---|---|---|
| R4-03 | `tests/test_docs_numbers.py` · `pytest -q tests/test_docs_numbers.py` | `tests/infra/test_docs_numbers.py` (CI infra-contracts 잡이 `tests/infra` 전체를 실행) | check·run 경로 정정 |
| R2-04 | `run: python scripts/constitution/review_health.py` · stage 4 | 판정 논리 테스트 `tests/infra/test_review_health.py`(CI에서 도는 것은 이쪽). 맨몸 `review_health.py` 는 `--events` 가 없으면 **exit 2(측정 불가)** 라 단계 4 에서 그대로 '실행 실패'로 판정된다 | run 을 논리 테스트로, stage 4→3 (대조표 권고와 일치) |
| 머리말 | `timeout_sec`·`cwd`·`shell` 설명 없음 | `audit.py` 가 이미 읽는 선택 필드(CONST-03 P1) | 필드 설명 3줄 추가 |
| R4-02 | `statement`: Python·Dart 모델이 `schemas/` JSON Schema 에서 자동 생성 · `scripts/check_generated.sh` | 전제 불일치(아래 절) — Kiki 가 (나)안(문구 개정)으로 결정 | `statement`·`check`·`run` 3줄을 '스키마 YAML ↔ 모델 필드 일치 검사'로 교체 |

R2-04 정정의 **한계(정직)**: 단계 3 에서 CI 가 검증하는 것은 '도장 찍기 경보의 *판정 논리*'이지 실제 검토 데이터가 아니다. 실제 검토 이벤트(JSONL)는 Kiki 머신에만 있으므로, 실데이터 판정은 `python scripts/constitution/review_health.py --events <경로>` 를 머신에서 직접 돌려 한다(L4 — 경고). 이 구분을 규칙 `statement` 에 넣을지는 Kiki 판단이다(패치는 `statement` 를 건드리지 않는다).

## 모의 실측 (정정 적용 사본에서 `audit.py --stage 3`)

| 항목 | 현재 main | 패치 적용 사본 |
|---|---|---|
| R4-03 | 📭 집행 장치 없음(필요: `tests/test_docs_numbers.py`) | ✅ 통과 — `infra-contracts` 잡의 `tests/infra` 실행이 대상 파일을 포함 |
| R2-04 | ⏳ 예정(4단계에서 도입) | ✅ 통과(실행 포함 모드) |
| R4-02 | 📭 집행 장치 없음(필요: `scripts/check_generated.sh`) | ✅ 통과(PR 1493 의 테스트를 사본에 둔 실행 포함 모드) |
| 단계 3 차단 사유 | 47건 | **45건** — 사본에 `.git` 이 없어 R0-02 가 '측정 불가'로 나온 1건을 뺀 값(실제 저장소에서는 통과) |
| 45건의 장(chapter) 분포 | — | 전건 5~29장(파트 II~VII = CONST-04~08 의 몫). **파트 I(0~4장)은 전건 통과** |

⇒ **이 패치를 채택하면 파트 I 의 단계 3 준비가 끝난다.** 그러나 `STAGE` 파일은 전역이다 — 지금 3 으로 올리면 파트 II~VII 의 단계 3 규칙 45건이 한꺼번에 판정돼 CI 래칫(`audit_ratchet.py`)이 red 가 된다. **STAGE 3 상향은 CONST-04~08 착지 뒤에 판단한다**(이 개정이 STAGE 를 바꾸지 않는 이유).

## R4-02 — Kiki 결정: (나)안 — 규칙 문구를 '스키마 YAML ↔ 모델 필드 일치 검사'로 개정

원 규칙: "Python·Dart 데이터 모델은 `schemas/` 의 JSON Schema에서 자동 생성되며, 재생성 결과가 커밋된 것과 같아야 한다." 실측으로 확인한 전제 불일치 — `schemas/v1.1/*.yaml` 은 JSON Schema 가 아니라 자체 명세 YAML(`fields:` 구조)이고 머리말이 '구본 명세(비정본)'를 선언하며, Python 모델은 손으로 쓴 Pydantic 이고 생성기·`check_generated.sh` 는 없다. 어떤 상태에서도 통과할 수 없는 문구였다.

**결정**: (가) 생성기 도입 대신 **(나) 문구 개정**. 개정 문구(`statement`): "스키마 명세 YAML(schemas/)의 모든 필드는 대응 데이터 모델에 존재해야 하며, 어긋남은 만료일과 함께 동결하고 늘리지 않는다" · `check`: `tests/constitution/test_schema_model_sync.py` · `run`: `pytest -q tests/constitution/test_schema_model_sync.py` (패치에 포함).

**실측(9개 엔티티, PR 1493)**: 일치 2(CurriculumEntry·TextbookMapping) · 어긋남 5(SolutionPath 1·Hint 2·Concept 7·ConceptEdge 6·Problem 12 — 동결·만료 2026-12-31) · 대응 모델 없음 2(MasteryState·StudentProfile). '전건 일치'를 요구하면 첫날 7건이 빨개져 **래칫(새 어긋남은 막고 줄기만 허용)**으로 시작한다.

**이 선택의 한계(정직)**
- 비교 기준이 '비정본으로 표시된 구본 명세'다 — 정본(손 Pydantic)과 명세 YAML 두 벌이 계속 남고, 이 검사는 둘의 *필드 이름*이 벌어지지 않게만 한다. 타입·필수·enum·DB 컬럼·Dart 는 보지 않는다.
- 어긋남 5건은 대부분 모델이 현행이고 YAML 이 낡았다 — 처분(YAML 갱신 vs 모델 수정)은 이 개정의 범위가 아니라 별도 태스크다. 만료(2026-12-31)가 지나면 CI 가 red 가 되므로 그 전에 처분이 필요하다.
- 처음 검토에서 제가 낸 대안(A: Pydantic 에서 JSON Schema 를 내보내 드리프트 검사)은 정본을 하나로 만드는 쪽이었다. 결정이 (나)로 난 것을 존중하되, YAML 폐기·내보내기 전환은 동결 해소 시점에 다시 검토할 후보로 남긴다.

## 정정하지 않는 것 (의도적)

- 규칙 `statement`·`id`·`level`·`article` — 불변. R2-02·R2-03·R3-01 은 이미 등록 경로(`tests/constitution/…`·`tests/test_idempotency.py`)와 착지가 일치해 정정할 것이 없다.
- `STAGE` — 위 사유로 불변(2).
- R1-01·R1-03 은 CONST-02 착지분이 이미 통과한다.

## 채택 절차 (Kiki)

1. 읽고 고칠 것이 있으면 고친다(이 초안은 AI 작성이다).
2. 패치 적용: 저장소 루트에서 `patch -p1 < docs/constitution_proposals/rules_A0005_part1_corrections.patch` (또는 Kiki 가 `rules.yaml` 을 직접 편집).
3. `constitution/amendments/A0005_*.md` 에 이 문서를 개정 기록으로 둔다(채택일·서명 기입). **기록 없이 `rules.yaml` 만 바꾸면 `check_amendment.py`(R0-02)가 CI 에서 red 로 막는다** — 이 개정이 그 규칙의 첫 실사용이다.
4. R4-02 는 이미 결정됐다((나)안). 채택 후 `python scripts/constitution/audit.py --stage 3` 에서 R4-02 가 통과로 바뀌는지 확인하고, 게이트 `G-const-r4-02-decision` 은 그 결과로 닫는다. 어긋남 5건 처분 태스크를 등재한다.
5. 순서: PR 1493(집행 테스트)이 main 에 있어야 R4-02 가 통과한다 — 먼저 머지하거나, 패치 적용 전에 테스트 파일이 있는지 확인한다.
