"""L6 게이팅 API 라우터 단위테스트 — FakeSession 주입(라이브 PG 없음, hermetic).

problems 라우터 단위테스트(test_problems.py)와 동형: `app.dependency_overrides[get_session]`로
가짜 세션을 주입하고 `TestClient(create_app(...))`로 `/v1/gating/*` 3 엔드포인트를 호출해
게이팅 결과(선별·우선순위·limit·저작권/페르소나 차단)를 검증한다. 실 PG 불요·순수 단위.

가짜 세션의 `execute()`는 라우터가 `select(Problem)`으로 만든 stmt를 *무시*하고(사전 SQL
필터가 없으므로 stmt 내용이 결과를 바꾸지 않는다 — 게이팅이 진실 게이트) 미리 정한 ORM
`Problem` 목록을 돌려준다(test_problems.py의 `_FakeResult`/`_FakeScalars` 패턴). 라우터는 각
행을 `to_schema()`로 변환해 L6 게이팅에 넘기므로, 가짜 행은 `Problem.from_schema(...)`로 만든
*진짜 ORM 인스턴스*다(to_schema가 동작해야 함).

검증 초점:
  - retake: persona=B에 자체생성 RT 문항 노출 · 평가원(본문 미보유) 출처 차단 · limit 적용.
  - suneung: persona=A에 정시 신호(exam_type/시그니처) 문항 노출 · 평가원 본문 차단.
  - school-progress: `?unit_codes=X&unit_codes=Y` 단원 정합 노출 · curriculum_version 불일치
    차단 · target 미지정 시 persona_fit 폴백.
  - 잘못된 persona 값(enum 밖) → 422.

레이어(CLAUDE.md): 테스트는 L1(`db.models.problem`·`schema.*`)·L5(`app`·`api.gating` 경유)만
건드린다. L6 게이팅은 라우터를 통해 *간접* 호출한다(게이팅 로직 자체는 l6 단위테스트가 검증).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.app import create_app
from whymath_backend.db.models.atom_node import AtomNode
from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import get_session
from whymath_backend.l1.curriculum import curriculum_resolve
from whymath_backend.schema.enums import (
    BloomLevel,
    Curriculum,
    ExamType,
    Persona,
    QuestionFormat,
    RequiredDepth,
    ReviewStatus,
    ScoringType,
    SignaturePattern,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry
from whymath_backend.schema.problem import Problem as ProblemSchema


# ──────────────────────────────────────────────────────────────────────
# 픽스처 빌더 — 자체생성 최소 Problem(ORM)에서 게이팅 신호만 오버라이드
# ──────────────────────────────────────────────────────────────────────
def _problem(**over: object) -> Problem:
    """게이팅 후보로 쓸 ORM `Problem` 빌더(합성 픽스처).

    기본은 `source_type=자체생성`(저작권 노출 게이트를 통과하는 출처)이라 게이팅 신호만
    오버라이드하면 적격/부적격을 자유로이 만든다. 본문 미보유 출처(평가원/EBS/교과서)는
    `source_type=...`로 바꿔 저작권 게이트를 시험한다. schema.Problem을 거쳐(불변식 검증)
    `from_schema`로 ORM을 만들므로, 라우터의 `to_schema()` 왕복이 그대로 동작한다.
    (l6 단위테스트 `_problem` 빌더와 동일한 필드 셋·type: ignore도 동일.)
    """
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        # PB-03 — 검수 노출 게이트(`is_review_cleared`) 추가로 기본값도 approved가 필요.
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
    }
    kwargs.update(over)
    return Problem.from_schema(ProblemSchema(**kwargs))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# 가짜 세션 — execute()가 stmt를 무시하고 정한 ORM 행을 돌려줌(test_problems.py 패턴)
# ──────────────────────────────────────────────────────────────────────
class _FakeScalars:
    def __init__(self, rows: list[Problem]) -> None:
        self._rows = rows

    def all(self) -> list[Problem]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[Problem]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeTupleResult:
    """조인 쿼리 결과 모사 — `.all()`로 튜플 행 반환.

    후보 쿼리(`select(Problem)`·scalars 경로)와 달리 성취기준 조인은 *튜플 select*
    (`select(ProblemConcept.problem_id, AtomNode.standard_codes)` — 원자 축·S2-03)라
    `result.all()`을 직접 부른다. 이 가짜는 미리 정한 `(problem_id, standard_codes 배열)` 행
    (또는 개념코드 조인의 `(problem_id, concept_code)` 행)을 그대로 돌려준다.
    """

    def __init__(self, rows: list[tuple[uuid.UUID, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[uuid.UUID, Any]]:
        return list(self._rows)


def _is_standard_join(stmt: Any) -> bool:
    """stmt가 성취기준 원자 축 조인인지 *컬럼 엔티티*로 판별(문자열 매칭보다 견고).

    후보 쿼리는 `select(Problem)`이라 column_descriptions의 엔티티가 `Problem` 하나뿐이고,
    성취기준 조인은 `(ProblemConcept.problem_id, AtomNode.standard_codes)` 튜플 select라(S2-03
    원자 축 전환) 엔티티에 `AtomNode`가 등장한다. 그 출현으로 두 쿼리를 가른다(stmt 텍스트·
    컬럼명 문자열에 의존하지 않음 — 리팩터에 견고).
    """
    try:
        entities = [c.get("entity") for c in stmt.column_descriptions]
    except (AttributeError, TypeError):
        return False
    return AtomNode in entities


def _is_concept_code_join(stmt: Any) -> bool:
    """stmt가 문항→개념 코드 조인(`_fetch_problem_concept_codes`)인지 *컬럼 엔티티*로 판별.

    깊이 주입은 `select(ProblemConcept.problem_id, Concept.code)` 튜플 select라 엔티티에 `Concept`이
    등장하고 `AtomNode`는 없다(성취기준 원자 축 조인과 구별). 후보 쿼리(`select(Problem)`)는
    엔티티가 Problem뿐이라 Concept이 없다. 그 출현으로 셋을 가른다.
    """
    try:
        entities = [c.get("entity") for c in stmt.column_descriptions]
    except (AttributeError, TypeError):
        return False
    return Concept in entities and AtomNode not in entities


class FakeSession:
    """AsyncSession 표면 일부 모사 — 게이팅 라우터가 부르는 `execute`만(stmt 분기).

    라우터는 사전 SQL 필터 없이 `select(Problem)`만 만들고 게이팅이 모두 거르므로, 가짜
    세션은 stmt 내용과 무관하게 보유한 후보 행(`rows`)을 통째로 돌려준다 — 그러면 *저작권/
    페르소나/진도 차단이 SQL이 아니라 게이팅에서* 일어남이 테스트로 입증된다(차단된 문항을
    가짜 세션이 *그대로 흘려보내도* 응답엔 없어야 한다).

    school-progress 핸들러는 후보 조회에 더해 *성취기준 원자 축 조인*(`_fetch_achievement_codes`·
    S2-03)도 실행하므로, `execute()`가 두 쿼리를 *컬럼 엔티티*(`_is_standard_join`)로 분기한다 —
    조인이면 미리 정한 `standard_rows`(`(problem_id, standard_codes 배열)` 목록·원자 행의
    `atom_node.standard_codes` 모사)를 `_FakeTupleResult.all()`로, 아니면 후보 행을
    `_FakeResult.scalars()`로 돌려준다. `standard_rows` 기본 빈 목록은 *성취기준 데이터0*
    (태깅 부재)을 모사해 단원·persona_fit 폴백이 그대로 동작함을 검증한다.
    """

    def __init__(
        self,
        rows: list[Problem] | None = None,
        standard_rows: list[tuple[uuid.UUID, list[str]]] | None = None,
        concept_code_rows: list[tuple[uuid.UUID, str]] | None = None,
    ) -> None:
        self._rows = list(rows or [])
        self._standard_rows = list(standard_rows or [])
        self._concept_code_rows = list(concept_code_rows or [])

    async def execute(self, stmt: Any) -> _FakeResult | _FakeTupleResult:
        if _is_standard_join(stmt):
            return _FakeTupleResult(self._standard_rows)
        # 깊이 주입 문항→개념 코드 조인 — 미리 정한 (problem_id, concept_code) 행(기본 빈 목록 →
        # 깊이 무신호·resolver 미호출로 실 DB 회피).
        if _is_concept_code_join(stmt):
            return _FakeTupleResult(self._concept_code_rows)
        return _FakeResult(self._rows)


def _client(
    rows: list[Problem],
    standard_rows: list[tuple[uuid.UUID, list[str]]] | None = None,
    concept_code_rows: list[tuple[uuid.UUID, str]] | None = None,
) -> TestClient:
    """후보 행(+ 선택적 성취기준·개념코드 조인 행)을 보유한 가짜 세션을 주입한 TestClient.

    `standard_rows`는 성취기준 원자 축 조인(`(problem_id, standard_codes 배열)`·S2-03),
    `concept_code_rows`는 깊이 주입의 문항→개념 코드 조인
    (`(problem_id, concept_code)`)을 모사한다. 둘 다 생략하면 빈 목록(데이터0) — 다른 모드·기존
    호출이 그대로 동작한다(하위호환). `concept_code_rows`가 비면 깊이 resolver는 호출되지 않는다
    (all_codes 빈 → 조기 반환·실 DB 회피).
    """
    app = create_app()

    async def _override() -> AsyncIterator[FakeSession]:
        yield FakeSession(rows, standard_rows, concept_code_rows)

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def _slugs(payload: list[dict[str, Any]]) -> list[str | None]:
    """응답 본문(list[ProblemSchema])에서 slug 순서를 뽑아 비교용 리스트로."""
    return [item["slug"] for item in payload]


def _source_types(payload: list[dict[str, Any]]) -> set[str]:
    """응답 본문에서 등장한 source_type 집합(본문 미보유 출처 부재 검증용)."""
    return {item["source_type"] for item in payload}


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/retake
# ──────────────────────────────────────────────────────────────────────
class TestRetake:
    def test_persona_b_sees_self_generated_rt_items(self) -> None:
        """persona=B(자사고N수) → 자체생성 RT 문항이 노출된다."""
        rt = _problem(slug="rt-fit", question_format=QuestionFormat.재수전용형)
        client = _client([rt])
        resp = client.get("/v1/gating/retake", params={"persona": "B_자사고N수"})
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["rt-fit"]

    def test_persona_required(self) -> None:
        """persona는 필수 쿼리 — 누락 시 422."""
        resp = _client([]).get("/v1/gating/retake")
        assert resp.status_code == 422

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """저작권 게이트 — 평가원(본문 미보유) 출처는 RT 신호가 있어도 응답에서 차단.

        가짜 세션은 차단 대상(평가원)을 그대로 흘려보내지만, 게이팅이 거르므로 응답엔
        자체생성만 남는다 → SQL이 아니라 게이팅이 진실 게이트임이 입증된다.
        """
        ok = _problem(slug="ok", question_format=QuestionFormat.재수전용형)
        # 평가원 출처(본문 미보유) — RT 라벨이 있어도 노출 불가. 본문 필드는 비워 둬야
        # schema.Problem 검증을 통과하므로 빌더 기본(본문 None)을 그대로 쓴다.
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            question_format=QuestionFormat.재수전용형,
        )
        client = _client([blocked, ok])
        resp = client.get("/v1/gating/retake", params={"persona": "B_자사고N수"})
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["ok"]
        # 평가원이 응답 어디에도 없어야 한다(본문 미보유 출처 노출 금지).
        assert "평가원" not in _source_types(payload)

    def test_limit_truncates(self) -> None:
        """limit이 상위 N개로 자른다(게이팅 우선순위 상위부터)."""
        rows = [
            _problem(
                slug=f"item-{i}",
                question_format=QuestionFormat.재수전용형,
                difficulty_overall=float(i),
            )
            for i in (1, 2, 3, 4, 5)
        ]
        client = _client(rows)
        resp = client.get("/v1/gating/retake", params={"persona": "B_자사고N수", "limit": 2})
        assert resp.status_code == 200
        # 난이도 5,4가 상위 2개(재수전용형 1.5 + 난이도).
        assert _slugs(resp.json()) == ["item-5", "item-4"]

    def test_non_target_persona_returns_empty(self) -> None:
        """비대상 페르소나(A) → 적합 문항이 있어도 게이팅이 전부 거른다(빈 배열)."""
        rt = _problem(
            slug="rt",
            question_format=QuestionFormat.재수전용형,
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([rt]).get("/v1/gating/retake", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/retake", params={"persona": "Z_없는페르소나"})
        assert resp.status_code == 422

    def test_empty_candidates_returns_empty(self) -> None:
        """후보가 없으면 빈 배열(200)."""
        resp = _client([]).get("/v1/gating/retake", params={"persona": "B_자사고N수"})
        assert resp.status_code == 200
        assert resp.json() == []


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/suneung
# ──────────────────────────────────────────────────────────────────────
_IN_SCOPE_CODE = "[12대수01-01]"  # 2028 수능 출제 범위 안(2022 개정 대수) — EOS-31
_OUT_OF_SCOPE_CODE = "[9수02-01]"  # 중학교 — 수능 출제 범위 밖


def _codes(*items: Problem, code: str = _IN_SCOPE_CODE) -> list[tuple[uuid.UUID, list[str]]]:
    """수능 게이트 ②-c 입력 — 성취기준 원자 축 조인 행(`(problem_id, standard_codes 배열)`).

    ORM `Problem`은 `achievement_standard_codes`(비영속)를 담지 못하므로 라우터가 조인으로 주입한다.
    """
    return [(item.problem_id, [code]) for item in items]


class TestSuneung:
    def test_persona_a_sees_exam_signal_item(self) -> None:
        """persona=A(기본) → 정시 신호(exam_type=수능) 자체생성 문항이 노출된다."""
        item = _problem(slug="suneung-exam", exam_type=ExamType.수능)
        resp = _client([item], _codes(item)).get("/v1/gating/suneung")  # persona 기본 A
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["suneung-exam"]

    def test_persona_a_sees_signature_pattern_item(self) -> None:
        """시그니처 패턴 보유 문항도 정시 적합 신호로 노출된다(persona=A 명시)."""
        item = _problem(
            slug="sig",
            signature_patterns=[SignaturePattern.COMPOUND_CHOICES],
        )
        resp = _client([item], _codes(item)).get(
            "/v1/gating/suneung", params={"persona": "A_일반고고3"}
        )
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["sig"]

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """수능 모드 핵심 — 평가원 기출 *본문*은 응답에서 원천 차단(자체생성만 노출)."""
        ok = _problem(slug="own", exam_type=ExamType.수능)
        # 평가원 출처(본문 미보유) — exam_type=수능 신호가 있어도 노출 불가.
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            exam_type=ExamType.수능,
        )
        resp = _client([blocked, ok], _codes(blocked, ok)).get("/v1/gating/suneung")
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["own"]
        assert "평가원" not in _source_types(payload)

    def test_priority_orders_by_authority(self) -> None:
        """출처 권위(exam_authority_weight)가 높은 문항이 앞에 온다(게이팅 우선순위)."""
        suneung = _problem(slug="suneung", exam_type=ExamType.수능, exam_authority_weight=1.0)
        hakpyeong = _problem(slug="hakpyeong", exam_type=ExamType.학평, exam_authority_weight=0.5)
        # 입력은 역순으로 줘서 정렬이 실제로 일어나는지 본다.
        resp = _client([hakpyeong, suneung], _codes(hakpyeong, suneung)).get("/v1/gating/suneung")
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["suneung", "hakpyeong"]

    def test_out_of_scope_item_is_excluded_even_with_exam_signal(self) -> None:
        """EOS-31 — 출제 범위 밖(중학교 코드) 문항은 기출 신호가 있어도 노출되지 않는다.

        범위는 신호(OR)가 아니라 선결 조건(AND)이다. 같은 요청에 범위 안 문항을 함께 둬 "범위 문항만
        남는다"가 변별되게 한다(전부 걸러진 빈 응답과 구분).
        """
        inside = _problem(slug="inside", exam_type=ExamType.수능)
        outside = _problem(slug="outside", exam_type=ExamType.수능)
        rows = _codes(inside) + _codes(outside, code=_OUT_OF_SCOPE_CODE)
        resp = _client([outside, inside], rows).get("/v1/gating/suneung")
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["inside"]

    def test_item_without_standard_codes_is_excluded_not_passed(self) -> None:
        """EOS-31 — 성취기준 코드를 모르는 문항(조인 행 없음)은 통과하지 않는다(fail-closed).

        주입이 빠진 `CandidatesDep`를 그대로 썼다면 이 엔드포인트가 *항상 빈 결과*를 냈을 것이다 —
        범위 안 문항이 함께 나가는 것으로 "주입 경로가 실제로 일한다"까지 같이 본다.
        """
        known = _problem(slug="known", exam_type=ExamType.수능)
        unknown = _problem(slug="unknown", exam_type=ExamType.수능)
        resp = _client([unknown, known], _codes(known)).get("/v1/gating/suneung")
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["known"]

    def test_non_target_persona_d_returns_empty(self) -> None:
        """D(학종·수시)는 정시 모드 비대상 → 게이팅이 거른다(빈 배열)."""
        item = _problem(slug="x", exam_type=ExamType.수능)
        resp = _client([item]).get("/v1/gating/suneung", params={"persona": "D_학종고2"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/suneung", params={"persona": "nope"})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/school-progress
# ──────────────────────────────────────────────────────────────────────
class TestSchoolProgress:
    def test_unit_code_overlap_exposes_matching_item(self) -> None:
        """`?unit_codes=X&unit_codes=Y` → 진도 단원과 겹치는 문항만 노출(단원 정합)."""
        match = _problem(slug="match", unit_codes=["CAL-INT-DEF", "FUN-COMPOSITE"])
        # 진도 단원과 전혀 안 겹치는 문항 → 게이팅이 진도 부정합으로 탈락.
        miss = _problem(slug="miss", unit_codes=["GEO-CIRCLE"])
        client = _client([miss, match])
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF", "PROB-COND"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["match"]

    def test_curriculum_mismatch_blocked(self) -> None:
        """curriculum_version 불일치 → 게이팅이 차단(2022 진도에 2015 문항 미혼입)."""
        item_2015 = _problem(
            slug="old",
            curriculum_version=Curriculum.REVISION_2015,
            unit_codes=["CAL-INT-DEF"],
        )
        client = _client([item_2015])
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF"],
                "curriculum_version": "2022_REVISION",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == []  # 교육과정 불일치로 차단

    def test_curriculum_match_passes(self) -> None:
        """curriculum_version 일치 + 단원 겹침 → 노출(정합 통과)."""
        item = _problem(
            slug="ok",
            curriculum_version=Curriculum.REVISION_2022,
            unit_codes=["CAL-INT-DEF"],
        )
        resp = _client([item]).get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF"],
                "curriculum_version": "2022_REVISION",
            },
        )
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["ok"]

    def test_no_target_units_falls_back_to_persona_fit(self) -> None:
        """target 미지정 → persona_fit 폴백으로 판정(진도 단원 정보 부재 시)."""
        fit = _problem(slug="fit", persona_fit={Persona.A_일반고고3: 0.8})
        nofit = _problem(slug="nofit", persona_fit={Persona.A_일반고고3: 0.2})
        client = _client([nofit, fit])
        # unit_codes 미지정 → persona_fit >= 0.5인 'fit'만 통과.
        resp = client.get("/v1/gating/school-progress", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["fit"]

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """저작권 게이트 — 평가원(본문 미보유) 출처는 진도 정합이어도 응답에서 차단."""
        ok = _problem(slug="ok", unit_codes=["CAL-INT-DEF"])
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            unit_codes=["CAL-INT-DEF"],
        )
        resp = _client([blocked, ok]).get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "unit_codes": ["CAL-INT-DEF"]},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["ok"]
        assert "평가원" not in _source_types(payload)

    def test_priority_orders_by_overlap_count(self) -> None:
        """진도 단원 *겹침 개수*가 많은 문항이 앞에 온다(게이팅 우선순위)."""
        two = _problem(slug="two", unit_codes=["CAL-INT-DEF", "FUN-COMPOSITE"])
        one = _problem(slug="one", unit_codes=["CAL-INT-DEF"])
        # 입력은 역순으로 줘서 정렬이 일어나는지 본다. 진도에 두 단원 모두 포함.
        client = _client([one, two])
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF", "FUN-COMPOSITE"],
            },
        )
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["two", "one"]

    def test_non_target_persona_b_returns_empty(self) -> None:
        """N수(B)는 비재학 → 학교진도 비대상 → 게이팅이 거른다(빈 배열)."""
        item = _problem(slug="x", unit_codes=["CAL-INT-DEF"])
        resp = _client([item]).get(
            "/v1/gating/school-progress",
            params={"persona": "B_자사고N수", "unit_codes": ["CAL-INT-DEF"]},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/school-progress", params={"persona": "bad"})
        assert resp.status_code == 422

    def test_invalid_curriculum_returns_422(self) -> None:
        """enum 밖 curriculum_version 값 → 422."""
        resp = _client([]).get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "curriculum_version": "9999_REVISION"},
        )
        assert resp.status_code == 422

    # ── 성취기준 매칭 심화(이 슬라이스) ──────────────────────────────────────
    def test_achievement_code_match_exposes_item_via_join(self) -> None:
        """`?achievement_codes=...` → 4단계 조인이 주입한 성취기준이 겹치는 문항이 노출된다.

        단원은 안 겹치고(진도 단원 미지정) *성취기준만* 겹치게 설계해, 조인 주입→OR 적격이
        실제로 동작함을 본다(성취기준 단독 신호로 통과). 가짜 세션의 `standard_rows`가 그 문항의
        official_code를 비영속 필드로 주입한다.
        """
        match = _problem(slug="ach-match", unit_codes=["CAL-INT-DEF"])
        # 조인 결과로 이 문항에 성취기준 '[12미적01-01]'을 매핑(다른 문항은 매핑 없음).
        standard_rows = [(match.problem_id, ["[12미적01-01]"])]
        client = _client([match], standard_rows=standard_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "achievement_codes": ["[12미적01-01]"]},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert _slugs(payload) == ["ach-match"]
        # 응답 JSON에 비영속 성취기준 코드가 직렬화돼 실린다(주입 입증).
        assert payload[0]["achievement_standard_codes"] == ["[12미적01-01]"]

    def test_achievement_code_mismatch_excluded(self) -> None:
        """진도 성취기준과 안 겹치고 단원도 미지정이면 부적격(성취기준 단독 신호 불일치)."""
        miss = _problem(slug="ach-miss", unit_codes=["CAL-INT-DEF"])
        standard_rows = [(miss.problem_id, ["[12미적02-99]"])]  # 진도와 다른 성취기준
        client = _client([miss], standard_rows=standard_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "achievement_codes": ["[12미적01-01]"]},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_achievement_and_unit_or_combination(self) -> None:
        """성취기준 불일치 + 단원 일치 → OR로 적격(성취기준이 단원 적합을 덮지 않음·핵심)."""
        # 문항 성취기준은 진도와 불일치(아래 standard_rows)지만 단원은 진도와 겹친다.
        item = _problem(slug="unit-ok", unit_codes=["CAL-INT-DEF"])
        standard_rows = [(item.problem_id, ["[12미적09-09]"])]  # 진도 성취기준과 불일치
        client = _client([item], standard_rows=standard_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF"],  # 단원은 겹침
                "achievement_codes": ["[12미적01-01]"],  # 성취기준은 안 겹침
            },
        )
        assert resp.status_code == 200
        # 성취기준 불일치라도 단원이 맞아 OR로 통과(AND였다면 빈 배열).
        assert _slugs(resp.json()) == ["unit-ok"]

    def test_achievement_priority_outranks_unit_only(self) -> None:
        """성취기준+단원 겹침(×3.0+×2.0) 문항이 단원만 겹친 문항보다 앞에 온다(우선순위 위계)."""
        # both: 단원 1겹침(2.0) + 성취기준 1겹침(3.0) = 5.0.
        both = _problem(slug="both", unit_codes=["CAL-INT-DEF"])
        # unit_only: 단원 1겹침(2.0)만 = 2.0(성취기준 조인 매핑 없음).
        unit_only = _problem(slug="unit-only", unit_codes=["CAL-INT-DEF"])
        standard_rows = [(both.problem_id, ["[12미적01-01]"])]  # both에만 성취기준 매핑
        # 입력은 역순으로 줘서 정렬이 실제로 일어나는지 본다.
        client = _client([unit_only, both], standard_rows=standard_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF"],
                "achievement_codes": ["[12미적01-01]"],
            },
        )
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["both", "unit-only"]

    def test_no_achievement_param_preserves_existing_behavior(self) -> None:
        """achievement_codes 미지정 → 기존 단원 정합 동작 100% 보존(조인 주입돼도 무영향).

        성취기준 코드가 조인으로 주입되더라도, *진도 성취기준 타깃을 안 주면* 성취기준 항은
        적격·우선순위에 전혀 기여하지 않는다(타깃 None → 항 0.0). 단원 정합만으로 기존과 동일하게
        선별된다(하위호환).
        """
        match = _problem(slug="match", unit_codes=["CAL-INT-DEF", "FUN-COMPOSITE"])
        miss = _problem(slug="miss", unit_codes=["GEO-CIRCLE"])
        # 두 문항 모두 성취기준이 주입되지만 achievement_codes 미지정이라 무관.
        standard_rows = [
            (match.problem_id, ["[12미적01-01]"]),
            (miss.problem_id, ["[12미적01-01]"]),
        ]
        client = _client([miss, match], standard_rows=standard_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF", "PROB-COND"],
            },
        )
        assert resp.status_code == 200
        # 단원 정합(기존 동작)만으로 'match'만 통과 — 성취기준 미지정이라 기존과 동일.
        assert _slugs(resp.json()) == ["match"]

    def test_empty_standard_join_falls_back_to_unit(self) -> None:
        """조인 결과가 비면(성취기준 데이터0) 빈 리스트 주입 → 단원 신호로 폴백(데이터0 안전).

        성취기준 코퍼스·문항 태깅이 없어 조인이 0행이어도, achievement_codes를 줬더라도 단원이
        맞으면 OR로 통과한다(빈 성취기준 코드 ∩ 타깃 = ∅ → 단원으로 폴백). 데이터가 차오르기 전
        골격 상태에서 회귀가 없음을 입증한다.
        """
        item = _problem(slug="unit-fallback", unit_codes=["CAL-INT-DEF"])
        # standard_rows 미지정 → 조인 0행(데이터0).
        client = _client([item])
        resp = client.get(
            "/v1/gating/school-progress",
            params={
                "persona": "A_일반고고3",
                "unit_codes": ["CAL-INT-DEF"],
                "achievement_codes": ["[12미적01-01]"],  # 줬지만 문항 코드가 비어 불일치
            },
        )
        assert resp.status_code == 200
        # 성취기준은 빈 리스트(데이터0)라 불일치하나 단원이 맞아 통과.
        assert _slugs(resp.json()) == ["unit-fallback"]
        # 비영속 성취기준 코드는 빈 리스트로 직렬화(주입 부재).
        assert resp.json()[0]["achievement_standard_codes"] == []

    # ── 자동 커리큘럼 정렬 깊이 축(이 슬라이스) ─────────────────────────────
    def test_depth_injection_orders_by_alignment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """문항→개념 조인 + curriculum_entry resolver가 깊이를 주입해 정합 문항을 앞세운다.

        같은 단원 겹침·같은 난이도(3.5)지만 개념의 교육과정 요구 깊이가 다른 두 문항을 준다 —
        conceptual(목표 난이도 3.5·완전 정합)이 awareness(목표 1.5·먼 거리)보다 우선순위가 높아
        앞에 와야 한다. resolver는 monkeypatch로 대체해 실 PG 없이 깊이 맵을 주입한다(개념코드
        조인은 가짜 세션 concept_code_rows로 모사). 응답 JSON에 curriculum_required_depth가 실린다.
        """
        aligned = _problem(slug="aligned", unit_codes=["CAL-INT-DEF"], difficulty_overall=3.5)
        misaligned = _problem(slug="misaligned", unit_codes=["CAL-INT-DEF"], difficulty_overall=3.5)
        # 문항→개념 코드 조인 모사: 각 문항이 개념 하나를 다룬다.
        concept_code_rows = [
            (aligned.problem_id, "C-ALIGN"),
            (misaligned.problem_id, "C-MIS"),
        ]
        # resolver를 대체 — 개념코드 → required_depth 맵(실 PG 회피).
        depth_map = {
            "C-ALIGN": RequiredDepth.conceptual,
            "C-MIS": RequiredDepth.awareness,
        }

        def _fake_resolve_many(
            self: object,
            concept_ids: object,
            *,
            country_code: str = "KR",
            min_confidence: float | None = None,
        ) -> dict[str, RequiredDepth]:
            return {c: depth_map[c] for c in concept_ids if c in depth_map}  # type: ignore[union-attr]

        monkeypatch.setattr(
            curriculum_resolve.CurriculumDepthResolver, "resolve_many", _fake_resolve_many
        )
        # 입력은 역순(misaligned 먼저)으로 줘서 깊이정렬이 재정렬하는지 본다.
        client = _client([misaligned, aligned], concept_code_rows=concept_code_rows)
        resp = client.get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "unit_codes": ["CAL-INT-DEF"]},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        # 깊이 정합(conceptual·난이도 3.5)이 앞으로.
        assert _slugs(payload) == ["aligned", "misaligned"]
        # 비영속 깊이가 응답 JSON에 직렬화(주입 입증).
        by_slug = {item["slug"]: item for item in payload}
        assert by_slug["aligned"]["curriculum_required_depth"] == "conceptual"
        assert by_slug["misaligned"]["curriculum_required_depth"] == "awareness"

    def test_depth_no_concept_codes_leaves_none(self) -> None:
        """개념코드 조인이 0행이면(curriculum_entry/개념 매핑 부재) 깊이 None·resolver 미호출.

        concept_code_rows 미지정 → all_codes 빈 → resolver 조기 반환(실 DB 회피). 깊이는 None으로
        남고 기존 단원 정합 경로가 그대로 동작한다(데이터0 안전·하위호환).
        """
        item = _problem(slug="no-depth", unit_codes=["CAL-INT-DEF"])
        resp = _client([item]).get(
            "/v1/gating/school-progress",
            params={"persona": "A_일반고고3", "unit_codes": ["CAL-INT-DEF"]},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["no-depth"]
        assert payload[0]["curriculum_required_depth"] is None


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/thinking
# ──────────────────────────────────────────────────────────────────────
class TestThinking:
    def test_persona_d_sees_top_bloom_item(self) -> None:
        """persona=D(기본) → Bloom 상위 단계(CREATE) 자체생성 문항이 노출된다."""
        item = _problem(
            slug="thinking",
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        resp = _client([item]).get("/v1/gating/thinking")  # persona 기본 D
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["thinking"]

    def test_lower_bloom_item_not_exposed(self) -> None:
        """하위 인지 수준(APPLY) 문항은 사고력 주신호가 아니라 게이팅이 거른다(빈 배열)."""
        item = _problem(
            slug="apply",
            bloom_level=BloomLevel.APPLY,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        resp = _client([item]).get("/v1/gating/thinking")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """저작권 게이트 — 평가원(본문 미보유) 출처는 최상위 bloom이어도 응답에서 차단."""
        ok = _problem(
            slug="own",
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        # 평가원 출처(본문 미보유) — CREATE 신호가 있어도 노출 불가.
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        resp = _client([blocked, ok]).get("/v1/gating/thinking")
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["own"]
        assert "평가원" not in _source_types(payload)

    def test_priority_orders_by_bloom_level(self) -> None:
        """Bloom 상위 단계(CREATE>EVALUATE)가 앞에 온다(게이팅 우선순위)."""
        create = _problem(
            slug="create",
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        evaluate = _problem(
            slug="evaluate",
            bloom_level=BloomLevel.EVALUATE,
            persona_fit={Persona.D_학종고2: 0.9},
        )
        # 입력은 역순으로 줘서 정렬이 실제로 일어나는지 본다.
        resp = _client([evaluate, create]).get("/v1/gating/thinking")
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["create", "evaluate"]

    def test_mvp_persona_a_sees_thinking_item(self) -> None:
        """A(MVP 고3)도 적합도 충족이면 사고력 문항이 노출된다(닫힌 집합 게이트 없음)."""
        item = _problem(
            slug="a-thinking",
            bloom_level=BloomLevel.EVALUATE,
            persona_fit={Persona.A_일반고고3: 0.8},
        )
        resp = _client([item]).get("/v1/gating/thinking", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["a-thinking"]

    def test_persona_without_fit_returns_empty(self) -> None:
        """조회 페르소나의 적합도가 없으면 상위 bloom이어도 게이팅이 거른다(빈 배열)."""
        item = _problem(
            slug="x",
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},  # 조회 대상 A는 없음
        )
        resp = _client([item]).get("/v1/gating/thinking", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/thinking", params={"persona": "nope"})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/metacognition
# ──────────────────────────────────────────────────────────────────────
class TestMetacognition:
    def test_persona_a_sees_distractor_map_item(self) -> None:
        """persona=A(기본) → distractor_map(오답→오개념) 보유 자체생성 문항이 노출된다."""
        item = _problem(
            slug="meta",
            distractor_map=[DistractorEntry(choice_index=1, misconception_id="m-a")],
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([item]).get("/v1/gating/metacognition")  # persona 기본 A
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["meta"]

    def test_scoring_type_alone_exposed(self) -> None:
        """distractor_map이 없어도 scoring_type 진단이면 노출된다(OR 보조 신호)."""
        item = _problem(
            slug="diag",
            scoring_type=ScoringType.진단,
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([item]).get("/v1/gating/metacognition")
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["diag"]

    def test_no_signal_item_not_exposed(self) -> None:
        """메타인지 신호(distractor_map·진단/루브릭)가 없는 문항은 게이팅이 거른다(빈 배열)."""
        item = _problem(
            slug="plain",
            scoring_type=ScoringType.정오답,
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([item]).get("/v1/gating/metacognition")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """저작권 게이트 — 평가원(본문 미보유) 출처는 distractor_map이 있어도 응답에서 차단."""
        ok = _problem(
            slug="own",
            distractor_map=[DistractorEntry(choice_index=1, misconception_id="m-a")],
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            distractor_map=[DistractorEntry(choice_index=1, misconception_id="m-b")],
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([blocked, ok]).get("/v1/gating/metacognition")
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["own"]
        assert "평가원" not in _source_types(payload)

    def test_priority_orders_by_distractor_count(self) -> None:
        """distractor_map 개수가 많은 문항이 앞에 온다(게이팅 우선순위)."""
        one = _problem(
            slug="one",
            distractor_map=[DistractorEntry(choice_index=0, misconception_id="m-0")],
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        two = _problem(
            slug="two",
            distractor_map=[
                DistractorEntry(choice_index=0, misconception_id="m-0"),
                DistractorEntry(choice_index=1, misconception_id="m-1"),
            ],
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        # 입력은 역순으로 줘서 정렬이 실제로 일어나는지 본다.
        resp = _client([one, two]).get("/v1/gating/metacognition")
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["two", "one"]

    def test_shared_core_other_persona_exposed(self) -> None:
        """공유 코어 — A 외 페르소나(D)도 적합도 충족이면 노출된다(닫힌 집합 게이트 없음)."""
        item = _problem(
            slug="d-meta",
            distractor_map=[DistractorEntry(choice_index=1, misconception_id="m-a")],
            persona_fit={Persona.D_학종고2: 0.8},
        )
        resp = _client([item]).get("/v1/gating/metacognition", params={"persona": "D_학종고2"})
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["d-meta"]

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/metacognition", params={"persona": "nope"})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /v1/gating/gifted
# ──────────────────────────────────────────────────────────────────────
class TestGifted:
    def test_persona_e_sees_gifted_item(self) -> None:
        """persona=E(기본) → 심화+창안(CREATE) 자체생성 문항이 노출된다."""
        item = _problem(
            slug="gifted",
            difficulty_overall=4.5,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        resp = _client([item]).get("/v1/gating/gifted")  # persona 기본 E
        assert resp.status_code == 200, resp.text
        assert _slugs(resp.json()) == ["gifted"]

    def test_non_target_persona_a_returns_empty(self) -> None:
        """비대상 페르소나(A)는 영재 트랙 비대상 → 게이팅이 거른다(빈 배열·닫힌 집합)."""
        item = _problem(
            slug="x",
            difficulty_overall=4.5,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.A_일반고고3: 0.9},
        )
        resp = _client([item]).get("/v1/gating/gifted", params={"persona": "A_일반고고3"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_below_difficulty_not_exposed(self) -> None:
        """난이도 미달(<4.0) 문항은 영재 심화 하한에 못 미쳐 게이팅이 거른다(빈 배열)."""
        item = _problem(
            slug="easy",
            difficulty_overall=3.0,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        resp = _client([item]).get("/v1/gating/gifted")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_min_difficulty_query_adjusts_threshold(self) -> None:
        """min_difficulty 쿼리로 심화 하한을 올리면 그 미만 문항이 빠진다."""
        item = _problem(
            slug="mid",
            difficulty_overall=4.2,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        # 기본(4.0)이면 통과하지만 하한을 4.5로 올리면 4.2는 미달.
        resp = _client([item]).get("/v1/gating/gifted", params={"min_difficulty": 4.5})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_pyeonggawon_body_source_blocked(self) -> None:
        """저작권 게이트 — 평가원(본문 미보유) 출처는 영재 신호가 있어도 응답에서 차단."""
        ok = _problem(
            slug="own",
            difficulty_overall=4.5,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        blocked = _problem(
            slug="pyeonggawon",
            source_type=SourceType.평가원,
            difficulty_overall=4.5,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        resp = _client([blocked, ok]).get("/v1/gating/gifted")
        assert resp.status_code == 200
        payload = resp.json()
        assert _slugs(payload) == ["own"]
        assert "평가원" not in _source_types(payload)

    def test_priority_orders_by_create_then_difficulty(self) -> None:
        """창안(CREATE) 고난도가 앞에 온다(게이팅 우선순위)."""
        high = _problem(
            slug="high",
            difficulty_overall=5.0,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        low = _problem(
            slug="low",
            difficulty_overall=4.0,
            bloom_level=BloomLevel.CREATE,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        resp = _client([low, high]).get("/v1/gating/gifted")
        assert resp.status_code == 200
        assert _slugs(resp.json()) == ["high", "low"]

    def test_data_zero_returns_empty(self) -> None:
        """영재 콘텐츠 미존재(일반 난이도·비창안)면 빈 배열(데이터0 안전)."""
        ordinary = _problem(
            slug="ord",
            difficulty_overall=3.0,
            bloom_level=BloomLevel.APPLY,
            persona_fit={Persona.E_홈스쿨링영재: 0.9},
        )
        resp = _client([ordinary]).get("/v1/gating/gifted")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_persona_returns_422(self) -> None:
        """enum 밖 persona 값 → 422."""
        resp = _client([]).get("/v1/gating/gifted", params={"persona": "nope"})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# 공통 — limit 범위 검증
# ──────────────────────────────────────────────────────────────────────
class TestLimitValidation:
    def test_limit_out_of_range_returns_422(self) -> None:
        """limit은 1~200 범위 — 벗어나면 422(problems.py 페이지네이션과 동형)."""
        client = _client([])
        assert (
            client.get(
                "/v1/gating/retake", params={"persona": "B_자사고N수", "limit": 0}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/v1/gating/retake", params={"persona": "B_자사고N수", "limit": 999}
            ).status_code
            == 422
        )


def test_problem_id_in_response_is_uuid_string() -> None:
    """게이팅 응답이 정상 ProblemSchema 직렬화(problem_id가 UUID 문자열)인지 확인."""
    item = _problem(slug="rt", question_format=QuestionFormat.재수전용형)
    resp = _client([item]).get("/v1/gating/retake", params={"persona": "B_자사고N수"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # problem_id가 유효한 UUID 문자열이어야 한다(schema 직렬화 정상).
    uuid.UUID(body[0]["problem_id"])
