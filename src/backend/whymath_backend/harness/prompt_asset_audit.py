"""프롬프트 자산 교수학 감사 — 배포 소크라테스 발화 자산 회귀 게이트(순수·CLI).

배경: `harness/pedagogical_rubric`(answer-leakage 부정지표 + `score_tutoring_response` 루브릭)는
머지됐으나 **소비처가 0**인 고아 자산이었다. SSM 게이트 큐 #12(`docs/standards/ssm_scan_2026-Q3.md`)
는 이 루브릭의 소비처를 "**프롬프트 템플릿을 이 루브릭으로 자체 평가·회귀테스트**"로 명시했다.

본 모듈이 그 첫 소비처다 — 프로젝트가 *실제로 배포하는* 소크라테스 튜터 발화 자산
(`l4/socratic/categories.EXAMPLE_QUESTION` 6종 캐논 발문)이 루브릭 준거(① 정답 미유출 ② 소크라테스
발문)를 **항상** 만족하는지 감사한다. 이를 회귀 게이트로 봉인하면, 배포 프롬프트 예시가 최상위
교수학 금기("막혔을 때 바로 정답 제공 금지")를 절대 어기지 않음을 코드로 보장한다.

순수(DB·파일·라이브 키 무관)·런타임 경로 무접촉. 라이브러리는 자산을 **주입**받아 순수를 유지하고
(l4 미import), 배포 자산 조립은 CLI/테스트가 담당한다. "판정 근거만" 톤(`needs_review_worklist`·
`reviewer_sample_package` 규약 미러 — 근거를 모으고 강제하지 않는다).

────────────────────────────────────────────────────────────────────────────
축 ②: L3 생성 프롬프트 3준거 (OPS-16 — 준거 교체)
────────────────────────────────────────────────────────────────────────────
위 소크라테스 루브릭을 L3에 그대로 확장하면 **무의미하다** — 생성 프롬프트는 소크라테스 발문이
아니고 학생에게 직접 나가지도 않는다. 그래서 L3 축은 준거를 갈아끼운다
(`docs/architecture/ai_content_generation_gap_review.md` §3 D4):

  ⓐ **저작권 레일** — 평가원·EBS·검정 교과서 본문 복제 금지 지시문이 *저작* 프롬프트에 실재하는가
     (`docs/data/licensing_safety.md` 삼중 방어 중 **프롬프트 레일**. 나머지 둘은 데이터 레일·
     구조 레일이고 그쪽은 `ops/provenance_audit`가 본다 — 축이 다르다·중복 없음).
  ⓑ **봉인 레일** — rephrase 계열에 수치·정답 불변 지시문이 실재하는가(`S3-15` 설계 결정 동결).
  ⓒ **독립성 레일** — `cross_verify` 프롬프트에 **생성자 문맥이 미주입**인가(생성자 ≠ 검증자).
     저작 프롬프트의 역할 선언이 검증자에게 새면 같은 사각을 공유한다. 독립 재구성 관점은
     추가로 *정답 은닉*(가시 필드에 정답·형식 모델 없음 + 은닉 선언 실재)까지 본다.

레일은 **자산별 선언표**(`L3_PROMPT_RAILS`)로 관리한다 — 레일이 없는 자산도 *사유와 함께* 등재를
강제해(빈 사유 무효) "레일을 안 걸었다"가 침묵으로 지나가지 못하게 한다(`test_test_suite_wiring`
의 `_INTENTIONALLY_UNWIRED` 규약 미러). 새 enum·새 분류축은 만들지 않는다(anti-explosion) —
레일 3종은 문자열 상수이고 그 자체가 D4가 정의한 준거다.

**판정(exit code)**: 소크라테스 축은 종전대로 근거만 낸다(exit 0). L3 축은 **게이트**다 — 레일
위반이 하나라도 있으면 `main()`이 1을 돌려 CI를 세운다. 저작권 지시문이 프롬프트에서 사라지는
것은 근거로 적어 둘 일이 아니라 즉시 막을 일이기 때문이다.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.harness.pedagogical_rubric import (
    LeakageVerdict,
    detect_answer_leakage,
    score_tutoring_response,
)

__all__ = [
    "DEFAULT_SAMPLE_ANSWERS",
    "L3_PROMPT_RAILS",
    "RAIL_COPYRIGHT",
    "RAIL_INDEPENDENCE",
    "RAIL_SEAL",
    "AssetAuditItem",
    "GenerationPromptAuditItem",
    "audit_generation_prompts",
    "audit_socratic_assets",
    "extract_example_responses",
    "main",
    "render_asset_audit_markdown",
    "render_generation_audit_markdown",
]

# 표본 정답 배터리 기본값 — 자산이 어떤 대표 정답도 유출 안 함을 교차 검증(수치·식·다자리).
# pedagogical_rubric 회귀 테스트의 `_SAMPLE_ANSWERS`와 동일 표본(일관).
DEFAULT_SAMPLE_ANSWERS: tuple[str, ...] = ("42", "13", "x=7", "3.14", "100")

# 프롬프트 문서 예시 발화 마커 — `docs/prompts/socratic_template.md`의 `- 응답 예: "..."` 한 줄
# 관례. 직선 큰따옴표 안의 발화 1건을 캡처(펜스 블록·JSON은 이 마커가 없어 자동 배제).
_EXAMPLE_MARKER = re.compile(r'^\s*-\s*응답 예:\s*"(.+)"\s*$')
# 시나리오 헤더 — 예시 발화의 라벨 추적용(`### 시나리오 N: ...`).
_SCENARIO_HEADER = re.compile(r"^\s*#{2,3}\s*(시나리오\s*\d+)")

# 유출 심각도 우선순위 — 표본 배터리 중 worst_leakage 결선(클수록 심각).
_LEAKAGE_SEVERITY: dict[LeakageVerdict, int] = {
    LeakageVerdict.clean: 0,
    LeakageVerdict.undecidable: 1,
    LeakageVerdict.leaked: 2,
}


class AssetAuditItem(BaseModel):
    """배포 발화 자산 1건의 교수학 감사 결과 — 근거만(reviewer 규약 톤·판정 강제 없음)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(description="자산 식별자(카테고리 키 등).")
    response: str = Field(description="감사 대상 튜터 발화(배포 자산 원문).")
    is_socratic: bool = Field(description="소크라테스 발문 신호 존재(정답 무관).")
    worst_leakage: LeakageVerdict = Field(
        description="표본 정답 배터리 중 최악 유출 판정(leaked>undecidable>clean)."
    )
    reasons: list[str] = Field(
        default_factory=list, description="판정 근거 누적(학생 비노출·조용한 실패 금지)."
    )


def _worst_leakage(verdicts: Iterable[LeakageVerdict]) -> LeakageVerdict:
    """유출 verdict 집합의 최악값(심각도 최대) — 빈 표본이면 clean(보수)."""
    return max(verdicts, key=lambda v: _LEAKAGE_SEVERITY[v], default=LeakageVerdict.clean)


def _normalize_assets(
    assets: Mapping[str, str] | Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """자산 입력을 (label, response) 리스트로 정규화 — Mapping·튜플 이터러블 모두 수용."""
    if isinstance(assets, Mapping):
        return list(assets.items())
    return list(assets)


def extract_example_responses(markdown: str) -> list[tuple[str, str]]:
    """프롬프트 문서 마크다운에서 예시 튜터 발화를 (라벨, 발화)로 추출한다(순수·결정론).

    `docs/prompts/socratic_template.md`의 `- 응답 예: "..."` 한 줄 관례를 대상으로 한다. 줄 스캔으로
    직전 `### 시나리오 N` 헤더를 라벨로 추적하고(헤더 없으면 `응답예{i}` 폴백), 마커 줄의 큰따옴표
    안 발화를 뽑는다. 마커가 없는 시스템 프롬프트·JSON·펜스 코드 블록은 자동 배제(순수 문자열 처리·
    파일 I/O 없음). 라벨 충돌 시 `#k` 접미(결정론).
    """
    items: list[tuple[str, str]] = []
    current_scenario: str | None = None
    seen_labels: dict[str, int] = {}
    for index, line in enumerate(markdown.splitlines(), start=1):
        header = _SCENARIO_HEADER.match(line)
        if header is not None:
            current_scenario = re.sub(r"\s+", "", header.group(1))
            continue
        marker = _EXAMPLE_MARKER.match(line)
        if marker is None:
            continue
        base = current_scenario if current_scenario is not None else f"응답예{index}"
        count = seen_labels.get(base, 0) + 1
        seen_labels[base] = count
        label = base if count == 1 else f"{base}#{count}"
        items.append((label, marker.group(1)))
    return items


def audit_socratic_assets(
    assets: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    sample_answers: Sequence[str] = DEFAULT_SAMPLE_ANSWERS,
) -> list[AssetAuditItem]:
    """배포 소크라테스 발화 자산을 교수학 루브릭으로 감사한다(순수·결정론·의존성 주입).

    각 발화에 대해 ① 소크라테스 발문 신호(정답 무관 — 자산이 발문 형식인지) ② 표본 정답 배터리
    (`sample_answers`) 중 어떤 값도 유출하지 않는지(worst_leakage)를 모은다. 라이브러리는 자산을
    주입받아 순수를 유지한다(배포 자산 조립은 CLI/테스트). 정렬은 label 안정 정렬(결정론).
    """
    items: list[AssetAuditItem] = []
    for label, response in _normalize_assets(assets):
        worst = _worst_leakage(detect_answer_leakage(response, a) for a in sample_answers)
        # 소크라테스 여부는 정답 무관 — 대표 정답 하나로 스코어해 `has_socratic_prompt`만 읽는다.
        probe_answer = sample_answers[0] if sample_answers else "0"
        is_socratic = score_tutoring_response(response, answer=probe_answer).has_socratic_prompt
        reasons = [
            f"소크라테스 발문 {'있음' if is_socratic else '없음'}.",
            f"표본 정답 {len(sample_answers)}종 중 최악 유출: {worst.value}.",
        ]
        items.append(
            AssetAuditItem(
                label=label,
                response=response,
                is_socratic=is_socratic,
                worst_leakage=worst,
                reasons=reasons,
            )
        )
    items.sort(key=lambda it: it.label)
    return items


def render_asset_audit_markdown(items: list[AssetAuditItem]) -> str:
    """자산 감사 결과를 사람이 읽을 마크다운으로 렌더(순수·판정 근거만).

    헤더에 총 자산 수·소크라테스 발문 수·정답 유출 의심(leaked) 수를, 자산마다 발화·소크라테스
    여부·최악 유출·근거를 낸다. "근거만" 톤 — 회귀 테스트가 강제를 담당하고, 렌더는 진단만 한다.
    """
    socratic = sum(1 for it in items if it.is_socratic)
    leaked = sum(1 for it in items if it.worst_leakage is LeakageVerdict.leaked)
    lines: list[str] = [
        "# 프롬프트 자산 교수학 감사 (소크라테스 발화)",
        "",
        f"- 총 자산 {len(items)} · 소크라테스 발문 {socratic} · 정답 유출 의심 {leaked}",
        "- 규약: 배포 발화 자산이 최상위 금기(정답 미유출)·소크라테스 발문을 지키는지 회귀 감사.",
        "",
    ]
    for idx, item in enumerate(items, start=1):
        ok = item.is_socratic and item.worst_leakage is not LeakageVerdict.leaked
        flag = "🟢" if ok else "🔴"
        lines.append(f"## {idx}. {flag} [{item.label}]")
        lines.append(f"- 발화: {item.response}")
        lines.append(f"- 소크라테스 발문: {'예' if item.is_socratic else '아니오'}")
        lines.append(f"- 최악 유출: {item.worst_leakage.value}")
        lines.extend(f"  - {reason}" for reason in item.reasons)
        lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 축 ②: L3 생성 프롬프트 3준거 (OPS-16)
# ══════════════════════════════════════════════════════════════════════════

RAIL_COPYRIGHT = "copyright"
RAIL_SEAL = "seal"
RAIL_INDEPENDENCE = "independence"

# 레일ⓐ 저작권 — 저작 프롬프트에 반드시 실재해야 하는 금지 지시문 어구. 하나라도 사라지면 위반이다
# (`docs/data/licensing_safety.md` 삼중 방어 중 프롬프트 레일). 어구는 원문의 *식별 조각*만 잡아
# 문장 다듬기에는 관대하고 금지 대상·금지 행위의 소실에는 민감하게 둔다.
# system은 **금지 대상을 열거한 전문(full)**을, user는 매 호출 반복되는 **재확인 어구**를 본다 —
# 봉인 레일이 system/user에 다른 어구를 요구하는 것과 같은 구조(자산의 역할이 다르면 준거도 다르다).
_COPYRIGHT_MARKERS_SYSTEM: tuple[str, ...] = ("평가원", "EBS", "교과서", "복제", "자작")
_COPYRIGHT_MARKERS_USER: tuple[str, ...] = ("기출 복제 금지", "자작")

# 레일ⓑ 봉인 — rephrase 계열이 지켜야 하는 불변 지시문(수치·수학적 의미·추가 금지).
# `S3-15`가 동결한 봉인 모델: *발문 문장 표현만* 바꾸고 방정식 문자열·의미·수치는 건드리지 않는다.
_SEAL_MARKERS_SYSTEM: tuple[str, ...] = ("그대로", "수학적 의미를 바꾸지", "추가하지")
_SEAL_MARKERS_USER: tuple[str, ...] = ("한 글자도 바꾸지 말고", "그대로")

# 레일ⓒ 독립성 — 검증자 프롬프트에 **있으면 안 되는** 생성자 문맥(저작 프롬프트의 역할 선언·지시).
# 이것이 검증자에게 새면 검증자가 "만든 사람의 눈"으로 읽어 같은 사각을 공유한다.
_GENERATOR_CONTEXT_MARKERS: tuple[str, ...] = (
    "동등문제 저작자",
    "발문 다양화 편집자",
    "자작 문제",
    "출제하세요",
)
# 레일ⓒ 보강 — 독립 재구성 관점은 *정답 은닉*까지 본다. 가시 필드에 정답·형식 모델이 새면
# 앵커링을 공유해 "독립"이 아니게 된다(`cross_verify` 모듈 docstring의 가시 필드 불변식).
_ANSWER_LEAK_MARKERS: tuple[str, ...] = ("[제시된 정답]", "[기계가 실제로 검산한 형식 모델]")
_ANSWER_HIDDEN_DECLARATION = "정답은 주어지지 않는다"

# 자산 → 적용 레일. **레일 0인 자산도 반드시 등재**하고 사유를 적는다(빈 사유는 무효 — 아래
# 회귀 테스트가 강제). 등재 자체가 "이 자산에 어떤 준거를 걸 것인가"를 판단하게 만든다.
L3_PROMPT_RAILS: dict[str, tuple[str, ...]] = {
    "l3.equivalent.system": (RAIL_COPYRIGHT,),
    "l3.equivalent.user": (RAIL_COPYRIGHT,),
    "l3.equivalent.user_topic": (),
    "l3.rephrase.system": (RAIL_SEAL,),
    "l3.rephrase.user": (RAIL_SEAL,),
    "l3.visualization.system": (),
    "l3.visualization.system_probability_note": (),
    "l3.visualization.user_head": (),
    "l3.visualization.user_styles": (),
    "l3.visualization.user_tail": (),
    "l3.cross_verify.reconstruct_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.reconstruct_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.falsify_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.falsify_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.grounding_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.grounding_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_reconstruct_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_reconstruct_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_falsify_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_falsify_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_grounding_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.statistical_grounding_user": (RAIL_INDEPENDENCE,),
    # v4 결함류별 적대적 검증 관점 — 같은 검증자 계열이므로 독립성 레일을 동일 적용한다.
    "l3.cross_verify.missing_condition_checklist_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.missing_condition_checklist_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.missing_condition_model_grounding_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.missing_condition_model_grounding_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.missing_condition_student_reading_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.missing_condition_student_reading_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_alternative_model_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_alternative_model_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_boundary_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_boundary_user": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_counterexample_system": (RAIL_INDEPENDENCE,),
    "l3.cross_verify.multiple_valid_answers_counterexample_user": (RAIL_INDEPENDENCE,),
}

# 레일 0 자산의 사유 — "왜 이 자산엔 준거를 안 거는가"를 명시한다(침묵 누락 금지).
L3_NO_RAIL_REASONS: dict[str, str] = {
    "l3.equivalent.user_topic": (
        "주제 힌트 한 줄(값 전달용) — 금지 지시문의 자리가 아니다. 저작권 레일은 같은 호출에서 "
        "함께 나가는 system·user 자산이 이미 담지한다."
    ),
    "l3.visualization.system": (
        "시각화는 *명세(구조 JSON)* 생성기이지 문항 본문 저작기가 아니다 — 출력이 렌더 파라미터라 "
        "본문 복제 축이 성립하지 않는다. 대신 렌더 계약 파생 봉인(VIZ-02)이 별도 게이트로 있다"
        "(tests/backend/schema/test_render_contract.py)."
    ),
    "l3.visualization.system_probability_note": "위와 동일(같은 시스템 프롬프트의 조건부 꼬리 줄).",
    "l3.visualization.user_head": "개념·수준 값 전달 — 지시문 없음.",
    "l3.visualization.user_styles": "권장 양식 힌트 값 전달 — 지시문 없음.",
    "l3.visualization.user_tail": "출력 1건 요청 한 줄 — 지시문 없음.",
}


class GenerationPromptAuditItem(BaseModel):
    """L3 생성 프롬프트 자산 1건의 레일 감사 결과 — 근거 + 위반 목록(게이트 입력)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(description="정본 자산 id(`docs/prompts/l3_*.md`의 펜스 라벨).")
    rails: list[str] = Field(description="이 자산에 적용된 준거(빈 목록이면 사유 등재 필수).")
    violations: list[str] = Field(
        default_factory=list, description="위반 사유(비어 있지 않으면 CI exit 1)."
    )
    reasons: list[str] = Field(default_factory=list, description="판정 근거 누적(통과분 포함).")

    @property
    def ok(self) -> bool:
        """레일 위반 0인가(리포트 플래그·게이트 판정의 단위)."""
        return not self.violations


def _missing_markers(text: str, markers: Sequence[str]) -> list[str]:
    """`markers` 중 본문에 없는 것들(결측 목록) — 있으면 그 레일은 위반이다."""
    return [marker for marker in markers if marker not in text]


def _check_copyright_rail(asset_id: str, text: str) -> tuple[list[str], list[str]]:
    """레일ⓐ — 저작 프롬프트의 본문 복제 금지 지시문 실재 검사(system=전문·user=재확인 어구)."""
    markers = _COPYRIGHT_MARKERS_USER if asset_id.endswith(".user") else _COPYRIGHT_MARKERS_SYSTEM
    missing = _missing_markers(text, markers)
    if missing:
        return (
            [
                f"{asset_id}: 저작권 금지 지시문 어구 결측 {missing} — 평가원·EBS·검정 교과서 "
                "본문 복제 금지 레일이 프롬프트에서 사라졌다."
            ],
            [],
        )
    return [], [f"저작권 레일: 금지 지시문 어구 {len(markers)}종 전부 실재."]


def _check_seal_rail(asset_id: str, text: str) -> tuple[list[str], list[str]]:
    """레일ⓑ — rephrase 봉인(수치·정답 불변) 지시문 실재 검사.

    system은 3어구(그대로·의미 불변·추가 금지), user는 앵커 2어구를 본다. **선지(distractor) 축은
    이 레일의 대상이 아니다** — rephrase가 다루는 것은 발문 한 줄뿐이고 선지는 스켈레톤 생성기가
    결정론으로 박아 rephrase 경로를 아예 지나지 않는다(정직한 공백·과잉 준거 금지).
    """
    markers = _SEAL_MARKERS_USER if asset_id.endswith(".user") else _SEAL_MARKERS_SYSTEM
    missing = _missing_markers(text, markers)
    if missing:
        return (
            [
                f"{asset_id}: 봉인 지시문 어구 결측 {missing} — 수치·정답 불변 봉인(S3-15)이 "
                "프롬프트에서 사라졌다."
            ],
            [],
        )
    return [], [f"봉인 레일: 불변 지시문 어구 {len(markers)}종 전부 실재."]


def _check_independence_rail(asset_id: str, text: str) -> tuple[list[str], list[str]]:
    """레일ⓒ — 검증자 프롬프트에 생성자 문맥 미주입 + 독립 재구성의 정답 은닉 검사."""
    violations: list[str] = []
    reasons: list[str] = []
    injected = [marker for marker in _GENERATOR_CONTEXT_MARKERS if marker in text]
    if injected:
        violations.append(
            f"{asset_id}: 검증자 프롬프트에 생성자 문맥 주입 {injected} — 생성자≠검증자 위반"
            "(검증자가 '만든 사람의 눈'으로 읽어 같은 사각을 공유한다)."
        )
    else:
        reasons.append("독립성 레일: 생성자 문맥 미주입(저작 프롬프트 역할 선언 0건).")
    if asset_id.startswith("l3.cross_verify.reconstruct"):
        leaked = [marker for marker in _ANSWER_LEAK_MARKERS if marker in text]
        if leaked:
            violations.append(
                f"{asset_id}: 독립 재구성 관점에 정답·형식모델 필드 노출 {leaked} — 가시 필드 "
                "은닉이 깨져 앵커링을 공유한다."
            )
        elif asset_id.endswith("_system") and _ANSWER_HIDDEN_DECLARATION not in text:
            violations.append(
                f"{asset_id}: 정답 은닉 선언('{_ANSWER_HIDDEN_DECLARATION}') 결측 — 모델이 "
                "정답을 요구·추측할 여지가 열린다."
            )
        else:
            reasons.append("독립성 레일(재구성): 정답·형식모델 은닉 유지.")
    return violations, reasons


_RAIL_CHECKS: dict[str, Callable[[str, str], tuple[list[str], list[str]]]] = {
    RAIL_COPYRIGHT: _check_copyright_rail,
    RAIL_SEAL: _check_seal_rail,
    RAIL_INDEPENDENCE: _check_independence_rail,
}


def audit_generation_prompts(
    assets: Mapping[str, str],
    *,
    rails: Mapping[str, tuple[str, ...]] | None = None,
) -> list[GenerationPromptAuditItem]:
    """L3 생성 프롬프트 자산을 3준거로 감사한다(순수·결정론·의존성 주입).

    자산은 **주입**받는다(라이브러리 순수 — l3 미import). 선언표에 있는데 자산이 없으면
    "위반 0 통과"가 아니라 **위반**이다 — 정본에서 자산이 통째로 사라진 상태가 조용히 초록으로
    보이면 그것이 곧 위장이다(CLAUDE.md "측정 실패와 0건 통과는 절대 같은 색이면 안 된다").
    반대로 선언표에 없는 자산이 정본에 있으면 **미선언 자산**으로 위반이다(레일 판단 누락 강제).

    Args:
        assets: {asset_id: 프롬프트 원문}.
        rails: {asset_id: 적용 레일 튜플}. 기본값은 배포 선언표(`L3_PROMPT_RAILS`).

    Returns:
        asset_id 안정 정렬된 감사 결과. `violations`가 비어 있지 않은 항목이 하나라도 있으면
        게이트는 실패다.
    """
    spec = L3_PROMPT_RAILS if rails is None else rails
    items: list[GenerationPromptAuditItem] = []
    for asset_id in sorted(set(spec) | set(assets)):
        declared = spec.get(asset_id)
        text = assets.get(asset_id)
        if declared is None:
            items.append(
                GenerationPromptAuditItem(
                    asset_id=asset_id,
                    rails=[],
                    violations=[
                        f"{asset_id}: 레일 선언표에 없는 자산 — 어떤 준거를 걸지"
                        "(또는 왜 안 거는지) 선언되지 않았다. L3_PROMPT_RAILS에 등재하라."
                    ],
                )
            )
            continue
        if text is None:
            items.append(
                GenerationPromptAuditItem(
                    asset_id=asset_id,
                    rails=list(declared),
                    violations=[
                        f"{asset_id}: 선언된 자산이 정본에 없다 — 감사 대상 자체가 사라졌다"
                        "(측정 실패는 통과가 아니다)."
                    ],
                )
            )
            continue
        violations: list[str] = []
        reasons: list[str] = []
        for rail in declared:
            rail_violations, rail_reasons = _RAIL_CHECKS[rail](asset_id, text)
            violations.extend(rail_violations)
            reasons.extend(rail_reasons)
        if not declared:
            reasons.append("레일 없음 — 사유가 L3_NO_RAIL_REASONS에 등재돼 있다.")
        items.append(
            GenerationPromptAuditItem(
                asset_id=asset_id, rails=list(declared), violations=violations, reasons=reasons
            )
        )
    return items


def render_generation_audit_markdown(items: Sequence[GenerationPromptAuditItem]) -> str:
    """L3 레일 감사 결과를 마크다운으로 렌더(순수). 헤더에 위반 총계를 낸다."""
    violations = sum(len(item.violations) for item in items)
    railed = sum(1 for item in items if item.rails)
    lines: list[str] = [
        "# L3 생성 프롬프트 레일 감사 (저작권·봉인·독립성)",
        "",
        f"- 총 자산 {len(items)} · 레일 적용 {railed} · 위반 {violations}",
        "- 준거: ⓐ 저작권(본문 복제 금지 지시문) ⓑ 봉인(수치·정답 불변) "
        "ⓒ 독립성(생성자 문맥 미주입).",
        "",
    ]
    for idx, item in enumerate(items, start=1):
        flag = "🟢" if item.ok else "🔴"
        rails = ", ".join(item.rails) if item.rails else "(레일 없음·사유 등재)"
        lines.append(f"## {idx}. {flag} [{item.asset_id}] — {rails}")
        lines.extend(f"  - {reason}" for reason in item.reasons)
        lines.extend(f"  - ❌ {violation}" for violation in item.violations)
        lines.append("")
    return "\n".join(lines)


def _resolve_deployed_assets() -> dict[str, str]:  # pragma: no cover — 배포 자산 조립 glue
    """배포 소크라테스 자산(`EXAMPLE_QUESTION`)을 label→발화 맵으로 조립(l4 소비·CLI 전용).

    라이브러리 순수를 지키려 l4 import는 이 CLI 헬퍼 안에서만 한다(harness→l4 = wh1_loop 기존
    방향·계약 무영향).
    """
    from whymath_backend.l4.socratic.categories import EXAMPLE_QUESTION

    return {category.value: question for category, question in EXAMPLE_QUESTION.items()}


def resolve_l3_prompt_assets() -> dict[str, str]:  # pragma: no cover — 정본 로드 glue
    """L3 생성 프롬프트 정본을 {asset_id: 원문}으로 조립(l3 소비·CLI/테스트 전용).

    라이브러리 순수를 지키려 l3 import는 이 헬퍼 안에서만 한다(`_resolve_deployed_assets`가
    l4에 대해 하는 것과 동형). 정본 파일 부재·파손은 `PromptAssetError`로 **올라간다** —
    감사가 "자산 0건 통과"로 위장하지 않기 위해서다.
    """
    from whymath_backend.l3.prompt_assets import asset_registry

    return dict(asset_registry())


def _run(  # pragma: no cover — 배포 자산 조립·파일 읽기 glue
    sample_answers: Sequence[str], *, prompt_file: str | None
) -> str:
    """배포 소크라테스 자산(+선택 문서 예시)을 감사해 리포트를 렌더(계산은 라이브러리·여긴 조립만).

    기본은 `EXAMPLE_QUESTION`만. `prompt_file`이 주어지면 그 마크다운의 `- 응답 예: "..."` 예시
    발화를 추출해 병합 감사한다(라벨 `시나리오N`·category값과 충돌 없음).
    """
    assets: dict[str, str] = _resolve_deployed_assets()
    if prompt_file is not None:
        with open(prompt_file, encoding="utf-8") as handle:
            for label, response in extract_example_responses(handle.read()):
                assets[label] = response
    items = audit_socratic_assets(assets, sample_answers=sample_answers)
    return render_asset_audit_markdown(items)


def _run_l3() -> tuple[str, int]:  # pragma: no cover — 정본 조립 glue
    """L3 레일 감사 리포트와 위반 수를 돌려준다(계산은 라이브러리·여긴 조립만)."""
    items = audit_generation_prompts(resolve_l3_prompt_assets())
    return render_generation_audit_markdown(items), sum(len(i.violations) for i in items)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 두 축(소크라테스 자산·L3 생성 프롬프트 레일)을 감사해 stdout에 리포트.

    반환값은 **L3 레일 위반 수로만** 결정된다(위반 0 → 0, 그 외 → 1). 소크라테스 축은 종전대로
    근거만 내고 판정하지 않는다(그 축의 강제는 `tests/backend/harness/test_prompt_asset_audit.py`
    회귀가 담당한다). `--axis`로 한쪽만 돌릴 수 있으며, `socratic` 단독 실행은 항상 0이다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.prompt_asset_audit",
        description=(
            "① 배포 소크라테스 발화 자산(EXAMPLE_QUESTION·선택적으로 프롬프트 문서 예시)이 교수학 "
            "루브릭(정답 미유출·소크라테스 발문)을 지키는지, ② L3 생성 프롬프트 정본"
            "(docs/prompts/l3_*.md)이 저작권·봉인·독립성 레일을 지키는지 감사·리포트한다. "
            "L3 레일 위반이 있으면 exit 1. 순수·DB 무관."
        ),
    )
    parser.add_argument(
        "--answers",
        nargs="*",
        default=list(DEFAULT_SAMPLE_ANSWERS),
        help="유출 교차검증용 표본 정답 배터리(기본: 대표 5종).",
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help='추가 감사할 프롬프트 문서 경로(선택·`- 응답 예: "..."` 예시 발화 병합).',
    )
    parser.add_argument(
        "--axis",
        choices=("all", "socratic", "l3"),
        default="all",
        help="감사 축(기본 all — 소크라테스 근거 리포트 + L3 레일 게이트).",
    )
    args = parser.parse_args(argv)
    violations = 0  # pragma: no cover — 아래는 전부 조립·출력 glue
    if args.axis in {"all", "socratic"}:  # pragma: no cover
        print(_run(args.answers, prompt_file=args.prompt_file))  # pragma: no cover
    if args.axis in {"all", "l3"}:  # pragma: no cover
        report, violations = _run_l3()  # pragma: no cover
        print(report)  # pragma: no cover
    return 1 if violations else 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
