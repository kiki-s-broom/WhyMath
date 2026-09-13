# 실중복 71쌍 콘텐츠 판정 기록 — QUAL-07 (2026-09)

- **태스크**: `QUAL-07-recovered-corpus-duplicate-disposition` (PB-13 회수가 만든 실중복 처분 — QUAL-01 가시화 → QUAL-02 처분 선례 승계)
- **판정일**: 2026-09-12
- **판정 기준**: `main` **5902faaf** (작업 브랜치 `claude/geos-ip-separation-evidence-e8hsjd`의 분기점). 아래 모든 "이전" 수치는 이 커밋의 코퍼스를 읽은 값이고, "이후" 수치는 이 세션 작업 트리의 값이다 — **미머지**다.
- **감사 도구**: `whymath_backend.harness.problem_duplication_audit` (실행 전용 — 이번에도 도구 자체는 수정하지 않았다)
- **판정 원칙**: 일괄 삭제·자동 규칙 금지. 71쌍이 동형인지를 **먼저 측정**하고, 동형이 증명된 뒤에야 하나의 판정을 71쌍에 적용했다(§2).

---

## 0. 요약

| | 처분 전 (main 5902faaf) | 처분 후 (이 트리) |
|---|---|---|
| 확정 실중복 쌍(T2) | **71** (same_format 71 · diff_format 0) | **0** |
| 그 밑에 깔린 **조건식(수학 실체) 동일** 건수 | **138** | **0** |
| 데모 풀 동시노출 쌍 | 0 | 0 |
| 슬러그 충돌(T1) | 0 | 0 |
| 총 문항 수 | 14,034 | **14,034** (불변 — 은퇴 0건) |
| 코퍼스 수 / 스캔 쌍 | 37 / 666 | 37 / 666 |
| `[12미적Ⅱ-02-04]` 커버 | 200 | **200** |
| `[CALC1-02-03]` 커버 | 200 | **200** |
| `[CALC1-02-04]` 커버 | 200 | **200** (무변경 — slug 200건 동일) |
| rephrase 무변화 회계 | 421 / 274 / 147 / 0 / 0 | 동일(무영향) |

**처분 수단은 레코드 은퇴가 아니라 생성기 파라미터 공간의 서로소 분리 + 전건 재생성이다**(§3). 은퇴(QUAL-02 선례의 수단)를 택하지 않은 이유는 §3-B에 전부 적었다 — 한 줄로 줄이면 *은퇴는 71건만 지우고 67건을 남기며, 생성기를 다시 돌리는 순간 전부 되살아난다*.

---

## 1. 실측 고정 (acceptance ①)

재현 명령(이 세션이 실제로 돌린 것):

```
cd src/backend && python3.12 -m pytest -c pyproject.toml ../../tests/backend/harness/test_problem_duplication_audit.py
```

처분 전 실측(전부 이 세션이 직접 재현):

- 교차 중복 **71쌍** — 전건 `same_question_format`, `diff_format` 0.
- 71쌍 전부 **신규↔신규**, 단 두 코퍼스 사이: `problem_bank_highschool_quotient_rule_v0`(200건, 전건 `[12미적Ⅱ-02-04]`) ↔ `problem_bank_university_calc1_chain_quotient_v0`(400건 = `[CALC1-02-03]` 200 + `[CALC1-02-04]` 200). 기존 main 코퍼스와의 교차 중복 0.
- **같은 코퍼스 내부 중복 0** (양쪽 모두 발문 200/400건 전건 고유).
- **데모 풀 동시노출 0/71** — 두 코퍼스 모두 데모 풀(`generated_v0`·`misconception_mc_v0`·`problem_bank_v1`) 밖이다. 학생 노출 경로에 닿지 않는다.
- 중복 71건은 **전부 대학 쪽 `[CALC1-02-03]`(몫의 미분법)** 이고 연쇄법칙 흔적 0건(설명문 "연쇄" 0/71 · `CALC1-CHAIN-RULE` unit 0/71). 대학 코퍼스의 나머지 329건 중 200건이 연쇄법칙 설명을 갖는다(= `[CALC1-02-04]` 밴드 전량).
- 한쪽 71건을 제거해도 커버가 0이 되는 성취기준은 없다: `[CALC1-02-03]` 200→129, `[12미적Ⅱ-02-04]` 200→129.

### 1-b. 태스크 서술에 없던 신규 실측 — 실제 중복은 71이 아니라 **138**이다

감사 도구는 **발문 텍스트**로 중복을 판정한다. 두 생성기는 발문 템플릿을 2종
(`f(x) = …일 때, f'(k)의 값을 구하시오.` / `함수 f(x) = …의 도함수 f'(x)에 대하여 f'(k)를 구하시오.`)
번갈아 쓰고, 그 선택은 생성 회차 인덱스의 홀짝이다. 두 코퍼스의 인덱스 진행이 달라서 **같은 스켈레톤이 서로 다른 템플릿을 받은 경우 발문이 달라진다**.

`verify.conditions`(SymPy 검산 조건식 = 수학 실체)로 재면:

- 두 코퍼스가 공유하는 **조건식 138건**. 그중 발문까지 같은 것이 71건, 발문만 다른 것이 **67건**.
- 예시(조건식 동일 · 발문 상이):
  - 고교: `함수 f(x) = (-x^2 - 2x - 4)/(-4x - 7)의 도함수 f'(x)에 대하여 f'(-2)를 구하시오.`
  - 대학: `f(x) = (-x^2 - 2x - 4)/(-4x - 7)일 때, f'(-2)의 값을 구하시오.`

이 67건은 **처분 대상을 고르는 방식에 직접 영향을 준다**: 71건만 은퇴시키면 사람이 봐서 "같은 문제"인 67쌍이 그대로 남고, 감사 도구는 0쌍을 보고한다 — 측정이 개선을 *위장*하는 상태가 된다.

**주의 — "조건식 동일 = 같은 문항"은 이 생성기 쌍에서 성립하는 성질이지 일반 규칙이 아니다.** 두 생성기의 조건식은 `Derivative((a*x**2 + b*x + c) / (d*x + e), x).doit().subs(x, k) = y` 형태로 **계수 4종과 대입점을 전부 담아** 발문과 일대일 대응한다(그래서 키가 서로소면 발문도 조건식도 서로소임이 *증명*된다). 다른 생성기 계열은 조건식이 축약돼 문항을 식별하지 못한다 — §7의 전수 스캔이 그 반례를 전부 보여 준다.

---

## 2. 쌍별 개별 판정 (acceptance ②)

### 2-1. "동형이므로 한 판정을 적용한다"의 근거 — 분포 전수 측정

71쌍 각각에 대해 아래 필드를 전수 대조했다(표본 아님). 괄호 안은 71쌍 중 해당 값의 건수.

| 축 | 고교 측 | 대학 측 | 동형인가 |
|---|---|---|---|
| 성취기준 코드 | `[12미적Ⅱ-02-04]` (71/71) | `[CALC1-02-03]` (71/71) | **완전 동형** — 예외 0 |
| 단원 코드 | `HS-CALC2-QUOTIENT-RULE` (71/71) | `CALC1-QUOTIENT-RULE` (71/71) | 완전 동형 |
| 난이도 | 3.7 (71/71) | 3.9 (71/71) | 완전 동형 |
| subject | 공통 (71/71) | 공통 (71/71) | 완전 동형 |
| 개념 태그 | `H:12미적Ⅱ02-04` PRIMARY 0.95 (71/71) | `[]` (71/71) | 완전 동형(양측 각각 단일값) |
| 문항 형식 | 단답형 (71/71) | 단답형 (71/71) | 완전 동형 |
| 연쇄법칙 흔적 | 0/71 | 0/71 | 완전 동형 |
| 정답 | — | — | **71/71 동일** |
| `verify.conditions` | — | — | **71/71 동일** |
| `answer_explanation` | — | — | **71/71 동일** |
| `answer_format` | — | — | **71/71 동일** |

즉 71쌍은 **어느 축에서도 두 갈래로 갈리지 않는다**. "쌍마다 사정이 다를 수 있다"는 가정이 측정으로 기각됐으므로, 아래 한 판정이 71쌍 전부에 적용된다. 갈렸다면(예: 일부 쌍만 난이도가 같다거나 일부만 연쇄법칙이었다면) 그 부분집합은 별도 판정 대상이었다.

### 2-2. 쌍별 판정 3문항 (71쌍 공통 — 위 동형성 위에서)

**⑴ 양쪽 성취기준 코드가 실제로 다른가 → 그렇다.** `[12미적Ⅱ-02-04]`(2022 개정 고등 미적분Ⅱ)와 `[CALC1-02-03]`(대학 미적분학 I)은 서로 다른 교육과정 축의 코드다. 몫의 미분법은 두 과정에 **실재**하므로, "같은 규칙을 두 학교급이 각각 다룬다"는 사실 자체는 결함이 아니다 — 이 축만 보면 **양쪽 존치가 정당하다**. 일괄 삭제를 금지한 근거가 여기다.

**⑵ 난이도·문맥이 학교급에 맞게 분화돼야 하는가 → 그렇다. 그리고 분화돼 있지 않았다.** 두 코퍼스는 난이도를 3.7 / 3.9로 **다르게 표기**하면서 문항 본문·정답·해설·검산 조건식이 **글자 그대로 같았다**. 난이도 라벨에 대응하는 구조적 실체가 0이었다는 뜻이다. 학교급 분화가 필요하다는 판정은 이 관측에서 나온다 — 두 코드가 같은 문항을 가리키는 한, 어느 쪽 라벨도 의미가 없다.

**⑶ 한쪽 은퇴가 그 코퍼스의 성취기준 커버를 깨뜨리는가 → 깨뜨리지 않는다(그러나 이것이 은퇴를 정당화하지는 않는다).** 대학 쪽 71건 은퇴 시 `[CALC1-02-03]` 200→129로 **0이 되지 않는다**. 고교 쪽을 은퇴시켜도 `[12미적Ⅱ-02-04]` 200→129. 즉 "커버가 깨지니까 못 지운다"는 반대 근거는 성립하지 않는다. 은퇴를 택하지 않은 이유는 커버가 아니라 **재발**과 **67건 잔존**이다(§3).

**판정 결론(71쌍 공통)**: *양쪽 존치. 단, 두 문항이 같아진 원인(생성기 공간 공유)을 제거하고 양쪽을 각자의 학교급에 맞는 공간에서 다시 만든다.* 은퇴 레코드 **0건**.

71쌍의 처분 전 슬러그 대응표는 §부록 A에 전량(71행) 남긴다 — 재생성으로 양쪽 슬러그가 모두 바뀌었으므로, 이 표가 없으면 "무엇이 중복이었는가"를 사후에 복원할 수 없다.

---

## 3. 생성기 축 판정 — 근본 원인과 처분안 비교 (acceptance ③)

### 3-A. 근본 원인 (실측)

`highschool_quotient_rule_skeleton_generator.py`의 모듈 docstring이 스스로 밝힌다 —
*"`calculus_chain_quotient_rule_skeleton_generator`(대학 CALC1 축)의 몫의 미분법 설계를 K-12 고등 축으로 **그대로 재적용**한다."* 그 "그대로"에 **계수 범위와 난수 시드**가 포함돼 있었다.

| | 고교 생성기 | 대학 생성기(몫 밴드) |
|---|---|---|
| 분자 최고차 `a` | `range(-4,5)\{0}` | `range(-4,5)\{0}` |
| 분자 `b`,`c` | `range(-5,6)` | `range(-5,6)` |
| 분모 최고차 `d` | `range(-4,5)\{0}` | `range(-4,5)\{0}` |
| 대입점 `k` | `range(-3,4)` | `range(-3,4)` |
| 풀 시드 | `random.Random(20260807)` | `random.Random(20260807)` |
| 풀 목표 | 300 | 260 |

같은 시드 + 같은 선택지 + 같은 거부 규칙이므로 두 표본 추출 스트림이 **동일**했다. 실측 결과:

- 대학 몫 밴드 풀 260개가 고교 풀 300개의 **진부분집합**(교집합 260 = 대학 풀 전체).
- 배치가 실제로 소비하는 앞 200개끼리의 키 교집합 **138** — 이것이 위 §1-b의 138과 정확히 일치한다(조합공간 전체 크기 108,416 중 고작 200개씩을 뽑았는데 138이 겹친 것은 우연이 아니라 **같은 스트림**이라는 증거다).

즉 **문항만 은퇴시키면 배치를 다시 돌리는 순간 138건이 그대로 재생된다.**

### 3-B. 처분안 비교 — 왜 (B)인가

| | (A) 대학 쪽 71레코드 은퇴 | (B) 파라미터 공간 서로소 분리 + 재생성 |
|---|---|---|
| 발문 동일 71건 | 해소 | 해소 |
| 조건식 동일 67건(발문 상이) | **잔존** — 감사는 0쌍을 보고하므로 **개선으로 위장**된다 | 해소 |
| 재생성 시 재발 | **재발**(생성기 무수정) | 차단(공간이 서로소) |
| `[CALC1-02-03]` 커버 | 200→129 (−35.5%) | 200 유지 |
| 난이도 라벨(3.9 vs 3.7)의 실체 | 없음(남은 129건도 고교 문항과 같은 공간) | 생김(대학 밴드는 큰 계수를 반드시 포함) |
| 슬러그 변동 | 71건 소멸 | 고교 200 + 대학 몫 200 재발급(외부 참조 0건 확인 — 아래) |
| 비파괴 격리(`EOS-71`) 적용 여부 | 격리로 대체 가능하나 위 두 줄은 그대로 | 애초에 제거가 아니므로 해당 없음 |

**(A)를 버린 결정적 이유는 두 가지다.** ① 재발한다 — 처분이 다음 배치 실행까지만 유효한 것은 처분이 아니다. ② 측정이 위장된다 — 71을 0으로 만들면서 67을 남기는 것은, 감사 지표만 개선하고 실제 중복은 절반 남기는 형태다. CLAUDE.md의 *"측정·게이트 도구가 판정치를 위장하면 안 된다"* 축에 정면으로 걸린다.

**(B)를 택하면서 받아들인 비용도 적는다**: 두 코퍼스의 슬러그 600건 중 400건(고교 200 + 대학 몫 200)이 바뀐다. 슬러그는 본문 해시라 본문이 바뀌면 필연이다. 제거 전 전수 grep으로 **외부 배선 참조 0건**을 확인했다(`src/`·`tests/`·`scripts/`·`data/corpus/**`·`seed_demo.py`·`concept_assessment_v1/index.json` — `wm-hs-quotient-rule`·`wm-calc1-quotient-rule` 문자열의 유일한 등장은 두 생성기의 `slug_prefix` 기본값뿐이다). 두 코퍼스는 데모 풀 밖이고 `is_published=false`이므로 학생 노출 경로에도 없다.

**검토했으나 버린 제3안 (C) 시드만 교체**: 두 스트림을 다르게 만들 뿐 공간은 계속 겹친다. 200×200 무작위 추출의 기대 충돌은 ~0.37건으로 작지만 **0이 아니고, 보장도 없다**. "서로소"는 확률이 아니라 성질이어야 게이트로 동결할 수 있다. 버린다.

**검토했으나 버린 제4안 (D) 대학 밴드를 분모 이차식으로 승격**: 난이도 분화로는 (B)보다 교육적으로 풍부하지만, 정수 답 보장 설계(g(k)=±1 역산)를 이차 분모로 다시 세워야 하고 검증·난이도 재산정이 따라붙는다. 이 태스크의 문제(중복)에 필요한 범위를 넘는 과공학이라 버린다 — 필요해지면 별도 태스크.

### 3-C. 어느 쪽 공간을 좁혔는가 — 교육적 판정

분할 축으로 **계수 절댓값**을 골랐다.

- **고교 미적분Ⅱ (난이도 3.7)**: 계수 4종(`a`,`b`,`c`,`d`) 전부 **절댓값 3 이하**. 교과서 도입 수준의 작은 계수.
- **대학 CALC1 (난이도 3.9)**: 계수 4종 중 **최소 하나가 절댓값 4 이상**(`_quotient_band_admits`).

두 술어는 서로의 부정이므로 교집합이 **정의상** 공집합이다(확률이 아니라 성질). 그리고 이 분할은 난이도 표기에 **구조적 실체**를 준다 — 대학 밴드는 항상 큰 계수를 하나 이상 포함하고 고교 밴드는 절대 포함하지 않는다.

**대입점 `k`는 좁히지 않았다.** 음수 대입 연습은 고교 축에서도 성취기준 요구이므로, `k`를 가르면 한쪽이 교육적으로 손상된다. 계수 축은 "숫자가 크다/작다"의 차이지만 대입점 축은 "부호 처리를 연습하는가"의 차이다 — 후자를 건드리지 않는 것이 판정의 핵심이다.

**좁힌 쪽(고교)이 성취기준 요구를 여전히 만족하는가 — 재생성 후 실측:**

| 축 | 처분 전(200건) | 처분 후(200건) | 판정 |
|---|---|---|---|
| 성취기준 커버 | `[12미적Ⅱ-02-04]` 200 | `[12미적Ⅱ-02-04]` 200 | 불변 |
| 발문 고유 수 | 200 | **200** | 전건 고유 유지 |
| `a` 실현값 | −4…4(0 제외) | **−3,−2,−1,1,2,3** (6종 전부) | 부호 양쪽 보존 |
| `b` 실현값 | −5…5 | **−3…3** (7종 전부, 0 포함) | 부호 양쪽 + 0항 생략 표기 보존 |
| `c` 실현값 | −5…5 | **−3…3** (7종 전부, 0 포함) | 동상 |
| `d` 실현값 | −4…4(0 제외) | **−3,−2,−1,1,2,3** (6종 전부) | 분모 부호 양쪽 보존 |
| `k` 실현값 | −3…3 | **−3…3** (7종 전부) | **좁히지 않음** — 음수 대입 보존 |
| `e`(역산 종속값) 범위 | — | **−10…10** | 분모 상수항은 여전히 두 자리까지 |
| `max\|계수\|` 분포 | — | 3:155 · 2:43 · 1:2 | 상한에 붙어 있지 않고 퍼져 있다 |
| 난이도 | 3.7 전건 | 3.7 전건 | 불변 |
| 정답 평균 절댓값 | 32.0 | **15.6** | 의도된 방향(도입 수준 계산량) |
| 정답 고유값 수 | 106 | **79** | 아래 §6에 한계로 기록 |
| `answer_format` | 실수 97 / 자연수 103 | 실수 107 / 자연수 93 | 균형 유지 |

**대학 쪽(넓은 쪽) 실측**: `a` −4…4(0 제외) 8종 전부 · `b`,`c` −5…5 11종 전부 · `d` 8종 전부 · `k` 7종 전부 · `max|계수|` 분포는 4:108 / 5:92 — 즉 **전건이 고교 상한(3) 바깥**이다. 커버·난이도·형식 전부 불변(`[CALC1-02-03]` 200 · 3.9 · 단답형).

**연쇄법칙 밴드(`[CALC1-02-04]`)는 손대지 않았다.** 구조가 `(ax+b)ⁿ`라 몫 공간과 애초에 겹치지 않는다 — 재생성 후에도 **슬러그 200건이 동일**함을 실측으로 확인했다(본문은 아래 §5의 스키마 필드 3종만 추가됨).

### 3-D. 실제로 바꾼 코드

| 파일 | 변경 |
|---|---|
| `src/backend/whymath_backend/l3/equivalent/highschool_quotient_rule_skeleton_generator.py` | `_MAX_ABS_COEFFICIENT = 3` 신설 · `_A_RANGE`/`_BC_RANGE`/`_D_RANGE`를 여기서 유도(`_K_RANGE` 무변경) · 모듈 docstring에 정정 기록 |
| `src/backend/whymath_backend/l3/equivalent/calculus_chain_quotient_rule_skeleton_generator.py` | `_QUOT_MIN_LARGE_ABS = 4` · `_quotient_band_admits()` 신설 · `_build_quotient_pool()`이 그 술어로 거부 샘플링 · 모듈 docstring 보강 |
| `data/corpus/problem_bank_highschool_quotient_rule_v0/problems.jsonl` | 전건 재생성(200건) |
| `data/corpus/problem_bank_university_calc1_chain_quotient_v0/problems.jsonl` | 전건 재생성(400건 — 몫 200건만 내용 변동, 연쇄 200건은 슬러그 동일) |
| 두 코퍼스의 `_provenance.json` | 재생성 이력·`disposition` 블록 추가. 대학 쪽은 `generation_method`의 *"생성기 파일명 자동 역추적 실패"*·`generation_cli`의 *"(미확정)"* 을 실측으로 **정정**(PB-14가 남긴 공백 — §7 참조) |

재생성 명령(둘 다 exit 0 · 수용 게이트 거부 0건):

```
cd src/backend
python3.12 -m whymath_backend.harness.highschool_quotient_rule_batch
python3.12 -m whymath_backend.harness.university_calc1_chain_quotient_batch
```

---

## 4. 집행 지점 — 정본화와 별항 (acceptance ④)

§3이 계약의 정본화라면, 아래가 **그 계약을 실제로 판정하는 실행 경로**다.

| 동결하는 것 | 파일 | **어느 CI 잡·스텝에서 도는가(실측)** |
|---|---|---|
| 실코퍼스 실중복 71 → **0** | `tests/backend/harness/test_problem_duplication_audit.py` | `ci.yml` 잡 **`backend`** → 스텝 **`Pytest (with coverage)`**(`pytest -m "not corpus_authoring" …`). 이 파일에는 `corpus_authoring` 마커가 없으므로 **PR 상시 경로**에서 돈다. |
| 파라미터 공간 서로소 분할(전수 열거)·풀·코퍼스·교육 요구 보존 | `tests/backend/l3/equivalent/test_quotient_rule_space_disjointness.py` (신규) | 동일 — `backend` 잡 `Pytest` 스텝. 마커를 **일부러 붙이지 않았다**(배치 실행이 없어 3.7초). |
| 생성기·배치 자체의 회귀(수용 게이트 전건 통과·바이트 결정론) | `tests/backend/l3/equivalent/test_*_quotient_*`·`tests/backend/harness/test_*_batch.py` | `ci.yml` 잡 **`corpus-authoring`** → 스텝 **`Pytest (corpus_authoring 마커 전량)`**. 이 잡은 `needs.changes.outputs.authoring`이 `src/backend/whymath_backend/l3/equivalent/`·`…/harness/`·`tests/backend/l3/equivalent/`·`tests/backend/harness/`를 건드리는 PR에서 true가 되므로, **이번 PR에서 반드시 실행된다**. |

### 4-1. 유지한 감시 축 2종과 그 공허성 — 숨기지 않는다

acceptance ④가 유지를 지시한 두 단언(데모 풀 동시노출 0 · "두 코퍼스 한정")은 **현재 0쌍 상태에서 공허 참**이다(빈 목록 위의 전칭·부분집합). 그 사실을 테스트 주석에 그대로 적었다. 남긴 이유는 *지금 무언가를 재기 위해서*가 아니라 **재발 시 성격을 즉시 가르기 위해서**다 — 재발분이 데모 풀에 닿거나 제3 코퍼스로 번지면 `== 0`이 먼저 깨지고, 이 두 단언이 **어느 쪽으로 깨졌는지**를 같은 실행에서 말한다. 형태는 전칭(`not any(...)`)·부분집합(`<= {…}`)으로 바꿔 0쌍에서도 참이 되게 했다(원래는 `== {…}`라 0쌍에서 거짓이 된다).

두 축의 **변별력은 주입으로 실측했다**(§부록 B의 M6·M7) — 데모 풀 코퍼스 2종에 같은 발문을 심으면 첫 단언이, 제3 코퍼스와 겹치게 심으면 둘째 단언이 각각 RED가 된다.

---

## 5. 부수 변경 — 스키마 필드 3종 (의도하지 않았으나 불가피)

두 코퍼스는 PB-13이 2026-08-09 브랜치에서 **파일 단위로 회수**한 것이라, 그 시점 직렬화 결과가 그대로 커밋돼 있었다. 현재 코드로 재생성하면 레코드에 `schema_version`(`whymath-problem` 1.1.0)·`extensions`·`relations` 세 필드가 추가된다. 이것은 처분의 목표가 아니라 **재생성의 필연적 부산물**이다.

- 손으로 제거하지 않았다 — 제거하면 커밋된 코퍼스가 `run_*_batch` 산출물과 달라져 "생성기 산출물이 정본"이 깨진다.
- 저장소 전체 대조: 37개 코퍼스 중 이 필드들을 가진 것은 `problem_bank_calculus1_integral_v0`·`problem_bank_calculus2_trig_integral_v0` 2종이었고, 이번에 두 코퍼스가 더해져 4종이 됐다. 나머지 33종은 여전히 구 형태다 — **이 문서는 그 33종을 손대지 않는다**(§7).

---

## 6. 남긴 한계 (정직 기록)

1. **고교 쪽 정답 고유값 106 → 79.** 계수를 좁히면 f'(k) 값의 분포도 좁아진다. 200문항 중 서로 다른 정답이 79종이라 같은 정답을 갖는 문항이 늘었다. 문항 자체는 200건 전건 고유(발문·조건식 모두)이므로 중복이 아니지만, "답만 외우는" 경로에는 이전보다 약간 유리하다. 측정했고, 수용한다 — 대안(계수 상한을 3이 아니라 다른 값으로)은 서로소 분할선을 옮기는 것이라 대학 쪽 공간을 대신 좁히게 된다.
2. **두 축의 술어는 코드 두 곳에 따로 있다.** 공유 상수 모듈로 묶지 않았다(형제 생성기 간 private 경계 비침범이 이 디렉터리의 기존 관례다). 드리프트 방어는 `test_quotient_rule_space_disjointness.py`의 **전수 열거**가 맡는다 — 한쪽 범위를 바꾸면 교집합 또는 미포함 조합이 즉시 나온다.
3. **감사 도구는 여전히 발문 텍스트만 본다.** §1-b의 67건(조건식 동일·발문 상이)은 이번에 공간 분리로 사라졌지만, **다른 코퍼스 쌍에도 같은 사각이 있을 수 있다**. 도구에 조건식 축을 더하는 것은 이 태스크 범위 밖이다(QUAL-02도 같은 이유로 도구를 수정하지 않았다) — §7에 후속으로 남긴다.
4. **`review_status` 축은 건드리지 않았다.** 두 코퍼스 모두 미검수·`is_published=false`이고 이번 처분은 제거가 아니므로 `EOS-71` 격리 경로를 쓸 일이 없었다. 재생성으로 슬러그가 바뀌었으므로, 이후 검수 기록은 새 슬러그 기준으로 쌓인다.

---

## 7. 범위 밖 (명시)

- **감사 도구(`problem_duplication_audit`)에 `verify.conditions` 축 추가** — §1-b가 드러낸 사각(발문만 다른 실질 중복)의 일반 해법. 도구 수정은 이 태스크 범위 밖이다(QUAL-02도 같은 이유로 도구를 수정하지 않았다). 다만 **범위 파악용 전수 스캔은 이번에 해 두었다** — 37개 코퍼스 전건이 `verify.conditions`를 갖고 있고, 조건식을 공유하는 코퍼스 쌍은 6쌍이다:

  | 코퍼스 쌍 | 조건식 공유 | 발문까지 동일 | 성격(전건 또는 표본 대조) |
  |---|---|---|---|
  | `generated_v0` × `rephrased_v0` | 336 | 274 | **계보** — rephrased 421건 전건이 `relations`로 부모를 선언하며, 감사 도구가 의도적으로 배제하는 관계다(QUAL-03 '무변화 274'가 바로 이 집합). 신규 사각 아님 |
  | `complex_number_arithmetic_v0` × `polynomial_arithmetic_v0` | 198 | **0** | **오탐** — 조건식이 `(-1) + (-3) = y`로 축약돼 문항을 식별하지 못한다(복소수 실수부 vs 다항식 상수항 계수 — 전혀 다른 문항) |
  | `elementary_area_measure_v0` × `elementary_volume_measure_v0` | 20 | **0** | **오탐** — `x - (1 * 1000000) = 0` (km²→m² vs m³→cm³) |
  | `generated_v0` × `killer_v0` | 8 | **0** | **오탐** — `x**2 + 2*x - 1 = 0` (삼차함수 극소점 vs 이차방정식 두 근의 곱) |
  | `rephrased_v0` × `problem_bank_v1` | 1 | **0** | **오탐** — 같은 이차방정식의 작은 근 vs 큰 근 |
  | `generated_v0` × `problem_bank_v1` | 1 | **0** | 동상 |

  즉 **이 저장소에서 조건식 축을 그대로 게이트로 올리면 오탐이 압도한다**(228/564 = 계보를 뺀 전건이 오탐). 조건식이 문항을 *식별*하는 생성기 계열에서만 의미가 있으므로, 도구화하려면 "이 조건식이 문항을 식별하는가"를 먼저 판정하는 층이 필요하다. 그 설계는 이 태스크 범위 밖이다 — **그리고 이번 몫의 미분법 쌍 외에 조건식-식별성이 성립하는 다른 생성기 쌍이 있는지는 측정하지 않았다.**
- **나머지 33개 코퍼스의 스키마 필드 현행화**(§5) — 재생성이 필요하고 코퍼스별 영향 검토가 따로 필요하다.
- **다른 생성기 쌍의 파라미터 공간 겹침 전수 점검** — 이 저장소에는 `l3/equivalent/`에 스켈레톤 생성기가 수십 종 있고, "형제 생성기 설계를 그대로 재적용" 관례가 반복 등장한다(이번 사고의 형태). 각 생성기 쌍의 *풀 키* 겹침을 직접 잰 것은 이번 몫의 미분법 쌍뿐이며, 나머지는 **점검하지 않았다** — 발문 축에서는 중복 감사가 0쌍이므로 같은 형태의 사고가 남아 있다면 위 표의 '조건식 축'을 통해서만 보일 텐데, 그 축은 오탐이 압도해 판정 근거가 되지 못한다.
- **대학 밴드의 이차 분모 승격**(§3-B (D)안) — 난이도 분화를 더 밀고 나가는 설계. 필요해지면 별도 태스크.
- **두 코퍼스의 AI 검수·노출 적격 판정** — 실 LLM이 필요해 이 환경 밖(Kiki 머신). `is_published=false` 유지.

---

## 부록 A — 처분 전 71쌍 슬러그 대응표

재생성으로 양쪽 슬러그가 모두 바뀌었으므로, 처분 전 상태를 복원할 수 있는 유일한 기록이다. 71쌍 전건은 위 §2-1의 모든 축에서 동형이며, `정답`은 두 레코드가 공유하는 값이다.

| # | 고교 (은퇴 아님·재생성으로 소멸) | 대학 (동상) | 정답 |
|---|---|---|---|
| 1 | `wm-hs-quotient-rule-3f2ba3d76a23` | `wm-calc1-quotient-rule-5009d7f4ff93` | 13 |
| 2 | `wm-hs-quotient-rule-e7ac18e4f53d` | `wm-calc1-quotient-rule-3876345f27ae` | -22 |
| 3 | `wm-hs-quotient-rule-9e93eabbc97c` | `wm-calc1-quotient-rule-dce6da01c73d` | -18 |
| 4 | `wm-hs-quotient-rule-732ad6701f72` | `wm-calc1-quotient-rule-7b955b03edc8` | -11 |
| 5 | `wm-hs-quotient-rule-204276fad9c7` | `wm-calc1-quotient-rule-90808cbfa0f0` | 101 |
| 6 | `wm-hs-quotient-rule-f5f233e2564e` | `wm-calc1-quotient-rule-8028ee43aac3` | 33 |
| 7 | `wm-hs-quotient-rule-c80d18bdf03c` | `wm-calc1-quotient-rule-866151f32b30` | -130 |
| 8 | `wm-hs-quotient-rule-2bd01bb6e7a3` | `wm-calc1-quotient-rule-53d6a17276f7` | 25 |
| 9 | `wm-hs-quotient-rule-f788c55f02d1` | `wm-calc1-quotient-rule-0b07afee3a73` | 4 |
| 10 | `wm-hs-quotient-rule-99a7513ab861` | `wm-calc1-quotient-rule-c19f0c131645` | 8 |
| 11 | `wm-hs-quotient-rule-8927dcf7e1eb` | `wm-calc1-quotient-rule-e697f36eb4dd` | 16 |
| 12 | `wm-hs-quotient-rule-60c1ffe3b66d` | `wm-calc1-quotient-rule-9421fb71a557` | 4 |
| 13 | `wm-hs-quotient-rule-bc9414a0b7f6` | `wm-calc1-quotient-rule-0d66704dedab` | 3 |
| 14 | `wm-hs-quotient-rule-6e8a1be945e8` | `wm-calc1-quotient-rule-edbe665d9d6b` | 21 |
| 15 | `wm-hs-quotient-rule-24c2efffd92d` | `wm-calc1-quotient-rule-6615e1a73478` | -11 |
| 16 | `wm-hs-quotient-rule-843957a29237` | `wm-calc1-quotient-rule-47f5ba4ff387` | -17 |
| 17 | `wm-hs-quotient-rule-8da48c5a99ce` | `wm-calc1-quotient-rule-ed7054e4517f` | 15 |
| 18 | `wm-hs-quotient-rule-433bb4a59e9d` | `wm-calc1-quotient-rule-893d88c9df31` | -76 |
| 19 | `wm-hs-quotient-rule-733825d26389` | `wm-calc1-quotient-rule-df3fd5184602` | 23 |
| 20 | `wm-hs-quotient-rule-535728cdf4c2` | `wm-calc1-quotient-rule-4cbfb4838abd` | -33 |
| 21 | `wm-hs-quotient-rule-0b908251564c` | `wm-calc1-quotient-rule-f7bad69abb2e` | 9 |
| 22 | `wm-hs-quotient-rule-9ef5807e4448` | `wm-calc1-quotient-rule-5ec0ce74241a` | -127 |
| 23 | `wm-hs-quotient-rule-6cdce756d186` | `wm-calc1-quotient-rule-de476ccadde5` | 8 |
| 24 | `wm-hs-quotient-rule-4b0e91348387` | `wm-calc1-quotient-rule-09bfe7e1a7e1` | 62 |
| 25 | `wm-hs-quotient-rule-f94bcbda32b8` | `wm-calc1-quotient-rule-48d65b6b733a` | -60 |
| 26 | `wm-hs-quotient-rule-5e4cb6caffc9` | `wm-calc1-quotient-rule-23dc7a32daa6` | -147 |
| 27 | `wm-hs-quotient-rule-f930376d2663` | `wm-calc1-quotient-rule-426168f8afd2` | 97 |
| 28 | `wm-hs-quotient-rule-3be4e4303706` | `wm-calc1-quotient-rule-57d89eedfd7b` | 37 |
| 29 | `wm-hs-quotient-rule-7f35c0d6ae04` | `wm-calc1-quotient-rule-d2f06978da66` | 21 |
| 30 | `wm-hs-quotient-rule-1cdcddafecf3` | `wm-calc1-quotient-rule-1ed01736668d` | -13 |
| 31 | `wm-hs-quotient-rule-1edb4d2c30a5` | `wm-calc1-quotient-rule-d8bebabcc136` | -17 |
| 32 | `wm-hs-quotient-rule-d3f73e6b730d` | `wm-calc1-quotient-rule-f427fd230bce` | -73 |
| 33 | `wm-hs-quotient-rule-8a7b2ed671e1` | `wm-calc1-quotient-rule-d7210180f40b` | 9 |
| 34 | `wm-hs-quotient-rule-9d1768854257` | `wm-calc1-quotient-rule-fb8205d9aaaf` | 15 |
| 35 | `wm-hs-quotient-rule-453f449f1c1d` | `wm-calc1-quotient-rule-2cf408e005df` | 77 |
| 36 | `wm-hs-quotient-rule-18c5d63fa374` | `wm-calc1-quotient-rule-80b76c35c40e` | 1 |
| 37 | `wm-hs-quotient-rule-8ca3ca985600` | `wm-calc1-quotient-rule-a4858e9321a1` | -24 |
| 38 | `wm-hs-quotient-rule-5fd5d7617501` | `wm-calc1-quotient-rule-e974943aafdb` | 5 |
| 39 | `wm-hs-quotient-rule-ea30c55e17c1` | `wm-calc1-quotient-rule-9f70d9f518ef` | 40 |
| 40 | `wm-hs-quotient-rule-07ede7f21d0d` | `wm-calc1-quotient-rule-f9ce46ca38fb` | -8 |
| 41 | `wm-hs-quotient-rule-5bebd9c9c25f` | `wm-calc1-quotient-rule-8cd59f46104f` | -78 |
| 42 | `wm-hs-quotient-rule-9fbc56a1d2a6` | `wm-calc1-quotient-rule-02af1f4a1b6a` | 23 |
| 43 | `wm-hs-quotient-rule-f207910e89f9` | `wm-calc1-quotient-rule-a7ec5cbc4578` | -40 |
| 44 | `wm-hs-quotient-rule-944798881967` | `wm-calc1-quotient-rule-67e014a76fc6` | -65 |
| 45 | `wm-hs-quotient-rule-c7994da5efc0` | `wm-calc1-quotient-rule-1620050f2415` | 18 |
| 46 | `wm-hs-quotient-rule-3ee09e9b3068` | `wm-calc1-quotient-rule-bae1f9eeae6a` | 16 |
| 47 | `wm-hs-quotient-rule-803ee0c5d0f9` | `wm-calc1-quotient-rule-3efb1c4513c8` | -13 |
| 48 | `wm-hs-quotient-rule-a49f4ee0f871` | `wm-calc1-quotient-rule-1657263d8fd0` | -31 |
| 49 | `wm-hs-quotient-rule-4dd017e0ba06` | `wm-calc1-quotient-rule-682f5aa7cd02` | -33 |
| 50 | `wm-hs-quotient-rule-dfd1fc1030f7` | `wm-calc1-quotient-rule-ae8d5c8c1a30` | 120 |
| 51 | `wm-hs-quotient-rule-8f589eb480fa` | `wm-calc1-quotient-rule-44d694553a40` | -6 |
| 52 | `wm-hs-quotient-rule-5c75d4f2f422` | `wm-calc1-quotient-rule-863fc4f9a22e` | -2 |
| 53 | `wm-hs-quotient-rule-cb65c199f79a` | `wm-calc1-quotient-rule-73eb26c6be63` | -14 |
| 54 | `wm-hs-quotient-rule-282b1189de0c` | `wm-calc1-quotient-rule-4fed040edc42` | -16 |
| 55 | `wm-hs-quotient-rule-c66ea2343271` | `wm-calc1-quotient-rule-cf3e27354fc3` | -14 |
| 56 | `wm-hs-quotient-rule-a90a35c9168b` | `wm-calc1-quotient-rule-706bf01fe650` | -23 |
| 57 | `wm-hs-quotient-rule-f6111dd555b8` | `wm-calc1-quotient-rule-f4273311ba3e` | 65 |
| 58 | `wm-hs-quotient-rule-17441a7a6ebb` | `wm-calc1-quotient-rule-c96241dcbda2` | 7 |
| 59 | `wm-hs-quotient-rule-ff07d1d67238` | `wm-calc1-quotient-rule-4b608bf25cdf` | 15 |
| 60 | `wm-hs-quotient-rule-2d777739351c` | `wm-calc1-quotient-rule-d5828a821aa3` | -6 |
| 61 | `wm-hs-quotient-rule-36d8de69ab08` | `wm-calc1-quotient-rule-fdb346030655` | 5 |
| 62 | `wm-hs-quotient-rule-712bae65491b` | `wm-calc1-quotient-rule-c0d8bcc06afa` | -27 |
| 63 | `wm-hs-quotient-rule-ca31e48ac4a5` | `wm-calc1-quotient-rule-e413ad2aa870` | 143 |
| 64 | `wm-hs-quotient-rule-270a67c5fc14` | `wm-calc1-quotient-rule-89c647661684` | 109 |
| 65 | `wm-hs-quotient-rule-6b66ff936240` | `wm-calc1-quotient-rule-ac74c9b2d426` | 13 |
| 66 | `wm-hs-quotient-rule-bd7cacddda71` | `wm-calc1-quotient-rule-c5ffbbf0580b` | -137 |
| 67 | `wm-hs-quotient-rule-5b138e745787` | `wm-calc1-quotient-rule-87f3ec7a304a` | 3 |
| 68 | `wm-hs-quotient-rule-6203feb311cd` | `wm-calc1-quotient-rule-e1243c37bed0` | -188 |
| 69 | `wm-hs-quotient-rule-8c797455650e` | `wm-calc1-quotient-rule-84316ce51f1f` | -6 |
| 70 | `wm-hs-quotient-rule-b454ac07c6d8` | `wm-calc1-quotient-rule-4f76bca19d23` | 27 |
| 71 | `wm-hs-quotient-rule-26731a38cef6` | `wm-calc1-quotient-rule-344023c1687e` | -1 |

---

## 부록 B — 보호 장치 실패 주입 (뮤테이션) 실측

하네스: 셸을 배제한 순수 Python(`scratchpad/mutate.py` — 세션 산출물, 저장소 밖). 각 회차마다
**주입이 실제로 적용됐는지**(`치환 대상 count == 기대치` + `mutated != original`)와 **원복이 바이트
동일한지**(sha256 전건 대조)를 실행 전후에 단언한다. 대조군(무주입)은 양쪽 파일 GREEN이고,
9회차 원복 후 재대조군도 GREEN이다.

| # | 무엇을 깨뜨렸나 | 대상 | 신호(rc) | **먼저 터진 단언** |
|---|---|---|---|---|
| 대조군 | 무주입 | 두 파일 | **0** (20 passed · 49 passed) | — |
| M1 | 고교 계수 상한 `3 → 4` (대학 공간과 재중첩) | disjointness | **1** (6 failed) | ① 전수 열거 교집합 |
| M2 | 고교 계수 상한 `3 → 2` (양쪽 다 좁히기 — 과잉 수정) | disjointness | **1** (4 failed) | ② 분할이 합집합을 덮는가 |
| M3 | 대학 술어 `>= 4 → >= 3` (경계 한 칸 완화) | disjointness | **1** (4 failed) | ① + 경계 파라미터 `(3,3,3,3)` |
| M4 | 대학 술어 `>= → >` (경계 한 칸 강화) | disjointness | **1** (5 failed) | ② + 경계 파라미터 `(4,3,3,3)` |
| M5 | 대학 술어가 `b`·`c`를 안 본다(부분 계수만 검사) | disjointness | **1** (4 failed) | ② (b·c만 큰 조합이 미아가 된다) |
| M6 | 풀 빌더가 술어를 **호출하지 않는다**(술어 자체는 멀쩡) | disjointness | **1** (1 failed) | ② 풀 키 교집합 — 술어와 배선을 가르는 축 |
| M7 | **코퍼스 재생성 누락**(생성기만 수정) | disjointness + audit | **1** (5 failed) | ③ 코퍼스 발문/조건식 교집합 · 코퍼스 계수 술어 정합 · 난이도 구조 분화 · audit `duplicate_pair_count == 0`(63쌍) |
| M8 | 데모 풀 코퍼스 2종(generated_v0·problem_bank_v1)의 발문을 같게 | audit | **1** (1 failed) | **`not any(pair.demo_pool_co_exposed …)`** — 유지 지시 축 ① |
| M9 | 고교 코퍼스 ↔ 제3 코퍼스(problem_bank_v1) 중복 | audit | **1** (1 failed) | **`{…} <= {두 코퍼스}`** — 유지 지시 축 ② |

**생존(검출 실패) 0건 / 9건.**

### B-1. 이 표가 말하지 않는 것 (전건 RED ≠ 커버리지)

전건 RED는 **내가 주입 목록에 올린 절**만 검사한다. 실제로 이번 회차에서 한 번 틀렸다: 초판
M8·M9는 레코드를 *추가*하는 방식이라 `report.total_problems == 14034`가 **먼저** 터졌고, 정작
재려던 감시 축 두 개에는 **도달하지 못했다**. 테스트 주석에는 그 두 축이 RED가 된다고 적혀
있었으므로, 고치지 않았다면 **차단 주체를 틀리게 지목한 문면**이 남았을 것이다. 발문 *치환*
방식으로 바꾸고 `--tb=long`으로 실제 실패 단언을 지목해 확인한 뒤에야 위 표의 M8·M9 열이
성립했다. 감시 축 두 개를 `== 0`보다 **앞에** 둔 것도 이 실측의 결과다.

주입하지 **않은** 축(= 이 표가 아무 말도 하지 않는 축)은 §6·§7에 적었다 — 특히 감사 도구 자체의
발문-전용 판정, 다른 생성기 쌍의 공간 겹침, 나머지 33개 코퍼스.
