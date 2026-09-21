# Subject Contract v1 — 교차 과목 프로브 (Physics) 판정표

> **판정 기준: main `76f415db`** (2026-09-06) — 아래 실측은 전부 이 커밋의 trunk 코드에서
> 확인했다. 판정은 시점에 종속되므로 해시 없는 판정은 재현 불가다(CLAUDE.md 2026-09-06).
>
> **재확인: main `bfd4cb3a`** — 판정 직후 `EOS-83·84·88·90·81`(#980)·`OPS-63`(#1001)이 착지했고
> 그중 **`EOS-90`이 `subject_adapter.py`와 2층 동결 테스트를 건드렸다**. 판정 전제를 재측정한
> 결과 전부 유지된다: DTO **15필드 불변**(5+3+4+3) · 필수 **3메서드 불변** · §4-1 재스캔
> **`ZERO_CALLERS`**. 따라서 이 문서의 판정을 갱신하지 않는다.
> 판정 *기준* 해시는 실측 시점 그대로 둔다 — 뒤늦게 바꾸면 재현 불가가 된다.
>
> **`EOS-90`과의 축 구분(중복 아님)**: 그쪽
> ([`subject_contract_v1_candidate_verdicts_2026-09-04.md`](../reviews/subject_contract_v1_candidate_verdicts_2026-09-04.md))은
> *"계획서 후보 9종 중 무엇이 계약에 **들어가는가**"*를 판정했고, 이 문서는 *"이미 들어간
> 15필드가 과목 **중립인가**"*를 판정한다. 소속 판정 ↔ 중립성 판정으로 상보적이다.

- **태스크**: `EOS-92-cross-subject-contract-probe`
- **상위 결정**: [`ADR-004`](./adr/ADR-004-subject-contract-v1-provisional.md) — Provisional · 프로브 후 Freeze · ✗ > 3이면 중단
- **대상 계약**: `schema/subject_adapter.py`(필수층) — 3메서드 + DTO 4종 **15필드**
- **결론 요약**: **깨진 필드 ✗ = 0 · 강등 0건 · Core 확장 0건.**
  **그러나 이 프로브는 반증력이 낮다** — 채움 축(갈래 A)에는 실패 사례가 존재하지 않고
  판정 축(갈래 B)에는 기계 뒷받침이 없다. 근거는 §3.
  **오늘 Frozen으로 승격하지 않는다**(ADR-004 ①: 9/27 이전 Frozen 선언 금지).

---

## §0. 프로브 문항 — 어디서 왔는가 (날조 금지)

**저장소에 물리 문항 자산은 없다.** 실측: `data/corpus/`의 `problem_bank_*` 전건이 수학이고,
`schema/enums.py`에 physics 과목 값이 없으며, `atom_graph_v1/graph.json`의 "물리" 히트 3건은
수학 원자 설명문 안의 부수 언급이지 문항이 아니다(검색: `grep -rli "physics|물리" data/corpus/`,
`grep -n "PHYSICS|physics" schema/enums.py`).

따라서 **아래 문항은 이 프로브를 위해 구성한 것**이며 코퍼스에서 인용한 것이 아니다.
ADR-004 §근거가 *"왜 구현이 아니라 대조인가 — 필요한 것은 '계약이 물리를 받는가'의 판정뿐"*
이라 적었으므로 이 방식이 전제된 설계다.

### P1 — 등가속도 운동 (물리학Ⅰ·역학)

> 질량 `2.0 kg`인 물체가 마찰이 없는 수평면 위에 정지해 있다. 이 물체에 수평 방향으로
> 일정한 알짜힘 `6.0 N`을 `4.0초` 동안 작용시켰다. **4.0초 후 물체의 속력**과 **그동안
> 이동한 거리**를 구하시오.

정답: `a = F/m = 3.0 m/s²` → **`v = 12 m/s`**, **`s = ½at² = 24 m`**

이 문항을 고른 이유 — 수학 문항과 **다른 축을 최대한 많이 건드리도록** 골랐다:
단위(m/s·m) · 차원 · 유효숫자 · **다답**(v와 s 둘) · 물리 법칙 제약(F=ma) ·
전형적 오개념(등가속도인데 등속 공식 `s=vt`를 적용해 48 m를 얻음).

---

## §1. 라운드 1 — 필드별 채움 (acceptance ① 문자 그대로)

판정 기준: **채우지 못하거나 의미가 뒤틀리면 ✗.** 인상 판정 금지.

### 1-A. `ProblemStatement` (5필드)

| # | 필드 | Physics로 채운 값 | 판정 | 근거 |
|---|---|---|---|---|
| 1 | `problem_ref` | `physics.mechanics.uniform-acceleration-0001` | **○** | canonical slug·DB PK 아님. 과목 접두는 `ADR-003`(접두사=규약)과 정합 |
| 2 | `question_text` | 위 P1 지문 전문 | **○** | Core에 불투명 텍스트 |
| 3 | `answer` | `v=12 m/s; s=24 m` | **○** | "과목이 정의하는 불투명 문자열" — 다답 인코딩 규약은 과목 책임 |
| 4 | `answer_kind` | `physics.quantity_with_unit` | **○** | 과목이 정의·Core 미해석. Core 분기 0건은 §4에서 별도 확인 |
| 5 | `conditions` | `F=m*a; v=a*t; s=0.5*a*t^2; m=2.0 kg; F=6.0 N; t=4.0 s; v0=0` | **○** | description이 *"물리면 물리 관계식"*을 이미 명시 — 그 상상이 실제로 성립 |

### 1-B. `AnswerEvaluation` (3필드)

| # | 필드 | Physics로 채운 값 | 판정 | 근거 |
|---|---|---|---|---|
| 6 | `state` | `pass` | **○** | 3상태로 충분. 부분점수·허용오차는 어댑터의 tolerance 정책이 pass/fail로 접는 것이며, 수학의 근사값 처리와 동형(과목 특이 아님) |
| 7 | `reason` | `None` (pass) / 오답 시 `"거리에 등속 공식 적용 — s=vt(48 m)"` | **○** | |
| 8 | `checked_axes` | `("numeric_substitution", "dimensional_consistency", "unit_match", "significant_figures")` | **○** | 자유 문자열 튜플이라 물리 축을 그대로 담는다 |

### 1-C. `ProblemValidation` (4필드)

| # | 필드 | Physics로 채운 값 | 판정 | 근거 |
|---|---|---|---|---|
| 9 | `state` | `pass` | **○** | |
| 10 | `reason` | `None` | **○** | |
| 11 | `machine_axes` | `("law_consistency", "dimensional_consistency")` | **○** | F=ma 정합·차원 일치는 기계로 닫힌다 |
| 12 | `residual_axes` | `("idealization_stated",)` | **○** | "마찰 없음" 같은 이상화 전제의 적절성은 기계가 못 닫는다 — 잔여 축 개념이 물리에서도 성립 |

### 1-D. `MisconceptionSignal` (3필드)

| # | 필드 | Physics로 채운 값 | 판정 | 근거 |
|---|---|---|---|---|
| 13 | `code` | `physics-constant-velocity-formula-on-accelerated-motion` | **○** | kebab·과목 네임스페이스는 과목 책임 |
| 14 | `confidence` | `0.82` | **○** | 0~1 |
| 15 | `matched_signals` | `("s=vt", "48")` | **○** | |

### 1-E. 메서드 3종 (시그니처 수용성)

| 메서드 | Physics 적용 | 판정 | 비고 |
|---|---|---|---|
| `evaluate_answer(problem, answer: Mapping[str,str])` | `{"v": "12 m/s", "s": "24 m"}` | **○** | 구조는 담긴다 |
| `detect_misconception(student_work: str, *, top_k)` | 텍스트화된 풀이 | **○** | |
| `async validate_problem(problem)` | 위 `ProblemValidation` | **○** | |

**라운드 1 집계: 15/15 ○ · ✗ 0건.** ADR-004 ④의 중단 상한(✗ > 3)에 걸리지 않았다.

---

## §2. 라운드 1에서 ✗가 아니지만 기록하는 관찰 3건

강등 대상이 **아니다**(✗가 아니므로). 그러나 "○"의 의미를 정확히 남기기 위해 적는다.

1. **`evaluate_answer`의 docstring 용어가 수학 은유다.** *"변수명→값 문자열 치환맵"* —
   물리에서 학생 답은 "변수에 대입할 값"이 아니라 "측정량의 값+단위"다. 자료구조는 동일하게
   담기므로 필드 결함이 아니지만, **용어가 수학을 전제**한다. 처분: 문서 용어 축(강등 아님).
2. **`ProblemStatement.answer`(단일 `str`) ↔ `evaluate_answer(answer: Mapping)`의 비대칭.**
   문항 정답은 문자열 1개인데 학생 답은 매핑이다. 다답 문항에서 정답 쪽 인코딩 규약을 과목이
   따로 정해야 한다. **수학의 연립방정식도 동일**하므로 과목 중립성 문제가 아니라 계약의
   일반적 표현력 한계다.
3. **`MisconceptionSignal.code`는 담기지만 뒷단이 수학 전용이다.** 계약은 코드만 받고 내용은
   L1에서 reactive 조회하는데, `misconception_catalog`·crosswalk 게이트 계약에 물리 오개념은
   없다. **계약 결함이 아니라 데이터 부재**다.

---

## §3. 라운드 2 — 이 프로브에 반증력이 있는가 (변별력 검사)

> CLAUDE.md "변별력 없는 검증 스텝 금지": *성공/실패 양쪽에서 같은 값을 내는 검사는 검증이
> 아니라 위장이다.* 라운드 1이 15/15 ○를 냈으므로, **그 검사가 실패할 수는 있었는지**를
> 확인해야 판정이 성립한다.

### 3-1. 정정 — 초판의 대조군 설계는 무효였다 (Codex P1 · PR #999)

**초판은 History를 "계약이 배제 선언한 과목"으로 보고 대조군에 썼다. 그 전제가 틀렸다.**

| 인용한 곳 | 실제로 무엇을 말하는가 |
|---|---|
| `verification_capabilities.py:274-277` — *"수학·물리엔 있고 역사엔 없다"* | **선택적** 능력 `ExpressionEquivalence`에 관한 문장이고, 바로 다음 절이 *"이것이 `SubjectAdapter` **필수 3종에 들어가지 않은 이유**다"*로 잇는다 — 즉 **필수층에서 History를 배제한 문장이 아니라, 그 능력을 필수층에서 뺀 이유**다 |
| `subject_adapter.py:221-227` — 필수층 추가 게이트 | *"이 능력이 Physics·Chemistry·**History**에도 반드시 존재하는가?"* — **History는 필수층의 대상**이다 |

그러므로 **History가 필수층 DTO를 채우는 것은 설계된 성공(expected pass)이지 대조군이 아니다.**
초판이 그것을 "배제 선언한 과목도 통과한다"로 읽은 것은 **선택층 문장을 필수층에 적용한
오독**이다. 그 오독 위에 세운 "반증력 없음" 논증도 그대로는 성립하지 않는다.

### 3-2. 다시 물음 — 그렇다면 이 검사가 **실패하는 입력**은 무엇인가

대조군을 무효화했으니 제대로 찾아야 한다. acceptance ①의 판정 기준은 두 갈래다.

**갈래 A — "채우지 못한다"(기계적 축): 실패하는 입력을 구성할 수 없었다.**

15필드의 타입 분포가 이유다:

| 타입 | 개수 | 실패 가능성 |
|---|---|---|
| `str` · `str \| None` · `tuple[str, ...]` | **13** | 임의의 문자열을 받는다 — **거부되는 값이 없다** |
| `Literal["pass","fail","unverifiable"]` | 2 (`state` ×2) | 3값 중 하나면 통과 |
| `float` (`ge=0, le=1`) | 1 | 0~1이면 통과 |

`extra="forbid"`는 **필드를 늘리는 것**만 막는다. 기존 필드에 무엇을 넣느냐는 막지 않는다.
따라서 갈래 A는 **어떤 과목을 대도 통과한다** — History가 통과한 것도 이 때문이고(설계대로),
계약이 상정하지 않은 임의의 텍스트를 넣어도 마찬가지다. **실패 사례를 구성할 수 없는 검사는
통과했다는 사실로 아무것도 입증하지 못한다.** 이것이 초판이 옳게 본 부분이며, 정정은
*근거*(대조군)였지 *결론*(갈래 A는 무정보)이 아니다.

**갈래 B — "의미가 뒤틀린다"(판정 축): 실패할 수 있으나 기계 뒷받침이 없다.**

이쪽은 실제로 실패할 수 있다. 실제로 §2에 뒤틀림 후보 3건을 적었고(수학 은유 용어·
정답/학생답 비대칭·오개념 뒷단 부재), 그중 어느 것도 **과목 중립성을 깨는 수준은 아니라고
판정**했다. 그러나 그 판정은 **사람의 읽기**이고, 그것을 검사하는 기계는 없다.
계약 파일이 같은 사실을 적는다(`subject_adapter.py:52-55`): *"그 축의 기계 집행은
**현재 없다**(있는 척 금지)."*

### 3-3. 이 라운드의 결론

라운드 1의 **✗ 0은 다음 두 가지의 합**이다:

- **갈래 A(채움) = 구조적으로 무정보** — 실패 사례가 존재하지 않는 검사의 통과
- **갈래 B(뒤틀림) = 사람 판정 · 기계 뒷받침 0** — 내가 0으로 판정했고 그 판정을 검사하는 것은 없다

그래서 "✗ 0이니 계약이 과목 중립임이 확인됐다"고 말할 수 **없다**. 말할 수 있는 것은
**"이 방법으로는 반증하지 못했다"**까지다. 반증 시도가 실패했다고 말하려면 그 시도에
반증력이 있어야 하는데, 갈래 A에는 없고 갈래 B에는 기계 뒷받침이 없다.

계약 파일 자신이 이 지점을 예고했다(`subject_adapter.py:40-55` "래칫의 한계"):

> 의미적 확장은 잡지 못한다 — `conditions`는 그대로 두고 그 안에 물리 관계식을 넣거나,
> Core 코드가 `answer_kind` 값을 읽어 분기하기 시작하는 것은 필드 개수가 안 변하므로 CI가
> 초록이다. **그런데 과목 중립성이 실제로 깨지는 주된 경로가 바로 이쪽이다.**
> … **이 축의 검증 책임은 `EOS-92`에 있다.**

그러므로 프로브는 §4로 이어져야 한다. 여기서 멈추면 "계약을 채워 봤다"는 의식만 치른 것이다.
반증력 있는 검사의 설계는 **`ARCH-43`**가 소유한다 — 그 태스크의 근거는 (정정 후) *"History가
잘못 통과한다"*가 아니라 **"갈래 A에 실패 사례가 존재하지 않고 갈래 B에 기계 뒷받침이 없다"**이다.

## §4. 라운드 3 — 계약이 지목한 진짜 축: Core가 불투명 페이로드를 해석하는가

기계 집행이 **없는** 축이다(`subject_adapter.py:52-55`가 "있는 척 금지"로 명시). 사람이 읽는다.

### 4-1. Core 측 해석 지점 실측 — **0건**

```
grep -rn "\.evaluate_answer(\|\.detect_misconception(\|\.validate_problem(" --include=*.py \
     src/backend/whymath_backend/ | grep -v schema/subject_adapter.py | grep -v l4/subject_adapter_math.py
→ 0건
grep -rn "SubjectAdapter" --include=*.py src/backend/whymath_backend/ (계약·구현 제외)
→ 산문 주석 2건뿐 (verification_capabilities.py:3,5,277 · l3/pedagogy/slot_generator.py:29)
```

Core가 `answer_kind`·`conditions` 값을 읽어 분기하는 코드는 **없다**. 중립성이 깨진 지점 0건.

### 4-2. 그러나 그 0의 의미를 정확히 적는다 — **필수층은 아직 호출된 적이 없다**

| 층 | 배선 | 근거 |
|---|---|---|
| **선택층** (`verification_capabilities`) | **실재** | `composition.py`가 팩토리 5종 노출(`__all__`:50-56) · 소비처 `api/coach.py`·`l3/pedagogy/slot_generator.py` |
| **필수층** (`SubjectAdapter` 3메서드) | **호출자 0** | `composition.py`에 어댑터 팩토리 0건 · Core 호출자 0건(위 grep) |

이는 사고가 아니라 **`EOS-69` ⑦의 설계 결과**다 — A분류 잔여 호출부가 쓰던 것은 단계 수준·
기호 동치 축이라 `evaluate_answer` 하나로 접으면 "unverifiable을 fail로 접기"가 발생하므로,
Kiki 결정으로 **능력별 좁은 Protocol(선택층)**로 분리했다(`EOS-69` acceptance ⑥·⑦).

**판정에 미치는 영향**: `Core→Math 정적 의존 0`(G1 조건)과 `해석 지점 0`(§4-1)은 사실이지만,
그 0은 **"계약이 잘 막아서"가 아니라 "필수층을 아직 아무도 쓰지 않아서"** 성립한다.
중립성은 *사용에 의해* 깨지는데, 사용이 없으므로 이 축은 **아직 시험된 적이 없다**.

> ⚠ **문서 드리프트 1건**: `subject_adapter.py:108-118` "집행 상태 — 경유 배선 완료"는 층을
> 구분하지 않아, 읽는 사람이 **필수층이 배선됐다고 오독**할 수 있다. 실제로 배선된 것은
> 선택층이다. 이 문서가 그 구분을 기록한다(계약 파일 수정은 이 프로브의 범위 밖 —
> Core 확장 금지 규칙과 무관한 문서 축이나, 라벨 변경 시 함께 다룬다).

---

## §5. 종합 판정

| 항목 | 결과 |
|---|---|
| 깨진 필드 ✗ | **0건** (15/15 ○) |
| ADR-004 ④ 중단 상한(✗ > 3) | **미도달** — 프로브 완주 |
| `DEMOTED_FIELDS` 변경 | **없음** — 빈 dict 유지 (강등 대상 0) |
| Core 확장 (규칙 2조 나) | **0건** — 필드·메서드 추가 없음 |
| 단조 축소 | 유지 (줄지도 늘지도 않음) |
| Core의 페이로드 해석 | **0건** (§4-1) |

### 상태 라벨 — **`Provisional` 유지. 오늘 승격하지 않는다.**

`EOS-92` acceptance ④는 *"깨진 필드 0이면 Frozen 승격 **가능**"*이라 적는다 — "가능"이지
"해야 한다"가 아니다. 승격하지 않는 이유 둘:

1. **ADR-004 ①이 금지한다.** *"2026-09-27까지 Core Contract를 Frozen으로 선언하지 않는다."*
   오늘은 09-06이다. 이 프로브는 9/27 판정의 **입력**이지 판정 자체가 아니다.
2. **✗ 0의 근거가 약하다.** §3-3이 보였듯 채움 축은 실패 사례를 구성할 수 없고(무정보),
   뒤틀림 축은 사람 판정이며 기계 뒷받침이 0이다. "반증 시도가
   실패했다"고 말하려면 그 시도에 반증력이 있어야 하는데, 라운드 1은 그렇지 못했다.
   §4가 보완하지만 §4-2의 한계(필수층 미사용)가 남는다.

### 9/27 승격 판정 시 확인할 조건 (권고)

- [ ] §4-1 재측정 — Core 해석 지점이 여전히 0건인가 (grep 2종, 이 문서 §4-1 명령 그대로)
- [ ] 필수층에 실사용 호출자가 생겼는가 — 생겼다면 그 지점이 페이로드를 해석하지 않는지 확인
- [ ] `DEMOTED_FIELDS`가 여전히 비어 있는가 (비어 있어야 정상 — 강등 0)
- [ ] `EOS-70`(explain) 판정이 이 프로브 결과에 종속돼 있음을 확인 (ADR-004 §결과)

**만약 9/27까지 필수층 사용이 여전히 0이라면**, 승격 라벨은 `Frozen`이 아니라
**`Frozen (unexercised)`**처럼 그 사실을 담는 표기를 권고한다 — ADR-004가
`Frozen (math-only, acknowledged)`를 둔 것과 같은 취지다. **인지된 한계는 관리할 수 있지만,
검증되지 않은 중립성을 검증된 것으로 부르면 관리할 수 없다.**

### 프로브 판정자 (ADR-004 §미결 답)

ADR-004는 *"프로브 판정자: Kiki 단독인가, 물리 도메인 확인이 필요한가 — `EOS-92`에서 확정"*을
미결로 남겼다. **답: 물리 도메인 전문가 확인은 불요.**
근거 — 이 프로브가 판정한 것은 *물리 내용의 정확성*이 아니라 **계약 필드가 물리 페이로드를
받는가**이며, 15필드 중 13개가 불투명 문자열이라 판정에 물리 지식이 개입할 여지가 구조적으로
없다(§3이 그것을 실증한다). P1의 물리 내용(`a=3.0 m/s²`·`v=12 m/s`·`s=24 m`)이 틀렸더라도
필드 채움 판정은 바뀌지 않는다. **9/27 승격 판정은 Kiki 단독으로 성립한다.**

---

## §6. 이 프로브가 남긴 한계와 소유자

"소유자 없는 알려진 결함"을 만들지 않는다(Gate D).

| # | 한계 | 소유자 |
|---|---|---|
| 1 | 필드 채움 검사의 반증력이 낮다(§3) — 갈래 A는 실패 사례가 **존재하지 않고**(13/15가 임의 문자열 수용), 갈래 B는 사람 판정에 기계 뒷받침이 0이다. 중립성을 실제로 반증할 수 있는 검사가 필요 | **`ARCH-43`** (신설) |
| 2 | 필수층 호출자 0(§4-2) — 중립성이 *사용*으로 시험된 적이 없다. `EOS-69` ⑦의 설계 결과이므로 결함은 아니나, 그 상태가 지속되는지 추적할 소유자가 없었다 | **`ARCH-41`** (신설) |
| 3 | 계약 파일 "집행 상태" 절이 층을 구분하지 않아 필수층 배선으로 오독 가능(§4-2 ⚠) | `ARCH-41` acceptance ③ |

> **한계 2·3의 프리픽스가 `EOS`가 아닌 이유** — 등재 시 `backlog.py add`가 거부했다:
> *"프리픽스 `EOS`는 00~99번을 모두 소진해 `TASK_ID_RE`(정확히 2자리 숫자)를 지키는 다음
> 번호를 더 이상 제안할 수 없다 — 새 프리픽스로 분리하는 등 **사람의 결정이 필요하다**
> (`HARN-21`)."* 거부는 장애물이 아니라 판정이므로 우회하지 않고(CLAUDE.md "거부의 우회
> 금지"), 내용상 아키텍처 계약 추적이라 기존 `ARCH` 계열로 등재했다.
> **`EOS` 계열 고갈은 이 프로브의 부수 발견이며 Kiki 결정 사항이다** — 다음 EOS 태스크는
> 누가 등재하든 같은 지점에서 막힌다. 기계 축은 `HARN-21`이 이미 소유한다.

> **`ARCH-43`의 번호 경위**: 초판은 `EOS-99`로 등재했으나 타 세션 #1000이 같은 번호를 **먼저
> 머지**해 충돌했다(`validate`가 "번호 참조가 결정 불가가 된다"로 거부 — HARN-10 유형). 머지된
> 쪽은 개명할 수 없으므로 미머지인 이쪽을 옮겼다. **EOS 계열은 소진**됐고(#1000: "EOS-98·EOS-99가
> 마지막"), **`MP`는 EOS 후속이 아니라 회차 축 접두**이며 EOS 축 일반의 후속 접두는 게이트
> `G-eos-task-prefix-exhausted`[kiki]가 정한다 — 미결이다. 3자리 손제작은 금기이므로
> (`build_harness.md` §8) 내용상 아키텍처 계약 검증인 이 태스크를 기존 `ARCH` 계열로 옮겼다
> (자매 `ARCH-41`과 같은 판단). 번호는 눈으로 고르지 않고 CLI 제안을 따랐다.

---

## 부록. 재현 명령

> **정정 3건 (Codex P1 · PR #999)** — 초판의 이 절은 세 가지가 틀렸다: ⑴`grep` 파이프라인이
> **스캔 실패와 0건을 구별하지 못했다** ⑵`pytest -q`로 출력을 억제했다(바로 아래에서 그 금지
> 규칙을 인용하면서) ⑶Kiki 기본 환경인 PowerShell 블록이 없었다. 셋 다 아래에서 고쳤다.

### ① Core 해석 지점 — 스캔 실패를 0건으로 위장하지 않는다

**왜 단순 파이프라인이면 안 되는가(실측)**: `grep A | grep -v B`에서 `$?`는 **마지막** grep의
값이다. 소스 경로가 없어 첫 grep이 exit 2로 죽어도 마지막 `grep -v`는 여전히 exit 1을 내므로,
**"스캔 실패"가 "호출자 0건"과 같은 값으로 보인다** — 측정 실패가 통과로 위장되는 정확한 형태다
(CLAUDE.md 검증 권위: *"인프라가 죽으면 '측정 실패'가 보여야지 '0건 통과'로 위장되면 안 된다"*).

```bash
# WSL / Linux — 저장소 루트
cd /mnt/c/Users/kiki/Desktop/__AI/WhyMath

set -o pipefail   # 파이프 중간 실패를 $?로 전파 — 이 줄이 이 검사의 변별력이다
SRC=src/backend/whymath_backend
test -d "$SRC" || { echo "SCAN_ERROR: 소스 경로 없음 — 판정 불가"; exit 2; }

grep -rn "\.evaluate_answer(\|\.detect_misconception(\|\.validate_problem(" \
  --include=*.py "$SRC" \
  | { grep -v "schema/subject_adapter.py" || true; } \
  | { grep -v "l4/subject_adapter_math.py" || true; }
rc=${PIPESTATUS[0]}   # 첫 grep의 값만 본다
case "$rc" in
  0) echo "RESULT=CALLERS_FOUND  (필수층 호출자가 생겼다 — §4-2 재판정 필요)" ;;
  1) echo "RESULT=ZERO_CALLERS   (정상 — 호출자 0건)" ;;
  *) echo "RESULT=SCAN_ERROR rc=$rc  (판정 불가 — 0건으로 읽지 말 것)" ;;
esac
```

```powershell
# Windows PowerShell (Phaiakes9) — 저장소 루트
cd C:\Users\kiki\Desktop\__AI\WhyMath

$Src = "src\backend\whymath_backend"
if (-not (Test-Path $Src)) { Write-Host "SCAN_ERROR: 소스 경로 없음 — 판정 불가"; exit 2 }

$hits = Select-String -Path "$Src\*.py" -Recurse `
          -Pattern '\.evaluate_answer\(|\.detect_misconception\(|\.validate_problem\(' |
        Where-Object { $_.Path -notmatch 'subject_adapter(_math)?\.py$' }

if ($null -eq $hits) { Write-Host "RESULT=ZERO_CALLERS   (정상 — 호출자 0건)" }
else { $hits | ForEach-Object { $_.Path + ":" + $_.LineNumber }; Write-Host "RESULT=CALLERS_FOUND  (§4-2 재판정 필요)" }
```

**세 상태를 구별한다**: `ZERO_CALLERS`(정상) / `CALLERS_FOUND`(재판정) / `SCAN_ERROR`(판정 불가).
초판처럼 `EXIT=1` 하나로 읽으면 앞의 둘 중 어느 것인지 알 수 없다.

### ② 계약 동결 테스트 — 출력을 억제하지 않는다

`-q`를 쓰지 않는다. 조용한 도구는 실패해도 성공과 같은 화면을 내며, 이 저장소는 그 형태로
한 번 뚫렸다(2026-08-09 PR #732 — `black --check -q`가 6파일 실패를 감춰 main red).

```bash
# WSL / Linux — 저장소 루트에서
python -m pytest tests/backend/schema/test_subject_adapter_two_tier_contract.py \
                 tests/backend/schema/test_subject_adapter.py; echo "EXIT=$?"
```

```powershell
# Windows PowerShell (Phaiakes9) — 저장소 루트
cd C:\Users\kiki\Desktop\__AI\WhyMath
python -m pytest tests\backend\schema\test_subject_adapter_two_tier_contract.py `
                 tests\backend\schema\test_subject_adapter.py; echo "EXIT=$LASTEXITCODE"
```

기대: **19 passed · EXIT=0**. 판정은 **exit code**로 한다(출력 문자열 아님 — CLAUDE.md
"검사 명령의 출력을 억제하거나 잘라서 판정 금지"). 실행기는 `python -m pytest`로 못 박는다
(단독 `pytest` 금지 — 다중 환경에서 다른 인터프리터에 결합될 수 있다).

### 이 재현 명령에 변별력이 있는가 — 실패 주입으로 확인함 (2026-09-06)

런북의 자가검증 스텝은 *실패 상태에서 실제로 실패 신호를 내는지* 확인된 것만 동봉한다
(CLAUDE.md 2026-07-17 "변별력 없는 검증 스텝 금지"). 명령 ①을 뮤테이션으로 검증했다:

| 상태 | 조작 | grep exit |
|---|---|---|
| 기준선 | 없음 | **1** (매칭 0건 = 해석 지점 없음) |
| 뮤테이션 | `api/coach.py` 끝에 `_adapter.evaluate_answer(...)` 1줄 주입 | **0** — 그 줄을 파일:줄과 함께 검출 |
| 원복 | `cp` 백업 복원 | **1** |

원복은 `cp` 백업으로 했다(`git checkout --`는 뮤테이션과 미커밋 작업분을 구분하지 못하고 둘 다
무증상으로 날린다 — CLAUDE.md 2026-08-10). 원복 후 `git status`에 뮤테이션 잔류 0건 확인.

**한계(있는 척 금지)**: 이 명령은 `.메서드(` 형태의 **텍스트 호출**만 본다.
`getattr(adapter, "evaluate_answer")()` 같은 동적 호출은 잡지 못한다 — 저장소 실측 0건이라
현재는 공백이 아니지만, 잡지 못한다는 사실 자체를 적는다. 이 축의 기계 집행 설계는
`ARCH-43`가 소유한다.
