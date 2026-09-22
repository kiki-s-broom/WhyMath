"""백오피스 웹 셸(`src/web/webapp/app/admin`)의 경계 동결 — ADMIN-06.

왜 이 파일이 있는가
-------------------
이 셸의 가치 주장은 둘이고 둘 다 **사람의 기억으로는 지켜지지 않는다**:

  ⓐ "좌측 내비에 하드코딩 nav가 없다"(04 §2 원칙7) — 한 번 지키기는 쉽고 계속 지키기는
     어렵다. 급할 때 메뉴 한 줄을 프런트에 박는 것이 언제나 제일 빠른 길이기 때문이다.
  ⓑ "공개 산출물에 admin 코드 0"(web_strategy §2) — 단일 앱 + 빌드 타깃 분리라는 구조 위에
     서 있어서, 파일명 규약 하나만 어긋나도 조용히 무너진다(빌드는 여전히 exit 0이다).

그래서 규약을 관례가 아니라 **계약**으로 둔다. 이 파일은 `infra-contracts` 잡에서 항상
실행된다 — `webapp` 잡은 paths 필터로 skip될 수 있고 skip은 red도 green도 아니다.

검증 계약
---------
① 스캔 대상이 실재한다 — admin 소스가 0건이면 아래 전부가 공허하게 통과한다(스캔 0건=실패)
② 빌드 타깃 분리 선언 — `next.config.ts`가 타깃별 `pageExtensions`를 가르고, **공개 목록에
   admin 확장자가 없다**
③ 파일명 규약 — `app/admin/**`의 라우트 파일은 전부 `.admin.*` 접미를 쓰고, admin 타깃의
   루트 레이아웃(`app/layout.admin.tsx`)이 실재한다. 접미가 떨어지면 공개 빌드에 `/admin`이
   실린다(2026-09-22 주입 실측: `out/admin/` 생성 + 번들 표식 2건)
④ 하드코딩 nav 0 — 레지스트리에서 파싱한 **섹션 키·모듈 id·모듈 라벨·모듈 라우트**가 admin
   소스에 리터럴로 등장하지 않는다
⑤ BFF 경유 + 1회 호출 — admin 소스의 API 경로 리터럴은 전부 `/v1/admin/`로 시작하고
   (04 §3 "프런트는 코어를 직접 호출하지 않는다"), `fetch(`는 정확히 1곳이다(원칙7 "1회 호출")
⑥ 자격증명 취급 — 탭을 넘어 남는 저장소·쿠키를 쓰지 않는다(04 §4·§5)
⑦ 번들 표식 ↔ CI 검사 문자열 일치 — 둘이 갈라지면 CI의 누출 검사가 **아무것도 안 보면서
   초록**이 된다
⑧ `live` 모듈은 실재 라우트를 가진다 — 레지스트리 상태와 파일 시스템의 드리프트 차단
⑨ 공개 노출 배포 설정 부재 (04 §5) — **검색 범위를 명시**한 부재 판정
⑩ 변별력 봉인 — ④⑤⑥⑧의 판정 함수에 위반을 주입하면 검출되고, 정상 입력은 통과한다

무엇을 검사하지 *않는가* (정직한 공백)
-------------------------------------
빌드 **산출물**은 여기서 못 본다(빌드를 돌려야 한다). 산출물 축 — 공개 `out/`에 `/admin`
경로와 번들 표식이 0건인지, admin `out/`에 셸과 표식이 실재하는지 — 은 CI `webapp` 잡의
검사 스텝이 exit code로 판정한다. 그 두 검사는 **서로 다른 누출을 잡는다**: 접미 규약이
깨지면 경로 검사가, 공개 클라이언트 소스가 admin을 import하면 표식 검사만 잡는다(후자는
`out/admin/`이 끝까지 안 생긴다). 역방향 import의 *소스* 축은
`test_webapp_landing_governance.py` 계약 ④가 본다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


def _load_boundary_rule() -> object:
    """공개/admin 경계 판정을 랜딩 거버넌스에서 **빌려 온다**(복사하지 않는다).

    같은 규약을 두 파일에 적으면 그 순간 둘이 드리프트하고, 그것은 이 파일이 막으려는 결함과
    정확히 같은 형태다. 평범한 import가 아니라 경로 로딩인 이유는 `tests/infra/`가 패키지가
    아니어서 테스트 모듈끼리 이름으로 import되지 않기 때문이다(실측: ModuleNotFoundError).
    """
    path = Path(__file__).with_name("test_webapp_landing_governance.py")
    spec = importlib.util.spec_from_file_location("_webapp_landing_governance", path)
    assert spec is not None and spec.loader is not None, f"경계 규약 모듈을 못 읽었다: {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


is_admin_only = _load_boundary_rule().is_admin_only  # type: ignore[attr-defined]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEBAPP = _REPO_ROOT / "src" / "web" / "webapp"
_ADMIN_DIR = _WEBAPP / "app" / "admin"
_REGISTRY = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "api" / "admin_module_registry.py"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_EXCLUDED_DIRS = frozenset({"node_modules", ".next", "out", "coverage"})

#: Next가 라우트로 인식하는 파일 이름(확장자 제외). 이 이름들이 `app/admin/` 아래에서
#: 접미 없이 나타나면 공개 빌드에 실린다.
_ROUTE_BASENAMES = frozenset(
    {
        "page",
        "layout",
        "route",
        "template",
        "default",
        "loading",
        "error",
        "not-found",
        "robots",
        "sitemap",
    }
)


# ── 스캔 모수 ────────────────────────────────────────────────────────────


def _admin_sources() -> dict[str, str]:
    """`{웹앱 상대경로: 내용}` — admin 타깃 전용 소스만."""
    found: dict[str, str] = {}
    for path in sorted(_WEBAPP.rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(_WEBAPP)
        if _EXCLUDED_DIRS & set(rel.parts[:-1]):
            continue
        key = str(rel)
        if is_admin_only(key):
            found[key] = path.read_text(encoding="utf-8")
    return found


def _scan(sources: dict[str, str], patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    """위반 문자열 목록. **입력이 비면 위반으로 보고한다**(경로가 바뀌면 위장이 된다)."""
    if not sources:
        return ["스캔 대상이 0건 — admin 소스 경로가 바뀌었거나 가드가 무력화됐다"]
    violations: list[str] = []
    for rel, text in sorted(sources.items()):
        for name, rx in patterns:
            match = rx.search(text)
            if match:
                violations.append(f"{rel}: {name} — {match.group(0)!r}")
    return violations


# ── 레지스트리 파싱 (백엔드를 import하지 않는다 — infra-contracts 잡은 백엔드 의존성이 없다) ──


def _registry_text() -> str:
    return _REGISTRY.read_text(encoding="utf-8")


def parse_section_keys(text: str) -> list[str]:
    """`AdminSection` enum의 값 목록."""
    body = re.search(r"class AdminSection\(str, Enum\):(.*?)\nSECTION_ORDER", text, re.S)
    if body is None:
        return []
    return re.findall(r'^\s+[A-Z_]+ = "([a-z_]+)"', body.group(1), re.M)


def parse_section_labels(text: str) -> list[str]:
    """`SECTION_LABELS_KO`의 라벨 목록."""
    return re.findall(r'AdminSection\.[A-Z_]+:\s*"([^"]+)"', text)


def parse_modules(text: str) -> list[dict[str, str]]:
    """`_MODULE_REGISTRY` 엔트리 목록 — id·section·label·route·status."""
    aliases = dict(re.findall(r"^(_[A-Z]+) = AdminModuleStatus\.([A-Z]+)", text, re.M))
    split = text.split("_MODULE_REGISTRY: tuple[AdminModule, ...] = (", 1)
    if len(split) != 2:
        return []
    entries = re.findall(
        r'_module\(\s*"([a-z0-9_]+)",\s*AdminSection\.([A-Z_]+),\s*"([^"]+)",\s*"([^"]+)",'
        r"\s*(_[A-Z]+|AdminModuleStatus\.[A-Z]+)",
        split[1],
    )
    modules: list[dict[str, str]] = []
    for module_id, section, label, route, raw_status in entries:
        status = aliases.get(raw_status, raw_status.rsplit(".", 1)[-1]).lower()
        modules.append(
            {
                "id": module_id,
                "section": section,
                "label": label,
                "route": route,
                "status": status,
            }
        )
    return modules


# ── 판정 함수 (변별력 봉인을 위해 순수 함수로 분리) ──────────────────────


def hardcoded_nav_violations(sources: dict[str, str], text: str) -> list[str]:
    """레지스트리 식별자가 admin 소스에 리터럴로 박혀 있으면 그것이 하드코딩 nav다.

    **정확 일치 문자열 리터럴**로만 판정한다(부분 일치 금지). 섹션 라벨 "설정"을 부분
    일치로 찾으면 "설정을 푼 뒤" 같은 산문이 걸려 가드가 꺼진다 — 오탐으로 죽은 가드는
    없는 가드다. 대신 라우트는 `"/admin/<무언가>"` 로 시작하는 리터럴을 본다(셸 자신의
    `/admin`과 BFF 경로 `/v1/admin/menu`는 걸리지 않는다).
    """
    modules = parse_modules(text)
    keys = parse_section_keys(text)
    if not modules or not keys:
        return ["레지스트리 파싱 0건 — 판정 모수가 없다(가드 무효)"]

    exact = [("섹션 키", key) for key in keys]
    exact += [("섹션 라벨", label) for label in parse_section_labels(text)]
    exact += [("모듈 id", module["id"]) for module in modules]
    exact += [("모듈 라벨", module["label"]) for module in modules]

    patterns: list[tuple[str, re.Pattern[str]]] = [
        (f"{kind} 리터럴 {value!r}", re.compile("[\"']" + re.escape(value) + "[\"']"))
        for kind, value in exact
    ]
    patterns.append(("모듈 라우트 리터럴", re.compile(r"""["']/admin/[A-Za-z0-9_-]""")))
    return _scan(sources, tuple(patterns))


def bff_path_violations(sources: dict[str, str]) -> list[str]:
    """admin 소스의 `/v1/...` 리터럴이 전부 `/v1/admin/`로 시작하는가 (04 §3)."""
    if not sources:
        return ["스캔 대상이 0건 — admin 소스 경로가 바뀌었거나 가드가 무력화됐다"]
    violations: list[str] = []
    for rel, text in sorted(sources.items()):
        for literal in re.findall(r"""["'](/v1/[^"']*)["']""", text):
            if not literal.startswith("/v1/admin/"):
                violations.append(f"{rel}: BFF 밖 코어 직접 호출 — {literal!r}")
    return violations


_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("탭을 넘어 남는 저장소", re.compile(r"\blocalStorage\b")),
    ("쿠키 저장", re.compile(r"\bdocument\s*\.\s*cookie\b")),
    ("URL에 토큰 노출", re.compile(r"[?&](?:token|access_token)=")),
)


def missing_live_routes(modules: list[dict[str, str]], admin_dir: Path) -> list[str]:
    """`live`로 선언된 모듈의 route에 해당하는 페이지 파일이 실재하는가.

    `live`의 정의가 "데이터+UI 모두 실동작"이므로, 화면이 없는데 `live`면 내비가 깨진 링크를
    만든다(셸은 `live`만 누를 수 있게 한다). 2026-09-22 현재 `live`는 0건이라 이 검사는
    **공허하게 통과한다** — 그래서 아래 `test_live_route_judge_detects_injected_violation`이
    가짜 `live` 모듈을 주입해 판정 함수가 실제로 무엇을 보는지 증명한다.
    """
    violations: list[str] = []
    for module in modules:
        if module["status"] != "live":
            continue
        route = module["route"]
        if not route.startswith("/admin"):
            violations.append(f"{module['id']}: route가 /admin 밖이다 — {route!r}")
            continue
        rest = route[len("/admin") :].strip("/")
        page_dir = admin_dir if not rest else admin_dir.joinpath(*rest.split("/"))
        if not (page_dir / "page.admin.tsx").is_file():
            violations.append(
                f"{module['id']}: status=live 인데 화면이 없다 — {route!r} "
                f"→ {page_dir / 'page.admin.tsx'} 부재"
            )
    return violations


# ── 계약 ① 스캔 실재 ────────────────────────────────────────────────────


def test_admin_sources_exist() -> None:
    """계약 ① — admin 소스가 실재한다. 0건이면 아래 전 계약이 공허하게 통과한다."""
    sources = _admin_sources()
    assert len(sources) >= 6, f"admin 소스가 {len(sources)}건뿐 — 경로가 바뀌었는지 확인하라"
    for required in (
        "app/layout.admin.tsx",
        "app/admin/layout.admin.tsx",
        "app/admin/page.admin.tsx",
        "app/admin/_components/AdminShell.tsx",
        "app/admin/_components/AdminNav.tsx",
        "app/admin/_lib/adminApi.ts",
    ):
        assert required in sources, f"셸 구성 파일을 못 찾았다: {required}"


def test_registry_parse_is_not_empty() -> None:
    """계약 ①(레지스트리 축) — 파싱 모수가 실재한다.

    파싱이 0건이면 계약 ④⑧이 "위반 0"으로 조용히 통과한다 — 레지스트리의 표기가 바뀌면
    (예: `_module(...)` 헬퍼를 안 쓰게 되면) 여기서 먼저 red가 나야 한다.
    """
    text = _registry_text()
    modules = parse_modules(text)
    assert len(modules) >= 20, f"모듈 파싱 {len(modules)}건 — 레지스트리 표기가 바뀌었다"
    assert len(parse_section_keys(text)) >= 6
    assert len(parse_section_labels(text)) >= 6
    assert {module["status"] for module in modules} <= {"live", "partial", "planned"}


# ── 계약 ② 빌드 타깃 분리 ───────────────────────────────────────────────


def test_build_targets_are_split_by_page_extensions() -> None:
    """계약 ② — 공개 타깃의 `pageExtensions`에 admin 확장자가 없다.

    이것이 "공개 산출물에 admin 0"의 **집행 지점**이다(web_strategy §2). 공개 목록에
    `admin.tsx`가 들어가는 순간 `app/admin/**`가 공개 빌드의 라우트가 된다.
    """
    config = (_WEBAPP / "next.config.ts").read_text(encoding="utf-8")
    match = re.search(r"pageExtensions:\s*([^\n]+)", config)
    assert match is not None, "next.config.ts에 pageExtensions 분기가 없다 — 타깃 분리가 사라졌다"
    line = match.group(1)
    assert "WHYMATH_WEB_TARGET" in config, "빌드 타깃 환경변수 분기가 없다"
    admin_part, _, public_part = line.partition(":")
    assert '"admin.tsx"' in admin_part, f"admin 타깃 목록에 admin 확장자가 없다: {line}"
    assert "admin" not in public_part, f"공개 타깃 목록에 admin 확장자가 있다: {line}"


# ── 계약 ③ 파일명 규약 ──────────────────────────────────────────────────


def test_admin_route_files_carry_the_admin_suffix() -> None:
    """계약 ③ — `app/admin/**`에 접미 없는 라우트 파일이 0건이다.

    접미가 떨어지면 그 파일은 **공개 타깃의 라우트가 된다**. 2026-09-22 주입 실측:
    `page.admin.tsx`·`layout.admin.tsx`의 접미를 떼자 공개 빌드가 `out/admin/`을 만들었고
    번들 표식도 2건 나왔다 — 그때도 `next build`는 exit 0이었다.
    """
    assert _ADMIN_DIR.is_dir(), "app/admin/이 없다 — 셸이 사라졌거나 경로가 바뀌었다"
    offenders = [
        str(path.relative_to(_WEBAPP))
        for path in sorted(_ADMIN_DIR.rglob("*"))
        if path.is_file()
        and path.suffix in _SOURCE_SUFFIXES
        and path.name.split(".")[0] in _ROUTE_BASENAMES
        and ".admin." not in path.name
    ]
    assert not offenders, f"접미 없는 라우트 파일 — 공개 빌드에 실린다: {offenders}"


def test_admin_target_root_layout_exists() -> None:
    """계약 ③ — admin 타깃의 루트 레이아웃이 실재한다(없으면 admin 빌드가 아예 안 선다)."""
    assert (_WEBAPP / "app" / "layout.admin.tsx").is_file()


# ── 계약 ④ 하드코딩 nav 0 ───────────────────────────────────────────────


def test_no_hardcoded_nav_in_admin_sources() -> None:
    """계약 ④ — 내비의 항목·순서·라벨이 프런트에 없다(04 §2 원칙7).

    "모든 가능 메뉴 자동 등록"의 실체는 발견 로직이 아니라 *중복 유지보수의 제거*다. 레지스트리
    식별자가 프런트에 한 글자라도 박히면 그 순간 유지보수 지점이 둘이 된다.
    """
    assert hardcoded_nav_violations(_admin_sources(), _registry_text()) == []


# ── 계약 ⑤ BFF 경유·1회 호출 ────────────────────────────────────────────


def test_admin_calls_only_the_bff() -> None:
    """계약 ⑤ — 프런트는 코어를 직접 호출하지 않는다(04 §3 — 인증·마스킹·감사 관문 우회 금지)."""
    assert bff_path_violations(_admin_sources()) == []


def test_menu_is_fetched_exactly_once() -> None:
    """계약 ⑤ — `fetch(` 호출 지점이 정확히 1곳이다(원칙7 "앱 로드 시 1회 호출").

    호출 지점이 흩어지면 화면마다 다른 메뉴를 들고 다니게 되고, 그것이 곧 내비의 두 번째
    진실 원천이다. 셸은 한 곳(`adminApi.fetchAdminMenu`)에서만 백엔드와 말한다.
    """
    sources = _admin_sources()
    assert sources, "스캔 0건"
    total = sum(len(re.findall(r"(?<![\w.])fetch\s*\(", text)) for text in sources.values())
    assert total == 1, f"admin 소스의 fetch( 호출이 {total}곳 — 1곳이어야 한다"


# ── 계약 ⑥ 자격증명 취급 ────────────────────────────────────────────────


def test_operator_token_is_not_persisted_beyond_the_tab() -> None:
    """계약 ⑥ — 탭을 넘어 남는 저장소·쿠키·URL에 토큰을 두지 않는다(04 §4·§5).

    내부망 한정은 *네트워크* 경계이지 *단말* 경계가 아니다 — 공용 운영 PC에서 다음 사람이
    이어 받는 상태를 막는 것은 저장소 선택뿐이다.
    """
    assert _scan(_admin_sources(), _CREDENTIAL_PATTERNS) == []


def test_session_storage_is_actually_used() -> None:
    """계약 ⑥ 양성 대조 — 금지만 확인하면 '아무 저장소도 안 쓴다'도 통과한다."""
    session = _admin_sources().get("app/admin/_lib/adminSession.ts", "")
    assert "sessionStorage" in session, "탭 수명 저장소를 쓰지 않는다 — 계약 ⑥이 공허하다"


# ── 계약 ⑦ 표식 ↔ CI 일치 ───────────────────────────────────────────────


def test_bundle_marker_matches_the_ci_leak_check() -> None:
    """계약 ⑦ — 표식 상수와 CI 검사 문자열이 같은 값이다.

    갈라지면 CI의 `grep`이 **아무것도 안 보면서 0건 통과**를 낸다 — 모든 입력에서 초록인
    가드와 같은 화면이다. CI는 이 표식을 두 번 쓴다: 공개 산출물에서 0건(누출 검사),
    admin 산출물에서 1건 이상(그 검사의 변별력 대조군).
    """
    marker_src = (_ADMIN_DIR / "_lib" / "marker.ts").read_text(encoding="utf-8")
    match = re.search(r'ADMIN_BUNDLE_MARKER\s*=\s*"([^"]+)"', marker_src)
    assert match is not None, "표식 상수를 못 찾았다"
    marker = match.group(1)

    shell = (_ADMIN_DIR / "_components" / "AdminShell.tsx").read_text(encoding="utf-8")
    assert "ADMIN_BUNDLE_MARKER" in shell, "셸이 표식을 렌더에 싣지 않는다 — 번들에 안 남는다"

    ci = _CI.read_text(encoding="utf-8")
    assert ci.count(marker) >= 2, (
        f"CI가 표식 {marker!r}을(를) {ci.count(marker)}번만 쓴다 — 누출 검사와 그 대조군 둘 다 "
        "있어야 한다"
    )


# ── 계약 ⑧ live ↔ 라우트 정합 ───────────────────────────────────────────


def test_live_modules_have_real_routes() -> None:
    """계약 ⑧ — `live` 선언과 실재 화면이 어긋나지 않는다.

    현재 `live`는 0건이라 이 테스트 자체는 공허하다 — 그 공허함을 아래 주입 테스트가 메운다.
    """
    assert missing_live_routes(parse_modules(_registry_text()), _ADMIN_DIR) == []


def test_shell_root_page_exists_for_the_admin_route() -> None:
    """계약 ⑧(비공허 축) — 셸 루트 화면은 지금 실재한다."""
    assert (_ADMIN_DIR / "page.admin.tsx").is_file()


# ── 계약 ⑨ 공개 노출 배포 설정 부재 ─────────────────────────────────────


def test_no_public_hosting_config_for_the_admin_build() -> None:
    """계약 ⑨ — admin 산출물을 공개 호스팅에 올리는 **선언**이 저장소에 없다(04 §5).

    **검색 범위(부재 판정이므로 명시한다)**: ⓐ `src/web/webapp/` 최상위의 관리형 정적 호스팅
    설정 파일 4종 ⓑ `.github/workflows/ci.yml`의 `webapp` 잡 안의 업로드·배포 액션.
    이 범위 **밖은 보지 않는다** — 실제 배포 여부는 저장소가 아니라 Kiki의 인프라 결정이고,
    그 축은 04 §5(내부망 한정)와 WEB-02(랜딩 배포 확정)가 소유한다. 즉 이 검사가 통과해도
    "공개되지 않았다"가 증명되는 것이 아니라 "이 저장소가 공개를 선언하지 않았다"가 확인된다.

    WEB-02가 *랜딩* 배포를 붙일 때 이 테스트는 red가 될 수 있다 — 그때 사람이 "랜딩 산출물만
    올리고 admin 산출물은 올리지 않는다"를 읽고 판정해 이 계약을 좁혀야 한다(postcss override
    테스트와 같은, 고의로 사람을 부르는 자리다).
    """
    hosting = [
        name
        for name in ("vercel.json", "netlify.toml", "firebase.json", "now.json")
        if (_WEBAPP / name).exists()
    ]
    assert not hosting, f"관리형 공개 호스팅 설정이 있다: {hosting} — 04 §5 내부망 한정과 충돌"

    ci = _CI.read_text(encoding="utf-8")
    job = ci.split("\n  webapp:\n", 1)
    assert len(job) == 2, "ci.yml에서 webapp 잡을 못 찾았다 — 검사 모수가 없다"
    body = job[1].split("\n  infra-contracts:", 1)[0]
    deploy = [
        token
        for token in (
            "actions/deploy-pages",
            "actions/upload-pages-artifact",
            "peaceiris/actions-gh-pages",
            "amondnet/vercel-action",
            "nwtgck/actions-netlify",
        )
        if token in body
    ]
    assert not deploy, f"webapp 잡에 배포 액션이 있다: {deploy} — admin 산출물 공개 노출 경로"


# ── 계약 ⑩ 변별력 봉인 (결함 주입 + 양성 대조) ──────────────────────────
#
# 아래 픽스처는 각 판정 절의 **반례**다 — 그 절이 없으면 통과해 버리는 문자열을 하나씩 든다.

_CLEAN_ADMIN = {
    "app/admin/_components/AdminNav.tsx": (
        "export function AdminNav({ sections }) {\n"
        "  return sections.map((s) => <li key={s.key}>{s.label_ko}</li>);\n"
        "}\n"
    )
}

_NAV_FIXTURES = (
    # 섹션 키를 프런트가 들고 있는 형태(순서 배열의 전형)
    'const ORDER = ["review", "dashboard"];',
    # 모듈 id
    'if (item.id === "review_queue") return null;',
    # 섹션 라벨
    'const title = "검수 큐";',
    # 모듈 라벨
    'const label = "KPI 대시보드";',
    # 모듈 라우트
    'href="/admin/content/concepts"',
)

_BFF_FIXTURES = (
    'await fetch(base + "/v1/problems");',
    'const url = "/v1/concepts/atoms";',
)

_CREDENTIAL_FIXTURES = (
    'localStorage.setItem("wm.admin.operator_token", token);',
    "document.cookie = `t=${token}`;",
    'const u = "/admin?token=abc";',
)


@pytest.mark.parametrize("fixture", _NAV_FIXTURES)
def test_nav_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑩ — 하드코딩 nav 축: 주입한 위반이 전건 검출된다."""
    sources = {"app/admin/_components/AdminNav.tsx": fixture}
    assert hardcoded_nav_violations(sources, _registry_text()), fixture


@pytest.mark.parametrize("fixture", _BFF_FIXTURES)
def test_bff_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑩ — BFF 경유 축: 코어 직접 호출이 검출된다."""
    assert bff_path_violations({"app/admin/_lib/adminApi.ts": fixture}), fixture


@pytest.mark.parametrize("fixture", _CREDENTIAL_FIXTURES)
def test_credential_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑩ — 자격증명 축: 영속 저장·쿠키·URL 노출이 검출된다."""
    assert _scan({"app/admin/_lib/adminSession.ts": fixture}, _CREDENTIAL_PATTERNS), fixture


def test_live_route_judge_detects_injected_violation() -> None:
    """계약 ⑩ — `live` 축: 화면 없는 `live` 모듈을 주입하면 검출된다.

    현재 레지스트리의 `live`가 0건이라 본 테스트가 공허하므로, **이 주입이 그 공허함을
    메우는 자리**다(전건 통과를 커버리지로 읽지 않는다).
    """
    fake = [
        {
            "id": "ghost",
            "section": "REVIEW",
            "label": "유령",
            "route": "/admin/ghost",
            "status": "live",
        },
    ]
    assert missing_live_routes(fake, _ADMIN_DIR)


def test_live_route_judge_passes_when_the_page_exists() -> None:
    """계약 ⑩ 양성 대조 — 화면이 실재하는 `live` 모듈은 통과한다(무차별 실패가 아니다)."""
    real = [
        {"id": "shell", "section": "DASHBOARD", "label": "셸", "route": "/admin", "status": "live"},
    ]
    assert missing_live_routes(real, _ADMIN_DIR) == []


@pytest.mark.parametrize(
    "judge",
    [
        lambda sources: hardcoded_nav_violations(sources, _registry_text()),
        bff_path_violations,
        lambda sources: _scan(sources, _CREDENTIAL_PATTERNS),
    ],
    ids=["nav", "bff", "credential"],
)
def test_judges_pass_on_clean_input(judge: object) -> None:
    """계약 ⑩ 양성 대조 — 정상 입력에서는 위반 0."""
    assert judge(_CLEAN_ADMIN) == []  # type: ignore[operator]


@pytest.mark.parametrize(
    "judge",
    [
        lambda sources: hardcoded_nav_violations(sources, _registry_text()),
        bff_path_violations,
        lambda sources: _scan(sources, _CREDENTIAL_PATTERNS),
    ],
    ids=["nav", "bff", "credential"],
)
def test_judges_report_empty_scan_as_violation(judge: object) -> None:
    """계약 ⑩ — 스캔 0건은 통과가 아니라 위반이다(가드 무력화 차단)."""
    assert judge({})  # type: ignore[operator]
