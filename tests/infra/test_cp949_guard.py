"""`scripts/ops/cp949_guard.py` — 인코딩 무결성 가드의 **변별력 동결**.

왜 이 테스트가 있는가
---------------------
정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 가드도 같은
화면을 낸다(CLAUDE.md 2026-09-01). 그래서 축마다 **그 축이 막으려는 상태를 실제로
주입해** exit 1이 나오는지 확인한다.

픽스처 설계 원칙 (CLAUDE.md 2026-09-07 · 2026-09-08)
----------------------------------------------------
① 절마다 **그 절의 반례**를 둔다. "경계 케이스"라는 추상이 아니라, 그 조건이 없으면
   통과해 버리는 구체적 문자열을 넣는다.
② **성공 방향 대조군**을 함께 둔다. 대조군이 없으면 "전부 위반으로 계상"이라는 과잉
   수정이 전건 RED로 통과한다. 이 가드에서 그 위험은 실재했다 — 2026-09-14 첫 설계가
   수학 연산자 런(`·×·÷`)을 mojibake로 오탐해 6건이 났다.
③ 전건 RED를 **커버리지의 증거로 읽지 않는다**. 주입 목록에 올린 절만 검사된다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "ops"))

import cp949_guard  # noqa: E402

_FFFD = chr(0xFFFD)


# ---------------------------------------------------------------------------
# 하네스 — 임시 git 저장소를 만들어 그 위에서 가드를 돌린다
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path: Path) -> Path:
    """정상 상태의 최소 저장소. 한국어 UTF-8 파일과 수학 기호 파일을 포함한다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "hangul.md").write_text(
        "# 수학 개념 그래프\n\n한글이 정상인 UTF-8 문서다.\n", encoding="utf-8"
    )
    # 대조군: 라틴-1 보충 영역이지만 기호뿐 — mojibake가 아니다(2026-09-14 오탐 6건의 형태).
    (repo / "operators.py").write_text('SIGNS = "·×·÷"\nFRACTIONS = "¼½¾·"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    return repo


def _run(repo: Path) -> int:
    return cp949_guard.main(["--root", str(repo)])


def _add_snapshot(repo: Path, source: str, body: bytes, content_type: str) -> Path:
    """라이선스 스냅샷 1건(본문 + meta)을 만든다."""
    d = repo / "data" / "licenses" / "snapshots" / source
    d.mkdir(parents=True, exist_ok=True)
    stem = "deadbeefcafe0001"
    html = d / f"{stem}.html"
    html.write_bytes(body)
    (d / f"{stem}.meta.json").write_text(
        json.dumps(
            {
                "source_id": source,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    return html


# ---------------------------------------------------------------------------
# 대조군 — 정상 상태는 통과해야 한다 (과잉 탐지 방지)
# ---------------------------------------------------------------------------


def test_clean_repo_passes(tmp_path: Path) -> None:
    """한글 UTF-8 + 수학 기호 런이 있는 정상 저장소는 exit 0."""
    assert _run(_make_repo(tmp_path)) == 0


def test_math_operator_runs_are_not_mojibake(tmp_path: Path) -> None:
    """`·×·÷` 는 우연히 한글로 디코딩되지만 mojibake가 아니다.

    이것이 C축의 '라틴 글자 포함' 조건이 존재하는 이유다. 조건이 없으면 이 저장소의
    수학 표기 파일 6건이 전부 위반이 된다(2026-09-14 실측 오탐).
    """
    assert cp949_guard.restore_mojibake("·×·÷") is None
    assert cp949_guard.restore_mojibake("¼½¾·") is None


def test_declared_non_utf8_snapshot_passes(tmp_path: Path) -> None:
    """meta가 charset을 선언했고 그대로 디코딩되면 정당한 예외다(학교알리미 실사례)."""
    repo = _make_repo(tmp_path)
    _add_snapshot(
        repo, "schoolinfo", "학교알리미 공시서비스".encode("euc-kr"), "text/html; charset=euc-kr"
    )
    assert _run(repo) == 0


# ---------------------------------------------------------------------------
# 축별 결함 주입 — 그 축이 없으면 통과해 버리는 입력
# ---------------------------------------------------------------------------


def test_axis_a_replacement_char_is_violation(tmp_path: Path) -> None:
    """A축 — U+FFFD. 면제가 없다(이미 원본 바이트 정보가 사라진 상태)."""
    repo = _make_repo(tmp_path)
    (repo / "damaged.md").write_text(f"안{_FFFD}하세요\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(repo) == 1


def test_axis_a_has_no_allow_marker_escape(tmp_path: Path) -> None:
    """A축은 mojibake 마커로도 면제되지 않는다 — 마커는 C축 전용이다.

    이 절이 없으면 '예시니까 괜찮다'로 진짜 손상이 들어온다.
    """
    repo = _make_repo(tmp_path)
    (repo / "doc.md").write_text(
        f"<!-- {cp949_guard.ALLOW_MARKER} -->\n안{_FFFD}하세요\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    assert _run(repo) == 1


def test_axis_b_undeclared_non_utf8_is_violation(tmp_path: Path) -> None:
    """B축 — 스냅샷 밖의 비-UTF-8 바이트. 저장소 내부는 UTF-8 전용이다."""
    repo = _make_repo(tmp_path)
    (repo / "legacy.txt").write_bytes("한글 테스트입니다".encode("cp949"))
    _git(repo, "add", "-A")
    assert _run(repo) == 1


def test_axis_b_snapshot_without_charset_declaration_is_violation(tmp_path: Path) -> None:
    """B축 — 스냅샷이어도 **선언이 없으면** 예외가 아니다(경로 면제 금지의 집행)."""
    repo = _make_repo(tmp_path)
    _add_snapshot(repo, "nodecl", "한글".encode("cp949"), "text/html")  # charset 없음
    assert _run(repo) == 1


@pytest.mark.parametrize(
    "label,encoding",
    [
        ("cp949 바이트를 latin-1로 읽음(T1)", "cp949"),
        ("UTF-8 바이트를 latin-1로 읽음(T2)", "utf-8"),
    ],
)
def test_axis_c_mojibake_both_directions_are_violations(
    label: str, encoding: str, tmp_path: Path
) -> None:
    """C축 — 두 방향 모두 잡는다. 한 방향만 픽스처에 두면 나머지 절이 살아남는다."""
    repo = _make_repo(tmp_path)
    broken = "안녕하세요 수학 개념".encode(encoding).decode("latin-1")
    (repo / "broken.md").write_text(broken + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(repo) == 1, label


def test_axis_c_allow_marker_permits_documented_examples(tmp_path: Path) -> None:
    """C축 — 마커를 선언한 파일은 통과한다(사례 카탈로그가 예시를 보여 줘야 하므로).

    대조군 역할도 한다: 마커가 *작동하지 않으면* 문서 자체가 상시 위반이 되고
    사람이 가드를 끈다.
    """
    repo = _make_repo(tmp_path)
    broken = "안녕하세요".encode("cp949").decode("latin-1")
    (repo / "catalog.md").write_text(
        f"<!-- {cp949_guard.ALLOW_MARKER} -->\n예시: {broken}\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    assert _run(repo) == 0


def test_marker_mentioned_in_prose_does_not_exempt(tmp_path: Path) -> None:
    """마커를 *언급*만 한 파일은 면제되지 않는다 — 선언이어야 한다.

    발견 경위(2026-09-14): 첫 구현이 단순 substring 검사라, MEMORY.md가 결정 로그에서
    마커명을 인용했다는 이유만으로 **파일 전체가 조용히 면제**됐다. 가드가 스스로
    보고서에 그 파일을 노출한 덕에 발각됐다(그래서 '조용한 면제 금지' 보고가 있다).

    산문 속 언급이 면제가 되면, 이 마커를 설명하는 문서가 늘어날수록 면제 표면이
    저절로 넓어진다 — 아무도 의도하지 않은 채로.
    """
    repo = _make_repo(tmp_path)
    broken = "안녕하세요".encode("cp949").decode("latin-1")
    (repo / "prose.md").write_text(
        f"가드는 `{cp949_guard.ALLOW_MARKER}` 마커로 예외를 인정한다.\n\n{broken}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    assert _run(repo) == 1


@pytest.mark.parametrize(
    "label,line",
    [
        ("markdown 주석", "<!-- encoding-guard: allow-mojibake -->"),
        ("인용문 안 주석", "> <!-- encoding-guard: allow-mojibake — 사유 -->"),
        ("파이썬 주석", "# encoding-guard: allow-mojibake"),
        ("들여쓴 주석", "    # encoding-guard: allow-mojibake"),
    ],
)
def test_marker_declared_at_line_head_exempts(label: str, line: str, tmp_path: Path) -> None:
    """선언 형태 4종은 모두 면제로 인정된다 — 조이다가 정당한 형태를 막으면 안 된다.

    대조군이다: 위 테스트만 있으면 '마커를 아예 무력화'하는 과잉 수정이 통과한다.
    """
    repo = _make_repo(tmp_path)
    broken = "안녕하세요".encode("cp949").decode("latin-1")
    (repo / "catalog2.md").write_text(f"{line}\n\n예시: {broken}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(repo) == 0, label


def test_axis_d_declaration_mismatch_is_violation(tmp_path: Path) -> None:
    """D축 — meta가 선언한 charset으로 디코딩되지 않으면 위반."""
    repo = _make_repo(tmp_path)
    _add_snapshot(repo, "mismatch", "한글".encode("cp949"), "text/html; charset=utf-8")
    assert _run(repo) == 1


def test_axis_d_stale_declaration_on_utf8_body_is_violation(tmp_path: Path) -> None:
    """D축 — 본문은 UTF-8인데 meta가 비-UTF-8을 선언한 경우(선언이 낡았거나 본문이 변환됨).

    증거 스냅샷은 변환 금지이므로 이 상태 자체가 사고 신호다.
    """
    repo = _make_repo(tmp_path)
    _add_snapshot(repo, "converted", "한글".encode("utf-8"), "text/html; charset=euc-kr")
    assert _run(repo) == 1


def test_axis_e_sha256_drift_is_violation(tmp_path: Path) -> None:
    """E축 — 저장된 바이트가 기록된 sha256과 어긋나면 위반(2026-09-14 실사례 5건)."""
    repo = _make_repo(tmp_path)
    html = _add_snapshot(
        repo, "drifted", b"<html>\r\n<body>\r\n</body>\r\n</html>\r\n", "text/html; charset=utf-8"
    )
    html.write_bytes(html.read_bytes().replace(b"\r\n", b"\n"))  # CRLF 정규화 재현
    _git(repo, "add", "-A")
    assert _run(repo) == 1


def test_axis_e_recorded_damage_passes(tmp_path: Path) -> None:
    """E축 — 훼손 사실이 기록돼 있으면 통과한다(복원 불가분 처리).

    무조건 위반으로 두면 고칠 수 없는 위반을 상시 보고해 사람이 가드를 끈다.
    기록 없이 통과시키면 깨진 증거가 멀쩡한 것으로 위장된다. 그 사이를 고정한다.
    """
    repo = _make_repo(tmp_path)
    html = _add_snapshot(repo, "noted", b"<html>\r\n</html>\r\n", "text/html; charset=utf-8")
    html.write_bytes(html.read_bytes().replace(b"\r\n", b"\n"))
    meta_path = html.with_name(html.name.replace(".html", ".meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["stored_sha256"] = hashlib.sha256(html.read_bytes()).hexdigest()
    meta["integrity_note"] = "CRLF 정규화로 훼손 — 혼합 줄바꿈이라 복원 불가"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(repo) == 0


def test_recorded_damage_needs_both_fields(tmp_path: Path) -> None:
    """E축 — `stored_sha256`만 있고 사유가 없으면 통과시키지 않는다.

    해시만 갱신하는 것은 '깨진 것을 정상으로 재정의'하는 것과 같다. 왜 깨졌는지가
    남아야 다음 사람이 판단할 수 있다.
    """
    repo = _make_repo(tmp_path)
    html = _add_snapshot(repo, "halfnoted", b"<html>\r\n</html>\r\n", "text/html; charset=utf-8")
    html.write_bytes(html.read_bytes().replace(b"\r\n", b"\n"))
    meta_path = html.with_name(html.name.replace(".html", ".meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["stored_sha256"] = hashlib.sha256(html.read_bytes()).hexdigest()  # 사유 없음
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _git(repo, "add", "-A")
    assert _run(repo) == 1


# ---------------------------------------------------------------------------
# 측정 실패 — 통과와 구별되어야 한다
# ---------------------------------------------------------------------------


def test_empty_scan_is_measurement_failure_not_pass(tmp_path: Path) -> None:
    """스캔 0건은 exit 2다. 대상을 못 찾은 전수 가드는 공허하게 초록을 낸다."""
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    assert _run(repo) == 2


def test_non_git_directory_is_measurement_failure(tmp_path: Path) -> None:
    """git 저장소가 아니면 exit 2 — '위반 0 통과'로 위장되면 안 된다."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _run(plain) == 2


# ---------------------------------------------------------------------------
# 실 저장소 계약 — 만들어 두고 안 돌아가는 상태 차단
# ---------------------------------------------------------------------------


def test_real_repository_is_clean() -> None:
    """이 저장소 자신이 정합해야 한다 — 가드가 CI에서 낼 판정과 같은 것을 여기서도 낸다."""
    assert cp949_guard.main(["--root", str(_REPO_ROOT)]) == 0


def test_guard_is_wired_into_ci() -> None:
    """CI가 이 가드를 실제로 실행하는가 — '저장소에 존재함'과 '돌아감'은 다르다.

    (CLAUDE.md '검증 장치를 만들고 배선 확인 없이 완료 선언 금지' — 이 부류는 이
    프로젝트에서 반복 발생했다: tests/infra 199건이 어떤 잡도 실행하지 않던 상태 등.)
    """
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "cp949_guard.py" in ci, "가드가 어떤 CI 잡에서도 실행되지 않는다"
