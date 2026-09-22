"""L3 Router 결정 로직 단위 테스트 — 축1(C.1)·축2(C.2)·가드·추정·키·에스컬레이션.

설계 정본: docs/architecture/03a_l3_router_design.md
  §C.1(축1 6규칙)·§C.2(축2 7규칙)·§D(에스컬레이션·guard_cloud)·§E(예산)·§F(캐시·태그)·§A.1(지연).
"""

from __future__ import annotations

from typing import Final

import pytest

from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.models import (
    CallSite,
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.router import (
    _EST_ASSUMED_INPUT_TOKENS,
    _EST_ASSUMED_OUTPUT_TOKENS,
    CLOUD_LATENCY_MS,
    CLOUD_MIN_COST_KRW,
    CLOUD_TOKEN_PRICE_USD_PER_1M,
    DAILY_LIMIT_KRW,
    ESCALATION_CHAIN,
    LOCAL_LATENCY_MS,
    LOCAL_MODEL_MATRIX,
    QUALITY_MODEL_ID,
    SERVING_CLOUD_SEAT,
    SLA_GATE_MS,
    USD_TO_KRW,
    Router,
    actual_cost_krw,
    actual_cost_usd,
    cache_key,
    cache_key_for,
    cloud_cost,
    cloud_latency,
    cloud_min_cost,
    cloud_token_price,
    guard_cloud,
    langfuse_fields,
    local_latency,
    next_tier,
    resolve_model,
)
from whymath_backend.schema.enums import LicenseType


def _req(**overrides: object) -> RoutingRequest:
    """테스트용 RoutingRequest 빌더 — 기본은 *LOCAL로 떨어지는* 요청.

    budget_krw=0 → 축1 규칙1이 LOCAL 강제하므로, 명시적으로 budget을 주지 않는 한
    축2 분기를 독립적으로 검증할 수 있다. 클라우드 경로 테스트는 budget을 채운다.

    `data_licenses`는 *반출 가능*(자체 저작)으로 고정한다 — 이 파일은 축1·축2·축3과
    구독·예산 가드를 재는 곳이고, 데이터 등급 게이트(EOS-59)를 켜 두면 클라우드 단언이
    전부 그 게이트 때문에 로컬이 되어 **원래 재려던 규칙을 못 재게 된다**. 등급 축 자체의
    변별력은 `test_data_export_policy.py`가 양방향으로 봉인한다(여기서 중복하지 않는다).
    """
    defaults: dict[str, object] = {
        "task_type": "explain",
        "difficulty": "medium",
        "requires_reasoning": False,
        "student_subscription": "premium",
        "budget_krw": 0.0,  # 기본: LOCAL 강제
        "max_latency_ms": 30000,
        "sync": True,
        "data_licenses": SELF_AUTHORED_CORPUS,  # 반출 가능 — 등급 축을 이 파일에서 중립화
    }
    defaults.update(overrides)
    return RoutingRequest(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def router() -> Router:
    return Router()


# ══════════════════════════════════════════════════════════════════════
# 축1 결정표 (03a §C.1) — 6규칙 각각
# ══════════════════════════════════════════════════════════════════════
class TestAxis1CostTier:
    def test_rule1_budget_exhausted_forces_local(self, router: Router) -> None:
        """규칙1: budget_krw<=0 → LOCAL (쿼터 소진, 비용 0원 강제)."""
        # killer + premium이지만 예산 0이라 클라우드 차단
        d = router.route(_req(difficulty="killer", student_subscription="premium", budget_krw=0.0))
        assert d.cost_tier == CostTier.LOCAL
        assert d.est_cost_krw == 0.0

    def test_rule1_negative_budget_forces_local(self, router: Router) -> None:
        """규칙1 경계: budget_krw<0도 LOCAL."""
        d = router.route(_req(task_type="prove", budget_krw=-10.0))
        assert d.cost_tier == CostTier.LOCAL

    def test_rule2_free_always_local(self, router: Router) -> None:
        """규칙2: free 구독은 예산이 있어도 항상 LOCAL."""
        d = router.route(
            _req(
                difficulty="killer",
                student_subscription="free",
                budget_krw=99999.0,
            )
        )
        assert d.cost_tier == CostTier.LOCAL

    def test_rule3_killer_to_cloud_high(self, router: Router) -> None:
        """규칙3: killer 난이도 → CLOUD_HIGH (예산·구독 가드 통과 시)."""
        d = router.route(
            _req(
                difficulty="killer",
                student_subscription="gifted",
                budget_krw=1000.0,
            )
        )
        assert d.cost_tier == CostTier.CLOUD_HIGH
        assert d.local_model is None
        assert d.mode == "sync"

    def test_rule3_prove_to_cloud_high(self, router: Router) -> None:
        """규칙3: task_type=prove → CLOUD_HIGH."""
        d = router.route(
            _req(
                task_type="prove",
                difficulty="hard",
                student_subscription="premium",
                budget_krw=1000.0,
            )
        )
        assert d.cost_tier == CostTier.CLOUD_HIGH

    def test_rule4_reasoning_premium_to_cloud_mid(self, router: Router) -> None:
        """규칙4: requires_reasoning + premium → CLOUD_MID."""
        d = router.route(
            _req(
                task_type="diagnose",
                difficulty="hard",
                requires_reasoning=True,
                student_subscription="premium",
                budget_krw=1000.0,
            )
        )
        assert d.cost_tier == CostTier.CLOUD_MID
        assert d.local_model is None

    def test_rule4_reasoning_gifted_to_cloud_mid(self, router: Router) -> None:
        """규칙4: requires_reasoning + gifted → CLOUD_MID."""
        d = router.route(
            _req(requires_reasoning=True, student_subscription="gifted", budget_krw=1000.0)
        )
        assert d.cost_tier == CostTier.CLOUD_MID

    def test_rule4_reasoning_basic_stays_local(self, router: Router) -> None:
        """규칙4 미적용: basic은 premium↑이 아니므로 LOCAL로 떨어진다."""
        d = router.route(
            _req(requires_reasoning=True, student_subscription="basic", budget_krw=1000.0)
        )
        assert d.cost_tier == CostTier.LOCAL

    def test_rule6_default_local(self, router: Router) -> None:
        """규칙6: 그 외 기본 LOCAL (목표 분포 80%)."""
        d = router.route(
            _req(
                task_type="explain",
                difficulty="easy",
                requires_reasoning=False,
                student_subscription="premium",
                budget_krw=1000.0,
            )
        )
        assert d.cost_tier == CostTier.LOCAL


# ══════════════════════════════════════════════════════════════════════
# 축2 결정표 (03a §C.2) — 7규칙 각각 (축1=LOCAL 전제, budget_krw=0)
# ══════════════════════════════════════════════════════════════════════
class TestAxis2LocalTier:
    def test_rule1_self_verify_quality_async(self, router: Router) -> None:
        """규칙1: call_site=⑤ 자기검증 → QUALITY/async."""
        d = router.route(_req(call_site=CallSite.SELF_VERIFY))
        assert d.cost_tier == CostTier.LOCAL
        assert d.local_model == LocalModelTier.QUALITY
        assert d.mode == "async"
        assert d.est_latency_ms == LOCAL_LATENCY_MS[LocalModelTier.QUALITY]

    def test_rule2_async_generate_quality(self, router: Router) -> None:
        """규칙2: 비동기 + generate → QUALITY/async (MoE 비동기 전용)."""
        d = router.route(_req(task_type="generate", sync=False))
        assert d.local_model == LocalModelTier.QUALITY
        assert d.mode == "async"

    def test_rule2_async_verify_quality(self, router: Router) -> None:
        """규칙2: 비동기 + verify → QUALITY/async."""
        d = router.route(_req(task_type="verify", sync=False))
        assert d.local_model == LocalModelTier.QUALITY

    def test_rule2_async_hard_quality(self, router: Router) -> None:
        """규칙2: 비동기 + hard 난이도 → QUALITY/async."""
        d = router.route(_req(task_type="explain", difficulty="hard", sync=False))
        assert d.local_model == LocalModelTier.QUALITY

    def test_rule2_async_killer_quality(self, router: Router) -> None:
        """규칙2: 비동기 + killer 난이도(예산 0이라 축1 LOCAL) → QUALITY/async."""
        d = router.route(_req(difficulty="killer", sync=False, budget_krw=0.0))
        assert d.local_model == LocalModelTier.QUALITY

    def test_rule3_sync_tight_sla_fast(self, router: Router) -> None:
        """규칙3: 동기 + max_latency<2000 → FAST (FAST만 SLA 게이트 통과)."""
        d = router.route(
            _req(
                task_type="explain", difficulty="hard", requires_reasoning=True, max_latency_ms=1500
            )
        )
        assert d.local_model == LocalModelTier.FAST
        assert d.mode == "sync"
        assert d.est_latency_ms == LOCAL_LATENCY_MS[LocalModelTier.FAST]

    def test_rule3_boundary_exactly_2000_not_fast(self, router: Router) -> None:
        """규칙3 경계: max_latency==2000은 <2000이 아니므로 규칙3 미적용."""
        # explain+reasoning이라 규칙5로 떨어져 MID
        d = router.route(
            _req(task_type="explain", requires_reasoning=True, max_latency_ms=SLA_GATE_MS)
        )
        assert d.local_model == LocalModelTier.MID

    def test_rule4_greeting_phase_fast(self, router: Router) -> None:
        """규칙4: conversation_phase=greeting → FAST."""
        d = router.route(_req(task_type="coach", conversation_phase="greeting"))
        assert d.local_model == LocalModelTier.FAST

    def test_rule4_followup_phase_fast(self, router: Router) -> None:
        """규칙4: conversation_phase=followup → FAST."""
        d = router.route(_req(conversation_phase="followup"))
        assert d.local_model == LocalModelTier.FAST

    def test_rule3_match_callsite_fast(self, router: Router) -> None:
        """규칙3: ④ match(call_site) → FAST (GENERAL 3b=100%, 2026-05-20)."""
        d = router.route(_req(call_site="match", task_type="match", difficulty="medium"))
        assert d.local_model == LocalModelTier.FAST

    @pytest.mark.parametrize("cs", ["extract", "translate"])
    def test_rule4_extract_translate_callsite_mid(self, router: Router, cs: str) -> None:
        """규칙4: ①extract·③translate(call_site) → MID (GENERAL 3b 하한 미달, 2026-05-20)."""
        d = router.route(_req(call_site=cs, task_type=cs, difficulty="medium"))
        assert d.local_model == LocalModelTier.MID

    def test_rule4_easy_no_reasoning_fast(self, router: Router) -> None:
        """규칙4: easy + not requires_reasoning → FAST (1단계 산술)."""
        d = router.route(_req(task_type="explain", difficulty="easy", requires_reasoning=False))
        assert d.local_model == LocalModelTier.FAST

    @pytest.mark.parametrize("task", ["explain", "coach", "diagnose"])
    def test_rule5_reasoning_main_dialogue_mid(self, router: Router, task: str) -> None:
        """규칙5: explain/coach/diagnose + reasoning → MID (정밀 풀이·메인 대화)."""
        d = router.route(_req(task_type=task, difficulty="medium", requires_reasoning=True))
        assert d.local_model == LocalModelTier.MID
        assert d.mode == "sync"
        assert d.est_latency_ms == LOCAL_LATENCY_MS[LocalModelTier.MID]

    def test_rule6_sync_medium_mid(self, router: Router) -> None:
        """규칙6: 동기 + medium(규칙4·5 미해당) → MID."""
        # task_type=generate(규칙5 set 밖), sync=True(규칙2 밖), medium → 규칙6
        d = router.route(_req(task_type="generate", difficulty="medium", sync=True))
        assert d.local_model == LocalModelTier.MID

    def test_rule6_sync_hard_mid(self, router: Router) -> None:
        """규칙6: 동기 + hard(규칙4·5 미해당) → MID."""
        d = router.route(
            _req(task_type="generate", difficulty="hard", requires_reasoning=False, sync=True)
        )
        assert d.local_model == LocalModelTier.MID

    def test_rule7_fallback_fast(self, router: Router) -> None:
        """규칙7: 어떤 규칙에도 안 걸리는 안전 기본값 → FAST."""
        # generate + easy + reasoning + sync: 규칙2(sync), 규칙3(latency),
        # 규칙4(easy인데 reasoning), 규칙5(generate 아님), 규칙6(easy 아님) 모두 미해당 → 규칙7
        d = router.route(
            _req(task_type="generate", difficulty="easy", requires_reasoning=True, sync=True)
        )
        assert d.local_model == LocalModelTier.FAST
        assert d.mode == "sync"


# ══════════════════════════════════════════════════════════════════════
# 축3 결정표 (03a §C.0) — MATH / GENERAL (축1=LOCAL 전제, budget_krw=0)
# ══════════════════════════════════════════════════════════════════════
class TestAxis3ModelFamily:
    @pytest.mark.parametrize(
        "call_site",
        [
            CallSite.CONCEPT_EXTRACT,  # ①
            CallSite.TRANSLATE_NORMALIZE,  # ③
            CallSite.CONCEPT_ID_MATCH,  # ④
        ],
    )
    def test_nlp_call_sites_general(self, router: Router, call_site: CallSite) -> None:
        """C.0 규칙1: NLP 호출지점 ①③④ → GENERAL (수학모델은 7b조차 0%)."""
        # ①③④ 모두 GENERAL 패밀리; 크기는 match=FAST·extract/translate=MID(§C.2 규칙3·4)
        d = router.route(_req(call_site=call_site, task_type="coach"))
        assert d.cost_tier == CostTier.LOCAL
        assert d.local_family == ModelFamily.GENERAL

    def test_depth_call_site_math(self, router: Router) -> None:
        """C.0 규칙2: ② 깊이추론 → MATH (위계·선수개념 의존성은 수학 추론)."""
        # depth는 크기로직상 일반 분기 → FAST/MID 중 하나(패밀리는 MATH여야)
        d = router.route(_req(call_site=CallSite.DEEP_REASON, task_type="diagnose"))
        assert d.local_family == ModelFamily.MATH

    @pytest.mark.parametrize("task", ["extract", "match", "translate", "classify"])
    def test_nlp_task_types_general(self, router: Router, task: str) -> None:
        """C.0 규칙3: NLP 계열 task_type → GENERAL (추출·매칭·정규화·분류)."""
        d = router.route(_req(task_type=task, difficulty="medium"))
        assert d.local_family == ModelFamily.GENERAL

    @pytest.mark.parametrize(
        "task", ["generate", "explain", "coach", "diagnose", "verify", "prove"]
    )
    def test_math_task_types_math(self, router: Router, task: str) -> None:
        """C.0 규칙4: 수학 풀이·설명·코칭·진단·검증·증명 → MATH.

        prove는 축1에서 CLOUD_HIGH 후보지만 budget_krw=0이라 LOCAL 강제되어
        축3까지 평가된다(규칙1 우선). 따라서 LOCAL+MATH로 확정.
        """
        d = router.route(_req(task_type=task, difficulty="medium", budget_krw=0.0))
        assert d.cost_tier == CostTier.LOCAL
        # FAST/MID면 family 노출, QUALITY면 None(아래서 별도 검증)
        if d.local_model in (LocalModelTier.FAST, LocalModelTier.MID):
            assert d.local_family == ModelFamily.MATH

    def test_default_unknown_is_math(self, router: Router) -> None:
        """C.0 규칙5: 미상 task_type → MATH (안전 기본값, 수학 앱)."""
        d = router.route(_req(task_type="unknown_task", difficulty="medium"))
        assert d.local_family == ModelFamily.MATH

    def test_quality_clears_family(self, router: Router) -> None:
        """QUALITY로 합류하면 local_family=None (MoE 패밀리 무관, 03a §A.0 불변식 4).

        ② depth(패밀리 MATH) + 비동기 hard → 크기 규칙2가 QUALITY로 올림.
        패밀리는 결정됐으나 QUALITY라 local_family는 비워진다(reason엔 남음).
        """
        d = router.route(_req(call_site=CallSite.DEEP_REASON, difficulty="hard", sync=False))
        assert d.local_model == LocalModelTier.QUALITY
        assert d.local_family is None
        assert "math" in d.reason  # reason에는 결정된 패밀리 흔적 유지

    def test_self_verify_quality_no_family(self, router: Router) -> None:
        """⑤ 자기검증 → QUALITY/async + local_family None (패밀리 무관)."""
        d = router.route(_req(call_site=CallSite.SELF_VERIFY))
        assert d.local_model == LocalModelTier.QUALITY
        assert d.local_family is None

    def test_reason_includes_family_and_size(self, router: Router) -> None:
        """reason 포맷 = local/{family}/{size} (03a §C.4)."""
        d = router.route(_req(task_type="match", difficulty="medium"))
        # use_enum_values=True → d.local_model은 문자열 값("fast")
        assert d.reason == f"local/{ModelFamily.GENERAL.value}/{d.local_model}"
        assert d.reason == "local/general/fast"


# ══════════════════════════════════════════════════════════════════════
# 패밀리×크기 매트릭스 (03a §A.0) — resolve_model lookup
# ══════════════════════════════════════════════════════════════════════
class TestResolveModel:
    def test_matrix_exact_ids(self) -> None:
        """A.0 매트릭스 — llm-architect.md와 동일한 4개 (패밀리×크기) → 모델 ID."""
        assert LOCAL_MODEL_MATRIX[(ModelFamily.MATH, LocalModelTier.FAST)] == "qwen2-math:1.5b"
        assert LOCAL_MODEL_MATRIX[(ModelFamily.MATH, LocalModelTier.MID)] == "qwen2-math:7b"
        assert LOCAL_MODEL_MATRIX[(ModelFamily.GENERAL, LocalModelTier.FAST)] == "qwen2.5:3b"
        assert LOCAL_MODEL_MATRIX[(ModelFamily.GENERAL, LocalModelTier.MID)] == "qwen2.5:7b"

    def test_resolve_math_fast(self) -> None:
        assert resolve_model(ModelFamily.MATH, LocalModelTier.FAST) == "qwen2-math:1.5b"

    def test_resolve_general_mid(self) -> None:
        assert resolve_model(ModelFamily.GENERAL, LocalModelTier.MID) == "qwen2.5:7b"

    def test_resolve_quality_family_irrelevant(self) -> None:
        """QUALITY는 패밀리 무관 → 항상 qwen3:30b-a3b (None이어도 동작)."""
        assert resolve_model(None, LocalModelTier.QUALITY) == QUALITY_MODEL_ID
        assert resolve_model(ModelFamily.MATH, LocalModelTier.QUALITY) == QUALITY_MODEL_ID

    def test_resolve_fast_without_family_raises(self) -> None:
        """FAST/MID인데 패밀리 None → 오류(불변식 4)."""
        with pytest.raises(ValueError):
            resolve_model(None, LocalModelTier.FAST)

    def test_resolve_none_model_raises(self) -> None:
        """클라우드(local_model None)에는 적용 불가."""
        with pytest.raises(ValueError):
            resolve_model(None, None)

    def test_resolve_accepts_string_values(self) -> None:
        """문자열 입력도 정규화하여 동작 (use_enum_values=True 대비)."""
        assert resolve_model("general", "fast") == "qwen2.5:3b"  # type: ignore[arg-type]

    def test_route_decision_resolves(self, router: Router) -> None:
        """route() 결정을 resolve_model에 통과 — match=GENERAL/FAST → qwen2.5:3b."""
        d = router.route(_req(task_type="match", difficulty="medium"))
        assert resolve_model(d.local_family, d.local_model) == "qwen2.5:3b"


# ══════════════════════════════════════════════════════════════════════
# 축1·축2 상호작용 — 축1이 먼저, 권위적 (03a §C.4 순서)
# ══════════════════════════════════════════════════════════════════════
class TestAxisInteraction:
    def test_axis1_wins_over_selfverify(self, router: Router) -> None:
        """축1이 먼저 평가 — reasoning+premium이면 ⑤여도 CLOUD_MID로 승급.

        C.2(축2)는 '축1=LOCAL로 확정된 요청만' 평가하므로, call_site=⑤가
        QUALITY를 강제하는 것은 LOCAL로 남았을 때 뿐이다(03a §C.2 전제).
        """
        d = router.route(
            _req(
                call_site=CallSite.SELF_VERIFY,
                requires_reasoning=True,
                student_subscription="premium",
                budget_krw=1000.0,
            )
        )
        assert d.cost_tier == CostTier.CLOUD_MID
        assert d.local_model is None

    def test_selfverify_stays_local_when_budget_zero(self, router: Router) -> None:
        """예산 0이면 축1이 LOCAL 강제 → ⑤가 QUALITY/async로 작동."""
        d = router.route(
            _req(
                call_site=CallSite.SELF_VERIFY,
                requires_reasoning=True,
                student_subscription="premium",
                budget_krw=0.0,
            )
        )
        assert d.cost_tier == CostTier.LOCAL
        assert d.local_model == LocalModelTier.QUALITY
        assert d.mode == "async"


# ══════════════════════════════════════════════════════════════════════
# guard_cloud (03a §D.4)
# ══════════════════════════════════════════════════════════════════════
class TestGuardCloud:
    def test_free_demoted_to_local(self) -> None:
        """free 구독은 클라우드 금지 → LOCAL 강등."""
        req = _req(student_subscription="free", budget_krw=99999.0)
        assert guard_cloud(req, CostTier.CLOUD_HIGH) == CostTier.LOCAL

    def test_insufficient_budget_demoted(self) -> None:
        """잔여 예산 < 1회 최소 비용 → LOCAL 강등."""
        # CLOUD_HIGH 최소비용보다 작은 예산
        req = _req(
            student_subscription="premium",
            budget_krw=CLOUD_MIN_COST_KRW[(CostTier.CLOUD_HIGH, "anthropic")] - 1.0,
        )
        assert guard_cloud(req, CostTier.CLOUD_HIGH) == CostTier.LOCAL

    def test_basic_high_limited_to_mid(self) -> None:
        """basic 구독 + CLOUD_HIGH 희망 → CLOUD_MID로 제한."""
        req = _req(student_subscription="basic", budget_krw=1000.0)
        assert guard_cloud(req, CostTier.CLOUD_HIGH) == CostTier.CLOUD_MID

    def test_premium_high_allowed(self) -> None:
        """premium + 충분 예산 → CLOUD_HIGH 그대로 통과."""
        req = _req(student_subscription="premium", budget_krw=1000.0)
        assert guard_cloud(req, CostTier.CLOUD_HIGH) == CostTier.CLOUD_HIGH

    def test_mid_allowed_with_budget(self) -> None:
        """충분 예산이면 CLOUD_MID 통과."""
        req = _req(student_subscription="basic", budget_krw=1000.0)
        assert guard_cloud(req, CostTier.CLOUD_MID) == CostTier.CLOUD_MID

    def test_route_killer_basic_demoted_to_mid(self, router: Router) -> None:
        """통합: killer + basic → 규칙3이 CLOUD_HIGH 희망하나 가드가 CLOUD_MID로 제한."""
        d = router.route(_req(difficulty="killer", student_subscription="basic", budget_krw=1000.0))
        assert d.cost_tier == CostTier.CLOUD_MID

    def test_route_killer_low_budget_demoted_to_local(self, router: Router) -> None:
        """통합: killer지만 예산이 HIGH 최소비용 미만 → LOCAL 강등."""
        d = router.route(
            _req(
                difficulty="killer",
                student_subscription="premium",
                budget_krw=CLOUD_MIN_COST_KRW[(CostTier.CLOUD_HIGH, "anthropic")] - 1.0,
            )
        )
        # 단 budget>0이라 규칙1은 통과, 규칙3 가드에서 LOCAL 강등
        assert d.cost_tier == CostTier.LOCAL
        assert d.local_model is not None  # 불변식 1: LOCAL이면 local_model 존재


# ══════════════════════════════════════════════════════════════════════
# 캐시 키 (03a §F.1) — 세 축 {cost_tier}:{local_family}:{local_model} 포함
# ══════════════════════════════════════════════════════════════════════
class TestCacheKey:
    def test_key_has_prefix(self) -> None:
        key = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        assert key.startswith("llm:cache:")

    def test_local_tiers_produce_different_keys(self) -> None:
        """같은 프롬프트라도 FAST vs MID는 다른 키 (캐시 정체성에 축2 포함)."""
        k_fast = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        k_mid = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.MID)
        assert k_fast != k_mid

    def test_families_produce_different_keys(self) -> None:
        """같은 크기라도 MATH vs GENERAL은 다른 키 (캐시 정체성에 축3 포함, 03a §F.1).

        MATH(qwen2-math) 응답과 GENERAL(qwen2.5) 응답을 섞지 않는다.
        """
        k_math = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        k_general = cache_key("p", "s", CostTier.LOCAL, ModelFamily.GENERAL, LocalModelTier.FAST)
        assert k_math != k_general

    def test_cost_tiers_produce_different_keys(self) -> None:
        """LOCAL vs CLOUD는 다른 키 (축1 포함)."""
        k_local = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        k_cloud = cache_key("p", "s", CostTier.CLOUD_MID, None, None)
        assert k_local != k_cloud

    def test_same_inputs_stable_key(self) -> None:
        """동일 입력 → 동일 키 (해시 안정성)."""
        k1 = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        k2 = cache_key("p", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        assert k1 == k2

    def test_none_family_and_model_uses_dash(self) -> None:
        """local_family·local_model None(클라우드)도 안정적으로 키 생성."""
        key = cache_key("p", "s", CostTier.CLOUD_HIGH, None, None)
        assert key.startswith("llm:cache:")

    def test_quality_none_family_stable(self) -> None:
        """QUALITY(패밀리 None)도 안정적으로 키 생성."""
        key = cache_key("p", "s", CostTier.LOCAL, None, LocalModelTier.QUALITY)
        assert key.startswith("llm:cache:")

    def test_accepts_string_values(self) -> None:
        """use_enum_values=True로 문자열이 들어와도 동작 (정규화)."""
        k_enum = cache_key("p", "s", CostTier.LOCAL, ModelFamily.GENERAL, LocalModelTier.FAST)
        k_str = cache_key("p", "s", "local", "general", "fast")  # type: ignore[arg-type]
        assert k_enum == k_str

    def test_cache_key_for_decision(self, router: Router) -> None:
        """cache_key_for(decision)는 cache_key와 동일 결과 (세 축 모두 전달)."""
        d = router.route(_req(task_type="extract"))
        k1 = cache_key_for("p", "s", d)
        k2 = cache_key("p", "s", d.cost_tier, d.local_family, d.local_model)
        assert k1 == k2

    def test_different_prompt_different_key(self) -> None:
        """프롬프트가 다르면 키도 다르다."""
        k1 = cache_key("p1", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        k2 = cache_key("p2", "s", CostTier.LOCAL, ModelFamily.MATH, LocalModelTier.FAST)
        assert k1 != k2


# ══════════════════════════════════════════════════════════════════════
# 추정기 (03a §A.1·§E)
# ══════════════════════════════════════════════════════════════════════
class TestEstimators:
    def test_local_latency_values(self) -> None:
        """로컬 지연 — 03a §A.1 벤치 p50."""
        assert local_latency(LocalModelTier.FAST) == 1010
        assert local_latency(LocalModelTier.MID) == 3918
        assert local_latency(LocalModelTier.QUALITY) == 2300

    def test_cloud_latency_values(self) -> None:
        """클라우드 지연 — placeholder 상수."""
        assert cloud_latency(CostTier.CLOUD_MID) == CLOUD_LATENCY_MS[CostTier.CLOUD_MID]
        assert cloud_latency(CostTier.CLOUD_HIGH) == CLOUD_LATENCY_MS[CostTier.CLOUD_HIGH]

    def test_cloud_min_cost_high_gt_mid(self) -> None:
        """CLOUD_HIGH 최소비용 > CLOUD_MID (Opus가 Sonnet보다 비쌈)."""
        assert cloud_min_cost(CostTier.CLOUD_HIGH) > cloud_min_cost(CostTier.CLOUD_MID)

    def test_cloud_cost_matches_min(self) -> None:
        """현재 cloud_cost는 placeholder로 최소비용 사용."""
        req = _req(student_subscription="premium", budget_krw=1000.0)
        assert (
            cloud_cost(req, CostTier.CLOUD_MID)
            == CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")]
        )

    def test_route_local_cost_zero(self, router: Router) -> None:
        """로컬 경로는 비용 0원."""
        d = router.route(_req(task_type="extract"))
        assert d.est_cost_krw == 0.0

    def test_route_cloud_cost_positive(self, router: Router) -> None:
        """클라우드 경로는 비용 > 0."""
        d = router.route(
            _req(difficulty="killer", student_subscription="gifted", budget_krw=1000.0)
        )
        assert d.est_cost_krw > 0.0

    def test_daily_limits_match_spec(self) -> None:
        """구독별 일일 한도 — 03a §E.2 확정값."""
        assert DAILY_LIMIT_KRW == {
            "free": 100,
            "basic": 500,
            "premium": 2000,
            "gifted": 5000,
        }


# ══════════════════════════════════════════════════════════════════════
# Langfuse 태그 dict (03a §F.2) — dict만 생성, 전송 X
# ══════════════════════════════════════════════════════════════════════
class TestLangfuseFields:
    def test_local_decision_fields(self, router: Router) -> None:
        """로컬 결정의 태그 — cost_tier·local_family·local_model·mode 포함."""
        d = router.route(_req(task_type="extract", difficulty="medium"))
        f = langfuse_fields(d)
        assert f["cost_tier"] == "local"
        assert f["local_family"] == "general"  # extract = NLP → GENERAL
        assert f["local_model"] == "mid"  # extract(medium) → 규칙8 MID
        assert f["mode"] == "sync"
        assert f["cache_hit"] is False
        assert f["escalated_from"] is None
        assert f["call_site"] is None
        assert f["student_id_hash"] is None

    def test_local_math_family_recorded(self, router: Router) -> None:
        """수학 태스크 로컬 결정 — local_family=math 기록 (03a §F.2)."""
        d = router.route(_req(task_type="explain", difficulty="medium", requires_reasoning=True))
        f = langfuse_fields(d)
        assert f["local_family"] == "math"

    def test_cloud_decision_local_family_and_model_null(self, router: Router) -> None:
        """클라우드 결정 태그 — local_family·local_model 모두 None."""
        d = router.route(
            _req(difficulty="killer", student_subscription="gifted", budget_krw=1000.0)
        )
        f = langfuse_fields(d)
        assert f["cost_tier"] == "cloud_high"
        assert f["local_family"] is None
        assert f["local_model"] is None

    def test_quality_local_family_null(self, router: Router) -> None:
        """QUALITY 결정 태그 — local_family None(패밀리 무관)."""
        d = router.route(_req(call_site=CallSite.SELF_VERIFY))
        f = langfuse_fields(d)
        assert f["local_model"] == "quality"
        assert f["local_family"] is None

    def test_optional_fields_recorded(self, router: Router) -> None:
        """cache_hit·escalated_from·call_site·student_id_hash 기록."""
        d = router.route(_req(task_type="extract"))
        f = langfuse_fields(
            d,
            cache_hit=True,
            escalated_from=LocalModelTier.FAST,
            call_site=CallSite.CONCEPT_EXTRACT,
            student_id_hash="abc123",
        )
        assert f["cache_hit"] is True
        assert f["escalated_from"] == "fast"
        assert f["call_site"] == "extract"
        assert f["student_id_hash"] == "abc123"

    def test_escalated_from_cost_tier_enum(self, router: Router) -> None:
        """escalated_from에 CostTier enum도 허용 (값으로 정규화)."""
        d = router.route(_req(task_type="extract"))
        f = langfuse_fields(d, escalated_from=CostTier.CLOUD_MID)
        assert f["escalated_from"] == "cloud_mid"

    def test_escalated_from_string(self, router: Router) -> None:
        """escalated_from에 문자열도 그대로 허용."""
        d = router.route(_req(task_type="extract"))
        f = langfuse_fields(d, escalated_from="mid")
        assert f["escalated_from"] == "mid"

    def test_call_site_string_accepted(self, router: Router) -> None:
        """call_site에 문자열도 허용 (정규화)."""
        d = router.route(_req(task_type="extract"))
        f = langfuse_fields(d, call_site="extract")
        assert f["call_site"] == "extract"


# ══════════════════════════════════════════════════════════════════════
# 에스컬레이션 사슬 (03a §D.1·§D.2) — next_tier 로직
# ══════════════════════════════════════════════════════════════════════
#: 반출 가능 등급 — 기존 사슬 테스트가 재는 것은 *사슬 계산*이지 법적 게이트가 아니다.
#: 등급을 명시하지 않으면 fail-closed 기본값 때문에 전부 로컬 천장에서 멈춰 원래 재려던
#: 것을 못 재게 된다. 게이트 축의 변별력은 아래 `TestEscalationRespectsExportGate`가 본다.
_EXPORTABLE: Final = (LicenseType.WHYMATH_GENERATED,)


class TestEscalationChain:
    def test_chain_order(self) -> None:
        """사슬 순서 — FAST→MID→QUALITY→CLOUD_MID→CLOUD_HIGH."""
        assert ESCALATION_CHAIN[0] == (CostTier.LOCAL, LocalModelTier.FAST)
        assert ESCALATION_CHAIN[-1] == (CostTier.CLOUD_HIGH, None)
        assert len(ESCALATION_CHAIN) == 5

    def test_fast_to_mid(self) -> None:
        assert next_tier(CostTier.LOCAL, LocalModelTier.FAST, data_licenses=_EXPORTABLE) == (
            CostTier.LOCAL,
            LocalModelTier.MID,
        )

    def test_mid_to_quality(self) -> None:
        assert next_tier(CostTier.LOCAL, LocalModelTier.MID, data_licenses=_EXPORTABLE) == (
            CostTier.LOCAL,
            LocalModelTier.QUALITY,
        )

    def test_quality_to_cloud_mid(self) -> None:
        """로컬 천장(QUALITY)에서 CLOUD로 넘어감."""
        assert next_tier(CostTier.LOCAL, LocalModelTier.QUALITY, data_licenses=_EXPORTABLE) == (
            CostTier.CLOUD_MID,
            None,
        )

    def test_cloud_mid_to_cloud_high(self) -> None:
        assert next_tier(CostTier.CLOUD_MID, None, data_licenses=_EXPORTABLE) == (
            CostTier.CLOUD_HIGH,
            None,
        )

    def test_cloud_high_is_ceiling(self) -> None:
        """천장(CLOUD_HIGH)에서는 더 승급 불가 → None."""
        assert next_tier(CostTier.CLOUD_HIGH, None, data_licenses=_EXPORTABLE) is None

    def test_unknown_pair_returns_none(self) -> None:
        """사슬에 없는 조합(예: CLOUD_MID+FAST)은 None."""
        assert next_tier(CostTier.CLOUD_MID, LocalModelTier.FAST, data_licenses=_EXPORTABLE) is None

    def test_accepts_string_values(self) -> None:
        """문자열 입력도 정규화하여 동작."""
        assert next_tier("local", "fast", data_licenses=_EXPORTABLE) == (CostTier.LOCAL, LocalModelTier.MID)  # type: ignore[arg-type]


class TestEscalationRespectsExportGate:
    """EOS-59 · codex P1 — 재시도 경로가 법적 게이트를 우회하지 못한다.

    `route()`가 등급 게이트로 클라우드를 막아도, 신뢰도 재시도가 `next_tier()`로 사슬을
    올리면 `LOCAL/QUALITY → CLOUD_MID`가 되어 **막으려던 국외반출이 되살아난다**. 사슬
    계산이 요청을 안 보는 순수 함수라는 사실이 곧 그 구멍이었다(AIHub 4조건 ② 위반 경로).

    양방향으로 본다 — 한쪽만 보면 "전부 로컬 천장"이라는 반대 결함(게이트 과확대로 클라우드
    승급을 통째로 죽임)을 못 잡는다.
    """

    def test_blocked_licenses_climb_only_the_local_chain(self) -> None:
        """반출 금지 자료는 로컬 사슬 안에서만 승급한다."""
        assert next_tier(
            CostTier.LOCAL, LocalModelTier.FAST, data_licenses=(LicenseType.AIHUB_OPEN,)
        ) == (CostTier.LOCAL, LocalModelTier.MID)
        assert next_tier(
            CostTier.LOCAL, LocalModelTier.MID, data_licenses=(LicenseType.AIHUB_OPEN,)
        ) == (CostTier.LOCAL, LocalModelTier.QUALITY)

    def test_blocked_licenses_stop_at_the_domestic_ceiling(self) -> None:
        """로컬 천장에서 CLOUD로 넘어가지 않는다 — 이것이 우회 차단의 핵심 단언."""
        assert (
            next_tier(
                CostTier.LOCAL, LocalModelTier.QUALITY, data_licenses=(LicenseType.AIHUB_OPEN,)
            )
            is None
        )

    def test_exportable_licenses_still_reach_cloud(self) -> None:
        """양성 대조 — 반출 가능 자료는 클라우드까지 정상 승급(게이트가 과확대되지 않는다)."""
        assert next_tier(CostTier.LOCAL, LocalModelTier.QUALITY, data_licenses=_EXPORTABLE) == (
            CostTier.CLOUD_MID,
            None,
        )
        assert next_tier(CostTier.CLOUD_MID, None, data_licenses=_EXPORTABLE) == (
            CostTier.CLOUD_HIGH,
            None,
        )

    def test_unverified_licenses_are_fail_closed(self) -> None:
        """미지정(빈 목록)은 '자료 없음'이 아니라 '모른다' — 차단이 정답이다."""
        assert next_tier(CostTier.LOCAL, LocalModelTier.QUALITY, data_licenses=()) is None

    def test_licenses_argument_is_required_not_optional(self) -> None:
        """인자를 빠뜨리면 **즉시 실패**한다 — 선택 인자였다면 조용한 fail-open이 됐다."""
        with pytest.raises(TypeError):
            next_tier(CostTier.LOCAL, LocalModelTier.QUALITY)  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════════════════
# 결정 객체 불변식 — route()는 항상 유효한 RoutingDecision 반환
# ══════════════════════════════════════════════════════════════════════
class TestRouteProducesValidDecisions:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"task_type": "extract", "budget_krw": 0.0},
            {"task_type": "verify", "sync": False, "budget_krw": 0.0},
            {"call_site": CallSite.SELF_VERIFY, "budget_krw": 0.0},
            {"difficulty": "killer", "student_subscription": "gifted", "budget_krw": 1000.0},
            {"requires_reasoning": True, "student_subscription": "premium", "budget_krw": 1000.0},
            {"task_type": "coach", "requires_reasoning": True, "budget_krw": 0.0},
            {"task_type": "generate", "difficulty": "medium", "sync": True, "budget_krw": 0.0},
        ],
    )
    def test_decision_is_valid(self, router: Router, overrides: dict[str, object]) -> None:
        """모든 경로의 결정이 RoutingDecision 불변식을 만족한다(생성 자체가 검증)."""
        d = router.route(_req(**overrides))
        assert isinstance(d, RoutingDecision)
        # 불변식 1·2: LOCAL ⟺ local_model 존재
        if d.cost_tier == CostTier.LOCAL:
            assert d.local_model is not None
        else:
            assert d.local_model is None
        # 불변식 3: QUALITY ⟹ async
        if d.local_model == LocalModelTier.QUALITY:
            assert d.mode == "async"
        # 불변식 4: local_family ⟺ (LOCAL and local_model in {FAST, MID})
        if d.cost_tier == CostTier.LOCAL and d.local_model in (
            LocalModelTier.FAST,
            LocalModelTier.MID,
        ):
            assert d.local_family is not None
        else:
            assert d.local_family is None
        # 추정치 타당성
        assert d.est_latency_ms > 0
        assert d.est_cost_krw >= 0.0
        assert d.reason  # 비어있지 않음


# ══════════════════════════════════════════════════════════════════════
# 실측 비용 순수 함수 (S1 게이트 ② — 추정 est_*와 분리된 actual)
# ══════════════════════════════════════════════════════════════════════
def _decision(cost: CostTier) -> RoutingDecision:
    """비용 축만 다른 최소 결정 객체(테스트 헬퍼)."""
    if cost is CostTier.LOCAL:
        return RoutingDecision(
            cost_tier=cost,
            local_family=ModelFamily.MATH,
            local_model=LocalModelTier.FAST,
            mode="sync",
            reason="t",
            est_latency_ms=1010,
        )
    return RoutingDecision(
        cost_tier=cost,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="t",
        est_latency_ms=3000,
        est_cost_krw=28.0,
    )


class TestActualCost:
    def test_local_is_always_zero(self) -> None:
        """로컬(Phaiakes9)은 토큰과 무관하게 0원 확정."""
        usage = Usage(input_tokens=999_999, output_tokens=999_999, latency_ms=1.0)
        assert actual_cost_usd(_decision(CostTier.LOCAL), usage) == 0.0
        assert actual_cost_krw(_decision(CostTier.LOCAL), usage) == 0.0

    def test_cloud_mid_token_pricing(self) -> None:
        """CLOUD_MID(sonnet $3/$15 per 1M) 1K+1K → $0.018 = 27.72원(1540원/USD)."""
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=None)
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_usd(d, usage) == pytest.approx(0.018)
        assert actual_cost_krw(d, usage) == pytest.approx(0.018 * USD_TO_KRW)

    def test_cloud_high_token_pricing(self) -> None:
        """CLOUD_HIGH(opus $5/$25 per 1M) 1K+1K → $0.03 = 46.2원."""
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=None)
        d = _decision(CostTier.CLOUD_HIGH)
        assert actual_cost_usd(d, usage) == pytest.approx(0.03)
        assert actual_cost_krw(d, usage) == pytest.approx(46.2)

    def test_cloud_unknown_tokens_returns_zero_for_caller_to_mark_none(self) -> None:
        """클라우드+토큰 미상 → 0.0 반환(호출부가 None 기록으로 '미상' 구분 — docstring 계약)."""
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_krw(d, Usage(input_tokens=None, output_tokens=100)) == 0.0
        assert actual_cost_krw(d, Usage(input_tokens=100, output_tokens=None)) == 0.0

    def test_zero_tokens_zero_cost(self) -> None:
        """0토큰(이론적 경계)은 0원 — 음수·환각값 없음."""
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_krw(d, Usage(input_tokens=0, output_tokens=0)) == 0.0


class TestEstCostDerivedFromPriceTable:
    """est(사전 추정)가 실측 단가표에서 *유도*됨을 봉인 — 하드코딩 매직넘버 아님(#465).

    CLOUD_MIN_COST_KRW[(tier, seat)]가 _EST_ASSUMED_* ×
    CLOUD_TOKEN_PRICE_USD_PER_1M[(tier, seat)] ×
    USD_TO_KRW의 단일 공식과 일치해야 한다. 가정 토큰을 튜닝하면 이 값이 자동 재계산되므로,
    이 테스트는 '유도 공식이 봉인됐음'을 지킨다(값 자체가 아니라 유도 관계를 검증).
    """

    @pytest.mark.parametrize("tier", [CostTier.CLOUD_MID, CostTier.CLOUD_HIGH])
    def test_min_cost_equals_price_table_formula(self, tier: CostTier) -> None:
        """CLOUD_MIN_COST_KRW = 가정 토큰 × 단가표 × 환율 (est가 단가표에서 유도됨)."""
        price_in, price_out = CLOUD_TOKEN_PRICE_USD_PER_1M[(tier, "anthropic")]
        expected = (
            (_EST_ASSUMED_INPUT_TOKENS * price_in + _EST_ASSUMED_OUTPUT_TOKENS * price_out)
            / 1_000_000
            * USD_TO_KRW
        )
        assert CLOUD_MIN_COST_KRW[(tier, "anthropic")] == pytest.approx(expected)

    def test_calibrated_values(self) -> None:
        """실측 보정 가정(74+358·S1-13 2026-07-14 라이브 p50) → MID≈8.61·HIGH≈14.35.

        상수 변경은 재보정 절차(라이브 p50 재대입)로만 — 이 핀이 무단 드리프트를 막는다.
        """
        assert _EST_ASSUMED_INPUT_TOKENS == 74
        assert _EST_ASSUMED_OUTPUT_TOKENS == 358
        assert CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")] == pytest.approx(8.61168)
        assert CLOUD_MIN_COST_KRW[(CostTier.CLOUD_HIGH, "anthropic")] == pytest.approx(14.3528)

    def test_high_gt_mid_invariant(self) -> None:
        """순서 불변식 — CLOUD_HIGH > CLOUD_MID (Opus가 Sonnet보다 비쌈)."""
        assert (
            CLOUD_MIN_COST_KRW[(CostTier.CLOUD_HIGH, "anthropic")]
            > CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")]
        )

    def test_est_and_actual_share_price_table(self) -> None:
        """est(CLOUD_MIN_COST_KRW)와 actual(actual_cost_*)이 *같은 단가표*를 근거로 삼음(#465).

        가정 토큰 상수를 그대로 실측 토큰으로 준 actual과 est가 일치 —
        같은 단가·같은 토큰이면 같은 값(둘의 차이는 토큰 출처뿐임을 봉인·재보정에 강건).
        """
        usage = Usage(
            input_tokens=_EST_ASSUMED_INPUT_TOKENS,
            output_tokens=_EST_ASSUMED_OUTPUT_TOKENS,
            latency_ms=None,
        )
        for tier in (CostTier.CLOUD_MID, CostTier.CLOUD_HIGH):
            actual = actual_cost_krw(_decision(tier), usage)
            assert CLOUD_MIN_COST_KRW[(tier, "anthropic")] == pytest.approx(actual)


class TestLangfuseActualFields:
    """langfuse_fields 실측 4키(cost_krw·latency_ms·input/output_tokens) — est_*와 공존."""

    def test_actual_fields_default_none(self, router: Router) -> None:
        """usage·cost_krw 미전달(캐시 히트·미계측) → 실측 키 4개가 None으로 존재."""
        d = router.route(_req(task_type="extract"))
        f = langfuse_fields(d)
        assert f["cost_krw"] is None
        assert f["latency_ms"] is None
        assert f["input_tokens"] is None
        assert f["output_tokens"] is None

    def test_actual_fields_filled_from_usage(self, router: Router) -> None:
        """usage·cost_krw 전달 → 실측 키가 채워지고 est_* 추정 키와 *별개로* 공존."""
        d = router.route(_req(task_type="extract"))
        usage = Usage(input_tokens=11, output_tokens=22, latency_ms=1234.5)
        f = langfuse_fields(d, usage=usage, cost_krw=0.0)
        assert f["input_tokens"] == 11
        assert f["output_tokens"] == 22
        assert f["latency_ms"] == 1234.5
        assert f["cost_krw"] == 0.0
        # 추정 키는 그대로(구분 유지 — 실측이 추정을 덮어쓰지 않는다).
        assert f["est_latency_ms"] == d.est_latency_ms
        assert f["est_cost_krw"] == d.est_cost_krw


class TestCloudSeatPriceAxis:
    """단가표 좌석 축(ARCH-62) — 티어만으로 키가 잡히면 좌석 이동이 원가를 거짓으로 만든다.

    종전 표는 `CostTier`만 키였고 `CLOUD_MID = Anthropic Sonnet`이 암묵 가정이었다.
    MID를 DeepSeek 좌석으로 옮기면 그 가정만 깨지고 표는 그대로라 **24.4배 과대 계상**이
    되며, 그 값이 `guard_cloud`의 예산 판정 입력이라 결과는 **불필요한 LOCAL 강등**이다.
    강등된 응답도 200이므로 무증상이다(03c §2.2·§2.3).
    """

    # 03c §2.2 표의 값 — 가정 토큰 74/358 · 환율 1,540원/USD 기준 1회 호출 비용.
    _MID_ANTHROPIC_KRW = 8.61168  # claude-sonnet-4-6 $3/$15
    _MID_OPENROUTER_KRW = 0.353584  # deepseek-v4.1-flash @ deepinfra $0.20/$0.60

    def test_mid_openrouter_seat_is_not_anthropic_price(self) -> None:
        """⑤ 변별력 — MID를 openrouter 좌석으로 두면 8.612원이 아니라 **0.354원**이다.

        이 한 줄이 이 태스크의 전부다. 종전 코드에서는 좌석을 넘길 자리 자체가 없어
        두 값이 같았다.
        """
        usage = Usage(
            input_tokens=_EST_ASSUMED_INPUT_TOKENS,
            output_tokens=_EST_ASSUMED_OUTPUT_TOKENS,
            latency_ms=None,
        )
        d = _decision(CostTier.CLOUD_MID)

        anthropic_krw = actual_cost_krw(d, usage, seat="anthropic")
        openrouter_krw = actual_cost_krw(d, usage, seat="openrouter")

        assert anthropic_krw == pytest.approx(self._MID_ANTHROPIC_KRW)
        assert openrouter_krw == pytest.approx(self._MID_OPENROUTER_KRW)
        # 24.4배 — 좌석 축이 죽으면 이 비가 1.0이 된다.
        assert anthropic_krw is not None and openrouter_krw is not None
        assert anthropic_krw / openrouter_krw == pytest.approx(24.36, rel=1e-3)

    def test_default_seat_is_serving_seat_not_selector(self) -> None:
        """좌석 생략 = 학생 대면 서빙 좌석(anthropic) — 기존 호출부의 뜻이 보존된다.

        `settings.cloud_provider`를 읽지 않는 것이 의도다(그 셀렉터는 저작 경로 전용).
        읽었다면 저작 좌석 변경이 학생 예산 판정까지 조용히 바꾼다.
        """
        assert SERVING_CLOUD_SEAT == "anthropic"
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=None)
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_usd(d, usage) == actual_cost_usd(d, usage, seat="anthropic")

    def test_unknown_seat_is_none_not_zero(self) -> None:
        """③ 좌석 미상 → None(미측정). 0.0이면 '공짜로 돌았다'와 구별되지 않는다."""
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=None)
        d = _decision(CostTier.CLOUD_MID)
        assert actual_cost_usd(d, usage, seat=None) is None
        assert actual_cost_krw(d, usage, seat=None) is None

    def test_unpriced_combination_is_none_not_zero(self) -> None:
        """③ 단가 미등재 조합(HIGH×openrouter — 핀 자체가 미확인) → None.

        근거 없는 값을 지어 넣지 않았다는 사실이 조회 결과로 드러나야 한다.
        """
        assert (CostTier.CLOUD_HIGH, "openrouter") not in CLOUD_TOKEN_PRICE_USD_PER_1M
        usage = Usage(input_tokens=1000, output_tokens=1000, latency_ms=None)
        d = _decision(CostTier.CLOUD_HIGH)
        assert actual_cost_usd(d, usage, seat="openrouter") is None
        assert actual_cost_krw(d, usage, seat="openrouter") is None

    def test_local_is_zero_regardless_of_seat(self) -> None:
        """LOCAL은 좌석과 무관하게 0원 확정 — 미상(None)이 아니다(Phaiakes9은 실제로 0원)."""
        usage = Usage(input_tokens=999_999, output_tokens=999_999, latency_ms=1.0)
        d = _decision(CostTier.LOCAL)
        assert actual_cost_usd(d, usage, seat=None) == 0.0
        assert actual_cost_krw(d, usage, seat="openrouter") == 0.0

    def test_cloud_token_price_lookup_three_states(self) -> None:
        """단가 조회의 3상태 — 등재/미등재/좌석 미상. 뒤 둘은 None이고 서로 같게 다뤄도 된다."""
        assert cloud_token_price(CostTier.CLOUD_MID, "openrouter") == (0.20, 0.60)
        assert cloud_token_price(CostTier.CLOUD_HIGH, "openrouter") is None
        assert cloud_token_price(CostTier.CLOUD_MID, None) is None

    def test_every_priced_combination_is_pinned_with_evidence(self) -> None:
        """단가 근거 드리프트 방어 — 표의 **모든** 등재 조합을 핀으로 고정한다.

        왜 전건인가: 좌석 하나만 테스트가 고정하지 않으면 그 값은 조용히 바뀔 수 있고,
        단가는 예산 판정 입력이라 바뀐 사실이 응답 200 뒤에 숨는다. 뮤테이션 검증에서
        `deepseek` 단가만 생존한 것이 이 테스트를 부른 이유다(전건 RED는 커버리지의
        증거가 아니다 — 픽스처가 없는 절은 주입 목록에도 오르지 않는다).

        값을 바꾸려면 여기 핀과 표 주석의 근거를 **함께** 고쳐야 한다.
        """
        expected = {
            # anthropic — 공개 가격(2026-06-23 확인)
            (CostTier.CLOUD_MID, "anthropic"): (3.0, 15.0),
            (CostTier.CLOUD_HIGH, "anthropic"): (5.0, 25.0),
            # openrouter — deepinfra 고정 공급사 실단가(list price $0.15/$0.60이 아니다)
            (CostTier.CLOUD_MID, "openrouter"): (0.20, 0.60),
            # deepseek 공식 API — 피크 단가(보수적 상한). off-peak는 $0.15/$0.60이며,
            # 예산 판정에서 과소 계상이 한도 초과를 낳으므로 상한을 쓴다.
            (CostTier.CLOUD_MID, "deepseek"): (0.30, 1.20),
        }
        assert CLOUD_TOKEN_PRICE_USD_PER_1M == expected

    def test_deepseek_seat_uses_conservative_peak_bound(self) -> None:
        """deepseek 좌석만 시간대 이중 단가 — 표는 **비싼 쪽**을 골랐다는 결정을 고정한다.

        off-peak($0.15/$0.60)를 고르면 예산 판정이 과소 계상되고, 그 방향의 오류는
        한도 초과라 되돌리기 어렵다(과대 계상이 낳는 불필요한 강등보다 나쁘다).
        """
        off_peak, peak = (0.15, 0.60), (0.30, 1.20)
        actual = CLOUD_TOKEN_PRICE_USD_PER_1M[(CostTier.CLOUD_MID, "deepseek")]
        assert actual == peak
        assert actual != off_peak

    def test_seat_literal_is_config_single_source(self) -> None:
        """① 좌석 어휘는 `config.CloudSeat` 하나 — 표의 좌석이 그 리터럴을 벗어나지 않는다.

        새 enum을 세우면 좌석 어휘가 둘이 되고, 그것이 ARCH-58이 상환한 사고다.
        """
        from typing import get_args

        from whymath_backend.config import CloudSeat, Settings

        allowed = set(get_args(CloudSeat))
        assert allowed == {"anthropic", "openrouter", "deepseek"}
        # 셀렉터 필드가 같은 별칭을 쓴다(사본이 아니라 같은 타입).
        assert Settings.model_fields["cloud_provider"].annotation is CloudSeat
        table_seats = {seat for _, seat in CLOUD_TOKEN_PRICE_USD_PER_1M}
        assert table_seats <= allowed


class TestGuardCloudSeatAxis:
    """④ 예산 판정이 좌석별 값을 쓴다 — 싼 좌석에서 비싼 좌석 임계로 강등하지 않는다."""

    def test_budget_between_seats_demotes_only_for_expensive_seat(self) -> None:
        """anthropic 임계 미만이지만 openrouter로는 충분한 예산 → 좌석에 따라 판정이 갈린다.

        종전에는 이 예산이 좌석과 무관하게 LOCAL 강등이었다(1,414회 가능한데 58회로 계산).
        """
        mid_anthropic = CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")]
        mid_openrouter = CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "openrouter")]
        assert mid_openrouter < mid_anthropic  # 전제: 좌석 단가가 실제로 다르다

        # 두 임계 사이의 예산 — 싼 좌석에서는 호출 가능, 비싼 좌석에서는 불가.
        budget = (mid_anthropic + mid_openrouter) / 2
        req = _req(student_subscription="premium", budget_krw=budget)

        assert guard_cloud(req, CostTier.CLOUD_MID, "anthropic") == CostTier.LOCAL
        assert guard_cloud(req, CostTier.CLOUD_MID, "openrouter") == CostTier.CLOUD_MID

    def test_default_seat_preserves_legacy_judgment(self) -> None:
        """좌석 생략 시 판정은 종전과 동일(서빙 좌석 anthropic) — 학생 트래픽 무변경."""
        budget = CLOUD_MIN_COST_KRW[(CostTier.CLOUD_MID, "anthropic")] - 1.0
        req = _req(student_subscription="premium", budget_krw=budget)
        assert guard_cloud(req, CostTier.CLOUD_MID) == CostTier.LOCAL
        assert guard_cloud(req, CostTier.CLOUD_MID) == guard_cloud(
            req, CostTier.CLOUD_MID, SERVING_CLOUD_SEAT
        )

    def test_unpriced_seat_raises_rather_than_folding_to_default(self) -> None:
        """단가 미등재 조합의 예산 판정은 **raise** — 기본 좌석 단가로 조용히 접지 않는다.

        `cloud_model_pins`와 같은 규율이다. 접으면 "새 좌석을 골랐는데 옛 좌석 단가로
        예산을 판정하는" 침묵 실패가 되고, 그것이 이 태스크가 상환하는 사고다.
        """
        req = _req(student_subscription="premium", budget_krw=1000.0)
        with pytest.raises(ValueError, match="단가 미등재 조합"):
            guard_cloud(req, CostTier.CLOUD_HIGH, "openrouter")
