"""오답 서명 규칙표의 **데이터 계약** — 형식 게이트(P3-56 후보 구현).

`data/corpus/wrong_answer_signatures_v1/rules.yaml`의 형식을 검증한다. 콘텐츠는 코드가 아니라
데이터라는 규율(P3 마스터 프리앰블)에 따라 "어느 오개념이 어떤 오답 모양으로 드러나는가"를 이
계약 뒤의 YAML이 소유한다. 계산(오답 값을 만드는 변환)은 코드가 이름으로 소유하고, 데이터는
**이름과 신뢰도·근거·픽스처**만 가진다.

ID 체계를 새로 만들지 않는다
────────────────────────────────────────────────────────────────────────────
규칙은 오개념을 **M-id**(오개념 코퍼스 정본 id)로 가리킨다. 런타임 후보는 kebab id로 나오므로
kebab ↔ M-id 해석은 기존 크로스워크 코퍼스(`misconception_crosslinks_v1`)를 읽는 쪽이 한다 —
이 파일에는 kebab이 한 군데도 없다(두 번째 매핑 표를 만들지 않는다).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "SIGNATURE_SCHEMA_VERSION",
    "EvidenceKind",
    "SignatureFixture",
    "SignatureFixtures",
    "SignatureRule",
    "SignatureSpec",
]

SIGNATURE_SCHEMA_VERSION = "1.0.0"

EvidenceKind = Literal["direct", "indirect"]
"""오답 값이 오개념 하나로만 설명되면 `direct`, 다른 원인으로도 같은 값이 나올 수 있으면
`indirect`다. 신뢰도 상한이 이 값에 묶인다(아래 `SignatureRule` 검증)."""

_MIS_ID = re.compile(r"^M\d{4}$")

# 직접 증거의 상한과 간접 증거의 상한 — 간접은 선지 연결(0.8)보다 높을 수 없다. 오답 값이 우연히
# 같을 수 있는 증거를 구조적으로 증명된 증거와 같은 신뢰로 올리면 R3 입력 하한(0.7 초과)을 쉽게
# 넘어 낙인이 되기 때문이다.
_INDIRECT_CONFIDENCE_CAP = 0.8
_CONFIDENCE_FLOOR = 0.65  # match_gate의 후보 인정선 — 이 아래 규칙은 어차피 게이트가 비운다.


class SignatureFixture(BaseModel):
    """문항은행 승인 문항 1건 + 학생이 낼 답 1건 — 규칙이 잡아야/잡지 말아야 하는 예.

    질문·정답은 문항은행에서 읽는다(`problem_id`). 이 파일에 정답을 손으로 다시 적지 않는다 —
    정답이 두 곳에 살면 어긋나도 모른다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str = Field(min_length=1, description="문항은행 승인 문항의 problem_id.")
    answer: str = Field(min_length=1, description="학생이 제출했다고 가정하는 답(문자열).")
    note: str = Field(min_length=1, description="이 답이 왜 이 오개념의 모양인지(또는 왜 아닌지).")


class SignatureFixtures(BaseModel):
    """한 규칙의 픽스처 — 잡아야 할 오답과 잡으면 안 되는 답(오탐 방지)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wrong: tuple[SignatureFixture, ...] = Field(
        min_length=1, description="이 규칙이 후보를 내야 하는 오답. 최소 1건."
    )
    not_wrong: tuple[SignatureFixture, ...] = Field(
        default=(),
        description="이 규칙이 후보를 내면 안 되는 답(정답 포함). 오탐 변별 픽스처.",
    )


class SignatureRule(BaseModel):
    """오답 서명 규칙 1건 — "이 질문에서 이 오개념이면 학생 답이 이 값이 된다"."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, description="규칙 식별자(표 안에서 유일).")
    mis_ids: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "이 서명이 드러내는 오개념의 M-id들. 크로스워크가 이들을 같은 kebab으로 모으면 "
            "하나의 런타임 후보가 된다(예: M0075·M0672 → product-rule-naive)."
        ),
    )
    ask: str = Field(min_length=1, description="질문이 무엇을 묻는가(엔진의 질문 추출기 이름).")
    wrong_transform: str = Field(
        min_length=1, description="오답 값을 만드는 변환의 이름(엔진의 변환 레지스트리 이름)."
    )
    confidence: float = Field(gt=0.0, le=1.0, description="후보 신뢰도. 1.0 미만을 권장.")
    evidence: EvidenceKind
    note: str = Field(min_length=1, description="이 서명이 왜 그 오개념의 증거인지 한 문장.")
    fixtures: SignatureFixtures

    @field_validator("mis_ids")
    @classmethod
    def _mis_ids_wellformed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [m for m in value if not _MIS_ID.match(m)]
        if bad:
            raise ValueError(f"M-id 형식(M0000)이 아닙니다: {bad}")
        if len(set(value)) != len(value):
            raise ValueError(f"mis_ids에 중복이 있습니다: {value}")
        return value

    @model_validator(mode="after")
    def _confidence_matches_evidence(self) -> SignatureRule:
        if self.confidence < _CONFIDENCE_FLOOR:
            raise ValueError(
                f"{self.rule_id}: confidence {self.confidence} < {_CONFIDENCE_FLOOR} — "
                "후보 인정선 미만 규칙은 게이트가 항상 비우므로 데이터에 둘 이유가 없습니다."
            )
        if self.evidence == "indirect" and self.confidence > _INDIRECT_CONFIDENCE_CAP:
            raise ValueError(
                f"{self.rule_id}: 간접 증거의 신뢰도는 {_INDIRECT_CONFIDENCE_CAP} 이하여야 합니다"
                f"(받은 값 {self.confidence}). 같은 오답 값이 다른 원인으로도 나올 수 있습니다."
            )
        return self


class SignatureSpec(BaseModel):
    """서명 규칙표 전체."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = Field(description="R6-03: 경계를 넘는 데이터의 버전.")
    spec_id: Literal["wrong_answer_signatures_v1"]
    rules: tuple[SignatureRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> SignatureSpec:
        ids = [r.rule_id for r in self.rules]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"rule_id가 중복됩니다: {dup}")
        return self
