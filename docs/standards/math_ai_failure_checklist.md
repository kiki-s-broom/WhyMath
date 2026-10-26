# 수학 AI 오류 방어 체크리스트 (Math AI Failure Defense Checklist)

> **목적**: 외부 "AI 수학 오류 사례집"(그럴듯한 오답 taxonomy)을 WhyMath의 현 방어 인프라와
> 대조해, 영역별 **완수 여부**를 근거(파일·함수)와 함께 기록한다. 단순 benchmark가 아니라
> "어떤 오류가·왜·어떤 조건에서 재발하고·어떻게 탐지/방지하는가"를 구조화한다.
>
> **범례**: ✅ 완수(작동 코드+테스트) · 🟡 부분(일부만·탐지만·미가동) · ⬜ 미완(설계/문서만 또는 부재)
>
> **최종 갱신**: 2026-07-07 · 조사 기준 커밋: main(#451 병합 전후)

---

## 0. 방어의 심장 (한 줄)

> **결정론 SymPy 검증 3종 + 판정 combiner** — 모두 순수·DB 0·모델 무관. "정답 생성과 검증 분리"
> (설계 원칙 2)를 코드로 강제하고, 판정 불가는 *단정하지 않고 격리*한다(보상 해킹·환각 차단).

| 모듈 | 역할 |
|---|---|
| `l3/symbolic_equivalence.py::identity_status` | 두 식 항등성 단일 권위(SymPy). 정의역 의존식은 `undecidable` |
| `l3/verify_answer.py::verify_answer` | 답 대입 잔차 + 고정시드 샘플링 + 경계값. 등식·부등식·연립·근 선택 |
| `l3/verify_step.py::verify_step` | 단계 변형 동치 3상태(correct/incorrect/unverifiable) |
| `l3/verify_solution.py` + `whs/verdict.py::final_verdict` | 단계 연쇄 + **최종 통과 = Tier1 pass AND 전 단계 correct(unverifiable 0)** |

---

## Part A — 사례집 23개 범주 × 방어 완수

| # | 오류 범주 | 완수 | 방어 위치 / 근거 | 갭·비고 |
|---|---|:---:|---|---|
| 1 | 산술 계산 오류 | 🟡 | `verify_answer.py`(evalf 잔차+샘플링)·`verify_step`(SymPy) | deterministic 검산은 있음. **PRM 점수·self-consistency voting 미구현** |
| 2 | 부호·괄호 분배 | ✅ | catalog `distribution-over-power`(regex+SymPy `canonical_wrong_form`)·`sign-flip-in-inequality`·`factor-sign-flip`·`translation-sign-flip` + `verify_step` | 오개념 탐지 + 기호 검증 이중 |
| 3 | 약분 (a+b)/a≠b | ✅ | catalog `fraction-cancellation`(regex_signals) | |
| 4 | 정의역 무시 (√(x²)=\|x\|·분모0) | 🟡 | catalog `square-root-positivity`·`division-by-zero`; `symbolic_equivalence`가 정의역 의존식을 `undecidable`로 보수 처리; `verify_answer` 특이점 샘플 스킵 | **전용 domain/branch 핸들러 없음** — undecidable 격리로만 안전 |
| 5 | 조건 누락 증명 (b≠0,d≠0) | ⬜ | — | proof 조건 추적 **부재** |
| 6 | 허위 증명·없는 정리 인용 | ⬜ | Lean Tier3 로드맵(03b §4·§9 S5)만 | 정리 DB·증명 검증기 **전무** |
| 7 | 순환 논증 | ⬜ | — | proof state circularity 추적 **부재** |
| 8 | 변수 스코프·quantifier(∀∃) | ⬜ | — | 코드·문서 0건 |
| 9 | 기하학적 환각 | ⬜ | `verify_step`이 기하를 `unverifiable`로 회피; catalog 기하 4종(substring) | 기하 검증기 **부재**(AlphaGeometry 인용만) |
| 10 | 좌표계 혼동 | ⬜ | — | 부재 |
| 11 | 단위·dimensional consistency | ⬜ | — | 차원 분석 **전무** |
| 12 | 무한/극한 오인(one-sided) | 🟡 | catalog `limit-equals-function-value`·`geometric-series-always-converges`·`term-to-zero-implies-convergence` | 오개념 탐지만·**극한 엔진 없음** |
| 13 | 확률 독립성·조건부확률 | 🟡 | catalog `gambler-fallacy`·`prosecutor-fallacy`·`mutually-exclusive-implies-independent` | substring 탐지만·검증기 없음 |
| 14 | 통계 인과/상관 혼동 | 🟡 | catalog `mean-vs-median`; 코퍼스 '자료와 가능성' 41종 | 인과/상관 전용 미미 |
| 15 | 미분 규칙 오적용 ((fg)'=f'g') | ✅ | catalog `product-rule-naive`·`chain-rule-inner-derivative-omitted`(regex+correct_form) | |
| 16 | 적분 상수 누락(+C) | ⬜ | `catalog.py:428` **의도적 배제** 주석 | omission형은 substring이 "오류 부재"를 못 잡음 → 임베딩 후속 |
| 17 | 분모0 허용 | 🟡 | catalog `division-by-zero`; `verify_answer` 특이점 스킵 | 위반을 *단정*하진 않음 |
| 18 | 반례 탐색 실패 | ✅ | `verify_answer` 고정시드 샘플링=수치 반례 탐색(위반 1샘플→fail); catalog 전 항목 `counterexample` 보유 | |
| 19 | 귀납법 구조 붕괴 | ⬜ | — | 부재 |
| 20 | 존재 vs 구성 혼동 | ⬜ | — | 부재 |
| 21 | 그래프 해석 환각 | 🟡 | `l3/visualization.py`·`viz_eval.py`(05b) | 그래프 *해석 검증기*는 아님 |
| 22 | 시각적 근사 오판 | ⬜ | — | 부재 |
| 23 | 교육적 위험(오답 승인·확신 오답·오개념 강화) | ✅ | CLAUDE.md 금기 L110-112; `verdict.py` unverified 격리; judge never-break→`불확실`; `calibration_coaching.py` 과신 코칭; 소크라테스 비난 없는 톤; 04a verify_step 의무 호출 | **가장 강함** |

**집계**: ✅ 완수 6 · 🟡 부분 7 · ⬜ 미완 10 (23범주 중).

---

## Part B — 방지 전략 5레이어 완수

| 레이어 | 완수 | 상태 | 근거 |
|---|:---:|---|---|
| **L1 Symbolic Engine** | 🟡 | SymPy 완비·외부 프로버 미연동 | `symbolic_equivalence`·`verify_*` 4모듈. Wolfram/Lean/Coq 미연동(Lean Tier3 로드맵) |
| **L2 Proof Verification** | ⬜ | step verifier만·PRM/정리증명 미구현 | `verify_step`/`verify_solution` 실동작 = 실질 Tier2. **PRM은 프롬프트+export 도구만**(`whs/prm_builder*.py`는 학습셋 export). 정리 증명 검증 없음 |
| **L3 Multi-agent Validation** | 🟡 | 하네스 골격+결정론 검증기 실동작·LLM 에이전트 미가동 | `whs/harness.py`·`harness/wh1_*.py`·`agreement_gate.py`. solver/critic LLM 정책(Ollama·Phaiakes9)은 주입만 |
| **L4 Misconception DB** | ✅ | **가장 성숙** | 코드 카탈로그 32종(`catalog.py`) + 코퍼스 <!-- fact:misconceptions.count -->843<!-- /fact -->종 + 탐지(substring·pgvector·LLM-judge)·distractor 역추적 |
| **L5 Confidence Calibration** | 🟡 | 학생 보정 있음·AI 자기 불확실성은 3상태 격리로만 | `calibration_coaching.py`(학생 과신). AI 측은 `unverifiable`→`unverified` 격리 + "모르면 모른다"(L110-112). **명시적 자연어 "확실하지 않음" 레이어 부재** |

---

## Part C — 사례집이 놓친 것 (WhyMath 맥락 추가 항목)

> 외부 사례집은 *범용 LLM-수학 오류*라, WhyMath의 아키텍처(입력·데이터·인프라·한국 맥락)가
> 반드시 다뤄야 하는 아래 항목을 놓친다. **우리가 별도로 체크해야 할 것.**

| # | 추가 오류 축 | 완수 | 근거·갭 |
|---|---|:---:|---|
| C1 | **입력 오인** — 손글씨 OCR(PaddleOCR+Qwen3-VL) 오독 → 잘못된 문제 파싱 | ⬜ | 사례집은 입력층 무시. OCR 신뢰도·재확인 루프 점검 필요 |
| C2 | **표기 파싱 오독** — `log_b x`를 선형식 `b·x`로 오독(위생 validator) | 🟡 | **2026-07-07 지수·로그 도메인에서 실측**. 우회(해설 재진술 제거)했으나 validator 근본 개선 미완 |
| C3 | **근의 개수 vs 근의 값** — count형 문항을 대입 검증 불가 | 🟡 | `test_corpus_quality`의 `_REVIEW_ONLY_SLUGS`로 정직 격리(자동검증 밖·사람 검수). count 검증기 후속 |
| C4 | **분포 이동(새 단원)** — 검증기·validator가 새 도메인을 안전 커버 못 함 | 🟡 | 지수·로그 추가 시 위생 오독(C2) 발견 = 실증. **새 도메인 추가 시 게이트 전건 재검증이 가드** |
| C5 | **비다항 dedup 회피** — canonical signature=None → 구조 dedup 스킵 | ✅ | 오케스트레이터 1급 지원(비다항→임베딩 위임). 풀 결정론 유일이라 안전 |
| C6 | **반올림/무한소수 오염** — 근사값을 정답으로 | ✅ | 스켈레톤은 정확값(Fraction·sqrt·sstr)만·`verify_answer`가 exact 강제 |
| C7 | **커리큘럼/성취기준 오정렬** — 문제를 잘못된 학년·단원에 태깅 | 🟡 | 성취기준 코드 태깅 있음. 자동 정렬 검증기는 부분 |
| C8 | **표현≠의미 위반** — AST 아닌 화면 문자열로 코어 저장 | 🟡 | 문항 스키마·conditions는 구조 저장. 렌더 일관성 전수 가드는 부분 |
| C9 | **LLM 라우팅/캐싱 오염** — 잘못된 캐시 히트로 다른 문제에 다른 답 | ⬜ | 캐시 키 3축 설계는 있으나(interfaces) 생성기 경로 미배선 |
| C10 | **저작권 오염** — 기출·교과서 본문 복제 | ✅ | S2-a 저작권 게이트·`source_type=자체생성`·`policy-guard` CI |
| C11 | **미성년자 안전·정서 강화** — 부정 피드백 강화 | ✅ | CLAUDE.md 금기·소크라테스 톤·범주 23과 정합 |
| C12 | **prompt injection/adversarial** — 학생이 프롬프트로 답 유도 | ⬜ | 전용 방어 미확인 |
| C13 | **스키마↔DB 폭 불일치** — pydantic max_length 부재로 실 PG 오버플로 | ✅ | **2026-07-06 실측·수정** + `TestCorpusFitsOrmColumns` hermetic 가드 |

---

## Part D — 갭 우선순위 권고

의사결정 우선순위(CLAUDE.md §의사결정: 안전>준법>교수학정확성>학습효과)에 따라 정렬:

### P0 — 안전·정확성 직결 (그럴듯한 오답이 학생 노출되는 경로)
1. **표기 파싱 validator 근본 개선(C2)** — `log_b x`·기타 함수 표기 오독. 새 도메인마다 재발. 위생 validator의 토큰화를 함수-인식형으로. *현재는 우회+게이트로 격리*.
2. **정의역/branch 핸들러(범주 4·17)** — √(x²)=\|x\|·분모0을 *단정 검증*(현재 undecidable 격리만). 고급 수학 확장의 전제.
3. **Confidence calibration 자연어 레이어(L5)** — AI 발화에 명시적 "확실하지 않음". 현재 3상태 격리는 내부용, 학생 노출 표현 부재.

### P1 — 확장 트랙 (도메인 커버리지)
4. **극한·확률·통계 검증기(범주 12·13·14)** — 오개념 탐지만 있고 수치/기호 검증기 없음. SymPy `limit`·확률 계산 결선.
5. **PRM 점수 산출(L2)** — export 도구·프롬프트는 준비됨. 실제 단계 보상 모델 학습·서빙.
6. **적분 상수 누락(+C, 16)** — omission형. 임베딩/구조 비교로 "빠진 항" 탐지.

### P2 — 장기 트랙 (형식 증명·기하)
7. **Proof verification(범주 5·6·7·19·20)** — Lean4 Tier3. 조건 누락·순환·허위 정리·귀납·존재vs구성. 자동형식화 난제라 로드맵 S5.
8. **Geometry 검증(범주 9·10·22)** — 도형 환각·좌표계·시각 근사. AlphaGeometry류.
9. **단위·차원 분석(범주 11)** — dimensional consistency 엔진(물리·활용 문항).

### 상시 가드 (이미 작동·유지)
- **새 도메인 추가 시 S2-a 게이트 전건 재검증**(C4) — 지수·로그에서 C2를 잡은 실증 메커니즘.
- **결정론 검증 3종 + unverified 격리**(범주 23) — 확신 오답·보상 해킹의 1차 방어벽.
- **스키마↔DB·저작권·미성년자 CI 가드**(C10·C11·C13).

---

## 부록 — 이 체크리스트의 확장 경로

사례집이 제안한 확장(Failure Ontology·Hallucination Taxonomy·오개념↔AI오류 매핑 DB·검증 DSL)과
WhyMath 자산의 접점:
- **오개념↔AI오류 매핑 DB**: 이미 `l4/misconception/`(32+<!-- fact:misconceptions.count -->843<!-- /fact -->) + `distractor.py` 역추적이 골격.
  AI 오류 사례를 오개념 id로 태깅하면 학생/AI 오류 통합 그래프가 된다.
- **검증 DSL**: `canonicalize.condition_dsl_violation`(닫힌 DSL)이 씨앗. 함수-인식 확장(C2)이 다음.
- **Failure Ontology**: 본 Part A/C가 v0 온톨로지. 각 범주에 재현 조건·탐지기·상태를 필드화하면 JSON 스키마로 승격 가능.
