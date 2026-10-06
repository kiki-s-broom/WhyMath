"""WhyMath 백엔드 패키지.

서브패키지:
  - l3: L3 LLM 콘텐츠 생성·검증 — 모델 라우터(M1.2). 두 라우팅 축
        (CostTier × LocalModelTier)을 합성해 결정한다.
        설계 정본: `docs/architecture/03a_l3_router_design.md`.
"""

__version__ = "0.1.0"

# CLI 출력 인코딩 — `python -m whymath_backend.<모듈>`이 cp949 파이프에서 죽지 않게 (OPS-53).
from whymath_backend._stdio import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()
