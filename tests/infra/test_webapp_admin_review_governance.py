"""검수 큐 웹 화면(`app/admin/review`)의 경계 동결 — ADMIN-07.

`test_webapp_admin_shell_governance.py`가 셸 전체(빌드 타깃 분리·하드코딩 nav·BFF 경유·자격증명)를
동결한다면, 이 파일은 **검수 큐 화면이 새로 만든 표면**의 규칙을 동결한다:

  ① 화면 라우트는 `.admin.tsx` 접미 — 접미가 떨어지면 공개 빌드에 `/admin/review`가 실린다
  ② 공개 소스가 검수 큐 코드를 import하지 않는다(역방향 누출 — 공개 번들에 admin 코드가 들어간다)
  ③ 원문 HTML 주입 경로 0건 — 문항 본문·해설은 저작물 원문이라 `dangerouslySetInnerHTML`·`innerHTML`로
     그리면 저장형 XSS 표면이 된다(텍스트 노드로만 렌더)
  ④ 토큰 부착·검수 큐 엔드포인트·전이 호출은 `adminReviewApi.ts` 한 곳 — 화면 컴포넌트가 직접
     요청을 만들면 타임아웃·`credentials:"omit"`·예외 타입명 기록이 갈라진다
  ⑥ (ADMIN-18) 착수 세션 URL(`review-sessions`)은 클라이언트 모듈에만 — 컴포넌트가 직접 세션을 만들면
     "판정은 세션과 함께"라는 불변이 화면마다 갈라진다
  ⑦ (ADMIN-18) 판정 본문 빌더(`buildTransitionBody`)가 `review_session_id`를 싣고, 세션 없는 승인·반려는
     본문을 만들지 않으며, 클라가 경과 시간(elapsed)을 보내지 않는다
  ⑧ (ADMIN-18) 반려코드 8종 클라 상수 == 서버 `GenerationFailureCode` 값집합(스캔 0건은 실패)
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
    # 인덱스 [:4]·[2:] 슬라이스 계약을 깨지 않도록 반드시 맨 끝에 둔다.
    ("착수 세션 경로", re.compile(r"review-sessions")),
)


def request_leak_violations(sources: dict[str, str]) -> list[str]:
    """요청 표지가 `adminReviewApi.ts` 밖에 있으면 위반. 입력이 비면 위반."""
    if not sources or _API_REL not in sources:
        return ["스캔 대상이 0건이거나 adminReviewApi.ts가 없다 — 가드가 무력화됐다"]
    # 토큰 부착 표지는 메뉴 클라이언트(`adminApi.ts`)에도 정당하게 있다. 검수 큐 전용 표지만 한 곳 제한.
    outside = {rel: text for rel, text in sources.items() if rel not in (_API_REL, _MENU_API_REL)}
    menu_side = {rel: text for rel, text in sources.items() if rel == _MENU_API_REL}
    if not outside:
        return ["API 파일 밖 소스가 0건 — 가드가 무력화됐다"]
    violations = _scan(outside, _REQUEST_MARKERS)
    violations += _scan(menu_side, _REQUEST_MARKERS[2:]) if menu_side else []
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
    }
    assert fetch_site_violations(ok) == []
    leaked = dict(ok, **{"app/admin/_components/ReviewQueueList.tsx": "await fetch(c);"})
    assert fetch_site_violations(leaked)
    doubled = dict(ok, **{_API_REL: "await fetch(b); await fetch(b2);"})
    assert fetch_site_violations(doubled)
    gone = dict(ok, **{_API_REL: "// 호출 없음"})
    assert fetch_site_violations(gone)


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


# ── ⑥ 착수 세션 URL은 클라이언트에만 (ADMIN-18) ─────────────────────────


def test_session_endpoint_lives_only_in_the_review_client() -> None:
    """⑥ — `review-sessions` 리터럴이 `adminReviewApi.ts` 밖 admin 소스에 없다."""
    sources = _admin_sources()
    outside = {rel: text for rel, text in sources.items() if rel != _API_REL}
    assert outside, "API 파일 밖 소스가 0건 — 가드가 무력화됐다"
    assert [v for v in _scan(outside, _REQUEST_MARKERS[-1:])] == []


def test_review_client_holds_the_session_endpoint() -> None:
    """⑥ 양성 대조 — 금지만 보면 '세션을 아무도 안 만든다'도 통과한다."""
    text = _admin_sources()[_API_REL]
    assert _REQUEST_MARKERS[-1][1].search(text), "클라이언트에 착수 세션 경로가 없다"
    assert "createReviewSession" in text


# ── ⑦ 판정 본문 빌더 (ADMIN-18) ─────────────────────────────────────────


def _builder_body(text: str) -> str | None:
    """`buildTransitionBody` 함수 본문(중괄호 균형으로 잘라 낸다). 없으면 None."""
    m = re.search(r"export function buildTransitionBody\([^)]*\)[^{]*\{", text)
    if m is None:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.start() : i] if depth == 0 else None


def transition_builder_violations(text: str) -> list[str]:
    """전이 본문 빌더가 세션·반려코드 계약을 지키는가. 빌더가 없으면 위반(공허 통과 차단)."""
    body = _builder_body(text)
    if body is None:
        return ["buildTransitionBody 를 찾지 못했다 — 가드가 무력화됐다"]
    out: list[str] = []
    if not re.search(r"body\.review_session_id\s*=", body):
        out.append("판정 본문에 review_session_id 를 싣지 않는다")
    if not re.search(r"req\.sessionId\s*===\s*null\)\s*return null", body):
        out.append("세션 없는 승인·반려를 막는 early-return(null)이 없다")
    if not re.search(r'"approve"\s*,\s*"reject"', text):
        out.append("세션 필수 액션 표(approve·reject)가 없다")
    if not re.search(r"body\.failure_code\s*=", body):
        out.append("반려 본문에 failure_code 를 싣지 않는다")
    if not re.search(
        r'if \(req\.action === "reject" && req\.failureCode !== null\) body\.failure_code', body
    ):
        out.append("failure_code 가 반려 한정으로 실리지 않는다(다른 액션에 보내면 서버 422)")
    if re.search(r"elapsed|duration|started_at|elapsed_ms|seconds", body, re.IGNORECASE):
        out.append("클라가 경과 시간 계열 필드를 싣는다 — 시간은 서버가 계산한다")
    return out


def test_transition_builder_carries_session_and_reject_code() -> None:
    """⑦ — 실제 클라이언트의 빌더가 계약을 지킨다."""
    assert transition_builder_violations(_admin_sources()[_API_REL]) == []


def test_submit_goes_through_the_builder() -> None:
    """⑦ — 전이 제출이 빌더를 경유한다(본문을 따로 조립하는 우회로가 없다)."""
    text = _admin_sources()[_API_REL]
    m = re.search(r"export async function submitReviewTransition\(.*?\n\}\n", text, re.DOTALL)
    assert m is not None, "submitReviewTransition 을 찾지 못했다"
    assert "buildTransitionBody(req)" in m.group(0)
    assert "expected_status" not in m.group(0), "제출 함수가 본문을 직접 조립한다"


_BUILDER_OK = """export function buildTransitionBody(req: R): Record<string, string> | null {
  if (SESSION_REQUIRED_ACTIONS.includes(req.action) && req.sessionId === null) return null;
  const body: Record<string, string> = { action: req.action, expected_status: req.expectedStatus };
  if (req.action === "reject" && req.failureCode !== null) body.failure_code = req.failureCode;
  if (req.sessionId !== null) body.review_session_id = req.sessionId;
  return body;
}
const SESSION_REQUIRED_ACTIONS = ["approve", "reject"];
"""


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("  if (req.sessionId !== null) body.review_session_id = req.sessionId;\n", ""),
        ("req.sessionId === null) return null;", "req.sessionId === undefined) return null;"),
        (
            'if (req.action === "reject" && req.failureCode !== null) body.failure_code',
            "if (req.failureCode !== null) body.failure_code",
        ),
        ("  return body;", "  body.elapsed_ms = Date.now() - t0;\n  return body;"),
    ],
)
def test_builder_judge_detects_injected_violation(old: str, new: str) -> None:
    """⑦ 변별력 — 세션 미탑재·null 가드 약화·failure_code 비한정·elapsed 전송을 각각 검출한다."""
    assert transition_builder_violations(_BUILDER_OK) == []
    assert old in _BUILDER_OK
    mutated = _BUILDER_OK.replace(old, new)
    assert mutated != _BUILDER_OK
    assert transition_builder_violations(mutated)


def test_builder_judge_reports_missing_builder() -> None:
    """⑦ — 빌더 부재·빈 입력은 통과가 아니라 위반이다."""
    assert transition_builder_violations("")
    assert transition_builder_violations("export const x = 1;")


# ── ⑧ 반려코드 클라 상수 == 서버 enum (ADMIN-18) ────────────────────────

_CODES_REL = "app/admin/_lib/reviewFailureCodes.ts"


def client_failure_codes(text: str) -> set[str]:
    """클라 상수 파일의 `code: "F#"` 리터럴 집합."""
    return set(re.findall(r'\bcode:\s*"(F\d+)"', text))


def failure_code_violations(client: set[str], server: set[str]) -> list[str]:
    """두 집합이 비었거나 다르면 위반."""
    if not client or not server:
        return ["스캔 0건 — 클라 상수 또는 서버 enum 을 못 읽었다(가드 무력화)"]
    out: list[str] = []
    if client - server:
        out.append(f"서버가 모르는 코드가 클라에 있다: {sorted(client - server)}")
    if server - client:
        out.append(f"서버 코드가 클라에 없다: {sorted(server - client)}")
    return out


def _server_codes() -> set[str]:
    from whymath_backend.schema.enums import GenerationFailureCode

    return {member.value for member in GenerationFailureCode}


def test_client_failure_codes_match_server_enum() -> None:
    """⑧ — 반려코드 8종이 서버 `GenerationFailureCode` 와 정확히 같다."""
    text = _admin_sources()[_CODES_REL]
    client = client_failure_codes(text)
    assert len(client) == 8, f"클라 반려코드가 8종이 아니다: {sorted(client)}"
    assert failure_code_violations(client, _server_codes()) == []


def test_failure_code_judge_detects_drift() -> None:
    """⑧ 변별력 — 코드 추가·누락·빈 스캔을 검출하고 일치 입력은 통과시킨다."""
    server = {f"F{i}" for i in range(1, 9)}
    assert failure_code_violations(set(server), server) == []
    assert failure_code_violations(server | {"F9"}, server)
    assert failure_code_violations(server - {"F8"}, server)
    assert failure_code_violations(set(), server)
    assert failure_code_violations(server, set())
