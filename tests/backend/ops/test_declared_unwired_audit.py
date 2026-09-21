"""선언≠배선 일반 탐지기 hermetic 테스트 — OPS-22.

전부 DB·LLM·HTTP 0(빌드타임 결정론). 합성 패키지 트리(`tmp_path`)로 4축 수집기의 변별력을
직접 실측한다 — "성공/실패 양쪽에서 같은 값을 내는 검사는 검증이 아니라 위장"(CLAUDE.md)을
따라 각 축마다 ⑴탐지됨(양성) ⑵탐지 안 됨(음성) 양쪽을 확인한다. 그랜드파더 만료 계약
(`_classify`)은 `ops/provenance_audit.py`(ARCH-25) 테스트 패턴을 그대로 답습한다.

실 저장소 스캔(`build_report()` 기본 인자)은 회귀 테스트 1건만 — 그 상세 분류는
`declared_unwired_audit._MANIFEST`(코드 리뷰 대상)의 소관이지 이 테스트의 소관이 아니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from whymath_backend.ops import declared_unwired_audit as dua


def _write_task_yaml(tasks_dir: Path, task_id: str, *, status: str) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.yaml").write_text(
        yaml.safe_dump({"id": task_id, "status": status}, allow_unicode=True),
        encoding="utf-8",
    )


# ──────────────────────────────────────────────────────────────────────────
# 경로 정규화·템플릿 매칭
# ──────────────────────────────────────────────────────────────────────────


class TestPathNormalization:
    def test_server_param_normalized(self) -> None:
        assert dua.normalize_server_path("/v1/problems/{problem_id}") == "/v1/problems/{param}"

    def test_dart_interpolation_normalized(self) -> None:
        assert dua.normalize_client_path("/v1/problems/$problemId") == "/v1/problems/{param}"
        assert dua.normalize_client_path("/v1/problems/${problemId}") == "/v1/problems/{param}"

    def test_python_fstring_interpolation_normalized(self) -> None:
        assert dua.normalize_client_path("/v1/me/sessions/{jti}/end") == (
            "/v1/me/sessions/{param}/end"
        )

    def test_literal_segment_untouched(self) -> None:
        """테스트가 흔히 쓰는 리터럴 더미 값(`j1`)은 인터폴레이션이 아니므로 안 건드린다 —
        매칭은 `_route_reached`의 템플릿 정규식이 담당한다(아래 클래스)."""
        assert dua.normalize_client_path("/v1/jobs/j1") == "/v1/jobs/j1"


class TestRouteReached:
    def test_literal_dummy_id_matches_template(self) -> None:
        """`client.get('/v1/jobs/j1')`처럼 인터폴레이션 없는 리터럴 더미 ID도 서버 템플릿
        `/v1/jobs/{job_id}`에 매칭돼야 한다(과거 실패 사례 — exact-string 비교로는 놓친다)."""
        callers = frozenset({("GET", "/v1/jobs/j1")})
        assert dua._route_reached("GET", "/v1/jobs/{job_id}", callers) is True

    def test_unmatched_route_not_reached(self) -> None:
        callers = frozenset({("GET", "/v1/jobs/j1")})
        assert dua._route_reached("GET", "/v1/problems/{problem_id}", callers) is False

    def test_method_mismatch_not_reached(self) -> None:
        callers = frozenset({("POST", "/v1/problems/1")})
        assert dua._route_reached("GET", "/v1/problems/{problem_id}", callers) is False


# ──────────────────────────────────────────────────────────────────────────
# 축 1 — HTTP 호출 추출(dart·python 테스트)
# ──────────────────────────────────────────────────────────────────────────


class TestCallExtraction:
    def test_dart_dio_call_extracted(self, tmp_path: Path) -> None:
        lib = tmp_path / "lib"
        lib.mkdir()
        (lib / "api.dart").write_text(
            "class Api {\n"
            "  Future<void> call() async {\n"
            "    await _dio.get<Map<String, dynamic>>(\n"
            "      '/v1/problems/$problemId',\n"
            "    );\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        entries = dua.dart_call_entries(lib)
        assert ("GET", "/v1/problems/{param}") in entries

    def test_dart_call_with_no_lib_dir_returns_empty(self, tmp_path: Path) -> None:
        assert dua.dart_call_entries(tmp_path / "missing") == frozenset()

    def test_python_test_client_call_extracted(self, tmp_path: Path) -> None:
        tests_root = tmp_path / "tests_backend"
        tests_root.mkdir()
        (tests_root / "test_x.py").write_text(
            'def test_foo(client):\n    client.get("/v1/me/sessions?limit=1")\n',
            encoding="utf-8",
        )
        entries = dua.test_call_entries(tests_root)
        assert ("GET", "/v1/me/sessions") in entries  # 쿼리스트링 제거됨

    def test_python_test_client_request_variant_extracted(self, tmp_path: Path) -> None:
        """`client.request("DELETE", "/v1/me", ...)` 변형(바디를 실어야 하는 DELETE 등)."""
        tests_root = tmp_path / "tests_backend"
        tests_root.mkdir()
        (tests_root / "test_x.py").write_text(
            "def test_foo(client):\n"
            '    client.request("DELETE", "/v1/me", json={"confirmation": "y"})\n',
            encoding="utf-8",
        )
        entries = dua.test_call_entries(tests_root)
        assert ("DELETE", "/v1/me") in entries

    def test_unrelated_dict_get_not_extracted(self, tmp_path: Path) -> None:
        """`dict.get(...)` 같은 무관 호출이 라우트로 오탐되지 않는다(접두사 제한)."""
        tests_root = tmp_path / "tests_backend"
        tests_root.mkdir()
        (tests_root / "test_x.py").write_text(
            'def test_foo(payload):\n    payload.get("something")\n',
            encoding="utf-8",
        )
        assert dua.test_call_entries(tests_root) == frozenset()


class TestPathConstantIndirection:
    """모듈 레벨 경로 상수 1홉 해석 — OPS-25 (2026-08-10 오탐 동결).

    실측 사고: `tests/backend/api/test_me_growth_evidence.py`가 `_ENDPOINT` 상수로
    `GET /v1/me/growth-evidence`를 이미 때리고 있었는데 감사기가 **리터럴 문자열만** 봐서
    미도달로 보고했고, 그 오탐 하나로 `PED-15`라는 **유령 태스크가 백로그에 등재**됐다
    (`POST /v1/ocr/pages`는 같은 원인을 자인하는 by-design 유예로 덮여 있었다 — 오탐 2건).

    양방향을 함께 동결한다 — 상수를 *실제로 쓰지 않는* 호출이 도달로 새면(반대 방향 오탐)
    탐지기가 아무것도 못 잡게 되므로 지금보다 나쁘다.
    """

    @staticmethod
    def _entries(tmp_path: Path, body: str) -> frozenset[tuple[str, str]]:
        tests_root = tmp_path / "tests_backend"
        tests_root.mkdir(exist_ok=True)
        (tests_root / "test_x.py").write_text(body, encoding="utf-8")
        return dua.test_call_entries(tests_root)

    # ── 양성 ──────────────────────────────────────────────────────────────
    def test_module_level_constant_call_extracted(self, tmp_path: Path) -> None:
        """`_ENDPOINT = "/v1/me/growth-evidence"` + `client.get(_ENDPOINT)` — 실물 관용구."""
        entries = self._entries(
            tmp_path,
            '_ENDPOINT = "/v1/me/growth-evidence"\n'
            "def test_foo(client):\n    client.get(_ENDPOINT)\n",
        )
        assert ("GET", "/v1/me/growth-evidence") in entries

    def test_annotated_module_level_constant_extracted(self, tmp_path: Path) -> None:
        entries = self._entries(
            tmp_path,
            '_PATH: str = "/v1/ocr/pages"\n' "def test_foo(client):\n    client.post(_PATH)\n",
        )
        assert ("POST", "/v1/ocr/pages") in entries

    def test_fstring_query_suffix_on_constant_extracted(self, tmp_path: Path) -> None:
        """`f"{_ENDPOINT}?limit=1"` — 쿼리스트링은 잘라내고 경로만 남는다."""
        entries = self._entries(
            tmp_path,
            '_ENDPOINT = "/v1/me/sessions"\n'
            "def test_foo(client):\n"
            '    client.get(f"{_ENDPOINT}?limit=1")\n',
        )
        assert ("GET", "/v1/me/sessions") in entries

    def test_fstring_subpath_on_constant_extracted(self, tmp_path: Path) -> None:
        """`f"{_BASE}/{jti}/end"` — 값을 모르는 보간은 `{param}`으로 접어 템플릿 매칭에 맡긴다."""
        entries = self._entries(
            tmp_path,
            '_BASE = "/v1/me/sessions"\n'
            "def test_foo(client, jti):\n"
            '    client.post(f"{_BASE}/{jti}/end")\n',
        )
        assert ("POST", "/v1/me/sessions/{param}/end") in entries

    def test_request_variant_with_constant_extracted(self, tmp_path: Path) -> None:
        entries = self._entries(
            tmp_path,
            '_PATH = "/v1/me"\n'
            "def test_foo(client):\n"
            '    client.request("DELETE", _PATH, json={"confirmation": "y"})\n',
        )
        assert ("DELETE", "/v1/me") in entries

    # ── 음성 대조(필수) ───────────────────────────────────────────────────
    def test_function_local_constant_not_extracted(self, tmp_path: Path) -> None:
        """함수 지역 변수는 "모듈 레벨 1홉" 범위 밖 — 풀지 않는다.

        범위 제한 자체가 이 정밀도 개선의 안전 장치다(`_insert_helpers` 선례와 동일 절제).
        못 잡는 것은 미도달로 남아 대장 등재를 강제받는 안전 방향이다.
        """
        entries = self._entries(
            tmp_path,
            "def test_foo(client):\n"
            '    endpoint = "/v1/me/growth-evidence"\n'
            "    client.get(endpoint)\n",
        )
        assert entries == frozenset()

    def test_imported_constant_not_extracted(self, tmp_path: Path) -> None:
        """다른 모듈에서 import한 상수는 풀지 않는다(전역 상수 테이블 추적 금지)."""
        entries = self._entries(
            tmp_path,
            "from tests_backend.shared import _ENDPOINT\n"
            "def test_foo(client):\n    client.get(_ENDPOINT)\n",
        )
        assert entries == frozenset()

    def test_non_route_string_constant_not_extracted(self, tmp_path: Path) -> None:
        """라우트 접두(`/v1/`·`/health`·`/status`)가 아닌 문자열 상수는 경로가 아니다 —
        `payload.get(_KEY)` 같은 무관 호출이 도달로 새지 않게 하는 유일한 방어선."""
        entries = self._entries(
            tmp_path,
            '_KEY = "answer"\n'
            '_OTHER = "/internal/thing"\n'
            "def test_foo(payload, client):\n"
            "    payload.get(_KEY)\n"
            "    client.get(_OTHER)\n",
        )
        assert entries == frozenset()

    def test_unresolvable_expression_not_extracted(self, tmp_path: Path) -> None:
        """`+` 연결·`.format()` 등 풀지 않는 표현식은 도달로 뭉개지 않고 미도달로 남긴다."""
        entries = self._entries(
            tmp_path,
            '_BASE = "/v1/me"\n'
            "def test_foo(client):\n"
            '    client.get(_BASE + "/growth-evidence")\n'
            '    client.post("{}/x".format(_BASE))\n',
        )
        assert entries == frozenset()

    def test_undefined_name_argument_not_extracted(self, tmp_path: Path) -> None:
        """상수 사전에 없는 이름 인자는 도달 근거가 아니다(모르는 것을 도달로 치지 않는다)."""
        entries = self._entries(
            tmp_path,
            "def test_foo(client, some_path):\n    client.get(some_path)\n",
        )
        assert entries == frozenset()


# ──────────────────────────────────────────────────────────────────────────
# 축 2 — EventType 생산자·소비자
# ──────────────────────────────────────────────────────────────────────────


class TestEventProducerConsumer:
    def test_producer_detected(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "writer.py").write_text(
            "def emit():\n" "    return build_event_data(EventType.검산결과, passed=True)\n",
            encoding="utf-8",
        )
        assert "검산결과" in dua.produced_event_types(pkg)

    def test_producer_via_variable_not_detected(self, tmp_path: Path) -> None:
        """변수로 우회한 EventType 호출은 AST 리터럴 패턴에 안 잡힌다(안전 방향 — 모듈
        docstring 명시: 그런 EventType은 미도달로 보고돼 대장 등재를 강제받는다)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "writer.py").write_text(
            "et = EventType.검산결과\n"
            "def emit():\n"
            "    return build_event_data(et, passed=True)\n",
            encoding="utf-8",
        )
        assert "검산결과" not in dua.produced_event_types(pkg)

    def test_consumer_compare_detected(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "reader.py").write_text(
            "def q(row):\n    return row.event_type == EventType.검산결과\n",
            encoding="utf-8",
        )
        assert "검산결과" in dua.consumed_event_types(pkg)

    def test_producer_only_not_a_consumer(self, tmp_path: Path) -> None:
        """생산 좌석(`build_event_data` 첫 인자)은 `ast.Compare`가 아니므로 소비로 안 잡힌다
        — 축 2의 핵심 변별력(생산≠소비를 같은 AST 패턴으로 뭉개지 않는다)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "writer.py").write_text(
            "def emit():\n" "    return build_event_data(EventType.막힘, turn_count=5)\n",
            encoding="utf-8",
        )
        assert "막힘" not in dua.consumed_event_types(pkg)

    def test_consumer_via_module_level_frozenset_constant(self, tmp_path: Path) -> None:
        """`_SET = frozenset({EventType.막힘, …})` + `not in _SET` — 실물 관용구 (OPS-25).

        `l2/learning_metrics_rollup.py`가 소크라테스 3종을 이 형태로 필터링한다. `in`/`not in`도
        `ast.Compare`지만 피연산자가 `Name`이라 예전 구현은 못 봤고, 그래서 **이미 소비 중인**
        `EventType.막힘`이 미도달로 보고돼 `S4-22` 유예에 허위로 끼어 있었다.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            "_SOCRATIC = frozenset({EventType.막힘, EventType.힌트요청})\n"
            "def run(event):\n"
            "    if event.event_type not in _SOCRATIC:\n"
            "        return None\n"
            "    return event\n",
            encoding="utf-8",
        )
        consumed = dua.consumed_event_types(pkg)
        assert "막힘" in consumed
        assert "힌트요청" in consumed

    @pytest.mark.parametrize(
        "literal",
        [
            "{EventType.막힘}",
            "[EventType.막힘]",
            "(EventType.막힘,)",
            "set([EventType.막힘])",
            "tuple((EventType.막힘,))",
            "frozenset({EventType.막힘})",
        ],
    )
    def test_consumer_via_various_container_literals(self, tmp_path: Path, literal: str) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            f"_SET = {literal}\n" "def run(event):\n    return event.event_type in _SET\n",
            encoding="utf-8",
        )
        assert "막힘" in dua.consumed_event_types(pkg)

    def test_constant_defined_but_never_compared_is_not_consumed(self, tmp_path: Path) -> None:
        """**핵심 음성 대조** — 상수를 *정의만* 하고 비교에 쓰지 않으면 소비가 아니다.

        상수 해석을 "선언만 보면 소비"로 느슨하게 만들면 이 축이 전부 도달로 뭉개져
        아무것도 못 잡는 탐지기가 된다(지금보다 나쁜 반대 방향 오탐).
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            "_SET = frozenset({EventType.막힘})\n" "def run(event):\n    return len(_SET)\n",
            encoding="utf-8",
        )
        assert "막힘" not in dua.consumed_event_types(pkg)

    def test_function_local_event_constant_not_resolved(self, tmp_path: Path) -> None:
        """함수 지역 집합은 "모듈 레벨 1홉" 범위 밖 — 풀지 않는다(HTTP 축과 동일 절제)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            "def run(event):\n"
            "    local = frozenset({EventType.막힘})\n"
            "    return event.event_type in local\n",
            encoding="utf-8",
        )
        assert "막힘" not in dua.consumed_event_types(pkg)

    def test_dynamic_container_not_resolved(self, tmp_path: Path) -> None:
        """`tuple(EventType)`처럼 원소가 리터럴이 아닌 동적 구성은 풀지 않는다 — 풀면 enum
        전체가 한 방에 소비로 뭉개진다."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            "_ALL = tuple(EventType)\n" "def run(event):\n    return event.event_type in _ALL\n",
            encoding="utf-8",
        )
        assert dua.consumed_event_types(pkg) == frozenset()

    def test_unrelated_name_compare_not_consumed(self, tmp_path: Path) -> None:
        """상수 사전에 없는 이름과의 비교는 소비 근거가 아니다."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "rollup.py").write_text(
            "def run(event, allowed):\n    return event.event_type in allowed\n",
            encoding="utf-8",
        )
        assert dua.consumed_event_types(pkg) == frozenset()

    def test_contract_definition_file_excluded_from_consumers(self, tmp_path: Path) -> None:
        """`enums.py`/`event_data_contract.py` 자신은 정의이지 소비가 아니다."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "event_data_contract.py").write_text(
            "MAP = {EventType.검산결과: SomeSchema}\n"
            "def q(row):\n    return row.event_type == EventType.검산결과\n",
            encoding="utf-8",
        )
        assert "검산결과" not in dua.consumed_event_types(pkg)


# ──────────────────────────────────────────────────────────────────────────
# 축 3 — 타임시리즈 writer/reader
# ──────────────────────────────────────────────────────────────────────────


def _write_timeseries_models(pkg: Path, class_names: list[str]) -> None:
    models_dir = pkg / "db" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    body = "\n".join(
        f"class {name}(Base):\n    __tablename__ = '{name.lower()}'\n" for name in class_names
    )
    (models_dir / "timeseries.py").write_text("class Base:\n    pass\n\n" + body, encoding="utf-8")


class TestTimeseriesUsage:
    def test_models_extracted(self, tmp_path: Path) -> None:
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo", "Bar"])
        assert dua.timeseries_models(pkg) == ("Bar", "Foo")

    def test_writer_detected_via_constructor_call(self, tmp_path: Path) -> None:
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        writer_dir = pkg / "writers"
        writer_dir.mkdir()
        (writer_dir / "job.py").write_text(
            "from fakepkg.db.models.timeseries import Foo\n" "def run():\n    return Foo(x=1)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ("writers.job",)
        assert usage["Foo"].readers == ()

    def test_reader_detected_without_constructor_call(self, tmp_path: Path) -> None:
        """`(Foo, "user_id")`처럼 생성자 호출 없이 이름만 참조하는 삭제/반출 계획 튜플도
        reader로 잡혀야 한다(writer와 구분 — 실제 erasure.py 관용구와 동형)."""
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        reader_dir = pkg / "privacy"
        reader_dir.mkdir()
        (reader_dir / "erasure.py").write_text(
            "from fakepkg.db.models.timeseries import Foo\n" "PLAN = ((Foo, 'user_id'),)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ()
        assert usage["Foo"].readers == ("privacy.erasure",)

    def test_writer_detected_through_aliased_import(self, tmp_path: Path) -> None:
        """`import Foo as FooORM` 별칭 import도 writer로 잡혀야 한다 (2026-08-10 오탐 동결).

        예전 구현은 `alias.asname or alias.name`으로 **로컬명만** 모은 뒤 모델명 집합과 교집합을
        냈다 — 별칭이 붙으면 교집합이 비어 그 모듈을 통째로 건너뛰었다. 하필 이 감사기가
        "schema/timeseries.py에 동명 Pydantic 클래스가 있어 이름 기반 탐지는 위험하다"고 경고했고
        코드베이스가 그 모호성을 푸는 방법이 정확히 `as ...ORM` 별칭이라, 감사기가 자기가 지적한
        문제의 해법에 눈이 먼 상태였다(실측 결과: 시계열 3종 전부 '적재 0' 오탐).
        """
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        writer_dir = pkg / "l2"
        writer_dir.mkdir()
        (writer_dir / "rollup.py").write_text(
            "from fakepkg.db.models.timeseries import Foo as FooORM\n"
            "def run():\n    return FooORM(x=1)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ("l2.rollup",)

    def test_writer_detected_via_pg_insert_call(self, tmp_path: Path) -> None:
        """`pg_insert(Model).values(...)` bulk upsert도 적재다 (2026-08-10 오탐 동결).

        생성자 호출(`Model(...)`)만 writer로 보면 이 저장소의 **멱등 적재 정본 관용구**
        (`l1/problem_bank/populate.py` 이하 15개 projection/loader)를 통째로 놓친다.
        """
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        writer_dir = pkg / "l2"
        writer_dir.mkdir()
        (writer_dir / "rollup.py").write_text(
            "from fakepkg.db.models.timeseries import Foo as FooORM\n"
            "from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
            "def run(rows):\n"
            "    return pg_insert(FooORM).values(rows)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ("l2.rollup",)

    def test_writer_detected_through_module_local_upsert_helper(self, tmp_path: Path) -> None:
        """모델을 인자로 받아 insert하는 *모듈 내 헬퍼* 경유 적재(1-홉)도 writer다.

        `l2/learning_metrics_rollup.py::_upsert(session, orm_model, rows, …)` 실물 관용구.
        """
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        writer_dir = pkg / "l2"
        writer_dir.mkdir()
        (writer_dir / "rollup.py").write_text(
            "from fakepkg.db.models.timeseries import Foo as FooORM\n"
            "from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
            "def _upsert(session, orm_model, rows):\n"
            "    return pg_insert(orm_model).values(rows)\n"
            "def run(session, rows):\n"
            "    return _upsert(session, FooORM, rows)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ("l2.rollup",)

    def test_helper_without_insert_does_not_make_writer(self, tmp_path: Path) -> None:
        """변별력 음성 — 모델을 인자로 받기만 하고 insert하지 않는 헬퍼는 writer가 아니다."""
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        writer_dir = pkg / "l2"
        writer_dir.mkdir()
        (writer_dir / "rollup.py").write_text(
            "from fakepkg.db.models.timeseries import Foo as FooORM\n"
            "def _describe(session, orm_model):\n    return str(orm_model)\n"
            "def run(session):\n    return _describe(session, FooORM)\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ()
        assert usage["Foo"].readers == ("l2.rollup",)

    def test_orm_alias_and_schema_plain_name_coexist(self, tmp_path: Path) -> None:
        """같은 파일이 ORM은 별칭·Pydantic은 원명으로 가져오는 실물 배치(rollup)에서, 스키마
        쪽 사용이 ORM 적재로 새지 않는다 — 별칭 매핑의 부수 효과인 정밀도 향상을 동결한다."""
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        schema_dir = pkg / "schema"
        schema_dir.mkdir()
        (schema_dir / "timeseries.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
        writer_dir = pkg / "l2"
        writer_dir.mkdir()
        (writer_dir / "rollup.py").write_text(
            "from fakepkg.db.models.timeseries import Foo as FooORM\n"
            "from fakepkg.schema.timeseries import Foo\n"
            "def build():\n    return Foo(x=1)\n"  # Pydantic — 적재가 아니다
            "PLAN = ((FooORM, 'user_id'),)\n",  # ORM — reader
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ()
        assert usage["Foo"].readers == ("l2.rollup",)

    def test_neither_writer_nor_reader_when_unreferenced(self, tmp_path: Path) -> None:
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ()
        assert usage["Foo"].readers == ()

    def test_schema_pydantic_namespace_collision_not_counted(self, tmp_path: Path) -> None:
        """`schema.timeseries`의 동명 Pydantic 클래스 import는 ORM 소비로 오인되지 않는다
        (`db.models`에서 온 import만 candidates로 센다)."""
        pkg = tmp_path / "fakepkg"
        _write_timeseries_models(pkg, ["Foo"])
        schema_dir = pkg / "schema"
        schema_dir.mkdir()
        (schema_dir / "timeseries.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
        consumer_dir = pkg / "api"
        consumer_dir.mkdir()
        (consumer_dir / "endpoint.py").write_text(
            "from fakepkg.schema.timeseries import Foo\n" "def handler():\n    return Foo()\n",
            encoding="utf-8",
        )
        usage = dua.timeseries_usage(pkg, ("Foo",))
        assert usage["Foo"].writers == ()
        assert usage["Foo"].readers == ()


# ──────────────────────────────────────────────────────────────────────────
# 축 4 — harness/ops CLI ↔ CI/전이 import
# ──────────────────────────────────────────────────────────────────────────


class TestCliReachability:
    def _make_pkg(self, tmp_path: Path) -> Path:
        pkg = tmp_path / "fakepkg"
        (pkg / "harness").mkdir(parents=True)
        (pkg / "ops").mkdir(parents=True)
        return pkg

    def test_cli_modules_require_module_level_main(self, tmp_path: Path) -> None:
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "with_main.py").write_text(
            "def main():\n    return 0\n", encoding="utf-8"
        )
        (pkg / "harness" / "no_main.py").write_text(
            "def helper():\n    return 0\n", encoding="utf-8"
        )
        clis = dua.cli_modules(pkg)
        assert "harness.with_main" in clis
        assert "harness.no_main" not in clis

    def test_ci_direct_invocation_reached(self, tmp_path: Path) -> None:
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "gate.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        clis = dua.cli_modules(pkg)
        ci_roots = frozenset({"harness.gate"})
        reached = dua.reached_clis(pkg, clis, ci_roots)
        assert "harness.gate" in reached

    def test_unreached_cli_is_not_reached(self, tmp_path: Path) -> None:
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "orphan.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        clis = dua.cli_modules(pkg)
        reached = dua.reached_clis(pkg, clis, frozenset())
        assert "harness.orphan" not in reached

    def test_production_import_reaches_cli(self, tmp_path: Path) -> None:
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "metrics.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (pkg / "api").mkdir()
        (pkg / "api" / "endpoint.py").write_text(
            "from fakepkg.harness import metrics\n", encoding="utf-8"
        )
        clis = dua.cli_modules(pkg)
        reached = dua.reached_clis(pkg, clis, frozenset())
        assert "harness.metrics" in reached

    def test_transitive_in_process_import_reaches_cli(self, tmp_path: Path) -> None:
        """`qa_pipeline`류 관용구 — CI가 orchestrator만 직접 실행해도, orchestrator가
        in-process import하는 하위 CLI까지 전이 도달로 잡혀야 한다."""
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "sub_check.py").write_text(
            "def main():\n    return 0\n", encoding="utf-8"
        )
        (pkg / "harness" / "orchestrator.py").write_text(
            "from fakepkg.harness import sub_check\n" "def main():\n    return sub_check.main()\n",
            encoding="utf-8",
        )
        clis = dua.cli_modules(pkg)
        ci_roots = frozenset({"harness.orchestrator"})
        reached = dua.reached_clis(pkg, clis, ci_roots)
        assert "harness.orchestrator" in reached
        assert "harness.sub_check" in reached

    def test_test_only_import_does_not_reach_cli(self, tmp_path: Path) -> None:
        """스코프는 `src/backend`뿐 — 테스트 트리는 이 수집 대상 밖이라(패키지 루트 밖) 애초에
        스캔되지 않는다는 사실 자체가 계약이다(별도 `tests/`를 package_root로 넘기지 않는 한
        아예 보이지 않는다 — 여기선 패키지 안에 아무 것도 import하지 않는 구성으로 대체 확인)."""
        pkg = self._make_pkg(tmp_path)
        (pkg / "harness" / "only_tested.py").write_text(
            "def main():\n    return 0\n", encoding="utf-8"
        )
        clis = dua.cli_modules(pkg)
        reached = dua.reached_clis(pkg, clis, frozenset())
        assert "harness.only_tested" not in reached


# ──────────────────────────────────────────────────────────────────────────
# 분류(그랜드파더 만료 계약) — ARCH-25 패턴 이식
# ──────────────────────────────────────────────────────────────────────────


class TestClassify:
    def test_reached_with_no_manifest_entry_is_reached(self, tmp_path: Path) -> None:
        verdict = dua._classify("axis", "key", True, tmp_path)
        assert verdict.status == "reached"

    def test_unreached_with_no_manifest_entry_is_unclassified(self, tmp_path: Path) -> None:
        verdict = dua._classify("axis", "key", False, tmp_path)
        assert verdict.status == "unclassified"
        assert verdict.is_violation is True

    def test_reached_with_manifest_entry_is_stale_waiver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(dua._MANIFEST, "axis", {"key": "by-design:테스트"})
        verdict = dua._classify("axis", "key", True, tmp_path)
        assert verdict.status == "stale-waiver"
        assert verdict.is_violation is True

    def test_by_design_with_empty_reason_is_missing_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(dua._MANIFEST, "axis", {"key": "by-design:"})
        verdict = dua._classify("axis", "key", False, tmp_path)
        assert verdict.status == "missing-reason"
        assert verdict.is_violation is True

    def test_pending_task_nonexistent_is_expired_waiver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(dua._MANIFEST, "axis", {"key": "pending-task:NONEXISTENT-XYZ"})
        verdict = dua._classify("axis", "key", False, tmp_path)
        assert verdict.status == "expired-waiver"
        assert verdict.is_violation is True

    def test_pending_task_done_is_expired_waiver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_task_yaml(tmp_path, "FAKE-DONE", status="done")
        monkeypatch.setitem(dua._MANIFEST, "axis", {"key": "pending-task:FAKE-DONE"})
        verdict = dua._classify("axis", "key", False, tmp_path)
        assert verdict.status == "expired-waiver"
        assert verdict.is_violation is True

    def test_pending_task_open_is_valid_waiver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_task_yaml(tmp_path, "FAKE-TODO", status="todo")
        monkeypatch.setitem(dua._MANIFEST, "axis", {"key": "pending-task:FAKE-TODO"})
        verdict = dua._classify("axis", "key", False, tmp_path)
        assert verdict.status == "pending-task"
        assert verdict.is_violation is False


# ──────────────────────────────────────────────────────────────────────────
# 수집기 파손 방어(exit 2)
# ──────────────────────────────────────────────────────────────────────────


class TestCollectorFloorGuard:
    def test_below_floor_raises_collector_error(self, tmp_path: Path) -> None:
        """실 저장소가 아닌 빈 루트를 넘기면(라우트·CLI 등 전 축 0건) `CollectorError`가 나야
        한다 — '0건 통과'로 위장하지 않는다. `create_app()`은 실 앱을 그대로 쓰므로 라우트
        축은 항상 하한을 넘긴다(수집기 파손 조건은 dart/test 호출·CLI·타임시리즈 축에서
        인위적으로 재현한다)."""
        empty_root = tmp_path / "empty_repo"
        (empty_root / "src" / "backend" / "whymath_backend").mkdir(parents=True)
        (empty_root / "backlog" / "tasks").mkdir(parents=True)
        with pytest.raises(dua.CollectorError):
            dua.build_report(empty_root)


# ──────────────────────────────────────────────────────────────────────────
# 실 저장소 회귀 — 상세 분류는 `_MANIFEST`(코드 리뷰) 소관, 여기선 exit 0만 고정.
# ──────────────────────────────────────────────────────────────────────────


class TestRealRepositoryReport:
    def test_real_repo_report_passes(self) -> None:
        report = dua.build_report()
        assert report.exit_code == 0, [v.to_json() for v in report.violations]


class TestRealRepositoryConstantIndirectionDiscrimination:
    """실 저장소 양방향 변별력 — OPS-25 acceptance ④.

    합성 픽스처는 "고친 로직이 의도대로 도는가"만 본다. 이 클래스는 **실제 코드베이스에서**
    ⑴오탐이 실제로 사라졌는지 ⑵상수를 안 쓰는 진짜 미도달이 여전히 미도달로 남는지를 함께
    동결한다. ⑵가 없으면 "전부 도달"로 뭉개는 반대 방향 오탐을 못 잡는다.
    """

    def test_socratic_constant_event_now_consumed(self) -> None:
        """양성 — `EventType.막힘`은 `_SOCRATIC_EVENT_TYPES` 상수 필터로 이미 소비 중이다."""
        package_root = dua.repo_root() / "src" / "backend" / "whymath_backend"
        assert "막힘" in dua.consumed_event_types(package_root)

    def test_producer_only_events_remain_unconsumed(self) -> None:
        """음성 대조 — 답입력·시각화조작은 생산 좌석과 계약 정의에만 나타난다(실측).

        S4-22가 소비자를 배선하면 이 단언이 깨지는데, 그때는 감사기 대장의 같은 2건도
        `stale-waiver`가 되므로 **함께** 갱신하는 것이 맞다(둘은 같은 사실을 말한다).
        """
        package_root = dua.repo_root() / "src" / "backend" / "whymath_backend"
        consumed = dua.consumed_event_types(package_root)
        assert "답입력" not in consumed
        assert "시각화조작" not in consumed

    def test_constant_only_route_now_reached(self) -> None:
        """양성 — `POST /v1/ocr/pages`는 `_PAGES_PATH` 상수로만 호출된다(리터럴 0건).

        리터럴 스모크가 덧대진 `/v1/me/growth-evidence`와 달리 이 라우트는 상수 경유 호출이
        **유일한** 도달 경로라, 상수 해석이 퇴행하면 이 단언만 깨진다(변별력 있는 검사).
        """
        callers = dua.test_call_entries(dua.repo_root() / "tests" / "backend")
        assert ("POST", "/v1/ocr/pages") in callers

    def test_route_without_any_caller_stays_unreached(self) -> None:
        """음성 대조 — 아무도 안 부르는 라우트는 여전히 미도달이다(`GET /v1/me/skill-mastery`).

        대조군 교체(MOB-18 회수 2026-09-07): 이전 대조군은 `GET /v1/gating/gifted`였는데,
        PB-04 도달 관측 테스트(`test_l6_mode_reach_observability.py`)가 그 경로를 실제로
        호출하면서 **대조군 자격을 잃었다**(도달했으므로 이 단언이 정당하게 깨졌다).
        단언을 지우면 "전부 도달로 뭉개는 반대 방향 오탐"을 못 잡게 되므로 지우지 않고
        *진짜* 미호출 라우트로 갈아끼웠다 — 감사기 실측(`--json` 리포트)에서 by-design
        미도달 11건 중 하나다.

        `skill-mastery`를 고른 이유는 위 `test_producer_only_events_remain_unconsumed`와
        같은 성질 때문이다: 감사기 대장에 **짝이 되는 유예**가 있어(`api/me.py` Phase 2b-2
        선언), 언젠가 스킬 축 화면이 배선되면 이 단언과 그 유예가 *함께* 깨진다 — 둘은 같은
        사실을 말하므로 함께 갱신하는 것이 맞다. 유예 없는 라우트를 골랐다면 테스트만 조용히
        낡는다.
        """
        callers = dua.test_call_entries(
            dua.repo_root() / "tests" / "backend"
        ) | dua.dart_call_entries(dua.repo_root() / "src" / "mobile" / "lib")
        assert dua._route_reached("GET", "/v1/me/skill-mastery", callers) is False
