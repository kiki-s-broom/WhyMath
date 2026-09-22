"""공개 랜딩(`src/web/webapp`)의 경계 동결 — WEB-01.

왜 이 파일이 있는가
-------------------
랜딩은 슬라이스 89 ③ "별도 웹"의 첫 실체다. 학생 *학습 경험*이 아니라 유입·소개 표면이라는
전제 위에서만 그 좌석이 성립하므로, 그 전제를 **사람의 기억이 아니라 기계가** 지킨다.
`src/web/graphing-calculator/test/no_math_judgement_governance.test.js`(ARCH-10)의 웹앱 축이며,
그쪽이 web 잡(Vitest)에서 도는 것과 달리 이 파일은 **항상 실행되는** `infra-contracts` 잡에서
돈다 — 랜딩 CI 잡은 paths 필터로 skip될 수 있고, skip은 red도 green도 아니기 때문이다.

검증 계약 (변별력이 확인된 것만 — 각 축마다 결함 주입 테스트가 짝으로 있다)
--------------------------------------------------------------------
① 스캔 대상이 실재한다 — 경로가 바뀌면 "위반 0 통과"가 아니라 **실패**(스캔 0건은 실패)
② 수학 판정·채점 심볼 0건 (ARCH-10 — 정오 판정의 단일 권위는 백엔드 L3/SymPy)
③ 네트워크 호출 0건 (web_strategy §3.2 — v1 랜딩은 백엔드 호출 0·외부 폼 *링크*만)
④ 공개 소스가 `app/admin/`을 import하지 않는다 (web_strategy §2 배포 요건)
⑤ 효과 단정 카피 0건 (§3.4 카피 가드) — **보조 탐지기다**. 문자열 열거는 표현을 바꾸면
   빠져나가므로 최종 판정은 변호사 검토 게이트가 한다(법령 유래 절차의 기계 대체 금지).

**스캔 범위(ADMIN-06에서 갈렸다)**: ②는 웹앱 *전체*를 본다(표현≠의미는 백오피스도 예외가
아니다 — 04 §2 원칙1). ③④⑤는 **공개 빌드에 실릴 수 있는 소스만** 본다 — 백오피스 셸은
설계상 BFF를 호출하므로(04 §3) 같은 잣대를 대면 ③이 영구 red가 되고, 그러면 사람이 가드를
끄게 된다. 공개/admin의 경계는 파일명 규약이며(`app/admin/**`·`*.admin.tsx`) 그 규약 자체와
빌드 타깃 분리는 `test_webapp_admin_shell_governance.py`가 따로 동결한다.
⑥ 정적 export 선언이 살아 있다 (`output: "export"` — 정적 호스팅 전제 자체)
⑦ 빌드 산출물·의존성이 커밋 대상에서 제외돼 있다
⑦-b 스택 표 정합(Next 15 핀) + postcss 취약점 override 존치 — 둘 다 *의도*라 조용히
   사라지면 안 된다(핀은 CLAUDE.md 스택 표, override는 그 핀 때문에 필요한 우회다)
⑧ 판정 함수의 변별력 봉인 — ②③⑤ 각각에 위반을 주입하면 검출되고, 정상 입력은 통과한다
   (모든 입력에서 초록인 가드도 정상 입력에서는 같은 화면을 낸다)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEBAPP = _REPO_ROOT / "src" / "web" / "webapp"

_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
# rglob은 .gitignore를 모른다 — 의존성·빌드 산출물을 이름으로 자른다(로컬에서만 부푸는
# 스캔 모수를 없앤다. eos_feature_inventory_v2 `_EXCLUDED_CLIENT_DIRS`와 같은 이유).
_EXCLUDED_DIRS = frozenset({"node_modules", ".next", "out", "coverage"})


# ── 판정 대상 패턴 ──────────────────────────────────────────────────────
# 이름은 실패 메시지에 그대로 나온다 — 무엇이 왜 걸렸는지가 한 줄로 읽혀야 한다.

_MATH_JUDGEMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("채점 호출/정의 checkAnswer", re.compile(r"\bcheckAnswer\w*\s*[=(]")),
    ("채점 호출/정의 gradeAnswer", re.compile(r"\bgradeAnswer\w*\s*[=(]")),
    ("동치 판정 sameGraph/isEquivalent", re.compile(r"\b(?:sameGraph|isEquivalent)\w*\s*[=(]")),
    ("오개념 진단 diagnose", re.compile(r"\bdiagnose\w*\s*[=(]")),
    ("수식 평가 라이브러리 mathjs", re.compile(r"""["']mathjs["']""")),
    ("수식 평가 호출 evaluate(", re.compile(r"\bevaluate\s*\(")),
)

_NETWORK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fetch 호출", re.compile(r"(?<![\w.])fetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("axios", re.compile(r"\baxios\b")),
    ("sendBeacon", re.compile(r"\bsendBeacon\s*\(")),
    ("WebSocket", re.compile(r"\bnew\s+WebSocket\s*\(")),
    ("EventSource", re.compile(r"\bnew\s+EventSource\s*\(")),
)

# 효과 단정·최상급 단정 — regulatory_checklist §4.1 / web_strategy §3.4 카피 가드.
# 각 패턴마다 아래 `_COPY_FIXTURES`에 **그 절을 실제로 밟는 반례**가 하나씩 있다.
_COPY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 한국어 활용형은 어간만으로 안 잡힌다("오르다"→"오릅니다"). 흔한 활용을 나열하되,
    # 열거가 완전하지 않다는 사실 자체가 이 축을 *보조 탐지기*로 두는 이유다.
    (
        "성적·점수 상승 단정",
        re.compile(
            r"(성적|점수|등급|실력)[이가은는을를]?\s*(오르|오릅|오를|올라|올랐|올려|올리|상승|향상)"
        ),
    ),
    ("등급 보장", re.compile(r"[1일]\s*등급\s*(보장|달성)")),
    ("결과 보장", re.compile(r"보장(합니다|해\s*드|됩니다)")),
    ("최초·최고·1위 단정", re.compile(r"(국내|업계|세계)\s*(최초|최고|최대|1위|유일)")),
    ("최상급 비교 단정", re.compile(r"가장\s*(뛰어난|정확한|빠른|효과적|좋은)")),
    ("압도적 우위 단정", re.compile(r"압도적")),
    ("효과 입증 단정", re.compile(r"효과가?\s*(입증|검증)")),
)


def _source_files() -> list[Path]:
    """웹앱의 *추적 대상* 소스만 — 의존성·빌드 산출물 제외(결정론)."""
    return sorted(
        p
        for p in _WEBAPP.rglob("*")
        if p.is_file()
        and p.suffix in _SOURCE_SUFFIXES
        and not (_EXCLUDED_DIRS & set(p.relative_to(_WEBAPP).parts[:-1]))
    )


def _scan(
    sources: dict[str, str],
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[str]:
    """`{상대경로: 내용}` → 위반 문자열 목록. 입력이 비면 **위반으로 보고**한다.

    빈 입력을 '위반 0'으로 돌려주면 경로가 바뀌는 순간 이 파일 전체가 위장이 된다.
    """
    if not sources:
        return ["스캔 대상이 0건 — 경로가 바뀌었거나 가드가 무력화됐다"]
    violations: list[str] = []
    for rel, text in sorted(sources.items()):
        for name, rx in patterns:
            m = rx.search(text)
            if m:
                violations.append(f"{rel}: {name} — {m.group(0)!r}")
    return violations


def _repo_sources() -> dict[str, str]:
    return {str(p.relative_to(_WEBAPP)): p.read_text(encoding="utf-8") for p in _source_files()}


def is_admin_only(rel: str) -> bool:
    """`rel`이 **admin 타깃 전용** 소스인가 — 공개 빌드에 실릴 수 없는 파일인가.

    판정 근거는 두 가지 파일명 규약뿐이고, 그 규약이 지켜진다는 것 자체는 여기서 검사하지
    않는다(`test_webapp_admin_shell_governance.py` 소관). 그래서 이 함수는 *경계의 선언*이지
    *경계의 증명*이 아니다 — 증명은 빌드 산출물 검사(CI)와 저쪽 파일이 나눠 진다.
    """
    parts = rel.replace("\\", "/").split("/")
    if "admin" in parts[:-1] and parts[0] == "app":
        return True
    return ".admin." in parts[-1]


def _public_sources() -> dict[str, str]:
    """공개 빌드에 실릴 수 있는 소스만. 0건이면 `_scan`이 위반으로 보고한다."""
    return {rel: text for rel, text in _repo_sources().items() if not is_admin_only(rel)}


# ── 계약 ① 스캔 실재 ────────────────────────────────────────────────────


def test_webapp_sources_exist() -> None:
    """계약 ① — 스캔 모수가 실재한다. 0건이면 아래 전 계약이 공허하게 통과한다."""
    files = _source_files()
    assert len(files) >= 6, f"웹앱 소스가 {len(files)}건뿐 — 경로가 바뀌었는지 확인하라"
    rels = {str(p.relative_to(_WEBAPP)) for p in files}
    assert "app/(public)/page.tsx" in rels, f"랜딩 페이지를 못 찾았다: {sorted(rels)}"
    assert "app/layout.tsx" in rels


# ── 계약 ②③⑤ 본 검사 ───────────────────────────────────────────────────


def test_no_math_judgement_symbols() -> None:
    """계약 ② — 랜딩에 정오 판정·채점·동치 판정 로직이 들어오면 red (ARCH-10)."""
    assert _scan(_repo_sources(), _MATH_JUDGEMENT_PATTERNS) == []


def test_no_network_calls() -> None:
    """계약 ③ — v1 랜딩은 백엔드를 호출하지 않는다(외부 폼 *링크*만).

    범위는 공개 소스다. 백오피스 셸의 BFF 호출은 설계 그 자체이므로(04 §3) 여기서 세면
    이 가드는 영구 red가 되고, 영구 red인 가드는 꺼진다.
    """
    assert _scan(_public_sources(), _NETWORK_PATTERNS) == []


def test_no_effect_claim_copy() -> None:
    """계약 ⑤ — 효과·최상급 단정 카피 차단(보조 탐지기·최종 판정은 변호사 게이트).

    범위는 공개 소스다 — 이 축이 규율하는 것은 *광고 표현*이고, 내부망 운영 화면은 그
    수범 대상이 아니다.
    """
    assert _scan(_public_sources(), _COPY_PATTERNS) == []


# ── 계약 ④ admin 분리 ───────────────────────────────────────────────────


#: 공개 소스가 백오피스 트리로 들어가는 import. 상대·별칭 두 형태를 모두 본다.
_ADMIN_IMPORT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("상대 경로 admin import", re.compile(r"""from\s+["'][./]*(?:\.\./)*admin/""")),
    ("별칭 경로 admin import", re.compile(r"""from\s+["']@/app/admin/""")),
)


def test_public_sources_do_not_import_admin() -> None:
    """계약 ④ — 공개 소스가 `app/admin/`을 끌어다 쓰지 않는다 (web_strategy §2).

    **왜 '부재'가 아니라 '역방향 import'인가 (ADMIN-06에서 교체된 축)**: 원래 이 계약은
    `app/admin/` 디렉터리 자체의 부재였고, "ADMIN-06이 들여오는 순간 red가 되어 공개 빌드
    분리를 강제로 설계하게 한다"가 목적이었다. 그 설계가 실제로 착지했으므로(빌드 타깃
    분리 — `next.config.ts`의 `pageExtensions`) 계약은 *디렉터리 부재*에서 *누출 부재*로
    옮겨간다. 파일명 규약상 `app/admin/**`는 공개 빌드에서 라우트가 되지 않지만, 공개
    **클라이언트** 소스가 그 트리를 import하면 라우트 없이 번들에만 실린다 — 2026-09-22
    주입 실측: `app/(public)/page.tsx`가 `AdminShell`을 import하자 `out/admin/` 은
    끝까지 생기지 않은 채 번들 표식만 1건 나왔다. 즉 **경로 검사로는 안 보이는 누출**이고,
    이 정적 검사와 CI의 번들 표식 검사가 그 자리를 나눠 맡는다.
    """
    assert _scan(_public_sources(), _ADMIN_IMPORT_PATTERNS) == []


@pytest.mark.parametrize(
    "fixture",
    [
        'import { AdminShell } from "../admin/_components/AdminShell";',
        'import { ADMIN_BUNDLE_MARKER } from "./admin/_lib/marker";',
        'import x from "@/app/admin/_lib/adminApi";',
    ],
)
def test_admin_import_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑧(④ 축) — 주입한 역방향 import가 검출된다."""
    assert _scan({"app/(public)/page.tsx": fixture}, _ADMIN_IMPORT_PATTERNS), fixture


def test_admin_import_judge_passes_on_sibling_paths() -> None:
    """계약 ⑧ 양성 대조 — admin이 아닌 상대 import는 통과한다(무차별 실패가 아니다)."""
    clean = {"app/(public)/page.tsx": 'import { Hero } from "./_components/Hero";'}
    assert _scan(clean, _ADMIN_IMPORT_PATTERNS) == []


def test_admin_sources_are_excluded_from_public_scope() -> None:
    """공개/admin 경계 판정이 실제로 갈린다 — 이 함수가 상수 True/False면 위 스코프가 위장이다."""
    assert is_admin_only("app/admin/_lib/adminApi.ts")
    assert is_admin_only("app/layout.admin.tsx")
    assert not is_admin_only("app/layout.tsx")
    assert not is_admin_only("app/(public)/page.tsx")
    public = _public_sources()
    assert public, "공개 소스가 0건 — 경계 판정이 전부를 잘라냈다"
    assert not any(is_admin_only(rel) for rel in public)
    assert len(public) < len(_repo_sources()), "admin 소스가 하나도 안 걸러졌다 — 경계가 무효다"


# ── 계약 ⑥⑦ 설정 동결 ──────────────────────────────────────────────────


def test_static_export_is_declared() -> None:
    """계약 ⑥ — 정적 export 선언. 이게 빠지면 산출물이 서버 런타임을 요구하게 된다."""
    config = (_WEBAPP / "next.config.ts").read_text(encoding="utf-8")
    assert re.search(
        r'output:\s*"export"', config
    ), 'next.config.ts에 output: "export"가 없다 — 정적 호스팅 전제가 깨진다'


def test_stack_pin_and_postcss_override_are_intentional() -> None:
    """계약 ⑦-b — Next 15 핀과 postcss override가 둘 다 살아 있다.

    왜 둘을 한 테스트로 묶는가: **인과로 묶여 있기 때문**이다.
      · CLAUDE.md 스택 표가 "React 19 + Next.js 15"를 확정했다. 15에서 16으로 올리려면
        MEMORY 결정 로그가 선결이다(스택 변경 규약).
      · 그런데 Next 15.5.25는 `postcss`를 **정확히 8.4.31로 핀**하고, 그 버전은 4건의
        권고(<=8.5.22)에 걸린다. `npm audit fix`가 제시하는 유일한 경로는 Next 16이라
        스택 규약과 충돌한다. 그래서 `overrides`로 postcss만 8.5.28+로 올린다 —
        실측(2026-09-22): override 후 `npm audit` 0건 · lint·build·CSS 모듈 해시 정상.
      · 즉 override가 사라지면 고지 없이 취약 버전으로 돌아가고, Next 16으로 올라가면
        override가 불필요해진다. 어느 쪽이든 **사람이 판단해 이 테스트를 고쳐야 한다**.
    """
    pkg = json.loads((_WEBAPP / "package.json").read_text(encoding="utf-8"))
    next_pin = pkg["dependencies"]["next"]
    assert next_pin.startswith("15."), (
        f"next 핀이 {next_pin} — CLAUDE.md 스택 표는 Next.js 15다. 메이저를 올리려면 "
        "MEMORY 결정 로그가 선결이고, 그때 이 단언과 아래 override 존치 사유도 함께 고쳐라."
    )
    override = (pkg.get("overrides") or {}).get("postcss")
    assert override, (
        "postcss override가 사라졌다 — Next 15가 postcss를 8.4.31로 정확히 핀하므로 "
        "override 없이는 권고 4건(<=8.5.22)에 그대로 노출된다. 지웠다면 왜 안전한지를 "
        "이 테스트에 적어라."
    )


def test_build_outputs_are_gitignored() -> None:
    """계약 ⑦ — 의존성·빌드 산출물이 커밋되지 않는다(스캔 모수·리포 크기 결정론)."""
    ignored = {
        line.strip().rstrip("/")
        for line in (_WEBAPP / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    missing = sorted({"node_modules", ".next", "out"} - ignored)
    assert not missing, f".gitignore가 빌드 산출물을 안 덮는다: {missing}"


# ── 계약 ⑧ 변별력 봉인 (결함 주입 + 양성 대조) ──────────────────────────
#
# 아래 픽스처는 **그 절이 없으면 통과해 버리는 문자열**이다 — 추상적 경계 케이스가 아니라
# 각 패턴의 반례를 하나씩 든다(2026-09-07 '픽스처가 그 절을 밟는가' 규칙).

_CLEAN = {"app/page.tsx": "export default function P() { return <h1>이유를 묻는 수학</h1>; }\n"}

_MATH_FIXTURES = (
    "const checkAnswer = (a) => a === 1;",
    "function gradeAnswerLocally() {}",
    "const sameGraph = (a, b) => true;",
    "const diagnose = (e) => e.kind;",
    'import { create } from "mathjs";',
    "const v = evaluate(expr);",
)
_NETWORK_FIXTURES = (
    'const r = await fetch("/v1/problems");',
    "const xhr = new XMLHttpRequest();",
    'import axios from "axios";',
    'navigator.sendBeacon("/log", d);',
    'const ws = new WebSocket("wss://x");',
    'const es = new EventSource("/stream");',
)
_COPY_FIXTURES = (
    "성적이 오릅니다",
    "점수가 올라갑니다",
    "등급을 올려 드립니다",
    "실력 향상",
    "1등급 보장",
    "결과를 보장합니다",
    "국내 최초의 메타인지 수학앱",
    "가장 정확한 채점",
    "압도적 학습량",
    "효과가 입증된 학습법",
)


@pytest.mark.parametrize("fixture", _MATH_FIXTURES)
def test_math_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑧ — 수학 판정 축: 주입한 위반이 전건 검출된다."""
    assert _scan({"app/x.tsx": fixture}, _MATH_JUDGEMENT_PATTERNS), fixture


@pytest.mark.parametrize("fixture", _NETWORK_FIXTURES)
def test_network_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑧ — 네트워크 축: 주입한 위반이 전건 검출된다."""
    assert _scan({"app/x.tsx": fixture}, _NETWORK_PATTERNS), fixture


@pytest.mark.parametrize("fixture", _COPY_FIXTURES)
def test_copy_judge_detects_injected_violation(fixture: str) -> None:
    """계약 ⑧ — 카피 축: 주입한 위반이 전건 검출된다."""
    assert _scan({"app/x.tsx": f"<p>{fixture}</p>"}, _COPY_PATTERNS), fixture


@pytest.mark.parametrize(
    "patterns",
    [_MATH_JUDGEMENT_PATTERNS, _NETWORK_PATTERNS, _COPY_PATTERNS],
    ids=["math", "network", "copy"],
)
def test_judges_pass_on_clean_input(
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> None:
    """계약 ⑧ 양성 대조 — 정상 입력에서는 위반 0(무차별 실패가 아니다)."""
    assert _scan(_CLEAN, patterns) == []


@pytest.mark.parametrize(
    "patterns",
    [_MATH_JUDGEMENT_PATTERNS, _NETWORK_PATTERNS, _COPY_PATTERNS],
    ids=["math", "network", "copy"],
)
def test_judges_report_empty_scan_as_violation(
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> None:
    """계약 ⑧ — 스캔 0건은 통과가 아니라 위반이다(가드 무력화 차단)."""
    assert _scan({}, patterns) == ["스캔 대상이 0건 — 경로가 바뀌었거나 가드가 무력화됐다"]
