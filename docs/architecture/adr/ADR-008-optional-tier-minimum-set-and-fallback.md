# ADR-008 — 과목이 반드시 제공할 선택층 능력 최소집합과 미제공 폴백을 정한다 (12월은 문서만, 코드는 2027)

- **상태:** **Proposed** — 등록 `ARCH-104`(EOS 감리 WP-B). 코드 이행은 2027-01 `ARCH-67`(G5 재확인) 결과를 본 뒤 **별도 ADR**로 한다. 이 ADR 자체는 코드를 바꾸지 않는다.
- **결정일:** 2026-10-23 (등록일 · 판정 기준 main `0523e19e`)
- **대상:** `schema/verification_capabilities.py`(선택층 능력 Protocol 8종) · `schema/subject_adapter.py`(필수층 3메서드, Frozen unexercised) · `composition.py`(`default_*` 팩토리 9개) · `api/_subject_capability_state.py`(`app.state` 등록 7종)
- **관련:** [ADR-004](./ADR-004-subject-contract-v1-provisional.md) · 감리 2026-10-19 W-08·W-17(과목 경계 사고실험 C12) · `EOS-92`(교차 과목 프로브, 물리 ✗0) · `ARCH-67`(필수층 미사용 재점검, G5 12/27) · `docs/architecture/eos_core_adapter_boundary.md` 「능력 수는 이렇게 센다」 · `docs/strategy/subject_pack_spec_v1.md` §0-1

> **번호 계열 주의**: 저장소 계열의 다음 빈 번호다(`adr_number_check.py` — 등록 직전 "문서 7건 · 다음 빈 번호 ADR-008"). 1차 감리(10/18)의 "ADR-001~009" 묶음과 무관하다.

---

## 맥락 (사실만 — 판정 기준 main `0523e19e`, 2026-10-23 재대조)

| 사실 | 근거 |
|---|---|
| 필수층 `SubjectAdapter` 3메서드(`evaluate_answer`·`detect_misconception`·`validate_problem`)는 상태 **Frozen (unexercised)** 이며 Core 호출자 0건이다. 파일 스스로 "필수층이 쓰이지 않는 것은 과도기가 아니라 설계 경로의 결과다"라고 적는다 | `schema/subject_adapter.py:3,97` |
| Core가 실제로 쓰는 과목 계약은 선택층 **능력 Protocol 8종** — `StepChainVerifier`(:173) · `FinalAnswerVerifier`(:215) · `AssessmentAnswerVerifier`(:250) · `ExpressionSeal`(:265) · `AnswerFormVerifier`(:282) · `ExpressionEquivalence`(:298) · `AnswerValueExposure`(:353) · `AttemptMisconceptionDetector`(:390). 결과 형태 Protocol 7개(`StepOutcome` 등)는 능력이 아니라 반환 모양이라 세지 않는다 | `schema/verification_capabilities.py` (AST로 "메서드를 가진 Protocol" 계수, 2026-10-23) |
| 그중 5종이 수식·값 계산을 전제한다 — `ExpressionEquivalence.identity_status(lhs, rhs)`(:298-301 "수학·물리엔 있고 역사엔 없다") · `ExpressionSeal.extract_sealed()`(:273) · `AnswerFormVerifier`(:285 "수학의 `기약분수`는 역사에 없고") · `AssessmentAnswerVerifier` · `AnswerValueExposure`(:356 "역사·국어엔 없다") | 같은 파일 |
| 반대로 `StepChainVerifier`(:176 "제공하지 않는 과목이 정상이다 — 서술형 역사 답안엔 '전이 동치'가 없다")와 `AttemptMisconceptionDetector`(:400 "반드시 있다고 단언할 수 없으므로 — 역사 서술형에 그런 구조가 있는가?")는 **파일 스스로 "모든 과목에 있다고 단언할 수 없다"**고 적었다 | 같은 파일 |
| 능력 미제공 시 동작이 지점마다 다르다 — ① `app.state` 등록 누락 = `AttributeError`(폴백 없는 `getattr`, `api/_subject_capability_state.py:20`) ② 항등 판정 미주입 = 즉시 `LookupError`(`l3/pedagogy/slot_generator.py:78`) ③ 오개념 훑기 미실행 = `MisconceptionScan.NOT_RUN`(`api/_attempt_misconception_scan.py:93`) ④ 값 노출 판정 미주입 = 문자열 `VALUE_NOT_RUN`, 게이트가 **거부**(`l4/hint_content/gates.py:88,149`) ⑤ 단계 연쇄 검증 미주입 = 합성 루트 기본 구현으로 **폴백**(`l4/solution_coaching.py:281-284`(조건문 :281 · import :282 · 호출 :284), 서빙 경로에서는 안 돎·단위테스트 편의) | 각 파일:행 |
| 화학 사고실험(감리 증거 A): 필수층만 구현하면 등록은 되나 채점 경로가 열리지 않는다 | 감리 보고서 2026-10-19 §5 C12 (저장소 밖 문서 — 재현은 위 두 행으로 가능) |
| 능력 수 표기가 5종/7종/8종으로 혼용됐다 — 모두 시점·대상이 다른 수치였고 이 태스크가 한 정의로 정리했다(능력 Protocol 8 · `app.state` 등록 7 · 팩토리 9 · 적합성 증명 8) | `eos_core_adapter_boundary.md` 「능력 수는 이렇게 센다」 |

## 결정

1. **과목 최소집합(제안)**: 모든 과목 Adapter는 선택층 중 **`FinalAnswerVerifier`·`AttemptMisconceptionDetector`·`StepChainVerifier` 3종**을 반드시 제공한다. 나머지 5종(`ExpressionSeal`·`AnswerFormVerifier`·`ExpressionEquivalence`·`AssessmentAnswerVerifier`·`AnswerValueExposure`)은 **수식·값 전제 선택**으로 재분류한다.
   - ⚠ **열린 쟁점(감리 초안과 현재 파일이 어긋나는 곳)**: 위 맥락 4번째 행처럼 `StepChainVerifier`·`AttemptMisconceptionDetector`의 docstring은 "모든 과목에 있다고 단언할 수 없다"고 적었다. 이 둘을 최소집합에 넣으면 **그 docstring 두 개를 함께 고치는 계약 변경**이다. 이 ADR은 Proposed이므로 최소집합의 구성은 확정하지 않고, 이행 ADR에서 ARCH-67 결과와 함께 다시 정한다. 후보 구성은 (가) 위 3종 (나) `FinalAnswerVerifier` 1종만 필수 + 나머지 전부 선택 — 둘 다 이행 ADR이 고른다.
2. **폴백 단일 규약(제안)**: 미제공 능력은 한 가지 신호로 통일한다 — 제안 형식은 `NOT_RUN` 계열 + 사유 문자열 `capability_absent:<능력명>`. 현재 `NOT_RUN`은 열거형(`MisconceptionScan.NOT_RUN`)과 문자열 상수(`VALUE_NOT_RUN`) 두 가지이고 `reason` 필드는 아직 없다 — 이 줄은 **존재하는 필드의 설명이 아니라 이행 ADR이 만들 형식의 제안**이다. `AttributeError`·조용한 건너뜀·합성 루트 폴백은 금지 후보다.
3. **문서 정정(12월 · 등록 PR에서 이미 이행)**: `eos_core_adapter_boundary.md`에 능력 수 정의 표를, `subject_pack_spec_v1.md` §0-1에 "엔진 0줄"의 성립 범위를 넣었다. "필수층 = 등록 계약, 선택층 최소집합 = 동작 계약"이라는 구분은 이 ADR이 처음 명문화한다.
4. **코드 변경은 하지 않는다(12/31까지)**: ADR-004 "계약은 줄어들 수만 있다"와 CI 적색 규칙(필수층 메서드 추가 = 동결 해제), 12/31 내부 검증 기간 방침 2항(필수층 변경 금지)을 존중한다. 2027-01 `ARCH-67` 결과와 함께 이행 ADR을 낸다.

## 대안과 기각 이유

- **필수층을 폐기하고 선택층만 남김**: 기각. ADR-004 동결 위반이고 `EOS-91` 필드 래칫이 깨진다.
- **선택층 8종 전부를 필수로**: 기각. 수식·값 전제 5종을 화학·국어가 구현할 수 없다.
- **12월에 코드까지 이행**: 기각. 가용 약 260h 중 Phase 3 사슬이 대부분이고, G5 동결(12/27) 전 Core 변경은 판정을 흐린다.

## 결과

- 화학 사고실험의 "필수층만으로는 채점 경로가 안 열린다"는 **문서로 해소(맥락·`subject_pack_spec_v1` §0-1), 코드는 2027**로 처분된다. 문항 적재(`Problem.subject` enum)·오개념 상수(`catalog.py`)·`/v1/verify` 직접 호출·슬롯 예시 문구는 2027 이월 후보로 `subject_pack_spec_v1` §0-1 표에 위치가 적혀 있다(12/31 방침 3항: 발견하면 한 줄 기록 후 멈춘다).
- `ARCH-67`의 G5 재점검은 이 ADR의 최소집합 후보 기준으로 "제공/미제공" 표를 만든다.

## 중단 규칙

- `ARCH-67`에서 필수층 호출자가 1건 이상 생겼다면 결정 1을 다시 본다(필수층이 살아난 것이므로).
- 최소집합 확정 전에 새 능력 Protocol이 추가되면(이번 `P3-77`처럼) 이 ADR의 맥락 표 능력 수를 먼저 갱신한다 — 표가 낡은 채 결정이 나가면 안 된다.
