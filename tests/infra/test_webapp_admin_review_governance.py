"""검수 큐 웹 화면(`app/admin/review`)의 경계 동결 — ADMIN-07.

`test_webapp_admin_shell_governance.py`가 셸 전체(빌드 타깃 분리·하드코딩 nav·BFF 경유·자격증명)를
동결한다면, 이 파일은 **검수 큐 화면이 새로 만든 표면**의 규칙을 동결한다:

  ① 화면 라우트는 `.admin.tsx` 접미 — 접미가 떨어지면 공개 빌드에 `/admin/review`가 실린다
  ② 공개 소스가 검수 큐 코드를 import하지 않는다(역방향 누출 — 공개 번들에 admin 코드가 들어간다)
  ③ 원문 HTML 주입 경로 0건 — 문항 본문·해설은 저작물 원문이라 `dangerouslySetInnerHTML`·`innerHTML`로
     그리면 저장형 XSS 표면이 된다(텍스트 노드로만 렌더)
  ④ 토큰 부착·검수 큐 엔드포인트·전이 호출은 `adminReviewApi.ts` 한 곳 — 화면 컴포넌트가 직접
     요청을 만들면 타임아웃·`credentials:"omit"`·예외 타입명 기록이 갈라진다
  ⑤ `fetch(` 지점 허용표(셸 계약 ⑤의 판정 함수)에 변별력이 있다 — 허용표 밖 위반을 주입하면 검출된다

**정직한 공백**: 렌더 결과(버튼 노출·409 흐름·0건/실패 구분)는 정적 검사로 못 본다. 그 축은 헤드리스
브라우저 검증(가짜 BFF)이 소유하며, 이 파일이 통과해도 화면이 *동작*한다는 증명은 아니다.
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
fetch_site_violations = _shell.fetch_site_violations  # type: ignore[attr-defined]
is_admin_only = _landing.is_admin_only  # type: ignore[attr-defined]
_repo_sources = _landing._repo_sources  # type: ignore[attr-defined]

_WEBAPP = Path(__file__).resolve().parents[2] / "src" / "web" / "webapp"
_REVIEW_DIR = _WEBAPP / "app" / "admin" / "review"
_API_REL = "app/admin/_lib/adminReviewApi.ts"
_MENU_API_REL = "app/admin/_lib/adminApi.ts"
# P3-12 CMS 클라이언트 — 토큰 부착(`Bearer`·`Authorization`)과 전이 호출 경로(`/transitions`)가 정당하게
# 있다. 다만 *검수 큐* 엔드포인트·XHR·sendBeacon은 여기에도 있으면 안 된다(아래 판정이 따로 본다).
_CMS_API_REL = "app/admin/_lib/adminCmsApi.ts"

_HTML_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dangerouslySetInnerHTML", re.compile(r"dangerouslySetInnerHTML")),
    ("innerHTML 대입·참조", re.compile(r"\.\s*(?:inner|outer)HTML\b")),
    ("insertAdjacentHTML", re.compile(r"insertAdjacentHTML")),
)

#: 요청을 만드는 표지. 이것들은 `adminReviewApi.ts` 밖에 있으면 안 된다.
_REQUEST_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Bearer 토큰 부착", re.compile(r"Bearer\s")),
    ("Authorization 헤더", re.compile(r"\bAuthorization\b")),
    ("검수 큐 엔드포인트", re.compile(r"review-queue")),
    ("전이 호출 경로", re.compile(r"/transitions")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("sendBeacon", re.compile(r"\bsendBeacon\b")),
)


#: CMS 클라이언트에도 있으면 안 되는 표지(이름) — 나머지는 CMS 클라이언트의 정당한 책임이다.
_CMS_FORBIDDEN_MARKERS = frozenset({"검수 큐 엔드포인트", "XMLHttpRequest", "sendBeacon"})


def request_leak_violations(sources: dict[str, str]) -> list[str]:
    """요청 표지가 `adminReviewApi.ts` 밖에 있으면 위반. 입력이 비면 위반."""
    if not sources or _API_REL not in sources:
        return ["스캔 대상이 0건이거나 adminReviewApi.ts가 없다 — 가드가 무력화됐다"]
    # 토큰 부착 표지는 메뉴 클라이언트(`adminApi.ts`)에도 정당하게 있다. 검수 큐 전용 표지만 한 곳 제한.
    clients = (_API_REL, _MENU_API_REL, _CMS_API_REL)
    outside = {rel: text for rel, text in sources.items() if rel not in clients}
    menu_side = {rel: text for rel, text in sources.items() if rel == _MENU_API_REL}
    cms_side = {rel: text for rel, text in sources.items() if rel == _CMS_API_REL}
    if not outside:
        return ["API 파일 밖 소스가 0건 — 가드가 무력화됐다"]
    violations = _scan(outside, _REQUEST_MARKERS)
    violations += _scan(menu_side, _REQUEST_MARKERS[2:]) if menu_side else []
    # CMS 클라이언트는 토큰 부착·전이 경로(앞 둘·넷째 제외)만 면제 — 검수 큐 엔드포인트·XHR·beacon은 막는다.
    cms_forbidden = tuple(m for m in _REQUEST_MARKERS if m[0] in _CMS_FORBIDDEN_MARKERS)
    violations += _scan(cms_side, cms_forbidden) if cms_side else []
    return violations


def public_import_violations(public: dict[str, str]) -> list[str]:
    """공개 소스가 검수 큐 모듈을 가리키는 import·경로를 갖고 있으면 위반."""
    if not public:
        return ["공개 소스가 0건 — 경로가 바뀌었거나 가드가 무력화됐다"]
    rx = re.compile(
        r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*)["'][^"']*(?:admin/review|ReviewQueue|adminReviewApi)"""
    )
    return [
        f"{rel}: 공개 소스가 검수 큐 코드를 import한다"
        for rel, text in sorted(public.items())
        if rx.search(text)
    ]


# ── ① 라우트 접미 ────────────────────────────────────────────────────────


def test_review_route_is_admin_suffixed() -> None:
    """① — 화면 라우트가 실재하고 `.admin.tsx`이며 접미 없는 변종이 없다."""
    assert (_REVIEW_DIR / "page.admin.tsx").is_file(), "검수 큐 화면(page.admin.tsx)이 없다"
    bare = [p.name for p in _REVIEW_DIR.iterdir() if p.is_file() and ".admin." not in p.name]
    assert not bare, f"app/admin/review/ 에 접미 없는 파일 — 공개 빌드에 실릴 수 있다: {bare}"


def test_review_modules_are_classified_admin_only() -> None:
    """① 양성 대조 — 새 파일이 전부 admin 전용으로 분류돼 검사 모수에 들어온다."""
    sources = _admin_sources()
    for rel in (
        "app/admin/review/page.admin.tsx",
        _API_REL,
        "app/admin/_components/ReviewQueue.tsx",
        "app/admin/_components/ReviewQueueList.tsx",
        "app/admin/_components/ReviewQueueDetail.tsx",
        "app/admin/_components/ReviewQueueNotice.tsx",
    ):
        assert rel in sources, f"admin 소스 모수에 없다: {rel}"


# ── ② 공개 소스에서 import 금지 ─────────────────────────────────────────


def test_public_sources_do_not_import_review_code() -> None:
    """② — 공개 소스(비-admin)가 검수 큐 코드를 import하지 않는다."""
    public = {rel: text for rel, text in _repo_sources().items() if not is_admin_only(rel)}
    assert public_import_violations(public) == []


# ── ③ 원문 HTML 주입 0건 ────────────────────────────────────────────────


def test_no_html_injection_in_admin_sources() -> None:
    """③ — admin 소스 전체에 HTML 주입 경로가 0건이다(문항 원문은 텍스트 노드로만)."""
    assert _scan(_admin_sources(), _HTML_INJECTION_PATTERNS) == []


# ── ④ 요청은 한 곳 ──────────────────────────────────────────────────────


def test_requests_live_only_in_the_review_client() -> None:
    """④ — 토큰·엔드포인트·전이 호출 표지가 `adminReviewApi.ts` 밖에 없다."""
    assert request_leak_violations(_admin_sources()) == []


def test_review_client_actually_holds_the_request_markers() -> None:
    """④ 양성 대조 — 금지만 보면 '아무도 호출하지 않는다'도 통과한다. 클라이언트에 실재해야 한다."""
    text = _admin_sources()[_API_REL]
    for name, rx in _REQUEST_MARKERS[:4]:
        assert rx.search(text), f"클라이언트에 {name}이(가) 없다 — 계약 ④가 공허하다"
    assert 'credentials: "omit"' in text and "AbortSignal.timeout" in text


# ── ⑤ 변별력 봉인 (결함 주입 + 양성 대조) ───────────────────────────────

_CLEAN = {
    _API_REL: 'await fetch(base + path, { headers: { Authorization: "Bearer " + t } });\n'
    '// "/v1/admin/review-queue/items"\n',
    "app/admin/_components/ReviewQueue.tsx": "export function ReviewQueue() { return <p>{text}</p>; }\n",
}


@pytest.mark.parametrize(
    "fixture",
    [
        "<div dangerouslySetInnerHTML={{ __html: q }} />",
        "node.innerHTML = question;",
        'el.insertAdjacentHTML("beforeend", x);',
    ],
)
def test_html_judge_detects_injected_violation(fixture: str) -> None:
    """⑤ — HTML 주입 판정이 표기 변형 전건을 검출한다."""
    assert _scan({"app/admin/_components/ReviewQueueDetail.tsx": fixture}, _HTML_INJECTION_PATTERNS)


@pytest.mark.parametrize(
    "fixture",
    [
        'headers: { Authorization: "Bearer " + token }',
        'const p = "/v1/admin/review-queue/items";',
        'url + "/transitions"',
        "new XMLHttpRequest()",
    ],
)
def test_request_judge_detects_leak_outside_the_client(fixture: str) -> None:
    """⑤ — 컴포넌트에 요청 표지가 새면 검출된다."""
    sources = dict(_CLEAN)
    sources["app/admin/_components/ReviewQueueDetail.tsx"] = fixture
    assert request_leak_violations(sources)


@pytest.mark.parametrize(
    "fixture",
    [
        'import { ReviewQueue } from "../admin/_components/ReviewQueue";',
        'import x from "@/app/admin/review/page.admin";',
        'const m = await import("../admin/_lib/adminReviewApi");',
    ],
)
def test_public_import_judge_detects_injected_violation(fixture: str) -> None:
    """⑤ — 공개 소스의 검수 큐 import가 검출된다."""
    assert public_import_violations({"app/(public)/page.tsx": fixture})


def test_fetch_judge_detects_fetch_outside_the_allowlist() -> None:
    """⑤ — 허용표 밖 파일의 `fetch(`와 허용 파일의 호출 증식·소실이 모두 검출된다."""
    ok = {
        "app/admin/_lib/adminApi.ts": "await fetch(a);",
        _API_REL: "await fetch(b);",
        _CMS_API_REL: "await fetch(cms);",
    }
    assert fetch_site_violations(ok) == []
    leaked = dict(ok, **{"app/admin/_components/ReviewQueueList.tsx": "await fetch(c);"})
    assert fetch_site_violations(leaked)
    doubled = dict(ok, **{_API_REL: "await fetch(b); await fetch(b2);"})
    assert fetch_site_violations(doubled)
    gone = dict(ok, **{_API_REL: "// 호출 없음"})
    assert fetch_site_violations(gone)
    # P3-12: CMS 클라이언트도 같은 규칙 — 호출 증식·소실이 모두 검출된다.
    assert fetch_site_violations(dict(ok, **{_CMS_API_REL: "await fetch(c); await fetch(d);"}))
    assert fetch_site_violations(dict(ok, **{_CMS_API_REL: "// 호출 없음"}))


def test_judges_pass_on_clean_input() -> None:
    """⑤ 양성 대조 — 정상 입력은 위반 0(무차별 실패가 아니다)."""
    assert _scan(_CLEAN, _HTML_INJECTION_PATTERNS) == []
    assert request_leak_violations(_CLEAN) == []
    assert (
        public_import_violations({"app/(public)/page.tsx": "export default function P(){}"}) == []
    )


def test_judges_report_empty_scan_as_violation() -> None:
    """⑤ — 스캔 0건은 통과가 아니라 위반이다."""
    assert _scan({}, _HTML_INJECTION_PATTERNS)
    assert request_leak_violations({})
    assert public_import_violations({})
    assert fetch_site_violations({})
