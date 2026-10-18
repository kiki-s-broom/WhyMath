# Phase 3 지표 실측 기록 — `phase3_coverage` 6지표 + `phase3_metrics` 7지표 (2026-10-18)

**판정 기준: main `6f668474592a325434468b435f4bc8b60dd714e8`** (2026-10-18 05:15 UTC · PR #1678 P3-49 머지 시점 · `git rev-parse HEAD`와 `origin/main`이 동일함을 확인)
**측정일**: 2026-10-18 07:10 UTC · **성격**: 계측기 2종을 **실제로 실행**한 값의 기록. production code·테스트·명세·코퍼스를 바꾸지 않았다(작업 트리 변경은 이 문서뿐).
**직전 기록**: 2026-10-17 `docs/reviews/p3_g1_week1_gate_rejudgment_2026-10-17.md`(6지표 · main `e35692ef`) · 2026-10-14 `docs/reviews/p3_05_step0_investigation_2026-10-14.md`(7지표 · `--no-db`).

## 0. 왜 이 문서가 있는가 — 인용값 대체의 경위

이 세션의 클론은 처음에 백엔드 패키지가 설치돼 있지 않아(`pydantic_settings` 없음 → `ModuleNotFoundError`) 두 CLI를 실행할 수 없었고, 그 상태에서는 6지표 값을 **10/17 판정문의 인용값으로 대체**할 수밖에 없었다. 인용값은 실측이 아니다 — 판정 기준 커밋이 다르면 값이 달라질 수 있고, 실제로 달라졌다(아래 §3). 그래서 `python -m pip install -e .`(`src/backend` · Python 3.13.16)로 의존성을 채운 뒤 두 CLI를 다시 실행해 이 문서에 **실측값**을 기록한다. 아래 표의 숫자는 전부 CLI stdout에서 옮긴 것이며 사람이 센 값은 없다.

CLAUDE.md 「trunk 부재를 미구현으로 단정 금지」·「미머지 존재를 충족으로 단정 금지」의 같은 축이다 — *실행하지 못한 측정*을 *실행한 측정*처럼 적지 않는다.

## 1. `phase3_coverage` — 6지표 (P3-02 계측기)

명령: `python -m whymath_backend.l1.standards.phase3_coverage` (작업 디렉터리 `src/backend` · 인자 없음 · DB 미접속)
명세: `phase3-scope-v1`(동결 2026-10-02 · 게이트 `G-p301-scope-choice`) · 읽은 문항 행 **14,742건**
**종료 코드: 1** (판정: 미달 — Concept Completeness · Graph Connectivity)

| 지표 | 값 | 목표 | 판정 |
|---|---|---|---|
| Content Coverage Rate | 10/10 = 100.0% | ≥ 95% | 충족 |
| Curriculum Coverage | 10/10 = 100.0% | ≥ 98% | 충족 |
| Concept Completeness | 0/10 = 0.0% | ≥ 95% | 미달 |
| Graph Connectivity Coverage | **4/10 = 40.0%** | ≥ 95% | 미달 |
| 공급 가능 커버리지 | 0/10 = 0.0% | 없음 | 목표 없음 |
| Concept Slot Coverage(6슬롯) | 60/60 = 100.0% | 없음 | 목표 없음 |

보조 수치(종료 코드 불참여):

- **연결별 충족 수**(핵심 개념 10 기준): prerequisite 10 · misconception 10 · solution 10 · pedagogy 10 · **hint 측정 불가 10**(힌트 좌석은 DB `hints.verified`뿐이라 `--hints-from-db` 없이는 잴 수 없다). 측정 가능한 연결만 본 완전 개념은 10/10 — 즉 Completeness 0/10은 결손이 아니라 "힌트를 잰 적이 없다"는 사실이다.
- **경로 깔때기**(개념 → 스킬 → 문항 → 오개념 → 교수): 스킬 10 → 문항 10 → 오개념 **4** → 교수 4. 끊기는 고리는 전부 `problem→misconception`(오답 보기가 핵심 오개념에 닿는 문항이 없다)이고 대상 개념은 `12미적Ⅰ-02-01`·`02-05`·`02-06`·`02-08`·`02-09`·`02-10` 6건이다.
- **문제 메타데이터 7필드**(적격 문항 1,121건): difficulty·skill·concept·solution·answer·misconception_signature 6필드는 1,121건 전부 present · `hint_strategy`는 1,121건 전부 unknown(측정 불가). 7필드 전부 충족 0건 · 결손(missing) 없음 1,121건 · 오개념 서명이 개념 상속만인 문항 885건.
- **공급 가능 커버리지 0/10**의 사유는 10건 전부 "개념 콘텐츠 검수 상태가 `ai_estimated`"다 — 검수 승격(G-kg02) 전에는 연결돼 있어도 학생에게 공급되지 않는다.

## 2. `phase3_metrics` — 7지표 (P3-14 제품 완성도 평면)

명령: `python -m whymath_backend.ops.phase3_metrics --json <경로>` (작업 디렉터리 `src/backend`)
run_id `c67f1e3bfec2` · 관측 시각 2026-10-18T07:10:02Z · 표본 기준 live · 명세 `phase3-scope-v1`
**종료 코드: 2** (종합: 측정 실패 — 미측정 지표가 있어 종합을 못 낸다). 합계: 충족 3 · 미달 1 · 미측정 3 · 목표미정 0.

| # | 지표 | 분모 | 값 | 목표 | 상태 |
|---|---|---|---|---|---|
| 1 | Curriculum Coverage | 대표 과정 10노드 | 10/10 = 100.0% | ≥ 98% | 충족 |
| 2 | Concept Completeness | 핵심 개념 10 | 측정 불가(0/10~10/10 구간) | ≥ 95% | 미측정 |
| 3 | Problem Coverage | 대표 과정 스킬 8종 | **8/8 = 100.0%** | ≥ 95% | 충족 |
| 4 | Solution QA Pass | 승인 문항 1,121건 재검증 | **1121/1121 = 100.0%** | ≥ 99.5% | 충족 |
| 5 | Learning Loop Success | 학습 루프(세션) 관측창 | 측정 불가 | — | 미측정 |
| 6 | Critical Defect | Hard Gate F-Ⅱ·F-Ⅴ | 측정 불가 | — | 미측정 |
| 7 | Graph Connectivity Coverage | 핵심 개념 10 | **4/10 = 40.0%** | ≥ 95% | 미달 |

지표별 단서:

- **② Completeness**가 `phase3_coverage`에서는 "0/10 미달"이고 여기서는 "미측정"인 것은 모순이 아니다. P3-14 CLI는 "측정 불가 연결(hint)만 남은 개념 10/10"을 미달 확정이 아니라 **구간 미확정**으로 접는다(모른다 ≠ 아니다). 두 CLI의 종료 코드 규칙이 다른 것도 같은 이유다(P3-02는 미달 우선 exit 1 · P3-14는 미측정 우선 exit 2).
- **③ Problem Coverage** 스킬별 승인 문항 수: case-analysis 72 · deductive-reasoning 48 · equation-rearrangement 316 · graph-reading 72 · graph-sketching 421 · pattern-generalization 24 · polynomial-arithmetic 312 · word-problem-modeling 24. 10/14 기록(6/8 · `pattern-generalization`·`word-problem-modeling` 0건)에서 **8/8**로 올라왔다 — PR #1636(필수 문제유형 2종 추가)이 길을 열고 P3-05 4·5단계(#1648·#1650·#1654 생성 → 승인 각인 204건)가 두 스킬을 채웠다. 8/8은 10/16 #1655(P3-05 완료 기록)가 이미 적은 값이며 이번 실측이 그것을 재확인한다.
- **④ Solution QA Pass** 통과/실패/검증 불가 = 1121/0/0 · 재검증 도구 `harness.corpus_reverify`(Tier1+Tier2 · fuzz 미사용). 10/14 기록 917/917에서 분모가 1,121로 늘었고(차이 204 = P3-05 4·5단계 승인 각인 204건과 일치) 실패는 여전히 0이다. 스코어카드 '수학적 오류율'과는 모집단이 다르다(골든 FN vs 대표 과정 SymPy 재검증).
- **⑤ Learning Loop Success** 미측정 사유: 기본 실행에서는 `ConnectionRefusedError`(이 클론에는 PostgreSQL이 없다 — 예외 타입명이 출력에 남는다). `--no-db`로 재실행(run_id `51e92fea0217`)하면 "DB 수집을 하지 않았고 입력도 없다"로 사유만 바뀌고 종료 코드는 같은 2다. 좌석은 `EOS-15` · 실제 값은 운영 DB(`whymath-pg` 5433)에서 `ops.loop_kpi_gate`로만 잰다.
- **⑥ Critical Defect** 미측정 사유: 입력 payload 없음(`--hard-gate-input` 미지정). 이 CLI는 payload 수집기를 갖지 않으므로 이 환경에서는 설계대로 측정 불가다 — 0건이 아니다.

## 3. 10/17 인용값 대비 변동 — Graph Connectivity 5/10 → 4/10

| 지표 | 10/17 판정문(main `e35692ef`) | 이번 실측(main `6f668474`) | 변동 |
|---|---|---|---|
| Content Coverage | 10/10 | 10/10 | 없음 |
| Curriculum Coverage | 10/10 | 10/10 | 없음 |
| Concept Completeness | 0/10 (hint 측정 불가 10) | 0/10 (hint 측정 불가 10) | 없음 |
| Graph Connectivity | 5/10 · 미충족 5건 | **4/10 · 미충족 6건** | `12미적Ⅰ-02-01` 추가 탈락 |
| 공급 가능 커버리지 | 0/10 | 0/10 | 없음 |
| Concept Slot Coverage | 60/60 | 60/60 | 없음 |

**원인 = P3-49(PR #1678, 2026-10-18 05:15 UTC 머지)**. 극값의 개수 객관식 24건의 PRIMARY 개념을 `02-01`(미분계수) → `02-07`(증가·감소, 극대·극소)로 옮겼고, 그 24건이 02-01에서 `problem→misconception` 고리를 성립시키던 유일한 문항들이었다. 이 하락은 게이트 `G-p3-49-extremum-retag-approval`(#1675)에서 Kiki가 **"5/10 → 4/10 하락 수용 포함"으로 승인**한 것이며 PR #1678 본문에도 명시돼 있다. 02-01 사슬 복구는 `P3-50`이 소유한다.

검증 방법(추론이 아니라 재실행): `git worktree add --detach <스크래치> d33ab2e46`(P3-49 직전 커밋)에서 `import whymath_backend; whymath_backend.__file__`이 워크트리 경로를 가리키는 것을 확인한 뒤 같은 CLI를 돌렸다 — 결과 **5/10 · 깔때기 오개념 5 → 교수 5 · 미충족 5건**, 즉 10/17 판정문과 동일. 따라서 변동은 측정 환경 차이가 아니라 코퍼스 변경 1건(P3-49)으로 전부 설명된다. 워크트리는 실행 후 제거했다.

## 4. 이 측정이 말하지 못하는 것 (한계 명시)

- **힌트 연결·`hint_strategy`**: 좌석이 DB뿐이라 이 클론(DB 없음)에서는 영원히 측정 불가다. Completeness의 실값은 Kiki 머신에서 `--hints-from-db`(prod DB 5433)로만 나온다.
- **⑤·⑥**: 위와 같은 이유로 이 환경에서는 설계상 미측정이다. 7지표의 종합(exit 0/1)은 운영 DB + Hard Gate payload가 있는 실행에서만 성립한다.
- **종료 코드로 게이트 조건을 가르지 못하는 문제**(P3-02 exit 1이 Content Coverage와 무관한 두 지표 때문에 난다)는 10/17 판정문이 이미 `P3-54`로 분리했고 이 문서는 그것을 다시 열지 않는다.
- 이 문서는 **값의 기록**이지 게이트 판정이 아니다. `G-p3-g1-week1`의 PASS(Content Coverage 10/10)는 이번 실측에서도 유지되지만, 게이트 재판정은 별도 태스크·세션의 몫이다.

## 5. 재현 명령 (Kiki 머신 · Windows PowerShell)

```powershell
# Windows PowerShell — 이 PC(Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git log -1 --oneline origin/main
cd src\backend
python -m whymath_backend.l1.standards.phase3_coverage
"COVERAGE_EXIT=$LASTEXITCODE"
python -m whymath_backend.ops.phase3_metrics --no-db --json $env:TEMP\phase3_metrics.json
"METRICS_EXIT=$LASTEXITCODE"
```

기대값: 첫 명령 exit 1(Completeness·Graph Connectivity 미달) · 둘째 exit 2(미측정 3종). 힌트까지 재려면 Docker `whymath-pg`를 띄운 뒤 첫 명령에 `--hints-from-db`를 붙인다(DB를 못 읽으면 exit 2로 멈추며 통과로 위장하지 않는다).
