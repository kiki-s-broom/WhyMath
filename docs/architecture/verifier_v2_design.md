# SymPy 불가 영역 검증기 v2 설계

> **문서 성격**: L3 콘텐츠 검증 계층의 다음 단계 설계서. `S4-13`(verifier v1 — 확률 유한 전수형)을 기반으로, verifier를 **통합 contract + 플러그인 도메인 검증기 + 영역별 잔여 교차검증** 구조로 확장한다.
>
> **한 줄**: 검증 권위 서열은 유지하되, 진입점·등급·잔여 처리를 통합하고 SymPy 불가 영역을 단계적으로 기계 검증覆盖한다.
>
> **정본 관계**:
> - 상위: `CLAUDE.md`(검증 권위 서열·7계층·LLM 안전), `docs/standards/superhuman_verification_standard.md`(6축).
> - 선행: `docs/architecture/problem_bank_gap_review.md` §3 D7(S4-13 설계 근거), `src/backend/whymath_backend/l3/verification_tier.py`, `src/backend/whymath_backend/l3/cross_verify.py`, `src/backend/whymath_backend/l3/finite_probability.py`.
> - 자매: `docs/architecture/verifier_v2_domains.md`(도메인별 DSL·잔여·관점).
> - 후속: 구현 슬라이스 태스크 `S4-52-1`~`S4-52-N`.

---

## 0. 왜 v2인가

### 0.1 v1이 확립한 것

`S4-13`은 SymPy 불가 영역 중 **확률 유한 전수형**에 대해 기계 검증 경로를 만들었다.

- 기계 가능 축: `finite_probability.py`가 표본공간을 전수 열거해 정확 유리수로 검증. 이 축은 그 형식 모델 위에서는 증명에 준한다.
- 기계 불가 잔여: 발문 ↔ 형식모델 정합, 등확률 가정 타당성 등은 `cross_verify.py`의 K=3 독립 다관점 LLM 교차검증 + Wilson 표본 검수 게이트가 로트 단위로 본다.
- 등급: `verification_tier.py`가 `MACHINE_EXHAUSTIVE`/`MACHINE_SAMPLED` 2종으로 "수치 축이 어떻게 검산됐는가"를 코퍼스 메타에 명시.

### 0.2 v1의 구조적 한계

| 한계 | 영향 | v2 대응 |
|---|---|---|
| 도메인 한정 — 확률/경우의 수 외 기하·벡터·통계·수열·귝명은 기계 검증 경로 부재 | K-12 커버리지가 대수·확률에 갇힘 | 도메인 verifier 플러그인 확장(§3) |
| 진입점 분산 — `verify_answer`(Tier1)·`finite_probability`(도메인 프리미티브)·`cross_verify`(잔여)가 별개 | 호출부가 도메인을 직접 판단해야 함 | 통합 `Verifier` contract(§2) |
| 등급 2종만 — `MACHINE_EXHAUSTIVE`/`MACHINE_SAMPLED`가 영역별 잔여 특성을 표현 못 함 | 하류 게이트가 "무엇이 증명됐고 무엇이 안 됐는가"를 세분화 못 함 | Tier 개편(§4) |
| 잔여 게이트가 확률 전수형만 지원 | 다른 영역의 교차검증은 관점·프롬프트·판정기 미정의 | Cross-Verify v2(§5) |

### 0.3 설계 원칙(불변)

1. **검증 권위 서열 유지**: ① 기계 증명 ② 측정 통과 기계 게이트 ③ 인간 폴백.
2. **SymPy 단일 권위**: 기존 `verify_answer`/`verify_solution`이 담당하는 기호/수치 축은 그대로 둔다.
3. **LLM 응답 검증 전 학생 노출 금지**: 모든 LLM 교차검증은 라우터 경유 + Langfuse 추적.
4. **신규 필드 최소**: 스키마 변경은 `verification_tier` 확장 외 최소화.
5. **소비처 없는 설계 금지**: 각 도메인 확장은 실제 코퍼스 밴드/소비처와 함께 발화 조건을 명시.

---

## 1. v2 아키텍처 개요

```
ProblemDSL (또는 verify 절 + answer + answer_kind)
         │
         ▼
┌─────────────────────────────────────┐
│  Unified Verifier Contract (l3/verifier.py)  │
│  • answer_kind → domain verifier 디스패치    │
│  • 기계 검증 결과 + 잔여 축 식별              │
└─────────────────────────────────────┘
         │
    ┌────┴────┬────────────┬─────────────┐
    ▼         ▼            ▼             ▼
 Symbolic   Domain       Residue        Human
 Verifier   Verifier     Cross-Verify   Fallback
(Tier1/2)  (new)         (v2)           (undecidable)
    │         │            │
    └────┬────┘            │
         ▼                  │
   VerificationVerdict      │
   (state + tier + axes)    │
                            │
         ┌──────────────────┘
         ▼
   Audit / Wilson Gate / is_exposable
```

### 1.1 핵심 변화

- **단일 진입점**: `verify(problem) -> VerificationVerdict`.
- **도메인 verifier 플러그인**: `answer_kind` → 등록된 도메인 verifier. 기존 `finite_probability`/`finite_count`는 그대로 유지.
- **잔여 축 중심**: 검증 결과는 단순 pass/fail이 아니라 "어떤 축이 기계로 증명됐고, 어떤 잔여 축이 남았는가"를 든다.
- **Cross-Verify v2**: 도메인별 관점 템플릿. 확률형 그대로 재사용 + 기하/벡터/통계용 신규.

---

## 2. 통합 Verifier Contract

### 2.1 인터페이스 (스켈레톤)

```python
# src/backend/whymath_backend/l3/verifier.py (stub)
class VerificationVerdict(BaseModel):
    state: Literal["pass", "fail", "unverifiable"]
    tier: VerificationTier
    residual_axes: tuple[str, ...]          # 기계가 닫지 못한 축
    machine_axes: tuple[str, ...]         # 기계가 닫은 축
    reason: str | None = None
    audit_labels: list[str] = Field(default_factory=list)

class Verifier:
    def __init__(self, *, cross_verifier: CrossVerifier | None = None) -> None: ...

    async def verify(self, problem: ProblemDSL) -> VerificationVerdict: ...
```

### 2.2 처리 흐름

1. **저작권/생성 방식 사전 검사**: `is_exposable` 전 단계. 본 contract는 검증에만 집중.
2. **`answer_kind` 디스패치**:
   - 기존 값(`real_root_count`, `extremum_count`, `finite_probability`, ...) → `_CONCEPTUAL_VERIFIERS` 그대로.
   - 신규 값(`geometric_discrete`, `vector_algebra`, `statistical_claim`, ...) → 도메인 verifier v2.
3. **기계 검증 실행**:
   - 도메인 verifier가 `AnswerVerdict`(pass/fail/unverifiable) + `machine_axes` 반환.
   - fail이면 즉시 `VerificationVerdict(state="fail")`.
4. **잔여 축 식별**:
   - 도메인 verifier가 "발문↔형식모델 정합", "등확률 가정", "단위/차원" 등 남은 축을 보고.
   - unverifiable이면서 잔여 축이 없으면 → `unverifiable`.
5. **잔여 교차검증(Cross-Verify v2)**:
   - 잔여 축이 있으면 도메인별 관점으로 K≥3 교차검증.
6. **집계**:
   - 기계 pass + 잔여 교차검증 ok → `state=pass`, tier=해당 등급.
   - 기계 pass + 교차검증 defect → `state=fail`.
   - 기계 pass + 교차검증 unresolved → `state=unverifiable`.

### 2.3 계층 규칙

- `l3/verifier.py`는 L3 내부 모듈만 호출(`verify_answer`, `finite_probability`, `cross_verify`, `verification_tier`).
- L4는 `l3/verifier.py`만 호출. 역방향 의존 금지(import-linter).
- `ProblemDSL`은 `schema/problem.py`의 `Problem`을 직접 받지 않고, 검증에 필요한 최소 필드(`verify`, `answer`, `answer_kind`, ...)만 노출.

---

## 3. 도메인 Verifier 플러그인 확장

### 3.1 플러그인 등록 구조

```python
DomainVerifier: Callable[[str, str], tuple[AnswerVerdict, tuple[str, ...]]]
# (conditions, answer) -> (verdict, residual_axes)

_VERIFIERS_V2: dict[str, DomainVerifier] = {
    "finite_probability": _wrap_finite_probability,   # 기존 유지
    "finite_count": _wrap_finite_count,               # 기존 유지
    # 신규(단계 A 우선순위)
    "geometric_discrete": _verify_geometric_discrete, # 설계 후 구현
    "statistical_claim": _verify_statistical_claim,   # 설계 후 구현
    # 신규(발화 조건)
    "vector_algebra": _verify_vector_algebra,
    "sequence_induction": _verify_sequence_induction,
}
```

### 3.2 단계 A — 실증 도메인 1개 선정

두 후보 중 **하나**를 S4-52-1 구현 슬라이스로 선정(이 설계서는 둘 다 후보로 기술, 최종 선택은 코퍼스 우선순위/소비처에 따름):

- **기하 이산형(`geometric_discrete`)**: 평면격자·정다각형·격자점·선분 교차·도형 내 정수점 등 "세기" 기반 기하. 전수 열거 가능.
- **통계 자료형(`statistical_claim`)**: 주어진 데이터 표(유한 표본)에 대한 평균·중앙값·분산·사분위수·상관계수 검증. 데이터가 주어지면 전수 결정론.

자세한 DSL 문법·잔여·관점은 `verifier_v2_domains.md` §2~§3 참조.

### 3.3 기존 도메인과의 경계

- 기존 `_CONCEPTUAL_VERIFIERS`에 등록된 `answer_kind`는 그대로 동작. `Verifier.verify()`는 이들을 래핑해서 `VerificationVerdict`로 변환.
- 신규 `answer_kind`는 `_VERIFIERS_V2`에 등록. 중복 키는 금지(구성 시점 `ValueError`).

---

## 4. Verification Tier 개편

### 4.1 등급은 "증명된 축의 집합"

기존 2종은 너무 거칠다. v2는 등급을 **증명된 축의 집합**으로 세분화하지만, 하위호환을 위해 기존 값은 alias로 유지.

```python
class VerificationTier(str, Enum):
    # 기존 값(legacy alias)
    # NOTE: v1 이름이지만 의미는 "유한 전수 열거"에 한정. SymPy 증명/데이터 전수를
    # 포함하는 상위 alias로 확대하지 않는다(Codex P2 피드백).
    MACHINE_EXHAUSTIVE = "machine_exhaustive"   # FINITE_EXHAUSTIVE의 legacy alias
    MACHINE_SAMPLED = "machine_sampled"           # NUMERIC_SAMPLING의 legacy alias(단일 매핑 — STATISTICAL_ESTIMATE는 alias 대상이 아님)

    # 신규 — 기계 증명/결정론
    FINITE_EXHAUSTIVE = "finite_exhaustive"     # 유한 집합 전수 열거(확률·기하 이산·통계 자료)
    SYMBOLIC_PROOF = "symbolic_proof"           # SymPy 동치·형식 증명
    DETERMINISTIC_DATA = "deterministic_data"   # 주어진 유한 데이터 전수 검증

    # 신규 — 기계 측정
    NUMERIC_SAMPLING = "numeric_sampling"         # Tier1 난수 샘플링
    STATISTICAL_ESTIMATE = "statistical_estimate" # 통계적 추정(신뢰구간 등)

    # 신규 — 잔여 검증
    RESIDUE_REVIEWED = "residue_reviewed"       # LLM 교차검증 + Wilson 게이트 통과 로트
    HUMAN_REVIEWED = "human_reviewed"           # 인간 폴백 완료
```

### 4.2 alias 처리

- `read_verification_tier()`는 레거시 값을 신규 등급으로 해석한다. 입력이 문자열이든 `VerificationTier` 멤버든 같은 규칙이다(S4-72 이전에는 멤버 입력만 alias를 건너뛰었다): `MACHINE_EXHAUSTIVE` → `FINITE_EXHAUSTIVE`, `MACHINE_SAMPLED` → `NUMERIC_SAMPLING`. 레거시 문자열 1개는 멤버 1개로만 해석되므로 `STATISTICAL_ESTIMATE`는 alias 대상이 아니라 신규 생산자가 직접 각인하는 등급이다. SymPy 증명/데이터 전수는 별도 등급을 부여받으므로 레거시 값에서 추론하지 않는다.
- `stamp_verification_tier()`는 신규 생산자가 신규값을 찍는다는 전제로 설계됐다(의도). 코드는 이를 강제하지 않고 받은 멤버를 그대로 기록한다 — 레거시 멤버도 거부하지 않는다. 현재 생산자 33개 파일이 레거시 멤버를 직접 찍고 있으며, 신규값으로의 전환은 첫 신규 값 생산자(S4-54·S4-56)의 몫이다. 기존 코퍼스는 마이그레이션 없이 alias로 그대로 읽힌다.
- 어떤 값도 "학생 노출 자격"을 단독으로 주지 않는다. 노출 판정은 두 독립 축이며 합치지 않는다 — `is_exposable`(`l6/_shared.py`, 저작권 출처 `METADATA_ONLY_SOURCES`만 본다)과 `is_review_cleared`(`l6/_shared.py`, `review_status` 검수 축). 호출부가 각각 독립된 `if`로 확인한다.

### 4.3 잔여 축 표현

`VerificationVerdict.residual_axes`는 문자열 튜플. 예:

- 확률: `("문발↔형식모델 정합", "등확률 가정")`
- 기하 이산: `("발문의 도형 조건 해석", "좌표계 가정")`
- 통계: `("표본 추출 방법", "자료 해석의 모호성")`

---

## 5. Cross-Verify v2

### 5.1 핵심 보존

- K≥3, 원리·프롬프트·가시 필드 독립성.
- 생성자≠검증자(`authored_by` 서명 충돌 거부).
- 집계: 만장일치 ok만 통과, 결함 지목은 다수결로 덮이지 않음.

### 5.2 도메인별 관점 템플릿

| 도메인 | 관점 1 | 관점 2 | 관점 3 |
|---|---|---|---|
| 확률(기존) | 독립 재구성(기계 판정) | 적대적 반증 | 서술-형식모델 정합 |
| 기하 이산 | 독립 재구성(격자점/변/면 수) | 적대적 반증(도형 조건 누락) | 좌표계↔발문 정합 |
| 통계 자료 | 독립 재계산(표에서 통계량) | 적대적 반증(자료 왜곡·이상점) | 자료↔발문 정합 |
| 벡터 | 독립 재계산(내적/외적/스칼라) | 적대적 반증(방향/단위 누락) | 좌표↔발문 정합 |

### 5.3 새 관점 유형

- `translation_consistency`: 발문의 한국어 서술과 형식 모델/자료/좌표가 같은 대상을 뜻하는지.
- `dimensional_sanity`: 단위·차원·순서쌍/벡터 방향성이 발문과 모순되지 않는지.
- `boundary_case_probe`: 경계값·퇴화 경우(예: 변 길이 0, 공집합 사건)에 발문이 여전히 유효한지.

### 5.4 출력

```python
class CrossVerifyReport:
    aggregate: Literal["ok", "defect", "unclear"]
    verdicts: list[PerspectiveVerdict]
    defect_class: str
    reason: str
    residual_axes: tuple[str, ...]
```

---

## 6. 감사·게이트 인프라

### 6.1 `residue_cross_verify_eval` 확장

- 입력: 코퍼스 경로 + `--domain geometric_discrete|statistical_claim|...`.
- 도메인별 `sample_n`, `max-defect-upper`, `min-n` 기본값.
- 기계 축 전수 재검증 → 잔여 축 표본 Wilson 검수.
- 산출: `audit.jsonl` + `as_found` 병기 + exit 0/1.

### 6.2 코퍼스 메타 확장

새 코퍼스/밴드 등록 시 다음 필수 메타:

- `verify.verification_tier`: 신규 등급.
- `verify.residual_axes`: 남은 축 목록(빈 배열 가능).
- `verify.domain`: `finite_probability`, `geometric_discrete`, `statistical_claim` 등.

### 6.3 CI 연동

- `backend` 잡에 `python -m whymath_backend.harness.residue_cross_verify_eval_v2 --dry-run` 추가(설계 단계에서는 dry-run).
- S4-52-1 구현 후 실제 파일럿 코퍼스(30~50문)로 게이트 승격.

---

## 7. 하위 슬라이스 분할안

S4-52 본 태스크는 **설계 전용**. 구현은 아래 슬라이스로 분할하여 별도 세션/브랜치에서 진행.

| 하위 태스크 | 내용 | 선행 |
|---|---|---|
| S4-52-1 | 단계 A 실증 도메인 구현: `geometric_discrete` **또는** `statistical_claim` DSL + verifier + 교차검증 관점 | S4-52 |
| S4-52-2 | `l3/verifier.py` 통합 contract 구현 및 기존 `_CONCEPTUAL_VERIFIERS` 연동 | S4-52 |
| S4-52-3 | `verification_tier.py` tier 개편 및 alias 처리 + 기존 코퍼스 읽기 하위호환 | S4-52 |
| S4-52-4 | `residue_cross_verify_eval` v2 CLI 확장 + 파일럿 코퍼스 30문 Wilson 게이트 | S4-52-1, S4-52-2 |
| S4-52-5 | 단계 B 도메인(`vector_algebra`, `sequence_induction`) 발화 조건 확정 및 설계 | S4-52-1 완료 후 |

---

## 8. 결정 사항 요약

- **통합 verifier contract**를 도입해 진입점을 단일화한다.
- **도메인 verifier 플러그인**으로 확률 외 영역을 단계적으로覆盖. 단계 A는 기하 이산 또는 통계 자료 중 1개를 실증.
- **Verification tier**를 "증명된 축의 집합"으로 개편하되 기존 값은 alias로 유지.
- **Cross-Verify v2**로 도메인별 잔여 교차검증 관점을 확장.
- **구현은 별도 하위 슬라이스**로 분할 — S4-52는 설계 문서와 contract 스켈레톤만 산출.
