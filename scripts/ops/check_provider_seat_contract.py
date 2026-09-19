#!/usr/bin/env python3
"""프로바이더 좌석 계약 스캔 게이트 — 누가 LLM 프로바이더를 손에 쥐고 호출하는가 (ARCH-46).

왜 세 번째 스캐너가 필요한가
--------------------------
자매 스캐너 둘은 *라우팅 자료구조*를 본다:

- `check_routing_data_grade.py`(EOS-59 ③) — **입력**(`RoutingRequest`)에 자료 등급이 실렸는가
- `check_routing_decision_bypass.py`(EOS-77) — **결정**(`RoutingDecision`) 손조립이 국외로 나가는가

둘 다 그 자료구조가 *등장할 때* 작동한다. 그러나 D1("모든 LLM 호출은 라우터 경유")이 실제로
깨지는 형태는 **프로바이더를 직접 쥐고 부르는 것**이며, 그 경로는 `RoutingDecision`을 아예 만들지
않을 수도 있다 — 새 프로바이더를 붙이면서 라우터를 통하지 않고 `SomeProvider().generate(...)`를
부르면 자매 스캐너 둘 다 **아무 말도 하지 않는다**(검사 대상이 등장하지 않으므로 조용히 통과).
이 스캐너는 그 사각을 메운다: 프로바이더를 임포트한 파일이 그것을 *호출*한다면, 그 파일에
**라우터 경유의 증거**가 있어야 한다.

ADR-005 열린 질문 ①에 대한 답이기도 하다 — 그 질문은 import-linter `forbidden` 계약을
후보로 들었으나 채택하지 않았다. forbidden은 "source가 target을 임포트 금지" 형태라 *허용
좌석만 열거*하려면 저장소의 모든 모듈을 source에 적어야 하고(유지보수 불가), 무엇보다
**임포트 여부만 보고 경유 여부는 못 본다**. 여기서 필요한 판정은 "임포트했는가"가 아니라
"임포트해서 *라우터 없이 불렀는가*"다.

판정 규칙 (`l3.providers.*`를 임포트한 파일마다)
----------------------------------------------
1. **조립 전용(FACTORY)** — 프로바이더를 임포트하지만 `.generate(...)`를 부르지 않는다.
   DI 팩토리·CLI 조립(`app.py`·`pregenerate/__main__.py`)이 여기다 → 통과. 조립은 D1의
   관심사가 아니다(누가 *부르는가*가 관심사다).
2. **경유 소비자(CONSUMER)** — `.generate(...)`를 부르고, 같은 파일에 라우터 경유의 증거가
   있다 → 통과. 증거는 둘 중 하나다:
   ⓐ `.route(...)` 호출 — 결정을 라우터에서 받는다(`Router()` *생성*만으로는 증거가 아니다)
   ⓑ `l3.pipeline` 임포트 — 파이프라인이 내부에서 `Router().route()`를 돈다
      (`pipeline.generate(req: RoutingRequest, ...)` 시그니처가 그 경유를 강제한다)
3. **직접 호출(위반)** — `.generate(...)`를 부르는데 ⓐⓑ 어느 증거도 없다. 유예 목록에
   있고 만료 전이면 `[WAIVED]`로 통과시킨다.

추가 규칙 — **인자 목록을 본다**(문자열 열거가 아니라 구성된 결과):
`LLMProvider.generate(prompt, system, decision, *, ...)`에서 `decision`은 3번째 위치 인자이자
필수다. 위치 인자가 3개 미만이면서 `decision=` 키워드도 없는 호출은 라우터 결정을 싣지 않은
것이므로 **위반**이다(유예 대상이 아니다 — 측정 도구도 결정은 실어야 한다).

유예 기계 (조용히 눌러앉지 못하게 — EOS-77·EOS-67 선례 동일)
-----------------------------------------------------------
유예는 `경로=YYYY-MM-DD`로만 쓴다. ①**만료** — `--today`가 만료일을 지나면 다시 위반이다.
②**unmatched** — 유예가 가리키는 파일이 직접 호출 상태가 *아니면* exit 1이다(고친 뒤 유예를
안 지우면 목록이 거짓이 된다). 만료 없는 그랜드파더는 이 저장소가 금지한다.

검사 대상·자가 변별력·정직한 공백
-------------------------------
- 대상 = 프로덕션 소스(`src/backend/whymath_backend`·`scripts`)뿐. 테스트는 제외한다 —
  provider 단위 테스트는 프로바이더를 직접 불러야 한다(자기 변별력을 막는 자가당착 방지,
  자매 스캐너 둘과 같은 이유).
- `l3.providers` 임포트를 **한 건도 못 찾으면 exit 1** — '위반 0 통과'와 '측정 실패'를 같은
  색으로 두지 않는다. 파싱 실패도 삼키지 않고 위반으로 계상한다.
- 공백(판정 범위를 밝혀 적는다): 경유 증거는 **파일 수준**에서 본다 — 같은 파일 안에서
  `Router().route()`로 받은 결정과 손으로 만든 결정이 *섞이면* 이 스캐너는 통과시킨다.
  그 축(결정이 어디서 왔는가)은 자매 스캐너 `check_routing_decision_bypass.py`가 국외 티어에
  한해 본다. 파일 간 데이터 흐름 추적은 하지 않는다.
- 공백: `getattr(mod, "OllamaProvider")()`처럼 동적으로 얻는 프로바이더는 임포트 스캔에
  안 잡힌다 — 2026-09-16 실측 프로덕션 0건. 생기면 이 문단이 확장 조건의 기록이다.

사용:  python3 scripts/ops/check_provider_seat_contract.py [경로...]
         [--waive 경로=YYYY-MM-DD ...] [--today YYYY-MM-DD]
종료:  0 통과 / 1 위반 또는 측정 실패 / 2 인자 오류
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from dataclasses import dataclass
from datetime import date

# 자매 스캐너의 공용 헬퍼 — 스크립트로 실행되면 sys.path[0]이 이 디렉터리라 그대로 import된다.
from check_routing_data_grade import DEFAULT_TARGETS, iter_python_files

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

PROVIDER_PACKAGE = "whymath_backend.l3.providers"
PIPELINE_MODULE = "whymath_backend.l3.pipeline"
ROUTER_MODULE = "whymath_backend.l3.router"

# `decision`은 provider.generate의 3번째 위치 인자(prompt, system, decision) — interfaces.py.
GENERATE_DECISION_POSITION = 3
DECISION_KEYWORD = "decision"

# 프로바이더 구현 자신은 검사 대상이 아니다 — 그들이 곧 호출 지점이다.
_PROVIDER_IMPL_DIR = ("whymath_backend", "l3", "providers")


@dataclass(frozen=True)
class Waiver:
    """유예 1건 — 저장소 상대 경로가 가리키는 직접 호출을 `until`까지만 허용한다."""

    path: str
    until: date


# 프로덕션 유예 목록 — 2026-09-16 ARCH-46 ① 전수 실측으로 채웠다.
# 전부 *측정·강등전 전용*이며, 공통 사유는 하나다: *라우터가 모델을 고르면 측정이 성립하지
# 않는다*. dense↔MoE 정확도 비교·결함 주입 검출률·결정론 재생성처럼 "모델을 고정한 채 다른
# 변수를 재는" 도구는 티어를 손으로 박는 것이 계약이다(강등전 방법론 —
# `docs/standards/superhuman_verification_standard.md` §3.1-3.2).
# 만료일은 S4 게이트 판정 지평(2026-12-31 내부 검증)에 맞춘다 — 그때 이 목록을 재확인한다.
# `residue_gate_demotion_battle.py`는 이 목록에 **없다** — 프로바이더를 조립해
# `cross_verify`에 주입할 뿐 자신은 `.generate(`를 부르지 않는 FACTORY다(2026-09-16 실측:
# 초판이 그것을 유예에 넣었고 unmatched 규칙이 잡아냈다 — 유예 기계의 변별력 실증 1건).
PROVIDER_DIRECT_WAIVERS: tuple[Waiver, ...] = (
    Waiver(
        path="src/backend/whymath_backend/harness/concept_content_review_batch.py",
        until=date(2026, 12, 31),
    ),
    Waiver(
        path="src/backend/whymath_backend/harness/quality_tier_moe_accuracy_battle.py",
        until=date(2026, 12, 31),
    ),
    Waiver(
        path="src/backend/whymath_backend/harness/generation_seed_replay_probe.py",
        until=date(2026, 12, 31),
    ),
    Waiver(path="scripts/demo/wh1_primary_probe.py", until=date(2026, 12, 31)),
)


class WaiverSyntaxError(ValueError):
    """`--waive` 인자 형식 오류 — `경로=YYYY-MM-DD`가 아니다."""


def parse_waiver(text: str) -> Waiver:
    """`경로=YYYY-MM-DD` → Waiver. 형식이 어긋나면 WaiverSyntaxError."""
    path, sep, until_text = text.rpartition("=")
    if not sep or not path:
        raise WaiverSyntaxError(f"유예 형식 오류(경로=YYYY-MM-DD 필요): {text!r}")
    try:
        until = date.fromisoformat(until_text)
    except ValueError as exc:
        raise WaiverSyntaxError(f"유예 만료일 형식 오류({type(exc).__name__}): {text!r}") from exc
    return Waiver(path=path, until=until)


def _module_of(node: ast.Import | ast.ImportFrom) -> list[str]:
    """임포트 노드가 가리키는 모듈 이름들(절대 경로만 — 상대 임포트는 빈 목록)."""
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.module and node.level == 0 else []
    return [alias.name for alias in node.names]


def imports_provider(tree: ast.AST) -> bool:
    """`l3.providers` 패키지(또는 그 하위)를 임포트하는가."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for module in _module_of(node):
                if module == PROVIDER_PACKAGE or module.startswith(PROVIDER_PACKAGE + "."):
                    return True
    return False


def has_router_evidence(tree: ast.AST) -> bool:
    """라우터 경유의 증거가 있는가 — ⓐ Router/route 호출 또는 ⓑ pipeline 임포트.

    ⓑ를 증거로 인정하는 근거: `pipeline.generate(req: RoutingRequest, ...)`는 `RoutingRequest`를
    받아 내부에서 `Router().route(req)`를 돈다(`l3/pipeline.py`). 즉 파이프라인을 타는 것은
    라우터를 타는 것이다 — 이 경유를 인정하지 않으면 `judge_seam.py`처럼 *정상*인 좌석이
    위반으로 잡힌다(2026-09-16 실측에서 실제로 그렇게 오분류됐다).
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for module in _module_of(node):
                if module in (PIPELINE_MODULE, ROUTER_MODULE):
                    return True
        if isinstance(node, ast.Call):
            # `.route(...)` 호출만 증거로 친다. `Router()` *생성*은 증거가 아니다 —
            # 만들어 놓고 쓰지 않은 채 결정을 손조립하면 그것이 곧 위장이다(2026-09-16
            # 뮤테이션 M2 생존이 그 과잉을 드러냈다: 생성 인정 절을 지워도 어떤 픽스처도
            # 붉어지지 않았고, 실제 경유는 언제나 `.route(` 호출을 동반한다).
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "route":
                return True
    return False


def _is_provider_generate_call(node: ast.Call) -> bool:
    """`무언가.generate(...)` 형태의 프로바이더 호출인가.

    속성 호출(`self._provider.generate`·`provider.generate`)만 본다. 파이프라인은 보통
    `from ...pipeline import generate as l3_generate` → `l3_generate(...)`(Name 호출)로 불리므로
    자연히 제외된다. 수신자가 `pipeline`이라고 *이름 붙은* 경우도 명시 제외한다.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "generate":
        return False
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id in ("pipeline", "l3_pipeline"):
        return False
    return True


def _has_decision_argument(node: ast.Call) -> bool:
    """호출에 라우터 결정이 실렸는가 — 3번째 위치 인자 또는 `decision=` 키워드."""
    if len(node.args) >= GENERATE_DECISION_POSITION:
        return True
    if any(kw.arg == DECISION_KEYWORD for kw in node.keywords):
        return True
    # `**kwargs` 전달은 정적으로 알 수 없다 — 보수적으로 실렸다고 본다(오탐 방지).
    return any(kw.arg is None for kw in node.keywords)


def _repo_relative(path: pathlib.Path) -> str:
    """유예 대조 키 — 저장소 상대 posix 경로(밖이면 절대 경로)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _is_provider_impl(path: pathlib.Path) -> bool:
    """`l3/providers/` 자신의 파일인가 (검사 제외)."""
    parts = path.resolve().parts
    joined = "/".join(parts)
    return "/".join(_PROVIDER_IMPL_DIR) in joined


@dataclass(frozen=True)
class FileScan:
    """한 파일의 스캔 결과."""

    seat: bool  # l3.providers를 임포트하는 좌석인가
    direct_call: bool  # 라우터 증거 없이 provider.generate를 부르는가
    issues: tuple[str, ...]


def scan_file(path: pathlib.Path, waivers: dict[str, Waiver], today: date) -> FileScan:
    """파일 1건을 스캔해 좌석 여부·직접 호출 여부·위반 목록을 낸다."""
    rel = _repo_relative(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        # 파싱 실패를 삼키면 '검사 못 한 파일'이 '통과한 파일'로 보인다.
        return FileScan(
            seat=False,
            direct_call=False,
            issues=(f"{rel}: 파싱 실패({type(exc).__name__}: {exc}) — 검사 불가",),
        )

    if _is_provider_impl(path) or not imports_provider(tree):
        return FileScan(seat=False, direct_call=False, issues=())

    generate_calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_provider_generate_call(n)
    ]
    issues: list[str] = []

    # 인자 목록 검사 — 유예와 무관하다(측정 도구도 결정은 실어야 한다).
    for call in generate_calls:
        if not _has_decision_argument(call):
            issues.append(
                f"{rel}:{call.lineno}: provider.generate 호출에 라우터 결정이 없다 — "
                f"`decision`은 3번째 위치 인자이자 필수다(l3/interfaces.py). "
                "라우터 결정을 실으라"
            )

    if not generate_calls:
        # 조립 전용(FACTORY) — 누가 부르는가가 D1의 관심사이고, 조립은 아니다.
        return FileScan(seat=True, direct_call=False, issues=tuple(issues))

    if has_router_evidence(tree):
        return FileScan(seat=True, direct_call=False, issues=tuple(issues))

    waiver = waivers.get(rel)
    if waiver is None:
        issues.append(
            f"{rel}: 프로바이더를 직접 호출하는데 라우터 경유의 증거가 없다 — "
            f"`Router().route(...)`로 결정을 받거나 `l3.pipeline.generate`를 경유하라 "
            f"(D1: 모든 LLM 호출은 라우터 경유·CLAUDE.md)"
        )
        return FileScan(seat=True, direct_call=True, issues=tuple(issues))

    if today > waiver.until:
        issues.append(
            f"{rel}: 프로바이더 직접 호출의 유예가 만료됐다"
            f"(until {waiver.until.isoformat()}, today {today.isoformat()}) — "
            "라우터 경유로 전환하거나 유예를 갱신·근거 기록"
        )
        return FileScan(seat=True, direct_call=True, issues=tuple(issues))

    print(f"[WAIVED] {rel} (until {waiver.until.isoformat()})")
    return FileScan(seat=True, direct_call=True, issues=tuple(issues))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", help="검사 경로(기본: 프로덕션 소스)")
    parser.add_argument(
        "--waive",
        action="append",
        default=[],
        metavar="경로=YYYY-MM-DD",
        help="프로바이더 직접 호출 유예(반복 가능) — 프로덕션 목록은 PROVIDER_DIRECT_WAIVERS",
    )
    parser.add_argument("--today", default=None, help="만료 판정 기준일(기본: 오늘, 테스트용)")
    args = parser.parse_args(argv[1:])

    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        cli_waivers = [parse_waiver(text) for text in args.waive]
    except (ValueError, WaiverSyntaxError) as exc:
        print(f"[인자 오류] {type(exc).__name__}: {exc}")
        return 2

    waivers = {w.path: w for w in (*PROVIDER_DIRECT_WAIVERS, *cli_waivers)}
    targets = [pathlib.Path(a) for a in args.targets] or list(DEFAULT_TARGETS)
    files = iter_python_files(targets)
    if not files:
        print(f"[측정 실패] 검사할 .py 파일이 없다 — 대상: {[str(t) for t in targets]}")
        return 1

    seats = 0
    all_issues: list[str] = []
    direct_paths: set[str] = set()
    scanned_paths: set[str] = set()
    for path in files:
        scanned_paths.add(_repo_relative(path))
        result = scan_file(path, waivers, today)
        if result.seat:
            seats += 1
        if result.direct_call:
            direct_paths.add(_repo_relative(path))
        all_issues.extend(result.issues)

    # unmatched 유예 — 가리키는 파일이 직접 호출 상태가 아니면 목록이 거짓이다.
    # **이번 스캔이 실제로 본 파일에만** 적용한다 — 대상을 좁혀 돌렸을 때(테스트·부분 스캔)
    # 시야 밖의 유예를 "사라졌다"고 보고하면 그 보고 자체가 거짓이다. 부분 스캔에서
    # 전체 유예를 unmatched로 계상하던 초판 결함을 green 픽스처가 잡았다(2026-09-16).
    for rel, waiver in sorted(waivers.items()):
        if rel not in scanned_paths:
            continue
        if rel not in direct_paths:
            all_issues.append(
                f"[유예 unmatched] {rel} (until {waiver.until.isoformat()}) — 이 유예가 가리키는 "
                "프로바이더 직접 호출이 없다. 고쳐졌으면 유예를 지우라(조용히 눌러앉기 금지)"
            )

    # 위반을 측정 실패보다 먼저 찍는다 — 좌석 0건인 트리에도 파싱 실패 같은 위반은 있을 수 있고,
    # 그것을 측정 실패 문구 뒤에 숨기면 원인이 사라진다.
    for message in all_issues:
        print(f"[FAIL] {message}")

    if seats == 0:
        print(
            f"[측정 실패] `{PROVIDER_PACKAGE}` 임포트 좌석을 한 건도 찾지 못했다 "
            f"(파일 {len(files)}건 스캔). 경로·리팩터를 확인하라 — "
            "'위반 0 통과'와 '측정 실패'를 같은 색으로 두지 않는다."
        )
        return 1

    waived = len([p for p in direct_paths if p in waivers])
    print(
        f"\n파일 {len(files)}건 / 프로바이더 좌석 {seats}건 / "
        f"직접 호출 {len(direct_paths)}건(유예 {waived}건) / 위반 {len(all_issues)}건"
    )
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
