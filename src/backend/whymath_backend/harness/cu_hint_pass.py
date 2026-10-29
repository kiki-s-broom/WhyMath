"""CU 사후 LLM 힌트 패스 CLI 진입점 — 프로세스 시작점 조립 (EOS-211).

    python -m whymath_backend.harness.cu_hint_pass --run-dir data/runs/eos197-a6-local
    python -m whymath_backend.harness.cu_hint_pass --run-dir data/runs/eos197-a6-openrouter \\
        --subscription premium --budget-krw 5000

패스 본체는 L4 `l4/hint_content/cu_hint_pass.py`다. 이 모듈은 본체가 쓰는 세 가지를 **조립해 내려
주기만** 한다(하네스 = INFRA — 계층 계약 밖 · 경계 문서 `BOUNDARY_MAP["harness"]`):

  ① provider — 저작 경로와 같은 표준 조립 `CompositeProvider(local=OllamaProvider(),
     cloud=build_cloud_provider())`(`l3/equivalent/llm_generator`의 provider=None 기본 구성과 동일).
     클라우드 좌석은 `settings.cloud_provider` 셀렉터가 정한다. 구성만으로는 네트워크 0(지연 연결).
  ② 관측 — `LangfuseSink`(키 미설정이면 no-op). 모든 LLM 호출 → Langfuse 추적.
  ③ 값 축 능력 — 수학 구현 `math_answer_value_exposure()`. `populate.main`이 합성 루트에서 받는 것과
     **같은 기본 구현**이다. 여기서 직접 받는 이유: L4 본체가 합성 루트(`composition`)를 경유하면
     Core→합성 루트 pull 간선이 하나 늘고(`tests/infra/test_eos_dependency_direction.py`의
     CORE_PULL_BASELINE·pyproject `ignore_imports`), 하네스는 어댑터를 직접 써도 되는 INFRA 구역이라
     (`harness/ai_quality_judges`·`ops/g3_content_measures` 선례) 간선 없이 같은 능력을 내려 줄
     수 있다.

종료 코드·산출물·재개 계약은 본체 docstring이 정본이다.
"""

from __future__ import annotations

from collections.abc import Sequence

from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l4.hint_content.cu_hint_pass import run_cli
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure

__all__ = ["main"]

_PROG = "python -m whymath_backend.harness.cu_hint_pass"


def _standard_provider() -> LLMProvider:
    """저작 경로 표준 provider — 로컬 Ollama + 셀렉터가 고른 클라우드 좌석(지연 연결)."""
    from whymath_backend.l3.providers.composite import CompositeProvider
    from whymath_backend.l3.providers.factory import build_cloud_provider
    from whymath_backend.l3.providers.ollama import OllamaProvider

    return CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())


def _standard_trace() -> TraceSink:
    """관측 기본 배선 — 키 미설정이면 no-op(네트워크 0)."""
    from whymath_backend.l3.trace.langfuse_sink import LangfuseSink

    return LangfuseSink()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — 요약 `KEY=VALUE` 줄을 내고 종료 코드(0·1·2·3)로 판정한다.

    세 의존은 팩토리로 넘긴다 — `run_cli`가 인자 검증 뒤, 최상위 예외 처리(exit 3) 안에서 만든다.
    """
    return run_cli(
        argv,
        prog=_PROG,
        provider_factory=_standard_provider,
        trace_factory=_standard_trace,
        value_exposure_factory=math_answer_value_exposure,
    )


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
