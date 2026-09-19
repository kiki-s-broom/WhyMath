"""성취기준 학습맵(`build_learning_map`) 단위테스트 — 4홉 조립·홉별 회계 (EOS-05).

hermetic — FakeSession(큐잉된 행)만 쓴다(`test_alignment_query.py`가 세운 관례 그대로).
실 SQL(ARRAY overlap·N:M 조인·in_ 대조)의 정확성은 실 PG 통합테스트 몫이다.

1홉(`get_alignments`)은 **정본 함수를 패치해 격리한다** — 그 함수의 축 합성·어휘 정책은
`test_alignment_query.py`가 이미 동결했고, 여기서 다시 재현하면 진실 원천이 둘이 된다.
이 파일이 보는 것은 *그 결과를 받아 나머지 3홉을 어떻게 조립하고 무엇을 정직하게 보고하는가*다.

검증 축:
  - **어휘 분기를 축으로 나눠 묻는가** — 1축엔 norm_id, 2·3축엔 official_code.
    한 어휘로 3축을 다 물으면 2·3축이 조용히 0이 된다(가짜 통일의 반대 실패).
  - **홉별 3분류 회계** — scanned/resolved/produced가 "안 봄"·"안 붙음"·"매핑 없음"을 구분.
    2분류로 접으면 그 셋이 같은 0으로 뭉개진다.
  - **개념 키 공간 두 곳** — `concept.code`와 `atom_node.code` 양쪽에서 찾고, 어디서 찾았는지
    `resolved_from`으로 밝힌다(한쪽만 보면 다른 축의 키가 통째로 미해소로 계상된다).
  - **오개념 두 경로** — 개념 느슨참조(`concept_src_id`)와 행동스킬 배열(`behavior_skills`)은
    의미가 달라 `matched_by`로 구분해 싣는다.
  - **유래 추적** — 스킬·문제가 *어느 개념 때문에* 딸려 왔는지 응답이 말한다.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from whymath_backend.l1.standards import learning_map as lm
from whymath_backend.l1.standards.alignment_query import AlignmentAxis


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _FakeResult:
        return self

    def unique(self) -> _FakeResult:
        return self


class _FakeSession:
    """execute 큐 — 원소 순서가 곧 홉 조회 순서(빈 큐는 빈 결과)."""

    def __init__(self, execute_queue: list[list[Any]] | None = None) -> None:
        self._queue = list(execute_queue or [])
        self.execute_calls = 0

    async def execute(self, _stmt: Any) -> _FakeResult:
        self.execute_calls += 1
        return _FakeResult(self._queue.pop(0) if self._queue else [])


def _obj(**kwargs: Any) -> Any:
    return type("_Row", (), kwargs)()


def _concept(code: str, name: str = "이차방정식", skills: list[str] | None = None) -> Any:
    return _obj(
        code=code, concept_id=uuid.uuid4(), name_ko=name, behavior_skills=list(skills or [])
    )


def _atom(code: str, name: str = "원자", skills: list[str] | None = None) -> Any:
    return _obj(code=code, name_ko=name, behavior_skills=list(skills or []))


def _skill(skill_id: str, family: str = "algebra") -> Any:
    return _obj(
        skill_id=skill_id,
        name_ko="인수분해로 푼다",
        behavior_area=_obj(value="계산"),
        family=family,
        mastery_estimable=True,
    )


def _problem() -> Any:
    return _obj(
        problem_id=uuid.uuid4(),
        question_format=_obj(value="단답형"),
        answer_format=_obj(value="수식"),
        difficulty_overall=3.0,
    )


def _misconception(mis_id: str, src: str | None = None, skills: list[str] | None = None) -> Any:
    return _obj(
        mis_id=mis_id,
        canonical_statement="영곱규칙 오적용",
        error_type="절차",
        severity="high",
        concept_src_id=src,
        behavior_skills=list(skills or []),
    )


class _AlignmentStub:
    """`get_alignments`의 최소 대역 — 축별로 어떤 outcome_id로 불렸는지 기록한다."""

    def __init__(self, by_outcome: dict[str, list[tuple[AlignmentAxis, str]]]) -> None:
        self.by_outcome = by_outcome
        self.calls: list[tuple[str, frozenset[AlignmentAxis]]] = []

    async def __call__(self, _session: Any, **kwargs: Any) -> Any:
        outcome = kwargs["outcome_id"]
        axes = frozenset(kwargs["axes"])
        self.calls.append((outcome, axes))
        pairs = [(a, k) for a, k in self.by_outcome.get(outcome, []) if a in axes]
        return _obj(
            alignments=tuple(_obj(axis=a, concept_key=k) for a, k in pairs),
            stats=_obj(probed=len(pairs), joined=len(pairs), matched=len(pairs)),
        )


@pytest.fixture
def stub_alignments(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(by_outcome: dict[str, list[tuple[AlignmentAxis, str]]]) -> _AlignmentStub:
        stub = _AlignmentStub(by_outcome)
        monkeypatch.setattr(lm, "get_alignments", stub)
        return stub

    return _install


@pytest.mark.asyncio
async def test_asks_each_axis_in_its_own_standard_vocabulary(stub_alignments: Any) -> None:
    """1축엔 norm_id, 2·3축엔 official_code로 묻는가 — 한 어휘로 다 물으면 2·3축이 0이 된다."""
    stub = stub_alignments({})
    await lm.build_learning_map(
        _FakeSession(), norm_id="2022_2수_01_01", official_code="[2수01-01]"
    )
    asked = {outcome: axes for outcome, axes in stub.calls}
    assert asked["2022_2수_01_01"] == frozenset({AlignmentAxis.CONCEPT_STANDARD_LINK})
    assert asked["[2수01-01]"] == frozenset(
        {AlignmentAxis.CURRICULUM_ENTRY, AlignmentAxis.ATOM_NODE}
    )


@pytest.mark.asyncio
async def test_empty_first_hop_reports_not_looked_rather_than_none_found(
    stub_alignments: Any,
) -> None:
    """1홉이 비면 뒤 홉은 **돌지 않는다** — 그 0은 '없음'이 아니라 '안 봄'이어야 한다."""
    stub_alignments({})
    session = _FakeSession()
    result = await lm.build_learning_map(session, norm_id="N", official_code="C")

    assert result.concept_stats == lm.HopStats(scanned=0, resolved=0, produced=0)
    for stats in (result.skill_stats, result.problem_stats, result.misconception_stats):
        assert stats.scanned == 0, "앞 홉이 비었는데 뒤 홉이 무언가를 훑었다고 보고한다"
        assert not stats.join_blackout, "돌지도 않은 홉에 조인 실패 경고가 서면 경고가 소음이 된다"
    assert session.execute_calls == 0, "개념 키가 0인데 뒤 홉 SQL이 돌았다"


@pytest.mark.asyncio
async def test_unresolved_concept_key_is_counted_as_scanned_but_not_resolved(
    stub_alignments: Any,
) -> None:
    """정렬은 키를 줬는데 실물이 없는 경우 — '안 붙음'이 보여야 한다(조인 이상 신호)."""
    stub_alignments({"N": [(AlignmentAxis.CONCEPT_STANDARD_LINK, "UC.ghost")]})
    session = _FakeSession([[], []])  # concept 0건 · atom 0건
    result = await lm.build_learning_map(session, norm_id="N", official_code="C")

    assert result.concept_stats.scanned == 1
    assert result.concept_stats.resolved == 0
    assert result.concept_stats.join_blackout is True
    assert result.concepts[0].resolved_from == ()
    assert result.concepts[0].concept_id is None


@pytest.mark.asyncio
async def test_concept_keys_resolve_from_both_key_spaces(stub_alignments: Any) -> None:
    """`concept.code`와 `atom_node.code` 양쪽을 본다 — 한쪽만 보면 다른 축이 통째로 미해소다."""
    stub_alignments(
        {
            "N": [(AlignmentAxis.CONCEPT_STANDARD_LINK, "UC.poly")],
            "C": [(AlignmentAxis.ATOM_NODE, "atom.quad")],
        }
    )
    session = _FakeSession(
        [
            [_concept("UC.poly")],  # concept 테이블
            [_atom("atom.quad")],  # atom_node 테이블
            [],  # skill
        ]
    )
    result = await lm.build_learning_map(session, norm_id="N", official_code="C")

    by_key = {c.concept_key: c for c in result.concepts}
    assert by_key["UC.poly"].resolved_from == ("concept",)
    assert by_key["atom.quad"].resolved_from == ("atom_node",)
    assert result.concept_stats.resolved == 2


@pytest.mark.asyncio
async def test_full_chain_assembles_with_provenance(stub_alignments: Any) -> None:
    """4홉 전부 도는 경우 — 항목이 서고, 각 항목이 *어디서 왔는지*를 말한다."""
    concept = _concept("UC.poly", skills=["skill.factor"])
    problem = _problem()
    stub_alignments({"N": [(AlignmentAxis.CONCEPT_STANDARD_LINK, "UC.poly")]})
    session = _FakeSession(
        [
            [concept],  # concept
            [],  # atom
            [_skill("skill.factor")],  # skill
            [(problem, concept.concept_id)],  # problem join
            [_misconception("M0425", src="UC.poly", skills=["skill.factor"])],
        ]
    )
    result = await lm.build_learning_map(session, norm_id="N", official_code="C")

    assert [s.skill_id for s in result.skills] == ["skill.factor"]
    assert result.skills[0].via_concept_keys == ("UC.poly",), "스킬의 유래 개념이 없다"
    assert [p.problem_id for p in result.problems] == [problem.problem_id]
    assert result.problems[0].via_concept_ids == (concept.concept_id,)
    assert result.problems[0].question_format == "단답형", "Enum이 값으로 풀리지 않았다"
    # 두 경로 모두로 걸린 오개념은 둘 다 표시한다 — 경로마다 의미가 다르다
    assert result.misconceptions[0].matched_by == ("concept_src_id", "behavior_skills")
    assert result.concept_stats.produced == 1
    assert result.skill_stats == lm.HopStats(scanned=1, resolved=1, produced=1)
    assert result.problem_stats == lm.HopStats(scanned=1, resolved=1, produced=1)


@pytest.mark.asyncio
async def test_misconception_matched_by_distinguishes_the_two_paths(
    stub_alignments: Any,
) -> None:
    """개념 느슨참조로 걸린 것과 행동스킬로 걸린 것을 구분한다 — 뭉개면 근거를 잃는다."""
    concept = _concept("UC.poly", skills=["skill.factor"])
    stub_alignments({"N": [(AlignmentAxis.CONCEPT_STANDARD_LINK, "UC.poly")]})
    session = _FakeSession(
        [
            [concept],
            [],
            [_skill("skill.factor")],
            [],  # 문제 없음
            [
                _misconception("M0001", src="UC.poly"),
                _misconception("M0002", skills=["skill.factor"]),
                _misconception("M0003", src="다른개념", skills=["다른스킬"]),
            ],
        ]
    )
    result = await lm.build_learning_map(session, norm_id="N", official_code="C")

    got = {m.mis_id: m.matched_by for m in result.misconceptions}
    assert got["M0001"] == ("concept_src_id",)
    assert got["M0002"] == ("behavior_skills",)
    # SQL이 OR로 걸러 주지만 hermetic 큐는 그대로 돌려준다 — 조립부는 근거 없는 것을 빈 튜플로
    # 정직하게 표시해야 한다(날조 금지). 실제 필터링 정확성은 실 PG 통합테스트 몫이다.
    assert got["M0003"] == ()


@pytest.mark.asyncio
async def test_limits_truncate_output_without_understating_what_was_scanned(
    stub_alignments: Any,
) -> None:
    """상한에 걸려 잘린 것과 원래 없는 것은 다르다 — scanned는 *자르기 전* 수여야 한다."""
    stub_alignments({"N": [(AlignmentAxis.CONCEPT_STANDARD_LINK, f"UC.{i:02d}") for i in range(5)]})
    session = _FakeSession([[_concept(f"UC.{i:02d}") for i in range(5)], [], []])
    result = await lm.build_learning_map(session, norm_id="N", official_code="C", concept_limit=2)

    assert len(result.concepts) == 2, "상한이 듣지 않았다"
    assert (
        result.concept_stats.scanned == 5
    ), "자른 뒤 수를 scanned로 적으면 '적게 봤다'가 '적게 있다'로 보인다"
