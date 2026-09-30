"""HARN-170 ⑤ — 기커밋 테스트 누출 묶음의 서명 판별기 계약 동결.

대장은 append 전용이라 누출분을 지우지 않고 집계에서 뺀다. 그 뺄셈이 정당하려면 판별기가
①누출 묶음을 실제로 찾고(실제 대장에서 0건이면 실패) ②실제 편집 경고를 누출로 오인하지 않아야
한다. 그래서 조건마다 **그 조건이 없으면 누출로 걸리는 반례**를 하나씩 둔다 — 절을 지웠을 때
초록이면 픽스처가 그 절을 안 밟은 것이다(CLAUDE.md 2026-09-07 픽스처 접촉 축).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import event_leaks as leaks
import pytest

import backlog as cli

REPO_ROOT = Path(__file__).resolve().parents[2]
BK = "scripts/harness/backlog.py"
BASE = datetime(2026, 9, 22, 3, 0, 0, tzinfo=timezone.utc)


def _ev(t: float, rule: str, file: str = BK, *, shard: str = "s.ndjson", base=BASE, line=None):
    return leaks.WarnEvent(
        shard=shard,
        line=line if line is not None else int(t * 10) + (1 if rule == "path_overlap" else 0),
        moment=base + timedelta(seconds=t),
        rule=rule,
        file=file,
    )


def _claimed_bundle(base=BASE, shard="s.ndjson") -> list[leaks.WarnEvent]:
    """claim 세션 모양 — backlog.py scope_drift·path_overlap 3번씩 + README.md scope_drift 1번."""
    out = []
    for i, t in enumerate((0, 2, 6)):
        out.append(_ev(t, "scope_drift", base=base, shard=shard, line=10 + 2 * i))
        out.append(_ev(t, "path_overlap", base=base, shard=shard, line=11 + 2 * i))
    out.append(_ev(4, "scope_drift", "README.md", base=base, shard=shard, line=30))
    return out


def _claimless_bundle(base=BASE) -> list[leaks.WarnEvent]:
    """claim 없는 세션 모양 — 원격 캐시 겹침으로 backlog.py path_overlap만 3번."""
    return [_ev(t, "path_overlap", line=40 + i, base=base) for i, t in enumerate((0, 3, 5))]


class TestFindsTheLeakShapes:
    def test_claimed_session_bundle(self) -> None:
        bundle = _claimed_bundle()
        assert leaks.leak_keys(bundle) == {e.key for e in bundle}

    def test_claimless_bundle(self) -> None:
        bundle = _claimless_bundle()
        assert leaks.leak_keys(bundle) == {e.key for e in bundle}

    def test_epoch_day_itself_counts(self) -> None:
        """경계 — 착지일 당일의 묶음은 누출이다(⑤는 '이전'만 거른다)."""
        day = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
        assert leaks.leak_keys(_claimless_bundle(base=day))


class TestEachClauseHasACounterexample:
    """각 반례는 그 조건 **하나만** 어긋나게 만든다 — 나머지 조건은 누출 모양 그대로다."""

    def test_other_file_in_the_bundle(self) -> None:  # ①
        bundle = [*_claimless_bundle(), _ev(4, "path_overlap", "src/x.py", line=99)]
        assert leaks.leak_keys(bundle) == set()

    def test_readme_alone_is_not_the_shape(self) -> None:  # ①
        assert leaks.leak_keys([_ev(0, "scope_drift", "README.md")]) == set()

    @pytest.mark.parametrize("times", [(0, 3), (0, 2, 4, 6)])
    def test_hot_file_count_must_be_exactly_three(self, times) -> None:  # ②
        bundle = [_ev(t, "path_overlap", line=50 + i) for i, t in enumerate(times)]
        assert leaks.leak_keys(bundle) == set()

    def test_two_readme_warnings_are_not_the_shape(self) -> None:  # ③
        bundle = [*_claimed_bundle(), _ev(5, "scope_drift", "README.md", line=31)]
        assert leaks.leak_keys(bundle) == set()

    def test_readme_overlap_is_not_the_shape(self) -> None:  # ③
        bundle = [*_claimless_bundle(), _ev(4, "path_overlap", "README.md", line=31)]
        assert leaks.leak_keys(bundle) == set()

    def test_bundle_longer_than_the_span_limit(self) -> None:  # ④ 길이
        """이웃 간격은 8초 이하로 이어지지만 전체가 24초 — 한 클래스가 연달아 도는 시간이 아니다."""
        bundle = [
            *[_ev(t, "scope_drift", line=60 + i) for i, t in enumerate((0, 8, 16))],
            _ev(24, "scope_drift", "README.md", line=70),
        ]
        assert leaks.leak_keys(bundle) == set()

    @pytest.mark.parametrize("offset", [-12, 15])
    def test_a_neighbour_within_the_isolation_window(self, offset) -> None:  # ④ 고립
        """사람의 연속 편집 — 모양은 같아도 앞뒤로 다른 편집 경고가 붙어 있다(실측 9·12초)."""
        neighbour_t = offset if offset < 0 else 5 + offset
        bundle = [*_claimless_bundle(), _ev(neighbour_t, "scope_drift", "src/y.py", line=80)]
        assert leaks.leak_keys(bundle) == set()

    def test_a_far_neighbour_does_not_hide_the_leak(self) -> None:  # ④ 대조군
        bundle = [*_claimless_bundle(), _ev(-40, "scope_drift", "src/y.py", line=1)]
        assert leaks.leak_keys(bundle) == {e.key for e in _claimless_bundle()}

    def test_before_the_epoch(self) -> None:  # ⑤
        """누출 경로가 착지하기 전 — 2026-09-07 한 세션의 실제 편집 묶음이 정확히 이 모양이었다."""
        day = datetime(2026, 9, 20, 23, 59, 0, tzinfo=timezone.utc)
        assert leaks.leak_keys(_claimless_bundle(base=day)) == set()

    def test_gaps_wider_than_the_join_limit_split_the_bundle(self) -> None:  # 잇기
        bundle = [_ev(t, "path_overlap", line=90 + i) for i, t in enumerate((0, 9, 18))]
        assert leaks.leak_keys(bundle) == set()

    def test_shards_are_not_mixed(self) -> None:  # 샤드 분리
        bundle = [
            _ev(0, "path_overlap", shard="a.ndjson", line=1),
            _ev(3, "path_overlap", shard="a.ndjson", line=2),
            _ev(5, "path_overlap", shard="b.ndjson", line=1),
        ]
        assert leaks.leak_keys(bundle) == set()


def _live_warn_events() -> list[leaks.WarnEvent]:
    return [record for record, _event, _known in leaks.read_warn_events(REPO_ROOT)]


class TestLiveLedger:
    def test_the_committed_leak_bundles_are_found(self) -> None:
        """판별기가 0건이면 실패 — 실제 대장에는 착수 실측 74묶음(2026-09-25) 이상이 있다.

        대장은 append 전용이라 이 수는 줄지 않는다. 하한 밑으로 떨어지면 판별기가 모양을 놓치기
        시작한 것이다(누출이 사라진 것이 아니다).
        """
        bundles = leaks.leak_bundles(_live_warn_events())
        assert len(bundles) >= 74
        assert all(b[0].moment.date() >= leaks.LEAK_EPOCH for b in bundles)
        assert all({e.file for e in b} <= leaks.LEAK_FILES for b in bundles)


class TestPolicyReportExcludesLeaks:
    def test_report_counts_only_genuine_warnings(self, git_repo: Path, monkeypatch, capsys) -> None:
        """hermetic — 누출 묶음 7줄 + 실제 경고 1줄 → 총 1건 · 제외 7건이 화면에 보인다."""
        monkeypatch.chdir(git_repo)
        assert cli.main(["seed"]) == 0
        shard = git_repo / "backlog" / "events" / "claude_leaky.ndjson"
        now = datetime.now().astimezone()
        lines = []
        for e in _claimed_bundle(base=now - timedelta(hours=2)):
            lines.append(
                {
                    "ts": e.moment.isoformat(timespec="seconds"),
                    "actor": "claude/leaky",
                    "action": "policy_warn",
                    "id": "-",
                    "rule": e.rule,
                    "file": e.file,
                    "mode": "warn",
                    "detail": "누출 픽스처",
                }
            )
        lines.append(
            {
                "ts": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
                "actor": "claude/leaky",
                "action": "policy_warn",
                "id": "-",
                "rule": "scope_drift",
                "file": "src/real.py",
                "mode": "warn",
                "detail": "실제 경고",
            }
        )
        shard.write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8"
        )
        capsys.readouterr()
        assert cli.main(["policy", "report"]) == 0
        out = capsys.readouterr().out
        assert "총 1건" in out
        assert "테스트 누출 서명 7건 제외" in out

    def test_a_bundle_straddling_the_window_edge_is_still_excluded(
        self, git_repo: Path, monkeypatch, capsys
    ) -> None:
        """판정은 기간 필터 **전** 전체에서 한다 — 묶음이 경계에서 잘리면 안쪽 반쪽은 모양이 깨진다.

        `--days 1` 경계를 누출 묶음 한가운데 둔다. 안쪽 반쪽만 보고 판정하면 규칙별 3건이 아니라
        누출로 인식되지 않고 집계에 섞인다(총 1건이 아니게 된다).
        """
        monkeypatch.chdir(git_repo)
        assert cli.main(["seed"]) == 0
        now = datetime.now().astimezone()
        edge = now - timedelta(days=1)
        lines = [
            {
                "ts": e.moment.isoformat(timespec="seconds"),
                "actor": "claude/leaky",
                "action": "policy_warn",
                "id": "-",
                "rule": e.rule,
                "file": e.file,
                "mode": "warn",
                "detail": "누출 픽스처",
            }
            for e in _claimed_bundle(base=edge - timedelta(seconds=1))
        ]
        lines.append(
            {
                "ts": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
                "actor": "claude/leaky",
                "action": "policy_warn",
                "id": "-",
                "rule": "scope_drift",
                "file": "src/real.py",
                "mode": "warn",
                "detail": "실제 경고",
            }
        )
        shard = git_repo / "backlog" / "events" / "claude_leaky.ndjson"
        shard.write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8"
        )
        capsys.readouterr()
        assert cli.main(["policy", "report", "--days", "1"]) == 0
        out = capsys.readouterr().out
        assert "총 1건" in out
        assert "테스트 누출 서명 0건" not in out  # 안쪽 반쪽이 실제로 빠졌다
