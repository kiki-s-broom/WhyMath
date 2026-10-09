# SymPy 불가 영역 검증기 v2 — 도메인별 설계 부록

> **문서 성격**: `verifier_v2_design.md`의 부록. 각 SymPy 불가 영역에 대해 DSL 문법·기계 검증 가능 축·기계 불가 잔여 축·교차검증 관점을 정의한다.
>
> **범위**: 단계 A 실증 도메인(기하 이산형 / 통계 자료형) 상세 + **단계 B 도메인(벡터 / 수열 귀납)의 발화 조건·DSL·잔여 축·관점 설계(S4-57)** + 코퍼스 소비처·밴드 매핑(§7) + 플러그인 하위호환 검토(§8) + 후속 슬라이스(§9).
>
> **판정 기준**: main `c322bb9cb`(2026-10-08). §4~§9의 코퍼스 수치와 코드 사실은 이 커밋에서 직접 실측했고, 수치 재현 명령은 §7.1에 있다. 판정은 시점에 종속되므로 코퍼스나 `l3/verifier.py`가 바뀌면 §7부터 다시 센다. "코드 독해 기준(미실행)"이라고 적은 항목은 읽어서 그렇게 보이는 것이지 실행으로 확인한 것이 아니다.
>
> **태스크 ID 대응**: 설계서 `verifier_v2_design.md` §7의 `S4-52-1`~`S4-52-5`는 대장에서 `S4-53`~`S4-57`로 등재됐다 — 단계 A 구현=S4-53, 통합 contract=S4-54, tier 개편=S4-55, Cross-Verify CLI·Wilson 게이트=S4-56, 단계 B 설계=S4-57(이 문서의 §4·§5·§7~§9).

---

## 1. 설계 공통 템플릿

각 도메인은 다음 5항목으로 기술한다.

1. **`answer_kind`**: 코퍼스 `verify.answer_kind`에 사용할 값.
2. **기계 검증 가능 축**: 전수/결정론으로 닫을 수 있는 부분.
3. **기계 불가 잔여 축**: 발문/자료/도형 해석에 남는 부분.
4. **DSL 문법 예시**: `verify.conditions` 문자열 형식.
5. **Cross-Verify v2 관점**: K=3 독립 관점.

---

## 2. 단계 A 후보 1: 기하 이산형 (`geometric_discrete`)

### 2.1 개요

평면/공간 격자·정다각형·격자점·선분 교차·도형 내부 정수점 등 "세기"로 답을 구할 수 있는 기하 문제. 유한 집합의 전수 열거가 가능하므로 `finite_probability`와 동일한 신뢰 등급(`FINITE_EXHAUSTIVE`)을 얻을 수 있다.

### 2.2 기계 검증 가능 축

- 주어진 좌표/격자 범위 내 점/선/면/도형의 개수.
- 교점 개수, 내부점 개수, 변 위 점 개수.
- 조합적 동치(예: 정n각형 대각선 교점 수 = C(n,4) 등) — SymPy 기호 검증과의 경계.

### 2.3 기계 불가 잔여 축

- **발문의 도형 조건 해석**: "평면 위의 서로 다른 4점"이 주어진 좌표 집합과 일치하는지.
- **좌표계 가정**: 문제가 암묵적으로 직교좌표계를 가정하는지.
- **일반성 없는 특수 사례**: "임의의" 삼각형 vs 주어진 좌표가 특수 삼각형(직각·정삼각형)인지.
- **측정 단위**: 길이/각도의 단위가 발문과 일치하는지.

### 2.4 DSL 문법 예시

```yaml
verify:
  answer_kind: geometric_discrete
  conditions: |
    grid=rectangular(x=[0,5], y=[0,5]);
    shape=triangle(A=(0,0), B=(4,0), C=(0,3));
    query=interior_integer_points
```

또는 더 간단한 형태:

```yaml
verify:
  answer_kind: geometric_discrete
  conditions: |
    polygon=((0,0),(4,0),(4,3),(0,3));
    query=boundary_points_count
```

### 2.5 검증기 동작

1. DSL 파싱 → `GridSpec`, `ShapeSpec`, `QuerySpec`.
2. 좌표 정수화/유리수화. 실수 근사는 허용하지 않음(정확 계산).
3. 질의에 따라 Pick 정리, 격자점 세기, 선분 교차 판정 등 결정론 알고리즘 실행.
4. 결과를 `answer`와 대조.

### 2.6 Cross-Verify v2 관점

| # | 관점 | 가시 필드 | 원리 |
|---|---|---|---|
| 1 | 독립 재구성 | 발문만 | 좌표/격자를 스스로 설정해 답을 재계산. 기계가 전수 값과 대조. |
| 2 | 적대적 반증 | 발문 + 답 | 도형 조건 누락, 특수 사례, 일반성 결여를 지목. |
| 3 | 좌표계↔발문 정합 | 발문 + 기계 산출 좌표/도형 설명 | 기계가 실제로 세고 있는 대상이 발문의 도형인지 번역 대조. |

---

## 3. 단계 A 후보 2: 통계 자료형 (`statistical_claim`)

### 3.1 개요

주어진 데이터 표(유한 표본)에 대한 평균·중앙값·분산·사분위수·상관계수·빈도 등을 검증. 데이터가 명시적으로 주어지면 전수 결정론 검증이 가능하다.

### 3.2 기계 검증 가능 축

- 평균, 중앙값, 최빈값, 분산, 표준편차, 사분위수, 범위.
- 주어진 자료에 대한 상관계수(피어슨/스피어만 — 플래그로 구분).
- 빈도표, 누적상대도수.

### 3.3 기계 불가 잔여 축

- **표본 추출 방법**: 주어진 자료가 모집단의 무작위 표본인지, 아니면 편의 추출인지.
- **자료 해석의 모호성**: "평균이 증가했다"는 주장이 자료만으로 인과를 함의하는지.
- **통계량 정의**: 분산을 `n`으로 나누는지 `n-1`로 나누는지 발문에 명시되어 있는지.
- **이상점 처리**: 이상점 포함/제외 여부.

### 3.4 DSL 문법 예시

```yaml
verify:
  answer_kind: statistical_claim
  conditions: |
    data=[12, 15, 18, 21, 24];
    query=mean
```

또는:

```yaml
verify:
  answer_kind: statistical_claim
  conditions: |
    x=[1,2,3,4,5];
    y=[2,4,6,8,10];
    query=pearson_correlation
```

### 3.5 검증기 동작

1. DSL 파싱 → `DataSpec`, `QuerySpec`.
2. 데이터를 정확 유리수(또는 `Decimal`)로 처리. 부동소수점 사용 금지. *(S4-58에서 `Fraction`으로 구현 착지 — §3.7)*
3. 질의에 따라 통계량을 결정론 계산.
4. 결과를 `answer`와 대조. 분산 정의(`n` vs `n-1`)는 DSL에 명시.

### 3.6 Cross-Verify v2 관점

| # | 관점 | 가시 필드 | 원리 |
|---|---|---|---|
| 1 | 독립 재계산 | 발문 + 자료 | 통계량을 스스로 재계산. 기계가 값과 대조. |
| 2 | 적대적 반증 | 발문 + 답 + 자료 | 자료 왜곡, 이상점 처리 누락, 통계량 정의 모호성 지목. |
| 3 | 자료↔발문 정합 | 발문 + 기계 산출 통계 설명 | 기계가 실제로 계산한 대상이 발문의 질문과 일치하는지 번역 대조. |

### 3.7 구현 DSL과 허용오차 정책 (S4-58)

§3.4의 예시(`query=`, `x=`/`y=`)는 설계 초안 표기이고, **구현된 DSL**은 `stat=`·`data=` 계열이다
(`src/backend/whymath_backend/l3/statistical_claim.py`).

```text
data=[1,2,4]; stat=mean; tolerance=round:2
data=[[1,1],[2,3],[3,2]]; stat=corr; columns=[0,1]
```

| 절 | 값 | 비고 |
|---|---|---|
| `data` | JSON 배열(1차원 또는 2차원) | 수는 float을 거치지 않고 정확 유리수(`Fraction`)로 읽는다. 최대 10,000점 |
| `stat` | `mean`·`median`·`variance`·`std`·`q1`·`q3`·`corr` | `corr`는 2차원 + `columns=[i,j]` |
| `columns` | 열 인덱스 배열 | 선택 |
| `variance_kind` | `sample`(기본, n-1)·`population`(n) | 선택 |
| `tolerance` | 아래 표 | 선택 |

**정확값 원칙.** 평균·중앙값·분산·사분위수는 유리수 정확값이다. 표준편차·상관계수는 제곱근이
유리수(완전제곱)일 때만 정확값이고, 아니면 정수 제곱근으로 만든 10^-60 이내 근사로 판정한다
(판정 해상도 한계 = 10^-60).

**허용오차 정책 (`tolerance`).** 주장값(`answer`)과 계산값을 비교하는 규칙을 문항 저자가 선언한다.

| 정책 | 통과 조건 | 비고 |
|---|---|---|
| `exact` | 주장값 == 계산값 | 계산값이 무리수면 `unverifiable`(대체 정책 안내) |
| `abs:<양수>` | \|계산값 − 주장값\| ≤ 양수 | 경계 포함 |
| `rel:<0~1 미만>` | \|계산값 − 주장값\| ≤ 비율 × \|계산값\| | 경계 포함. 계산값이 0이면 정확 일치 |
| `round:<0~15>` | 주장값 == 계산값을 소수 k자리로 반올림한 값 | half-up(0에서 먼 쪽), 정확 유리수 연산 |
| (생략) | 계산값이 유한소수면 `exact`, 무한소수·무리수면 `abs:0.000000001` | 결과의 `policy` 필드에 `기본→…`로 표기 |

- 기본 정책의 무한소수·무리수 쪽이 **절대오차만** 쓰는 이유: 상대오차를 섞으면 큰 값에서 허용 폭이 값에
  비례해 커진다(평균 1조에서 폭 1000). S4-53의 `rel_tol=1e-9` 비교가 이 결함을 가졌다.
- 정책 이름은 대소문자를 가리지 않는다. 철자가 틀린 절 이름(`tolerence=`)·중복 절·형식이 틀린 정책은
  **조용히 기본 정책으로 떨어지지 않고** `unverifiable`이다 — 검증 강도가 몰래 바뀌는 것을 막는다.

**입력 방어.** 다음은 `fail`로 위장하거나 예외로 터지지 않고 `unverifiable`로 돌아온다: `NaN`·`Infinity`,
`bool`·문자열·`null`, 길이 64자 초과 수 토큰, 지수 절댓값 30 초과(`1e999999999` 폭탄), 비 ASCII 숫자·밑줄
숫자(`1_000`), 공백으로 갈라진 숫자(혼합수 `1 1/2`가 `11/2`로 읽히던 오독), 분모 0, 깊은 중첩 JSON.

**교차검증 재계산 대조 (S4-70).** `StatisticalResult.value`(float)는 하위 호환용이며 판정에는 쓰지 않는다.
교차검증 관점 ④(`statistical_reconstruction`)는 한때 이 float을 `math.isclose(rel_tol=1e-9)`로 LLM
재계산값과 대조해 평균 1조에서 허용 폭이 1000으로 열렸다(대값 왜곡이 동형으로 잔존). 이제 기계값은
`StatisticalResult.exact_value`(유리수 정확값)·`approx_value`(10^-60 근사)로 `ResidueSubject.machine_exact`·
`machine_approx`에 실려 가고, LLM 재계산값은 `Fraction`으로 읽어(float은 LLM이 쓴 십진 표기 그대로)
선언 없는 기본 정책과 같은 규칙으로 대조한다 — 기계값이 유한소수면 정확 일치, 무한소수·무리수면 `abs:0.000000001`.
`ResidueSubject.machine_value`(float)는 정확 필드를 모르는 기존 소비자를 위해 남기며, 정확 필드가 없을 때만
절대오차 대조에 쓴다(float을 정확값으로 승격하면 올바른 `7/3`이 거부된다).

- 경계: 교차검증(CORE)은 수학 ADAPTER인 `statistical_claim`을 import할 수 없다(import-linter 계약).
  그래서 대조 정책은 `cross_verify.py`에 도메인 중립 최소 구현으로 자급하고, 두 정책이 어긋나지 않는 것은
  `tests/backend/l3/test_cross_verify.py`의 패리티 검사(`verify_statistical_claim`과 같은 입력 격자)가 잡는다.
- 한계: 문항이 선언한 `tolerance=` 절은 교차검증 대조에 전달하지 않는다(LLM은 원 통계량을 재계산할 뿐
  반올림 정책을 모른다). 표본분산 n=1이 0으로 계산되는 S4-53 동작은 보존했다(정의 불가 값).

---

## 4. 단계 B 도메인 1: 벡터 (`vector_algebra`)

> **판정(S4-57): 발화 보류 (NO-GO) · 우선순위 2.** 소비처가 없어서가 아니다. 소비처(코퍼스 400건)가 이미 Tier1 정수 연산 검산을 받고 있어, 이 도메인이 **새로 닫는 수치 축이 없기** 때문이다. 근거 §7.3, 재확인 지점 = `S4-67`.

### 4.1 개요와 범위 재정의

2022 개정 기하 과목의 벡터 단원 성취기준은 5개다(`data/corpus/standards_v1/standards.json`).

| 코드 | 성취기준 | 이 도메인의 처리 |
|---|---|---|
| `[12기하03-01]` | 벡터의 뜻을 알고, 벡터의 덧셈, 뺄셈, 실수배를 할 수 있다 | IN — 선형결합 |
| `[12기하03-02]` | 위치벡터의 뜻을 알고, 벡터와 좌표를 대응시켜 표현할 수 있다 | IN — 두 점 사이 벡터 |
| `[12기하03-03]` | 내적의 뜻을 알고, 두 벡터의 내적을 구할 수 있다 | IN — 내적·크기²·평행/수직·cos² |
| `[12기하03-04]` | 벡터를 이용하여 직선의 방정식을 구할 수 있다 | OUT — 답이 *방정식*이라 값 대조가 아니라 방정식 동치 판정 영역 |
| `[12기하03-05]` | 좌표공간에서 벡터를 이용하여 평면의 방정식과 구의 방정식을 구할 수 있다 | OUT — 위와 같음(+3차원) |

**외적(cross product)은 이 5개 어디에도 없다.** 종전 부록은 외적을 기계 검증 축으로 적었으나 교육과정·코퍼스 어느 쪽에도 소비처가 없어 제외한다(`verifier_v2_design.md` §0.3 원칙 5 "소비처 없는 설계 금지"). 영재·대학 모드가 외적 문항을 갖게 되면 그때 별도로 재판정한다.

### 4.2 기계 검증 가능 축 — 정확 산술

성분은 정수 또는 유리수(`p/q`)만 받고 `fractions.Fraction`으로 계산한다. 소수 표기와 부동소수점은 파서가 거부한다(§6.1 — 단계 A 구현이 부동소수점 비교를 쓴 결과 1만 틀린 정수 오답이 통과하는 구간이 실측됐다).

| `query` | 성취기준 | 계산 | v1 답 형태 |
|---|---|---|---|
| `combo_sum` | 03-01 | `expr`(선형결합) 결과 벡터의 성분의 합 | 유리수 — 코퍼스 400건의 답 형태 |
| `combo` | 03-01 | 결과 벡터 | 성분 튜플 |
| `vec_sum(A,B)` | 03-02 | `AB = B − A`의 성분의 합 | 유리수 |
| `vec(A,B)` | 03-02 | `AB = B − A` | 성분 튜플 |
| `dot(u,v)` | 03-03 | 내적 | 유리수 |
| `norm_sq(u)` | 03-03 | 크기의 제곱 | 유리수 |
| `is_parallel(u,v)` / `is_perpendicular(u,v)` | 03-03 | 평행(2D는 `u₁v₂ − u₂v₁ = 0`, 영벡터는 판정 불가) / 수직(내적 0) | 0 또는 1 |
| `cos_sq(u,v)` | 03-03 | `(u·v)² ÷ (크기(u)² × 크기(v)²)` | 유리수 |

답이 무리수(`√`, `arccos`)로 나오는 질의는 v1에서 **받지 않는다** — `unverifiable`(사유 명시)로 돌려보낸다. 크기·코사인 값 자체를 묻는 문항은 `norm_sq`·`cos_sq`로 환원되는 경우에만 대응하고, 그 환원이 발문의 질의와 같은지는 잔여 축이다.

### 4.3 기계 불가 잔여 축 (`residual_axes`)

- **발문↔좌표 정합** — DSL의 벡터·점이 발문의 대상과 같은가(성분 순서 `x,y`, 부호, `AB`와 `BA`).
- **질의 해석 정합** — 발문이 묻는 양('성분의 합' / '크기' / '내적')이 `query`와 같은가.
- **기저·좌표계 가정** — 발문이 직교좌표 기저를 암묵적으로 가정하는가.
- **방향 vs 평행 해석** — '같은 방향'과 '평행'(반대 방향 포함)의 구분.
- **단위** — 좌표에 길이 단위가 붙는 문항에 한정한다. 현 코퍼스 400건에는 단위 표현이 0건이다(실측) — 발화 시 재확인.

종전 부록의 축 이름은 그대로 쓰지 않는다. `residual_axes`는 자유 문자열이라 정본 어휘가 없고, 기존 확률 도메인의 축 이름에는 오타(`문발↔형식모델 정합`)가 코드·테스트에 고정돼 있다(§8 C8). 단계 B는 `<대상>↔<대상> 정합` 형식을 올바른 철자로 새로 쓴다.

### 4.4 DSL 문법

`verify.conditions` 문자열. 절은 `;`로 나누고 첫 `=`에서 키와 값을 가른다(`statistical_claim`·`finite_probability`와 같은 방식).

```text
conditions := clause (";" clause)*
clause     := NAME "=" "(" NUM ("," NUM){1,2} ")"      # 소문자 한 글자 = 벡터, 대문자 한 글자 = 점
            | "expr=" TERM (("+" | "-") TERM)*          # TERM := [NUM "*"] 소문자 한 글자
            | "query=" QUERY
NUM        := ["-"] DIGITS ["/" DIGITS]                 # 정수 또는 분수. 소수점은 파서가 거부한다
QUERY      := "combo" | "combo_sum"
            | "vec(" 대문자 "," 대문자 ")" | "vec_sum(" 대문자 "," 대문자 ")"
            | "dot(" 소문자 "," 소문자 ")" | "norm_sq(" 소문자 ")"
            | "is_parallel(" 소문자 "," 소문자 ")" | "is_perpendicular(" 소문자 "," 소문자 ")"
            | "cos_sq(" 소문자 "," 소문자 ")"
```

예시 (모두 자체 생성 코퍼스의 형태이며 값은 실측으로 확인했다).

```yaml
# 03-01 — 코퍼스 첫 건(a=(-6,-1), b=(6,-1), 4a-4b의 성분의 합 = -48)과 같은 문항
verify:
  answer_kind: vector_algebra
  conditions: |
    a=(-6,-1); b=(6,-1);
    expr=4*a-4*b;
    query=combo_sum
```

```yaml
# 03-02 — AB = B - A = (3,4), 성분의 합 = 7
verify:
  answer_kind: vector_algebra
  conditions: |
    A=(1,2); B=(4,6);
    query=vec_sum(A,B)
```

```yaml
# 03-03 — 내적 = 1*3 + 2*(-4) = -5
verify:
  answer_kind: vector_algebra
  conditions: |
    u=(1,2); v=(3,-4);
    query=dot(u,v)
```

파싱 규칙(전부 위반 시 `VectorAlgebraError`(`ValueError` 하위) → `unverifiable`, 조용한 통과 금지):

- 절 중복·미지 키·미정의 이름·성분 수 불일치·`expr`가 필요한 `query`에 `expr` 없음은 거부한다.
- `eval`·`sympify`를 쓰지 않는다. 정규식과 토큰 단위 직접 파싱만 쓴다(`statistical_claim`이 `json.loads`로 `eval`을 피한 선례와 같은 취지).
- 한도: 성분 절댓값 ≤ 10⁶, 정의된 이름 ≤ 8개, `expr` 항 ≤ 16개.
- 영벡터에 대한 `cos_sq`·`is_parallel`은 정의되지 않는다 → `fail`이 아니라 `unverifiable`.
- 답은 정수·`p/q`만 읽는다. 소수·`√` 포함 답은 `unverifiable`(사유: 무리수 답은 v1 범위 밖).
- 판정은 `Fraction` 정확 일치다. 허용오차는 없다.

### 4.5 Cross-Verify v2 관점 (K=3)

| # | `principle` | 가시 필드 | 판정 방식 |
|---|---|---|---|
| 1 | `vector_reconstruction` | `question_text` | LLM이 발문에서 벡터를 직접 읽어 질의량을 재계산하고, **기계가 `Fraction` 정확 일치로 대조** |
| 2 | `vector_falsification` | `question_text`, `answer` | 성분 순서·부호·`AB`↔`BA`·'성분의 합'↔'크기' 혼동·'같은 방향'↔'평행' 지목(라벨형) |
| 3 | `vector_grounding` | `question_text`, `machine_model_ko` | 기계가 계산한 대상("벡터 a=(−6,−1), b=(6,−1)에서 4a−4b의 성분의 합")이 발문의 대상과 같은지 번역 대조. 수치 계산 금지(라벨형) |

**통계 관점(`STATISTICAL_PERSPECTIVES`)과 다른 점은 의도적이다.** 통계 관점 ①은 `data`를 가시 필드에 넣는다 — 자료가 표 형태로 발문과 분리돼 주어지기 때문이다. 벡터는 성분이 발문 서술 안에 있다. ①에 DSL을 보여 주면 **"발문에서 벡터를 읽는 행위" 자체가 검증에서 빠진다** — 그 번역 오류가 잔여 축의 본체인데 그것을 가리게 된다. 그래서 ①은 발문만 본다. 설계서 §5.3의 `dimensional_sanity`(방향성·단위)는 K=3 밖의 선택 관점으로 두고 필요할 때 4번째로 붙인다.

프롬프트 자산은 `docs/prompts/l3_cross_verify.md` 정본에 `l3.cross_verify.vector_{reconstruct,falsify,grounding}_{system,user}` 6개를 추가한다(자산 ID 규약은 기존 `statistical_*`와 같다). 관점 ①의 판정기는 `Fraction` 정확 일치 판정기를 새로 쓴다 — 기존 통계 판정기(`_judge_stat_reconstruct`)는 `float`과 `math.isclose`를 쓰므로 재사용하지 않는다(§8 C4).

---

## 5. 단계 B 도메인 2: 수열 귀납 (`sequence_induction`)

> **판정(S4-57): 기계 축 발화 (GO) · 우선순위 1 → `S4-66`.** 잔여 축 Wilson 로트 게이트는 밴드가 52건 이상이 된 뒤다(§7.2 FC-4). 근거 §7.3.

### 5.1 개요와 범위 재정의

2022 개정 대수 과목의 수열 단원 성취기준은 7개다.

| 코드 | 성취기준 | 이 도메인의 처리 |
|---|---|---|
| `[12대수03-01]` | 수열의 뜻을 설명할 수 있다 | OUT — 수렴·발산 문항(코퍼스 48건)은 SymPy 소관(`geometric_convergence`·`series_converges`) |
| `[12대수03-02]` | 등차수열의 뜻을 알고, 일반항, 첫째항부터 제n항까지의 합을 구할 수 있다 | OUT — 폐형 일반항 문항이라 Tier1 `x − (식) = 0`으로 충분 |
| `[12대수03-03]` | 등비수열의 뜻을 알고, 일반항, 첫째항부터 제n항까지의 합을 구할 수 있다 | OUT — 위와 같음 |
| `[12대수03-04]` | ∑의 뜻과 성질을 이해하고, 이를 활용하여 문제를 해결할 수 있다 | OUT — 닫힌 합 공식 계산, Tier1이 처리 |
| `[12대수03-05]` | 여러 가지 수열의 첫째항부터 제n항까지의 합을 구하는 방법을 설명할 수 있다 | OUT — 위와 같음 |
| `[12대수03-06]` | 수열의 귀납적 정의를 설명할 수 있다 | **IN — 핵심 소비처** |
| `[12대수03-07]` | 수학적 귀납법의 원리를 이해하고, 이를 이용하여 명제를 증명할 수 있다 | OUT — 증명 영역. 코퍼스 0건 |

이 도메인이 닫는 것은 **귀납적 정의로 주어진 수열의 점화식을 실제로 실행**하는 축이다. 수학적 귀납법 증명(03-07)은 "모든 자연수 n"을 다루므로 유한 검산이 `pass`의 근거가 될 수 없다 — 이 도메인은 03-07에 대해 `pass`를 내지 않는다(반례 탐색 `boundary_case_probe`만 잔여 교차검증의 보조로 가능).

### 5.2 기계 검증 가능 축 — 정확 산술

정수는 파이썬 `int`, 유리수는 `fractions.Fraction`으로 계산한다. 부동소수점은 쓰지 않는다. 점화식 종류(v1)는 아래 네 가지다.

| 종류 | 형태 | 예 |
|---|---|---|
| 1단계 선형 | `a(n+1)=p*a(n)+q` (p, q 유리수. 등차는 p=1, 등비는 q=0) | `a(n+1)=2*a(n)+1` |
| 계차형 | `a(n+1)=a(n)+f(n)` (f는 n의 다항식) | `a(n+1)=a(n)+2*n+1` |
| 2단계 선형 | `a(n+2)=p*a(n+1)+q*a(n)+r` | `a(n+2)=a(n+1)+a(n)` |
| 홀짝 분기 | `if(n%2==0, 식1, 식2)` | `a(n+1)=if(n%2==1, a(n)+2, 2*a(n))` |

질의와 등급(등급은 `verification_tier.py`의 의미를 그대로 쓴다 — 현재 `Verifier.verify`는 등급을 한 값으로 고정하므로 반영은 §8 C3).

| `query` | 뜻 | 등급 | `pass`가 뜻하는 것 |
|---|---|---|---|
| `a(N)` | N번째 항 | `DETERMINISTIC_DATA` | 정의(초기항+점화식)가 완전하면 `a(N)`은 유일하게 확정된다 — 값 자체의 증명 |
| `S(N)` | 첫 N항의 합 | `DETERMINISTIC_DATA` | 위와 같음 |
| `terms(N)` | 첫 N항 목록 | `DETERMINISTIC_DATA` | 위와 같음(답이 목록) |
| `closed(식, upto=M)` | 폐형 `식`이 점화식 실행값과 시작 항부터 `M`까지 모두 일치하는가(0/1) | `FINITE_EXHAUSTIVE` | **n ≤ M 전수 일치**이지 "모든 n"이 아니다. 잔여 축 "모든 n에 대한 일반 주장"이 항상 남는다 |

`closed` 질의가 이 도메인의 존재 이유다. 현재 `[12대수03-06]` 30건은 발문에 점화식을 쓰고 `verify.conditions`에는 생성기가 계산한 폐형식을 싣는다(§7.1). 점화식과 폐형이 어긋나게 생성돼도 Tier1에서는 드러나지 않는다 — `closed` 질의가 그 정합을 처음 닫는다.

**자원 상한.** 점화식 실행은 폭주할 수 있다. `a(n+1)=a(n)^2`에 `a(1)=2`를 주면 항의 비트 길이가 매 단계 두 배가 되어 n=17에서 65,536비트를 넘는다(실측). 그러므로 단계 수 N ≤ 1000, 항 비트 길이 ≤ 65,536, 거듭제곱 지수 ≤ 64(0 이상 정수 리터럴), 식 노드 수 ≤ 64를 상한으로 두고, 초과는 `fail`이 아니라 `unverifiable`(사유 "범위 초과")로 돌려보낸다. `fail`로 돌리면 "정답이 틀렸다"는 거짓 신호가 된다.

### 5.3 기계 불가 잔여 축 (`residual_axes`)

- **발문↔점화식 정합** — DSL의 `init`·`rec`가 발문의 수열 정의와 같은 수열인가(계수·부호·`aₙ₊₁` 지정).
- **인덱스 시작점·초기항 완비성** — `a₀`부터인지 `a₁`부터인지, 2단계 점화에 초기항이 둘 다 주어졌는가.
- **모든 n에 대한 일반 주장** — `closed` 질의에서 **항상 남긴다**. `Verifier`는 잔여 축이 비어 있으면 완전 기계 `pass`로 처리하므로(`verifier.py:344-350`), 이 축은 `closed`에서 절대 비우지 않는다.
- **분기 조건 해석** — 홀짝 분기에서 `n`의 홀짝이 항 번호 기준인지 아닌지.

수렴·발산·극한은 이 도메인의 질의로 받지 않는다(파서가 거부) — SymPy 소관이다.

### 5.4 DSL 문법

```text
conditions := clause (";" clause)*
clause     := "start=" ("0" | "1")                      # 첫 항 번호. 생략하면 1
            | "init=" INIT ("," INIT)*                  # 초기항. 점화식 단계 수만큼 필요
            | "rec=" "a(n+" K ")=" EXPR                 # 점화식. K는 1 또는 2
            | "query=" QUERY
INIT       := "a(" INT ")=" NUM
EXPR       := 정수·분수 리터럴 / n / a(n) / a(n+1)(K=2일 때만)
              과 + - * / ^(지수는 0 이상 64 이하 정수 리터럴) 괄호, if(조건, 식1, 식2)
조건       := n%INT==INT | n%INT!=INT
QUERY      := "a(" INT ")" | "S(" INT ")" | "terms(" INT ")"
            | "closed(a(n)=" EXPR ", upto=" INT ")"
```

종전 부록의 예시 `sequence=a(n+1)=2*a(n)+1, a(1)=1; query=a(10)`는 폐기한다. 한 절에 `=`가 3개 들어가 "첫 `=`에서 키와 값을 가른다"는 규칙에서 값 파싱이 모호하다 — 절을 `init`·`rec`·`query`로 나눈다.

예시 (값은 모두 실측으로 확인했다).

```yaml
# 등차 점화 — 코퍼스 [12대수03-06] 문항과 같은 형태. a(12) = 7 + 11*6 = 73
verify:
  answer_kind: sequence_induction
  conditions: |
    init=a(1)=7;
    rec=a(n+1)=a(n)+6;
    query=a(12)
```

```yaml
# 2단계 점화(피보나치형) — a(10) = 55. 현 생성기는 1단계 점화(등차·등비)만 다루고
# 2단계·분기 점화는 "별도 검증 재료 필요"로 후속에 남겨 뒀다 — 이 도메인이 그 재료다
verify:
  answer_kind: sequence_induction
  conditions: |
    init=a(1)=1,a(2)=1;
    rec=a(n+2)=a(n+1)+a(n);
    query=a(10)
```

```yaml
# 점화식과 폐형의 정합 — n=1..12에서 모두 일치하면 1
verify:
  answer_kind: sequence_induction
  conditions: |
    init=a(1)=3;
    rec=a(n+1)=5*a(n);
    query=closed(a(n)=3*5^(n-1), upto=12)
```

```yaml
# 홀짝 분기 — 첫 6항 1, 3, 6, 8, 16, 18 이므로 S(6) = 52
verify:
  answer_kind: sequence_induction
  conditions: |
    init=a(1)=1;
    rec=a(n+1)=if(n%2==1, a(n)+2, 2*a(n));
    query=S(6)
```

식 평가의 구현 방식은 `S4-66`이 정한다. 단 `eval`·`sympify`는 쓰지 않고, 허용 노드 화이트리스트와 위 자원 상한을 둔다. 파싱 규칙은 §4.4와 같다(절 중복·미지 키·초기항 부족·질의 항 번호가 시작 항보다 작음은 거부, 답은 정수·`p/q`·목록만 읽고 허용오차는 없다).

### 5.5 Cross-Verify v2 관점 (K=3)

| # | `principle` | 가시 필드 | 판정 방식 |
|---|---|---|---|
| 1 | `sequence_reconstruction` | `question_text` | LLM이 발문의 초기항·점화식에서 질의 항/합을 직접 계산하고, **기계가 `Fraction` 정확 일치로 대조** |
| 2 | `sequence_falsification` | `question_text`, `answer` | 초기항 누락·인덱스 시작점(`a₀`/`a₁`)·점화식 오독·"모든 n" 과대 주장·분기 조건 반전 지목(라벨형) |
| 3 | `sequence_grounding` | `question_text`, `machine_model_ko` | 기계가 실행한 정의("초항 a₁=7, a(n+1)=a(n)+6, a(12)")가 발문과 같은 수열인지 번역 대조. 수치 계산 금지(라벨형) |

관점 ①이 발문만 보는 이유는 §4.5와 같다 — 발문에서 점화식을 읽는 번역이 잔여 축의 본체다. 프롬프트 자산은 `l3.cross_verify.sequence_{reconstruct,falsify,grounding}_{system,user}` 6개이고, 정확 일치 판정기는 §8 C4의 신규 판정기를 쓴다.

---

## 6. 도메인 선택 가이드 (단계 A)

| 기준 | 기하 이산형 | 통계 자료형 |
|---|---|---|
| 구현 난이도 | 중간(격자점 알고리즘) | 낮음(통계량 공식) |
| 잔여 축 복잡도 | 높음(도형 해석) | 중간(통계량 정의·표본 해석) |
| 코퍼스 준비도 | 중학교 기하/격자 문제 다수 | 개념형 코퍼스에 통계 자료 문제 확장 가능 |
| Cross-Verify v2 재사용성 | 확률과 유사(전수-발문 정합) | 확률과 유사(재계산-발문 정합) |
| 권장 | ✓ 단계 A 1순위 | ✓ 단계 A 2순위(구현이 더 쉬움) |

**권장**: 기하 이산형을 단계 A로 선정. 이유:
- `finite_probability`와 동일한 "유한 집합 전수" 패러다임을 공유해 `VerificationTier.FINITE_EXHAUSTIVE`의 의미가 일관된다.
- 잔여 축(도형 해석)이 풍부해 Cross-Verify v2의 도메인별 관점 설계를 검증하기 좋다.
- 통계 자료형은 DSL이 더 간단하므로 S4-52-2 또는 병렬 슬라이스로 빠르게 추가 가능.

### 6.1 실제 선정 결과와 §3.5의 어긋남 (S4-57 기록)

- **선정 결과**: 단계 A는 `statistical_claim`으로 구현됐다(S4-53, PR #874). 위 권장(`geometric_discrete` 1순위)과 다른 결과이며 선정 사유는 대장에 남아 있지 않다(S4-53 notes는 "최종 선택은 코퍼스 우선순위/소비처에 따름"까지만 적었다). `geometric_discrete`는 미착수다.
- **소비처**: 현재 `statistical_claim`을 `verify.answer_kind`로 쓰는 코퍼스 레코드는 **0건**이다(전체 14,034건 실측 — §7.1). 구현은 있으나 이를 쓰는 데이터가 아직 없다.
- **§3.5와의 어긋남**: §3.5는 "정확 유리수(또는 `Decimal`)로 처리, 부동소수점 사용 금지"라고 적었으나 구현(`l3/statistical_claim.py`)은 `float`으로 계산하고 `math.isclose(rel_tol=1e-9)`로 대조한다(`_TOL = 1e-9`, 66행). 교차검증 재계산 판정기(`cross_verify.py` 391행)도 같은 방식이다.

이 비교식이 값이 큰 구간에서 오답을 통과시키는지 실측했다. 점화식 `a(n+1)=2a(n)+1`, `a(1)=1`의 정확한 항을 정수 연산으로 구하고, 참값에 1만 더한 오답을 `math.isclose(rel_tol=1e-9, abs_tol=1e-9)`와 정수 일치로 각각 대조했다.

| 항 | 참값 | 오답(참값+1) | `isclose` 통과? | 정수 일치? |
|---|---|---|---|---|
| a(10) | 1,023 | 1,024 | 아니오 | 아니오 |
| a(30) | 1,073,741,823 | 1,073,741,824 | **예** | 아니오 |
| a(40) | 1,099,511,627,775 | 1,099,511,627,776 | **예** | 아니오 |
| a(50) | 1,125,899,906,842,623 | 1,125,899,906,842,624 | **예** | 아니오 |

1만 틀린 오답이 `a(30)`부터 통과한다. 이것은 통계 자료형의 실위험을 측정한 값이 아니라 **비교 방식이 값이 커지는 구간에서 무너진다**는 실측이다. 통계 도메인의 실위험 판정과 수정은 `S4-58`(`statistical_claim tolerance/exact value DSL 개선`)이 겨냥하는 문제이나, 2026-10-08 현재 `S4-58`의 `acceptance`가 비어 있어 범위가 확정되지 않았다. 단계 B 도메인은 이 비교식을 이어받지 않는다(§4.2·§5.2: 정확 일치만).

---

## 7. 단계 B 코퍼스 소비처·밴드 매핑과 우선순위 (S4-57 판정)

### 7.1 측정과 재현

판정 기준 main `c322bb9cb`, 대상 `data/corpus/problem_bank_*/problems.jsonl` 전체 14,034건(2026-10-08). 한 문항이 여러 성취기준 코드를 가지면 코드별로 중복 집계된다. 전체 14,034건 중 `verify.answer_kind`가 있는 레코드는 394건이며, `statistical_claim`·`vector_algebra`·`sequence_induction`은 **각각 0건**이다.

**표 A — 벡터 `[12기하03-0x]`**

| 코드 | 코퍼스 | 건수 | `verify.answer_kind` | `verification_tier` | `verify.conditions` 형태 |
|---|---|---|---|---|---|
| 03-01 | `problem_bank_vector_operations_v0` | 200 | 없음 | `machine_sampled` | `x - (…) = 0` |
| 03-02 | `problem_bank_vector_operations_v0` | 200 | 없음 | `machine_sampled` | `x - (…) = 0` |
| 03-03 | `problem_bank_conceptual_v0` | 24 | `dot_product_scalar` | 없음 | 쉼표 구분 4성분(`1,2,3,1`) |
| 03-04 | — | 0 | | | |
| 03-05 | — | 0 | | | |

03-03의 24건은 "두 벡터의 내적이 벡터인가"를 0/1로 묻는 **개념 판정**이다(`verify_dot_product_scalar` 독스트링). 내적을 *계산*하는 문항은 0건이다. `S4-31`이 이 성취기준을 "이미 커버"로 기록한 근거는 계산형이 아니다.

**표 B — 수열 `[12대수03-0x]`**

| 코드 | 코퍼스 | 건수 | `verify.answer_kind` | `verification_tier` | `verify.conditions` 형태 |
|---|---|---|---|---|---|
| 03-01 | `conceptual_v0` | 48 | `geometric_convergence` 24 · `series_converges` 24 | 없음 | 수렴 판정 입력 |
| 03-02 | `generated_v0` 105 · `rephrased_v0` 60 | 165 | 없음 | 없음 | `x - (…) = 0` |
| 03-03 | `generated_v0` 50 · `rephrased_v0` 30 | 80 | 없음 | 없음 | `x - (…) = 0` |
| 03-04 | `sequence_sigma_v0` | 100 | 없음 | `machine_sampled` | `x - (…) = 0` |
| 03-05 | `sequence_sigma_v0` | 32 | 없음 | `machine_sampled` | `x - (…) = 0` |
| 03-06 | `generated_v0` | **30** | 없음 | **없음** | `x - (폐형) = 0` |
| 03-07 | — | 0 | | | |

03-06의 30건은 발문에 점화식을 쓰고 `verify`에는 생성기가 계산한 폐형식을 싣는다. 실제 한 건:

- 발문: 수열 {aₙ}이 다음 조건을 만족시킨다. (가) a₁ = 7 (나) aₙ₊₁ = aₙ + 6 (n ≥ 1). a₁₂의 값을 구하시오.
- `verify.conditions`: `x - (7 + (12 - 1)*6) = 0`, 정답 `73`

Tier1(`verify_answer`)은 이 등식에 답을 대입할 뿐 발문의 점화식을 실행하지 않는다. 생성기가 점화식과 폐형을 어긋나게 쓰는 결함이 있어도 이 경로에서는 드러나지 않는다(`inductive_sequence_skeleton_generator.py` `_InductiveSkeleton.condition` — "점화식의 폐형을 그대로 공급"). 이 30건에는 `verification_tier`도 없다.

**재현 명령** (저장소 루트에서 실행. 출력은 위 표의 건수와 대조한다):

```python
# 코퍼스 전수에서 벡터·수열 성취기준 코드별 건수와 answer_kind·tier 분포를 센다 (재현용)
import collections
import glob
import json

# 벡터 5개, 수열 7개 성취기준 코드만 본다
want = {f"[12기하03-0{i}]" for i in range(1, 6)} | {f"[12대수03-0{i}]" for i in range(1, 8)}
rows = collections.defaultdict(collections.Counter)  # 코드 -> (코퍼스, answer_kind, tier) -> 건수
kinds = collections.Counter()  # 전체 코퍼스의 answer_kind 분포
total = 0
for path in sorted(glob.glob("data/corpus/problem_bank_*/problems.jsonl")):
    corpus = path.split("/")[2]
    for line in open(path, encoding="utf-8"):
        rec = json.loads(line)
        total += 1
        verify = rec.get("verify") or {}
        kinds[verify.get("answer_kind")] += 1
        for code in rec.get("achievement_standard_codes", []):
            if code in want:
                key = (corpus, verify.get("answer_kind"), verify.get("verification_tier"))
                rows[code][key] += 1
print("전체", total, "건 / answer_kind 있음", total - kinds[None], "건")
for code in sorted(want):
    print(code, sum(rows[code].values()), dict(rows[code]))
```

### 7.2 발화 조건 (확정)

종전 부록의 조건("코퍼스에 벡터 문제가 30문 이상 생기고…")은 *성취기준 단위*로 읽혀 개념 판정 24건과 계산형을 구분하지 못했다. 아래 5조건으로 대체한다. 도메인은 **다섯 조건을 모두 평가한 뒤** 판정한다.

| 조건 | 내용 | 왜 필요한가 |
|---|---|---|
| FC-1 소비처 실재 | 이 도메인이 검증할 **질의형**에 해당하는 코퍼스 문항이 30건 이상(성취기준 전체 건수가 아니라 질의형으로 센다). 30은 단계 A 파일럿 밴드(30~50문)와 같은 기준 | 소비처 없는 설계 금지(설계서 원칙 5) |
| FC-2 Tier1 비중복 | 이 도메인이 **새로 닫는 축**이 있다 — Tier1의 폐형 등식이 발문의 정의 관계(점화식 등)를 실행하지 않거나, 등급이 없거나 `machine_sampled`인 밴드에서 Tier1이 못 닫는 축을 닫는다. Tier1이 같은 수치 축을 같은 강도로 이미 닫고 있으면 불충족 | 새 모듈·프롬프트·등록 비용을 정당화하는 유일한 근거 |
| FC-3 구조 입력 공급 | DSL 입력이 생성기의 원시 파라미터(또는 저작 시점 구조 필드)에서 오고, 발문을 LLM으로 파싱한 결과가 아니다 | 발문→DSL 번역을 LLM이 하면 번역 오류가 기계 축 안에 숨는다. 그 번역이 곧 잔여 축 "발문↔DSL 정합"이다 |
| FC-4 게이트 통과 가능 크기 | 잔여 축 로트 게이트를 결함 0건으로 통과할 수 있는 표본 크기 n ≥ 52 (아래 표). 미달이면 기계 축은 발화해도 **로트 게이트는 대기** | 통과할 수 없는 게이트를 "게이트가 있다"로 세지 않는다 |
| FC-5 호환 선결 | §8의 해당 도메인에 걸린 항목이 구현 슬라이스에 포함됐거나 해소됨 | 등록 시점의 오동작·CI 적색 방지 |

**FC-4의 수치.** 게이트(`harness/residue_cross_verify_eval.py`)의 기본값은 `--max-defect-upper 0.05`, `--min-n 20`, 신뢰수준 0.95이고 상한은 저장소의 `wilson_upper_bound`(`harness/wilson.py`)로 계산한다. 결함 0건일 때:

| 표본 n | Wilson 95% 상한 | 기본 임계 0.05 |
|---|---|---|
| 20 | 0.1192 | 불통과 |
| 30 | 0.0827 | 불통과 |
| 40 | 0.0634 | 불통과 |
| 50 | 0.0513 | 불통과 |
| 51 | 0.0504 | 불통과 |
| 52 | 0.0495 | **통과** |
| 100 | 0.0263 | 통과 |

결함 1건을 허용하려면 n ≥ 87이 필요하다. 이는 `MEMORY.md`에 이미 기록된 사실(기본값 `--sample-n 30`·`--max-defect-upper 0.05`는 무결함 로트도 통과할 수 없는 조합, 상한 0.0827)과 일치한다. 따라서 30~50건 밴드로는 기본 임계를 통과할 수 없다 — `S4-56`의 완료 조건 ⑤("파일럿 코퍼스 30~50문으로 게이트 승격")는 임계를 명시적으로 바꾸거나 밴드를 52건 이상으로 키우지 않으면 충족할 수 없다.

### 7.3 도메인별 판정

| 조건 | `sequence_induction` | `vector_algebra` |
|---|---|---|
| FC-1 | ✔ 03-06 **30건**(경계값 — 정확히 기준선) | 부분 — 03-01/02 질의형 400건은 있으나 03-03 계산형은 **0건** |
| FC-2 | ✔ 점화식을 실행하는 검산이 없고 `verification_tier`도 없음 | ✘ 03-01/02 400건은 Tier1이 원시 파라미터에서 정수 연산을 이미 재계산한다(`vector_operations_skeleton_generator.py` 독스트링 "조건식을 원시 파라미터에서 그대로 재구성해 SymPy가 독립적으로 재계산"). 새로 닫는 수치 축이 없고, 남는 이득은 등급 표기(`machine_sampled`→`deterministic_data`)와 교차검증의 "발문↔좌표 정합"뿐이다 |
| FC-3 | ✔ `_InductiveSkeleton`(kind·first·step·term)을 직렬화하면 된다 | ✔ 원시 파라미터 dataclass(`_LinearComboSkeleton`·`_PositionVectorSkeleton`)가 있다 — 필드 구성은 구현 시점에 확인 |
| FC-4 | ✘ 30 < 52 — **로트 게이트는 대기**(2단계·분기 점화로 밴드가 커진 뒤) | ✘ 계산형 밴드가 없다 |
| FC-5 | 구현 슬라이스에 동반(§8) | 해당 없음(보류) |
| **판정** | **기계 축 GO** — 우선순위 1, `S4-66` | **NO-GO(보류)** — 우선순위 2, 재확인 지점 `S4-67` |

`vector_algebra` 보류의 핵심은 FC-2다. 400건의 템플릿 문항은 같은 원시 파라미터로 발문과 검산식을 함께 만들기 때문에, 이 도메인이 추가로 잡아낼 결함은 생성기 자체의 버그뿐이다. 그 이득은 새 모듈 1개·프롬프트 6개·등록·§8의 동반 정합 비용을 정당화하기에 약하다. 반대로 **내적 계산형 밴드(03-03)가 생기면** 사정이 달라질 수 있다(각도·크기 문항은 정답이 무리수로 나오는 경우가 많아 `x - (식) = 0` 형태의 Tier1 등식으로 옮기기 번거롭다) — 이 부분은 *추정*이며, 재판정은 밴드를 실제로 만든 뒤 FC를 다시 측정해서 한다(`S4-67`).

**효과 범위의 한계.** `sequence_induction` GO가 바꾸는 것은 저작·적재 시점의 기계 축 검산(`closed` 질의)과 이후의 로트 게이트다. 서빙 경로의 `pass`가 늘어나지는 않는다 — 운영 어댑터는 `cross_verifier` 없이 `Verifier()`를 쓰므로(`l4/subject_adapter_math.py:97`) 잔여 축이 있는 모든 `answer_kind`는 교차검증 없이 `unverifiable`로 회피된다(설계된 보수성).

### 7.4 우선순위 결정

| 순위 | 도메인 | 판정 | 태스크 |
|---|---|---|---|
| 1 | `sequence_induction` | 기계 축 GO, 로트 게이트는 밴드 ≥ 52 이후 | `S4-66` |
| 2 | `vector_algebra` | 보류. 03-03 계산형 밴드 확보 후 재판정 | `S4-67` |
| — | 외적 | 기각 — 교육과정 밖(소비처 0) | — |
| — | 수학적 귀납법 증명(03-07) | 기각 — "모든 n"은 유한 검산으로 `pass`를 낼 수 없다(코퍼스 0건) | — |
| — | 수렴·발산 문항(03-01) | 범위 밖 — SymPy 소관(기존 `geometric_convergence`·`series_converges`) | — |
| — | 직선·평면·구의 방정식(03-04/05) | 범위 밖 — 답이 방정식이라 동치 판정 영역(코퍼스 0건) | — |
| — | `geometric_discrete`(단계 A 잔여 후보) | 이 문서의 범위 밖 — 미착수 상태만 기록(§6.1) | — |

---

## 8. 도메인 verifier 플러그인 등록 인터페이스 하위호환 검토

### 8.1 현 인터페이스 사실 (main `c322bb9cb` 독해 기준)

- 통합 contract는 main에 구현돼 있다(`474bf918`, PR #871). 대장의 `S4-54` 행은 아직 `todo`이며 그 정리는 `S4-54` 소관이다.
- 도메인 verifier 시그니처: `DomainVerifier = Callable[[str, str], _DomainResult]` (`verifier.py:122`) — `(conditions, answer)`를 받는다. `_DomainResult`(106행)는 모듈 private이다.
- 등록은 **공개 `register()` API가 아니라 정적 조립**이다: `_build_verifiers_v2()`(264행)가 `statistical_claim`을 먼저 넣고 `_CONCEPTUAL_VERIFIERS`를 순회해 감싸 `_VERIFIERS_V2`(288행)를 만든다. 새 도메인은 이 함수를 직접 고쳐야 한다.
- 교차검증 관점은 별도 표 `_CROSS_VERIFY_PERSPECTIVES`(125행)이고, 조회는 `.get(kind, PROBABILITY_PERSPECTIVES)`(383행)다.
- 운영 호출처는 1곳이다: `l4/subject_adapter_math.py`의 `validate_problem`이 `Verifier.verify`를 부르며, 계약으로 넘기는 것은 `state`·`reason`·`machine_axes`·`residual_axes`뿐이다(`tier`·`audit_labels`는 의도적으로 비노출).

### 8.2 변경 없이 단계 B를 수용하는 것 (호환)

- `DomainVerifier` 시그니처. 단계 B 함수도 `(conditions, answer)`를 받아 `_DomainResult`를 돌려주면 된다.
- `VerificationVerdict` 필드와 어댑터 계약(`ProblemVerifyInput` 5필드·`ProblemValidation` 4필드). `answer_kind`·`conditions`는 Core에서 **불투명 문자열**이므로(EOS-85, `populate.py` 주석) 새 `answer_kind`가 L1·Core에 어휘 등록을 요구하지 않는다.
- 중복 키 가드. `_build_verifiers_v2`가 이미 있는 키를 만나면 `ValueError`를 던진다(278-279행) — 조용한 덮어쓰기가 아니라 import 시점 실패다.
- 후행 기본값 필드 추가. `ResidueSubject`·`_DomainResult`의 src 생성처가 전부 키워드 인자다(`verifier.py` 5곳, `residue_cross_verify_eval.py:212`, `residue_gate_demotion_battle.py:444`). 테스트 생성처는 구현 슬라이스가 기존 테스트 무변경 통과로 확인한다.

### 8.3 단계 B 착지 시 걸리는 지점

분류: **동반** = 첫 도메인 등록과 같은 슬라이스(`S4-66`)에서 처리. **정리** = `S4-68`. **후속** = 다른 태스크 이후.

| ID | 지점 | 읽은 사실 | 단계 B에 걸리는 이유 / 권고 | 분류 |
|---|---|---|---|---|
| C1 | `verifier.py:383` | 관점 조회가 fail-open — 키가 없으면 확률 관점으로 조용히 폴백. 개념형(SymPy) 15종도 잔여 축을 남기므로(230행) `cross_verifier`가 주입되면 확률 관점으로 갈 것으로 *읽힌다*(**미실행**) | 등록을 빠뜨린 도메인이 표본공간 가정 프롬프트로 검증된다. 권고: 키 부재는 `unverifiable(관점 미등록)`, 확률 관점은 `finite_*` 두 키에 명시 등록. 운영 어댑터는 `cross_verifier`를 주입하지 않아 운영 영향은 없고 `S4-56` 경로에서 발현 | 정리(`S4-68`) + 동반(자기 kind 명시 등록) |
| C2 | `verifier.py:119`, `cross_verify.py:123` | `machine_value`의 타입이 `float` 또는 `None` | 큰 정수 수열값(2⁵³ 초과)과 튜플 답(벡터)을 무손실로 못 싣는다. 권고: 후행 기본값 `machine_value_exact: str = ""` 추가(§8.2 호환), 기존 `machine_value` 경로(통계)는 유지 | 동반 |
| C3 | `verifier.py:313-406` | `Verifier.verify`가 `tier`를 상수로 고정(통과는 `MACHINE_EXHAUSTIVE`, 그 외 `MACHINE_SAMPLED`) | 도메인별 등급(`DETERMINISTIC_DATA` 등)을 표현할 수 없다. 권고: `_DomainResult`에 선택 필드 `tier`(기본값 `None`)를 추가하고 `None`이면 종전 상수를 쓴다. 어댑터 계약이 `tier`를 비노출하므로 Core 영향 0 | 동반 |
| C4 | `cross_verify.py:391`, `statistical_claim.py:66` | 재계산 대조가 `float` + `math.isclose` | §6.1 실측대로 정수 오답이 통과한다. 권고: `Fraction` 정확 일치 판정기를 신설하고 통계 판정기는 재사용하지 않는다. 통계 쪽 교정은 `S4-58` | 동반 |
| C5 | `qa_pipeline.py:319` | `_NON_EQUATION_DSL_ANSWER_KINDS`가 수동 목록 6종이고 `statistical_claim`이 **없다** | 등식 DSL 폐쇄 검사(축 2)가 비등식 DSL을 위반으로 센다. `statistical_claim`은 코퍼스 0건이라 **잠복**. 권고: 자기 kind 추가 + 목록을 v2 레지스트리에서 파생하거나 동기 테스트 | 동반(자기 kind) + 정리(`statistical_claim` 정정) |
| C6 | `populate.py:153` | `_VERIFICATION_TIER_VALUES`가 2값(`machine_exhaustive`·`machine_sampled`)이고 L3 `VerificationTier`는 9값 | 신규 등급을 `verify.verification_tier`로 찍은 레코드는 `ProblemCorpusError`로 적재가 거부된다(설계서 §6.2와 충돌). L1은 L3를 import할 수 없으므로 두 집합을 대조하는 테스트로 동기를 강제. 헌법 R6-02(스키마 변경은 과거 실제 데이터 호환 테스트) 적용 | 정리(`S4-68`) |
| C7 | `corpus_reverify.py:53`, `acceptance.py:121` | 야간 재검증의 디스패치 표가 `acceptance._CONCEPTUAL_VERIFIERS`(단일 정본, 17종)를 그대로 쓴다. `_VERIFIERS_V2`에만 있는 `statistical_claim`은 그 표에 없다 | v2 전용 kind는 야간 재검증에서 Tier1 경로로 떨어진다(**읽기 기준**). 표에만 등록하면 `_build_verifiers_v2`가 개념형 래퍼로 감싸 도메인의 잔여 축·관점이 사라지고, 빌더에 선등록까지 겹치면 중복 가드로 import 시 `ValueError`가 난다 — `finite_*`처럼 전용 분기가 필요. 권고: v2 레지스트리를 단일 원천으로 삼는 방향을 순환 import 검사와 함께 판정 | 정리(`S4-68`) |
| C8 | `verifier.py:137,183`, `test_verifier.py:83` | `residual_axes`는 자유 문자열. 확률 도메인의 `문발↔형식모델 정합`은 오타인데 코드·테스트·설계서(`verifier_v2_design.md:202`)에 고정 | 현재 `residual_axes`를 집계 키로 쓰는 코드는 어댑터 통과 외 확인하지 못했다(내가 찾은 방법으로 0건). 단계 B는 올바른 철자로 신설하고 기존 값은 바꾸지 않는다 — 집계 소비처가 생기면 어휘 등록부를 판정 | 정리(`S4-68`이 필요성만 판정) |
| C9 | `eos_core_adapter_boundary_scan.py:121-122`, `eos_feature_inventory_v2.py:819` | 신규 `l3.*` 모듈은 ADAPTER 분류와 인벤토리 귀속이 필요(`l3.statistical_claim` 선례) | 이 둘은 pytest가 아니라 CI `infra-contracts` 잡이 검사한다 — 빠뜨리면 pytest가 초록인 채 CI가 적색이다 | 동반 |
| C10 | `docs/prompts/l3_cross_verify.md`, `l3/prompt_assets.py` | 프롬프트는 정본 문서의 자산 ID로만 로드되고 없으면 `PromptAssetError`(fail-closed) | 관점마다 `system`·`user` 2개, 도메인당 6개를 정본에 추가해야 `prompt_text`가 통과한다. `prompt_asset_audit` 통과 필요 | 동반 |
| C11 | `residue_cross_verify_eval.py:65` | `_SUPPORTED_KINDS = {finite_probability, finite_count}` | 다른 kind는 `TIER_UNSUPPORTED`로 거부 — `S4-56`의 v2 CLI 이전에는 단계 B 로트 게이트를 돌릴 수 없다 | 후속(`S4-56`) |

### 8.4 판정

시그니처·결과 타입·어댑터 계약은 **변경 없이** 단계 B를 수용한다. 추가가 필요한 것은 후행 기본값 필드(C2·C3)뿐이다. 다만 C2·C4·C5·C9·C10은 첫 도메인 등록과 같은 슬라이스에서 처리하지 않으면 각각 정수 오답 통과, 등식 DSL 위반 집계, CI `infra-contracts` 적색, 프롬프트 자산 결측으로 나타난다. C1·C6·C7·C8은 `S4-68`이 맡고, C11은 `S4-56` 이후다.

이 검토의 한계: C1·C7의 거동은 코드를 읽어 도출한 것이며 실행으로 확인하지 않았다. `S4-68`의 첫 완료 조건이 그 실측이다.

---

## 9. 후속 슬라이스와 재확인 지점

| 태스크 | 내용 | 선행 | 우선순위 | 비고 |
|---|---|---|---|---|
| `S4-66` | `sequence_induction` 구현(DSL·정확 평가기·관점 3종·프롬프트 6개·동반 정합 C2~C5·C9·C10) | `S4-57` | P1 | 단계 B 1순위. 로트 게이트는 범위 밖 |
| `S4-67` | 03-03 내적·크기·평행수직 계산형 밴드 신설(≥52건) + `vector_algebra` 재판정 | `S4-57` | P2 | **보류의 재확인 지점** — 완료 시 §7.3을 다시 판정한다 |
| `S4-68` | `answer_kind` v2 소비 지점 드리프트 해소(C1·C5의 `statistical_claim` 정정·C6·C7·C8) | `S4-57` | P1 | `S4-66`과 `verifier.py`·`cross_verify.py`를 함께 건드리므로 병렬 착수 시 파일 겹침을 조율 |
| `S4-56` | (기존) Cross-Verify v2 CLI·Wilson 게이트 | `S4-53`·`S4-54` | P1 | 완료 조건 ⑤의 "30~50문 승격"은 기본 임계에서 통과 불가(FC-4) — 임계 변경을 명시하거나 밴드를 키워야 한다 |
| `S4-58` | (기존) `statistical_claim` tolerance/exact value DSL 개선 | `S4-53` | P1 | `acceptance`가 비어 있다. §6.1 실측을 입력으로 쓸 수 있다 |

**재확인 계약.** `vector_algebra`의 유예는 만료가 없으면 안 된다. 그 장치는 `S4-67`이다 — `S4-67`이 `done`이 되면 §7.3 재판정이 그 태스크의 완료 조건 ④로 강제된다. 이 문서의 코퍼스 수치는 판정 기준 커밋(`c322bb9cb`)에서만 유효하며, 코퍼스나 `l3/verifier.py`가 바뀐 뒤에는 §7.1의 재현 명령으로 갱신한다.
