"""교수전략 카탈로그(PedagogyStrategyCard) Pydantic 계약 — 카탈로그 YAML의 형식 게이트.

설계 정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §3(전략 카탈로그 — 필드 소비처
지정표·제거 필드 3종). 오개념(839+원자 전량 카탈로그)·문제 공략 전략(8종 데이터카드)에 비해
교수전략만 `PedagogyStrategy` enum+docstring인 비대칭을 해소하는 *서술 자산*의 계약이다 —
`data/corpus/pedagogy_strategies_v1/*.yaml`(전략 10종·enum 1:1)을 레지스트리
(`l4/pedagogy/strategy_registry.py`)가 적재하기 전에 이 모델이 게이트한다(`pedagogy_pack.py`의
`PedagogyPack` 시더 계약 선례 미러).

⚠️ 용어 3축 주의(04g §1): 이 카탈로그의 "전략"은 **교수전략**(`PedagogyStrategy` — 교사가 어떻게
가르칠까)이다. 학생의 문제 공략 전략(`StrategyNode`·`strategy.analogy`=유추)과 같은 영단어·다른
개념이므로 혼동 금지.

────────────────────────────────────────────────────────────────────────────
필드 원칙 — 소비처를 지정 못 하는 필드는 착시·금지 (04g §3.2)
────────────────────────────────────────────────────────────────────────────
StudentSignals가 "항상 None인 필드는 착시"(04d §2.1)라며 필드를 거부한 것과 동형으로, 이 계약의
9필드는 각각 실재 소비처가 지정되어 있다(각 Field description에 병기). 필드 추가는 소비처 실재
증명 전제 — 필드셋은 `tests/backend/schema/test_pedagogy_strategy_schema.py`가 리터럴로 동결한다.

────────────────────────────────────────────────────────────────────────────
제거 필드 3종 — 정본 이중화 방지 (04g §3.3 — 부재를 테스트로 동결)
────────────────────────────────────────────────────────────────────────────
외부 프레임워크의 다음 3계열은 *의도적으로 없다*(재제안 방지 — 04g §8 영구 기록과 이중 방어):
  ① AI 추천 점수(ai_score/recommendation_score) — 정적 점수는 bandit 무정보 사전 Beta(1,1)를
     데이터 없이 오염. 학습된 점수의 유일 좌석 = PED-03 posterior.
  ② 기계 판정용 사용/금지 조건(forbidden_conditions) — 허용의 정본은 팩 `forbidden_modes`+
     `gate()` 2축. 카탈로그에 또 두면 truth source 2개(유지보수 지옥 진입점).
  ③ 선행/후속 전략·페이딩(predecessor/successor/fading) — 페이딩 정본은 팩 `fading_schedule`
     (k_type 축). 전략 간 선후를 여기 넣으면 페이딩이 2곳에 산다.
부재는 `extra="forbid"`(런타임 — YAML에 해당 키가 오면 거부)와 스키마 동결 테스트(정적 —
model_fields에 계열 이름 부재 assert)가 이중으로 지킨다.

────────────────────────────────────────────────────────────────────────────
카탈로그 불변식 (`@model_validator(mode="after")` — 저작 실수를 형식 게이트에서 거부)
────────────────────────────────────────────────────────────────────────────
카탈로그는 *데이터*(코드 아님)라 사람이 YAML로 저작한다. `PedagogyPack` 불변식 선례 미러:
  (a) 폐쇄 어휘 위반 거부 — `target_grade_bands`(GRADE_BAND_VOCAB 4종)·`difficulty_range`
      (DIFFICULTY_VOCAB 3종)·`suitable_error_types`(ERROR_TYPE_VOCAB 6종 — 오개념 코퍼스
      `error_type` 정본 어휘, `docs/data/misconception_catalog_v1.md`). 오탈자·미정의 값 차단.
  (b) `research_basis` 최소 1건 — 근거 없는 전략 서술 금지(각 항목 빈 문자열도 거부).
  (c) 빈 문자열 거부 — `name_ko`·`description`·`usage_notes`(str_strip_whitespace 후 검사).
  (d) select() 필터 축(`target_grade_bands`·`difficulty_range`·`target_k_types`)은 비어 있으면
      거부 — 빈 필터 축은 후보 필터에서 그 전략을 영원히 제외시키는 저작 실수다. 반면
      `suitable_error_types`는 빈 리스트 허용(R2 정밀화 미참여 신호 — 정직한 공백).
  (e) 각 리스트의 중복 항목 거부 — 어휘 위생(중복은 저작 노이즈).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import KnowledgeType, PedagogyStrategy

# ──────────────────────────────────────────────────────────────────────────
# 폐쇄 어휘 3종 (FORBIDDEN_MODE_VOCAB 패턴 미러 — 확장은 상수 갱신+동결 테스트 갱신 전제)
# ──────────────────────────────────────────────────────────────────────────
# 학교급 4종 — `target_grade_bands` 항목의 통제 어휘. 소비처는 select() 후보 필터(PED-06 §4·
# 생산자 `UserProfile.grade`).
GRADE_BAND_VOCAB: frozenset[str] = frozenset(
    {
        "초등",
        "중학",
        "고등",
        "대학",
    }
)

# 문항 난이도 3종 — `difficulty_range` 항목의 통제 어휘. 오개념 카탈로그 `difficulty`('상/중/하')
# 와 동일 어휘 재사용(04g §3.2 — 새 어휘 축 신설 금지).
DIFFICULTY_VOCAB: frozenset[str] = frozenset(
    {
        "상",
        "중",
        "하",
    }
)

# 오류 유형 6종 — `suitable_error_types` 항목의 통제 어휘. 정본은 오개념 코퍼스의 `error_type`
# 6종(`docs/data/misconception_catalog_v1.md` — atom_graph_v1 `misconception_type` 실 데이터 값과
# 일치 확인함). ⚠️ "정의·표기오류"는 가운뎃점 포함 *1개* 유형이다(정의 오류+표기 오류 통합 축).
ERROR_TYPE_VOCAB: frozenset[str] = frozenset(
    {
        "개념혼동",
        "절차오류",
        "정의·표기오류",
        "과잉일반화",
        "직관오류",
        "역방향오류",
    }
)


# ──────────────────────────────────────────────────────────────────────────
# 핵심: PedagogyStrategyCard (교수전략 1종의 카탈로그 항목 = 전략 카드 원천)
# ──────────────────────────────────────────────────────────────────────────
class PedagogyStrategyCard(BaseModel):
    """교수전략 카탈로그 항목 — 전략 1종의 서술 자산(YAML 파일당 1건·enum 1:1).

    9필드 전부에 소비처가 지정되어 있다(04g §3.2 소비처 지정표 — 각 Field description 병기).
    카탈로그는 **서술 자산**이다: 로직(선택·게이트)은 코드(`runtime_selector`)가, 서술(이름·
    근거·적합성·사용 주의)은 이 데이터가 맡는다. 특히 `usage_notes`는 **사람 서술 전용**이며
    기계 배선 금지다 — 기계 판정(허용/금지)의 정본은 팩 `forbidden_modes`+`gate()` 2축이다.

    제거 필드 3종(AI 추천 점수·기계 판정용 금지조건·선행/후속·페이딩)의 부재 근거는 04g §3.3
    참조(모듈 docstring 요약) — 부재 자체를 스키마 동결 테스트가 검사한다.
    """

    model_config = ConfigDict(
        # 추가 필드 금지 — 계약의 단일 진실(YAML 오타 키·제거 필드 3종 재유입 차단)
        extra="forbid",
        # 직렬화·검증 후 enum 값 그대로(strategy가 "DIRECT" 문자열로 → registry dict 키 정합)
        use_enum_values=True,
        # 문자열 양끝 공백 제거(YAML `|` 블록 스칼라의 후행 개행 제거 — 팩 계약 선례)
        str_strip_whitespace=True,
    )

    # 카탈로그 PK 축 = 교수전략(10종과 1:1). use_enum_values=True라 검증 후 문자열 값이 된다.
    strategy: PedagogyStrategy = Field(
        ...,
        description="교수전략(폐쇄 10종·파일당 1·유일) — 소비처: registry 키·enum 1:1 동결 테스트",
    )
    name_ko: str = Field(
        ...,
        description=(
            "한국어 표기명(비어 있으면 거부) — 소비처: 전략 카드(prompt_assembler 계층)·L5 표기"
        ),
    )
    description: str = Field(
        ...,
        description="1~2문장 설명 — 소비처: 전략 카드·문서화",
    )
    research_basis: list[str] = Field(
        ...,
        description=(
            "연구 근거 인용(1줄씩·최소 1건 — 저자·연도·효과명 수준, 세부 날조 금지) — "
            "소비처: 전략 카드(요약 1줄만 주입 — attention 절약)·문서화"
        ),
    )
    target_grade_bands: list[str] = Field(
        ...,
        description="적용 학교급(GRADE_BAND_VOCAB 폐쇄 4종) — 소비처: select() 후보 필터(PED-06)",
    )
    difficulty_range: list[str] = Field(
        ...,
        description=(
            "적합 문항 난이도(DIFFICULTY_VOCAB 폐쇄 3종) — 소비처: select() 후보 필터(PED-06)"
        ),
    )
    target_k_types: list[KnowledgeType] = Field(
        ...,
        description=(
            "적용 지식유형(KnowledgeType 7종) — 소비처: select() 후보 필터"
            "(k_type_resolver 산출 대조)"
        ),
    )
    suitable_error_types: list[str] = Field(
        default_factory=list,
        description=(
            "적합 오류 유형(ERROR_TYPE_VOCAB 폐쇄 6종 — 오개념 error_type 정본 어휘). "
            "빈 리스트 = R2 정밀화 미참여(정직한 공백) — 소비처: select() R2 정밀화"
            "(오개념 가설 대조)"
        ),
    )
    usage_notes: str = Field(
        ...,
        description=(
            "사용·금지 조건·기대 효과의 **사람 서술 전용** 필드 — 기계 배선 금지"
            "(기계 판정 정본은 팩 forbidden_modes+gate() 2축·04g §3.3)"
        ),
    )

    # ── 불변식 ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _enforce_catalog_invariants(self) -> PedagogyStrategyCard:
        """카탈로그 불변식 (a)~(e) 강제 — 저작 실수·어휘 오염 항목을 거부한다.

        분기 (a)~(e)는 모듈 docstring 참조. use_enum_values=True라 `self.strategy`는 이미
        문자열 값이므로 오류 메시지에 그대로 담는다.
        """
        # (c) 빈 문자열 거부 — str_strip_whitespace=True 이후 검사라 공백-만 문자열도 걸린다.
        for field_name, value in (
            ("name_ko", self.name_ko),
            ("description", self.description),
            ("usage_notes", self.usage_notes),
        ):
            if not value:
                raise ValueError(
                    f"카탈로그 불변식 위반(c): strategy={self.strategy}의 {field_name}가 "
                    "비었습니다 — 서술 자산의 필수 서술 필드는 비워둘 수 없습니다."
                )

        # (b) research_basis 최소 1건 + 각 항목 비어있지 않음 — 근거 없는 전략 서술 금지.
        if not self.research_basis:
            raise ValueError(
                f"카탈로그 불변식 위반(b): strategy={self.strategy}의 research_basis가 "
                "비었습니다 — 연구 근거 인용을 최소 1건 담아야 합니다(저자·연도·효과명 수준)."
            )
        if any(not item for item in self.research_basis):
            raise ValueError(
                f"카탈로그 불변식 위반(b): strategy={self.strategy}의 research_basis에 빈 "
                "항목이 있습니다 — 각 인용은 비어 있지 않은 1줄이어야 합니다."
            )

        # (d) select() 필터 축은 비어 있으면 거부 — 빈 필터 축은 그 전략을 후보에서 영구 제외
        #     시키는 저작 실수다(suitable_error_types만 빈 리스트 허용 — R2 미참여 신호).
        for field_name, seq in (
            ("target_grade_bands", self.target_grade_bands),
            ("difficulty_range", self.difficulty_range),
            ("target_k_types", self.target_k_types),
        ):
            if not seq:
                raise ValueError(
                    f"카탈로그 불변식 위반(d): strategy={self.strategy}의 {field_name}가 "
                    "비었습니다 — select() 후보 필터 축은 최소 1개 값을 선언해야 합니다"
                    "(전 범위 적용이면 어휘 전종을 명시)."
                )

        # (a) 폐쇄 어휘 위반 거부 — 오탈자·미정의 값 차단(FORBIDDEN_MODE_VOCAB 검사 선례).
        for field_name, seq, vocab in (
            ("target_grade_bands", self.target_grade_bands, GRADE_BAND_VOCAB),
            ("difficulty_range", self.difficulty_range, DIFFICULTY_VOCAB),
            ("suitable_error_types", self.suitable_error_types, ERROR_TYPE_VOCAB),
        ):
            unknown = [item for item in seq if item not in vocab]
            if unknown:
                raise ValueError(
                    f"카탈로그 불변식 위반(a): strategy={self.strategy}의 {field_name}에 "
                    f"미정의 값이 있습니다: {unknown}. 허용 어휘: {sorted(vocab)}."
                )

        # (e) 중복 항목 거부 — 어휘 위생(중복은 저작 노이즈·필터 의미 없음).
        for field_name, raw_seq in (
            ("research_basis", self.research_basis),
            ("target_grade_bands", self.target_grade_bands),
            ("difficulty_range", self.difficulty_range),
            ("target_k_types", [str(k) for k in self.target_k_types]),
            ("suitable_error_types", self.suitable_error_types),
        ):
            if len(raw_seq) != len(set(raw_seq)):
                raise ValueError(
                    f"카탈로그 불변식 위반(e): strategy={self.strategy}의 {field_name}에 "
                    "중복 항목이 있습니다 — 각 값은 한 번만 선언합니다."
                )

        return self


# ──────────────────────────────────────────────────────────────────────────
# 스키마 동결 (PED-05 — 필드 추가는 "소비처 실재 증명" 전제)
# ──────────────────────────────────────────────────────────────────────────
# `PedagogyStrategyCard`의 9필드와 폐쇄 어휘 3종(GRADE_BAND_VOCAB·DIFFICULTY_VOCAB·
# ERROR_TYPE_VOCAB)·제거 필드 3계열의 *부재*는 PED-05에서 동결됐다. 변경 시
# `tests/backend/schema/test_pedagogy_strategy_schema.py`의 동결 리터럴을 함께 갱신한다
# (`test_pedagogy_dsl_schema_freeze.py` 선례).

__all__ = [
    "DIFFICULTY_VOCAB",
    "ERROR_TYPE_VOCAB",
    "GRADE_BAND_VOCAB",
    "PedagogyStrategyCard",
]
