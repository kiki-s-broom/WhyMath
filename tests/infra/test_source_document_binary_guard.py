"""[LIC-07 ④] 저작권 위험 원본 문서 차단 가드의 **변별력** 동결.

왜 이 테스트가 있는가
--------------------
2026-08-08에 KICE 평가기준 개발 연구 보고서 원본 PDF 2건이 저장소에 들어왔고, 아무 신호도
나지 않았다(제거 경위: `docs/ops/kice_pdf_history_purge_runbook.md`). 그 가드를 만들었으니
이제 **가드가 막으려는 상태를 실제로 주입해 red를 확인**해야 "보호 있음"으로 칠 수 있다
(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").

정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 가드도 같은 화면을
낸다. 그래서 아래 모든 케이스가 **위반을 주입한 뒤 exit 1을 요구**한다.

검증 축(가드의 ⓪①②와 대응)
--------------------------
⓪ `.gitignore` 1차 방어선이 뚫리면 red — 규칙을 지워도 아무 신호가 없으면 방어선이 아니다.
① 차단 확장자(`.pdf`·`.hwp` …)가 추적되면 red.
② **확장자를 바꿔도** 매직 바이트로 잡는다 — `보고서.pdf` → `보고서.txt` 한 번으로 뚫리면
   금지 목록은 표기 변형에서 무력하다(CLAUDE.md "금지 패턴 열거 대신 산출물 검사").
③ 허용 목록은 *사유 있는 영구 예외*이지 구멍이 아니다 — 등재분은 통과하되, ⓐ실재하지 않는
   항목(죽은 예외)이 쌓이면 red ⓑ등재 경로의 **내용이 바뀌면** red(면제는 경로가 아니라
   sha256에 붙는다 — 경로 면제는 그 경로를 원본 문서의 통로로 만든다).
④ **측정 실패는 통과가 아니다** — 전수 스캔이 성립하지 않으면 exit 2(0건 통과로 위장 금지).
   추적되는데 *읽지 못한* 파일도 여기 속한다 — "매직 없음"으로 접으면 검사되지 않은 파일이
   검사된 것처럼 계상된다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import subprocess

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / "scripts" / "ops" / "check_source_document_binaries.py"

_PDF_MAGIC = b"%PDF-1.7\n(KICE \xec\x97\xb0\xea\xb5\xac\xeb\xb3\xb4\xea\xb3\xa0\xec\x84\x9c)"

_NO_MAGIC = b"\x00\x01 not-a-known-signature\n"
"""알려진 매직이 **아닌** 바이트.

확장자 축 테스트에 매직 있는 내용을 쓰면 매직 축이 대신 잡아 준다 — 확장자 목록을 통째로
비워도 초록이라 그 테스트는 확장자 축을 전혀 동결하지 못한다(CLAUDE.md "변별력 없는 검증 스텝
금지"). 그래서 확장자 축은 **매직으로는 절대 안 걸리는** 내용으로 검사한다.
"""


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_source_document_binaries", _GUARD)
    assert spec is not None and spec.loader is not None, f"가드 스크립트 부재: {_GUARD}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_repo(
    tmp_path: pathlib.Path, guard, monkeypatch, *, min_files: int | None = None
) -> pathlib.Path:
    """차단 규칙이 갖춰진 깨끗한 tmp 저장소.

    `main()`의 전수성 하한을 넘기려면 파일이 충분히 있어야 하므로 더미를 채운다 — 하한을
    테스트용으로 낮추는 seam을 두지 않는다(그 seam이 곧 가드를 약화시키는 통로가 된다).

    실 저장소용 `_ALLOWED`는 비운다. tmp 저장소엔 그 경로가 없어 **죽은 예외**로 잡히는데,
    그건 가드가 옳게 동작하는 것이지 이 테스트가 보려는 축이 아니다(허용 목록 축은
    `test_allowlisted_path_passes`가 따로 본다).
    """
    monkeypatch.setattr(guard, "_ALLOWED", {})
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")

    rules = "\n".join(f"*{suffix}" for suffix in sorted(guard.BLOCKED_SUFFIXES))
    (repo / ".gitignore").write_text(rules + "\n", encoding="utf-8")

    count = guard._MIN_TRACKED_FILES + 5 if min_files is None else min_files
    filler = repo / "filler"
    filler.mkdir()
    for i in range(count):
        (filler / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _run(guard, repo: pathlib.Path) -> int:
    return guard.main(["check", str(repo)])


# ──────────────────────────────────────────────────────────────────────
# 기준선 — 깨끗한 상태는 통과해야 한다(아래 red들이 의미를 가지려면)
# ──────────────────────────────────────────────────────────────────────


def test_clean_repo_passes(guard, tmp_path, monkeypatch) -> None:
    assert _run(guard, _make_repo(tmp_path, guard, monkeypatch)) == guard.EXIT_OK


def test_real_repository_passes(guard) -> None:
    """실 저장소가 통과한다 — 이 계약이 깨지면 원본 문서가 들어온 것이다."""
    assert guard.main(["check", str(_REPO_ROOT)]) == guard.EXIT_OK


# ──────────────────────────────────────────────────────────────────────
# ① 확장자 축 — 위반 주입
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "docs/(고등학교)2015 개정 교육과정에 따른 평가기준 개발 연구(수학과).pdf",  # 실제 사고 파일명
        "docs/평가기준.hwp",
        "docs/자료.docx",
        "docs/모음.zip",
        # 복합 확장자 — `PurePosixPath.suffix`가 `.gz`만 보므로 `.gz`를 목록에 넣으면 걸린다.
        # 이 두 줄이 없으면 `.gitignore`가 `*.tar.gz`를 막던 시절의 공백이 그대로 남는다.
        "docs/payload.tar.gz",
        "docs/payload.tar.bz2",
    ],
)
def test_blocked_suffix_is_red(guard, tmp_path, monkeypatch, name: str) -> None:
    repo = _make_repo(tmp_path, guard, monkeypatch)
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_NO_MAGIC)  # 매직 축이 대신 잡아 주지 않게 — 확장자 축만 남긴다
    _git(repo, "add", "-f", name)  # .gitignore를 뚫고 들어온 상황을 재현
    assert _run(guard, repo) == guard.EXIT_VIOLATION, f"{name}을 잡지 못했다"


# ──────────────────────────────────────────────────────────────────────
# ② 매직 바이트 축 — 확장자 위장
# ──────────────────────────────────────────────────────────────────────


def test_renamed_pdf_is_caught_by_magic(guard, tmp_path, monkeypatch) -> None:
    """확장자만 바꾼 PDF — 금지 확장자 목록만 있으면 여기서 뚫린다."""
    repo = _make_repo(tmp_path, guard, monkeypatch)
    disguised = repo / "docs" / "innocuous_notes.txt"
    disguised.parent.mkdir(parents=True, exist_ok=True)
    disguised.write_bytes(_PDF_MAGIC)
    _git(repo, "add", "-A")
    assert _run(guard, repo) == guard.EXIT_VIOLATION

    # 대칭 — 진짜 텍스트는 통과해야 한다(모든 .txt를 잡는 가드가 아니라는 증명)
    disguised.write_text("보통의 메모\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(guard, repo) == guard.EXIT_OK


@pytest.mark.parametrize(
    ("body", "label"),
    [
        (b"PK\x03\x04rest-of-an-xlsx", "zip(오피스 OOXML·hwpx)"),
        (b"\x1f\x8b\x08\x00rest-of-a-gzip", "gzip"),
        (b"BZh9rest-of-a-bzip2", "bzip2"),
        (b"\xfd7zXZ\x00rest-of-an-xz", "xz"),
        (b"7z\xbc\xaf\x27\x1crest-of-a-7z", "7z"),
        (b"Rar!\x1a\x07\x00rest-of-a-rar", "rar"),
    ],
)
def test_renamed_archive_is_caught_by_magic(guard, tmp_path, monkeypatch, body, label) -> None:
    """확장자만 바꾼 아카이브 — 원본 문서는 아카이브로 감싸 들어오는 경로가 흔하다."""
    repo = _make_repo(tmp_path, guard, monkeypatch)
    disguised = repo / "docs" / "data.json"
    disguised.parent.mkdir(parents=True, exist_ok=True)
    disguised.write_bytes(body)
    _git(repo, "add", "-A")
    assert _run(guard, repo) == guard.EXIT_VIOLATION, f"{label} 매직을 잡지 못했다"


# ──────────────────────────────────────────────────────────────────────
# ③ 허용 목록 — 예외이되 구멍이 아니다
# ──────────────────────────────────────────────────────────────────────


_ALLOWED_BODY = b"PK\x03\x04" + "자체작성".encode("utf-8")
_ALLOWED_SHA = hashlib.sha256(_ALLOWED_BODY).hexdigest()


def _stage_allowlisted(repo: pathlib.Path, name: str, body: bytes) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    _git(repo, "add", "-f", name)


def test_allowlisted_path_passes(guard, tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path, guard, monkeypatch)
    name = "docs/self_authored.xlsx"
    _stage_allowlisted(repo, name, _ALLOWED_BODY)

    monkeypatch.setattr(guard, "_ALLOWED", {name: (_ALLOWED_SHA, "자체작성 — 제3자 저작물 아님")})
    assert _run(guard, repo) == guard.EXIT_OK

    # 같은 파일이 허용 목록에서 빠지면 즉시 red — 통과가 목록 덕임을 증명한다
    monkeypatch.setattr(guard, "_ALLOWED", {})
    assert _run(guard, repo) == guard.EXIT_VIOLATION


def test_allowlisted_path_with_changed_content_is_red(guard, tmp_path, monkeypatch) -> None:
    """허용은 *경로*가 아니라 *내용*에 붙는다 — 등재 경로에 다른 문서를 덮어쓰면 red.

    경로만으로 면제하면 `.gitignore` 부정 규칙(`!docs/...xlsx`)이 스테이징까지 허용하므로
    **그 경로 하나가 원본 문서의 통로**가 된다. 실제로 재현했다(PR #1016 리뷰 지적):
    등재 xlsx를 `%PDF-1.4…`로 바꿔치기해도 해시 검사 이전 가드는 EXIT=0을 냈다.
    """
    repo = _make_repo(tmp_path, guard, monkeypatch)
    name = "docs/self_authored.xlsx"
    _stage_allowlisted(repo, name, _PDF_MAGIC)  # 등재 경로에 PDF를 덮어썼다

    monkeypatch.setattr(guard, "_ALLOWED", {name: (_ALLOWED_SHA, "자체작성 — 제3자 저작물 아님")})
    assert _run(guard, repo) == guard.EXIT_VIOLATION

    # 대칭 — 등재된 내용 그대로면 통과한다(모든 내용을 막는 검사가 아니라는 증명)
    _stage_allowlisted(repo, name, _ALLOWED_BODY)
    assert _run(guard, repo) == guard.EXIT_OK


def test_dead_allowance_is_red(guard, tmp_path, monkeypatch) -> None:
    """실재하지 않는 예외가 남아 있으면 red — 예외가 조용히 쌓이는 것을 막는다."""
    repo = _make_repo(tmp_path, guard, monkeypatch)
    monkeypatch.setattr(guard, "_ALLOWED", {"docs/사라진파일.pdf": ("0" * 64, "옛 예외")})
    assert _run(guard, repo) == guard.EXIT_VIOLATION


# ──────────────────────────────────────────────────────────────────────
# ⓪ .gitignore 1차 방어선
# ──────────────────────────────────────────────────────────────────────


def test_missing_gitignore_rule_is_red(guard, tmp_path, monkeypatch) -> None:
    """규칙을 지우면 red — 지워도 조용하면 그건 방어선이 아니다."""
    repo = _make_repo(tmp_path, guard, monkeypatch)
    rules = [
        line
        for line in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line != "*.pdf"
    ]
    (repo / ".gitignore").write_text("\n".join(rules) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(guard, repo) == guard.EXIT_VIOLATION


def test_real_gitignore_covers_every_blocked_suffix(guard) -> None:
    """실 저장소의 1차 방어선이 차단 확장자를 전부 덮는다."""
    assert guard.find_unignored_suffixes(_REPO_ROOT) == []


# ──────────────────────────────────────────────────────────────────────
# ④ 측정 실패 ≠ 통과
# ──────────────────────────────────────────────────────────────────────


def test_thin_inventory_is_measurement_failure_not_pass(guard, tmp_path, monkeypatch) -> None:
    """전수 스캔이 성립하지 않으면 exit 2 — '0건 통과'로 위장하지 않는다."""
    repo = _make_repo(tmp_path, guard, monkeypatch, min_files=3)
    assert _run(guard, repo) == guard.EXIT_MEASUREMENT_FAILURE


def test_unreadable_tracked_file_is_measurement_failure(guard, tmp_path, monkeypatch) -> None:
    """추적되는데 읽을 수 없는 파일 — "매직 없음"으로 접으면 검사된 것처럼 OK가 나간다.

    작업 트리에서만 사라진 파일(sparse checkout·부분 체크아웃과 같은 형태)을 만든다.
    권한(chmod 000)으로 재현하지 않는 이유는 **root에서는 변별력이 없어** 정상/실패 양쪽에서
    같은 화면을 내기 때문이다(CLAUDE.md "변별력 없는 검증 스텝 금지").
    """
    repo = _make_repo(tmp_path, guard, monkeypatch)
    ghost = repo / "docs" / "ghost.txt"
    ghost.parent.mkdir(parents=True, exist_ok=True)
    ghost.write_text("내용\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ghost")
    assert _run(guard, repo) == guard.EXIT_OK  # 기준선 — 있을 때는 통과

    ghost.unlink()  # git ls-files는 여전히 목록에 낸다
    assert _run(guard, repo) == guard.EXIT_MEASUREMENT_FAILURE


def test_non_git_directory_is_measurement_failure(guard, tmp_path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert guard.main(["check", str(plain)]) == guard.EXIT_MEASUREMENT_FAILURE
