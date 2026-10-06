# 개정 기록 A0005 — 파트 I 집행 장치 정합 정정 + R4-02 결정 (초안)

- 상태: **초안 — 채택 전** (헌법 제11조: 개정은 사람만 한다. 이 문서는 AI가 작성한 초안이다)
- 일자: 2026-10-06 (초안 작성) · 채택일: ____ (Kiki 기입)
- 개정자: Kiki (서명란: ____)
- 선행: A0003·A0002 채택 완료. **A0004 초안(원본 등록부 3건 추가)과는 독립**이다 — 번호는 초안 작성 순서일 뿐 적용 순서는 무관하다(둘 다 `rules.yaml` 의 서로 다른 줄을 건드린다).
- 대상: `constitution/rules.yaml` — 머리말 필드 설명 3줄 추가 · R4-03 경로 정정 · R2-04 단계·실행 명령 정정 (규칙 문장·id·level 은 불변)
- 정정 패치: `docs/constitution_proposals/rules_A0005_part1_corrections.patch` (`patch -p1 --dry-run` 으로 현재 main 의 `rules.yaml` 에 깨끗이 적용됨을 확인)
- 태스크·게이트: `CONST-03` · `G-const-a0005-part1-corrections`(정정 채택) · `G-const-r4-02-decision`(R4-02 3택) · `G-const-protection-outside-claude`(⑦)

## 사유 — 왜 정정이 필요한가

`rules.yaml` 머리말은 "check·run의 경로는 **제안 경로**다. 실제 저장소 구조에 맞게 사람이 조정한다"고 선언한다. 3단계 집행 장치(CONST-03 P2·P3)를 실제로 착지시키자 파트 I(0~4장) 규칙 중 다음 어긋남이 드러났다.

| 규칙 | 현재 등록 | 실제 착지 | 정정 |
|---|---|---|---|
| R4-03 | `tests/test_docs_numbers.py` · `pytest -q tests/test_docs_numbers.py` | `tests/infra/test_docs_numbers.py` (CI infra-contracts 잡이 `tests/infra` 전체를 실행) | check·run 경로 정정 |
| R2-04 | `run: python scripts/constitution/review_health.py` · stage 4 | 판정 논리 테스트 `tests/infra/test_review_health.py`(CI에서 도는 것은 이쪽). 맨몸 `review_health.py` 는 `--events` 가 없으면 **exit 2(측정 불가)** 라 단계 4 에서 그대로 '실행 실패'로 판정된다 | run 을 논리 테스트로, stage 4→3 (대조표 권고와 일치) |
| 머리말 | `timeout_sec`·`cwd`·`shell` 설명 없음 | `audit.py` 가 이미 읽는 선택 필드(CONST-03 P1) | 필드 설명 3줄 추가 |

R2-04 정정의 **한계(정직)**: 단계 3 에서 CI 가 검증하는 것은 '도장 찍기 경보의 *판정 논리*'이지 실제 검토 데이터가 아니다. 실제 검토 이벤트(JSONL)는 Kiki 머신에만 있으므로, 실데이터 판정은 `python scripts/constitution/review_health.py --events <경로>` 를 머신에서 직접 돌려 한다(L4 — 경고). 이 구분을 규칙 `statement` 에 넣을지는 Kiki 판단이다(패치는 `statement` 를 건드리지 않는다).

## 모의 실측 (정정 적용 사본에서 `audit.py --stage 3`)

| 항목 | 현재 main | 패치 적용 사본 |
|---|---|---|
| R4-03 | 📭 집행 장치 없음(필요: `tests/test_docs_numbers.py`) | ✅ 통과 — `infra-contracts` 잡의 `tests/infra` 실행이 대상 파일을 포함 |
| R2-04 | ⏳ 예정(4단계에서 도입) | ✅ 통과(실행 포함 모드) |
| 단계 3 차단 사유 | 47건 | **46건** (파트 I 에서 남는 것은 R4-02 한 건) |
| 46건의 장(chapter) 분포 | — | 4장 1건(R4-02) · 5~29장 45건(파트 II~VII = CONST-04~08 의 몫) |

⇒ **파트 I 은 R4-02 한 건만 남기고 단계 3 준비가 끝난다.** 그러나 `STAGE` 파일은 전역이다 — 지금 3 으로 올리면 파트 II~VII 의 단계 3 규칙 45건이 한꺼번에 판정돼 CI 래칫(`audit_ratchet.py`)이 red 가 된다. **STAGE 3 상향은 CONST-04~08 착지 뒤에 판단한다**(이 개정이 STAGE 를 바꾸지 않는 이유).

## R4-02 — 결정이 필요하다 (이번 패치에 포함하지 않음)

규칙: "Python·Dart 데이터 모델은 `schemas/` 의 JSON Schema에서 자동 생성되며, 재생성 결과가 커밋된 것과 같아야 한다."

**실측으로 확인한 전제 불일치**
- `schemas/v1.1/*.yaml` 은 JSON Schema 가 아니다 — `properties` 가 아니라 `fields:` 구조를 쓴다.
- `schemas/v1.1/problem.schema.yaml` 머리말이 스스로 "**구본 명세(비정본)** — 구현 정본은 `src/backend/whymath_backend/schema/problem.py` · 본 파일은 미구현이며 필드 체계가 상이하다"고 적고 있다(2026-07-28 판정).
- Python 모델은 손으로 쓴 Pydantic 이다(예: `Problem` 83필드). 생성기(`datamodel-codegen` 등)·`scripts/check_generated.sh` 는 저장소에 없다.
- Dart 쪽: CLAUDE.md 7계층 원칙상 학생 클라이언트(L5)는 수학 로직을 갖지 않고 API 로만 소비한다. **모바일 코드가 실제로 어떤 모델을 들고 있는지는 이번에 확인하지 않았다** — A 안의 Dart 확장 시점은 그 실측 뒤에 정한다.

따라서 이 규칙은 **지금 어떤 코드로도 정직하게 통과시킬 수 없다**. 선택지:

| 안 | 내용 | 비용 | 판정 |
|---|---|---|---|
| A (권고) | **방향을 뒤집는다** — Pydantic 모델이 정본이고, `model_json_schema()` 로 JSON Schema 를 내보내 커밋하고 CI 가 '재생성 = 커밋본'을 확인한다. 규칙 문장을 "Python 모델이 정본이며 `schemas/generated/` 의 JSON Schema 는 모델에서 재생성되고 커밋본과 같아야 한다"로 개정 | 소~중(내보내기 스크립트 + 드리프트 테스트 + 구본 yaml 의 위치 정리). Dart 는 모바일이 모델을 직접 소비하게 될 때 추가 | 정본 하나(Pydantic)를 지키는 현행 구조와 맞는다 |
| B | 규칙 그대로 — `schemas/` 를 정본으로 되살리고 생성기를 도입해 Pydantic 을 자동 생성 | 대(83필드 모델 전부를 손 코드에서 생성 코드로 이전 · 불변식(`model_validator`)은 생성기가 표현하지 못해 별도 층 필요 · 구본 yaml 은 필드 체계가 달라 재작성) | 현재 정본(손 Pydantic)과 정면 충돌 — 비권고 |
| C | 이 규칙을 이 저장소에서 **철회**하거나 단계 6 으로 이월하고 사유를 개정 기록에 남긴다 | 소 | 규칙이 막으려던 결함(모델·스키마 사본 불일치)이 방치된다 — 단, 현재 사본은 구본 yaml 하나뿐이고 비정본으로 표시돼 있다 |

## 정정하지 않는 것 (의도적)

- 규칙 `statement`·`id`·`level`·`article` — 불변. R2-02·R2-03·R3-01 은 이미 등록 경로(`tests/constitution/…`·`tests/test_idempotency.py`)와 착지가 일치해 정정할 것이 없다.
- `STAGE` — 위 사유로 불변(2).
- R1-01·R1-03 은 CONST-02 착지분이 이미 통과한다.

## 채택 절차 (Kiki)

1. 읽고 고칠 것이 있으면 고친다(이 초안은 AI 작성이다).
2. 패치 적용: 저장소 루트에서 `patch -p1 < docs/constitution_proposals/rules_A0005_part1_corrections.patch` (또는 Kiki 가 `rules.yaml` 을 직접 편집).
3. `constitution/amendments/A0005_*.md` 에 이 문서를 개정 기록으로 둔다(채택일·서명 기입). **기록 없이 `rules.yaml` 만 바꾸면 `check_amendment.py`(R0-02)가 CI 에서 red 로 막는다** — 이 개정이 그 규칙의 첫 실사용이다.
4. R4-02 는 위 3택 중 하나를 정해 게이트 `G-const-r4-02-decision` 에 판정을 남긴다(A 안이면 후속 태스크로 내보내기 스크립트·드리프트 테스트 착지).
