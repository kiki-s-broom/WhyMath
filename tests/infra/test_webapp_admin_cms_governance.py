"""CMS 웹 화면(`app/admin` 7개 화면 + `adminCmsApi.ts`)의 경계 동결 — P3-12.

`test_webapp_admin_shell_governance.py`(셸 전체)·`test_webapp_admin_review_governance.py`(검수 큐)가
이미 *모든 admin 소스*에 거는 규칙(하드코딩 nav 0 · BFF 경유 · `fetch(` 파일당 1회 · HTML 주입 0 ·
자격증명 저장소 금지)은 새 파일에도 그대로 걸린다. 이 파일은 **CMS 화면이 새로 만든 표면**만 동결한다:

  ① 레지스트리의 CMS 모듈 7종이 `live`이고 각자의 화면 파일이 실재한다(`.admin.tsx` 접미)
  ② CMS 소스가 admin 전용으로 분류돼 검사 모수에 들어온다
  ③ 공개 소스가 CMS 코드를 import하지 않는다(역방향 누출)
  ④ CMS 엔드포인트 경로(`/v1/admin/cms`)는 `adminCmsApi.ts` 한 곳 — 화면 컴포넌트가 직접 경로를 만들면
     토큰 부착·타임아웃·예외 타입명 기록이 갈라진다
  ⑤ 화면이 **권한 판정을 복제하지 않는다** — 역할 이름 리터럴이 없다(어떤 버튼을 보일지는 서버가 준
     값, 가능 여부는 서버의 권한 검사가 정한다)
  ⑥ 변별력 봉인 — ③④⑤의 판정 함수에 위반을 주입하면 검출되고 정상 입력은 통과한다

**정직한 공백**: 렌더 결과(버튼 노출·409 흐름·0건/실패 구분)와 클라이언트가 부르는 경로가 실제 백엔드
라우트와 맞는지는 정적 검사로 못 본다. 그 축은 실백엔드를 세워 헤드리스 브라우저로 도는 종단 검증이
소유하며, 이 파일이 통과해도 화면이 *동작*한다는 증명은 아니다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


def _load(name: str) -> object:
    """형제 거버넌스 모듈을 경로로 로딩한다(`tests/infra/`는 패키지가 아니다)."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location("_" + name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None, f"모듈을 못 읽었다: {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_shell = _load("test_webapp_admin_shell_governance.py")
_landing = _load("test_webapp_landing_governance.py")
_admin_sources = _shell._admin_sources  # type: ignore[attr-defined]
_scan = _shell._scan  # type: ignore[attr-defined]
_registry_text = _shell._registry_text  # type: ignore[attr-defined]
parse_modules = _shell.parse_modules  # type: ignore[attr-defined]
is_admin_only = _landing.is_admin_only  # type: ignore[attr-defined]
_repo_sources = _landing._repo_sources  # type: ignore[attr-defined]

_ADMIN_DIR = _shell._ADMIN_DIR  # type: ignore[attr-defined]
_API_REL = "app/admin/_lib/adminCmsApi.ts"

#: CMS 화면을 가진 레지스트리 모듈(P3-12). 이 7종이 `live`여야 내비에서 눌러 들어갈 수 있다.
#: 모듈 id를 *테스트*가 적는 것은 하드코딩 nav가 아니다(그 규칙은 프런트 소스에만 건다).
_CMS_MODULE_IDS = (
    "curriculum",
    "pedagogy_pack",
    "knowledge_graph",
    "misconception",
    "content_library",
    "content_version",
    "deployment",
)

#: CMS 화면이 새로 만든 소스 — 전부 admin 전용으로 분류돼야 한다.
_CMS_SOURCES = (
    _API_REL,
    "app/admin/_components/CmsCommon.tsx",
    "app/admin/_components/CmsResourceScreen.tsx",
    "app/admin/_components/CmsResourcePanel.tsx",
    "app/admin/_components/CmsResourceDetail.tsx",
    "app/admin/_components/CmsConceptWorkspace.tsx",
    "app/admin/_components/CmsConceptStudioPane.tsx",
    "app/admin/_components/CmsVersionPane.tsx",
)

#: 권한 판정 복제 표지 — 역할 이름 리터럴. 화면은 역할을 모른다.
_ROLE_NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("역할 이름 리터럴", re.compile(r"""["']content_(?:admin|editor|reviewer|publisher)["']""")),
    ("역할 enum 참조", re.compile(r"\bRole\.(?:CONTENT|ADMIN)\w*")),
)

_CMS_PATH = re.compile(r"/v1/admin/cms")


def cms_path_leak_violations(sources: dict[str, str]) -> list[str]:
    """CMS 엔드포인트 경로 리터럴이 `adminCmsApi.ts` 밖에 있으면 위반. 입력이 비면 위반."""
    if not sources or _API_REL not in sources:
        return ["스캔 대상이 0건이거나 adminCmsApi.ts가 없다 — 가드가 무력화됐다"]
    outside = {rel: text for rel, text in sources.items() if rel != _API_REL}
    if not outside:
        return ["API 파일 밖 소스가 0건 — 가드가 무력화됐다"]
    return _scan(outside, (("CMS 엔드포인트 경로", _CMS_PATH),))


def public_import_violations(public: dict[str, str]) -> list[str]:
    """공개 소스가 CMS 모듈을 가리키는 import·경로를 갖고 있으면 위반."""
    if not public:
        return ["공개 소스가 0건 — 경로가 바뀌었거나 가드가 무력화됐다"]
    rx = re.compile(
        r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*)["'][^"']*(?:adminCmsApi|/Cms[A-Z]\w*)"""
    )
    return [
        f"{rel}: 공개 소스가 CMS 코드를 import한다"
        for rel, text in sorted(public.items())
        if rx.search(text)
    ]


# ── ① 모듈 live ↔ 화면 파일 ─────────────────────────────────────────────


def test_cms_modules_are_live_and_have_pages() -> None:
    """① — CMS 모듈 7종이 `live`이고 `.admin.tsx` 화면 파일이 실재하며 접미 없는 변종이 없다."""
    modules = {m["id"]: m for m in parse_modules(_registry_text())}
    assert set(_CMS_MODULE_IDS) <= set(modules), "레지스트리에서 CMS 모듈을 못 찾았다"
    for module_id in _CMS_MODULE_IDS:
        module = modules[module_id]
        assert (
            module["status"] == "live"
        ), f"{module_id}: status={module['status']} — 화면이 있는데 live가 아니다"
        route = module["route"]
        assert route.startswith("/admin/"), (module_id, route)
        page_dir = _ADMIN_DIR.joinpath(*route[len("/admin/") :].strip("/").split("/"))
        assert (
            page_dir / "page.admin.tsx"
        ).is_file(), f"{module_id}: {page_dir}에 page.admin.tsx가 없다"
        bare = [p.name for p in page_dir.iterdir() if p.is_file() and ".admin." not in p.name]
        assert not bare, f"{module_id}: 접미 없는 파일 — 공개 빌드에 실릴 수 있다: {bare}"


def test_each_cms_page_renders_a_cms_component() -> None:
    """① 양성 대조 — 페이지가 비어 있지 않고 CMS 컴포넌트를 실제로 그린다(빈 페이지로 live 위장 금지)."""
    modules = {m["id"]: m for m in parse_modules(_registry_text())}
    for module_id in _CMS_MODULE_IDS:
        route = modules[module_id]["route"]
        page = (
            _ADMIN_DIR.joinpath(*route[len("/admin/") :].strip("/").split("/")) / "page.admin.tsx"
        )
        text = page.read_text(encoding="utf-8")
        assert re.search(
            r"<Cms(?:ResourceScreen|ConceptWorkspace)\b", text
        ), f"{module_id}: 페이지가 CMS 컴포넌트를 그리지 않는다"


# ── ② 모수 분류 ─────────────────────────────────────────────────────────


def test_cms_sources_are_classified_admin_only() -> None:
    """② — 새 파일이 전부 admin 전용으로 분류돼 위 전수 검사(nav·BFF·fetch·HTML)의 모수에 들어온다."""
    sources = _admin_sources()
    for rel in _CMS_SOURCES:
        assert rel in sources, f"admin 소스 모수에 없다: {rel}"


# ── ③ 역방향 import ─────────────────────────────────────────────────────


def test_public_sources_do_not_import_cms_code() -> None:
    """③ — 공개 소스(비-admin)가 CMS 코드를 import하지 않는다."""
    public = {rel: text for rel, text in _repo_sources().items() if not is_admin_only(rel)}
    assert public_import_violations(public) == []


# ── ④ 경로는 한 곳 ──────────────────────────────────────────────────────


def test_cms_paths_live_only_in_the_cms_client() -> None:
    """④ — `/v1/admin/cms` 경로 리터럴이 `adminCmsApi.ts` 밖에 없다."""
    assert cms_path_leak_violations(_admin_sources()) == []


def test_cms_client_actually_holds_the_markers() -> None:
    """④ 양성 대조 — 금지만 보면 '아무도 호출하지 않는다'도 통과한다. 클라이언트에 실재해야 한다."""
    text = _admin_sources()[_API_REL]
    assert _CMS_PATH.search(text), "클라이언트에 CMS 경로가 없다 — 계약 ④가 공허하다"
    assert re.search(r"Bearer\s", text) and re.search(r"\bAuthorization\b", text)
    assert 'credentials: "omit"' in text and "AbortSignal.timeout" in text
    # 쓰기 메서드가 요청 지점 하나를 지난다 — 읽기만 있는 클라이언트면 화면은 CMS가 아니다.
    assert '"PATCH"' in text and '"POST"' in text


# ── ⑤ 권한 판정 복제 금지 ───────────────────────────────────────────────


def test_cms_sources_do_not_decide_by_role() -> None:
    """⑤ — CMS 소스에 역할 이름이 없다. 화면은 서버가 준 값만 따르고, 막는 것은 서버다."""
    cms = {rel: text for rel, text in _admin_sources().items() if rel in _CMS_SOURCES}
    assert set(cms) == set(_CMS_SOURCES), "CMS 소스 모수가 비었다 — 가드가 무력화됐다"
    assert _scan(cms, _ROLE_NAME_PATTERNS) == []


# ── ⑥ 변별력 봉인 (결함 주입 + 양성 대조) ───────────────────────────────

_CLEAN = {
    _API_REL: 'const CMS_BASE = "/v1/admin/cms";\nawait fetch(base + path);\n',
    "app/admin/_components/CmsResourceDetail.tsx": "export function X() { return <p>{text}</p>; }\n",
}


@pytest.mark.parametrize(
    "fixture",
    [
        'const url = "/v1/admin/cms/concepts";',
        "const url = `${base}/v1/admin/cms/resources`;",
        'fetchLike("/v1/admin/cms/audit?x=1");',
    ],
)
def test_path_judge_detects_leak_outside_the_client(fixture: str) -> None:
    """⑥ — 컴포넌트에 CMS 경로가 새면 검출된다(문자열·템플릿 표기 모두)."""
    sources = dict(_CLEAN)
    sources["app/admin/_components/CmsVersionPane.tsx"] = fixture
    assert cms_path_leak_violations(sources)


@pytest.mark.parametrize(
    "fixture",
    [
        'if (role === "content_publisher") showPublish();',
        "const ok = ['content_admin', 'content_editor'].includes(r);",
        "if (user.role === Role.CONTENT_REVIEWER) {}",
    ],
)
def test_role_judge_detects_role_literals(fixture: str) -> None:
    """⑥ — 역할 이름으로 권한을 가르는 코드가 검출된다."""
    assert _scan({"app/admin/_components/CmsVersionPane.tsx": fixture}, _ROLE_NAME_PATTERNS)


@pytest.mark.parametrize(
    "fixture",
    [
        'import { x } from "../admin/_lib/adminCmsApi";',
        'import { CmsResourceScreen } from "../admin/_components/CmsResourceScreen";',
        'const m = await import("../admin/_components/CmsVersionPane");',
    ],
)
def test_public_import_judge_detects_injected_violation(fixture: str) -> None:
    """⑥ — 공개 소스의 CMS import가 검출된다."""
    assert public_import_violations({"app/(public)/page.tsx": fixture})


def test_judges_pass_on_clean_input() -> None:
    """⑥ 양성 대조 — 정상 입력은 위반 0(무차별 실패가 아니다). 권한 이름이 아닌 capability 문자열은 허용."""
    assert cms_path_leak_violations(_CLEAN) == []
    assert (
        public_import_violations({"app/(public)/page.tsx": "export default function P(){}"}) == []
    )
    allowed = 'const canRollback = capabilities.includes("publish");'
    assert _scan({"app/admin/_components/CmsVersionPane.tsx": allowed}, _ROLE_NAME_PATTERNS) == []


def test_judges_report_empty_scan_as_violation() -> None:
    """⑥ — 스캔 0건은 통과가 아니라 위반이다."""
    assert cms_path_leak_violations({})
    assert public_import_violations({})
    assert _scan({}, _ROLE_NAME_PATTERNS)
    # 클라이언트 파일이 모수에서 빠져도(경로 변경) 위반 — 통과로 위장되지 않는다.
    assert cms_path_leak_violations({"app/admin/_components/CmsVersionPane.tsx": "x"})
