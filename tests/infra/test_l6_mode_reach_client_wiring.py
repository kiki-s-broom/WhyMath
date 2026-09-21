"""[PB-04] L6 응용 모드 6종 — 클라 미배선 정적 관측(그레이-박스) 게이트.

왜 이 테스트가 있는가
--------------------
`api/gating.py`에 L6 응용 모드 6종(재도전·수능·학교진도·사고력·메타인지·영재)이 이미
`GET /v1/gating/{retake,suneung,school-progress,thinking,metacognition,gifted}`로 구현돼
있지만, 학생 앱(`src/mobile`)·웹(`src/web`) 어디도 이 6개 경로를 호출하지 않는다(실측 —
`problem_bank_gap_review_r2.md` §0-②-나). 학생 앱이 부르는 유일한 추천 표면
`GET /v1/me/next-problem`(`problems_api.dart` `getNextProblem()`)도 `mode` 쿼리 파라미터를
아예 보내지 않는다 — 서버가 받을 수 있는 모드 값공간(`NextProblemMode`)도 `Literal['suneung']
| None` 1종뿐이다(`api/me.py`). 즉 6개 응용 모드 전부 *학생 도달 0회*다.

이 테스트는 그 실측을 grep 기반으로 고정한다 — `api/_l6_mode_reach_state.py`(라이브 카운터)와
이 정적 게이트가 **이중 회계**를 이룬다(라이브 값이 SaaS 관측 없이도 검증 가능한 것처럼, 정적
값은 라이브 서버 없이도 검증 가능하다).

**이 게이트는 미래의 배선을 막는 금지 규칙이 아니다.** `PB-04-l6-mode-reach-observability`
acceptance③은 "관측 없이 확장하지 않는다"이지 "영원히 확장하지 않는다"가 아니다 — 관측
인프라(`L6ModeReachCounters`·`/health/ready` 노출)가 이미 갖춰졌으니, 향후 클라가 실제로
특정 모드를 배선하는 PR은 정당하다. 그런 PR이 이 테스트를 깨뜨리면, 그것은 버그가 아니라
**"클라가 실제로 모드를 배선하기 시작했다"는 신호**다 — 아래 각 실패 메시지가 그 다음 확인
사항(`NextProblemMode` 값공간 확장 여부·`L6ModeReachCounters` 값 상승)을 명시한다. 담당자는
이 assertion을 그냥 고쳐서 넘기지 말고, 그 확인을 거친 뒤 의식적으로 갱신해야 한다.

검증 계약
--------
① 스캔 대상(모바일·웹 소스)이 비어 있지 않다(경로 이동·개명 시 공허한 green 차단)
② `src/mobile`·`src/web` 소스에 6개 gating 엔드포인트 경로 문자열이 없다
③ `problems_api.dart`의 `getNextProblem()` 호출부가 `mode` 쿼리 파라미터를 보내지 않는다
④ 파서가 위장하지 않는다 — 대상 디렉터리·대상 메서드 자체가 없으면 "위반 0 통과"가 아니라 실패
⑤ 변별력 — 결함주입(양성 대조 + 실제로 검출되는 반례)으로 게이트가 살아있음을 실증
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 소스만 스캔한다 — node_modules·dist·coverage·.dart_tool·build(벤더/빌드 산출물)는 제외.
# ARCH-27(test_shipped_asset_judgement_governance.py)이 출하 자산을 별도로 이미 다루므로
# 여기서는 "사람이 짜는 클라이언트 소스"만 본다.
_MOBILE_SOURCE_DIRS: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "mobile" / "lib",
    _REPO_ROOT / "src" / "mobile" / "test",
)
_WEB_SOURCE_DIRS: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "web" / "graphing-calculator" / "src",
    _REPO_ROOT / "src" / "web" / "graphing-calculator" / "test",
)
_ALL_SOURCE_DIRS: tuple[Path, ...] = _MOBILE_SOURCE_DIRS + _WEB_SOURCE_DIRS

_SCAN_EXTENSIONS = frozenset({".dart", ".ts", ".tsx", ".js", ".jsx"})

_NEXT_PROBLEM_API_FILE = (
    _REPO_ROOT / "src" / "mobile" / "lib" / "features" / "problems" / "data" / "problems_api.dart"
)

# L6 6개 gating 엔드포인트 경로(라우터 prefix 포함 — 부분 문자열 오탐 방지를 위해 `/v1/gating/`
# 까지 앵커).
_GATING_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gating:retake", re.compile(r"/v1/gating/retake")),
    ("gating:suneung", re.compile(r"/v1/gating/suneung")),
    ("gating:school-progress", re.compile(r"/v1/gating/school-progress")),
    ("gating:thinking", re.compile(r"/v1/gating/thinking")),
    ("gating:metacognition", re.compile(r"/v1/gating/metacognition")),
    ("gating:gifted", re.compile(r"/v1/gating/gifted")),
)

# getNextProblem() 메서드 본문 추출 — Dart 2-space 들여쓰기 규약에서 메서드 시작부터 첫
# "\n  }"(멤버 레벨 닫는 중괄호)까지. 본문 내부 중괄호(맵 리터럴·async 블록)는 4칸 이상 들여쓰기라
# 이 앵커에 걸리지 않는다(problems_api.dart 실측 확인).
_GET_NEXT_PROBLEM_METHOD_PATTERN = re.compile(
    r"Future<NextProblemResponse>\s+getNextProblem\(.*?\n  \}", re.S
)
# 쿼리 파라미터 맵에 'mode' 키를 넣는 패턴(작은따옴표/큰따옴표 모두 허용).
_MODE_QUERY_PARAM_PATTERN = re.compile(r"""['"]mode['"]\s*:""")


def _walk_source_files(root: Path) -> list[Path]:
    """`root` 하위 스캔 대상 확장자 파일을 정렬해 돌려준다.

    디렉터리 자체가 없으면 조용히 빈 리스트(=위반 0 위장)가 아니라 예외로 실패한다(계약④).
    """
    if not root.is_dir():
        raise AssertionError(
            f"{root} 이(가) 없다 — 클라이언트 소스 스캔 대상 경로가 바뀌었을 수 있다. "
            "이 게이트가 실제로 무엇을 보고 있는지 다시 확인하라."
        )
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in _SCAN_EXTENSIONS)


def _all_client_source_files() -> list[Path]:
    files: list[Path] = []
    for root in _ALL_SOURCE_DIRS:
        files.extend(_walk_source_files(root))
    return files


def _scan_gating_paths(
    files: list[Path],
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = _GATING_PATH_PATTERNS,
) -> dict[str, list[str]]:
    """파일별로 매치된 gating 경로 패턴 이름 목록을 돌려준다(매치 0건인 파일은 결과에서 제외)."""
    violations: dict[str, list[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [name for name, pattern in patterns if pattern.search(text)]
        if hits:
            violations[str(path)] = hits
    return violations


def _extract_get_next_problem_body(text: str) -> str:
    match = _GET_NEXT_PROBLEM_METHOD_PATTERN.search(text)
    if match is None:
        raise AssertionError(
            "problems_api.dart에서 getNextProblem() 메서드를 찾지 못했다 — 메서드 시그니처나 "
            "포맷팅이 바뀌어 이 게이트의 추출 정규식이 더는 맞지 않는다(위장 방지·계약④)."
        )
    return match.group(0)


# ──────────────────────────────────────────────────────────────────────
# 계약① — 스캔 대상 비어있지 않음
# ──────────────────────────────────────────────────────────────────────
def test_scan_target_is_not_empty() -> None:
    """계약① — 실 저장소 클라이언트 소스 스캔 대상이 비어 있지 않다(게이트 무력화 방지)."""
    files = _all_client_source_files()
    assert len(files) > 10, (
        f"src/mobile·src/web 소스 스캔 대상이 {len(files)}건뿐 — 경로가 바뀌었거나 게이트가 "
        "빈 디렉터리를 스캔하고 있다(공허한 green 위험)."
    )


# ──────────────────────────────────────────────────────────────────────
# 계약② — 6개 gating 경로 무일치
# ──────────────────────────────────────────────────────────────────────
def test_no_client_code_calls_gating_endpoints() -> None:
    """계약② — src/mobile·src/web 소스 어디도 6개 L6 gating 엔드포인트를 호출하지 않는다.

    실패하면: 클라가 실제로 L6 응용 모드 하나를 배선하기 시작했다는 뜻이다. 버그가 아니다 —
    다만 그냥 이 assertion을 지우거나 예외 목록에 넣고 넘어가지 마라. ①`L6ModeReachCounters`
    (`api/_l6_mode_reach_state.py`)의 해당 모드 값이 라이브에서도 실제로 올라가는지 함께
    확인하고 ②이 테스트를 "그 모드는 이제 배선됐다"는 의식적 갱신으로 고쳐라(예: 해당 모드를
    패턴 목록에서 빼고 왜 빠졌는지 주석을 남긴다).
    """
    files = _all_client_source_files()
    violations = _scan_gating_paths(files)
    assert violations == {}, (
        "클라이언트 소스(학생 실기기로 나가는 mobile/web)에 L6 gating 엔드포인트 호출 흔적이"
        f"있다 — 위 docstring의 실패 처리 절차를 따르라. 위반 파일: {violations}"
    )


# ──────────────────────────────────────────────────────────────────────
# 계약③ — next-problem이 mode 파라미터를 보내지 않음
# ──────────────────────────────────────────────────────────────────────
def test_next_problem_call_site_does_not_send_mode_param() -> None:
    """계약③ — `getNextProblem()`이 `mode` 쿼리 파라미터를 보내지 않는다(서버 기본 CAT 고정).

    실패하면: 클라가 next-problem에 mode를 배선하기 시작했다는 뜻이다. 이때 반드시 함께
    확인하라 — `api/me.py`의 `NextProblemMode`(`Literal['suneung'] | None`) 값공간이 클라가
    보내려는 모드를 실제로 받아주는가? 값공간 밖의 mode를 보내면 서버가 422로 거부한다(관측
    없는 확장 자체가 여기서 막힌다). 값공간이 이미 그 모드를 포함한다면(예: 'suneung'), 이
    assertion은 의식적으로 갱신해도 좋다(이 파일 상단 docstring 참고).
    """
    if not _NEXT_PROBLEM_API_FILE.is_file():
        raise AssertionError(
            f"{_NEXT_PROBLEM_API_FILE} 이(가) 없다 — problems_api.dart 경로가 바뀌었다. "
            "이 게이트가 실제로 무엇을 보고 있는지 다시 확인하라(계약④)."
        )
    text = _NEXT_PROBLEM_API_FILE.read_text(encoding="utf-8")
    body = _extract_get_next_problem_body(text)
    assert not _MODE_QUERY_PARAM_PATTERN.search(body), (
        "getNextProblem()이 'mode' 쿼리 파라미터를 보내는 코드가 감지됐다 — 위 docstring의 "
        f"실패 처리 절차를 따르라.\n메서드 본문:\n{body}"
    )


# ──────────────────────────────────────────────────────────────────────
# 계약④ — 파서가 위장하지 않는다(디렉터리·메서드 부재 시 실패)
# ──────────────────────────────────────────────────────────────────────
def test_parser_fails_loudly_when_source_dir_missing(tmp_path: Path) -> None:
    """계약④ — 스캔 대상 디렉터리 자체가 없으면 위반 0으로 위장하지 않고 예외."""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(AssertionError, match="없다"):
        _walk_source_files(missing)


def test_parser_fails_loudly_when_get_next_problem_method_missing() -> None:
    """계약④ — getNextProblem() 메서드를 못 찾으면 위반 0으로 위장하지 않고 예외."""
    with pytest.raises(AssertionError, match="찾지 못했다"):
        _extract_get_next_problem_body("class ProblemsApi { /* no such method here */ }")


# ──────────────────────────────────────────────────────────────────────
# 계약⑤ — 변별력(결함주입)
# ──────────────────────────────────────────────────────────────────────
def test_control_clean_client_file_passes(tmp_path: Path) -> None:
    """계약⑤(양성 대조) — gating 경로가 없는 정상 클라 코드는 위반 0."""
    clean = tmp_path / "problems_api.dart"
    clean.write_text(
        "Future<NextProblemResponse> getNextProblem() async {"
        " return _dio.get('/v1/me/next-problem'); }",
        encoding="utf-8",
    )
    assert _scan_gating_paths([clean]) == {}


def test_defect_gating_path_call_is_detected(tmp_path: Path) -> None:
    """계약⑤ — gating 경로 문자열이 재유입되면 검출된다(6종 각각)."""
    for name, pattern in _GATING_PATH_PATTERNS:
        injected = tmp_path / f"probe_{name.replace(':', '_').replace('-', '_')}.dart"
        injected.write_text(f"_dio.get('{pattern.pattern}');", encoding="utf-8")
        violations = _scan_gating_paths([injected])
        assert violations, f"{name} 결함주입이 검출되지 않았다 — 게이트가 무력화됐다."
        assert name in violations[str(injected)]


def test_defect_mode_query_param_is_detected() -> None:
    """계약⑤ — getNextProblem()에 mode 쿼리 파라미터가 재유입되면 검출된다."""
    injected_source = """
class ProblemsApi {
  Future<NextProblemResponse> getNextProblem({String? mode}) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/v1/me/next-problem',
      queryParameters: <String, dynamic>{
        if (mode != null) 'mode': mode,
      },
    );
    return NextProblemResponse.fromJson(_requireBody(response));
  }
}
"""
    body = _extract_get_next_problem_body(injected_source)
    assert _MODE_QUERY_PARAM_PATTERN.search(body), "mode 쿼리 파라미터 결함주입이 검출되지 않았다."


def test_real_problems_api_file_extraction_matches_only_get_next_problem() -> None:
    """계약⑤ — 실 파일 추출이 getNextProblem 본문만 잘라내고 다음 메서드(getProblem)를 안 삼킨다.

    추출 경계가 너무 넓으면(다음 메서드까지 삼키면) mode 오탐/누락이 생길 수 있다 — 실 파일로
    경계 정확성을 확인한다.
    """
    text = _NEXT_PROBLEM_API_FILE.read_text(encoding="utf-8")
    body = _extract_get_next_problem_body(text)
    assert "getNextProblem" in body
    assert "getProblem(String problemId)" not in body
