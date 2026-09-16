"""curricula API 라우터 단위테스트 — FakeSession 주입(라이브 PG 없음, hermetic).

`get_session` 의존성을 가짜 세션으로 오버라이드해 *엔드포인트 결선*(상태코드·직렬화·404/422
분기·노드 뷰 투영·subject-neutral 경로 계약)을 검증한다(test_concepts.py 동형 분담 — 실제 SQL
정확성은 test_curricula_integration.py의 실 PG 몫). CUR-11의 다섯 표면 중 이 파일은 curricula
라우터 4종을, alignments는 test_alignments.py가 본다.

FakeSession은 test_me_target_progress.py의 *execute 큐* 관례를 답습한다 — 상세 조회(단건 get →
버전 execute)처럼 한 핸들러가 get과 execute를 섞어 부르므로, get은 (모델, PK) 맵으로, execute는
호출 순서 큐로 모사한다.

전부 GET·무인증(공개 카탈로그 선례 — concepts/problems GET)이라 인증 오버라이드가 없다:
헤더 없는 호출이 200인 것 자체가 무인증 계약의 회귀 검증이다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from whymath_backend.api import curricula
from whymath_backend.app import create_app
from whymath_backend.db.models.achievement_standard import AchievementStandard
from whymath_backend.db.models.curriculum_entry import CurriculumEntry
from whymath_backend.db.models.curriculum_framework import CurriculumFramework
from whymath_backend.db.models.curriculum_version import CurriculumVersion
from whymath_backend.db.session import get_session
from whymath_backend.schema.curriculum_entry import CurriculumEntry as CurriculumEntrySchema
from whymath_backend.schema.curriculum_framework import (
    CurriculumFramework as CurriculumFrameworkSchema,
)
from whymath_backend.schema.curriculum_version import (
    CurriculumVersion as CurriculumVersionSchema,
)
from whymath_backend.schema.enums import CurriculumLicense
from whymath_backend.schema.standard import (
    AchievementStandard as AchievementStandardSchema,
)

_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class FakeSession:
    """AsyncSession 표면 일부 모사 — 라우터가 부르는 get/execute만.

    get은 (모델 클래스, PK) 맵 조회, execute는 *호출 순서 큐*(test_me_target_progress.py 관례
    — 한 핸들러가 여러 execute를 부를 수 있으므로 pop(0)). 큐가 비면 빈 결과를 돌려준다
    (빈 목록 경로를 별도 적재 없이 모사). execute 호출 횟수를 기록해 "필요할 때만 조회"
    (404 조기 반환 시 엔트리 미조회) 결선을 검증할 수 있게 한다.
    """

    def __init__(
        self,
        *,
        get_map: dict[tuple[type, str], Any] | None = None,
        execute_queue: list[list[Any]] | None = None,
    ) -> None:
        self._get_map = dict(get_map or {})
        self._queue = list(execute_queue or [])
        self.execute_calls = 0

    async def get(self, model: type, pk: str) -> Any | None:
        return self._get_map.get((model, pk))

    async def execute(self, _stmt: Any) -> _FakeResult:
        self.execute_calls += 1
        if not self._queue:
            return _FakeResult([])
        return _FakeResult(self._queue.pop(0))


def _client(fake: FakeSession) -> TestClient:
    app = create_app()

    async def _override() -> AsyncIterator[FakeSession]:
        yield fake

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


# ── 표본 ORM 빌더 (from_schema — 라이브 PG 불필요·transient) ──────────────
def _framework(framework_id: str = "KR_NC_2022") -> CurriculumFramework:
    return CurriculumFramework.from_schema(
        CurriculumFrameworkSchema(
            framework_id=framework_id,
            authority="한국 교육부",
            country="KR",
            title="2022 개정 교육과정",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )


def _version(framework_id: str = "KR_NC_2022", label: str = "2022_REV_01") -> CurriculumVersion:
    return CurriculumVersion.from_schema(
        CurriculumVersionSchema(
            version_id=uuid.uuid4(),
            framework_id=framework_id,
            version_label=label,
            effective_from=date(2025, 3, 1),
            created_at=_NOW,
            updated_at=_NOW,
        )
    )


def _entry(
    entry_id: str = "ce-0001",
    *,
    framework_id: str | None = "KR_NC_2022",
    codes: list[str] | None = None,
) -> CurriculumEntry:
    return CurriculumEntry.from_schema(
        CurriculumEntrySchema(
            entry_id=entry_id,
            concept_id="math.algebra.polynomial",
            country_code="KR",
            source_name="NCIC",
            source_url="https://ncic.re.kr/example",
            license_id=CurriculumLicense.KR_NCIC,
            framework_id=framework_id,
            domain_label="변화와 관계",
            introduced_grade=10,
            is_present=True,
            confidence=0.9,
            national_standard_codes=list(codes or ["[10공수1-01-01]"]),
            notation_local="다항식 표기",  # 노드 뷰 *제외* 축 — 응답 부재 검증용
            created_at=_NOW,
            updated_at=_NOW,
        )
    )


def _standard(norm_id: str = "2022_10공수1_01_01") -> AchievementStandard:
    return AchievementStandard.from_schema(
        AchievementStandardSchema(
            norm_id=norm_id,
            official_code="[10공수1-01-01]",
            curriculum_revision="2022 개정",
            framework_id="KR_NC_2022",
            grade_band="고등학교",
            school_type="고등학교",
            subject="공통수학1",
            domain="변화와 관계",
            statement="다항식의 사칙연산의 원리를 설명하고, 그 계산을 할 수 있다.",
            official_statement="다항식의 사칙연산의 원리를 설명하고, 그 계산을 할 수 있다.",
            source_url="https://ncic.re.kr/example",
            version_id=uuid.uuid4(),
        )
    )


# ──────────────────────────────────────────────────────────────────────────
# GET /v1/curricula — 목록·페이지네이션
# ──────────────────────────────────────────────────────────────────────────
class TestListCurricula:
    def test_list_returns_rows(self) -> None:
        """행이 있으면 200 + to_schema 직렬화(framework_id 에코)."""
        fake = FakeSession(execute_queue=[[_framework("KR_NC_2015"), _framework("KR_NC_2022")]])
        resp = _client(fake).get("/v1/curricula")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [f["framework_id"] for f in body] == ["KR_NC_2015", "KR_NC_2022"]

    def test_list_empty_returns_empty_list(self) -> None:
        """빈 결과 → 200 + [] (404 아님 — 목록 계약)."""
        fake = FakeSession()
        resp = _client(fake).get("/v1/curricula")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_accepts_country_and_status_filters(self) -> None:
        """country·status(alias) 필터가 422 없이 통과하고 조회를 1회 수행한다."""
        fake = FakeSession(execute_queue=[[_framework()]])
        resp = _client(fake).get("/v1/curricula", params={"country": "KR", "status": "published"})
        assert resp.status_code == 200
        assert fake.execute_calls == 1

    def test_list_rejects_bad_status_value(self) -> None:
        """status가 생명주기 Literal 밖 값이면 422."""
        resp = _client(FakeSession()).get("/v1/curricula", params={"status": "bogus"})
        assert resp.status_code == 422

    def test_list_rejects_bad_pagination(self) -> None:
        """limit=0(ge=1 위반)·offset=-1(ge=0 위반) → 422."""
        client = _client(FakeSession())
        assert client.get("/v1/curricula", params={"limit": 0}).status_code == 422
        assert client.get("/v1/curricula", params={"offset": -1}).status_code == 422
        assert client.get("/v1/curricula", params={"limit": 201}).status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# GET /v1/curricula/{framework_id} — 단건 + 버전 동봉
# ──────────────────────────────────────────────────────────────────────────
class TestReadCurriculum:
    def test_read_existing_returns_framework_and_versions(self) -> None:
        """존재하는 framework → 200 + framework 본체 + versions 목록."""
        fw = _framework()
        fake = FakeSession(
            get_map={(CurriculumFramework, "KR_NC_2022"): fw},
            execute_queue=[[_version(label="2022_REV_01"), _version(label="2022_REV_02")]],
        )
        resp = _client(fake).get("/v1/curricula/KR_NC_2022")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["framework"]["framework_id"] == "KR_NC_2022"
        assert [v["version_label"] for v in body["versions"]] == ["2022_REV_01", "2022_REV_02"]

    def test_read_existing_with_no_versions(self) -> None:
        """버전이 아직 없어도 200 + versions=[] (정직한 빈 목록)."""
        fake = FakeSession(get_map={(CurriculumFramework, "KR_NC_2022"): _framework()})
        resp = _client(fake).get("/v1/curricula/KR_NC_2022")
        assert resp.status_code == 200
        assert resp.json()["versions"] == []

    def test_read_missing_returns_404(self) -> None:
        """없는 framework_id → 404 (버전 조회도 수행하지 않는다 — 조기 반환)."""
        fake = FakeSession()
        resp = _client(fake).get("/v1/curricula/NOPE")
        assert resp.status_code == 404
        assert fake.execute_calls == 0

    def test_read_overlong_framework_id_returns_422(self) -> None:
        """경로 파라미터가 컬럼 길이(64) 초과 → 422 (조기 거부)."""
        resp = _client(FakeSession()).get(f"/v1/curricula/{'x' * 65}")
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# GET /v1/curricula/{framework_id}/nodes — 개념 노드 뷰
# ──────────────────────────────────────────────────────────────────────────
class TestCurriculumNodes:
    def test_nodes_returns_projected_view(self) -> None:
        """엔트리가 노드 뷰로 투영된다 — 포함 축은 값, 제외 축(notation 등)은 키 자체가 없다."""
        fake = FakeSession(
            get_map={(CurriculumFramework, "KR_NC_2022"): _framework()},
            execute_queue=[[_entry("ce-0001")]],
        )
        resp = _client(fake).get("/v1/curricula/KR_NC_2022/nodes")
        assert resp.status_code == 200, resp.text
        (node,) = resp.json()
        assert node["entry_id"] == "ce-0001"
        assert node["concept_id"] == "math.algebra.polynomial"
        assert node["subject"] == "수학"  # subject는 경로가 아니라 데이터 축(기본값 에코)
        assert node["national_standard_codes"] == ["[10공수1-01-01]"]
        assert node["license_id"] == "KR-NCIC"
        # 제외 축 — 노드 뷰 계약(표기·맥락·교과서 참조·감사 필드는 싣지 않는다).
        for excluded in (
            "notation_local",
            "introduced_context",
            "textbook_unit_refs",
            "source_url",
        ):
            assert excluded not in node

    def test_nodes_normalizes_null_arrays(self) -> None:
        """ORM 배열 컬럼이 NULL이어도 응답은 빈 목록(소비처 분기 제거)."""
        entry = _entry("ce-0002")
        entry.prerequisite_concept_ids = None  # DB에서 NULL로 온 상황 모사
        fake = FakeSession(
            get_map={(CurriculumFramework, "KR_NC_2022"): _framework()},
            execute_queue=[[entry]],
        )
        resp = _client(fake).get("/v1/curricula/KR_NC_2022/nodes")
        assert resp.status_code == 200
        assert resp.json()[0]["prerequisite_concept_ids"] == []

    def test_nodes_missing_framework_returns_404_without_entry_query(self) -> None:
        """framework 부재 → 404, 엔트리 조회는 수행하지 않는다."""
        fake = FakeSession(execute_queue=[[_entry()]])
        resp = _client(fake).get("/v1/curricula/NOPE/nodes")
        assert resp.status_code == 404
        assert fake.execute_calls == 0

    def test_nodes_empty_returns_empty_list(self) -> None:
        """framework는 있으나 연결 엔트리가 없으면 200 + []."""
        fake = FakeSession(get_map={(CurriculumFramework, "KR_NC_2022"): _framework()})
        resp = _client(fake).get("/v1/curricula/KR_NC_2022/nodes")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_nodes_accepts_data_axis_filters(self) -> None:
        """subject·country_code·present_only는 쿼리 필터(데이터 축)로 통과한다."""
        fake = FakeSession(
            get_map={(CurriculumFramework, "KR_NC_2022"): _framework()},
            execute_queue=[[_entry()]],
        )
        resp = _client(fake).get(
            "/v1/curricula/KR_NC_2022/nodes",
            params={"subject": "수학", "country_code": "KR", "present_only": "true"},
        )
        assert resp.status_code == 200

    def test_nodes_rejects_bad_pagination(self) -> None:
        """limit 범위 위반 → 422."""
        fake = FakeSession(get_map={(CurriculumFramework, "KR_NC_2022"): _framework()})
        resp = _client(fake).get("/v1/curricula/KR_NC_2022/nodes", params={"limit": 0})
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# GET /v1/learning-outcomes/{norm_id} — 성취기준 단건
# ──────────────────────────────────────────────────────────────────────────
class TestReadLearningOutcome:
    def test_read_existing_returns_200(self) -> None:
        """존재하는 norm_id → 200 + 전체 스키마(본문은 NCIC 공공누리 1유형·source_url 동봉)."""
        std = _standard()
        fake = FakeSession(get_map={(AchievementStandard, "2022_10공수1_01_01"): std})
        resp = _client(fake).get("/v1/learning-outcomes/2022_10공수1_01_01")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["norm_id"] == "2022_10공수1_01_01"
        assert body["official_code"] == "[10공수1-01-01]"
        # 출처 표시 의무(공공누리 1유형) — source_url이 응답에 실린다.
        assert body["source_url"] == "https://ncic.re.kr/example"

    def test_read_missing_returns_404(self) -> None:
        """없는 norm_id → 404."""
        resp = _client(FakeSession()).get("/v1/learning-outcomes/2022_없음_01_01")
        assert resp.status_code == 404

    def test_read_overlong_norm_id_returns_422(self) -> None:
        """경로 파라미터가 컬럼 길이(32) 초과 → 422."""
        resp = _client(FakeSession()).get(f"/v1/learning-outcomes/{'x' * 33}")
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Subject-neutral 경로 계약 (acceptance ②) — 기계 동결
# ──────────────────────────────────────────────────────────────────────────
def _all_route_paths(app: Any) -> set[str]:
    """앱의 전체 경로 집합 — 지연 포함(_IncludedRouter)까지 평탄화.

    실측: 현행 FastAPI는 `include_router`를 즉시 전개하지 않고 `app.routes`에 지연 포함
    컨테이너(`.path` 없음, `original_router`만 보유)로 담는다. `.path`만 긁으면 포함된
    라우터의 경로가 전부 누락된다. 라우터 *자체* prefix는 route.path에 이미 구워져 있고
    (실측: APIRouter(prefix="/v1")의 route.path == "/v1/curricula"), include 시점 prefix만
    별도(include_context.prefix)라 그것만 붙인다(구버전 즉시 전개·신버전 지연 포함 양쪽 동작).
    """
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
            continue
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(route, "include_context", None)
            include_prefix = str(getattr(ctx, "prefix", "") or "")
            for sub in inner.routes:
                sub_path = getattr(sub, "path", None)
                if isinstance(sub_path, str):
                    paths.add(include_prefix + sub_path)
    return paths


class TestSubjectNeutralPaths:
    def test_curriculum_routes_registered_and_subject_neutral(self) -> None:
        """CUR-11 다섯 경로가 등록돼 있고, 경로 문자열에 과목 특화 세그먼트가 없다.

        `/math/grade/10/unit/3` 류의 과목·학년·단원 *경로* 세그먼트 금지 — 과목·학년은
        쿼리 필터(데이터 축)로만 표현한다는 계약을 라우팅 테이블에서 직접 검증한다.
        """
        app = create_app()
        paths = _all_route_paths(app)
        expected = {
            "/v1/curricula",
            "/v1/curricula/{framework_id}",
            "/v1/curricula/{framework_id}/nodes",
            "/v1/learning-outcomes/{norm_id}",
            "/v1/alignments",
        }
        assert expected <= paths
        forbidden_segments = ("/math/", "/grade/", "/unit/", "/subject/")
        for path in paths:
            if path.startswith(("/v1/curricula", "/v1/learning-outcomes", "/v1/alignments")):
                for seg in forbidden_segments:
                    assert seg not in path, f"과목 특화 경로 금지 위반: {path}"


# ──────────────────────────────────────────────────────────────────────────
# GET /v1/learning-outcomes/{norm_id}/learning-map — 학습맵 (EOS-05)
#
# 계획서 200 §18의 단일 질의. 조회 조립은 L1(`build_learning_map`)이 하고 그 로직은
# `tests/backend/l1/standards/test_learning_map.py`가 동결한다 — 여기서 보는 것은
# **엔드포인트 결선**이다(404 조기 반환·L1에 넘기는 인자·응답 직렬화·회계 필드 노출).
# ──────────────────────────────────────────────────────────────────────────
class TestLearningMap:
    def test_unknown_norm_id_returns_404_without_touching_the_chain(self) -> None:
        """없는 성취기준이면 404이고 **뒤 홉 조회를 시작하지 않는다**.

        404인데 체인이 돌면 없는 성취기준에 대해 DB를 4번 훑는다 — 조기 반환 결선의 회귀 검증.
        """
        fake = FakeSession(get_map={})
        response = _client(fake).get("/v1/learning-outcomes/없는코드/learning-map")

        assert response.status_code == 404
        assert fake.execute_calls == 0, "404인데 학습맵 체인이 조회를 시작했다"

    def test_passes_both_standard_vocabularies_down_to_l1(self, monkeypatch: Any) -> None:
        """핸들러가 norm_id와 official_code를 **둘 다** 내려주는가.

        L1이 축별로 다른 어휘로 묻는 것은 두 값을 다 받기 때문이다 — 핸들러가 한쪽만 넘기면
        L1의 어휘 분기가 조용히 무력해진다(2·3축이 전건 0이 되고 그 0은 '없음'으로 읽힌다).
        """
        standard = _standard()
        captured: dict[str, Any] = {}

        async def _stub(_session: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _empty_learning_map(kwargs["norm_id"], kwargs["official_code"])

        monkeypatch.setattr(curricula, "build_learning_map", _stub)
        fake = FakeSession(get_map={(AchievementStandard, standard.norm_id): standard})
        response = _client(fake).get(
            f"/v1/learning-outcomes/{standard.norm_id}/learning-map?concept_limit=7"
        )

        assert response.status_code == 200
        assert captured["norm_id"] == standard.norm_id
        assert captured["official_code"] == standard.official_code
        assert captured["concept_limit"] == 7, "쿼리 상한이 L1까지 전달되지 않았다"

    def test_response_carries_per_hop_accounting_not_just_items(self, monkeypatch: Any) -> None:
        """빈 배열만 주고 회계를 빼면 소비처가 '없음'과 '안 봄'을 구분할 수 없다."""
        standard = _standard()

        async def _stub(_session: Any, **kwargs: Any) -> Any:
            return _empty_learning_map(kwargs["norm_id"], kwargs["official_code"])

        monkeypatch.setattr(curricula, "build_learning_map", _stub)
        fake = FakeSession(get_map={(AchievementStandard, standard.norm_id): standard})
        body = _client(fake).get(f"/v1/learning-outcomes/{standard.norm_id}/learning-map").json()

        for hop in ("concept_stats", "skill_stats", "problem_stats", "misconception_stats"):
            assert hop in body, f"{hop} 회계가 응답에 없다 — 빈 배열의 원인을 알 수 없다"
            assert set(body[hop]) == {"scanned", "resolved", "produced", "join_blackout"}
        assert body["official_code"] == standard.official_code

    def test_serializes_chain_items_with_provenance(self, monkeypatch: Any) -> None:
        """항목 4종이 직렬화되고 유래(via_*·matched_by·resolved_from)가 살아 나오는가."""
        standard = _standard()
        concept_id, problem_id = uuid.uuid4(), uuid.uuid4()

        async def _stub(_session: Any, **kwargs: Any) -> Any:
            from whymath_backend.l1.standards import learning_map as lm

            return lm.LearningMap(
                norm_id=kwargs["norm_id"],
                official_code=kwargs["official_code"],
                concepts=(
                    lm.LearningMapConcept(
                        concept_key="UC.poly",
                        axes=("concept_standard_link",),
                        concept_id=concept_id,
                        name_ko="다항식",
                        resolved_from=("concept",),
                    ),
                ),
                skills=(
                    lm.LearningMapSkill(
                        skill_id="skill.factor",
                        name_ko="인수분해",
                        behavior_area="계산",
                        family="algebra",
                        mastery_estimable=True,
                        via_concept_keys=("UC.poly",),
                    ),
                ),
                problems=(
                    lm.LearningMapProblem(
                        problem_id=problem_id,
                        question_format="단답형",
                        answer_format="수식",
                        difficulty_overall=3.0,
                        via_concept_ids=(concept_id,),
                    ),
                ),
                misconceptions=(
                    lm.LearningMapMisconception(
                        mis_id="M0425",
                        canonical_statement="영곱규칙 오적용",
                        error_type="절차",
                        severity="high",
                        matched_by=("concept_src_id",),
                    ),
                ),
                concept_stats=lm.HopStats(1, 1, 1),
                skill_stats=lm.HopStats(1, 1, 1),
                problem_stats=lm.HopStats(1, 1, 1),
                misconception_stats=lm.HopStats(1, 1, 1),
                alignment_stats=(),
            )

        monkeypatch.setattr(curricula, "build_learning_map", _stub)
        fake = FakeSession(get_map={(AchievementStandard, standard.norm_id): standard})
        body = _client(fake).get(f"/v1/learning-outcomes/{standard.norm_id}/learning-map").json()

        assert body["concepts"][0]["resolved_from"] == ["concept"]
        assert body["skills"][0]["via_concept_keys"] == ["UC.poly"]
        assert body["problems"][0]["via_concept_ids"] == [str(concept_id)]
        assert body["misconceptions"][0]["matched_by"] == ["concept_src_id"]
        # 회계는 **값이 통과**해야 한다 — 필드 이름만 보면 상수로 위장한 핸들러가 통과한다
        # (뮤테이션 M10 생존으로 실측: 2026-09-16). scanned=0은 "안 봄"을 뜻하므로,
        # 실제로 1건을 훑은 응답이 0을 말하면 소비처가 정반대로 읽는다.
        assert body["concept_stats"] == {
            "scanned": 1,
            "resolved": 1,
            "produced": 1,
            "join_blackout": False,
        }
        assert body["skill_stats"]["scanned"] == 1
        assert body["problem_stats"]["produced"] == 1
        assert body["misconception_stats"]["resolved"] == 1
        # 저작권 레일 — 문제 **본문**은 이 응답에 담지 않는다(구조 메타데이터만).
        assert "question_text" not in body["problems"][0]

    def test_learning_map_path_is_subject_neutral_and_registered(self) -> None:
        """경로가 등록돼 있고 과목 특화 세그먼트가 없다 — 이 파일의 subject-neutral 계약 계승."""
        paths = _all_route_paths(create_app())
        assert "/v1/learning-outcomes/{norm_id}/learning-map" in paths


def _empty_learning_map(norm_id: str, official_code: str) -> Any:
    from whymath_backend.l1.standards import learning_map as lm

    zero = lm.HopStats(0, 0, 0)
    return lm.LearningMap(
        norm_id=norm_id,
        official_code=official_code,
        concepts=(),
        skills=(),
        problems=(),
        misconceptions=(),
        concept_stats=zero,
        skill_stats=zero,
        problem_stats=zero,
        misconception_stats=zero,
        alignment_stats=(),
    )
