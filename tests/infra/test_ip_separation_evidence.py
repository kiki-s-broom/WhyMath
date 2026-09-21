"""[IP-SEP] 겸직 IP 귀속 증빙 생성기의 계약 동결 — **양방향** 변별력.

왜 이 테스트가 있는가
--------------------
이 도구의 산출물은 **투자 실사에 제출되는 사실 자료**다. 그래서 여기서 가장
비싼 실패는 "틀린 숫자"가 아니라 **"괜찮아 보이는 실패"**다:

  · shallow 클론에서 나온 "혼입 0건"은 잘린 이력에 대한 참일 뿐인데, 리포트에
    실리면 그대로 거짓 진술이 된다.
  · author만 검사하는 신원 검사는 재직사 계정이 committer로만 찍힌 커밋을
    **조용히 통과**시킨다.
  · 오프셋이 섞인 이력에서 현지시각을 그대로 세면 서로 다른 벽시계를 한
    히스토그램에 합치는 셈인데, 그래도 그럴듯한 표가 나온다.

CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"에 따라, 모든
축을 **정상 입력에서 침묵 · 결함 입력에서 발화**하는 쌍으로 동결한다. 결함
주입만 확인하면 *모든* 입력에서 발화하는 검사도 절반은 통과하기 때문이다.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "ip_separation_evidence",
    Path(__file__).resolve().parents[2] / "scripts" / "ops" / "ip_separation_evidence.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # @dataclass 조회 대비 — exec 전 등록
_spec.loader.exec_module(_mod)

Commit = _mod.Commit
classify_identities = _mod.classify_identities
environment_profile = _mod.environment_profile
time_profile = _mod.time_profile
ai_profile = _mod.ai_profile
evaluate_thresholds = _mod.evaluate_thresholds
collect = _mod.collect
parse_coauthors = _mod.parse_coauthors
person_authored = _mod.person_authored
build_scope = _mod.build_scope
looks_like_signed_binary = _mod.looks_like_signed_binary
stream_commits = _mod.stream_commits
EvidenceError = _mod.EvidenceError
DEFAULT_REVS = _mod.DEFAULT_REVS
marker_of = _mod.marker_of
scan_tracked_documents = _mod.scan_tracked_documents
SIGNED_MARKER = _mod.SIGNED_MARKER
TEMPLATE_MARKER = _mod.TEMPLATE_MARKER
render = _mod.render
main = _mod.main
LIMITS = _mod.LIMITS
case_collision_keys = _mod.case_collision_keys
consumption_profile = _mod.consumption_profile
consumption_note = _mod.consumption_note
summary_of = _mod.summary_of
render_summary = _mod.render_summary
summarize_cli = _mod.summarize_cli
DEFAULT_TOOL_IDENTITIES = _mod.DEFAULT_TOOL_IDENTITIES

PERSONAL = {"kiki@example.com"}
TOOL = set(DEFAULT_TOOL_IDENTITIES)


def commit(
    sha: str = "a" * 40,
    *,
    an: str = "kiki",
    ae: str = "kiki@example.com",
    cn: str = "GitHub",
    ce: str = "noreply@github.com",
    ad: str = "2026-03-07T22:10:00+09:00",
    subject: str = "feat: 무언가",
    coauthors=None,
) -> Commit:
    """정상 커밋 — 어떤 신호도 내면 안 되는 기준점."""
    return Commit(sha, an, ae, cn, ce, ad, ad, subject, coauthors or [])


# ── IDENT-01 신원 혼입 ─────────────────────────────────────────────────────
def test_clean_history_is_silent() -> None:
    """정상 침묵 — 개인·도구 신원만 있는 이력에서는 신호가 없어야 한다."""
    _, findings = classify_identities([commit(), commit("b" * 40)], PERSONAL, TOOL)
    assert findings == []


def test_employer_author_fires() -> None:
    """결함 발화 — 재직사 도메인이 author면 IDENT-01."""
    dirty = commit("c" * 40, ae="kiki@employer.co.kr")
    _, findings = classify_identities([commit(), dirty], PERSONAL, TOOL)
    assert [f.code for f in findings] == ["IDENT-01"]
    assert "employer.co.kr" in findings[0].subject
    assert "cccccccccccc" in findings[0].detail


def test_employer_committer_only_fires() -> None:
    """**author만 보는 검사는 이 커밋을 놓친다** — committer 축의 결함 주입.

    이 테스트가 뮤테이션 표적이다: `classify_identities`에서 committer 순회를
    지우면 위 test_employer_author_fires는 여전히 GREEN이고 이것만 RED가 된다.
    """
    dirty = commit("d" * 40, ce="build@employer.co.kr", cn="사내빌드")
    _, findings = classify_identities([dirty], PERSONAL, TOOL)
    assert [f.code for f in findings] == ["IDENT-01"]
    assert findings[0].subject.startswith("committer:")


def test_tool_identity_is_not_foreign() -> None:
    """도구 신원(GitHub 웹 머지 서명 등)은 혼입이 아니다 — 오탐 방어."""
    _, findings = classify_identities([commit()], PERSONAL, TOOL)
    assert findings == []
    _, findings2 = classify_identities([commit()], PERSONAL, set())
    assert [f.code for f in findings2] == ["IDENT-01"]  # 도구 선언을 빼면 잡힌다


def test_identity_matching_is_case_insensitive() -> None:
    """이메일 대소문자 변형으로 검사를 우회할 수 없다."""
    _, findings = classify_identities([commit(ae="KiKi@Example.COM")], PERSONAL, TOOL)
    assert findings == []


def test_findings_carry_a_prescription() -> None:
    """신호에는 사람이 다음에 할 일이 붙는다 — 코드만 던지지 않는다."""
    _, findings = classify_identities([commit(ae="x@employer.co.kr")], PERSONAL, TOOL)
    assert findings[0].prescription


# ── ENV-01 환경 분포 ───────────────────────────────────────────────────────
def test_environment_profile_separates_offsets() -> None:
    """오프셋별로 나뉘어 세어진다 — KST와 그 외가 한 칸에 합쳐지면 안 된다."""
    env = environment_profile(
        [
            commit(ad="2026-03-07T22:10:00+09:00"),
            commit(ad="2026-03-07T09:10:00-04:00"),
            commit(ad="2026-03-07T13:10:00+00:00"),
        ]
    )
    assert env["by_author_utc_offset"] == {"+09:00": 1, "-04:00": 1, "+00:00": 1}
    assert env["local_kst_commits"] == 1
    assert env["non_kst_commits"] == 2


# ── TIME-01 시각 분포 ──────────────────────────────────────────────────────
def test_time_profile_converts_everything_to_kst() -> None:
    """**모든 커밋을 KST로 환산**한다 — 현지시각을 그대로 세면 안 된다.

    결함 주입 표적: `.astimezone(KST)`를 빼면 아래 -04:00 커밋이 09시로 세어져
    업무시간 1건이 된다(정답은 22시·업무시간 0건).
    """
    tp = time_profile([commit(ad="2026-03-07T09:10:00-04:00")])  # = 2026-03-07 22:10 KST
    assert tp["by_hour_kst"]["22"] == 1
    assert tp["work_hours_commits"] == 0


def test_work_hours_counts_weekday_business_hours() -> None:
    """정상 발화 — 평일 낮 커밋은 업무시간으로 센다."""
    tp = time_profile([commit(ad="2026-03-05T14:00:00+09:00")])  # 목요일
    assert tp["work_hours_commits"] == 1
    assert tp["work_hours_ratio"] == 1.0


def test_weekend_daytime_is_not_work_hours() -> None:
    """주말 낮은 업무시간이 아니다 — 요일 조건의 결함 주입 표적."""
    tp = time_profile([commit(ad="2026-03-07T14:00:00+09:00")])  # 토요일
    assert tp["work_hours_commits"] == 0
    assert tp["off_hours_commits"] == 1


def test_work_hours_boundaries_are_half_open() -> None:
    """09:00은 포함, 18:00은 제외 — 경계 정의를 못박는다."""
    tp = time_profile(
        [
            commit(ad="2026-03-05T09:00:00+09:00"),
            commit(ad="2026-03-05T18:00:00+09:00"),
        ]
    )
    assert tp["work_hours_commits"] == 1


def test_threshold_absent_is_silent() -> None:
    """임계를 주지 않으면 판정하지 않는다 — 임의의 기본 임계를 두지 않는다."""
    tp = time_profile([commit(ad="2026-03-05T14:00:00+09:00")])
    assert evaluate_thresholds(tp, work_hours_threshold=None) == []


def test_threshold_given_fires_above_and_stays_silent_below() -> None:
    """임계를 준 사람에게만, 그리고 **넘었을 때만** 신호가 간다 — 양방향."""
    tp = time_profile([commit(ad="2026-03-05T14:00:00+09:00")])  # 비율 1.0
    assert [f.code for f in evaluate_thresholds(tp, work_hours_threshold=0.5)] == ["TIME-01"]
    assert evaluate_thresholds(tp, work_hours_threshold=1.0) == []


# ── AI-01 ─────────────────────────────────────────────────────────────────
def test_ai_profile_counts_tool_authored_commits() -> None:
    """AI 저작 커밋은 별도로 센다 — 판정이 아니라 실사 대비 사실 자료다."""
    prof = ai_profile([commit(), commit("e" * 40, an="Claude", ae="noreply@anthropic.com")], TOOL)
    assert prof["tool_authored_commits"] == 1
    assert prof["tool_involved_ratio"] == 0.5


# ── 렌더 계약 ──────────────────────────────────────────────────────────────
def test_limits_are_always_rendered() -> None:
    """증명 한계는 **옵션이 아니다** — 정상 리포트에도 항상 실린다.

    이 도구의 산출물을 읽는 사람은 git 메타데이터의 증명력을 과대평가하기 쉽다.
    한계 문단이 조건부가 되면 가장 좋은 리포트에서 가장 먼저 사라진다.
    """
    report = _mod.Report(
        status="ok",
        total_commits=1,
        identities={
            "declared_personal": ["kiki@example.com"],
            "declared_tool": [],
            "by_author": {"kiki <kiki@example.com>": 1},
            "by_committer": {"kiki <kiki@example.com>": 1},
            "foreign_identities": {},
        },
        environments=environment_profile([commit()]),
        time_profile=time_profile([commit()]),
        ai_profile=ai_profile([commit()], TOOL),
    )
    text = render(report)
    assert "증명하지 **못하는** 것" in text
    for limit in LIMITS:
        assert limit.split("—")[0].strip()[:20] in text


def test_failed_report_refuses_to_look_like_evidence() -> None:
    """수집 실패 리포트는 표를 그리지 않고 사용 금지를 명시한다."""
    text = render(_mod.Report(status="shallow", message="shallow 클론"))
    assert "수집 실패" in text
    assert "증빙으로 쓰지 말" in text
    assert "혼입" not in text  # 판정처럼 읽히는 문구가 새어 나오면 안 된다


# ── 수집 실패 경로 (실제 git 저장소) ────────────────────────────────────────
def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """커밋 2건짜리 실 저장소 — 개인 신원 1건 + 도구 신원 1건."""
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "kiki")
    _git(root, "config", "user.email", "kiki@example.com")
    # 개발자 머신의 전역 설정이 이 fixture를 깨지 않게 한다 — 서명 키가 없는 곳에서
    # commit.gpgsign=true면 커밋 자체가 실패하고, 그 실패는 이 도구와 무관하다.
    _git(root, "config", "commit.gpgsign", "false")
    for i in (1, 2):
        (root / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        _git(root, "add", ".")
        _git(
            root,
            "-c",
            f"user.date=2026-03-0{i}T22:00:00+09:00",
            "commit",
            "-q",
            "--date",
            f"2026-03-0{i}T22:00:00+09:00",
            "-m",
            f"커밋 {i}",
        )
    return root


def test_shallow_clone_is_not_ok(repo: Path, tmp_path: Path) -> None:
    """**측정 실패 ≠ 통과** — 잘린 이력의 '혼입 0건'을 증빙으로 내보내지 않는다.

    이 계약이 이 파일에서 가장 중요하다. shallow에서 status=ok가 나오면 리포트는
    사실과 무관하게 깨끗해 보이고, 그 리포트가 실사에 제출된다.
    """
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", "-q", repo.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
    )
    report = collect(shallow, personal=PERSONAL, tool=TOOL)
    assert report.status == "shallow"
    assert report.total_commits == 0
    assert "unshallow" in report.message
    assert main(["--root", str(shallow), "--identity", "kiki@example.com"]) == 2


def test_missing_identity_declaration_is_not_ok(repo: Path) -> None:
    """개인 신원을 선언하지 않으면 혼입 판정이 성립하지 않는다 — exit 2.

    빈 allowlist로 돌리면 **모든 신원이 혼입**으로 잡혀 리포트가 무의미해진다.
    그 상태를 exit 1(신호 있음)로 내면 '검사했다'처럼 읽힌다.
    """
    report = collect(repo, personal=set(), tool=TOOL)
    assert report.status == "error"
    assert "--identity" in report.message
    assert main(["--root", str(repo)]) == 2


def test_zero_commits_is_failure_not_pass(repo: Path) -> None:
    """스캔 0건은 성공이 아니다 — 공허하게 통과하는 전수 가드 방지."""
    report = collect(repo, personal=PERSONAL, tool=TOOL, since="2030-01-01")
    assert report.status == "error"
    assert "0건" in report.message
    assert (
        main(["--root", str(repo), "--identity", "kiki@example.com", "--since", "2030-01-01"]) == 2
    )


def test_not_a_git_repo_names_the_exception_type(tmp_path: Path) -> None:
    """침묵 실패 금지 — 실패 메시지에 **예외 타입명**이 들어간다."""
    plain = tmp_path / "plain"
    plain.mkdir()
    report = collect(plain, personal=PERSONAL, tool=TOOL)
    assert report.status == "error"
    assert "GitExitError" in report.message or "Error" in report.message


# ── 증거 보존 (③ 실패해도 증거가 남는다) ────────────────────────────────────
def test_jsonl_records_every_commit(repo: Path, tmp_path: Path) -> None:
    """커밋 1건마다 즉시 flush — 도중에 죽어도 그 시점까지가 남는다."""
    sink = tmp_path / "nested" / "commits.jsonl"  # 부모 디렉터리도 만들어야 한다
    report = collect(repo, personal=PERSONAL, tool=TOOL, jsonl=sink)
    assert report.status == "ok"
    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == report.total_commits == 2
    assert json.loads(lines[0])["author_email"] == "kiki@example.com"


def test_jsonl_is_flushed_before_the_run_finishes(repo: Path, tmp_path: Path) -> None:
    """**즉시** flush인지 확인한다 — 파일을 닫을 때 한꺼번에 쓰는 것과 구별한다.

    `sink.flush()`만 지우면 파일은 결국 close 시점에 채워지므로, 끝난 뒤에 줄 수만
    세는 검사는 정상/결함 양쪽에서 같은 값을 낸다("변별력 없는 검증 스텝 금지").
    그래서 제너레이터를 **1건에서 멈춘 채** 파일을 읽는다.
    """
    sink = tmp_path / "partial.jsonl"
    gen = _mod.stream_commits(repo, jsonl=sink)
    try:
        next(gen)  # 커밋 1건만 소비하고 멈춘다
        assert len(sink.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        gen.close()


def test_out_dir_writes_both_formats(repo: Path, tmp_path: Path) -> None:
    """실사 제출용 JSON + Markdown 한 쌍을 남긴다."""
    out = tmp_path / "out"
    assert main(["--root", str(repo), "--identity", "kiki@example.com", "--out", str(out)]) == 0
    payload = json.loads((out / "ip_separation_evidence.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["limits"] == LIMITS  # 한계는 기계 판독 산출물에도 실린다
    assert "IP 귀속 분리 증빙" in (out / "ip_separation_evidence.md").read_text(encoding="utf-8")


def test_exit_code_separates_clean_from_foreign(repo: Path) -> None:
    """판정은 exit code로 한다 — 출력 문자열 매칭이 아니다(양방향)."""
    assert main(["--root", str(repo), "--identity", "kiki@example.com"]) == 0
    # 개인 신원 선언을 다른 사람으로 바꾸면 같은 이력이 전부 혼입이 된다
    assert main(["--root", str(repo), "--identity", "other@example.com"]) == 1


# ── 서명 실물 유출 가드 ────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[2]


def test_marker_is_the_whole_first_line() -> None:
    """마커는 **첫 줄 전체**다 — 본문에 인용한 문서가 위반으로 잡히면 안 된다.

    이 가드를 "이 문자열이 어디든 있으면 위반"으로 만들면 마커를 *설명하는*
    런북·템플릿 주의문이 전부 걸리고, 그 오탐을 피하려 예외를 넣는 순간 가드가
    스스로 구멍이 된다. 그래서 위치를 계약으로 삼는다(양방향).
    """
    assert marker_of(SIGNED_MARKER) == "signed"
    assert marker_of(f"  {SIGNED_MARKER}  \n") == "signed"  # 공백은 허용
    assert marker_of(TEMPLATE_MARKER) == "template"
    assert marker_of(f"이 문서의 실물은 `{SIGNED_MARKER}` 로 표시한다") is None
    assert marker_of("# 제목") is None


def test_no_signed_document_is_tracked() -> None:
    """**기입·서명된 실물이 저장소에 커밋되지 않았다.**

    `.gitignore`는 `git add -f` 한 번이면 뚫린다 — 이 검사가 2차 방어다.
    """
    found = scan_tracked_documents(_REPO)
    assert found["signed"] == [], f"서명 실물이 추적되고 있다: {found['signed']}"
    assert found.get("unreadable", []) == []


def test_marker_scan_actually_walks_the_tree() -> None:
    """**스캔 0건은 실패다** — 대상을 못 찾은 전수 가드는 공허하게 통과한다.

    위 검사가 초록인 이유가 "서명 실물이 없어서"인지 "아무것도 안 훑어서"인지
    구별하는 유일한 축이다. 템플릿 2건이 잡히면 스캐너가 실제로 돈 것이다.
    """
    found = scan_tracked_documents(_REPO)
    assert len(found["template"]) >= 2, f"템플릿을 못 찾았다 — 스캐너 무효: {found}"
    assert all(f.startswith("docs/legal/templates/") for f in found["template"])


def test_evidence_outputs_are_gitignored() -> None:
    """산출물 경로가 **실제로** 무시되는지 git에게 직접 묻는다.

    `.gitignore`에 줄이 있는지 문자열로 확인하지 않는다 — 규칙은 순서·부정
    패턴·상위 규칙에 따라 뒤집힐 수 있고, 그 결과는 git만 안다(산출물 검사).
    """

    def ignored(rel: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", rel], cwd=_REPO, capture_output=True
            ).returncode
            == 0
        )

    assert ignored(".ip_evidence/ip_separation_evidence.json")
    assert ignored("docs/private/ip/declaration.md")
    # 반대 방향 — 정본 템플릿까지 무시되면 가드가 아니라 사고다
    assert not ignored("docs/legal/templates/no_employer_assets_declaration_ko.md")


# ── Co-Authored-By 트레일러 (2026-09-07 리뷰 P2) ────────────────────────────
def test_parse_coauthors_reads_trailers() -> None:
    """본문의 `Co-Authored-By`를 (이름, 이메일)로 뽑는다 — 대소문자 무관."""
    body = (
        "본문 한 줄\n\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n"
        "co-authored-by: 동료 <peer@example.com>\n"
    )
    assert parse_coauthors(body) == [
        ["Claude", "noreply@anthropic.com"],
        ["동료", "peer@example.com"],
    ]


def test_parse_coauthors_is_silent_without_trailers() -> None:
    """정상 침묵 — 트레일러가 없으면 빈 목록."""
    assert parse_coauthors("그냥 본문\nSigned-off-by: x <x@y.z>\n") == []


def test_coauthor_identity_is_scanned() -> None:
    """**공동저작자도 신원 검사를 받는다** — 잠재적 공동 권리자이기 때문이다.

    결함 주입 표적: `classify_identities`에서 coauthor 순회를 지우면 이 테스트만
    RED가 되고 author/committer 테스트는 그대로 GREEN이다.
    """
    c = commit(coauthors=[["사내동료", "peer@employer.co.kr"]])
    _, findings = classify_identities([c], PERSONAL, TOOL)
    assert [f.code for f in findings] == ["IDENT-01"]
    assert findings[0].subject.startswith("coauthor:")


def test_ai_profile_counts_coauthored_not_only_authored() -> None:
    """AI 관여는 author만 세면 크게 빗나간다 (실측 25 vs 998).

    이 저장소의 관례는 사람이 author이고 AI가 트레일러로 들어가는 형태다.
    """
    human_with_ai = commit(coauthors=[["Claude", "noreply@anthropic.com"]])
    ai_authored = commit("f" * 40, an="Claude", ae="noreply@anthropic.com")
    prof = ai_profile([human_with_ai, ai_authored, commit("0" * 40)], TOOL)
    assert prof["tool_authored_commits"] == 1
    assert prof["tool_coauthored_commits"] == 1
    assert prof["tool_involved_commits"] == 2  # 합집합


# ── 시각 분포의 모집단 (사람 저작) ──────────────────────────────────────────
def test_person_authored_excludes_tool_commits() -> None:
    """봇이 커밋한 시각은 사람이 일한 시각이 아니다 — 모집단에서 뺀다."""
    bot = commit("1" * 40, an="whymath-harness", ae="harness@whymath.invalid")
    people = person_authored([commit(), bot], TOOL)
    assert [c.sha for c in people] == ["a" * 40]


def test_harness_bot_is_a_tool_not_a_foreign_identity() -> None:
    """하네스 봇은 사람이 아니다 — 기본 도구 신원에 들어 있다.

    실측 근거: 이 신원의 932건은 전부 `harness-claims`(claim 대장 orphan 브랜치)에만
    있고 트리는 `claims/` 하나뿐이다. 다만 **숨기지는 않는다** — 신원 표에 실린다.
    """
    assert "harness@whymath.invalid" in DEFAULT_TOOL_IDENTITIES
    bot = commit("2" * 40, an="whymath-harness", ae="harness@whymath.invalid")
    profile, findings = classify_identities([bot], PERSONAL, TOOL)
    assert findings == []
    assert "whymath-harness <harness@whymath.invalid>" in profile["by_author"]


# ── 스캔 범위 (2026-09-07 리뷰 P1·P2) ──────────────────────────────────────
def test_default_scope_is_all_refs() -> None:
    """기본 범위는 HEAD가 아니라 모든 ref다 — HEAD만 보면 44%만 본다(실측)."""
    assert tuple(DEFAULT_REVS) == ("--all",)


def test_scope_marks_full_history_only_when_unfiltered() -> None:
    """전수/부분을 양방향으로 구분한다 — 부분인데 전수로 표시되면 거짓 진술이다."""
    assert build_scope(["--all"], None, refs=3, scanned=9)["is_full_history"] is True
    assert build_scope(["HEAD"], None, refs=3, scanned=9)["is_full_history"] is False
    assert build_scope(["--all"], "2026-01-01", refs=3, scanned=9)["is_full_history"] is False


def test_unreachable_commit_is_scanned(repo: Path) -> None:
    """**HEAD에서 도달할 수 없는 커밋도 검사한다.**

    이 파일에서 `test_shallow_clone_is_not_ok` 다음으로 중요한 계약이다. 초판은
    `git log HEAD`만 순회해 미머지 브랜치의 커밋을 통째로 놓쳤고, 이 저장소
    실측으로 2297건 중 1279건(56%)이 그 사각에 있었다 — 그 커밋에 재직사 신원이
    있어도 리포트는 "혼입 0건"이라고 선언했을 것이다.
    """
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=stranger@employer.co.kr", "commit", "-q", "-m", "곁가지")
    _git(repo, "checkout", "-q", "main")

    # HEAD만 보면 침묵한다 — 이것이 초판의 상태다
    head_only = collect(repo, personal=PERSONAL, tool=TOOL, revs=("HEAD",))
    assert head_only.findings == []
    assert head_only.scope["is_full_history"] is False
    assert head_only.unmeasured  # 부분 측정임을 스스로 말한다

    # 기본(모든 ref)이면 잡는다
    full = collect(repo, personal=PERSONAL, tool=TOOL)
    # `-c user.email`은 author·committer 둘 다 바꾸므로 역할별로 2건이 정상이다.
    assert {f.code for f in full.findings} == {"IDENT-01"}
    roles = sorted(f.subject.split(":", 1)[0] for f in full.findings)
    assert roles == ["author", "committer"]
    assert all("employer.co.kr" in f.subject for f in full.findings)
    assert full.scope["is_full_history"] is True
    assert full.unmeasured == []


def test_partial_scope_report_refuses_full_history_wording(repo: Path) -> None:
    """부분 범위 리포트는 '이력 전체'라고 말하지 않는다."""
    partial = collect(repo, personal=PERSONAL, tool=TOOL, revs=("HEAD",))
    text = render(partial)
    assert "부분 측정" in text
    assert "스캔한" in text


# ── 타임아웃 집행 (2026-09-07 리뷰 P2) ─────────────────────────────────────
def test_timeout_fires_even_when_read_blocks(repo: Path, monkeypatch) -> None:
    """**블로킹 read 안에서 멈춰도** 타임아웃이 걸린다.

    초판은 `proc.stdout.read()`가 반환된 **뒤에만** deadline을 봤다. git이 출력
    없이 정지하면 그 검사 지점에 영영 도달하지 못해, 선언한 300초가 장식이 된다.
    watchdog 스레드가 프로세스를 죽여야 read가 풀린다.
    """
    released = threading.Event()

    class _BlockingStdout:
        closed = False

        def read(self, _n):
            released.wait(10)  # kill()이 풀어 준다 — 안 풀리면 테스트가 실패한다
            return ""

        def close(self):
            # 실물 파이프를 충실히 흉내낸다 — `_reap`이 종료 경로에서 닫는다.
            self.closed = True

    class _FakeProc:
        stdout = _BlockingStdout()
        returncode = -9

        def kill(self):
            released.set()

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
    with pytest.raises(EvidenceError) as excinfo:
        list(stream_commits(repo, timeout=0.05))
    assert "TimeoutExpired" in str(excinfo.value)
    assert released.is_set()  # watchdog이 실제로 kill했다
    assert _FakeProc.stdout.closed  # 종료 경로가 stdout까지 닫았다


# ── 서명 스캔본 가드 (2026-09-07 리뷰 P2) ──────────────────────────────────
def test_signed_scan_is_detected_by_name_and_location() -> None:
    """서명 **스캔본**(PDF·이미지)은 첫 줄을 읽을 수 없다 — 이름과 위치로 본다."""
    assert looks_like_signed_binary("docs/legal/재직사자산무사용확인서.pdf")
    assert looks_like_signed_binary("anywhere/IP양도예정기록.jpg")
    assert looks_like_signed_binary("docs/legal/scan001.pdf")


def test_signed_scan_guard_does_not_overfire() -> None:
    """정상 침묵 — 정본 템플릿·일반 문서·다른 경로의 자산은 잡지 않는다."""
    assert (
        looks_like_signed_binary("docs/legal/templates/no_employer_assets_declaration_ko.md")
        is None
    )
    assert looks_like_signed_binary("docs/legal/copyright_guide_v2.md") is None
    assert looks_like_signed_binary("assets/logo.png") is None  # 법무 경로가 아니다


def test_no_signed_scan_is_tracked() -> None:
    """서명 스캔본이 저장소에 커밋되지 않았다 — 마커 스캔의 바이너리 축."""
    found = scan_tracked_documents(_REPO)
    assert found["signed_binary"] == [], f"서명 스캔본 의심: {found['signed_binary']}"


# ── mailmap 우회 (2026-09-07 재리뷰 P1) ────────────────────────────────────
def test_mailmap_does_not_hide_employer_identity(repo: Path, tmp_path: Path) -> None:
    """**`.mailmap`이 재직사 신원을 개인 신원으로 가리지 못한다.**

    이 파일에서 `test_shallow_clone_is_not_ok`·`test_unreachable_commit_is_scanned`와
    같은 급의 계약이다. git의 `%aE`(대문자)는 `.mailmap`이 **적용된** 이메일을
    내므로, 저장소에 다음 한 줄만 있으면 재직사 커밋이 개인 이메일로 보인다:

        개인 <kiki@example.com> 사내계정 <worker@employer.co.kr>

    그 상태에서 IDENT-01은 신호 없이 exit 0을 낸다 — 귀속 증빙 도구가 정확히
    잡아야 할 것을 못 보는 것이다. 원본은 소문자 `%ae`/`%ce`로만 나온다.

    결함 주입 표적: `_FIELDS`의 `%ae`→`%aE`(또는 `%ce`→`%cE`)로 되돌리면
    이 테스트만 RED가 되고 나머지는 전부 GREEN이다.
    """
    # 재직사 신원으로 커밋한다
    (repo / "corp.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=사내계정",
        "-c",
        "user.email=worker@employer.co.kr",
        "commit",
        "-q",
        "-m",
        "재직사 계정 커밋",
    )
    # 그 신원을 개인 신원으로 매핑하는 .mailmap을 심는다
    (repo / ".mailmap").write_text(
        "개인 <kiki@example.com> 사내계정 <worker@employer.co.kr>\n", encoding="utf-8"
    )
    _git(repo, "add", ".mailmap")
    _git(repo, "commit", "-q", "-m", "mailmap")

    # 전제 확인 — 이 환경의 git이 실제로 mailmap을 적용하는가(변별력 확보).
    mapped = _mod._git(repo, "log", "--format=%aE", "-n", "3")
    raw = _mod._git(repo, "log", "--format=%ae", "-n", "3")
    assert mapped != raw, "이 git이 mailmap을 적용하지 않는다 — 테스트가 무효다"

    report = collect(repo, personal=PERSONAL, tool=TOOL)
    assert report.status == "ok"
    assert [f.code for f in report.findings] == ["IDENT-01"] * len(report.findings)

    # **두 축을 각각 못박는다.** "1건 이상"으로만 단언하면 author·committer 중
    # 한쪽만 mailmap 포맷으로 되돌려도 나머지가 발화해 통과한다 — 실제로 첫 판에
    # M27·M28이 그렇게 살아남았다(CLAUDE.md '픽스처가 그 절을 실제로 밟는가').
    roles = {f.subject.split(":", 1)[0] for f in report.findings if "employer.co.kr" in f.subject}
    assert roles == {"author", "committer"}, f"mailmap에 가려 놓친 축이 있다: {roles}"


# ── 자식 프로세스 수거 (2026-09-07 재리뷰 P2) ──────────────────────────────
def test_early_close_reaps_the_child(repo: Path) -> None:
    """조기 `close()`에서도 자식을 **kill 후 wait까지** 한다 — zombie 방지.

    `kill()`만 하고 `wait()`하지 않으면 POSIX에서 자식이 zombie로 남고 종료
    자체도 확정되지 않는다. `poll()`이 None이 아니면 수거가 끝난 것이다.
    """
    captured = {}
    real_popen = _mod.subprocess.Popen

    def _spy(*a, **k):
        proc = real_popen(*a, **k)
        captured["proc"] = proc
        captured["waited"] = False
        real_wait = proc.wait

        def _wait(timeout=None):
            captured["waited"] = True
            return real_wait(timeout=timeout)

        proc.wait = _wait
        return proc

    _mod.subprocess.Popen = _spy
    try:
        gen = stream_commits(repo)
        next(gen)
        gen.close()
    finally:
        _mod.subprocess.Popen = real_popen

    proc = captured["proc"]
    # **`poll()`만으로는 변별력이 없다** — `poll()`은 스스로 `waitpid(WNOHANG)`을
    # 불러 zombie를 거두므로, wait를 지운 코드에서도 None이 아닌 값을 낸다.
    # 첫 판에 M29가 그렇게 살아남았다. 계약은 "종료 경로가 자식을 거둔다"이고
    # 파이썬에서 그 수단은 `wait()`이므로, 호출 자체를 못박는다.
    assert captured["waited"], "종료 경로가 wait()를 부르지 않았다 — zombie로 남는다"
    assert proc.poll() is not None, "자식이 종료되지 않았다"


# ── 산출물 저장 실패 (2026-09-07 재리뷰 P2) ────────────────────────────────
def test_out_write_failure_is_exit_2_not_1(repo: Path, tmp_path: Path) -> None:
    """저장 실패는 **exit 2**다 — exit 1(혼입 발견)로 오분류되면 안 된다.

    `--out`이 기존 *일반 파일*이면 `mkdir`이 `NotADirectoryError`(OSError)를 내는데,
    잡지 않으면 파이썬이 exit 1을 낸다. 이 CLI에서 1은 "수집 성공 · 혼입 발견"으로
    예약된 값이라, 디스크·권한 문제가 신원 혼입으로 보이게 된다.
    """
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("나는 파일이다", encoding="utf-8")
    code = main(["--root", str(repo), "--identity", "kiki@example.com", "--out", str(blocker)])
    assert code == 2, f"저장 실패가 exit {code} — 2여야 한다"


# ── CONSUME-01 · 리포트를 소비자가 읽을 수 있는가 ─────────────────────────
#
# 2026-09-08 라이브 실측에서 이 도구는 리포트를 **잘 만들었는데 런북이 읽지
# 못했다**. Windows PowerShell 5.1의 `ConvertFrom-Json`이 대소문자만 다른
# 신원 키를 중복으로 보고 거부했고, 그 실패 화면에 `FOREIGN=0종`이 찍혀
# "혼입 없음"처럼 읽혔다. 아래 축은 그 두 가지를 각각 동결한다.


def _report_payload(**over) -> dict:
    """정상 리포트 payload — 각 테스트가 필요한 필드만 뒤집는다."""
    payload = {
        "status": "ok",
        "total_commits": 2621,
        "head_sha": "6259f8be40ae7f83345c7e7740b7718ec4727d44",
        "scope": {
            "description": "저장소의 모든 ref(129개) 전수",
            "is_full_history": True,
            "person_authored": 1132,
        },
        "identities": {"foreign_identities": {}},
        "time_profile": {"work_hours_ratio": 0.348},
        "findings": [],
    }
    payload.update(over)
    return payload


def test_case_collision_is_silent_on_distinct_keys() -> None:
    """정상 입력에서 침묵 — 모든 입력에서 발화하는 검출기가 아니다."""
    assert case_collision_keys({"a": {"Claude <x@y>": 1, "Sonnet <z@y>": 2}}) == []


def test_case_collision_finds_the_live_pair() -> None:
    """실측 그대로의 쌍을 잡는다 — 이 쌍이 PowerShell 파싱을 무너뜨렸다."""
    hits = case_collision_keys(
        {
            "identities": {
                "by_coauthor": {
                    "Claude <noreply@anthropic.com>": 702,
                    "claude <noreply@anthropic.com>": 1,
                }
            }
        }
    )
    assert len(hits) == 1
    assert "identities.by_coauthor" in hits[0]
    assert "Claude <noreply@anthropic.com>" in hits[0]
    assert "claude <noreply@anthropic.com>" in hits[0]


def test_case_collision_walks_nested_lists() -> None:
    """리스트 안의 객체도 본다 — findings 배열에 숨으면 못 보는 검출기는 공허하다."""
    hits = case_collision_keys({"findings": [{"A": 1, "a": 2}]})
    assert len(hits) == 1 and "findings[0]" in hits[0]


def test_consumption_profile_declares_unsafe_when_colliding() -> None:
    """리포트가 자신의 소비 가능성을 **스스로** 말한다."""
    unsafe = consumption_profile({"x": {"Claude <a@b>": 1, "claude <a@b>": 2}})
    assert unsafe["powershell_convertfrom_json_safe"] is False
    assert unsafe["case_collision_keys"]
    assert "--summary-from" in unsafe["safe_consumption"]

    safe = consumption_profile({"x": {"Claude <a@b>": 1}})
    assert safe["powershell_convertfrom_json_safe"] is True
    assert safe["case_collision_keys"] == []


def test_consumption_note_names_the_parser_and_the_way_out() -> None:
    note = consumption_note(["identities.by_coauthor: Claude <a@b> ~ claude <a@b>"])
    assert "ConvertFrom-Json" in note
    assert "--summary-from" in note


def test_summary_of_clean_report_is_clear_ready() -> None:
    fields, blockers = summary_of(
        _report_payload(), expect_head="6259f8be40ae7f83345c7e7740b7718ec4727d44"
    )
    assert blockers == []
    assert fields["CLEAR_READY"] == "1"
    assert fields["SAME_HEAD"] == "1"
    assert fields["COMMITS"] == "2621"
    assert fields["FULL"] == "1"
    assert fields["FOREIGN"] == "0"


@pytest.mark.parametrize(
    "over, marker",
    [
        ({"status": "shallow"}, "status=shallow"),
        ({"total_commits": 0}, "commits=0"),
        (
            {"scope": {"description": "HEAD만", "is_full_history": False}},
            "full_history=false",
        ),
    ],
)
def test_summary_of_blocks_each_failure_mode(over, marker) -> None:
    """결함 주입 — 축마다 **그 축이 없으면 통과할 입력**으로 RED를 확인한다."""
    fields, blockers = summary_of(_report_payload(**over))
    assert fields["CLEAR_READY"] == "0"
    assert any(marker in b for b in blockers), blockers
    assert marker in fields["CLEAR_BLOCKERS"]


def test_foreign_identity_blocks_clear() -> None:
    """혼입이 있으면 기계가 clear하지 못한다 (2026-09-08 Codex P1).

    이 축이 없으면 생성 명령이 exit 1을 낸 리포트로도 요약이 exit 0을 내
    게이트가 닫힌다 — **재직사 계정이 이력에 있는 채로** "귀속 분리 증빙 확보"가
    선언된다. 혼입이 오분류였을 때의 해소 경로는 게이트 통과가 아니라 그 신원을
    `--identity`로 선언하고 다시 재는 것이다.
    """
    fields, blockers = summary_of(
        _report_payload(
            identities={"foreign_identities": {"author:kiki <kiki@employer.co.kr>": 3}},
            findings=[{"code": "IDENT-01", "subject": "author:kiki <kiki@employer.co.kr>"}],
        )
    )
    assert fields["FOREIGN"] == "1"
    assert fields["CLEAR_READY"] == "0"
    assert "foreign_identities=1" in fields["CLEAR_BLOCKERS"]
    assert any("foreign_identities" in b for b in blockers)


def test_non_ident_finding_also_blocks_clear() -> None:
    """혼입 말고도 생성이 exit 1을 내는 축(임계 초과)이 있다 — 그것도 막는다."""
    fields, _ = summary_of(
        _report_payload(findings=[{"code": "TIME-01", "subject": "업무시간 비율"}])
    )
    assert fields["CLEAR_READY"] == "0"
    assert "TIME-01" in fields["CLEAR_BLOCKERS"]


def test_ident_finding_is_not_counted_twice() -> None:
    """IDENT-01은 foreign 축이 이미 이름을 붙였다 — 같은 사실을 두 번 세지 않는다."""
    fields, blockers = summary_of(
        _report_payload(
            identities={"foreign_identities": {"author:x <x@e.co>": 1}},
            findings=[{"code": "IDENT-01", "subject": "author:x <x@e.co>"}],
        )
    )
    assert blockers == ["foreign_identities=1"]
    assert "findings=" not in fields["CLEAR_BLOCKERS"]


def test_summary_cli_exit_1_on_foreign_identity(tmp_path: Path, capsys) -> None:
    """CLI 축 — 런북의 $EvidenceOk가 이 exit code로 판정하므로 여기서 새야 한다."""
    report = tmp_path / "foreign.json"
    report.write_text(
        json.dumps(
            _report_payload(
                identities={"foreign_identities": {"author:kiki <kiki@employer.co.kr>": 3}},
                findings=[{"code": "IDENT-01", "subject": "author:kiki <kiki@employer.co.kr>"}],
            )
        ),
        encoding="utf-8",
    )
    code = main(
        ["--summary-from", str(report), "--expect-head", "6259f8be40ae7f83345c7e7740b7718ec4727d44"]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "CLEAR_READY=0" in out
    assert "foreign_identities=1" in out


def test_summary_of_blocks_stale_report() -> None:
    """리포트가 **다른 시점**을 잰 것이면 막는다 — 이 축이 없으면 과거 측정으로 게이트가 닫힌다."""
    fields, _ = summary_of(_report_payload(), expect_head="a" * 40)
    assert fields["SAME_HEAD"] == "0"
    assert fields["CLEAR_READY"] == "0"
    assert "head_mismatch" in fields["CLEAR_BLOCKERS"]


def test_short_sha_is_accepted_but_too_short_is_not() -> None:
    """짧은 sha는 받되 7자 미만은 비교로 치지 않는다 — 우연 일치로 통과하면 안 된다."""
    ok, _ = summary_of(_report_payload(), expect_head="6259f8be")
    assert ok["SAME_HEAD"] == "1"
    coincidence, _ = summary_of(_report_payload(), expect_head="6259")
    assert coincidence["SAME_HEAD"] == "0"


def test_summary_values_never_span_lines() -> None:
    """KEY=VALUE 파서가 무너지지 않게 — 줄바꿈이 섞인 설명도 한 줄로 접는다."""
    fields, _ = summary_of(
        _report_payload(scope={"description": "여러\n줄\n설명", "is_full_history": True})
    )
    text = render_summary(fields)
    assert len(text.splitlines()) == len(fields)
    assert "SCOPE=여러 줄 설명" in text


def test_summary_cli_reads_a_report_powershell_would_reject(tmp_path: Path, capsys) -> None:
    """**이 테스트가 이 태스크의 본체다** — 실측 실패를 그대로 재현한 입력을 읽어낸다."""
    payload = _report_payload(
        identities={
            "by_coauthor": {
                "Claude <noreply@anthropic.com>": 702,
                "claude <noreply@anthropic.com>": 1,
            },
            "foreign_identities": {},
        }
    )
    report = tmp_path / "ip_separation_evidence.json"
    report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code = main(["--summary-from", str(report), "--expect-head", payload["head_sha"]])
    out = capsys.readouterr().out
    assert code == 0
    assert "SUMMARY_OK=1" in out
    assert "CLEAR_READY=1" in out
    assert "CASE_COLLISIONS=1" in out  # 충돌은 감춰지지 않는다


def test_summary_cli_missing_file_emits_no_values(tmp_path: Path, capsys) -> None:
    """실패는 값으로 위장되지 않는다 — `FOREIGN=0`이 실패 화면에 찍히면 '이상 없음'으로 읽힌다."""
    code = main(["--summary-from", str(tmp_path / "없음.json")])
    out = capsys.readouterr().out
    assert code == 2
    assert "SUMMARY_OK=0" in out
    assert "FileNotFoundError" in out  # 예외 타입명 — 침묵 실패 금지
    for forbidden in ("FOREIGN=", "CLEAR_READY=", "STATUS=", "COMMITS="):
        assert forbidden not in out


def test_summary_cli_broken_json_names_the_exception(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"status": "ok",', encoding="utf-8")
    code = main(["--summary-from", str(broken)])
    out = capsys.readouterr().out
    assert code == 2
    assert "SUMMARY_OK=0" in out
    assert "JSONDecodeError" in out
    assert "CLEAR_READY=" not in out


def test_summary_cli_wrong_file_is_not_a_report(tmp_path: Path, capsys) -> None:
    """다른 JSON을 가리켜도 '읽었다'가 되지 않는다 — 경로 오타가 통과하면 안 된다."""
    other = tmp_path / "other.json"
    other.write_text('{"hello": "world"}', encoding="utf-8")
    code = main(["--summary-from", str(other)])
    out = capsys.readouterr().out
    assert code == 2
    assert "SchemaError" in out
    assert "CLEAR_READY=" not in out


def test_summary_cli_exit_1_when_readable_but_blocked(tmp_path: Path, capsys) -> None:
    """읽기 실패(2)와 조건 미충족(1)은 **다른 색**이다 — 섞이면 대처가 달라진다."""
    report = tmp_path / "shallow.json"
    report.write_text(
        json.dumps(_report_payload(status="shallow", total_commits=0)), encoding="utf-8"
    )
    code = main(["--summary-from", str(report)])
    out = capsys.readouterr().out
    assert code == 1
    assert "SUMMARY_OK=1" in out
    assert "CLEAR_READY=0" in out
    assert "status=shallow" in out


def test_summary_mode_does_not_touch_git(tmp_path: Path, capsys) -> None:
    """git 없는 디렉터리에서도 성립한다 — 요약은 이미 만든 리포트를 읽을 뿐이다."""
    report = tmp_path / "r.json"
    report.write_text(json.dumps(_report_payload()), encoding="utf-8")
    code = main(["--root", str(tmp_path), "--summary-from", str(report)])
    assert code == 0
    assert "SUMMARY_OK=1" in capsys.readouterr().out


def test_generated_report_carries_consumption_block(repo: Path, tmp_path: Path) -> None:
    """집행 지점 — 실제 실행이 낸 리포트에 소비 블록이 실린다(정본화와 별항)."""
    out = tmp_path / "ev"
    main(["--root", str(repo), "--identity", "me@example.com", "--out", str(out)])
    payload = json.loads((out / "ip_separation_evidence.json").read_text(encoding="utf-8"))
    assert "consumption" in payload
    assert payload["consumption"]["powershell_convertfrom_json_safe"] in (True, False)
    assert "--summary-from" in payload["consumption"]["safe_consumption"]


def _runbook_text() -> str:
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "ops"
        / "ip_separation_evidence_gate_runbook.md"
    ).read_text(encoding="utf-8")


def _powershell_fences(text: str) -> list:
    """```powershell 펜스를 **블록 단위로** 돌려준다(주석·빈 줄 제외).

    블록을 합쳐서 보면 "어딘가 한 번 있으면 통과"가 되어, 두 블록 중 하나에서
    가드를 지워도 초록이 나온다(2026-09-08 뮤테이션 R3 생존으로 발각). 검사는
    **그 가드가 필요한 자리마다** 있는지를 물어야 한다.
    """
    fences, current, inside = [], [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if inside:
                fences.append(current)
                current = []
            inside = stripped.lower().startswith("```powershell")
            continue
        if inside and stripped and not stripped.startswith("#"):
            current.append(line)
    if inside and current:
        fences.append(current)
    return fences


def _fenced_command_lines(text: str) -> list:
    """```powershell 펜스 **안**의 줄만 돌려준다.

    산문과 명령을 나누는 이유: 이 런북은 `ConvertFrom-Json`을 *금지 사유로*
    언급해야 한다 — 산문에서도, 실행 블록의 주석에서도. 문서 전체를 문자열로
    훑는 가드는 그 설명 자체를 위반으로 잡아 — 규칙을 지키려는 문장이 규칙
    위반이 되는 — 사람이 가드를 꺼 버리게 만든다. 검사 대상은 **실제로
    실행되는 줄**이므로 주석 전용 줄(`#`로 시작)도 제외한다. 줄 끝 주석이
    달린 실행 줄(`… | ConvertFrom-Json  # 설명`)은 그대로 남는다.
    """
    lines, inside = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            inside = stripped.lower().startswith("```powershell")
            continue
        if inside and stripped and not stripped.startswith("#"):
            lines.append(line)
    return lines


def test_runbook_does_not_consume_the_report_with_convertfrom_json() -> None:
    """런북 동결 — 이 저장소에서 **다시 이 실패를 만들지 못하게** 한다.

    2026-09-08 실측에서 깨진 줄은 `$J = Get-Content $Report … | ConvertFrom-Json`
    이었다. 파일 이름이 변수 뒤에 숨어 있었으므로, "리포트 파일명과 같은 줄"을
    찾는 가드는 **이 줄을 놓친다**. 그래서 실행 블록 안의 `ConvertFrom-Json`
    자체를 금지한다 — 이 런북에는 그것을 정당하게 쓸 자리가 없다.
    """
    commands = _fenced_command_lines(_runbook_text())
    assert commands, "펜스 추출이 0줄 — 스캔 0건은 실패다(공허한 통과 금지)"
    offenders = [line for line in commands if "ConvertFrom-Json" in line]
    assert not offenders, f"실행 블록이 리포트를 ConvertFrom-Json으로 읽는다: {offenders}"


def test_runbook_reads_the_report_through_the_safe_path() -> None:
    """금지만으로는 부족하다 — 대체 경로가 실제로 블록 안에 있어야 한다."""
    commands = _fenced_command_lines(_runbook_text())
    assert any(
        "--summary-from" in line for line in commands
    ), "런북 실행 블록에 안전 소비 경로(--summary-from)가 없다"


def test_runbook_checks_tool_capability_before_using_it() -> None:
    """도구 능력 선검사 동결 (2026-09-08 실측) — **호출하는 블록마다** 요구한다.

    `--summary-from`이 없는 체크아웃에서 이 블록을 돌리면 argparse가 **exit 2**를
    내는데, 요약 모드의 "읽기 실패"도 exit 2다 — 화면만 보면 리포트가 깨진 것으로
    읽힌다. 실제 원인은 브랜치가 낡은 것이다.

    "런북 어딘가에 선검사가 있다"로는 부족하다: 블록이 둘인데 한쪽에서만 검사하면
    나머지 블록은 무방비인 채로 이 테스트가 통과한다(뮤테이션 R3 생존으로 발각).
    """
    fences = _powershell_fences(_runbook_text())
    assert fences, "펜스 추출이 0건 — 스캔 0건은 실패다(공허한 통과 금지)"

    callers = [f for f in fences if any("--summary-from .ip_evidence" in line for line in f)]
    assert callers, "런북에 --summary-from 호출이 하나도 없다"

    for fence in callers:
        assert any(
            "--help" in line and "ip_separation_evidence" in line for line in fence
        ), f"이 블록이 능력 확인 없이 --summary-from을 쓴다: {fence[:3]}"
        assert any(
            "HAS_SUMMARY_FROM" in line for line in fence
        ), f"선검사 결과가 이 블록의 화면에 남지 않는다: {fence[:3]}"


def test_fence_extractor_actually_separates_prose_from_commands() -> None:
    """가드의 재료 자체를 검증한다 — 펜스 추출이 틀리면 위 두 검사는 위장이다."""
    sample = "\n".join(
        [
            "설명에서 ConvertFrom-Json 을 금지한다",
            "",
            "```powershell",
            "# 주석에서도 ConvertFrom-Json 을 금지 사유로 적는다",
            "Get-Item x",
            "$J = Get-Content $R | ConvertFrom-Json  # 줄 끝 주석은 면제가 아니다",
            "```",
            "뒷글 ConvertFrom-Json",
        ]
    )
    extracted = _fenced_command_lines(sample)
    # 산문 2줄·주석 1줄은 빠지고 실행 줄 2줄만 남는다 — 줄 끝 주석은 면제가 아니다
    assert extracted == [
        "Get-Item x",
        "$J = Get-Content $R | ConvertFrom-Json  # 줄 끝 주석은 면제가 아니다",
    ]


def test_fence_grouping_keeps_blocks_apart() -> None:
    """블록 경계가 실제로 나뉘는지 — 합쳐지면 '한쪽만 검사'가 통과한다."""
    sample = "\n".join(["```powershell", "A", "```", "사이 산문", "```powershell", "B", "```"])
    assert _powershell_fences(sample) == [["A"], ["B"]]
