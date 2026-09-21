#!/usr/bin/env python3
"""저장소 파일의 바이트 무결성 가드 — cp949/UTF-8 혼용이 만드는 손상을 전수 차단한다.

왜 이 가드가 따로 있는가
------------------------
이 저장소는 같은 계열 사고를 네 번 겪었고, 그때마다 **다른 축**이었다:

  ① 2026-07-17 logconfig   — 외부 도구가 *읽는* 파일의 인코딩
  ② HARN-19                 — 우리가 *파싱하는* 서브프로세스 출력의 디코딩
  ③ OPS-53 (미착수)         — 우리가 *내는* stdout이 cp949 콘솔에서 크래시
  ④ 2026-09-14 ruleset 수집 — 셸이 *중계하는* 제3 도구 출력의 디코딩 왕복

넷 중 어느 것도 **저장소에 커밋되는 파일 자체가 깨지는 것**을 막지 못한다. 그것이 이
가드의 축이고, 손상 등급이 가장 나쁘다 — U+FFFD나 `?`로 치환된 바이트는 원본 정보가
사라져 되돌릴 수 없기 때문이다(자세한 등급표는 docs/standards/encoding_safety.md).

판정 4축
--------
  A. U+FFFD 포함        — 복구 불가 등급. **면제 없음**.
  B. UTF-8 디코딩 실패  — 선언되지 않은 비-UTF-8 바이트.
  C. mojibake           — 다른 인코딩으로 잘못 읽힌 한글이 굳어진 형태.
  D. 선언↔실측 불일치   — 스냅샷 meta가 선언한 charset으로 실제 디코딩되지 않음.
  E. 스냅샷 바이트 무결성 — 기록된 sha256과 실제 바이트가 어긋남.

경로 면제가 아니라 **선언 대조**
--------------------------------
`data/licenses/snapshots/**`는 외부 사이트가 서빙한 바이트 *그대로*가 증거이므로
UTF-8이 아닐 수 있다(실사례: 학교알리미가 euc-kr로 서빙). 이것을 경로로 통째 면제하면
그 디렉터리에서 생기는 진짜 손상도 함께 통과한다. 그래서 옆의 `*.meta.json`이
`content_type`에 선언한 charset과 대조해, **선언했고 그 선언대로 디코딩되는** 경우에만
통과시킨다. 선언이 없으면 위반이다.

C축의 판별 원리 (오탐 0건으로 실측된 구성)
------------------------------------------
"이 문자를 쓰지 마라" 식 패턴 열거는 표기 변형에서 뚫리고, 반대로 정당한 문자까지
잡는다. 그래서 문자열이 아니라 **구성된 결과**를 본다 — 의심 런을 latin-1 바이트로
되돌려 cp949/UTF-8로 디코딩했을 때 *실제 한글이 나오는가*.

여기에 조건이 하나 더 필요했다. 2026-09-14 실측에서 수학 연산자 런(`·×·÷`)과 분수
기호 런(`¼½¾·`)이 **우연히** 유효한 한글로 디코딩돼 오탐 6건이 났다. 진짜 한글
mojibake는 cp949/UTF-8 바이트 구조상 **반드시 라틴 글자를 포함**하지만 연산자 런은
기호뿐이므로, 런에 라틴 글자가 없으면 후보에서 제외한다. 이 조건을 넣자 변별력 8/8 ·
오탐 0/3,511이 됐다.

**한계(명시)**: 자동 인코딩 탐지(chardet 계열)는 쓰지 않는다. ASCII 위주·짧은 파일·
한글이 몇 자 없는 파일에서 오판하므로 판정 근거가 될 수 없다. 이 가드가 하는 것은
추측이 아니라 **결정론적 디코딩 시도와 선언 대조**뿐이다. 또한 `?`로 치환된 손상
(유형 5)은 **기계로 탐지할 수 없다** — `?`는 정상 문자와 구별되지 않는다. 그 축의
방어는 탐지가 아니라 예방(errors="replace"/"ignore" 금지)이며 문서가 소유한다.

사용
----
    python3 scripts/ops/cp949_guard.py            # 전수 검사
    python3 scripts/ops/cp949_guard.py --json     # 기계 판독용

종료 코드: 0=정합 · 1=위반 · 2=측정 실패(대상 0건·git 조회 불가 등)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = "data/licenses/snapshots/"

# 바이너리는 텍스트 규칙의 대상이 아니다. 확장자 목록 + NUL 바이트 휴리스틱을 함께 쓴다
# (확장자만 믿으면 확장자 없는 바이너리를 텍스트로 읽어 거짓 위반을 낸다).
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
        ".bin",
        ".gguf",
        ".safetensors",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".xlsx",
        ".xls",
        ".docx",
        ".pptx",
        ".mp4",
        ".mp3",
        ".wav",
        ".jar",
        ".so",
        ".dll",
        ".dylib",
        ".pyc",
        ".class",
    }
)

# mojibake 후보 런: 라틴-1 보충 영역(U+0080~U+00FF)이 4자 이상 연속.
# 리터럴 제어문자를 소스에 남기지 않으려고 chr()로 만든다.
_MOJIBAKE_RUN = re.compile("[" + chr(0x80) + "-" + chr(0xFF) + "]{4,}")

# 이 파일이 mojibake 예시를 *의도적으로* 담고 있음을 선언하는 마커.
# 사례 카탈로그 문서는 깨진 문자열을 그대로 보여 줘야 교육적이므로 예외가 필요한데,
# 경로로 면제하면 그 문서에서 생기는 진짜 손상까지 통과한다. 파일이 스스로 선언하게
# 하고, 가드는 어떤 파일이 이 마커를 썼는지 **보고서에 노출**한다(조용한 면제 금지).
ALLOW_MARKER = "encoding-guard: allow-mojibake"

# 마커는 **그 줄의 선두 내용**이어야 한다. 단순 substring 검사면 문서·로그가 마커명을
# 산문 속에서 언급하기만 해도 그 파일 전체가 조용히 면제된다 — 2026-09-14 실측으로
# 발각됐다(MEMORY.md가 결정 로그에서 마커명을 인용했다는 이유로 허용 목록에 올랐다).
# 앞에 올 수 있는 것은 주석·인용 장식뿐이다: 공백 · > · # · * · / · - · <!--
_ALLOW_MARKER_LINE = re.compile(r"^[\s>#*/\-]*(?:<!--)?[\s\-]*" + re.escape(ALLOW_MARKER))

# 리터럴 U+FFFD를 소스에 박으면 이 가드가 자기 자신을 위반으로 잡는다(A축은 면제가
# 없으므로 옳은 동작이다). 코드포인트 이스케이프로 쓴다 — 2026-09-14 실측으로 발각.
REPLACEMENT_CHAR = "\ufffd"


@dataclass
class Finding:
    axis: str
    path: str
    detail: str


@dataclass
class Report:
    scanned: int = 0
    skipped_binary: int = 0
    snapshots_checked: int = 0
    allow_marked: list[str] = field(default_factory=list)
    violations: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _tracked_files(root: Path) -> list[str]:
    """git 추적 파일만 본다 — 작업 트리의 임시 파일·빌드 산출물은 대상이 아니다."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files 실패(rc={proc.returncode}): {proc.stderr[:200]!r}")
    return [chunk.decode("utf-8", "surrogateescape") for chunk in proc.stdout.split(b"\0") if chunk]


def _is_binary(path: Path, raw: bytes) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES or b"\0" in raw[:8192]


def _has_latin_letter(run: str) -> bool:
    return any(unicodedata.category(ch) in ("Lu", "Ll") for ch in run)


def _count_hangul(text: str) -> int:
    return sum(1 for ch in text if "가" <= ch <= "힣")


def _has_allow_marker(text: str) -> bool:
    """허용 마커가 *선언으로서* 쓰였는지 본다(산문 속 언급은 면제가 아니다)."""
    return any(_ALLOW_MARKER_LINE.match(line) for line in text.splitlines())


def restore_mojibake(run: str) -> tuple[str, str] | None:
    """의심 런이 잘못 읽힌 한글인지 **복원해서** 판정한다.

    반환: (원래 인코딩, 복원된 문자열) 또는 None.
    """
    if not _has_latin_letter(run):
        # 기호만으로 이뤄진 런(수학 연산자·분수 기호)은 우연히 한글로 디코딩될 수 있다.
        # 2026-09-14 실측 오탐 6건이 전부 이 형태였다.
        return None
    try:
        raw = run.encode("latin-1")
    except UnicodeEncodeError:
        return None
    for encoding in ("cp949", "utf-8"):
        try:
            restored = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _count_hangul(restored) >= 2:
            return encoding, restored
    return None


def _declared_charset(meta: dict) -> str | None:
    """스냅샷 meta의 content_type에서 charset을 뽑는다."""
    ctype = meta.get("content_type") or ""
    m = re.search(r"charset\s*=\s*([\w\-]+)", ctype, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _sibling_meta(path: Path) -> dict | None:
    """스냅샷 본문 옆의 <같은이름>.meta.json 을 읽는다."""
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    if not meta_path.exists():
        meta_path = path.with_suffix(".meta.json")
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scan(root: Path) -> Report:
    report = Report()
    for rel in _tracked_files(root):
        path = root / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue  # 심볼릭 링크 등 — 내용이 없으면 인코딩 축의 대상이 아니다
        if _is_binary(path, raw):
            report.skipped_binary += 1
            continue
        report.scanned += 1
        _check_file(rel, path, raw, report)
    _check_snapshot_integrity(root, report)
    return report


def _check_file(rel: str, path: Path, raw: bytes, report: Report) -> None:
    is_snapshot = rel.startswith(SNAPSHOT_DIR)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # 축 B/D — 비-UTF-8 바이트. 스냅샷이면 선언 대조로 정당성을 판정한다.
        _check_undecodable(rel, path, raw, exc, is_snapshot, report)
        return

    # 축 A — U+FFFD. 면제 없음: 이미 원본 바이트 정보가 사라진 상태다.
    if REPLACEMENT_CHAR in text:
        n = text.count(REPLACEMENT_CHAR)
        idx = text.index(REPLACEMENT_CHAR)
        ctx = text[max(0, idx - 30) : idx + 30].replace("\n", "\\n")
        report.violations.append(Finding("A", rel, f"U+FFFD {n}개 — 복구 불가 등급. 주변: {ctx!r}"))

    # 축 D — 스냅샷이 UTF-8로 읽히는데 meta는 비-UTF-8을 선언한 경우(선언이 낡음).
    if is_snapshot and not rel.endswith(".meta.json"):
        meta = _sibling_meta(path)
        declared = _declared_charset(meta) if meta else None
        if declared and declared.replace("_", "-") not in ("utf-8", "utf8"):
            report.violations.append(
                Finding(
                    "D",
                    rel,
                    f"meta는 charset={declared}를 선언하는데 본문은 UTF-8로 디코딩된다 — "
                    "선언이 낡았거나 본문이 변환됐다(증거 스냅샷은 변환 금지)",
                )
            )

    # 축 C — mojibake.
    if _has_allow_marker(text):
        report.allow_marked.append(rel)
        return
    for run in _MOJIBAKE_RUN.findall(text):
        restored = restore_mojibake(run)
        if restored:
            encoding, value = restored
            report.violations.append(
                Finding(
                    "C",
                    rel,
                    f"mojibake — {run!r} 는 {encoding} 바이트를 latin-1로 읽은 것이다. "
                    f"복원: {value!r}",
                )
            )
            return  # 한 파일에 수백 건이 나올 수 있다 — 첫 건만 보고하고 다음 파일로


def _check_undecodable(
    rel: str,
    path: Path,
    raw: bytes,
    exc: UnicodeDecodeError,
    is_snapshot: bool,
    report: Report,
) -> None:
    if not is_snapshot:
        report.violations.append(
            Finding("B", rel, f"UTF-8로 디코딩되지 않는다 — {exc}. 저장소 내부는 UTF-8 전용이다")
        )
        return

    meta = _sibling_meta(path)
    if meta is None:
        report.violations.append(
            Finding(
                "B",
                rel,
                "비-UTF-8 스냅샷인데 meta.json이 없다 — 선언 없는 예외는 허용하지 않는다",
            )
        )
        return
    declared = _declared_charset(meta)
    if not declared:
        report.violations.append(
            Finding(
                "B",
                rel,
                f"비-UTF-8 스냅샷인데 meta의 content_type이 charset을 선언하지 않는다 "
                f"(content_type={meta.get('content_type')!r})",
            )
        )
        return
    try:
        raw.decode(declared)
    except (UnicodeDecodeError, LookupError) as decode_exc:
        report.violations.append(
            Finding(
                "D",
                rel,
                f"meta가 선언한 charset={declared}로도 디코딩되지 않는다 — {decode_exc}",
            )
        )
        return
    # 선언했고 선언대로 읽힌다 = 정당한 예외. 위반 아님.


def _check_snapshot_integrity(root: Path, report: Report) -> None:
    """축 E — 스냅샷 본문 바이트가 meta의 sha256과 일치하는가.

    라이선스 스냅샷은 *그 시점에 서빙된 약관*의 법적 증거다. 바이트가 바뀌면
    sha256이 검증되지 않아 증거로서의 값이 떨어진다. 2026-09-14 실측에서
    `.gitattributes`에 `.html` 규칙이 없어 Git 기본 `text auto`가 CRLF를 LF로
    정규화한 탓에 20건 중 5건이 어긋나 있었다.

    되돌릴 수 없는 훼손(혼합 줄바꿈이라 어느 줄이 CRLF였는지 알 수 없는 경우)은
    meta에 `integrity_note`와 `stored_sha256`을 기록해 **사실을 남기고** 통과시킨다.
    기록 없이 통과시키면 깨진 증거가 멀쩡한 것으로 위장되고, 무조건 위반으로 두면
    고칠 수 없는 위반을 상시 보고해 사람이 이 가드를 끄게 된다.
    """
    snap_root = root / SNAPSHOT_DIR
    if not snap_root.is_dir():
        return
    for meta_path in sorted(snap_root.glob("*/*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.violations.append(
                Finding("E", str(meta_path.relative_to(root)), f"meta 파싱 불가 — {exc}")
            )
            continue
        stem = meta_path.name.split(".")[0]
        body = next(
            (
                p
                for p in sorted(meta_path.parent.iterdir())
                if p.name.startswith(stem) and not p.name.endswith(".meta.json")
            ),
            None,
        )
        if body is None:
            report.violations.append(
                Finding("E", str(meta_path.relative_to(root)), "meta는 있는데 본문 파일이 없다")
            )
            continue
        report.snapshots_checked += 1
        actual = hashlib.sha256(body.read_bytes()).hexdigest()
        rel_body = str(body.relative_to(root))
        if actual == meta.get("sha256"):
            continue
        if meta.get("stored_sha256") == actual and meta.get("integrity_note"):
            continue  # 훼손 사실이 기록돼 있다 — 위장이 아니다
        report.violations.append(
            Finding(
                "E",
                rel_body,
                f"sha256 불일치 — 기록 {str(meta.get('sha256'))[:12]} vs 실제 {actual[:12]}. "
                "복원하거나 meta에 integrity_note·stored_sha256을 기록한다",
            )
        )


AXIS_LABEL = {
    "A": "U+FFFD(복구 불가)",
    "B": "선언 없는 비-UTF-8",
    "C": "mojibake",
    "D": "선언↔실측 불일치",
    "E": "스냅샷 바이트 무결성",
}


def render(report: Report) -> str:
    lines = [
        f"[인코딩 무결성 가드] 텍스트 {report.scanned}건 검사 "
        f"(바이너리 {report.skipped_binary}건 제외 · 스냅샷 {report.snapshots_checked}건 대조)"
    ]
    if report.allow_marked:
        lines.append(
            f"ⓘ mojibake 예시 허용 마커 사용 {len(report.allow_marked)}건 — 조용한 면제가 아니다:"
        )
        lines += [f"    · {p}" for p in report.allow_marked]
    if report.ok:
        lines.append("✔ 위반 0건")
        return "\n".join(lines)
    by_axis: dict[str, list[Finding]] = {}
    for v in report.violations:
        by_axis.setdefault(v.axis, []).append(v)
    lines.append(f"❌ 위반 {len(report.violations)}건")
    for axis in sorted(by_axis):
        lines.append(f"  [{axis}] {AXIS_LABEL[axis]} — {len(by_axis[axis])}건")
        for v in by_axis[axis][:20]:
            lines.append(f"    · {v.path}: {v.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="저장소 파일의 인코딩·바이트 무결성 전수 검사")
    parser.add_argument("--root", default=str(REPO_ROOT), help="검사할 저장소 루트")
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON 출력")
    args = parser.parse_args(argv)

    try:
        report = scan(Path(args.root))
    except RuntimeError as exc:
        print(f"❌ 측정 실패 — {exc}", file=sys.stderr)
        return 2

    if report.scanned == 0:
        # 스캔 0건은 통과가 아니라 실패다. 대상을 하나도 못 찾은 전수 가드는
        # 공허하게 초록을 내며, 그 초록은 보호의 증거가 아니다.
        print("❌ 측정 실패 — 검사 대상 0건. 경로·git 추적 상태를 확인한다", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "scanned": report.scanned,
                    "skipped_binary": report.skipped_binary,
                    "snapshots_checked": report.snapshots_checked,
                    "allow_marked": report.allow_marked,
                    "violations": [
                        {"axis": v.axis, "path": v.path, "detail": v.detail}
                        for v in report.violations
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
