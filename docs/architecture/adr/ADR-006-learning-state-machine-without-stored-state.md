# ADR-006 — 학습 상태 머신: 8상태를 채택하되 상태를 저장하지 않는다

- **상태:** 채택
- **결정일:** 2026-09-16
- **결정 주체:** Kiki(3택 중 "원문 그대로 전면 구현" 선택) · claude 집행
- **판정 기준:** main `0f12e76a`
- **대상:** 계획서 300 §3 「Phase 2의 핵심 상태 머신」 = `docs/ops/phase2_eos_closed_loop_execution_prompts.md` §P-04 · 태스크 `EOS-105`
- **관련:** `backlog/gates.yaml::G-state-machine-deferral-recheck`(판정 3택 중 **②ADR로 채택**) · `MEMORY.md` 2026-09-03·2026-09-16 결정 로그 · `docs/reviews/eos_phase2_plan_300_gap_review_2026-09-03.md` §5-A · `docs/architecture/canonical_entity_model_v1.md` §2-A 13행

---

## 맥락 — 이 ADR이 존재해야 하는 이유

2026-09-03 Kiki 결정이 8상태 학습 상태 머신의 신설을 **보류**했다. 사유는 하나였다:

> 저장소는 상태를 *머신*이 아니라 *이력*으로 모델링한다(`*MasteryHistory` append-only + `attempt_event` 시계열) — 8상태를 세우면 **같은 사실의 두 번째 진실 원천**이 생긴다. 붕괴 연쇄 "유지보수 지옥 ← truth source가 하나가 아님"의 교과서 사례다.

그 보류에는 만료가 못 박혀 있었다(재확인 지점 G4 2026-12-13, 게이트 `G-state-machine-deferral-recheck`, 판정 3택). 게이트의 선택지 ②는 **"ADR로 채택 — `*MasteryHistory`와의 진실 원천 중복 해소안을 ADR에 포함해야 한다"**였다. 이 문서가 그 해소안이다.

2026-09-16, Kiki가 재확인 지점 이전에 보류를 **번복**하고 원문대로의 전면 구현을 지시했다. 번복은 09-03 판정이 틀렸다는 뜻이 아니다 — 그 시점에 그 판정은 옳았다. 바뀐 것은 우선순위이고, **바뀌지 않은 것은 중복 위험이다.** 그러므로 이 ADR은 "위험이 없다"고 말하지 않고 **위험을 어떻게 다루는지**를 말한다.

## 결정

1. **8상태를 채택한다.** `NEW · DIAGNOSING · READY · LEARNING · PRACTICING · ASSESSING · REMEDIATING · ADVANCING`.
2. **허용 전이는 데이터로 선언한다.** `schema/learning_state.py::ALLOWED_TRANSITIONS`(frozenset 17쌍)가 단일 진실 원천이며, 판정 함수는 이 집합만 읽는다. 전이 규칙을 담은 `if`를 코드에 두지 않는다.
3. **미정의 전이는 거부한다.** 표에 없는 `(from, to)`는 `UndefinedTransitionError`다. 기본 상태 폴백·조용한 통과 경로를 만들지 않는다.
4. **상태를 저장하지 않는다 — 전이를 저장한다.** 영속 좌석은 `learning_state_transition`(append-only 원장)이며, **현재 상태는 원장 최신 행의 `to_state`에서 파생**한다. 가변 상태 컬럼을 어떤 테이블에도 만들지 않는다.
5. **정책은 교체 가능한 이음매로 분리한다.** `LearningStatePolicy` Protocol(`decide(state, evidence) -> PolicyDecision`). v1 구현은 if/else 규칙 6종이고, 추정기 교체(BKT→DKT 등) 시 호출부 수정은 0이다.
6. **LLM은 상태를 결정하지 않는다.** LLM은 증거를 *채우는* 쪽과 결정을 *설명으로 번역하는* 쪽에만 관여한다.

## 진실 원천 중복 해소안 (게이트 ②가 요구한 항목)

### 해소 ① — 역할을 겹치지 않게 가른다

| 담는 사실 | 좌석 | 이 머신과의 관계 |
|---|---|---|
| 무슨 일이 있었는가(측정·증거) | `concept_mastery_history` · `skill_mastery_history` · `attempt_event` | **복제하지 않는다.** 전이 원장은 숙달값·정답률·이벤트를 컬럼으로 갖지 않는다 |
| 시점별 종합 학력 사진 | `user_state_snapshot`(writer 0) | **건드리지 않는다.** 컬럼 추가 0 |
| 학생당 1행 현재 학습 좌표 | `learner_state`(EOS-103 · 이 ADR 시점 미머지) | **건드리지 않는다** |
| 학습 국면의 **전이 사건** | `learning_state_transition`(신설) | 이 머신이 소유 |

판단 근거는 "어느 기존 테이블이 이 사실을 담고 있는가"였고, 답은 **없다**였다(어휘 3종 `DIAGNOSING`·`REMEDIATING`·`ADVANCING`의 `src/` 코드 0건 — EOS-105 등재 시 실측). 즉 이 머신이 만드는 것은 기존 사실의 사본이 아니라 **기록된 적 없는 사실**이다: "이 학생은 지금 어느 교육적 국면에 있는가".

### 해소 ② — 현재 상태를 저장하지 않는다

중복의 가장 위험한 형태는 **같은 사실을 두 자리에 쓰는 것**이다. 그래서 현재 상태를 가변 컬럼에 두지 않았다. 원장이 정본이고 현재 상태는 파생값이므로, "현재 상태"라는 사실의 쓰기 지점은 `record_transition` 하나뿐이다.

부수 효과 둘:
- **왜 그 상태인가**가 남는다. UPDATE는 직전 값을 지우지만 append-only는 `(from, to, trigger, rule_id)`를 남긴다.
- **누가 바꿨는가**가 남는다. 가변 컬럼은 어느 경로든 덮어쓸 수 있어 단일 writer 보증이 관습에 의존하지만, append-only는 과거 행을 바꿀 방법 자체가 없다.

### 해소 ③ — 남는 어긋남은 검출 가능하게 만든다

역할을 갈라도 위험이 0이 되지는 않는다. 숙달 증거가 말하는 국면과 원장이 말하는 국면이 어긋날 수 있다(정책이 바뀌었거나, 적재가 누락됐거나). 그래서 `reconcile_state`가 둘을 대조해 **불일치를 보고**한다.

**자동 정정하지 않는다.** 어느 쪽이 옳은지 기계가 알 수 없기 때문이다. 조용히 덮어쓰면 그 순간 대조가 검출기가 아니라 위장이 된다. 이 성질은 뮤테이션 M15(`diverged`를 항상 False로)가 RED를 내며 동결한다.

## 근거 — 무엇을 실측했는가

| 실측 대상 | 사실 | 근거 |
|---|---|---|
| 8상태 어휘의 기존 구현 | `src/`·`schemas/` **코드 0건** | 어휘 3종 전수 grep(EOS-105 등재 실측) |
| `user_state_snapshot` | writer **0** · 학생당 N행 시점 사진 | `db/models/user.py` · 대조표 §4 단위2 |
| `learner_state`(EOS-103) | main에 **테이블 부재** | `git cat-file -e origin/main:src/backend/whymath_backend/db/models/learner_state.py` → 부재 |
| 좌석 귀속 | LearnerState 좌석 **2번째 테이블**로 편입 | `canonical_entity_model_v1.md` §2-A 13행(좌석 합계 42→43) |
| 과목 중립성 | `l2`·`schema`는 Math Adapter baseline **0** 구역 | import-linter "EOS Core → Math Adapter 금지" 계약 |
| GDPR 파기 | `_ERASURE_PLAN` 편입 | `privacy/erasure.py` · 전수 가드 `test_erasure_plan_completeness.py` |

## 채택하지 않은 대안

**A. 보류 유지 + ADR 초안만** — 게이트 판정 3택의 ①에 해당. Kiki가 번복을 선택했으므로 미채택.

**B. 파생 전용 머신(영속 0)** — 상태를 전혀 저장하지 않고 매번 증거에서 계산. 중복 위험은 가장 낮지만 **전이 사건 자체가 기록되지 않는다** — "이 학생이 언제 왜 교정 국면에 들어갔는가"를 사후에 재구성할 수 없고, 정책이 바뀌면 과거 상태가 소급해 바뀐다(감사 불가). 미채택.

**C. `user_state_snapshot`에 상태 컬럼 추가** — 등재 당시 acceptance ⑤가 이것이었다. 착수 후 실측으로 폐기했다: ①그 테이블은 학생당 N행 사진이라 사진마다 상태를 중복 기록하게 된다 ②EOS-103이 같은 좌석에 작업 중이라 머지 충돌 ③가변 컬럼은 위 해소 ②의 이점을 전부 잃는다.

## 한계 — 이 결정이 해결하지 않은 것

1. **기존 학생 전원이 `NEW`라 첫 응답 제출의 평가 진입 전이가 거부된다**(`NEW → ASSESSING`은 표에 없다). 그 쌍을 표에 넣어 거부를 없애는 선택을 **하지 않았다** — "무엇 대비 평가인가"가 없는 평가를 합법화하면 머신이 보증하는 것이 사라진다. 거부는 응답 `learning_state.rejected_transition`에 값으로 실리고, **응답 적재·숙달 전파는 그대로 성공한다**. 상태 머신이 학습 루프를 *게이팅*하는 것은 이 ADR의 범위 밖이며, 그 결정에는 온보딩 전이(진단 시작)를 누가 언제 적재하는가가 선결이다.
2. **규칙 R4(선수결손)는 서빙 경로에서 매치되지 않는다** — 생산자(`recommend_prerequisite_gaps`)가 개념 그래프 재귀 CTE 순회라 제출마다 돌리기에 무겁다. `build_attempt_evidence`가 인자로 받도록 열어 두었으므로 배치·비동기 경로가 넣어 주면 정책 코드 0줄 수정으로 작동한다.
3. **`record_transition`의 읽기-적재 사이 TOCTOU 창**이 남는다. append-only라 과거를 훼손하지 않으며 어긋남은 `reconcile_state`가 검출한다.

## 재검토 조건

다음 중 하나가 실측되면 이 ADR을 갱신하거나 새 ADR을 쓴다.

1. `reconcile_state`의 불일치가 **운영 데이터에서 유의미한 비율**로 관측될 때 — 역할 분리가 실패했다는 신호다.
2. 전이표가 **25쌍을 넘어설 때** — 상태 폭발의 전조이며, 그 시점에 상태 수 자체를 재검토한다(붕괴 연쇄 "노드 폭발").
3. 상태 머신이 **학습 루프를 게이팅**해야 한다는 요구가 생길 때 — 한계 ①의 결정이 필요해지는 시점이다.
4. `learner_state`(EOS-103)가 머지된 뒤 **두 테이블의 역할 경계가 실무에서 흐려질 때**.
