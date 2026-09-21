"""LLM ↔ 학습상태 **권위 경계**의 기계 동결 (ARCH-59).

무엇을 지키는가
--------------
설계 규율 한 줄: **LLM은 학습 상태를 직접 결정하지 않는다.** LLM의 역할은 설명·힌트·후보
분류·제안까지이고, LearnerState의 최종 변경은 Assessment / Mastery / Policy 엔진이 한다.

이 문장은 지금까지 저장소에 **산문으로만** 있었다 — `l2/learning_state_policy.py`,
`schema/learning_state.py`, `l2/assessment_evidence.py`의 docstring 세 곳이다. 그 문장들을
검사하는 테스트는 0건이었고(2026-09-18 실측: `tests/infra` 전체에 `mastery` 문자열 0건),
7계층 import 계약은 오히려 `l3 → l2` 방향을 **허용**하므로 import-linter로는 이 축이 성립조차
하지 않는다. 즉 누군가 튜터 경로에서 mastery writer를 부르거나 LLM 출력에 숙달값을 실어도
**아무것도 빨개지지 않는 상태**였다.

여기서 세 축을 동결한다:

  ① **발화 승격의 쓰기 범위** — LLM이 만든 발화가 교수 결정에서 갈아끼우는 필드는 *학생 대면
     발화 본문 하나뿐*이다. hint_level·전이·socratic_category 같은 구조화 결정은 결정론 경로가
     끝까지 소유한다. 이것이 "LLM은 상태를 결정하지 않는다"가 코드에서 실제로 서 있는 자리다.
  ② **writer 좌석 전수** — mastery writer를 손에 쥔 모듈의 집합을 동결한다. 튜터 경로
     (`harness/**`·`l3/**`)에는 한 건도 없어야 한다.
  ③ **LLM 출력 타입의 필드 집합** — 튜터가 고를 수 있는 도구 액션 8종의 필드명을 동결한다.
     숙달·능력치 필드가 하나라도 생기면 그 순간 LLM이 상태를 실어 보낼 **자리**가 생긴다.

판정 방식 — 문자열이 아니라 **구성된 산출물**
--------------------------------------------
`test_proxy_ca_optional.py`(AST 거버넌스 선례)를 따른다. 금지 문자열 열거는 표기 변형에서
뚫리므로(`"mastery"` 검색은 주석에도 걸리고 `getattr(m, "master" + "y")`는 놓친다) `ast`로
**구성된 결과**를 본다 — dict 리터럴의 키 집합, import 노드의 이름, ClassDef의 필드 선언.

**의존성 제약(중요)**: 이 파일이 도는 `infra-contracts` 잡은 백엔드 패키지를 설치하지 않는다
(실측: pytest·pytest-asyncio·pytest-randomly·pyyaml·sqlalchemy·ruff·black 7종뿐). 따라서
`import whymath_backend`도 `import pydantic`도 쓸 수 없다 — 전부 `ast` + 표준 라이브러리로만
판정한다. 이 제약을 어기면 잡이 수집 단계에서 깨진다.

**스캔 0건은 실패다**(④) — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다. 세 축 모두
대상 실재를 먼저 단언한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# ── ① 발화 승격 좌석 ──────────────────────────────────────────────────
_PROMOTION_FILE = _BACKEND / "api" / "coach.py"
_PROMOTION_FUNC = "_wh1_primary_decision_or"
# LLM 발화가 갈아끼워도 되는 **유일한** 키 — 학생 대면 발화 본문.
_UTTERANCE_FIELD = "prompt"

# ── ② mastery writer 좌석 ────────────────────────────────────────────
# l2가 노출하는 *쓰기* 진입점. 읽기·리포트(`ConceptMasteryHistory` 조회 등)는 대상이 아니다 —
# 하네스 리포트 CLI가 정당하게 숙달 행을 *읽기* 때문이다(그 둘을 섞으면 오탐이 난다).
_MASTERY_WRITER_MODULES = (
    "whymath_backend.l2.mastery_contract",
    "whymath_backend.l2.mastery_tracking",
    "whymath_backend.l2.skill_mastery_tracking",
)
_MASTERY_WRITER_NAMES = frozenset(
    {
        "update_mastery",
        "record_attempt_mastery",
        "record_problem_attempt_mastery",
        "record_problem_attempt_skill_mastery",
    }
)
# writer를 쥘 수 있는 좌석 — L5 엔드포인트 2곳뿐(2026-09-18 실측). l2 자신은 스캔에서 제외한다.
_ALLOWED_WRITER_SEATS = frozenset({"api/coach.py", "api/me.py"})
# 튜터 경로 — 여기엔 writer가 한 건도 없어야 한다(②의 핵심 주장).
_TUTOR_PATH_PREFIXES = ("harness/", "l3/")

# ── ③ LLM 도구 액션 타입 ─────────────────────────────────────────────
_ACTION_FILE = _BACKEND / "harness" / "wh1_loop.py"
# 2026-09-18 실측 baseline. 필드가 늘거나 줄면 RED — 특히 숙달·능력치 축이 생기면
# LLM이 상태를 실어 보낼 자리가 생긴 것이다.
_ACTION_FIELDS_BASELINE: dict[str, frozenset[str]] = {
    "CurateHypothesisAction": frozenset({"kind", "turns_elapsed"}),
    "EndTurnAction": frozenset({"action_type", "kind", "utterance"}),
    "LogEvidenceAction": frozenset({"kind", "misconception_id", "polarity", "weight"}),
    "MatchMisconceptionAction": frozenset({"kind", "student_text"}),
    "QueryCurriculumAction": frozenset({"kind", "node_id", "relation"}),
    "ReadStateAction": frozenset({"kind", "node_ids"}),
    "SelectProbeAction": frozenset({"administered", "candidates", "kind", "outside_mids", "theta"}),
    "VerifyStepAction": frozenset({"kind", "steps"}),
}
# 학습 상태 권위를 뜻하는 필드명 조각 — 액션에 등장하면 곧바로 위반이다.
# `theta`는 예외다: `SelectProbeAction.theta`는 정책이 *사적으로 보유한 값으로 채우는* 진단
# 컨텍스트이지 LLM이 정하는 상태가 아니다(wh1_llm_policy 민감 인자 격리 계약). baseline이
# 그 한 자리를 이미 고정하고 있으므로, 새로 생기는 theta 필드는 baseline 대조에서 걸린다.
_STATE_AUTHORITY_TOKENS = ("mastery", "proficiency", "ability", "skill_level", "competence")


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _production_modules() -> list[Path]:
    """l2를 제외한 백엔드 프로덕션 소스 전수 — writer 좌석 스캔 대상."""
    return sorted(
        p
        for p in _BACKEND.rglob("*.py")
        if "__pycache__" not in p.parts and not p.relative_to(_BACKEND).as_posix().startswith("l2/")
    )


def _imports_mastery_writer(tree: ast.Module) -> bool:
    """모듈이 mastery *쓰기* 진입점을 임포트하는가 — 지연 import(함수 안)도 `walk`로 본다."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in _MASTERY_WRITER_MODULES:
                return True
            if any(alias.name in _MASTERY_WRITER_NAMES for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name in _MASTERY_WRITER_MODULES for alias in node.names):
                return True
    return False


# ──────────────────────────────────────────────────────────────────────
# ① 발화 승격이 갈아끼우는 키 집합
# ──────────────────────────────────────────────────────────────────────
def _promotion_update_keys() -> list[list[str]]:
    """`_wh1_primary_decision_or` 안의 `.model_copy(update={...})` 리터럴 키 목록.

    리터럴 dict만 본다 — 비리터럴 `update=`는 정적으로 키를 알 수 없으므로 아래에서 **위반**
    으로 계상한다(정직한 공백이 아니라 막아야 할 구멍이다: 변수 하나로 이 가드를 통째로
    우회할 수 있기 때문).
    """
    tree = _parse(_PROMOTION_FILE)
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == _PROMOTION_FUNC
        ),
        None,
    )
    assert target is not None, (
        f"{_PROMOTION_FUNC!r}를 {_PROMOTION_FILE.name}에서 못 찾았다 — 스캔이 깨졌다"
        " (함수명이 바뀌었으면 이 가드의 좌석도 함께 옮겨야 한다)"
    )
    found: list[list[str]] = []
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "model_copy"):
            continue
        update = next((kw.value for kw in node.keywords if kw.arg == "update"), None)
        assert isinstance(update, ast.Dict), (
            "발화 승격이 리터럴이 아닌 update= 로 필드를 바꾼다 — 무엇을 쓰는지 정적으로 알 수"
            " 없으면 이 경계는 검사 불가다(변수 하나로 가드를 우회하는 형태)"
        )
        keys: list[str] = []
        for key in update.keys:
            assert isinstance(key, ast.Constant) and isinstance(
                key.value, str
            ), "발화 승격 update= 의 키가 문자열 리터럴이 아니다 — 정적 판정 불가"
            keys.append(key.value)
        found.append(keys)
    return found


class TestUtterancePromotionWritesOnlyTheUtterance:
    """① LLM 발화는 *발화 본문*만 갈아끼운다 — 구조화 교수 결정은 결정론 경로 소유."""

    def test_promotion_call_sites_were_found(self) -> None:
        """스캔 0건 방어 — 승격 호출을 못 찾으면 아래 검사가 공허하게 통과한다."""
        assert (
            _promotion_update_keys()
        ), "발화 승격(`model_copy(update=...)`) 호출을 한 건도 못 찾았다 — 스캔이 깨졌다"

    def test_only_the_utterance_field_is_overwritten(self) -> None:
        for keys in _promotion_update_keys():
            assert set(keys) == {_UTTERANCE_FIELD}, (
                f"LLM 발화 승격이 {sorted(set(keys) - {_UTTERANCE_FIELD})} 까지 갈아끼운다 — "
                "LLM은 학습 상태를 결정하지 않는다(설계 규율). 발화 본문 외의 결정은 "
                "Assessment/Mastery/Policy 엔진이 소유한다."
            )


# ──────────────────────────────────────────────────────────────────────
# ② mastery writer를 쥔 좌석 전수
# ──────────────────────────────────────────────────────────────────────
def _writer_seats() -> list[str]:
    return [
        p.relative_to(_BACKEND).as_posix()
        for p in _production_modules()
        if _imports_mastery_writer(_parse(p))
    ]


class TestMasteryWritersStayOutOfTheTutorPath:
    """② 튜터 경로는 숙달을 *쓰지* 않는다 — 읽기·리포트는 정당하므로 writer만 잰다."""

    def test_scan_found_production_modules(self) -> None:
        """스캔 0건 방어."""
        assert len(_production_modules()) > 50, "프로덕션 모듈 스캔이 비었다 — 스캔이 깨졌다"

    def test_writer_seats_are_nonempty(self) -> None:
        """대조군 — writer를 쥔 좌석이 *있어야* 한다. 0건이면 탐지기가 죽은 것이다."""
        assert _writer_seats(), (
            "mastery writer를 임포트한 모듈을 한 건도 못 찾았다 — 탐지기가 죽었다"
            "(이름이 바뀌었으면 _MASTERY_WRITER_NAMES 를 함께 갱신해야 한다)"
        )

    def test_writer_seats_match_the_frozen_allowlist(self) -> None:
        assert set(_writer_seats()) == set(_ALLOWED_WRITER_SEATS), (
            f"mastery writer 좌석이 바뀌었다: {sorted(_writer_seats())} "
            f"(동결: {sorted(_ALLOWED_WRITER_SEATS)}). 새 좌석이 정당하다면 이 목록과 함께 "
            "'누가 학습 상태를 쓰는가'를 다시 판정한 뒤 갱신한다."
        )

    def test_tutor_path_holds_no_mastery_writer(self) -> None:
        offenders = [seat for seat in _writer_seats() if seat.startswith(_TUTOR_PATH_PREFIXES)]
        assert not offenders, (
            f"튜터 경로가 mastery writer를 쥐었다: {offenders}. LLM 튜터링 경로에서 숙달을 "
            "직접 쓰면 'LLM → Mastery = 0.83' 형태의 경로가 열린다 — 설계 규율 위반."
        )


# ──────────────────────────────────────────────────────────────────────
# ③ LLM 도구 액션 타입의 필드 집합
# ──────────────────────────────────────────────────────────────────────
def _action_fields() -> dict[str, frozenset[str]]:
    """`wh1_loop.py`의 `*Action` ClassDef별 선언 필드명 — AST만으로(백엔드 미설치 잡 대응).

    상속 필드(`_ActionBase`)는 각 클래스가 자기 `kind`를 선언하므로 별도 병합이 불필요하다.
    """
    tree = _parse(_ACTION_FILE)
    out: dict[str, frozenset[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.name.endswith("Action"):
            continue
        if node.name.startswith("_"):  # `_ActionBase` — 추상 베이스는 대상 아님
            continue
        fields = {
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        out[node.name] = frozenset(fields)
    return out


class TestTutorActionTypesCarryNoLearningState:
    """③ LLM이 고르는 도구 액션에 숙달·능력치 필드가 없다 — 실을 *자리*를 두지 않는다."""

    def test_action_classes_were_found(self) -> None:
        """스캔 0건 방어."""
        assert (
            _action_fields()
        ), f"{_ACTION_FILE.name}에서 Action 클래스를 못 찾았다 — 스캔이 깨졌다"

    def test_action_field_sets_match_the_frozen_baseline(self) -> None:
        assert _action_fields() == _ACTION_FIELDS_BASELINE, (
            "튜터 도구 액션의 필드 구성이 바뀌었다. 필드를 늘릴 때는 그것이 *LLM이 정해도 되는 "
            "비민감 스칼라*인지 먼저 판정한다 — 학습 상태 축이면 이 경계 위반이다."
        )

    def test_no_action_field_names_a_state_authority_axis(self) -> None:
        """baseline과 독립인 두 번째 축 — baseline을 '갱신'하며 뚫는 경로를 막는다."""
        for cls, fields in _action_fields().items():
            for field in sorted(fields):
                lowered = field.lower()
                hits = [tok for tok in _STATE_AUTHORITY_TOKENS if tok in lowered]
                assert not hits, (
                    f"{cls}.{field} 가 학습 상태 축({hits})을 이름에 담았다 — LLM 출력 타입은 "
                    "도구 선택과 비민감 스칼라까지다(LearnerState 변경은 엔진 소유)."
                )
