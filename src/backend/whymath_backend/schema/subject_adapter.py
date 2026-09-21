"""SubjectAdapter — EOS Core가 과목에 요구하는 최소 행위 계약 (EOS-66 · Subject Contract v1).

## 🚧 상태: **Provisional** — pending cross-subject probe (9/27)

**이 계약은 확정(Frozen)이 아니다.** v1의 메서드와 필드는 전부 **Math 단일 과목에서 도출**됐다.
한 과목만 보고 "과목 중립"이라고 부르는 것은 관찰이 아니라 **가설**이다 — 실제로 다른 과목을
얹어 보기 전까지는 어느 필드가 중립이고 어느 필드가 수학의 흔적인지 아무도 모른다.
(부재 판정: 2026-09-05 역할 기반 검색으로 `docs/`·`backlog/`에서 교차 과목 프로브 **0건** —
이 계약은 지금까지 반증 시도를 한 번도 통과한 적이 없다.)

해제 조건 = **교차 과목 프로브**(`EOS-92`, 9/27 G1 게이트일). Physics 문항으로 아래 3메서드와
DTO 4종의 **모든 필드**를 실제로 채워 보고, 채우지 못하거나 의미가 뒤틀리는 필드를 가려낸다.

### 프로브 결과 처리 규칙 3조 (Kiki 지시 2026-09-05 · 협상 불가)

> **(가) 프로브에서 깨진 필드는 무조건 Core→Adapter 강등한다.**
> 유지·조건부 유지·"물리만 예외"·"기본값을 주면 된다" — **전부 없다.** 한 과목에서 깨졌다는
> 것은 그 필드가 과목 중립이 아니라는 **증명**이며, 중립이 아닌 것은 정의상 Core에 있을 수
> 없다. 강등처는 선택층(`verification_capabilities.py`) 또는 어댑터 내부다.
>
> **(나) Core 확장 금지.**
> 프로브가 "Physics에는 이런 게 더 필요하다"를 발견해도 **필수층에 넣지 않는다.** 새 능력은
> 전부 선택층 또는 어댑터 내부로 간다.
>
> **(다) 강등도 확장도 불가능한 결함(✗ 판정)은 ADR에 기록하고 2027 백로그로 이월한다.**
> v1에서는 **Adapter 중복 구현을 허용**한다. ✗가 **3건을 초과하면 프로브를 중단**하고
> "수학 전용 계약임을 인지한 상태"로 예정대로 Freeze한다.
>
> (다)가 필요한 이유: 교과 간 선수관계(예: 물리 '등가속도 운동'의 선수가 수학 '이차함수')처럼
> **Core의 지식 그래프가 과목 간 간선을 지원해야 풀리는** 결함은 Adapter로 내릴 수 없다.
> 그런데 (나)로 확장까지 막혀 있으면 프로브가 그것을 발견해도 취할 조치가 없고, 그때
> 반드시 편법이 나온다 — 필드를 안 늘리고 **기존 필드의 의미를 넓히는** 우회로. 그 우회로는
> 아래 "래칫의 한계" 때문에 CI를 통과한다. 출구가 없는 금지는 위반을 숨길 뿐이다.
> **중복 구현이 잘못된 추상화보다 낫다.**

세 조항의 귀결: **이 계약은 프로브를 거치며 줄어들 수만 있다(단조 축소·monotonic shrink).**
확장 경로는 (다)뿐이고 (다)는 Core를 바꾸지 않는다(ADR + 이월 + 어댑터 중복). 그래서
"Physics를 지원하려다 Core가 비대해지는" 실패 방식이 구조적으로 닫힌다.

### ⚠ 래칫의 한계 — 기계는 **필드 개수**만 본다

집행 테스트는 DTO의 **필드 집합**을 동결한다. 그것이 잡는 것은 *구조적* 확장(필드 추가)뿐이다.
**의미적 확장은 잡지 못한다** — `conditions`는 그대로 두고 그 안에 물리 관계식을 넣거나,
Core 코드가 `answer_kind` 값을 읽어 분기하기 시작하는 것은 필드 개수가 안 변하므로 CI가
초록이다. 그런데 과목 중립성이 실제로 깨지는 **주된 경로가 바로 이쪽**이다.

그러므로 **9/27에 "CI가 초록이니 계약이 지켜졌다"고 판단하면 안 된다.** CI 초록은 "필드를
늘리지 않았다"까지만 말한다. Core가 불투명 페이로드를 해석하는 코드는
`eos_core_adapter_boundary_scan.py`(정적 import 축)로는 잡히지 않는다.

**해석 축의 기계 집행은 `ARCH-43`가 세웠다(2026-09-06).**
`scripts/analysis/eos_opaque_payload_gate.py`가 CORE 배정 모듈(`BOUNDARY_MAP` 재사용)에서
`answer`·`answer_kind`·`conditions`(아래 "불투명 페이로드 원칙" 절에서 기계로 파생)의 **값**을
리터럴 비교·어휘 집합 대조·조회 키·`match`·문자열 파싱에 쓰는 자리를 AST로 잡고,
`tests/infra/test_eos_opaque_payload_gate.py`가 위반 6종 **주입 RED**와 기준선 동결(현행 1건 =
`l1.problem_bank.populate`, `EOS-85` 소유)로 집행한다. **한계(있는 척 금지)**: 이름 기반·정적·
별칭 한 단계라 `getattr`·함수 경유·런타임 프롬프트 조립은 못 본다. 그리고 잡는 것은 *Core가
값을 읽는가*(해석 축)뿐이다 — *뜻이 뒤틀리는가*(의미 축 · `EOS-92` 프로브 §3 갈래 B)는 여전히
사람 판정이다.

**의미 축의 검증 책임은 `EOS-92`에 있다.** 기계가 못 보는 갭에 소유자가 없으면 "알려진 결함·
소유자 없음" 상태가 된다. `EOS-92`는 "채우지 못하거나 **의미가 뒤틀리는** 필드를 가려내는"
태스크로 정의돼 있으므로, 의미 뒤틀림의 검출은 그 프로브의 판정표가 **보상 통제**
(compensating control)로 담당한다.

### 왜 Frozen이 아니라 Provisional인가

Frozen은 *바뀌지 않는다*는 약속이고, 그 약속은 **검증된 것에만** 할 수 있다. v1은 기계 동결이
걸려 있어(아래 2층 절) 조용히 바뀌지는 않지만, 그 동결은 "확장을 막는 장치"이지 "내용이
옳다는 증거"가 아니다. **동결됐다는 사실과 옳다는 사실을 혼동하면**, 반증되지 않은 가설이
동결의 권위를 빌려 정설이 된다. 그래서 상태 라벨은 프로브 통과 전까지 Provisional이다.

집행: `tests/backend/schema/test_subject_adapter_two_tier_contract.py` — 상태 라벨·규칙 3조·
필드 집합을 기계가 잡는다. **필드 확장은 무조건 RED**, 축소는 강등 대장(`DEMOTED_FIELDS`)
경유로만 통과한다. 프로브 없이 이 상태를 되돌리면 RED. **의미적 확장은 못 잡는다**(위 한계 절).

계획서 100 §3.9의 원칙: **과목마다 반드시 존재하는 능력만 계약에 넣는다.** `evaluateAnswer()`는
공통성이 높지만 `renderEquation()`은 Math 전용이므로 계약이 아니다. 이 모듈은 그 선을 코드로
긋는다 — Core는 여기 정의된 것만 알고, 수학이 어떻게 그것을 하는지는 모른다.

## 왜 `schema`에 사는가

`schema`는 import-linter 7계층 계약의 **최하위**다(어느 계층도 import하지 않는다). 계약이
`l3`/`l4`를 참조하면 Core가 다시 Adapter를 알게 되므로, 계약은 순수 타입만으로 성립해야 한다.
그래서 이 파일은 `l3.verifier.VerificationVerdict` 같은 기존 결과 타입을 **재사용하지 않고**
중립 등가물을 따로 둔다. 그 변환이 곧 어댑터의 일이다(`l4.subject_adapter_math`).

## 불투명 페이로드 원칙

`answer_kind`·`conditions`·`answer`는 **과목이 정의하고 Core는 해석하지 않는 불투명 문자열**이다.
Core가 "이 문자열은 이차방정식"임을 알게 되는 순간 경계가 무너진다(계획서 100 §3.7의
`if problem.type == "quadratic"` 금지). 반대로 문자열 자체는 과목 중립이다 — Physics 어댑터는
같은 필드에 물리 관계식을 담고 자기 방식으로 해석한다.

## 🔑 계약은 **2층**이다 — 이 파일은 그중 **필수층**이다

> **이 절을 읽지 않고 아래 Protocol에 메서드를 추가하지 말 것.** 여기에 추가하는 것은
> "모든 과목이 반드시 제공해야 한다"는 선언이며, 되돌리기 어렵다.

**필수층** — 이 파일의 `SubjectAdapter`.
  의미: 과목이면 **반드시** 제공한다. 없으면 그 과목은 이 시스템에 들어올 수 없다.
  추가 게이트: "Physics·Chemistry·History에도 **반드시** 존재하는가?"에 **예**일 때만.

**선택층** — `schema/verification_capabilities.py`.
  의미: 있는 과목만 제공한다. Core는 그 능력이 없을 때의 경로를 **반드시** 갖는다.
  추가 게이트: 위 질문에 **아니오**면 전부 이쪽으로 간다.

**필요한 능력이 생겼을 때의 기본 행선지는 선택층이다.** 필수층 확장은 예외이고 근거가 필요하다.
단계 연쇄 검증·기호 항등 판정·수식 봉인이 선택층에 있는 이유가 정확히 이것이다 — 역사·국어에
'전이 동치'나 '항등'이 없으므로, 필수로 만들면 그 과목들이 **빈 구현을 강요당하고** 빈 구현은
곧 "판정했다"는 거짓 신호가 된다(검증 없는 신뢰 금지).

이 2층 구조는 **기계가 지킨다**: `tests/backend/schema/test_subject_adapter_two_tier_contract.py`
가 이 Protocol의 필수 메서드 집합을 동결한다. 여기에 메서드를 늘리면 CI가 적색이 되고, 그때
"선택층으로 갈 수 없는 이유"를 적어야 통과한다(조용한 확장 불가).

## 집행 상태 (2026-08-31 `EOS-69` 완료 — 이 절은 실측으로 갱신됨)

이 파일이 있다고 해서 경계가 집행되는 것은 아니다. 그러나 2026-08-31 현재:

- **경유 배선 완료.** 착수 시점 A분류 11건(`api.coach`·`l6.blueprint.assembly`·
  `l3.render.adapters`·`l3.pedagogy.slot_generator`)은 전부 계약 경유로 바뀌었다. 기본 구현
  선택은 합성 루트 `whymath_backend.composition`(INFRA) 한 곳에 산다.
- **경계 스캔 위반 0건** (`scripts/analysis/eos_core_adapter_boundary_scan.py`).
- **정적 강제 가동.** `EOS-67`의 import-linter 계약 3건이 CI lint 스텝에서 매 PR을 판정한다.

한계(명시): 스캔·계약 모두 **정적 import**만 본다. 동적 import·문자열 경유 참조는 사각이며,
`MIXED` 34모듈은 위반 계산에서 빠지므로 0은 *CORE 배정 모듈 기준의* 0이다.

## v1이 3메서드인 이유 — 후보 9종 전수 판정 (EOS-90 · 2026-09-04)

계획서 100 §3.9가 제시한 후보 9종을 4축(능력인가 데이터인가 / 과목 지식을 요구하는가 / Physics·
Chemistry·History에 반드시 존재하는가 / Core가 반환값을 해석해야 하는가)으로 판정한 결과다.
근거 전문은 `docs/reviews/subject_contract_v1_candidate_verdicts_2026-09-04.md`, 판정표 자체는
`tests/backend/schema/test_subject_adapter_two_tier_contract.py`의 `CANDIDATE_VERDICTS`가 동결한다.

| 후보 | 판정 | 근거 요약 |
|---|---|---|
| `evaluateAnswer` · `detectMisconception` · `validateProblem` | **필수층** | 아래 Protocol 3종 |
| `getConcept` · `getPrerequisites` · `getLearningObjectives` | 계약 아님(**데이터**) | 아래 ⓐ |
| `estimateDifficulty` | 계약 아님(**Core 소유**) | 아래 ⓑ |
| `getRepresentations` | **선택층 후보**(재설계 전제) | 아래 ⓒ |
| `generateExplanation` | 계약 아님(**어댑터 내부**) | 다음 절 |

- ⓐ 개념 15컬럼·`EdgeType` 6종이 이미 과목 중립이고 `subject`는 Overlay로 빠졌다. **조회(read)지
  계산(compute)이 아니다** — 계약에 넣으면 어댑터가 ORM 위임층이 되고 `schema`가 `db`를 알게 된다.
- ⓑ `l2.irt`가 응답 통계만으로 난이도 b를 추정한다(문항 내용 미참조). Core가 이미 하는 일을 과목에
  되물을 이유가 없다.
- ⓒ 유일하게 진짜 능력이나 `VisualizationStyle` 16종이 전량 수학 어휘다. 중립 반환 타입 재설계
  전에는 계약이 될 수 없다.

**핵심 판별선은 조회 vs 계산이다.** 필수 3종은 전부 *입력을 받아 판정을 내리는 계산*이다. 테이블에서
행을 읽는 조회는 과목이 아니라 데이터가 답한다.

## `explain`을 v1에서 뺀 이유

계획서 100 §3.9는 `explain`을 후보로 들지만, 저장소 실측 결과 **위임할 공개 진입점이 0건**이다
(`l1`~`l6` 전수 grep — 공개 `explain*` 함수 없음. 설명 생성기는 전부 스켈레톤 생성기 내부의
비공개 `_explanation()`이고, 연령별 설명 생성은 EOS-53 crosswalk가 C9 **'신규'**로 판정했다).
없는 것을 계약에 넣으면 `NotImplementedError` 좌석이 생겨 "선언≠배선"이 하나 늘 뿐이다.
v1은 **위임 대상이 실재하는 3메서드로 시작**하고, `explain`은 생성 축이 착지한 뒤 별도 태스크로
계약에 추가한다.
"""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

VerificationState = Literal["pass", "fail", "unverifiable"]
"""3상태 판정 — 2상태(정답/오답)로 접으면 '측정 실패'가 '오답'으로 위장된다.

`unverifiable`은 기계가 판정하지 못했다는 뜻이지 학생이 틀렸다는 뜻이 아니다. 이 저장소의
검증 권위 서열(측정 실패를 통과·미달로 위장 금지)이 타입 수준에서 강제되는 지점이다.
"""


class ProblemStatement(BaseModel):
    """Core → Adapter 전달 봉투 — Core가 *들고 있을 수는 있으나 해석하지 않는* 문항 페이로드.

    `l3.verifier.ProblemVerifyInput`과 필드가 겹치지만 **의도적으로 별개 타입**이다. 그쪽은 L3
    (Adapter) 내부 타입이라 `schema`가 import하면 계층 역방향이 된다. 둘 사이의 변환은
    `l4.subject_adapter_math.MathSubjectAdapter`가 수행하며, 그 변환이 어댑터의 존재 이유다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_ref: str = Field(
        description="canonical 문항 식별자(slug·external_id). **DB PK를 넣지 않는다** — "
        "계획서 100 §3.11 'ID에 DB PK 의미를 넣지 말 것'.",
    )
    question_text: str = Field(description="문항 지문. Core에는 불투명 텍스트.")
    answer: str = Field(description="정답 표현. 과목이 정의하는 불투명 문자열.")
    answer_kind: str = Field(
        description="답 종류 태그 — **과목이 정의하고 Core는 값을 해석하지 않는다**. "
        "Core가 이 값으로 분기하면 경계 위반이다.",
    )
    conditions: str = Field(
        default="",
        description="정답이 만족해야 할 제약. 수학이면 수식, 물리면 물리 관계식 — Core에는 불투명.",
    )


class AnswerEvaluation(BaseModel):
    """`evaluate_answer` 결과 — 3상태 + 사유. 과목 중립."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: VerificationState = Field(description="3상태 판정.")
    reason: str | None = Field(
        default=None,
        description="fail/unverifiable 사유. **학생에게 그대로 노출하지 않는다**(진단용).",
    )
    checked_axes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="실제로 닫힌 검증 축. 빈 튜플 = 아무 축도 못 닫음(작동한 비율 원칙).",
    )


class ProblemValidation(BaseModel):
    """`validate_problem` 결과 — 3상태 + 닫힌 축/잔여 축. 과목 중립.

    `residual_axes`가 비어 있지 않다는 것은 **기계가 닫지 못한 축이 남았다**는 뜻이다. 이를
    무시하고 pass로 취급하면 미검증을 검증으로 위장하게 된다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: VerificationState = Field(description="3상태 판정.")
    reason: str | None = Field(default=None, description="fail/unverifiable 사유.")
    machine_axes: tuple[str, ...] = Field(default_factory=tuple, description="기계로 닫힌 축.")
    residual_axes: tuple[str, ...] = Field(
        default_factory=tuple, description="기계가 닫지 못해 교차검증·인간 폴백이 필요한 축."
    )


class MisconceptionSignal(BaseModel):
    """`detect_misconception` 결과 1건 — 오개념 **식별자**와 신뢰도. 과목 중립.

    오개념의 *내용*(정의·반례·개입 전략)은 여기 싣지 않는다 — Core는 코드만 받고, 내용이
    필요하면 오개념 DB(L1)에서 reactive하게 조회한다(구축 플레이북: 오개념 preload 금지).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(description="오개념 정본 ID(kebab-case). 과목별 네임스페이스는 과목 책임.")
    confidence: float = Field(ge=0.0, le=1.0, description="0~1 신뢰도.")
    matched_signals: tuple[str, ...] = Field(
        default_factory=tuple, description="매칭 근거 신호(디버그·UI). 학생 원문 아님."
    )


@runtime_checkable
class SubjectAdapter(Protocol):
    """모든 과목이 EOS Core에 제공해야 하는 최소 능력 3종.

    **여기에 메서드를 추가하기 전의 질문**(계획서 100 §3.9): 이 능력이 Physics·Chemistry·
    History에도 *반드시* 존재하는가? 아니면 Math 전용인가? 후자면 계약이 아니라 어댑터
    내부 공개 API로 둔다.

    금지 예: `render_equation()`·`parse_latex()`·`simplify_expression()` — 전부 Math 전용이다.
    """

    subject_id: str
    """과목 식별자(예: "math"). canonical ID 규칙상 DB PK가 아니다."""

    def evaluate_answer(
        self, problem: ProblemStatement, answer: Mapping[str, str]
    ) -> AnswerEvaluation:
        """학생 답이 문항 조건을 만족하는지 3상태로 판정한다.

        `answer`는 변수명 → 값 문자열 치환맵이다(단일 답은 항목 1개). 값의 *의미*는 과목이
        정한다 — Core는 매핑 구조만 안다.
        """
        ...

    def detect_misconception(
        self, student_work: str, *, top_k: int = 3
    ) -> Sequence[MisconceptionSignal]:
        """학생 풀이 텍스트에서 오개념 후보를 신뢰도 내림차순으로 반환한다.

        매칭 0이면 빈 시퀀스. **없는 오개념을 지어내지 않는다** — 빈 결과가 정상 응답이다.
        """
        ...

    async def validate_problem(self, problem: ProblemStatement) -> ProblemValidation:
        """문항이 스스로 정합한지(정답이 조건을 만족하는지 등) 기계 판정한다.

        비동기인 이유: 잔여 축이 남으면 교차검증(LLM 다관점)이 붙는 구현이 있다. 동기 구현은
        그냥 즉시 반환하면 된다.
        """
        ...
