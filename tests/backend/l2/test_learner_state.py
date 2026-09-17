"""L2 `LearnerState` v0 조립기(`get_state`) 단위테스트 (hermetic·FakeSession).

PED-05: `docs/architecture/02_learner_model.md` §"출력 — LearnerState" v0 실체화. 기존
`test_concept_diagnosis.py`의 `_QueueSession`(execute() 호출 순서대로 결과를 반환) 관례를
확장해 `get_state()`의 4회 `execute()`(BKT→IRT abilities→theta→misconceptions) + 1회
`get()`(user_profile)를 hermetic으로 검증한다.

계층 가드(`test_no_import_cycle.py::test_l1_embedding_modules_have_no_l4_import`와 동일 AST
패턴)로 `l2/learner_state.py`가 `whymath_backend.l4.*`를 전혀 import하지 않음을 봉인한다
(CLAUDE.md "L_n은 L_{n+1}을 알지 못한다" — 역방향 의존 금지의 회귀 가드).
"""

from __future__ import annotations

import ast
import importlib
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.l2.learner_state import FieldStatus, LearnerState, get_state

_UID = uuid.uuid4()


# ──────────────────────────────────────────────────────────────────────────
# hermetic 좌석 — `test_concept_diagnosis.py::_QueueSession` 관례 확장(execute 큐 + get() 추가)
# ──────────────────────────────────────────────────────────────────────────
class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


@dataclass
class _FakeProfile:
    """`UserProfile`의 `get_state()`가 실제로 읽는 필드만 흉내(hermetic — ORM 불요)."""

    grade: int | None = None
    target_grade: int | None = None
    target_score: int | None = None
    target_exam_date: date | None = None
    target_universities: list[dict[str, Any]] | None = None


class _QueueSession:
    """`execute()`가 호출 순서대로 미리 준 결과를 반환 — `get_state()` 내부 호출 순서:

    ①BKT 최신 숙달(`compute_concept_diagnoses` 1단계)
    ②IRT abilities(`compute_concept_diagnoses` → `compute_concept_abilities`)
    ③전과목 θ(`get_current_theta`)
    ④활성 오개념 id(`_get_active_misconception_ids`)
    ⑤스킬별 최신 숙달(`get_all_current_skill_mastery` — EOS-10)
    그 뒤 `session.get(UserProfile, user_id)` 1회(execute 큐와 별개).

    **순서가 계약이다** — 큐가 위치로 결과를 돌려주므로 `get_state()`가 호출 순서를 바꾸면
    이 하네스가 엉뚱한 행을 먹인다. 큐가 마르면 `IndexError`가 나므로 호출이 *늘어나는* 것은
    반드시 발각된다(조용히 통과하지 않는다).
    """

    def __init__(self, results: list[list[Any]], profile: _FakeProfile | None) -> None:
        self._results = list(results)
        self._profile = profile

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, _model: Any, _pk: Any) -> _FakeProfile | None:
        return self._profile


def _session(
    *,
    bkt_rows: list[Any] | None = None,
    ability_rows: list[Any] | None = None,
    theta_rows: list[Any] | None = None,
    misconception_rows: list[Any] | None = None,
    skill_rows: list[Any] | None = None,
    profile: _FakeProfile | None = None,
) -> AsyncSession:
    return cast(
        AsyncSession,
        _QueueSession(
            [
                bkt_rows or [],
                ability_rows or [],
                theta_rows or [],
                misconception_rows or [],
                skill_rows or [],
            ],
            profile,
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 정상 조립 — 각 필드가 기존 좌석 재사용으로 올바르게 채워지는지
# ──────────────────────────────────────────────────────────────────────────
class TestGetState:
    async def test_mastery_and_domain_abilities_from_diagnoses(self) -> None:
        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        session = _session(
            bkt_rows=[
                (cid_a, "MATH-A", "개념A", 0.9),  # 숙달(>=0.8)
                (cid_b, "MATH-B", "개념B", 0.2),  # 초보(<0.4)
            ],
            theta_rows=[0.5],  # 전과목 θ
            profile=_FakeProfile(grade=2),
        )
        state = await get_state(session, _UID)
        assert state.mastery == {"MATH-A": 0.9, "MATH-B": 0.2}
        assert state.general_ability == 0.5
        assert state.grade == 2

    async def test_domain_abilities_keyed_by_concept_code_irt_theta_source(
        self,
    ) -> None:
        cid = uuid.uuid4()
        session = _session(
            ability_rows=[(cid, "MATH-C", "개념C", True, 0.5, None)],  # 정답·난이도 0.5
            theta_rows=[None],
        )
        state = await get_state(session, _UID)
        # irt_theta 소스 — concept_code가 키, θ 자체가 값(도메인명 아님 — docstring 명시).
        assert "MATH-C" in state.domain_abilities
        assert isinstance(state.domain_abilities["MATH-C"], float)

    async def test_recent_struggles_and_successes_threshold_split(self) -> None:
        cid_a, cid_b, cid_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        session = _session(
            bkt_rows=[
                (cid_a, "LOW", "낮음", 0.3),  # < 0.4 → struggle
                (cid_b, "MID", "중간", 0.6),  # 0.4~0.8 → 어느 쪽도 아님
                (cid_c, "HIGH", "높음", 0.85),  # >= 0.8 → success
            ],
        )
        state = await get_state(session, _UID)
        assert state.recent_struggles == ["LOW"]
        assert state.recent_successes == ["HIGH"]

    async def test_active_misconceptions_from_own_select_not_l4(self) -> None:
        session = _session(misconception_rows=["MC-정의혼동", "MC-부호오류"])
        state = await get_state(session, _UID)
        assert state.active_misconceptions == ["MC-정의혼동", "MC-부호오류"]

    async def test_goals_assembled_from_target_fields_none_omitted(self) -> None:
        session = _session(
            profile=_FakeProfile(
                target_grade=2,
                target_score=None,
                target_exam_date=date(2027, 11, 18),
                target_universities=None,
            )
        )
        state = await get_state(session, _UID)
        assert state.goals == {"target_grade": "2", "target_exam_date": "2027-11-18"}
        assert "target_score" not in state.goals
        assert "target_universities" not in state.goals

    async def test_goals_empty_dict_when_all_targets_none(self) -> None:
        session = _session(profile=_FakeProfile())
        state = await get_state(session, _UID)
        assert state.goals == {}

    # ──────────────────────────────────────────────────────────────────
    # 빈 데이터(신규 학생) — NO_DATA 센티널이 아니라 그냥 빈 컬렉션(단순 조립기 계약)
    # ──────────────────────────────────────────────────────────────────
    async def test_no_diagnoses_no_misconceptions_yields_empty_collections(
        self,
    ) -> None:
        session = _session(profile=None)
        state = await get_state(session, _UID)
        assert state.mastery == {}
        assert state.domain_abilities == {}
        assert state.active_misconceptions == []
        assert state.recent_struggles == []
        assert state.recent_successes == []
        assert state.general_ability is None
        assert state.grade is None
        assert state.goals == {}

    async def test_student_id_and_timestamp_populated(self) -> None:
        session = _session()
        state = await get_state(session, _UID)
        assert state.student_id == str(_UID)
        assert state.timestamp is not None


# ──────────────────────────────────────────────────────────────────────────
# 계층 경계 가드 — l2/learner_state.py는 whymath_backend.l4.*를 전혀 import하지 않는다
# ──────────────────────────────────────────────────────────────────────────
def test_learner_state_module_has_no_l4_import() -> None:
    """AST로 실제 import 문(TYPE_CHECKING 포함)만 검사 — 주석·docstring의 'L4' 언급은 무방.

    `test_no_import_cycle.py::test_l1_embedding_modules_have_no_l4_import`와 동일 패턴(역방향
    의존 회귀 가드). CLAUDE.md "L_n은 L_{n+1}을 알지 못한다"의 기계 시행.
    """
    module = "whymath_backend.l2.learner_state"
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None, f"모듈 경로 해석 실패: {module}"
    with open(spec.origin, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=spec.origin)

    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "whymath_backend.l4"
        ):
            offending.append(f"from {node.module} import ... (line {node.lineno})")
        elif isinstance(node, ast.Import):
            offending.extend(
                f"import {alias.name} (line {node.lineno})"
                for alias in node.names
                if alias.name.startswith("whymath_backend.l4")
            )
    assert not offending, f"{module}에 L4 역방향 import 발견:\n" + "\n".join(offending)


# ──────────────────────────────────────────────────────────────────────────
# EOS-10 — 결손 3필드(curriculum_id·current_objective_id·skill_mastery) + 유래 축
# ──────────────────────────────────────────────────────────────────────────
class TestSkillMasteryAssembly:
    """스킬 축은 *조립*이다 — 값은 소유 모듈의 벌크 좌석이 내고 여기서 재계산하지 않는다."""

    async def test_skill_mastery_assembled_from_bulk_seat(self) -> None:
        session = _session(
            skill_rows=[("skill.factorize", 0.72), ("skill.substitute", 0.31)],
        )
        state = await get_state(session, _UID)
        assert state.skill_mastery == {"skill.factorize": 0.72, "skill.substitute": 0.31}
        assert state.origins["skill_mastery"].status is FieldStatus.MEASURED
        # 좌석이 응답에 드러난다 — 교체 시 바뀌는 곳이 어디인지 소비처가 알 수 있다.
        assert state.origins["skill_mastery"].seat == (
            "l2.skill_mastery_tracking.get_all_current_skill_mastery"
        )

    async def test_skill_mastery_empty_marks_no_data_not_no_producer(self) -> None:
        """측정 이력이 없는 것과 생산자가 없는 것은 다르다 — 스킬 축은 전자다."""
        state = await get_state(_session(), _UID)
        assert state.skill_mastery == {}
        assert state.origins["skill_mastery"].status is FieldStatus.NO_DATA


class TestNoProducerFields:
    """생산자 0건인 두 필드는 **항상 None이고 그 사실을 말한다**(착시 금지)."""

    async def test_curriculum_and_objective_are_none_with_no_producer_origin(self) -> None:
        state = await get_state(_session(), _UID)
        for field in ("curriculum_id", "current_objective_id"):
            assert getattr(state, field) is None, f"{field}는 생산자가 없으므로 None이어야 한다"
            assert state.origins[field].status is FieldStatus.NO_PRODUCER, (
                f"{field}의 부재는 NO_DATA가 아니라 NO_PRODUCER다 — 학생이 무엇을 해도 "
                "채워지지 않는다는 뜻이며, 둘을 같은 값으로 접으면 소비처가 "
                "'고칠 수 있는 것'과 '고칠 수 없는 것'을 구별하지 못한다"
            )
            # 생산자가 없으므로 추정기·좌석도 없어야 한다(있다면 그 자체가 모순이다).
            assert state.origins[field].estimator is None
            assert state.origins[field].seat is None

    async def test_no_producer_fields_stay_none_even_with_full_data(self) -> None:
        """다른 축이 전부 측정돼도 이 둘은 채워지지 않는다 — 데이터 문제가 아니기 때문이다."""
        session = _session(
            theta_rows=[0.8],
            misconception_rows=["mis.sign-flip"],
            skill_rows=[("skill.factorize", 0.9)],
            profile=_FakeProfile(grade=3, target_grade=1),
        )
        state = await get_state(session, _UID)
        assert state.origins["grade"].status is FieldStatus.MEASURED  # 대조군
        assert state.curriculum_id is None
        assert state.current_objective_id is None


class TestOriginsCompleteness:
    """`origins`는 데이터 필드 **전건**을 덮어야 한다 — 이 가드가 없으면 필드만 늘고 유래가 빈다."""

    _META_FIELDS = frozenset({"student_id", "timestamp", "origins"})

    async def test_origins_covers_every_data_field(self) -> None:
        state = await get_state(_session(), _UID)
        data_fields = set(LearnerState.model_fields) - self._META_FIELDS
        missing = data_fields - set(state.origins)
        extra = set(state.origins) - data_fields
        assert not missing, (
            f"유래 없는 데이터 필드: {sorted(missing)} — 필드를 추가했으면 `get_state()`의 "
            "`origins` dict에도 항을 추가하라. 유래 없는 필드는 '작동한 비율'을 셀 수 없게 만든다"
        )
        assert not extra, f"존재하지 않는 필드의 유래: {sorted(extra)}"

    async def test_measured_ratio_is_computable_from_origins(self) -> None:
        """소비처가 '이 조립이 실제로 작동한 비율'을 셀 수 있어야 한다(CLAUDE.md 작동한 비율)."""
        session = _session(
            theta_rows=[0.5],
            skill_rows=[("skill.factorize", 0.6)],
            profile=_FakeProfile(grade=2),
        )
        state = await get_state(session, _UID)
        measured = [k for k, o in state.origins.items() if o.status is FieldStatus.MEASURED]
        assert sorted(measured) == [
            "general_ability",
            "grade",
            "skill_mastery",
        ], "측정된 필드만 MEASURED여야 한다 — 빈 컬렉션이 MEASURED로 새면 비율이 부풀려진다"

    async def test_estimator_is_a_value_not_a_comment(self) -> None:
        """추정기 교체(BKT→DKT)가 스키마 모양이 아니라 **값**만 바꾸도록 타입에 실려 있는가."""
        session = _session(theta_rows=[0.5], skill_rows=[("skill.factorize", 0.6)])
        state = await get_state(session, _UID)
        assert state.origins["skill_mastery"].estimator == "bkt.v1"
        assert state.origins["general_ability"].estimator == "irt.2pl"
        # 추정이 아닌 경로(프로필 조회)는 추정기가 없어야 한다 — 아무 데나 붙이면 의미가 죽는다.
        assert state.origins["grade"].estimator is None


# ──────────────────────────────────────────────────────────────────────────
# 좌석 판정 가드 (EOS-10 acceptance ③) — 이 조립기는 `user_state_snapshot`을 경유하지 않는다
# ──────────────────────────────────────────────────────────────────────────
def _strip_docstrings(tree: ast.AST) -> None:
    """모듈·클래스·함수의 docstring 노드만 제거 — 나머지 문자열 리터럴은 남긴다.

    남기는 것이 중요하다: 좌석 이름을 **코드의 문자열 리터럴**로 쓰는 우회
    (`getattr(models, "UserStateSnapshot")`·`text("select … from user_state_snapshot")`)는
    여전히 검출돼야 한다. docstring만 정확히 지운다.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]


def test_get_state_does_not_touch_user_state_snapshot_seat() -> None:
    """`UserStateSnapshot`(writer 0·축이 다름)을 읽거나 쓰지 않음을 AST로 동결.

    판정 근거는 `get_state()` docstring의 "좌석 판정" 절에 있다. 이 가드는 그 판정이 나중에
    조용히 뒤집히는 것을 막는다 — 스냅샷을 읽기 시작하면 `concept_mastery`가 같은 사실의 두
    번째 진실 원천이 되고(붕괴 연쇄 "유지보수 지옥"), 게다가 writer가 0이라 항상 빈 상태를
    돌려준다. 좌석을 쓰기로 **결정을 바꾸는** 것은 가능하지만, 그때는 이 테스트를 지우는 것이
    그 결정의 명시적 기록이 된다(조용한 표류 금지).
    """
    module = "whymath_backend.l2.learner_state"
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None, f"모듈 경로 해석 실패: {module}"
    with open(spec.origin, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=spec.origin)

    # ① import 축 — 심볼을 끌어오지 않는다.
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.extend(
                f"{node.module}.{alias.name} (line {node.lineno})"
                for alias in node.names
                if alias.name == "UserStateSnapshot"
            )
    assert not imported, f"{module}이 좌석 심볼을 import한다:\n" + "\n".join(imported)

    # ② 이름 축 — import 없이 문자열·속성으로 닿는 경로도 막는다.
    #
    # **docstring은 반드시 걷어낸다.** 이 모듈의 docstring은 좌석 판정을 *기록*하므로 그 이름을
    # 정당하게 담고 있다 — 걷어내지 않으면 판정을 적었다는 이유로 가드가 터진다(초판이 실제로
    # 그랬다). 걷어낸 뒤에도 코드에 이름이 남으면 그것은 진짜 참조다.
    _strip_docstrings(tree)
    code_only = ast.unparse(tree)
    for needle in ("UserStateSnapshot", "user_state_snapshot"):
        assert needle not in code_only, (
            f"{module}의 **코드**에 좌석 참조 `{needle}`가 있다 — 판정은 '이 표면은 그 좌석을 "
            "쓰지 않는다'이며, 쓰기로 결정을 바꿨다면 docstring의 좌석 판정 절과 이 가드를 "
            "함께 갱신하라"
        )
