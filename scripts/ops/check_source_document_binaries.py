#!/usr/bin/env python3
"""저작권 위험 원본 문서(PDF·hwp·오피스·아카이브)의 커밋을 차단한다 — LIC-07 ④.

왜 이 가드가 있는가
------------------
2026-08-08에 KICE 평가기준 개발 연구 보고서 원본 PDF 2건(합 10.7MB)이 저장소에 들어왔다.
판권장에 "※ 본 자료 내용의 무단 복제를 금함"이 박힌 **연구보고서**였고,
`docs/data/licensing_safety.md`의 'NCIC 구분'이 이미 그 부류를 영리 차단(C등급)으로 분류해
두었는데도 아무 신호 없이 통과했다. 2026-09-06에 제거를 마쳤지만(브랜치 삭제 ·
`docs/ops/kice_pdf_history_purge_runbook.md`) **들어온 경로 자체는 그대로 열려 있었다.**

이 가드가 막는 것은 "본문을 인용했는가"(기존 policy-guard의 텍스트 패턴 축)가 아니라
**원본 문서 파일이 저장소에 들어오는 것 자체**다. 원본이 들어오면 그 안의 내용은 우리가
읽지도 검사하지도 못한 채 모든 clone에 배포된다 — 텍스트 패턴 검사가 구조적으로 볼 수 없는
축이다.

무엇을 보는가
------------
⓪ **`.gitignore` 1차 방어선** — 차단 확장자마다 ignore 규칙이 실재하는지 `git check-ignore`로
   확인한다. 2026-08-08 사고 당시 `.gitignore`는 아카이브(`*.zip` 등)만 막고 있었고 PDF·hwp·
   오피스는 규칙이 아예 없어 `git add`로 그냥 들어왔다 — 이 가드가 **자기 방어선의 실재까지**
   검사하지 않으면, 누가 그 줄을 지워도 아무 신호가 나지 않는다.
① **확장자** — `.pdf`·`.hwp`/`.hwpx`·오피스(`.doc(x)`·`.ppt(x)`·`.xls(x)`)·`.epub`·아카이브.
② **매직 바이트** — 확장자를 바꿔 넣어도 잡는다. `%PDF`(PDF) · `PK\\x03\\x04`(zip 계열:
   오피스 OOXML·hwpx·zip) · gzip·bzip2·xz·7z·rar. ①만 있으면 `보고서.pdf` → `보고서.txt`
   한 번으로 뚫린다.
③ **허용 목록의 내용 고정** — 등재 경로는 `sha256`이 일치할 때만 면제된다. 경로만으로 면제하면
   그 경로가 통로가 된다(PR #1016 리뷰 지적·실측 재현).
④ **읽지 못한 파일은 통과가 아니다** — 전수 스캔을 주장하므로 읽기 실패는 exit 2로 올린다.

①②를 함께 두는 이유는 **금지 패턴 열거가 표기 변형에서 뚫리기 때문**이다(CLAUDE.md
2026-09-01 "금지 패턴 열거 대신 산출물 검사") — 여기서 "산출물"은 파일의 실제 바이트다.

**판정 범위(과신 금지)**: 이 가드는 *원본 문서 파일*을 잡지, 텍스트로 옮겨 적은 본문을 잡지
못한다. 그쪽은 policy-guard의 패턴 축과 사람 검수 몫이다. 또한 zip이 아닌 독자 포맷(예: 구형
`.hwp`는 OLE 복합문서)은 매직으로는 안 잡히고 확장자로만 잡힌다 — 확장자를 바꾼 구형 hwp는
이 가드를 통과한다. 알면서 남기는 공백이다.

허용 목록
--------
`_ALLOWED`는 **사유가 붙은 영구 예외**이지 유예가 아니다(CLAUDE.md "만료 없는 유예·제외 금지"
— 유예가 아니므로 만료가 필요 없다). 자체 저작물처럼 저작권 위험이 없는 것만 올린다.
목록에 있는데 파일이 실재하지 않으면 **죽은 예외**로 보고 실패시킨다 — 예외가 조용히 쌓여
가드를 갉아먹는 것을 막는다.

사용:  python3 scripts/ops/check_source_document_binaries.py
종료:  0 통과 / 1 위반(차단) / 2 측정 실패(전수성 붕괴 — 통과로 위장 금지)
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
from typing import Final

EXIT_OK: Final = 0
EXIT_VIOLATION: Final = 1
EXIT_MEASUREMENT_FAILURE: Final = 2

BLOCKED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".pdf",
        ".hwp",
        ".hwpx",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".epub",
        ".zip",
        ".7z",
        ".rar",
        # tar 계열 — `PurePosixPath("a.tar.gz").suffix`가 `.gz`라 **맨 끝 조각만** 본다.
        # `.gz`·`.bz2`·`.xz`를 넣으면 `.tar.gz`·`.tar.bz2`도 자동으로 걸린다(복합 확장자
        # 별도 처리 불요). `.gitignore`가 이미 `*.tar.gz`·`*.tar.bz2`를 대용량 아카이브로
        # 다루고 있었는데 이 가드만 비어 있었다 — PR #1016 리뷰 지적.
        ".gz",
        ".bz2",
        ".xz",
        ".tar",
    }
)

BLOCKED_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF", "PDF"),
    (b"PK\x03\x04", "zip 계열(오피스 OOXML·hwpx·zip)"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
)
"""확장자를 바꿔 넣은 경우를 잡는다 — 실제 바이트가 정본이다."""

_ALLOWED: Final[dict[str, tuple[str, str]]] = {
    "docs/architecture/ai_llm_inventory_2026-07.xlsx": (
        "a15a0b380426a4fea0cd77e4456b8880857110182032b7a65315fd40b2cd2032",
        "와이매스 자체작성 AI/LLM 인벤토리(2026-07) — 제3자 저작물 아님. "
        "스택 표의 모델·프로바이더 실측 대장이라 표 형식이 정본이다.",
    ),
}
"""`{경로: (sha256, 사유)}` — 사유가 붙은 **영구 예외**이되 *내용에 묶인다*.

경로만으로 면제하면 그 경로에 제3자 문서(심지어 PDF)를 덮어써도 검사를 통째로 건너뛴다 —
`.gitignore` 부정 규칙이 그 경로의 스테이징도 허용하므로 **하드코딩된 사유 문자열 하나로
policy-guard가 통과**한다(PR #1016 리뷰 지적·실측 재현). 그래서 해시를 함께 못박고, 내용이
바뀌면 **의도적으로 해시를 갱신**해야 통과한다. 갱신 자체가 리뷰 지점이 된다.
"""

_MIN_TRACKED_FILES: Final = 100
"""전수성 하한 — 이보다 적으면 `git ls-files`가 제대로 돌지 않은 것으로 본다.

스캔 대상이 0건인데 "위반 0건 통과"를 내면 그건 검증이 아니라 위장이다
(CLAUDE.md 2026-09-01 "스캔 0건은 실패"). 실 저장소는 3,000건대다.
"""


def _tracked_files(repo_root: pathlib.Path) -> list[str] | None:
    """추적 파일 목록. 측정 자체가 실패하면 None(→ exit 2)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # 침묵 실패 금지 — 예외 타입명을 남긴다.
        print(f"[측정 실패] git ls-files 실행 불가({type(exc).__name__}): {exc}")
        return None
    return [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]


class UnreadableTrackedFileError(Exception):
    """추적 파일을 읽지 못했다 — 스캔이 불완전하므로 통과가 아니라 측정 실패다."""


def _magic_of(path: pathlib.Path) -> str | None:
    """차단 대상 매직 바이트면 그 이름, 아니면 None.

    읽기 실패를 None(=매직 없음)으로 접으면, sparse checkout이나 권한 문제로 내용을 못 본
    파일이 **검사된 것처럼** 계상돼 `OK`가 출력된다(PR #1016 리뷰 지적). 전수 스캔을 주장하는
    도구이므로 fail closed — 예외 타입명을 달아 올려보내고 호출부가 exit 2로 판정한다.
    """
    try:
        head = path.open("rb").read(8)
    except OSError as exc:
        raise UnreadableTrackedFileError(f"{path} ({type(exc).__name__}: {exc})") from exc
    for signature, label in BLOCKED_MAGIC:
        if head.startswith(signature):
            return label
    return None


def _sha256_of(path: pathlib.Path) -> str:
    """허용 목록 대조용 해시. 읽기 실패는 `UnreadableTrackedFileError`로 올린다(fail closed)."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise UnreadableTrackedFileError(f"{path} ({type(exc).__name__}: {exc})") from exc
    return digest.hexdigest()


def find_violations(repo_root: pathlib.Path, tracked: list[str]) -> list[tuple[str, str]]:
    """(경로, 사유) 목록.

    허용 목록 항목은 **해시가 일치할 때만** 면제된다 — 경로 면제는 그 경로를 통로로 만든다.
    Raises:
        UnreadableTrackedFileError: 추적 파일을 읽지 못함(→ 호출부가 exit 2).
    """
    violations: list[tuple[str, str]] = []
    for name in tracked:
        path = repo_root / name
        suffix = pathlib.PurePosixPath(name).suffix.lower()

        allowance = _ALLOWED.get(name)
        if allowance is not None:
            expected, _reason = allowance
            actual = _sha256_of(path)
            if actual == expected:
                continue
            violations.append(
                (
                    name,
                    f"허용 목록 항목이나 내용이 바뀌었다 — sha256 {actual[:12]}… ≠ "
                    f"등재값 {expected[:12]}…. 자체 저작물이 맞다면 _ALLOWED의 해시를 "
                    "의도적으로 갱신하라",
                )
            )
            continue

        if suffix in BLOCKED_SUFFIXES:
            violations.append((name, f"차단 확장자 {suffix}"))
            continue
        magic = _magic_of(path)
        if magic is not None:
            violations.append((name, f"매직 바이트 {magic} — 확장자({suffix or '없음'})와 무관"))
    return violations


def find_unignored_suffixes(repo_root: pathlib.Path) -> list[str] | None:
    """`.gitignore`가 덮지 않는 차단 확장자. 측정 자체가 실패하면 None(→ exit 2).

    실재하지 않는 탐침 경로로 `git check-ignore`를 돌린다 — 파일을 만들지 않고 규칙만 본다.
    """
    probes = [f"__ignore_probe__{suffix}" for suffix in sorted(BLOCKED_SUFFIXES)]
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"],
            input="\0".join(probes).encode("utf-8"),
            cwd=repo_root,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[측정 실패] git check-ignore 실행 불가({type(exc).__name__}): {exc}")
        return None
    # exit 0=일부 매치 · 1=매치 없음 · 그 외=오류. 1은 "전부 미차단"이라 정상 판정 대상이다.
    if result.returncode not in (0, 1):
        print(
            f"[측정 실패] git check-ignore 종료코드 {result.returncode}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
        return None
    ignored = {name for name in result.stdout.decode("utf-8", "replace").split("\0") if name}
    return [
        suffix for suffix in sorted(BLOCKED_SUFFIXES) if f"__ignore_probe__{suffix}" not in ignored
    ]


def find_dead_allowances(repo_root: pathlib.Path, tracked: list[str]) -> list[str]:
    """실재하지 않는 허용 목록 항목 — 예외가 조용히 쌓이는 것을 막는다."""
    present = set(tracked)
    return sorted(name for name in _ALLOWED if name not in present)


def main(argv: list[str]) -> int:
    repo_root = pathlib.Path(argv[1]).resolve() if len(argv) > 1 else pathlib.Path.cwd()

    tracked = _tracked_files(repo_root)
    if tracked is None:
        return EXIT_MEASUREMENT_FAILURE
    if len(tracked) < _MIN_TRACKED_FILES:
        print(
            f"[측정 실패] 추적 파일 {len(tracked)}건 — 하한 {_MIN_TRACKED_FILES} 미만. "
            "전수 스캔이 성립하지 않았다(0건 통과로 위장 금지)."
        )
        return EXIT_MEASUREMENT_FAILURE

    unignored = find_unignored_suffixes(repo_root)
    if unignored is None:
        return EXIT_MEASUREMENT_FAILURE

    dead = find_dead_allowances(repo_root, tracked)
    try:
        violations = find_violations(repo_root, tracked)
    except UnreadableTrackedFileError as exc:
        print(
            f"[측정 실패] 추적 파일을 읽지 못해 전수 스캔이 성립하지 않았다: {exc}\n"
            "  (sparse checkout·권한 문제 등. 불완전한 스캔을 OK로 내보내지 않는다.)"
        )
        return EXIT_MEASUREMENT_FAILURE

    if unignored:
        print(
            f"[위반] .gitignore가 덮지 않는 차단 확장자 {len(unignored)}건 — "
            "1차 방어선이 뚫려 있다(git add로 바로 스테이징된다):"
        )
        for suffix in unignored:
            print(f"  · {suffix}")
        print("  → .gitignore의 '저작권 위험 원본 문서' 블록에 규칙을 되살려라.")

    if dead:
        print("[위반] 허용 목록에 있으나 실재하지 않는 경로(죽은 예외) — 목록에서 지워라:")
        for name in dead:
            print(f"  · {name}")

    if violations:
        print(f"[위반] 저작권 위험 원본 문서 {len(violations)}건이 추적되고 있다:")
        for name, reason in violations:
            print(f"  · {name}  ({reason})")
        print(
            "\n원본 문서는 저장소에 넣지 않는다 — 내용이 검사되지 않은 채 모든 clone에 배포된다.\n"
            "  · 구조 메타데이터만 추출해 코퍼스로 커밋하고 원본은 커밋하지 않는다\n"
            "    (선례: data/corpus/achievement_criteria_v1 — 원본 PDF는 처리 후 미보존)\n"
            "  · 자체 저작물이라 위험이 없으면 이 스크립트의 _ALLOWED에 **사유와 함께** 등재한다\n"
            "  · 판단 기준: docs/data/licensing_safety.md · 경위: "
            "docs/ops/kice_pdf_history_purge_runbook.md"
        )

    if unignored or dead or violations:
        return EXIT_VIOLATION

    print(
        f"OK — 추적 {len(tracked)}건 전수 스캔, 저작권 위험 원본 0건 · "
        f".gitignore 차단 확장자 {len(BLOCKED_SUFFIXES)}종 전부 커버 "
        f"(허용 목록 {len(_ALLOWED)}건은 사유 등재분)"
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    sys.exit(main(sys.argv))
