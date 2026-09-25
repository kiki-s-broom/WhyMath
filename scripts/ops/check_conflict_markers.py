#!/usr/bin/env python3
"""커밋된 충돌 마커 전수 차단 (HARN-128).

왜 이 가드가 따로 있는가
------------------------
일반 소스 파일의 충돌 마커는 lint·pytest가 즉시 잡는다. 이 가드가 존재하는 이유는 그
*일반적인* 경우가 아니라 **CI 설정 파일 자신**이 깨지는 경우 때문이다.

사고(2026-09-02 · PR #969 · 커밋 6209a8b8): `origin/main` 머지 충돌이 해소되지 않은 채
커밋·푸시됐고, `.github/workflows/ci.yml`에 마커가 남아 GitHub Actions가 워크플로를
파싱하지 못했다. 결과는 **CI 실패가 아니라 CI 부재**였다 — 체크 0건은 화면에서 "아직 안
돌았다"와 구별되지 않는다. 마커가 *그 lint를 실행할 주체 자체를 없앤* 것이다.

즉 이 가드가 막는 것은 "틀린 코드"가 아니라 **침묵**이다(CLAUDE.md 침묵 실패 금지).

판정 규칙 — 왜 `=` 7개만으로는 위반이 아닌가
--------------------------------------------
git이 남기는 마커는 네 종류다: 시작(`<` 7개 + 라벨) · 공통조상(`|` 7개 · diff3 스타일) ·
구분선(`=` 7개) · 끝(`>` 7개 + 라벨). 이 중 **구분선만은 정상 문서에서도 나타난다** —
Markdown setext 제목의 밑줄(`제목` 다음 줄에 `=` 반복)이 정확히 7개일 수 있다.

그래서 구분선 단독은 위반으로 세지 않고, **같은 파일에 시작·공통조상·끝 중 하나라도
있을 때만** 함께 보고한다. 실제 충돌은 시작과 끝을 반드시 동반하므로 이 규칙으로
놓치는 진짜 충돌은 없고, setext 제목 오탐은 사라진다.

**한계(명시)**: 사람이 부분 해소를 하며 시작·끝만 지우고 구분선을 남긴 경우는 잡지
못한다. 그 상태는 파서를 깨뜨리지 않아 이 가드의 축(침묵)과 다르고, 오탐 0을 얻는 대가로
의도적으로 포기했다.

가드 자신이 자기 자신에 걸리지 않는 이유
----------------------------------------
패턴을 리터럴 7연속이 아니라 정규식 수량자(`{7}`)로 쓴다. 제외 목록으로 자기 자신을
빼면 그 목록이 곧 구멍이 되므로(어떤 파일이든 이름만 올리면 면제된다) 그 방식을 쓰지
않았다. 테스트 픽스처도 같은 이유로 런타임에 문자를 곱해 만든다.

면제는 **스스로 소멸한다**
--------------------------
`KNOWN_MARKERS`에 등재된 경로는 위반이 아니라 유예로 보고한다. 단 그 경로에 마커가
**없어지면 그 순간 위반**이 된다(낡은 면제 금지 — `admin_guard_audit.stale_guard_exemptions`
선례). 날짜 만료가 아니라 상태 만료라서, 정리가 끝나면 CI가 면제 삭제를 강제한다.
CLAUDE.md "만료 없는 유예·제외 금지"를 날짜가 아닌 구조로 충족한다.

이 가드가 **덮지 못하는 것**과 그것을 어떻게 덮었는가 (HARN-128 ③)
------------------------------------------------------------------
한계는 실재한다 — 실측(2026-09-23)으로 확인했다. `ci.yml`에 마커를 주입하면 YAML
파서가 `ScannerError`를 내므로, 그 파일 *안의* `policy-guard` 스텝은 사고 상황에서
정확히 함께 죽는다. ci.yml 안에서는 닫을 수 없는 구멍이다.

그래서 같은 스크립트를 **별도 워크플로 파일**(`.github/workflows/conflict-guard.yml`)
에서도 돌린다. GitHub는 워크플로를 파일 단위로 독립 파싱하므로 ci.yml이 깨져도 그
잡은 뜬다. 반대로 그 파일이 깨지면 이 스텝이 그 파일의 마커를 잡는다 — **상호 엄호**이고,
둘이 동시에 깨지는 경우만 남는다. "두 배선이 서로 다른 파일에 있다"까지가 계약이며
`tests/infra/test_conflict_marker_guard.py`가 동결한다.

함께 판정한 대안 2종:
  · **로컬 훅(pre-commit)** — 미채택. 커밋 시점 차단이라 가장 이르지만, 훅은 각자
    머신에 설치돼야 하고 `--no-verify`로 우회되며 에이전트 세션·CI에는 존재하지 않는다.
    "설치됐는지 기계가 확인할 수 없는 보호"는 상시 무력 상태와 구별되지 않는다.
  · **별도 워크플로** — 채택(위). 설치가 필요 없고 배선 실재성을 테스트가 동결한다.

남은 정직한 공백:
  · `conflict-guard` 잡은 **required check가 아니다**(의도적). 이 잡의 일은 차단이 아니라
    *설명*이다 — ci.yml이 깨진 PR은 required check가 0건 보고돼 이미 머지가 막히고,
    사고의 실제 피해는 무단 착지가 아니라 *원인을 알 수 없는 정지*였다. required 승격은
    Kiki의 룰셋 편집(사람 게이트)을 요구하고, 그 목록의 현행성은 `HARN-82`의 축이다.
  · required 여부를 판단하도록 강제하는 계약(`test_required_checks_doc.py`)은 **ci.yml의
    잡만** 열거한다 — 별도 워크플로의 잡은 그 판단에서 구조적으로 빠진다. 여기서는
    위 단락으로 판단을 명문화했고, 계약 확장은 `HARN-165`로 등재했다.
  · `harness-audit.yml`은 `push: branches: [main]`이라 PR 브랜치를 보지 않는다 —
    착지 후에야 보이므로 사전 차단 경로가 되지 못한다.
사용
----
    python3 scripts/ops/check_conflict_markers.py          # 전수 검사
    python3 scripts/ops/check_conflict_markers.py --json   # 기계 판독용

종료 코드: 0=정합 · 1=위반 · 2=측정 실패(대상 0건·git 조회 불가 등)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 마커 4종. **리터럴 7연속을 쓰지 않는다** — 그러면 이 파일 자신이 스캔에 걸린다.
#: `^`는 아래 `pattern.match()`와 **의도적으로 중복**이다(match는 문자열 시작에
#: 앵커되므로 `^`가 없어도 같은 행동이다). 둘 중 하나만 지워도 행동이 유지되는 것을
#: 뮤테이션으로 실측했고(2026-09-23 M1·M1a 생존 · 동시 제거 M1b는 RED), 그 이중성은
#: 누군가 match를 search로 바꿔도 행두 전용 판정이 남게 하려는 것이다.
MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("start", re.compile(r"^<{7}(?:\s|$)")),
    ("base", re.compile(r"^\|{7}(?:\s|$)")),
    ("separator", re.compile(r"^={7}\s*$")),
    ("end", re.compile(r"^>{7}(?:\s|$)")),
)

#: 구분선 단독은 위반이 아니다(Markdown setext 제목). 이 셋 중 하나가 같은 파일에 있어야
#: 구분선도 마커로 센다 — 모듈 docstring "판정 규칙" 참조.
DECISIVE_KINDS = frozenset({"start", "base", "end"})

#: 상태 만료 면제. 값은 **소유 태스크와 사유**다 — 사유 없는 면제는 면제가 아니라 구멍이다.
#: 등재된 경로에서 마커가 사라지면 그 순간 위반이 되어 이 항목의 삭제를 강제한다.
KNOWN_MARKERS: dict[str, str] = {}

BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".pdf",
        ".zip",
        ".gz",
        ".zst",
        ".tar",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".xlsx",
        ".docx",
        ".pptx",
        ".db",
        ".sqlite",
        ".so",
        ".dylib",
        ".dll",
    }
)


@dataclass(frozen=True)
class Hit:
    """마커 1건 — 경로·줄번호·종류. 실패 메시지가 '어디를 고치라'를 바로 말하게 한다."""

    path: str
    line: int
    kind: str
    text: str


@dataclass
class Report:
    exemptions: dict[str, str] = field(default_factory=dict)
    scanned: int = 0
    skipped_binary: int = 0
    violations: list[Hit] = field(default_factory=list)
    waived: dict[str, list[Hit]] = field(default_factory=dict)
    stale_exemptions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations and not self.stale_exemptions


def _tracked_files(root: Path) -> list[str]:
    """git 추적 파일만 본다.

    작업 트리의 임시 파일·빌드 산출물은 커밋되지 않으므로 이 축의 대상이 아니다.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files 실패(rc={proc.returncode}): {proc.stderr[:200]!r}")
    return [chunk.decode("utf-8", "surrogateescape") for chunk in proc.stdout.split(b"\0") if chunk]


def _is_binary(path: Path, raw: bytes) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES or b"\0" in raw[:8192]


def find_markers(rel: str, text: str) -> list[Hit]:
    """한 파일의 마커 목록. 구분선 단독은 제외한다(모듈 docstring '판정 규칙')."""
    hits: list[Hit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in MARKER_PATTERNS:
            if pattern.match(line):
                hits.append(Hit(path=rel, line=lineno, kind=kind, text=line[:60]))
                break
    if not any(hit.kind in DECISIVE_KINDS for hit in hits):
        return []
    return hits


def scan(root: Path, exemptions: dict[str, str] | None = None) -> Report:
    """전수 스캔.

    `exemptions`는 **이 저장소의 경로 목록**이므로 다른 루트에는 적용되지 않는다
    (main이 root를 보고 결정한다 — 픽스처 저장소에서 낡은 면제가 상시 위반으로
    보고되는 것을 막되, CLI 플래그로 면제를 끄는 탈출구는 만들지 않는다).
    """
    exemptions = KNOWN_MARKERS if exemptions is None else exemptions
    report = Report(exemptions=dict(exemptions))
    for rel in _tracked_files(root):
        path = root / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue  # 심볼릭 링크 등 — 내용이 없으면 이 축의 대상이 아니다
        if _is_binary(path, raw):
            report.skipped_binary += 1
            continue
        report.scanned += 1
        text = raw.decode("utf-8", "replace")
        hits = find_markers(rel, text)
        if not hits:
            continue
        if rel in exemptions:
            report.waived[rel] = hits
        else:
            report.violations.extend(hits)

    # 낡은 면제 — 등재됐는데 마커가 없거나 파일이 사라진 경우. 면제는 상태로 만료한다.
    for rel in exemptions:
        if rel not in report.waived:
            report.stale_exemptions.append(rel)
    return report


def render(report: Report) -> str:
    lines = [
        f"[충돌 마커 가드] 텍스트 {report.scanned}건 검사 "
        f"(바이너리 {report.skipped_binary}건 제외)"
    ]
    for rel, hits in sorted(report.waived.items()):
        lines.append(f"ⓘ 유예 {rel} — 마커 {len(hits)}건 · 조용한 면제가 아니다")
        lines.append(f"    사유: {report.exemptions.get(rel, '(사유 미등재)')}")
    if report.stale_exemptions:
        lines.append(f"❌ 낡은 면제 {len(report.stale_exemptions)}건 — 정리됐으면 항목을 지운다:")
        lines += [
            f"    · {rel} (KNOWN_MARKERS에 있으나 마커가 없다)" for rel in report.stale_exemptions
        ]
    if report.violations:
        by_path: dict[str, list[Hit]] = {}
        for hit in report.violations:
            by_path.setdefault(hit.path, []).append(hit)
        lines.append(f"❌ 충돌 마커 {len(report.violations)}건 / {len(by_path)}파일")
        for rel in sorted(by_path):
            lines.append(f"  · {rel}")
            for hit in by_path[rel][:10]:
                lines.append(f"      {hit.line}행 [{hit.kind}] {hit.text}")
    if report.ok:
        lines.append("✔ 위반 0건")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="커밋된 충돌 마커 전수 검사")
    parser.add_argument("--root", default=str(REPO_ROOT), help="검사할 저장소 루트")
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON 출력")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    # 면제표는 이 저장소의 경로 목록이다 — 다른 루트(테스트 픽스처)에는 의미가 없다.
    exemptions = KNOWN_MARKERS if root == REPO_ROOT else {}
    try:
        report = scan(root, exemptions)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"❌ 측정 실패 — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if report.scanned == 0:
        # 스캔 0건은 통과가 아니라 실패다 — 대상을 못 찾은 전수 가드는 공허하게 초록을 낸다.
        print("❌ 측정 실패 — 검사 대상 0건. 경로·git 추적 상태를 확인한다", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "scanned": report.scanned,
                    "skipped_binary": report.skipped_binary,
                    "violations": [
                        {"path": h.path, "line": h.line, "kind": h.kind} for h in report.violations
                    ],
                    "waived": {
                        rel: [{"line": h.line, "kind": h.kind} for h in hits]
                        for rel, hits in report.waived.items()
                    },
                    "stale_exemptions": report.stale_exemptions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render(report))

    if not report.ok:
        print(
            "::error::커밋된 충돌 마커 — 워크플로 파일이면 CI가 red가 아니라 '안 뜬다'(HARN-128)",
            file=sys.stderr,
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
