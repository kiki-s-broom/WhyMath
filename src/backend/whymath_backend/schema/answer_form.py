"""답 **형태** 계약 — 값 동치와 분리된 지시 준수 축 (EOS-28).

────────────────────────────────────────────────────────────────────────────
무엇이 문제였나 (실측 2026-09-01)
────────────────────────────────────────────────────────────────────────────
"확률을 **기약분수로** 나타내시오"라고 지시한 문항 26건에서, 채점기는 지시를 전혀 보지
않았다. 실측(`verify_final_answer` 직접 호출):

    제출 `1/36`         → correct
    제출 `2/72`         → correct   ← 기약이 아닌데 통과
    제출 `5/180`        → correct   ← 동상
    제출 `0.0277777777` → correct   ← 분수조차 아닌데 통과

값 동치(`1/36 = 2/72`)만 보면 셋 다 맞다. 그러나 학생이 지시를 읽고 따랐는지는 **다른
질문**이고, 그 질문에 대한 답이 시스템에 존재하지 않았다.

────────────────────────────────────────────────────────────────────────────
왜 `answer_format`을 확장하지 않고 `answer_constraint`에 넣는가 (ADR)
────────────────────────────────────────────────────────────────────────────
**후보 ①  `answer_format`**(enum 4종: 자연수·분수·실수·식) — ❌ 기각.
  이것은 답의 **타입 라벨**("이 답은 분수다")이다. "분수다"와 "기약이어야 한다"는 다른
  축이라 섞으면 의미가 뭉개지고, 형태 요구마다 값을 늘리면 4종이 곧 폭발한다.

**후보 ②  `answer_constraint`**(JSONB·문항별 제약·실측 소비 0건) — ✅ **채택**.
  이미 있는 제약 슬롯이다. 마이그레이션이 필요 없고 SEC-24 비노출 경계를 그대로 상속한다.

**후보 ③  신규 컬럼** — ❌ 기각.
  1%(작성 당시 스캔 26/2,638) 기능에 마이그레이션을 붙인다. 게다가 그 용도의 컬럼이 이미 있다(후보
  ②).

자유형 JSONB의 위험(스키마 강제 없음)은 **닫힌 키 + 닫힌 어휘 + fail-closed 리더**로 막는다:
`expected_form_of()`가 모르는 값을 만나면 조용히 통과시키지 않고 `None`을 주며, 호출측은
그것을 "요구 없음"이 아니라 판정 불가로 다룰 수 있다(아래 `FormVerdict` 4상태).

────────────────────────────────────────────────────────────────────────────
폐쇄 어휘가 1종뿐인 이유 — 측정이 그렇게 말했다
────────────────────────────────────────────────────────────────────────────
`scripts/analysis/answer_form_requirement_scan.py`가 작성 당시 코퍼스 2,638건을 전수 조사했다.
**실증된 형태 어휘는 `reduced_fraction` 1종(26건·0.99%)뿐이고 나머지 6종은 0건**이다
(인수분해·전개·유리화·간단히·소수 자릿수·지정 꼴).

없는 것을 미리 넣지 않는다(소비처 0 추상 금기 — 구축 플레이북). 어휘를 늘리려면 **스캐너가
그 형태를 코퍼스에서 실제로 잡아야** 한다: 스캐너의 `FORM_PATTERNS`가 후보 목록이고,
이 enum은 그중 *적중이 0이 아닌 것*만 담는다. 이 규칙은 테스트로 동결돼 있다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = ["ExpectedForm", "FormVerdict", "expected_form_of"]

#: `answer_constraint` 안에서 형태 요구가 사는 **닫힌 키**.
EXPECTED_FORM_KEY = "expected_form"


class ExpectedForm(str, Enum):
    """문항이 요구하는 답의 표기 형태 — **코퍼스에 실증된 것만**.

    값을 추가하려면 먼저 `answer_form_requirement_scan.py`에서 적중이 0이 아니어야 한다.
    """

    reduced_fraction = "reduced_fraction"
    """기약분수 — "기약분수로 나타내시오"(실측 26건·probability_finite 뱅크)."""


class FormVerdict(str, Enum):
    """형태 판정 4상태 — **값 판정(`VerificationOutcome`)과 별개 축**이다.

    별도 enum을 둔 이유: 값 3상태의 `correct`/`incorrect`를 형태에 재사용하면 "형태가
    incorrect"라는 문장이 만들어지고, 그 순간 형태 위반이 오답으로 읽힌다. **형태 불만족은
    오답이 아니다**(EOS-28 acceptance ③·④). 어휘를 분리하는 것이 그 혼동을 막는 1차 방어다.

    `not_required`가 독립 상태인 이유(None-vs-zero): 문항의 99%는 형태 요구가 없다.
    그것을 `satisfied`로 적으면 "지시를 지켰다"는 **거짓 신호**가 되고, 지표에서 형태 준수율이
    99%로 부풀어 오른다. 요구가 없는 것과 요구를 지킨 것은 다르다.
    """

    satisfied = "satisfied"
    """요구된 형태를 실제로 지켰다."""

    violated = "violated"
    """요구된 형태를 지키지 않았다. **오답이 아니다** — 값은 맞을 수 있다."""

    not_required = "not_required"
    """이 문항에 형태 요구가 없다. 판정 대상 자체가 아니다."""

    unverifiable = "unverifiable"
    """요구는 있으나 판정하지 못했다(파싱 실패·미지 어휘). **`satisfied`로 접지 않는다.**"""


def expected_form_of(answer_constraint: Any) -> ExpectedForm | None:
    """`answer_constraint`에서 형태 요구를 읽는다 — **fail-closed**.

    반환:
      - `ExpectedForm`: 닫힌 어휘에 있는 요구.
      - `None`: 요구 없음(키 부재·제약 자체 없음).

    모르는 값(`expected_form: "무언가이상한값"`)에는 `None`이 아니라 **예외를 던지지 않고**
    `None`을 주되, 호출측이 그것을 구별할 수 있어야 한다 — 그래서 `raises` 대신
    `strict_expected_form_of()`를 따로 둔다. 기본 리더가 조용한 이유는 이 값이 콘텐츠 저작
    산물이라 오타 하나가 채점 전체를 500으로 만들면 안 되기 때문이다(가용성 우선).
    """
    form, _known = _read(answer_constraint)
    return form


def strict_expected_form_of(answer_constraint: Any) -> tuple[ExpectedForm | None, bool]:
    """`(형태, 어휘에_있는가)` — 미지 값을 **드러내야 하는** 호출자용.

    두 번째 값이 `False`면 "요구가 적혀 있는데 우리가 모르는 어휘"라는 뜻이다. 그 경우
    `not_required`가 아니라 `unverifiable`로 흘려야 한다 — 모르는 요구를 요구 없음으로
    처리하면 저작 오타가 조용히 무시된다(침묵 실패 금지).
    """
    return _read(answer_constraint)


def _read(answer_constraint: Any) -> tuple[ExpectedForm | None, bool]:
    if not isinstance(answer_constraint, dict):
        return None, True  # 제약 자체가 없다 — 요구 없음이 맞다.
    raw = answer_constraint.get(EXPECTED_FORM_KEY)
    if raw is None:
        return None, True
    try:
        return ExpectedForm(str(raw)), True
    except ValueError:
        return None, False  # 적혀 있는데 모르는 어휘 — 호출측이 구별할 수 있게 한다.
