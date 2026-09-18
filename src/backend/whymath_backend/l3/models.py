"""L3 라우터 스키마 — 세 라우팅 축의 enum + 입력/출력 모델 (Pydantic).

설계 정본: `docs/architecture/03a_l3_router_design.md` §G(스키마)·§0.1(명칭 충돌 해소)·
§0.2(패밀리 축 도입)·§A.0(패밀리×크기 매트릭스).

세 라우팅 축 (03a §0):
  - 축1 `CostTier` (비용·위치): LOCAL / CLOUD_MID / CLOUD_HIGH — 목표 분포 80/18/2
  - 축3 `ModelFamily` (로컬 모델 패밀리): MATH(qwen2-math) / GENERAL(qwen2.5)
    — CostTier.LOCAL + FAST/MID일 때만 의미를 가진다(QUALITY는 패밀리 무관).
  - 축2 `LocalModelTier` (로컬 모델 크기): FAST(1.5b/3b) / MID(7b) / QUALITY(27b)
    — CostTier.LOCAL일 때만 의미를 가진다.

로컬 실제 모델 = (패밀리 축3 × 크기 축2) 매트릭스 lookup (03a §A.0, router.LOCAL_MODEL_MATRIX).

명칭 충돌 해소: 기존 단일 enum `LLMTier{LOCAL,MID,HIGH}`를 (a) 축1 `CostTier`와
(b) 축2 `LocalModelTier`로 분해한다. `LLMTier.MID → CostTier.CLOUD_MID`,
`LLMTier.HIGH → CostTier.CLOUD_HIGH`로 1:1 의미 보존(03a §0.1).
2026-05-20 Phaiakes9 태스크 인지 실측이 축3 `ModelFamily`를 추가로 강제했다 —
NLP를 수학 모델로 돌리면 7b조차 0%였다(03a §0.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import LicenseType

# ──────────────────────────────────────────────────────────────────────────
# 데이터 등급 축의 보수 기본값 (EOS-59)
#
# 등급 어휘를 새로 만들지 않고 `LicenseType`을 그대로 쓴다 — "AIHub는 국외반출 금지"라는
# 사실은 이미 `l1/rights/permission_map.py`(`_AIHUB_OPEN.export=False`)에 선언돼 있고,
# 라우터가 그것을 자기 방식으로 다시 정의하면 그 순간 권리 기준이 두 벌이 된다.
#
# 기본값이 `UNKNOWN`인 이유(fail-closed): `permission_map`에서 UNKNOWN의 `export`는
# `None`(미확인)이고, 데이터 등급 게이트는 `None`을 허용으로 보지 않는다 → 등급을 명시하지
# 않은 요청은 클라우드로 나가지 못한다. 이 보수 기본값이 *일상 동작*이 되지 않도록,
# 프로덕션 호출부가 등급을 실제로 채우는지는 소스 스캔 게이트
# (`scripts/ops/check_routing_data_grade.py`·CI `backend` 잡)가 강제한다 —
# 기본값은 그 명시를 잊었을 때만 작동하는 *사고 방지용 backstop*이다.
# ──────────────────────────────────────────────────────────────────────────
DEFAULT_DATA_LICENSES: tuple[LicenseType, ...] = (LicenseType.UNKNOWN,)
"""등급 미지정 요청의 기본 등급 — 가장 보수적(미확인 → 국외 반출 차단)."""


# ──────────────────────────────────────────────────────────────────────────
# 축1: 비용·위치 (기존 LLMTier.MID/HIGH → CLOUD_ 접두사로 개명, 03a §0.1)
# ──────────────────────────────────────────────────────────────────────────
class CostTier(str, Enum):
    """비용·위치 축 — 클라우드로 *올라갈* 것인가? (03a §0 표·§A.1)"""

    LOCAL = "local"
    """Phaiakes9 로컬 (0원) — 축2(LocalModelTier)로 세분."""

    CLOUD_MID = "cloud_mid"
    """Claude Sonnet 4.6 등 (구 LLMTier.MID). ~$0.003/$0.015."""

    CLOUD_HIGH = "cloud_high"
    """Claude Opus 4.7 / GPT-5 등 (구 LLMTier.HIGH). ~$0.015/$0.075."""


# ──────────────────────────────────────────────────────────────────────────
# 축3: 로컬 모델 패밀리 (2026-05-20 태스크 인지 실측, CostTier.LOCAL + FAST/MID일 때만)
# 그라운딩 데이터: 03a §0.2·§A.0·§B.2 (Phaiakes9 GPU 127.0.0.1, temperature=0).
# ──────────────────────────────────────────────────────────────────────────
class ModelFamily(str, Enum):
    """로컬 모델 패밀리 축 — 로컬에서 *어느 패밀리*(수학 vs 일반)인가? (03a §0.2·§A.0)

    크기(축2)에 앞서 결정한다 — 같은 "FAST"라도 패밀리가 가리키는 실제 모델이
    다르기 때문(MATH×FAST=qwen2-math:1.5b vs GENERAL×FAST=qwen2.5:3b, 03a §A.0).
    QUALITY(27b)는 양 패밀리를 포괄하므로 패밀리 무관(축3 미적용, 03a §A.0).
    """

    MATH = "math"
    """qwen2-math — 수학 계산·풀이·증명. 산술 7b 100%·1.5b 87.5% (03a §A.0)."""

    GENERAL = "general"
    """qwen2.5 — NLP: 추출·정규화·매칭·분류. match 3b 100%·translate 7b 75% (03a §A.0)."""

    VISION = "vision"
    """qwen3-vl — 멀티모달(이미지+텍스트). 손글씨/인쇄 수식·그래프 인식(L5 OCR Phase C+).
    `requires_vision=True` 요청만 이 패밀리로 라우팅된다(수학/일반 텍스트와 직교)."""


# ──────────────────────────────────────────────────────────────────────────
# 축2: 로컬 모델 크기 (2026-05-19 벤치 라인업, CostTier.LOCAL일 때만 적용)
# 그라운딩 데이터: 03a §A.1 (Phaiakes9 / Radeon 8060S / Ollama 0.24.0).
# 실제 모델은 (패밀리 축3 × 크기 축2)로 결정 — 03a §A.0 매트릭스 lookup.
# ──────────────────────────────────────────────────────────────────────────
class LocalModelTier(str, Enum):
    """로컬 모델 크기 축 — 로컬에서 *어느 크기* 모델인가? (03a §A.1)"""

    FAST = "fast"
    """MATH=qwen2-math:1.5b / GENERAL=qwen2.5:3b — p50≈1,010ms, SLA PASS, 동기 즉답."""

    MID = "mid"
    """MATH=qwen2-math:7b / GENERAL=qwen2.5:7b — p50≈3,918ms, 동기 가능(즉답엔 길다)."""

    QUALITY = "quality"
    """qwen3.5:27b (패밀리 무관) — p50 13,886ms, 병렬 미작동(GPU 단일 점유) → 비동기 전용."""


# ──────────────────────────────────────────────────────────────────────────
# 5개 핵심 호출지점 (03a §B.2 — PRD가 식별한 LLM 필수 호출지점 ①~⑤)
# ──────────────────────────────────────────────────────────────────────────
class CallSite(str, Enum):
    """LLM 핵심 호출지점 식별자 (03a §B.2, 03 문서 "LLM 핵심 호출지점")."""

    CONCEPT_EXTRACT = "extract"
    """① 개념 추출 — 기본 FAST. 반복성 높음·캐싱 적중률 큼."""

    DEEP_REASON = "depth"
    """② 깊이 추론 — 기본 MID(난이도 hard↑면 QUALITY/CLOUD). 다단계."""

    TRANSLATE_NORMALIZE = "translate"
    """③ 번역·정규화 — 기본 FAST. 표기 통일·동의어 정규화는 경량."""

    CONCEPT_ID_MATCH = "match"
    """④ 개념 ID 매칭 — 기본 FAST(모호하면 MID). 매칭 실패 → 사람 검수."""

    SELF_VERIFY = "self_verify"
    """⑤ 자기검증 — QUALITY 비동기 전용. 환각 방어 ③. 추가 비용 → 샘플링."""


# ──────────────────────────────────────────────────────────────────────────
# 입력: RoutingRequest (기존 llm-architect.md 모델 확장, 03a §B.1·§G)
# ──────────────────────────────────────────────────────────────────────────
class RoutingRequest(BaseModel):
    """라우팅 결정의 입력 신호 (03a §B.1 입력 신호 표)."""

    model_config = ConfigDict(
        # 추가 필드 금지 — 모델이 스키마의 단일 진실 (data-pipeline 컨벤션)
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    task_type: str = Field(
        ...,
        description=(
            "작업 유형 — explain/diagnose/coach/generate/verify/prove/"
            "extract/match/translate/self_verify (03a §B.1)"
        ),
    )
    difficulty: str = Field(
        ...,
        description="난이도 — easy/medium/hard/killer. 축1·축2 동시 영향 (03a §B.1)",
    )
    requires_reasoning: bool = Field(
        ...,
        description="다단계 추론 필요 여부 — MID/QUALITY·CLOUD 승급 신호",
    )
    student_subscription: str = Field(
        ...,
        description="구독 — free/basic/premium/gifted. CLOUD 승급 가드 (03a §E.2)",
    )
    max_latency_ms: int = Field(
        default=30000,
        description="SLA 한도(ms). <2000이면 사실상 FAST 강제 (03a §B.1·C.2 규칙3)",
        ge=0,
    )
    budget_krw: float = Field(
        default=0.0,
        description=(
            "이 호출의 클라우드 잔여 예산(원). 0 이하면 LOCAL 강제 "
            "(구 budget_cents 개명, 03a §B.1·§E.2)"
        ),
    )
    # ── 신규 신호 (03a §B.1·§G) ──
    sync: bool = Field(
        default=True,
        description="True=동기 즉답 요구, False=비동기 허용. QUALITY 게이팅의 핵심",
    )
    conversation_phase: str | None = Field(
        default=None,
        description=(
            "L4 대화 상태 — greeting/probing/hint/solution_reveal/followup. "
            "즉답성 판단 (03a §B.1)"
        ),
    )
    call_site: CallSite | None = Field(
        default=None,
        description="5개 핵심 호출지점 식별 ①~⑤ (없으면 일반 호출, 03a §B.2)",
    )
    requires_vision: bool = Field(
        default=False,
        description=(
            "멀티모달(이미지) 입력 필요 여부 — True면 LOCAL Qwen3-VL(VISION 패밀리)·FAST·동기로 "
            "직행한다(수학/일반 텍스트 라우팅 규칙 무시). L5 OCR Qwen3-VL 인식기용(03a 확장)."
        ),
    )
    # ── 데이터 등급 축 (EOS-59 — 법적 신호. 비용·품질 신호와 성격이 다르다) ──
    data_licenses: tuple[LicenseType, ...] = Field(
        default=DEFAULT_DATA_LICENSES,
        min_length=1,
        description=(
            "이 호출의 프롬프트에 실리는 *자료*의 라이선스 목록(등급 축). 클라우드 티어는 "
            "국외 법인 프로바이더이므로, 반출이 허용되지 않는 자료(AIHub 등)가 하나라도 "
            "있으면 `l3.data_export_policy.guard_data_export`가 LOCAL로 강등한다. "
            "미지정이면 UNKNOWN(=미확인)이라 fail-closed로 차단된다 — 프로덕션 호출부는 "
            "소스 스캔 게이트가 명시를 강제한다(EOS-59 ③)."
        ),
    )

    @model_validator(mode="after")
    def _validate_data_licenses_non_empty(self) -> RoutingRequest:
        """등급 목록은 비어 있을 수 없다 — "자료 없음"과 "미확인"을 구분하지 못하게 만든다.

        `min_length=1`이 스키마 차원에서 이미 막지만, `model_construct`(검증 우회) 경로가
        생기더라도 빈 목록이 조용히 통과하지 않도록 한 겹 더 둔다. 게이트 쪽
        (`export_judgment(())`)도 빈 목록을 UNVERIFIED로 떨어뜨려 3중으로 fail-closed다.
        """
        if not self.data_licenses:
            raise ValueError(
                "data_licenses는 비어 있을 수 없다 — 자료 등급 미상은 "
                "LicenseType.UNKNOWN으로 *명시*한다(빈 목록은 '자료 없음'과 구분 불가)"
            )
        return self


# ──────────────────────────────────────────────────────────────────────────
# 출력: RoutingDecision — 세 축을 합성한 결정 객체 (03a §G)
# ──────────────────────────────────────────────────────────────────────────
class RoutingDecision(BaseModel):
    """라우팅 결정 — (축1, 축3, 축2) 합성 + 모드·근거·추정치 (03a §G).

    불변식 (03a §G·§0.1·§0.2, after-validator로 강제):
      1. cost_tier == LOCAL  ⟺  local_model is not None
      2. cost_tier in {CLOUD_MID, CLOUD_HIGH}  ⟺  local_model is None
      3. local_model == QUALITY  ⟹  mode == "async" (27b 동기 불가, 03a §A.1)
      4. local_family is not None  ⟺  (cost_tier == LOCAL and local_model in {FAST, MID})
         — 패밀리는 *FAST/MID일 때만* 모델 선택에 영향. QUALITY(27b)는 양 패밀리를
         포괄하므로 패밀리 무관(local_family = None). CLOUD_*도 축3 없음(03a §A.0·§G).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    cost_tier: CostTier = Field(..., description="축1 — 비용·위치 결정")
    local_family: ModelFamily | None = Field(
        default=None,
        description=(
            "축3 — 로컬 모델 패밀리 (cost_tier=LOCAL + FAST/MID일 때만; "
            "QUALITY·CLOUD_*는 None, 03a §A.0·§G)"
        ),
    )
    local_model: LocalModelTier | None = Field(
        default=None,
        description="축2 — 로컬 모델 크기 (cost_tier=LOCAL일 때만, 아니면 None)",
    )
    mode: str = Field(
        default="sync",
        description="sync/async — QUALITY는 async 강제 (03a §A.1·C.2)",
    )
    reason: str = Field(
        default="",
        description="결정 근거 (디버깅·Langfuse 태그용, 03a §F.2)",
    )
    est_latency_ms: int = Field(
        ...,
        description=("예상 지연(ms) — FAST≈1010/MID≈3918/QUALITY≈13886/CLOUD≈가변 " "(03a §A.1)"),
        ge=0,
    )
    est_cost_krw: float = Field(
        default=0.0,
        description="예상 비용(원) — 로컬=0, 클라우드 추정 (03a §E)",
        ge=0.0,
    )
    # ── 데이터 등급 게이트의 *작동 신호* (EOS-59 ② — "작동한 비율") ──
    data_export_blocked: bool = Field(
        default=False,
        description=(
            "데이터 등급(법적) 게이트가 이 결정에서 *실제로* 클라우드를 막았는가. "
            "True면 비즈니스 규칙은 클라우드를 원했으나 반출 불가/미확인 자료 때문에 "
            "LOCAL로 강등됐다는 뜻이다. 이미 LOCAL이던 요청은 막을 것이 없었으므로 False "
            "(정상 응답을 '게이트가 일했다'로 오인하지 않기 위한 구분)."
        ),
    )
    data_export_reason: str | None = Field(
        default=None,
        description=(
            "반출 판정 사유 — EXPORT_ALLOWED/EXPORT_PROHIBITED/EXPORT_UNVERIFIED "
            "(`l3.data_export_policy`). None은 '판정 안 함'(라우터를 거치지 않고 직접 조립된 "
            "결정)이며 '허용'이 아니다 — 미상과 통과를 구분한다."
        ),
    )
    # ── 관할 축(ARCH-49)이 읽는 등급 *승계* 필드 ──
    data_licenses: tuple[LicenseType, ...] = Field(
        default=(),
        description=(
            "이 결정이 판정 대상으로 삼은 자료 등급 목록 — `RoutingRequest.data_licenses`를 "
            "그대로 승계한다. 반출 *가부*(`data_export_reason`)만으로는 답할 수 없는 질문이 "
            "있어서 싣는다: `l3.provider_jurisdiction`은 '반출해도 되는가'가 아니라 '**어느 "
            "관할로** 반출해도 되는가'를 묻고, 그 답은 등급별로 다르다(CN은 합성 프로브만). "
            "빈 튜플은 '자료 없음'이 아니라 **'미선언'**이며, 추가 좁힘이 있는 관할(CN·미확인 "
            "공급사)은 미선언을 fail-closed로 차단한다 — 라우터를 거치지 않고 손으로 조립된 "
            "결정이 중국 서버로 새어 나가지 않게 하는 기본값이다. 좁힘이 없는 관할(US·현행 "
            "Anthropic 경로)은 이 필드를 요구하지 않아 **기존 호출부 동작은 무변경**이다."
        ),
    )

    @model_validator(mode="after")
    def _validate_axis_invariants(self) -> RoutingDecision:
        """세 축 불변식 강제 (03a §G·§0.1·§0.2).

        use_enum_values=True 환경에서도 동작하도록 enum/문자열 양쪽을 비교한다.
        """
        # use_enum_values=True면 필드가 문자열 값일 수 있으므로 정규화
        cost_value = (
            self.cost_tier.value if isinstance(self.cost_tier, CostTier) else self.cost_tier
        )
        local_value = (
            self.local_model.value
            if isinstance(self.local_model, LocalModelTier)
            else self.local_model
        )
        family_value = (
            self.local_family.value
            if isinstance(self.local_family, ModelFamily)
            else self.local_family
        )

        is_local = cost_value == CostTier.LOCAL.value

        # 불변식 1·2: LOCAL ⟺ local_model 존재
        if is_local and local_value is None:
            raise ValueError(
                "불변식 위반: cost_tier=LOCAL이면 local_model이 반드시 있어야 한다 "
                "(03a §G 불변식 1)"
            )
        if (not is_local) and local_value is not None:
            raise ValueError(
                f"불변식 위반: cost_tier={cost_value}(CLOUD_*)이면 local_model은 "
                f"None이어야 한다(현재 {local_value!r}, 03a §G 불변식 2)"
            )

        # 불변식 3: QUALITY ⟹ async
        if local_value == LocalModelTier.QUALITY.value and self.mode != "async":
            raise ValueError(
                f"불변식 위반: local_model=QUALITY(27b)는 mode='async'여야 한다 "
                f"(현재 {self.mode!r}, 동기 불가 03a §A.1·§G 불변식 3)"
            )

        # 불변식 4: local_family는 LOCAL + FAST/MID일 때만 존재 (QUALITY·CLOUD_*는 None)
        #   — QUALITY(27b)는 양 패밀리 포괄, CLOUD_*는 범용이라 축3 없음(03a §A.0·§G)
        family_applicable = is_local and local_value in (
            LocalModelTier.FAST.value,
            LocalModelTier.MID.value,
        )
        if family_applicable and family_value is None:
            raise ValueError(
                "불변식 위반: cost_tier=LOCAL + local_model in {FAST, MID}이면 "
                "local_family(MATH/GENERAL)가 반드시 있어야 한다 (03a §A.0·§G 불변식 4)"
            )
        if (not family_applicable) and family_value is not None:
            raise ValueError(
                f"불변식 위반: QUALITY 또는 CLOUD_*에서는 local_family가 None이어야 한다 "
                f"(현재 {family_value!r}; QUALITY는 패밀리 무관, 03a §A.0·§G 불변식 4)"
            )

        # 불변식 5: 데이터 등급 게이트는 *강등만* 한다 (EOS-59 단방향성)
        #   — "게이트가 막았다"고 표시된 결정이 클라우드로 나가 있으면 그 자체가 모순이다.
        #     게이트가 우회됐거나(치명적) 플래그가 잘못 붙은(관측 오염) 두 경우뿐이고,
        #     둘 다 조용히 넘어가면 안 된다. 이 불변식이 단방향성을 *구조로* 봉인한다.
        if self.data_export_blocked and not is_local:
            raise ValueError(
                f"불변식 위반: data_export_blocked=True인데 cost_tier={cost_value}(국외 티어)다 "
                "— 데이터 등급 게이트는 강등만 하며, 막힌 요청은 반드시 LOCAL이어야 한다 "
                "(EOS-59 단방향성)"
            )

        # 모드 값 자체 검증
        if self.mode not in ("sync", "async"):
            raise ValueError(f"mode는 'sync' 또는 'async'여야 한다(현재 {self.mode!r})")

        return self


# ──────────────────────────────────────────────────────────────────────────
# provider 반환 계약 — 실측 usage + 원시 텍스트 (S1 탈출 게이트 ② 계측 배선)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class Usage:
    """LLM 호출 1건의 *실측* 텔레메트리 — 토큰·지연 (S1 게이트 ② 비용 실측 근거).

    라우터의 *추정*(RoutingDecision.est_latency_ms/est_cost_krw)과 명시적으로 구분되는
    **actual** 값이다 — 추정 vs 실측 구분을 코드가 유지한다(03a §F.2: est_* ↔ 실측 필드).
    provider가 usage를 노출하지 않거나 응답 형태가 예상과 다르면 각 필드는 None이다 —
    값을 *지어내지 않는다*(CLAUDE.md "모르면 모른다고").

    출처: Anthropic `response.usage.input_tokens/output_tokens`, Ollama
    `prompt_eval_count/eval_count`. 지연은 provider가 호출을 감싸 monotonic으로 잰다.
    """

    input_tokens: int | None = None
    """입력(프롬프트) 토큰 수 — provider 응답 usage에서 포착. 미상이면 None."""

    output_tokens: int | None = None
    """출력(생성) 토큰 수 — provider 응답 usage에서 포착. 미상이면 None."""

    latency_ms: float | None = None
    """호출 벽시계 지연(ms) — provider가 time.monotonic()으로 실측. 미측정이면 None."""

    # ── 프롬프트 캐시 축 (EOS-99) ─────────────────────────────────────────
    # `input_tokens`와 **합산 관계가 아니라 배타 관계**다: Anthropic은 캐시로 읽힌 프리픽스를
    # `input_tokens`에서 *빼고* `cache_read_input_tokens`에 따로 센다. 그래서 프롬프트 총
    # 토큰은 `input + cache_read + cache_creation`이고, 적중률의 분모도 그 합이다
    # (`harness/anchor_round_ledger.prompt_cache_rates` 단일 원천 — 여기서 재구현 금지).
    #
    # None의 뜻은 **두 가지이며 이 좌석은 그 둘을 구분하지 않는다** — ⓐ 캐시 개념이 없는
    # provider(Ollama 로컬: prompt_eval_count/eval_count만 노출) ⓑ 응답에 필드가 없거나
    # 형태가 달라 못 읽음. 어느 쪽이든 "0건이었다"가 아니다(미측정 ≠ 0). 0은 **읽었는데
    # 0이었다**는 실측이며, 캐싱 플래그가 켜진 상태의 연속 0은 "켰지만 작동 안 함"이다.
    cache_read_input_tokens: int | None = None
    """캐시에서 *읽힌* 프리픽스 토큰 수(적중 — 약 0.1배 과금). 미상·해당없음이면 None."""

    cache_creation_input_tokens: int | None = None
    """캐시에 *쓰인* 프리픽스 토큰 수(첫 회차 — 약 1.25배 과금). 미상·해당없음이면 None."""


@dataclass(slots=True, frozen=True)
class GenerationResult:
    """`LLMProvider.generate`의 반환형 — 검증 전 원시 텍스트 + 실측 usage.

    ⚠️ 이름 구분: `l3.pipeline.GenerationResult`(라우팅 메타데이터 + 동기/비동기 상태 —
    파이프라인 *오케스트레이션* 결과)와 이름만 같고 **다른 타입**이다. 이 타입은
    provider 경계의 *생성 1회* 결과다(텍스트 + usage). 파이프라인이 이 타입의
    `.text`/`.usage`를 소비해 자기 결과·trace·GenerationLog로 흘린다.

    `text`는 *검증 전 원시 모델 출력*이다 — 03 문서 환각 방어 파이프라인을 통과하기
    전에는 학생에게 직접 노출 금지(CLAUDE.md "LLM 응답을 검증 없이 학생에게 제공 금지").
    `usage`는 provider가 포착한 실측 텔레메트리 — 미지원 provider/테스트 가짜는 None.
    """

    text: str
    """생성 텍스트(검증 전 원시 출력)."""

    usage: Usage | None = None
    """실측 usage — provider가 노출하지 않으면 None(지어내지 않음)."""
