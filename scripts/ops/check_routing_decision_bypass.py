#!/usr/bin/env python3
"""라우터 우회 결정 스캔 게이트 — 손 조립 `RoutingDecision`이 법적 게이트를 건너뛰는가 (EOS-77).

왜 두 번째 스캐너가 필요한가
--------------------------
`check_routing_data_grade.py`(EOS-59 ③)는 **입력**(`RoutingRequest`)에 등급이 실렸는지를 본다.
그러나 등급 판정의 *집행 지점*은 `Router.route` 하나뿐이다 — `RoutingDecision`을 손으로
조립해 provider에 바로 넘기면 입력에 등급을 아무리 잘 적어도 판정을 지나지 않는다.
2026-09-01 실측(EOS-59 자진 공개): 프로덕션 직접 생성 중 클라우드 도달 1건
(`ops/live_preflight._cloud_mid_decision`)이 그 사각이었다. 오늘은 리터럴 스모크 프롬프트라
법적 노출 0이지만, AIHub 자료가 저작 입력으로 편입되는 순간 실 노출이 된다 — 그래서
산문이 아니라 게이트로 막는다(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").

판정 규칙 (`RoutingDecision(...)` 생성 호출마다)
----------------------------------------------
`cost_tier=` 인자의 **형태**로 셋 중 하나로 분류한다.

1. **클라우드 리터럴** — `CostTier.CLOUD_MID`/`CostTier.CLOUD_HIGH`(속성 이름) 또는 문자열
   `"cloud_mid"`/`"cloud_high"`가 값 표현식 **어디에든** 있으면(조건식·호출 인자·첨자 포함).
   이 결정은 라우터를 거치지 않고 국외 프로바이더에 도달할 수 있다 → **위반**. 유예 목록
   (`--waive` 또는 `CLOUD_DIRECT_WAIVERS`)에 `경로::함수`가 있고 만료 전이면 통과시키되
   `[WAIVED]`로 출력한다.
2. **로컬 리터럴** — `CostTier.LOCAL`/`"local"`. 국외로 나가지 않으므로 사각이 아니다 → 통과.
3. **비리터럴** — 변수·속성(`decision.cost_tier`)·호출 등. 티어를 정적으로 알 수 없으므로
   **판정 승계**가 있어야 한다: `data_export_reason=` 키워드가 있고 그 값이 *표현식*
   (라우터 결정·`export_judgment` 결과에서 온 것)이어야 통과. 키워드가 없거나 값이 리터럴
   (`"EXPORT_ALLOWED"`·`None`)이면 → **위반**(승계가 아니라 위조다).

추가 규칙:
- `cost_tier=` 키워드가 없거나 `**kwargs`/위치 인자만 있으면 정적 증명 불가 → **위반**.
- `.model_copy(update={... "cost_tier": ...})`는 라우터 판정을 사후에 무효화하는 경로 →
  **위반**(리터럴 dict에 `cost_tier` 키가 있을 때만 본다 — 비리터럴 update는 아래 공백).

유예 기계 (조용히 눌러앉지 못하게 — EOS-67 baseline 선례)
--------------------------------------------------------
유예는 `경로::함수=YYYY-MM-DD`로만 쓴다. ①**만료** — `--today`(기본 오늘)가 만료일을 지나면
그 자리는 다시 위반이다. ②**unmatched** — 유예가 가리키는 자리에 클라우드 리터럴 생성이
*없으면* exit 1이다(고친 뒤 유예를 안 지우면 목록이 거짓이 된다). 유예가 0건이면 이 규칙은
아무 일도 하지 않는다 — 2026-09-05 기준 프로덕션 유예는 **0건**이다(live_preflight를
라우터 경유로 전환했다).

검사 대상·자가 변별력·정직한 공백
-------------------------------
- 대상 = 프로덕션 소스(`src/backend/whymath_backend`·`scripts`)뿐. 테스트는 제외한다 —
  provider 단위 테스트는 클라우드 결정을 손으로 만들어야 한다(자기 변별력 테스트를 막는
  자가당착 방지, `check_routing_data_grade.py`와 같은 이유).
- `RoutingDecision(` 생성 호출을 **한 건도 못 찾으면 exit 1** — '위반 0 통과'와 '측정 실패'를
  같은 색으로 두지 않는다. 파싱 실패도 삼키지 않고 위반으로 계상한다.
- 공백: `RoutingDecision.model_validate(...)`·`model_construct(...)`, 비리터럴 `update=` —
  2026-09-05 실측 프로덕션 0건. 생기면 이 스캐너를 확장한다(이 문단이 그 조건의 기록이다).
- 공백: 승계 값이 *표현식*이라는 것까지만 본다 — `data_export_reason=some_unrelated_var`는
  통과한다. 그 축은 코드 리뷰 대상이다. 같은 이유로 리터럴이 전혀 없는 동적 티어
  (`cost_tier=pick_tier()`)는 승계만 있으면 통과한다 — 정적으로 더 알 수 없다.

사용:  python3 scripts/ops/check_routing_decision_bypass.py [경로...]
         [--waive 경로::함수=YYYY-MM-DD ...] [--today YYYY-MM-DD]
종료:  0 통과 / 1 위반 또는 측정 실패 / 2 인자 오류
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from dataclasses import dataclass
from datetime import date

# 같은 디렉터리의 자매 스캐너에서 공용 헬퍼를 가져온다 — 스크립트로 실행되면 sys.path[0]이
# 이 파일의 디렉터리라 별도 경로 조작 없이 import된다(CI cwd=src/backend여도 동일).
from check_routing_data_grade import DEFAULT_TARGETS, iter_python_files

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

TARGET_CALL = "RoutingDecision"
TIER_KEYWORD = "cost_tier"
INHERIT_KEYWORD = "data_export_reason"

# CostTier 열거의 *이름*과 *값* 양쪽을 본다 — `use_enum_values=True`라 소스에 문자열 값이
# 직접 적히는 형태도 실재한다(tests/backend/ops/test_live_preflight.py 등).
CLOUD_TIER_NAMES: frozenset[str] = frozenset({"CLOUD_MID", "CLOUD_HIGH"})
CLOUD_TIER_VALUES: frozenset[str] = frozenset({"cloud_mid", "cloud_high"})
LOCAL_TIER_NAMES: frozenset[str] = frozenset({"LOCAL"})
LOCAL_TIER_VALUES: frozenset[str] = frozenset({"local"})


@dataclass(frozen=True)
class Waiver:
    """유예 1건 — `경로::함수`가 가리키는 클라우드 리터럴 생성을 `until`까지만 허용한다."""

    site: str
    until: date


# 프로덕션 유예 목록 — 2026-09-05 실측 0건. 항목을 넣을 때는 반드시 만료일과 사유 주석을 함께
# 적는다(만료 없는 유예 금지). 만료·unmatched는 이 스캐너가 exit 1로 강제한다.
CLOUD_DIRECT_WAIVERS: tuple[Waiver, ...] = ()


class WaiverSyntaxError(ValueError):
    """`--waive` 인자 형식 오류 — `경로::함수=YYYY-MM-DD`가 아니다."""


def parse_waiver(text: str) -> Waiver:
    """`경로::함수=YYYY-MM-DD` → Waiver. 형식이 어긋나면 WaiverSyntaxError."""
    site, sep, until_text = text.rpartition("=")
    if not sep or "::" not in site:
        raise WaiverSyntaxError(f"유예 형식 오류(경로::함수=YYYY-MM-DD 필요): {text!r}")
    try:
        until = date.fromisoformat(until_text)
    except ValueError as exc:
        raise WaiverSyntaxError(f"유예 만료일 형식 오류({type(exc).__name__}): {text!r}") from exc
    return Waiver(site=site, until=until)


def _is_decision_call(node: ast.Call) -> bool:
    """`RoutingDecision(...)` 또는 `모듈.RoutingDecision(...)` 생성 호출인가."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == TARGET_CALL
    if isinstance(func, ast.Attribute):
        return func.attr == TARGET_CALL
    return False


def _keyword(node: ast.Call, name: str) -> ast.expr | None:
    """키워드 인자 값 노드 (없으면 None)."""
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _has_star_kwargs(node: ast.Call) -> bool:
    return any(keyword.arg is None for keyword in node.keywords)


def _is_cloud_literal(node: ast.AST) -> bool:
    """노드 하나가 클라우드 티어 리터럴인가 (`CostTier.CLOUD_*` 속성 또는 `"cloud_*"` 문자열)."""
    if isinstance(node, ast.Attribute):
        return node.attr in CLOUD_TIER_NAMES
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in CLOUD_TIER_VALUES
    return False


def _is_local_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in LOCAL_TIER_NAMES
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in LOCAL_TIER_VALUES
    return False


def classify_tier(value: ast.expr) -> str:
    """`cost_tier=` 값 노드 → "cloud" / "local" / "dynamic".

    **서브트리 전체**를 본다 — 최상위 노드만 보면 `CostTier.CLOUD_MID if flag else
    decision.cost_tier`·`_as_cost_tier("cloud_high")`처럼 표현식 안에 숨긴 리터럴이 "동적"으로
    분류되고, 승계 키워드만 붙이면 통과했다(PR #983 Codex P1). 클라우드 리터럴이 *어디든*
    있으면 클라우드다(보수적 — 그 표현식은 라우터 없이 국외 티어를 만들 수 있다). 로컬은
    최상위가 로컬 리터럴일 때만이다(`LOCAL if x else decision.cost_tier`는 동적 → 승계 필요).
    """
    if any(_is_cloud_literal(node) for node in ast.walk(value)):
        return "cloud"
    if _is_local_literal(value):
        return "local"
    return "dynamic"


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """각 호출 노드 id → 가장 안쪽 함수 이름(모듈 수준이면 "<module>")."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, child.name)
            else:
                if isinstance(child, ast.Call):
                    owner[id(child)] = current
                visit(child, current)

    visit(tree, "<module>")
    return owner


def _site_key(path: pathlib.Path, func: str) -> str:
    """유예 대조 키 — 저장소 상대 posix 경로(밖이면 절대 경로)::함수."""
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(_REPO_ROOT)
    except ValueError:
        rel = resolved
    return f"{rel.as_posix()}::{func}"


@dataclass(frozen=True)
class FileScan:
    """한 파일의 스캔 결과."""

    decision_calls: int
    issues: tuple[str, ...]
    cloud_sites: tuple[str, ...]  # 클라우드 리터럴 생성의 site key(유예 대조용)


def scan_file(path: pathlib.Path, waivers: dict[str, Waiver], today: date) -> FileScan:
    """한 파일을 스캔한다. 파싱 실패는 삼키지 않고 위반으로 계상한다(침묵 실패 금지)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return FileScan(
            0,
            (f"{path}: 파싱 실패({type(exc).__name__}) — 검사 불가이므로 위반으로 계상",),
            (),
        )

    owners = _enclosing_functions(tree)
    calls = 0
    issues: list[str] = []
    cloud_sites: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_model_copy_resetting_tier(node):
            issues.append(
                f"{path}:{node.lineno}: model_copy(update=...)가 `{TIER_KEYWORD}`를 재설정한다 — "
                "라우터의 등급 판정을 사후에 무효화하는 경로. 티어가 바뀌면 Router.route를 "
                "다시 부르라."
            )
            continue
        if not _is_decision_call(node):
            continue
        calls += 1
        site = _site_key(path, owners.get(id(node), "<module>"))
        problem = _judge_decision_call(node, site, waivers, today, cloud_sites)
        if problem is not None:
            issues.append(f"{path}:{node.lineno}: {problem}")
    return FileScan(calls, tuple(issues), tuple(cloud_sites))


def _is_model_copy_resetting_tier(node: ast.Call) -> bool:
    """`x.model_copy(update={..., "cost_tier": ...})` 형태인가 (리터럴 dict만 본다)."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "model_copy"):
        return False
    update = _keyword(node, "update")
    if not isinstance(update, ast.Dict):
        return False
    return any(isinstance(key, ast.Constant) and key.value == TIER_KEYWORD for key in update.keys)


def _judge_decision_call(
    node: ast.Call,
    site: str,
    waivers: dict[str, Waiver],
    today: date,
    cloud_sites: list[str],
) -> str | None:
    """생성 호출 1건 판정 — 위반이면 메시지, 통과면 None. 클라우드 리터럴은 cloud_sites에 적재."""
    if node.args:
        return "RoutingDecision 생성에 위치 인자 — 티어를 정적으로 증명할 수 없다(키워드로 적으라)"
    tier_value = _keyword(node, TIER_KEYWORD)
    if tier_value is None:
        if _has_star_kwargs(node):
            return f"**kwargs만 있고 `{TIER_KEYWORD}=` 키워드가 없다(정적 증명 불가)"
        return f"`{TIER_KEYWORD}=` 키워드 없음(정적 증명 불가)"

    kind = classify_tier(tier_value)
    if kind == "local":
        return None  # 국외로 나가지 않는다 — 사각 아님
    if kind == "cloud":
        cloud_sites.append(site)
        waiver = waivers.get(site)
        if waiver is None:
            return (
                "클라우드 티어 RoutingDecision 직접 생성 — 데이터 등급(법적) 게이트를 지나지 "
                f"않고 국외 프로바이더에 도달한다. Router.route를 경유하라 (site: {site})"
            )
        if today > waiver.until:
            return (
                f"클라우드 티어 직접 생성의 유예가 만료됐다(until {waiver.until.isoformat()}, "
                f"today {today.isoformat()}) — Router.route로 전환하거나 유예를 갱신·근거 기록 "
                f"(site: {site})"
            )
        print(f"[WAIVED] {site} (until {waiver.until.isoformat()})")
        return None

    # dynamic — 판정 승계가 있어야 한다
    inherit = _keyword(node, INHERIT_KEYWORD)
    if inherit is None:
        return (
            f"`{TIER_KEYWORD}`가 비리터럴인데 `{INHERIT_KEYWORD}=` 승계가 없다 — 티어를 정적으로 "
            "알 수 없고 등급 판정도 실리지 않는다. 라우터 결정의 판정을 승계하라"
        )
    if isinstance(inherit, ast.Constant):
        return (
            f"`{INHERIT_KEYWORD}=`가 리터럴({inherit.value!r})이다 — 판정 *승계*가 아니라 위조다. "
            "라우터 결정(`decision.data_export_reason`) 또는 `export_judgment(...).reason`을 실으라"
        )
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", help="검사 경로(기본: 프로덕션 소스)")
    parser.add_argument(
        "--waive",
        action="append",
        default=[],
        metavar="경로::함수=YYYY-MM-DD",
        help="클라우드 리터럴 생성 유예(반복 가능) — 프로덕션 목록은 CLOUD_DIRECT_WAIVERS",
    )
    parser.add_argument("--today", default=None, help="만료 판정 기준일(기본: 오늘, 테스트용)")
    args = parser.parse_args(argv[1:])

    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        cli_waivers = [parse_waiver(text) for text in args.waive]
    except (ValueError, WaiverSyntaxError) as exc:
        print(f"[인자 오류] {type(exc).__name__}: {exc}")
        return 2

    waivers = {w.site: w for w in (*CLOUD_DIRECT_WAIVERS, *cli_waivers)}
    targets = [pathlib.Path(a) for a in args.targets] or list(DEFAULT_TARGETS)
    files = iter_python_files(targets)
    if not files:
        print(f"[측정 실패] 검사할 .py 파일이 없다 — 대상: {[str(t) for t in targets]}")
        return 1

    total_calls = 0
    all_issues: list[str] = []
    seen_cloud_sites: set[str] = set()
    for path in files:
        result = scan_file(path, waivers, today)
        total_calls += result.decision_calls
        all_issues.extend(result.issues)
        seen_cloud_sites.update(result.cloud_sites)

    # unmatched 유예 — 가리키는 자리에 클라우드 리터럴 생성이 없으면 목록이 거짓이다.
    for site, waiver in sorted(waivers.items()):
        if site not in seen_cloud_sites:
            all_issues.append(
                f"[유예 unmatched] {site} (until {waiver.until.isoformat()}) — 이 유예가 가리키는 "
                "클라우드 티어 직접 생성이 없다. 고쳐졌으면 유예를 지우라(조용히 눌러앉기 금지)"
            )

    # 위반은 측정 실패보다 *먼저* 찍는다 — 생성 호출 0건인 트리에도 model_copy 재설정·파싱
    # 실패 같은 위반은 있을 수 있고, 그것을 측정 실패 문구 뒤에 숨기면 원인이 사라진다.
    for message in all_issues:
        print(f"[FAIL] {message}")

    if total_calls == 0:
        print(
            f"[측정 실패] {TARGET_CALL}( 생성 호출을 한 건도 찾지 못했다 "
            f"(파일 {len(files)}건 스캔). 경로·리팩터를 확인하라 — "
            "'위반 0 통과'와 '측정 실패'를 같은 색으로 두지 않는다."
        )
        return 1

    waived = len([s for s in seen_cloud_sites if s in waivers])
    print(
        f"\n파일 {len(files)}건 / {TARGET_CALL} 생성 호출 {total_calls}건 / "
        f"클라우드 리터럴 {len(seen_cloud_sites)}건(유예 {waived}건) / 위반 {len(all_issues)}건"
    )
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
