"""L3 생성 프롬프트 정본 로더 — `docs/prompts/l3_*.md`를 단일 진실 원천으로 인용한다(OPS-16).

배경(부채): L4 교수학 프롬프트는 `docs/prompts/` 정본 + 코드 인용 + `harness/prompt_asset_audit`
회귀 감사를 갖는데, **L3 생성 프롬프트는 코드 인라인이 정본이고 감사가 0**이었다
(`docs/architecture/ai_content_generation_gap_review.md` §3 D4). "새 LLM 생성 경로를 열지
않는다"고 판정했다면 이미 열려 있는 LLM 지점이 정본·감사 없이 사는 상태가 그 판정과 모순이다.

정본 규약(L4 미러 + 로더 경유):
    - 문면의 소유자는 `docs/prompts/l3_*.md`다. 코드는 사본을 두지 않고 asset id로 **인용**한다.
    - 문구를 바꾸려면 **정본 파일을 먼저** 고친다(doc-first). 코드에 사본이 없으므로 두 진실
      원천이 애초에 생기지 않는다 — L4(코드 상수 사본 + 원문 정합 단언)보다 한 단계 강한 형태다.
    - 무엇이 인용되는지는 `REQUIRED_ASSET_IDS`가 동결한다(정본에만 있고 아무도 안 쓰는 고아
      자산·코드가 부르는데 정본에 없는 유령 id를 양방향으로 검출 — `test_prompt_assets.py`).

블록 형식(마크다운 안전):
    ```prompt:<asset_id>
    ...프롬프트 원문(마지막 개행 1개는 정규화로 제거)...
    ```
    정보 문자열(`prompt:`)로 여는 펜스만 자산이다. 문서의 설명 산문·다른 코드 블록은 자동 배제
    되므로, 정본 파일에 규약·근거·버전 이력을 자유롭게 쓸 수 있다(문서로서도 읽힌다).

플레이스홀더는 `{{NAME}}` 형태이고 `fill()`이 치환한다. `str.format`을 쓰지 않는 이유는 프롬프트
본문에 JSON 예시(`{"type": ...}`)가 많아 중괄호 이스케이프 지옥이 되기 때문이다.

파일 I/O는 **프로세스당 1회**다(`lru_cache` — `l3/render/assessment_bank.py`·`l3/visualization.py`
선례). 매 LLM 호출마다 디스크를 읽지 않는다.

강등 정책(침묵 실패 금지) — **fail-closed**:
    정본 파일 부재·파손·id 결측은 폴백하지 않고 `PromptAssetError`로 **차단**한다. 프롬프트 자산은
    저작권 레일ⓐ·봉인 레일ⓑ·독립성 레일ⓒ의 *담지체*이므로, 레일이 빠진 문면으로 LLM을 부르는
    것보다 호출을 실패시키는 쪽이 안전하다(의사결정 우선순위: 법적 준수 ② > 비용·개발속도 ⑥⑦).
    `l3/visualization.py`의 렌더 계약이 "읽기 실패 = 직전 동작 유지"로 강등할 수 있었던 것은
    코드 측 폴백값이 계약과 **동일함을 CI가 동결**했기 때문인데, 프롬프트 문면에는 그런
    동치 폴백이 존재할 수 없다(사본을 두는 순간 정본이 둘이 된다). 그래서 방향이 반대다.
    실패는 항상 **예외 타입명을 로그에 실어** 남긴다(값·경로 외 내용은 싣지 않는다).

7계층: L3 지역. 배포 자산 파일을 읽을 뿐 상위 계층을 import하지 않는다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

logger = logging.getLogger("whymath.l3.prompt_assets")

__all__ = [
    "PROMPT_ASSET_FILES",
    "REQUIRED_ASSET_IDS",
    "PromptAssetError",
    "asset_registry",
    "fill",
    "prompt_text",
    "reset_prompt_asset_cache",
]


class PromptAssetError(RuntimeError):
    """정본 프롬프트 자산을 읽을 수 없거나 인용 대상이 없음 — fail-closed 차단 신호.

    호출자는 폴백하지 않는다. 레일이 빠진 프롬프트로 LLM을 부르는 것보다 요청 실패가 안전하다.
    """


# 정본 파일 경로 — 레포 루트 기준 고정(cwd 무관). 이 파일은
# src/backend/whymath_backend/l3/prompt_assets.py라 parents[4]가 레포 루트다
# (`l3/visualization.py`의 렌더 계약 앵커와 같은 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
PROMPT_ASSET_DIR = _REPO_ROOT / "docs" / "prompts"

# 정본 파일 목록 — L3 생성 프롬프트 4모듈. L4 프롬프트 문서는 여기 없다(축이 다르다·타 세션 소관).
PROMPT_ASSET_FILES: tuple[str, ...] = (
    "l3_equivalent_gen.md",
    "l3_rephrase.md",
    "l3_visualization.md",
    "l3_cross_verify.md",
)

# 코드가 실제로 인용하는 asset id 전량 — 정본↔코드 드리프트 검출의 기준선.
# 여기 없는 id가 정본에 있으면 **고아 자산**(아무도 안 쓰는 문면이 감사만 통과), 여기 있는데
# 정본에 없으면 **유령 인용**(런타임 PromptAssetError). 양방향을 회귀 테스트가 동결한다.
REQUIRED_ASSET_IDS: tuple[str, ...] = (
    "l3.cross_verify.falsify_system",
    "l3.cross_verify.falsify_user",
    "l3.cross_verify.grounding_system",
    "l3.cross_verify.grounding_user",
    "l3.cross_verify.missing_condition_checklist_system",
    "l3.cross_verify.missing_condition_checklist_user",
    "l3.cross_verify.missing_condition_model_grounding_system",
    "l3.cross_verify.missing_condition_model_grounding_user",
    "l3.cross_verify.missing_condition_student_reading_system",
    "l3.cross_verify.missing_condition_student_reading_user",
    "l3.cross_verify.multiple_valid_answers_alternative_model_system",
    "l3.cross_verify.multiple_valid_answers_alternative_model_user",
    "l3.cross_verify.multiple_valid_answers_boundary_system",
    "l3.cross_verify.multiple_valid_answers_boundary_user",
    "l3.cross_verify.multiple_valid_answers_counterexample_system",
    "l3.cross_verify.multiple_valid_answers_counterexample_user",
    "l3.cross_verify.reconstruct_system",
    "l3.cross_verify.reconstruct_user",
    "l3.cross_verify.statistical_falsify_system",
    "l3.cross_verify.statistical_falsify_user",
    "l3.cross_verify.statistical_grounding_system",
    "l3.cross_verify.statistical_grounding_user",
    "l3.cross_verify.statistical_reconstruct_system",
    "l3.cross_verify.statistical_reconstruct_user",
    "l3.equivalent.system",
    "l3.equivalent.user",
    "l3.equivalent.user_topic",
    "l3.rephrase.system",
    "l3.rephrase.user",
    "l3.visualization.system",
    "l3.visualization.system_probability_note",
    "l3.visualization.user_head",
    "l3.visualization.user_styles",
    "l3.visualization.user_tail",
)

# 펜스 여는 줄 — 정보 문자열이 `prompt:<id>`인 것만 자산으로 본다(다른 코드 블록 자동 배제).
_FENCE_OPEN = re.compile(r"^```prompt:([a-z0-9_.]+)\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")
# 치환되지 않고 남은 플레이스홀더 탐지 — 채우기 누락이 프롬프트로 새는 것을 막는다.
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def parse_prompt_blocks(markdown: str, *, origin: str) -> dict[str, str]:
    """마크다운에서 `prompt:<id>` 펜스 블록을 뽑아 {id: 원문}으로 돌려준다(순수·결정론).

    블록 본문은 줄 목록을 `\\n`으로 잇는다 — 즉 **마지막 개행 1개는 포함하지 않는다**(정규화).
    같은 파일 안의 id 중복은 조용히 덮어쓰지 않고 `PromptAssetError`다(어느 쪽이 정본인지
    결정 불가 = 단일 진실 원천 붕괴). 닫히지 않은 펜스도 마찬가지로 실패시킨다(파손 위장 금지).
    """
    blocks: dict[str, str] = {}
    current_id: str | None = None
    buffer: list[str] = []
    for line in markdown.splitlines():
        if current_id is None:
            opened = _FENCE_OPEN.match(line)
            if opened is not None:
                current_id = opened.group(1)
                buffer = []
            continue
        if _FENCE_CLOSE.match(line):
            if current_id in blocks:
                raise PromptAssetError(f"{origin}: 프롬프트 자산 id 중복 — {current_id}")
            blocks[current_id] = "\n".join(buffer)
            current_id = None
            continue
        buffer.append(line)
    if current_id is not None:
        raise PromptAssetError(f"{origin}: 닫히지 않은 프롬프트 펜스 — {current_id}")
    return blocks


@lru_cache(maxsize=1)
def asset_registry() -> Mapping[str, str]:
    """정본 파일 전량을 1회 읽어 {asset_id: 원문} 읽기전용 맵으로 캐시한다.

    프로세스당 1회 파일 I/O(매 LLM 호출마다 디스크를 읽지 않는다). 테스트는
    `reset_prompt_asset_cache()`로 무효화한다.

    실패(파일 부재·인코딩 파손·펜스 파손·파일 간 id 충돌)는 폴백 없이 `PromptAssetError`다 —
    **예외 타입명을 로그에 싣는다**(침묵 실패 금지·시크릿/본문은 싣지 않는다).
    """
    merged: dict[str, str] = {}
    for filename in PROMPT_ASSET_FILES:
        path = PROMPT_ASSET_DIR / filename
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            logger.error(
                "L3 프롬프트 정본 로드 실패 — 생성을 차단한다(폴백 없음). error_type=%s path=%s",
                type(exc).__name__,
                path,
            )
            raise PromptAssetError(f"정본 프롬프트 파일을 읽을 수 없다: {path}") from exc
        for asset_id, body in parse_prompt_blocks(text, origin=filename).items():
            if asset_id in merged:
                raise PromptAssetError(f"프롬프트 자산 id가 파일 간 충돌: {asset_id} ({filename})")
            merged[asset_id] = body
    return MappingProxyType(merged)


def prompt_text(asset_id: str) -> str:
    """asset id → 정본 프롬프트 원문. 없으면 `PromptAssetError`(fail-closed).

    호출자가 폴백 문면을 지어내지 못하게 *예외로만* 실패한다 — 저작권·봉인·독립성 레일이
    빠진 프롬프트가 조용히 LLM에 나가는 경로를 원천 차단한다.
    """
    registry = asset_registry()
    try:
        return registry[asset_id]
    except KeyError as exc:
        logger.error(
            "L3 프롬프트 자산 결측 — 생성을 차단한다. error_type=%s asset_id=%s",
            type(exc).__name__,
            asset_id,
        )
        raise PromptAssetError(
            f"정본에 없는 프롬프트 자산 id: {asset_id} (docs/prompts/l3_*.md 확인)"
        ) from exc


def fill(template: str, **values: str) -> str:
    """`{{NAME}}` 플레이스홀더를 치환한다(순수). 미치환 잔여가 있으면 `PromptAssetError`.

    잔여 검사가 이 함수의 존재 이유다 — 정본에 플레이스홀더를 추가하고 코드에서 값을 넘기지
    않으면, 검사가 없을 때 `{{FOO}}`가 **그대로 LLM에 나간다**(조용한 품질 붕괴). 값이 비어야
    정상인 자리는 빈 문자열을 명시적으로 넘긴다.
    """
    filled = template
    for name, value in values.items():
        filled = filled.replace(f"{{{{{name}}}}}", value)
    leftover = _PLACEHOLDER.findall(filled)
    if leftover:
        raise PromptAssetError(f"치환되지 않은 프롬프트 플레이스홀더: {sorted(set(leftover))}")
    return filled


def reset_prompt_asset_cache() -> None:
    """정본 캐시 무효화 — 테스트 격리용 seam(`reset_render_contract_cache` 동형).

    프로덕션은 정본이 프로세스 수명 동안 고정이라 호출할 일이 없다.
    """
    asset_registry.cache_clear()
