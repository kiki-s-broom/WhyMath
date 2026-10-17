"""[HARN-28] 고립 브랜치 스캔 리포트 — 직렬화 계약·발행/조회 왕복·4상태·브리핑 소비.

왜 이 테스트가 있는가
--------------------
`scan_stale_branches`는 shallow 클론이면 판정을 포기하고, 모든 CCR 세션 컨테이너가 shallow라
이 탐지기는 세션에서 한 번도 목록을 낸 적이 없다. 실행 위치를 CI(full clone)로 옮기고 결과를
`harness-reports` 브랜치로 세션에 전달한다. 이 파일은 그 전달선의 **각 이음매가 실제로
변별력을 갖는지** 동결한다.

핵심 변별(= 이 태스크의 acceptance ④)
------------------------------------
리포트 *없음* / *손상* / *정상*(+ 네트워크 불가)이 **서로 다른 화면**을 내야 한다. 같은 화면이면
"리포트가 없다"가 "고립 없음"으로 읽힌다 — 측정 실패와 통과가 같은 색이 되는 바로 그 결함.

가짜 git이 아니라 진짜 로컬 bare 원격을 쓴다(시임이면 `--force-with-lease`의 서버측 판정과
부모 없는 커밋 덮어쓰기를 검증할 수 없다). 뮤테이션 앵커는 각 테스트 docstring의 `kills:`.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import isolation_report as iso
import pytest
import remote_claims

import backlog as cli

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────


def _git(cwd: Path, *argv: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", *argv],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **(env or {})},
    )
    return done.stdout.strip()


def _push_old_branch(repo: Path, branch: str, days_ago: int, filename: str = "work.txt") -> None:
    """`days_ago`일 전 committerdate의 커밋 1건을 가진 브랜치를 원격에 올린다."""
    _git(repo, "checkout", "-b", branch)
    (repo / filename).write_text(f"{branch}\n", encoding="utf-8")
    past = datetime.now(timezone.utc) - timedelta(days=days_ago)
    stamp = past.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    _git(repo, "add", filename)
    _git(
        repo,
        "commit",
        "-m",
        f"{branch} work",
        env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    _git(repo, "push", "-u", "origin", branch)
    _git(repo, "checkout", "-")


def _scan(clone: Path) -> remote_claims.StaleBranchScanResult:
    result = remote_claims.scan_stale_branches(clone, days_threshold=3)
    assert result.status == "ok", f"픽스처 전제 위반 — 스캔이 ok가 아니다: {result.message}"
    return result


def _real_report(clone: Path) -> dict[str, Any]:
    return iso.build_report(
        _scan(clone), root=clone, days_threshold=3, now=datetime.now(timezone.utc)
    )


def _valid_report(**overrides: Any) -> dict[str, Any]:
    """네트워크·git 없이 만든 최소 정상 리포트 — validate/to_brief 변별 시험용."""
    report: dict[str, Any] = {
        "schema_version": iso.SCHEMA_VERSION,
        "generated_at": NOW.isoformat(),
        "scan_status": "ok",
        "basis": {
            "days_threshold": 3,
            "trunk_ref": "refs/remotes/origin/main",
            "trunk_branch": "main",
            "trunk_source": "ls-remote",
            "trunk_sha": "a" * 40,
            "scanned_refs": 12,
            "truncated": False,
            "pr_lookup_ok": True,
            "pr_lookup_error": "",
            "pr_state_lookup_ok": True,
            "pr_state_lookup_error": "",
            "pr_label_lookup_ok": True,
            "pr_label_lookup_error": "",
            "run_id": "",
        },
        "counts": {"isolated": 1},
        "branches": [
            {
                "branch": "claude/lost-work-abc123",
                "status": "isolated",
                "ahead": 7,
                "last_commit_at": (NOW - timedelta(days=5)).isoformat(),
                "age_days_at_generation": 5.0,
                "evidence": "",
                "partial_port": "",
                "port_scan_error": "",
                "disposal_labels": [],
                "impl_new": 3,
                "impl_changed": 1,
                "impl_scan_error": "",
            }
        ],
    }
    report.update(overrides)
    return report


def _push_raw_tree(clone: Path, filename: str, content: str, *, days_ago: int = 0) -> None:
    """원격 `harness-reports`에 임의 파일명·내용의 루트 커밋을 올린다(손상 시나리오 제작용).

    `days_ago`는 커밋 날짜를 과거로 돌린다 — 방치 스캔의 나이 임계를 넘기는 시나리오용.
    """
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    blob_sha = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=clone,
        input=content,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=clone,
        input=f"100644 blob {blob_sha}\t{filename}\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    commit = _git(
        clone,
        "commit-tree",
        tree,
        "-m",
        "tampered",
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.invalid",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        },
    )
    _git(clone, "push", "--force", "origin", f"{commit}:{iso.REPORTS_REF}")


# ── ① 직렬화 계약 ─────────────────────────────────────────────────────────


class TestSerializationContract:
    def test_report_carries_contract_fields(self, bare_remote):
        """리포트가_생성시각_판정기준_브랜치별_ahead_최종커밋일을_싣는다

        kills: build_report에서 basis·last_commit_at·ahead 누락.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)

        report = _real_report(b)

        assert iso.validate_report(report) == []
        assert report["generated_at"]
        basis = report["basis"]
        assert basis["days_threshold"] == 3
        assert basis["trunk_ref"].endswith("/main")
        # 판정 기준 = 어느 트렁크 시점에서 쟀는가. 해시가 비면 재현할 수 없는 판정이다.
        main_sha = _git(b, "rev-parse", "refs/remotes/origin/main")
        assert basis["trunk_sha"] == main_sha
        by_name = {x["branch"]: x for x in report["branches"]}
        assert "claude/old-orphan" in by_name
        entry = by_name["claude/old-orphan"]
        assert entry["ahead"] >= 1
        assert entry["status"] == "isolated"
        assert datetime.fromisoformat(entry["last_commit_at"]).tzinfo is not None
        assert report["counts"] == {"isolated": 1}

    def test_report_is_machine_readable_json(self, bare_remote):
        """직렬화_왕복이_무손실이다 — json.dumps→loads 후에도 검증을 통과한다."""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        report = _real_report(b)
        again = json.loads(json.dumps(report, ensure_ascii=False))
        assert again == report
        assert iso.validate_report(again) == []

    @pytest.mark.parametrize("status", ["shallow", "offline", "error"])
    def test_build_refuses_unmeasurable_scan(self, status):
        """측정_불가_스캔으로는_리포트를_만들지_않는다 — 빈 목록 발행 = '고립 0건' 위장

        kills: build_report의 status 가드 제거.
        """
        scan = remote_claims.StaleBranchScanResult(status, message="측정 못 함")
        with pytest.raises(ValueError, match=status):
            iso.build_report(scan, root=Path("."), days_threshold=3, now=NOW)

    def test_none_impl_signal_is_serialized_as_null_not_zero(self):
        """구현_신호_미측정은_0이_아니라_null이다(모른다≠없다)

        kills: impl_new를 `or 0`으로 접는 변환.
        """
        stale = remote_claims.StaleBranch(
            branch="claude/x",
            ref="refs/remotes/origin/claude/x",
            last_commit_at=NOW - timedelta(days=4),
            age_days=4.0,
            ahead=2,
            status="isolated",
            impl_new=None,
            impl_changed=None,
            impl_scan_error="TimeoutExpired: diff",
        )
        scan = remote_claims.StaleBranchScanResult(
            "ok", stale=[stale], trunk_ref="refs/remotes/origin/main"
        )
        report = iso.build_report(scan, root=Path("."), days_threshold=3, now=NOW)
        entry = report["branches"][0]
        assert entry["impl_new"] is None and entry["impl_changed"] is None
        assert entry["impl_scan_error"] == "TimeoutExpired: diff"


# ── 검증기 변별 ───────────────────────────────────────────────────────────


class TestValidateReport:
    def test_baseline_is_valid(self):
        """음성 대조 — 아래 변조 케이스가 전부 RED인 것이 의미 있으려면 이게 초록이어야 한다."""
        assert iso.validate_report(_valid_report(), now=NOW) == []

    @pytest.mark.parametrize(
        ("mutate", "needle"),
        [
            (lambda r: r.pop("schema_version"), "schema_version"),
            (lambda r: r.update(schema_version=99), "schema_version"),
            (lambda r: r.update(generated_at="2026-10-08T12:00:00"), "generated_at"),  # naive
            (lambda r: r.update(generated_at="어제"), "generated_at"),
            (lambda r: r.update(generated_at=(NOW + timedelta(days=3)).isoformat()), "미래"),
            (lambda r: r.update(scan_status="shallow"), "scan_status"),
            (lambda r: r.pop("basis"), "basis"),
            (lambda r: r["basis"].pop("trunk_sha"), "trunk_sha"),
            (lambda r: r["basis"].update(scanned_refs="12"), "scanned_refs"),
            (lambda r: r.update(branches={}), "branches"),
            (lambda r: r["branches"][0].update(status="weird"), "알 수 없는 분류"),
            (lambda r: r["branches"][0].update(ahead="7"), "ahead"),
            (lambda r: r["branches"][0].update(ahead=True), "ahead"),
            (lambda r: r["branches"][0].update(last_commit_at="2026-10-03"), "last_commit_at"),
            (lambda r: r["branches"][0].update(branch=""), "branch"),
            (lambda r: r.update(counts={"isolated": 0}), "counts"),
            (lambda r: r.update(counts={}), "counts"),
        ],
    )
    def test_each_corruption_is_detected(self, mutate, needle):
        """필수 키·형·시각·집계 어느 하나만 어긋나도 전체를 손상으로 본다(부분 정상 불인정)"""
        report = copy.deepcopy(_valid_report())
        mutate(report)
        errors = iso.validate_report(report, now=NOW)
        assert errors, "변조가 검출되지 않았다 — 검증기가 관대하다"
        assert any(needle in e for e in errors), errors

    def test_non_object_top_level(self):
        assert iso.validate_report([1, 2, 3], now=NOW)
        assert iso.validate_report(None, now=NOW)


# ── ② 발행 · 조회 왕복 (진짜 bare 원격) ────────────────────────────────────


class TestPublishFetchRoundTrip:
    def test_first_publish_creates_single_commit_branch_with_only_report(self, bare_remote):
        """최초_발행은_브랜치를_만들고_커밋_1개_파일_1개다

        kills: 부모를 달아 이력이 쌓이는 변형 · lease 기대값이 빈 값이 아닌 변형.
        """
        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)

        result = iso.publish(b, _real_report(b))

        assert result.status == "ok", result.message
        assert _git(bare, "rev-list", "--count", iso.REPORTS_REF) == "1"
        assert _git(bare, "ls-tree", "-r", "--name-only", iso.REPORTS_REF) == iso.REPORT_FILE

    def test_second_publish_replaces_without_growing_history(self, bare_remote):
        """재발행은_이력을_쌓지_않고_덮어쓴다 — 소비 fetch 비용이 영구히 O(1)

        kills: commit-tree에 `-p`를 붙이는 변형.
        """
        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        first = iso.publish(b, _real_report(b))
        _push_old_branch(a, "claude/second-orphan", days_ago=8, filename="two.txt")
        second = iso.publish(b, _real_report(b))

        assert first.status == second.status == "ok"
        assert first.commit != second.commit
        assert _git(bare, "rev-list", "--count", iso.REPORTS_REF) == "1"
        body = json.loads(_git(bare, "show", f"{iso.REPORTS_REF}:{iso.REPORT_FILE}"))
        assert {x["branch"] for x in body["branches"]} >= {
            "claude/old-orphan",
            "claude/second-orphan",
        }

    def test_publish_does_not_touch_index_or_worktree(self, bare_remote):
        """발행은_인덱스와_작업_트리를_건드리지_않는다(plumbing만 사용)"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        (b / "scratch.txt").write_text("미커밋 작업\n", encoding="utf-8")
        before = _git(b, "status", "--porcelain")

        assert iso.publish(b, _real_report(b)).status == "ok"

        assert _git(b, "status", "--porcelain") == before
        assert (b / "scratch.txt").read_text(encoding="utf-8") == "미커밋 작업\n"

    def test_lease_conflict_is_retried_not_clobbered(self, bare_remote, monkeypatch):
        """lease_경합이면_재조회_후_재시도한다 — 낡은 tip으로 덮어쓰지 않는다

        kills: --force-with-lease를 --force로 바꾸는 변형(경합을 무시하고 덮어씀).
        """
        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        assert iso.publish(b, _real_report(b)).status == "ok"

        real_tip = iso._remote_tip
        calls: list[int] = []

        def stale_first(root):
            calls.append(1)
            if len(calls) == 1:
                return "d" * 40, "ok"  # 그 사이 남이 갱신한 것처럼 낡은 기대값
            return real_tip(root)

        monkeypatch.setattr(iso, "_remote_tip", stale_first)
        result = iso.publish(b, _real_report(b))

        assert result.status == "ok", result.message
        assert len(calls) == 2, "lease 거부 뒤 재조회·재시도가 일어나야 한다"

    def test_invalid_report_is_never_pushed(self, bare_remote):
        """자기_검증을_못_넘는_리포트는_발행하지_않는다 — 소비자에게 손상본을 넘기지 않는다"""
        bare, clone = bare_remote
        b = clone("session-b")
        bad = _valid_report(counts={"isolated": 99})

        result = iso.publish(b, bad)

        assert result.status == "error"
        assert "counts" in result.message
        assert _git(bare, "for-each-ref", iso.REPORTS_REF) == ""

    def test_shallow_session_reads_what_full_clone_published(self, bare_remote, shallow_clone):
        """CI(full)가_발행한_것을_세션(shallow)이_읽는다 — 이_태스크의_전달선_전체

        그리고 읽은 뒤에도 shallow 클론은 shallow 그대로다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        published = _real_report(b)
        assert iso.publish(b, published).status == "ok"

        session = shallow_clone("shallow-session")
        fetched = iso.fetch_report(session)

        assert fetched.state == iso.STATE_OK, fetched.detail
        assert fetched.report == published
        assert remote_claims.is_shallow_repo(session) is True

    def test_fetch_never_turns_a_full_clone_into_shallow(self, bare_remote):
        """리포트_조회가_full_클론을_shallow로_바꾸지_않는다

        fetch에 `--depth`를 주면 full 클론이 shallow가 되어 이 태스크가 고치려는 결함을 스스로
        만든다(그 클론의 이후 스캔이 전부 shallow 판정 포기).
        kills: fetch_report의 fetch에 `--depth 1` 추가.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        assert iso.publish(b, _real_report(b)).status == "ok"
        assert remote_claims.is_shallow_repo(b) is False

        assert iso.fetch_report(b).state == iso.STATE_OK

        assert remote_claims.is_shallow_repo(b) is False
        assert _scan(b)  # 이후에도 스캔이 ok로 돈다


# ── 소비 4상태: 없음 / 손상 / 정상 / 네트워크 불가 ───────────────────────────


class TestFetchStates:
    def test_absent_when_branch_never_published(self, bare_remote):
        _, clone = bare_remote
        fetched = iso.fetch_report(clone("session-a"))
        assert fetched.state == iso.STATE_ABSENT
        assert fetched.report is None

    @pytest.mark.parametrize(
        ("filename", "content", "needle"),
        [
            (iso.REPORT_FILE, "{ not json", "JSONDecodeError"),
            (iso.REPORT_FILE, "[]", "스키마 위반"),
            (iso.REPORT_FILE, json.dumps({"schema_version": 1}), "스키마 위반"),
            ("other.json", "{}", "파일이 브랜치 트리에 없다"),
        ],
    )
    def test_corrupt_branches_are_reported_as_corrupt(self, bare_remote, filename, content, needle):
        """브랜치는_있는데_내용이_못_쓸_것이면_absent가_아니라_corrupt다"""
        _, clone = bare_remote
        a = clone("session-a")
        _push_raw_tree(a, filename, content)

        fetched = iso.fetch_report(clone("session-b"))

        assert fetched.state == iso.STATE_CORRUPT
        assert needle in fetched.detail

    def test_unreachable_when_origin_cannot_be_read(self, bare_remote):
        _, clone = bare_remote
        a = clone("session-a")
        _git(a, "remote", "set-url", "origin", str(a.parent / "does-not-exist.git"))

        fetched = iso.fetch_report(a)

        assert fetched.state == iso.STATE_UNREACHABLE
        assert fetched.report is None

    def test_fetch_never_raises_and_names_exception_type(self, bare_remote, monkeypatch):
        """훅_진입점이므로_어떤_예외도_삼키되_타입명은_남긴다(침묵_실패_금지)"""
        _, clone = bare_remote
        a = clone("session-a")

        def boom(*_a, **_k):
            raise RuntimeError("git 폭발")

        monkeypatch.setattr(remote_claims, "_git", boom)
        fetched = iso.fetch_report(a)

        assert fetched.state == iso.STATE_UNREACHABLE
        assert "RuntimeError" in fetched.detail


# ── 브리핑 번역: 상태마다 다른 화면 (acceptance ④의 핵심) ─────────────────────


def _brief_for(state: str, **extra: Any) -> iso.BriefIsolation:
    fetched = {
        iso.STATE_OK: iso.ReportFetch(iso.STATE_OK, report=_valid_report()),
        iso.STATE_ABSENT: iso.ReportFetch(iso.STATE_ABSENT, detail="브랜치 없음"),
        iso.STATE_CORRUPT: iso.ReportFetch(iso.STATE_CORRUPT, detail="JSONDecodeError: x"),
        iso.STATE_UNREACHABLE: iso.ReportFetch(iso.STATE_UNREACHABLE, detail="fetch 실패(offline)"),
    }[state]
    return iso.to_brief(fetched, local_status="shallow", now=NOW, **extra)


class TestBriefTranslation:
    def test_four_states_yield_four_distinct_screens(self):
        """없음/손상/정상/불가가 서로 다른 (status, message, source_line)을 낸다

        kills: 비-ok 분기를 하나로 합치는 변형 · absent를 ok-0건으로 접는 변형.
        """
        screens = {
            state: (
                (b := _brief_for(state)).status,
                b.message,
                b.source_line,
                len(b.stale_branches),
            )
            for state in (iso.STATE_OK, iso.STATE_ABSENT, iso.STATE_CORRUPT, iso.STATE_UNREACHABLE)
        }
        assert len(set(screens.values())) == 4, screens

    @pytest.mark.parametrize("state", [iso.STATE_ABSENT, iso.STATE_CORRUPT, iso.STATE_UNREACHABLE])
    def test_unmeasured_says_unmeasured_never_zero(self, state):
        """리포트를_못_쓰면_'미측정'이라고_말하고_status를_ok로_올리지_않는다

        kills: 비-ok에서 status="ok"·빈 목록을 내는 변형("고립 0건" 위장).
        """
        b = _brief_for(state)
        assert "미측정" in b.message
        assert b.status == "shallow"  # 세션 스캔의 원 상태 유지 → render가 판정 보류 줄을 낸다
        assert b.stale_branches == []
        assert b.source_line == ""
        assert "0건" not in b.message

    def test_unmeasured_prescriptions_differ_per_state(self):
        """처방이_상태마다_다르다 — 같은 문구면 상태를 나눈 의미가 없다"""
        hints = {
            s: _brief_for(s).message
            for s in (iso.STATE_ABSENT, iso.STATE_CORRUPT, iso.STATE_UNREACHABLE)
        }
        assert len(set(hints.values())) == 3
        assert "isolation-scan" in hints[iso.STATE_ABSENT]

    def test_unmeasured_keeps_manual_recovery_hint(self):
        """세션_스캔의_수동_복구_안내(--unshallow)를_버리지_않는다"""
        b = _brief_for(iso.STATE_ABSENT, local_message=remote_claims.SHALLOW_PENDING_MESSAGE)
        assert "--unshallow" in b.message

    def test_ok_report_always_shows_generation_time_and_basis(self):
        """정상_리포트는_생성_시각과_기준_커밋을_항상_병기한다

        kills: source_line에서 generated_at·trunk_sha 제거.
        """
        b = _brief_for(iso.STATE_OK)
        assert b.status == "ok"
        assert "2026-10-08 12:00Z" in b.source_line
        assert "0시간 전" in b.source_line
        assert "main@" + "a" * 8 in b.source_line
        assert "미반영" in b.source_line  # 측정 이후 머지·삭제는 반영 전이라는 한계 고지

    def test_ok_report_with_zero_branches_is_not_mistaken_for_unmeasured(self):
        """'리포트가_있고_0건'과_'리포트가_없다'는_다른_화면이다"""
        empty = _valid_report(counts={}, branches=[])
        ok_zero = iso.to_brief(
            iso.ReportFetch(iso.STATE_OK, report=empty), local_status="shallow", now=NOW
        )
        absent = _brief_for(iso.STATE_ABSENT)
        assert ok_zero.status == "ok" and "0건" in ok_zero.source_line
        assert absent.status == "shallow" and "미측정" in absent.message
        assert ok_zero.source_line != absent.source_line

    @pytest.mark.parametrize(
        ("hours", "warns"), [(10, False), (35, False), (37, True), (200, True)]
    )
    def test_stale_report_is_flagged_beyond_threshold(self, hours, warns):
        """낡은_리포트는_36시간_초과_시_경고한다 — 야간_잡이_멎은_것을_숨기지_않는다

        kills: STALE_AFTER_HOURS 비교 제거·방향 반전.
        """
        report = _valid_report(generated_at=(NOW - timedelta(hours=hours)).isoformat())
        b = iso.to_brief(
            iso.ReportFetch(iso.STATE_OK, report=report), local_status="shallow", now=NOW
        )
        assert (f"{iso.STALE_AFTER_HOURS}시간 초과" in b.source_line) is warns
        assert f"{hours}시간 전" in b.source_line

    def test_branch_age_is_recomputed_at_read_time(self):
        """브랜치_나이는_읽는_시점에_last_commit_at에서_다시_계산한다

        어제 잰 '5일'이 오늘도 5일로 읽히면 안 된다.
        kills: age_days_at_generation을 그대로 쓰는 변형.
        """
        report = _valid_report()
        later = NOW + timedelta(days=2)
        b = iso.to_brief(
            iso.ReportFetch(iso.STATE_OK, report=report), local_status="shallow", now=later
        )
        age_days = b.stale_branches[0][1]
        assert 6.9 < age_days < 7.1  # 생성 시점 5일 + 경과 2일

    def test_pr_state_lookup_flags_travel_with_the_report(self):
        """리포트_시점의_PR_상태_조회_실패가_소비_쪽_문구에_그대로_전달된다"""
        report = _valid_report()
        report["basis"]["pr_state_lookup_ok"] = False
        report["basis"]["pr_state_lookup_error"] = "NoTokenError"
        b = iso.to_brief(
            iso.ReportFetch(iso.STATE_OK, report=report), local_status="shallow", now=NOW
        )
        assert b.pr_state_lookup_ok is False
        assert b.pr_state_lookup_error == "NoTokenError"

    def test_tuple_contract_matches_render_brief_ten_fields(self):
        """튜플이_render_brief가_소비하는_10필드_계약과_같은_길이·순서다"""
        entry = _brief_for(iso.STATE_OK).stale_branches[0]
        assert len(entry) == 10
        assert entry[0] == "claude/lost-work-abc123"
        assert entry[2] == 7 and entry[3] == "isolated"
        assert entry[7] == 3 and entry[8] == 1  # impl_new · impl_changed


# ── ③ 소비 지점: cmd_brief 배선 (실제 bare 원격 + brief CLI) ────────────────


class TestBriefCommandConsumesReport:
    def _session(self, bare_remote, monkeypatch):
        _, clone = bare_remote
        mine = clone("newcomer")
        monkeypatch.chdir(mine)
        assert cli.main(["seed"]) == 0
        return clone, mine

    def _force_shallow(self, monkeypatch):
        monkeypatch.setattr(
            remote_claims,
            "scan_stale_branches",
            lambda root, **kwargs: remote_claims.StaleBranchScanResult(
                "shallow", message=remote_claims.SHALLOW_PENDING_MESSAGE
            ),
        )

    def test_shallow_session_shows_published_report(self, bare_remote, monkeypatch, capsys):
        """세션_스캔이_shallow면_발행된_리포트의_고립_브랜치가_브리핑에_뜬다(시각_병기)

        kills: cmd_brief의 리포트 대체 블록 제거·isolation_source 미전달.
        """
        clone, mine = self._session(bare_remote, monkeypatch)
        publisher = clone("publisher")
        _push_old_branch(clone("worker"), "claude/lost-work-abc123", days_ago=9)
        assert iso.publish(publisher, _real_report(publisher)).status == "ok"
        self._force_shallow(monkeypatch)

        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out

        assert "claude/lost-work-abc123" in out
        assert "CI 야간 리포트" in out
        assert "측정 " in out and "시간 전" in out
        assert "고립 브랜치 미측정" not in out

    def test_shallow_session_without_report_says_unmeasured(self, bare_remote, monkeypatch, capsys):
        """리포트가_없으면_'고립_없음'이_아니라_'미측정'이다(상태_구분_acceptance)"""
        self._session(bare_remote, monkeypatch)
        self._force_shallow(monkeypatch)

        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out

        assert "고립 브랜치 미측정" in out
        assert "판정 보류" in out
        assert "📡" not in out
        assert "--unshallow" in out  # 수동 복구 안내 보존

    def test_corrupt_report_says_unmeasured_with_distinct_text(
        self, bare_remote, monkeypatch, capsys
    ):
        """손상_리포트도_미측정이되_'없음'과_다른_문구다"""
        clone, _mine = self._session(bare_remote, monkeypatch)
        _push_raw_tree(clone("tamperer"), iso.REPORT_FILE, "{ not json")
        self._force_shallow(monkeypatch)

        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out

        assert "고립 브랜치 미측정" in out
        assert "손상" in out
        assert "📡" not in out

    def test_full_clone_live_scan_does_not_read_report(self, bare_remote, monkeypatch, capsys):
        """라이브_스캔이_ok면_리포트를_읽지_않는다 — 더_신선한_쪽을_쓴다(대조군)

        kills: shallow 조건을 제거해 항상 리포트를 읽는 변형.
        """
        self._session(bare_remote, monkeypatch)

        # 호출 기록으로 검증한다 — 예외로 막으면 cmd_brief의 fail-open `except Exception`이
        # 삼켜서 "shallow 조건 제거" 변형이 검출되지 않는다(주입 시험으로 확인할 약점).
        calls: list[int] = []
        real_fetch = iso.fetch_report

        def spy(*args, **kwargs):
            calls.append(1)
            return real_fetch(*args, **kwargs)

        monkeypatch.setattr(iso, "fetch_report", spy)
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        assert calls == [], "라이브 스캔이 ok인데 리포트를 읽었다"
        assert "📡" not in out

    def test_report_lookup_failure_never_breaks_the_brief(self, bare_remote, monkeypatch, capsys):
        """리포트_대체_중_예외가_나도_브리핑은_나오고_예외_타입명이_남는다(훅_진입점_fail-open)"""
        self._session(bare_remote, monkeypatch)
        self._force_shallow(monkeypatch)

        def boom(*_a, **_k):
            raise KeyError("x")

        monkeypatch.setattr(iso, "brief_for_session", boom)
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        assert "KeyError" in out
        assert "판정 보류" in out


# ── 하네스 소유 브랜치는 방치 스캔 대상 밖 ───────────────────────────────────


class TestOwnedBranchExclusion:
    def test_reports_branch_never_reported_as_stale(self, bare_remote):
        """harness-reports는_야간_잡이_사흘_멎어도_'결정_대기'로_뜨지_않는다

        orphan이라 trunk 대비 ahead>0이 되어 제외가 없으면 isolated로 뜬다.
        kills: HARNESS_OWNED_BRANCHES에서 REPORTS_BRANCH 제거.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        # 같은 스캔 안의 대조군 — 일반 오래된 브랜치는 잡히고 리포트 브랜치만 빠져야 한다.
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        # 리포트 브랜치도 9일 전 커밋으로 — 임계(3일)를 확실히 넘겨 제외가 없으면 반드시 뜬다.
        _push_raw_tree(a, iso.REPORT_FILE, "{}", days_ago=9)

        names = {s.branch for s in _scan(b).stale}

        assert "claude/old-orphan" in names
        assert iso.REPORTS_BRANCH not in names
        assert remote_claims.CLAIMS_BRANCH not in names

    def test_owned_branch_set_is_exactly_claims_and_reports(self):
        assert remote_claims.HARNESS_OWNED_BRANCHES == frozenset(
            {remote_claims.CLAIMS_BRANCH, remote_claims.REPORTS_BRANCH}
        )
        assert iso.REPORTS_BRANCH == remote_claims.REPORTS_BRANCH == "harness-reports"


# ── CLI ───────────────────────────────────────────────────────────────────


class TestPublishCommand:
    def test_unmeasurable_scan_does_not_publish_and_exits_2(
        self, shallow_clone, bare_remote, capsys, monkeypatch
    ):
        """스캔_불가(shallow)면_발행하지_않고_exit_2다 — 측정_실패를_초록으로_올리지_않는다

        kills: scan.status 가드 제거 · 실패 시 exit 0.
        """
        bare, _clone = bare_remote
        session = shallow_clone("ci-misconfigured")
        monkeypatch.chdir(session)

        code = iso.main(["publish"])

        assert code == 2
        assert _git(bare, "for-each-ref", iso.REPORTS_REF) == ""
        assert "발행하지 않는다" in capsys.readouterr().err

    def test_publish_from_full_clone_writes_branch_and_artifact(
        self, bare_remote, tmp_path, capsys, monkeypatch
    ):
        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        monkeypatch.chdir(b)
        out_file = tmp_path / "isolation.json"

        code = iso.main(["publish", "--out", str(out_file)])

        assert code == 0
        assert json.loads(out_file.read_text(encoding="utf-8"))["counts"] == {"isolated": 1}
        assert _git(bare, "rev-list", "--count", iso.REPORTS_REF) == "1"
        assert "발행 완료" in capsys.readouterr().out

    def test_dry_run_publishes_nothing(self, bare_remote, capsys, monkeypatch):
        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _push_old_branch(a, "claude/old-orphan", days_ago=9)
        monkeypatch.chdir(b)

        assert iso.main(["publish", "--dry-run"]) == 0

        assert _git(bare, "for-each-ref", iso.REPORTS_REF) == ""

    @pytest.mark.parametrize(
        ("setup", "code"),
        [("none", 3), ("corrupt", 4), ("ok", 0)],
    )
    def test_show_exit_codes_distinguish_states(self, bare_remote, monkeypatch, setup, code):
        """show의_exit_code가_상태를_가른다(0_정상/3_없음/4_손상)"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        if setup == "corrupt":
            _push_raw_tree(a, iso.REPORT_FILE, "{ not json")
        elif setup == "ok":
            _push_old_branch(a, "claude/old-orphan", days_ago=9)
            assert iso.publish(b, _real_report(b)).status == "ok"
        monkeypatch.chdir(b)

        assert iso.main(["show"]) == code
