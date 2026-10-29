"""CU 사후 힌트 패스 프롬프트 정본 인용 — `docs/prompts/cu_hint_pass.md` 원문 그대로 (EOS-211).

**드리프트 방지 원칙**(`l4/misconception/judge_prompts.py` 동일 패턴): SYSTEM 문구·USER 템플릿·출력
JSON 스키마는 `docs/prompts/cu_hint_pass.md`의 `prompt:<id>` 블록 *원문을 그대로* 옮긴다. 문구를
바꿀 때는 그 문서를 *먼저* 고친 뒤 코드를 맞춘다(doc-first). 이 상수가 문서와 어긋나면
`tests/backend/l4/hint_content/test_cu_hint_pass.py`의 원문 정합 단언이 깨진다.

왜 L3 `prompt_assets` 로더를 쓰지 않는가: 그 로더의 등록부(`PROMPT_ASSET_FILES`·
`REQUIRED_ASSET_IDS`)와 레일 감사(`harness/prompt_asset_audit.L3_PROMPT_RAILS`)는 **L3 생성
프롬프트**의 축이다. 이 패스는 L4(교수학 — graded 힌트) 좌석이므로 L4 관례(코드 상수 사본 +
문서 원문 정합 단언)를 따른다.

프롬프트가 요구하는 형식은 게이트 3종(`gates.py`)의 **실제 판정 규칙**에서 거꾸로 정했다:
  - 게이트 A ③ 흐름 표지 정규식 `_FLOW_MARKERS`
    (`\\d+\\s*(?:번째\\s*)?단계|첫\\s*단계|마지막\\s*단계`)
    — L1은 이 표지가 하나도 없어야 하고, L2·L3는 하나 이상 있어야 한다. 그래서 L2에 "풀이는 모두
    N단계로 이어져."와 "지금은 첫 단계"를, L3에 "첫 단계"를 요구하고, L1에는 단계 낱말
    자체를 금한다.
  - 게이트 A ③ 계산 노출 — 단계 본문(정규화 2자 이상)이 L1·L2 본문에 들어 있으면 거부, L3에는
    하나 이상 들어 있어야 한다. 그래서 L3에 첫 단계 식을 **글자 그대로** 싣게 하고 L1·L2엔
    식을 금한다.
  - 게이트 A ③ 개념 이름 — L1 본문에 `concept_name`이 그대로 있어야 한다(「」로 감싸게 한다).
  - 게이트 A ④ — L3가 마지막 단계를 시연하거나 최종 단계 식이 본문에 실리면 거부한다. 값 축은
    최종 단계를 **목표 값**으로 읽으므로, 마지막 단계를 `변수 = 정답` 식으로 쓰게 한다 — 한국어
    문장이면 목표를 읽지 못해 판정 불가(undecidable)가 되고 그 힌트는 거부된다(판정 불가 ≠ 통과).
  - 게이트 B — 정답 값 글자·계산하면 정답이 되는 식 금지.
  - 게이트 C(`l4/tone_filter`) — 금지 패턴 6종(잘못된·틀렸·못 하·실수·바보·포기)은 부분 문자열로
    걸린다. 개념 이름 「실수」(real number)도 걸리므로 그 낱말을 피하게 한다(게이트 C는 치환하지
    않고 거부한다 — 뜻을 망가뜨리지 않기 위해).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final

__all__ = [
    "CU_HINT_OUTPUT_SCHEMA",
    "CU_HINT_PROMPT_ASSET_IDS",
    "CU_HINT_SYSTEM",
    "CU_HINT_USER_TEMPLATE",
    "build_cu_hint_user",
    "cu_hint_prompt_version",
]

# ──────────────────────────────────────────────────────────────────────────
# SYSTEM — `docs/prompts/cu_hint_pass.md` 블록 `prompt:l4.cu_hint.system` 원문.
# ──────────────────────────────────────────────────────────────────────────
CU_HINT_SYSTEM: Final[
    str
] = """당신은 WhyMath의 **힌트 저작자**입니다. 이미 만들어진 자체 저작 수학 문항 하나를 받아,
그 문항의 풀이 단계 목록과 3단계 힌트(L1·L2·L3)를 JSON 객체 하나로만 출력하세요.

## 절대 금기
- 정답 값을 L1·L2·L3 어디에도 쓰지 마세요. 계산하면 정답이 되는 식도 쓰지 마세요.
- 마지막 단계의 식을 L1·L2·L3 어디에도 쓰지 마세요.
- 학생을 다그치거나 깎아내리는 말을 쓰지 마세요. 특히 다음 낱말은 어떤 뜻으로도 쓰지 마세요:
  잘못된, 틀렸, 못 하, 실수, 바보, 포기. (수 체계의 '실수'도 쓰지 마세요 — 다른 말로 바꿔 쓰세요.)
- 고등학교 교육과정 밖의 방법(예: 로피탈 정리)을 쓰지 마세요.
- 평가원·EBS·검정 교과서의 본문·문제·풀이를 인용하거나 복제하지 마세요.

## 출력 형식 — 아래 키만 가진 JSON 객체 하나. 다른 글·코드 펜스 금지
{"steps": ["...", "..."], "concept_name": "...", "hints": {"L1": "...", "L2": "...", "L3": "..."}}

### steps — 풀이 단계 (2개 이상 8개 이하)
- 각 단계는 **식 한 줄**입니다. 한국어 문장을 섞지 말고 식만 쓰세요.
- 곱셈은 `*`, 거듭제곱은 `^`로 씁니다. 예: f'(x) = 6*x^2 - 6*x + 4
- 해설이 주어지면 그 해설을 단계로 나누고, 해설이 없으면 직접 풀어 단계를 만드세요.
- **마지막 단계는 `변수 = 정답` 꼴의 식 하나**입니다. 예: b = -14
- 첫 단계와 마지막 단계는 서로 다른 식이어야 합니다.

### concept_name — 이 문항의 핵심 개념 이름
- 고등학교 교육과정 용어로 2~20자. 숫자·등호·식을 넣지 마세요.

### hints — 세 힌트 모두 학생에게 건네는 다정한 반말로 쓰고, 질문으로 끝내세요
- L1 (개념 이름만): concept_name을 「」로 감싸 글자 그대로 한 번 쓰고, 그 개념의 어떤 성질을
  쓸 수 있을지 묻습니다. '단계'라는 낱말, 숫자, 식을 쓰지 마세요.
- L2 (단계 흐름만): "풀이는 모두 N단계로 이어져."(N은 steps의 개수)와 "지금은 첫 단계"를 그대로
  포함하고, 각 단계에서 *무엇을 하는지*(예: 도함수를 구한다, 접점의 좌표를 정한다)만 말합니다.
  계산 결과·식·숫자 값을 쓰지 마세요.
- L3 (첫 단계 시연): "첫 단계"라는 말을 쓰고, steps의 첫 번째 식을 **글자 그대로** 한 줄로
  보여 준 뒤, 그다음은 학생이 이어 가도록 묻습니다. 첫 번째 식 말고 다른 단계의 식은 쓰지 마세요."""

# ──────────────────────────────────────────────────────────────────────────
# USER 템플릿 — `docs/prompts/cu_hint_pass.md` 블록 `prompt:l4.cu_hint.user` 원문.
# 자리표시는 `{{NAME}}`(str.format을 쓰지 않는다 — 본문에 중괄호 JSON 예시가 있다).
# ──────────────────────────────────────────────────────────────────────────
CU_HINT_USER_TEMPLATE: Final[str] = """문항 (자체 저작 · WHYMATH_GENERATED)
{{QUESTION}}

정답: {{ANSWER}}
해설: {{EXPLANATION}}
과목: {{SUBJECT}} · 성취기준: {{STANDARDS}}

위 문항의 풀이 단계와 3단계 힌트를 형식 그대로 JSON 객체 하나로만 출력하세요."""

CU_HINT_PROMPT_ASSET_IDS: Final[tuple[str, ...]] = (
    "l4.cu_hint.system",
    "l4.cu_hint.user",
)
"""정본 문서의 블록 id(고정 순서) — 원문 정합 테스트와 prompt_version 계산의 재료."""

_NO_EXPLANATION: Final[str] = "(해설 없음 — 직접 풀어 단계를 만드세요)"

# Ollama 제약 디코딩용 출력 스키마(LOCAL 결정에서만 싣는다 — 클라우드는 프롬프트 + 관대 파서).
# 길이·문자 제약은 여기서 다 걸지 않는다 — 수용 계약의 정본은 `cu_hint_pass.CuHintDraft`다.
CU_HINT_OUTPUT_SCHEMA: Final[Mapping[str, object]] = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 8},
        "concept_name": {"type": "string"},
        "hints": {
            "type": "object",
            "properties": {
                "L1": {"type": "string"},
                "L2": {"type": "string"},
                "L3": {"type": "string"},
            },
            "required": ["L1", "L2", "L3"],
        },
    },
    "required": ["steps", "concept_name", "hints"],
}


def build_cu_hint_user(
    *,
    question: str,
    answer: str,
    explanation: str | None,
    subject: str,
    standards: tuple[str, ...],
) -> str:
    """USER 템플릿 자리표시 치환 — 해설이 없으면 '직접 풀라'는 문구로 채운다(빈칸 금지)."""
    filled = explanation.strip() if explanation and explanation.strip() else _NO_EXPLANATION
    replacements = {
        "QUESTION": question.strip(),
        "ANSWER": answer.strip(),
        "EXPLANATION": filled,
        "SUBJECT": subject.strip() or "(미기재)",
        "STANDARDS": ", ".join(standards) if standards else "(미기재)",
    }
    text = CU_HINT_USER_TEMPLATE
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def cu_hint_prompt_version() -> str:
    """프롬프트 정본 식별자 — 인용하는 두 블록 내용의 해시(`l4.cu_hint@sha256:<12hex>`).

    `l3/equivalent/llm_generator._prompt_version`과 같은 형식이다(번호를 발명하지 않고 실제 문면으로
    결정론 식별 — 같은 식별자 = 같은 문면). 출력 스키마도 모델 입력이므로 함께 해시한다.
    """
    digest = hashlib.sha256()
    for asset_id, body in zip(
        CU_HINT_PROMPT_ASSET_IDS, (CU_HINT_SYSTEM, CU_HINT_USER_TEMPLATE), strict=True
    ):
        digest.update(asset_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(body.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(json.dumps(CU_HINT_OUTPUT_SCHEMA, sort_keys=True).encode("utf-8"))
    return f"l4.cu_hint@sha256:{digest.hexdigest()[:12]}"
