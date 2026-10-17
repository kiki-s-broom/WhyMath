"""L6 수능(정시) 모드 게이팅 로직 — 적격성·우선순위·선별.

이 모듈은 정시(수능) 응시 페르소나에게 *어떤* 기존 문항을 수능 모드로 노출할지 결정한다.
**오버레이 모델**(RT 트랙 게이팅 `l6/retake/gating.py`와 동형): 새 enum·concept 노드·Alembic
마이그레이션을 만들지 않고, 기존 L1 `Problem`의 필드(`exam_type`·`exam_authority_weight`·
`signature_patterns`·`persona_fit`·`difficulty_overall`·`source_type`)만 *재사용*하는 순수
결정 로직이다. 부수효과 없음(I/O·LLM 호출 없음)·결정적(deterministic).

공개 API 4종(출제 범위 정의는 `scope.py` — 게이트 ②-c와 api의 SQL 사전필터가 같은 접두어 상수를
읽는다):
  - `is_suneung_eligible(problem, persona, *, min_fit)` — 이 문항을 이 페르소나에게 수능
    모드로 노출해도 되는가(불리언 게이트).
  - `suneung_priority(problem)` — 노출 우선순위 가중치(높을수록 먼저). 교수학 근거 반영.
  - `select_suneung_items(problems, persona, *, min_fit, limit)` — 적격 필터 → 우선순위
    내림차순 안정정렬 → limit 적용.
  - `SUNEUNG_PERSONAS`·`METADATA_ONLY_SOURCES`·`SUNEUNG_EXAM_TYPES`·`SUNEUNG_DEFAULT_MIN_FIT`
    — 게이팅 상수(아래 docstring에 근거). `SUNEUNG_EXAM_TYPES`는 S2-06(수능 적응 추천)에서,
    `SUNEUNG_DEFAULT_MIN_FIT`는 S3-17(수능 SQL 사전필터 persona_fit 확장)에서 api의 SQL
    사전축소가 같은 신호 집합·임계값을 참조해야 해서 공개로 승격했다(정본은 여전히 이 모듈).

레이어 규칙(CLAUDE.md): L6→L1만 의존(`schema.problem`·`schema.enums`). L4/L2/L3를 import하지
않는다 — 이 모듈은 기존 `Problem` 필드의 *존재·값*만 보므로 하위 카탈로그·검증자·모델이
불필요하다. L6은 아무도 import하지 않는 최상위 소비자다(역방향 의존 부재).

use_enum_values=True 주의: `Problem`은 `ConfigDict(use_enum_values=True)`라 직렬화·구성
경로에 따라 `source_type`·`exam_type`이 *문자열 값*일 수 있고 `persona_fit`의 *키*도 문자열일
수 있다. 따라서 enum 비교 시 항상 enum/문자열 양쪽을 정규화해 비교한다(`schema/problem.py`의
`_enforce_copyright_no_body_for_metadata_sources` validator·`l6/_shared.py` 패턴 답습).

Rule of three — 추출 완료(`l6/_shared.py`): `METADATA_ONLY_SOURCES`와 정규화 헬퍼
(`_source_value`·`_persona_fit`)는 본래 RT 트랙(`l6/retake/gating.py`)과 *의도적으로*
중복했다(RT 파일을 건드리지 않아 무회귀를 보장하려는 선택). 학교진도가 *세 번째* L6 모드로
들어오면서 그 중복을 `l6/_shared.py`로 통합했다 — 이 모듈은 이제 `_shared.is_exposable`
(저작권 게이트)·`_shared.normalize_enum_value`(enum 정규화)·`_shared.persona_fit`을 호출한다.
`METADATA_ONLY_SOURCES`는 기존 import 경로(`l6.suneung.gating.METADATA_ONLY_SOURCES`)와
테스트 호환을 위해 `_shared`에서 *재노출*한다(아래).
"""

from __future__ import annotations

from collections.abc import Iterable

from whymath_backend.l6 import _shared
from whymath_backend.l6._shared import METADATA_ONLY_SOURCES
from whymath_backend.l6.suneung.scope import ScopeVerdict, suneung_scope_verdict
from whymath_backend.schema.enums import ExamType, Persona
from whymath_backend.schema.problem import Problem

# 저작권 노출 게이트 차단 집합(평가원·EBS·교과서)을 L6 공용 모듈에서 *재노출*한다 —
# 기존 import 경로(`l6.suneung.gating.METADATA_ONLY_SOURCES`)·테스트 호환을 위해 이름을 유지.
# 정의 정본은 `l6/_shared.py`(Rule of three 추출 완료). `__all__`에도 그대로 둔다.
__all__ = [
    "METADATA_ONLY_SOURCES",
    "SUNEUNG_DEFAULT_MIN_FIT",
    "SUNEUNG_EXAM_TYPES",
    "SUNEUNG_PERSONAS",
    "is_suneung_eligible",
    "select_suneung_items",
    "suneung_priority",
]

# ──────────────────────────────────────────────────────────────────────────
# 게이팅 상수
# ──────────────────────────────────────────────────────────────────────────
SUNEUNG_PERSONAS: frozenset[Persona] = frozenset(
    {Persona.A_일반고고3, Persona.B_자사고N수, Persona.C_검정고시N수}
)
"""수능(정시) 모드의 대상 페르소나 — 정시(수능)로 대학에 가는 응시생.

PRD 5종 페르소나(`enums.Persona`) 중 *정시(수능)* 트랙에 있는 셋만 수능 모드 대상이다:
  - `A_일반고고3` — 일반고 고3(MVP·시장 최대·수능 정면 대상),
  - `B_자사고N수` — 자사고 출신 N수생(정시 재도전·결제 최대 세그먼트),
  - `C_검정고시N수` — 검정고시 N수생(정시 의존도 높음·수학 의존 100%).
나머지 둘은 *정시(수능) 중심이 아니므로* 제외한다:
  - `D_학종고2` — 학생부종합(수시) 중심으로 세특·자유연구가 핵심이라 정시 모드 대상이 아니다
    (`Persona.D_학종고2` docstring: "v1.5·세특/자유연구"),
  - `E_홈스쿨링영재` — 영재(올림피아드·심화) 트랙으로 수능 기출 유형 숙달이 주목적이 아니다
    (`Persona.E_홈스쿨링영재` docstring: "v2.0·가치 최대").
"""

# 저작권 노출 게이트 차단 집합 `METADATA_ONLY_SOURCES`(평가원·EBS·교과서)는 L6 공용 모듈
# `l6/_shared.py`에 정본을 두고, 이 파일 상단에서 *재노출*한다(Rule of three 추출 완료).
# 수능 모드 특히 중요: 평가원 기출 본문은 절대 노출 불가 → `_shared.is_exposable`가 원천 차단.

# 수능 적합 신호로 인정하는 시험 유형(권위 있는 기출 유형) — 수능·모평·학평.
# 정시 대비의 핵심은 *평가원·교육청 기출 유형*에 대한 숙달이므로 이 셋을 적합 신호로 본다
# (EBS교재·N제·자체생성은 그 자체로는 "기출 유형" 신호가 아니라 다른 적합 신호로 판정).
# (수능 전용 신호라 공용 추출 대상이 아니다 — 이 모듈에 남긴다.)
# S2-06에서 비공개(_SUNEUNG_EXAM_TYPES) → 공개로 승격: api의 수능 후보 SQL 사전축소가
# 같은 집합을 참조한다(중복 재정의 방지 — 정본은 이 모듈 하나).
SUNEUNG_EXAM_TYPES: frozenset[ExamType] = frozenset({ExamType.수능, ExamType.모평, ExamType.학평})

# persona_fit 적합도 임계값(기본값) — is_suneung_eligible·select_suneung_items의 min_fit 기본과
# api/me.py의 수능 SQL 사전필터(S3-17)가 *같은 이름으로 공유*하는 단일 권위. 게이트(파이썬)와
# SQL(사전축소)이 서로 다른 임계를 쓰면 "SQL은 통과시켰는데 게이트가 막는다"류 이원화가 생긴다
# (METADATA_ONLY_SOURCES를 api가 그대로 재사용하는 것과 동일 원칙).
SUNEUNG_DEFAULT_MIN_FIT: float = 0.5


def is_suneung_eligible(
    problem: Problem,
    persona: Persona = Persona.A_일반고고3,
    *,
    min_fit: float = SUNEUNG_DEFAULT_MIN_FIT,
) -> bool:
    """이 문항을 이 페르소나에게 수능(정시) 모드로 노출해도 되는가(불리언 게이트).

    판정 순서(앞 게이트에서 막히면 즉시 False):
      ① 대상 페르소나 게이트 — `persona ∈ SUNEUNG_PERSONAS`(A·B·C)가 아니면 False(비응시).
         D(학종·수시 중심)·E(영재)는 정시 모드 대상이 아니다.
      ② 저작권 노출 게이트 — `source_type`이 본문 미보유 출처(평가원/EBS/교과서)면 False.
         학생 노출 불가 본문이므로 *대상 페르소나라도* 막힌다(CLAUDE.md 우선순위 #2 — 법적).
         **수능 모드 특히 중요**: 평가원 기출 본문은 절대 노출 불가 → 자체생성 동등문제만.
      ②-c 출제 범위 게이트 — 목표 학년도 수능의 출제 범위(`scope.py` · 2028학년도 = 2022 개정
         대수·미적분Ⅰ·확률과 통계) 안의 성취기준 코드를 하나도 못 가진 문항은 False. 코드를 모르는
         문항(`UNKNOWN`)도 False다(fail-closed). **신호(③)가 아니라 선결 조건**이다 — 시그니처
         패턴이나 persona_fit이 높아도 범위 밖 문항은 수능 적격이 아니다(EOS-31: persona_fit은
         난이도 구간만의 함수라 학년·범위를 가르지 못했다).
      ③ 수능 적합 신호 — 다음 중 *하나라도* 참이면 True, 아니면 False:
           (a) `exam_type ∈ {수능, 모평, 학평}`(권위 있는 기출 유형 문항), **또는**
           (b) `signature_patterns`가 비어 있지 않음(한국 수능 시그니처 패턴 보유), **또는**
           (c) `persona_fit[persona] >= min_fit`(이 페르소나 적합도가 임계 이상).

    Args:
      problem: 후보 문항(L1 `Problem`). `achievement_standard_codes`(비영속)가 주입돼 있어야 ②-c를
        통과할 수 있다.
      persona: 노출 대상 페르소나(기본 A_일반고고3 — MVP 정시 정면 대상).
      min_fit: persona_fit 임계값(기본 0.5 — "절반 이상 적합"). 0~1 척도.

    Returns:
      수능 모드 노출 적격이면 True.

    use_enum_values=True 주의: source_type·exam_type·persona_fit 키가 문자열일 수 있어
    L6 공용 헬퍼(`_shared.is_exposable`·`_shared.normalize_enum_value`·`_shared.persona_fit`)로
    정규화해 비교한다.
    """
    # ① 대상 페르소나 게이트.
    if persona not in SUNEUNG_PERSONAS:
        return False

    # ② 저작권 노출 게이트 — 본문 미보유 출처는 노출 불가(대상 페르소나라도 차단).
    #    수능 모드 핵심: 평가원 기출 본문은 절대 노출 불가 → 여기서 원천 차단.
    if not _shared.is_exposable(problem):
        return False

    # ②-b 검수 노출 게이트 — 저작권 축과 독립(합치지 않음, PB-03). review_status=approved만 통과.
    if not _shared.is_review_cleared(problem):
        return False

    # ②-c 출제 범위 게이트(EOS-31) — 선결 조건. 성취기준 코드는 비영속 필드라 L5가 주입해야 한다
    #     (미주입이면 `UNKNOWN`으로 거절되어 "범위를 모르는 문항"이 적격으로 새지 않는다).
    if suneung_scope_verdict(problem) is not ScopeVerdict.IN_SCOPE:
        return False

    # ③ 수능 적합 신호 — 기출 유형 / 시그니처 패턴 / 페르소나 적합도 중 하나라도.
    suneung_exam_values = {e.value for e in SUNEUNG_EXAM_TYPES}
    is_exam_signal = _shared.normalize_enum_value(problem.exam_type) in suneung_exam_values
    has_signature = bool(problem.signature_patterns)
    meets_fit = _shared.persona_fit(problem, persona) >= min_fit
    return is_exam_signal or has_signature or meets_fit


def suneung_priority(problem: Problem) -> float:
    """수능 모드 노출 우선순위 가중치 — 높을수록 먼저 노출. 결정적(deterministic).

    교수학 근거(CLAUDE.md 우선순위 #3·#4): 정시(수능) 대비의 핵심은 *권위 있는 기출 유형*의
    숙달과 *한국 수능 시그니처 패턴*의 체화다(수능>모평>학평 순으로 출제 권위가 높고, ㄱㄴㄷ
    합답형·조건 나열·그래프 개형 추론 같은 시그니처 패턴은 수능 고난도 문항의 전형이라 우선
    노출 가치가 크다). 이를 반영해:

      가중치 = (exam_authority_weight|0.0 × 2.0) + (signature_patterns 있으면 +1.0)
               + (difficulty_overall|0.0)

      - `exam_authority_weight`(수능1.0/모평0.8/학평0.5, None이면 0.0) × 2.0 → 가장 큰
        가중치. 출처 권위가 높은 기출 유형일수록(수능>모평>학평) 정시 대비 가치가 직결되므로
        *최우선*으로 앞세운다(×2.0이라 수능=2.0·모평=1.6·학평=1.0 기여).
      - `signature_patterns` *존재* → +1.0. 한국 수능 시그니처 패턴(10종 중 하나라도)을 가진
        문항은 수능 전형 유형이라 가산(존재 여부만 본다 — 패턴 내용·정합은 보지 않는다).
      - `difficulty_overall`(1.0~5.0, None이면 0.0) → 그대로 가산. 정시는 변별·심화가 목적이라
        어려운 문항을 약하게 앞세운다(보조 축 — 위 두 신호를 압도하지 않는다).

    구체 가중치(권위×2.0/시그니처+1.0/난이도 그대로)는 *상대 순서*만 의미가 있다 — 출처 권위
    신호(최대 2.0)가 시그니처 신호(1.0)보다 크고, 난이도는 동급 신호 사이의 타이브레이커로
    약하게 작동하도록 정했다. 합산이라 같은 점수(예: 권위·시그니처·난이도가 모두 같음)는
    동률이며, 동률 처리는 `select_suneung_items`의 *안정정렬*(원래 순서 보존)에 맡긴다.

    Args:
      problem: 우선순위를 매길 문항.

    Returns:
      가중치(클수록 우선). 음수 없음(모든 항이 비음수).
    """
    weight = 0.0

    # 출처 권위 신호(수능1.0/모평0.8/학평0.5, None이면 0.0) × 2.0 — 권위 최우선.
    if problem.exam_authority_weight is not None:
        weight += problem.exam_authority_weight * 2.0

    # 한국 수능 시그니처 패턴 *존재* 신호 — 수능 전형 유형(존재 여부만 본다).
    if problem.signature_patterns:  # 빈 리스트면 거짓(존재하지 않음)
        weight += 1.0

    # 종합 난이도 보조 축(None이면 0.0) — 심화·변별을 약하게 앞세움.
    if problem.difficulty_overall is not None:
        weight += problem.difficulty_overall

    return weight


def select_suneung_items(
    problems: Iterable[Problem],
    persona: Persona = Persona.A_일반고고3,
    *,
    min_fit: float = SUNEUNG_DEFAULT_MIN_FIT,
    limit: int | None = None,
) -> list[Problem]:
    """수능 모드 노출 문항을 *선별·정렬*한다 — 적격 필터 → 우선순위 내림차순 → limit.

    파이프라인:
      1. `is_suneung_eligible(p, persona, min_fit=min_fit)`로 적격 문항만 남긴다(비응시
         페르소나·본문 미보유 출처·적합 신호 부재는 탈락).
      2. `suneung_priority(p)` *내림차순*으로 **안정정렬**한다(동률은 입력 순서 보존 —
         `suneung_priority` docstring의 동률 처리 계약). 따라서 출처 권위가 높은(수능>모평>학평)
         문항이 앞으로 온다.
      3. `limit`이 주어지면 상위 `limit`개만 돌려준다(None이면 무제한·전부).

    Args:
      problems: 후보 문항들(임의 iterable — 한 번만 순회).
      persona: 노출 대상 페르소나(기본 A_일반고고3 — MVP 정시 정면 대상).
      min_fit: persona_fit 임계값(기본 0.5). `is_suneung_eligible`에 전달.
      limit: 최대 개수(None=무제한). 0이면 빈 리스트.

    Returns:
      우선순위 내림차순으로 정렬된 적격 문항 리스트(limit 적용).

    결정적(deterministic)·부수효과 없음. `sorted(reverse=True)`는 파이썬 안정정렬이라
    동률 간 입력 순서가 보존된다.
    """
    eligible = [p for p in problems if is_suneung_eligible(p, persona, min_fit=min_fit)]
    # 안정정렬 — 동률(같은 priority)은 입력 순서 유지. reverse=True로 큰 가중치 우선.
    ranked = sorted(eligible, key=suneung_priority, reverse=True)
    if limit is None:
        return ranked
    return ranked[:limit]
