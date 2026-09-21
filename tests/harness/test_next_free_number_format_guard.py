"""backlog._next_free_number — 100 이상에서 형식 위반 ID를 제안하던 결함 (HARN-21 결함②).

`{index:02d}`는 **최소** 2자리이지 **정확히** 2자리가 아니다 — `index=100`이면 `"100"`
(3자리)을 낸다. HARN-21 시점에는 `models.TASK_ID_RE`가 `\\d{2}`(정확히 2자리)만
허용해 그 출력이 형식 위반 ID였다. 그래서 당시 수정은 index가 99를 넘으면
`_next_free_number`가 `None`을 반환하고 `cmd_add`가 "프리픽스 소진 — 사람의 결정
필요" 명시적 오류로 승격하는 것이었다(날조된 3자리 제안 금지).

[HARN-97 갱신 · 2026-09-11] 그 "99 = 소진" 판정 자체가 실제로 ARCH·EOS 두 접두를
막았다 — `--id EOS-100`이 형식 검증에서 거부됐다. `models.TASK_ID_RE`를 2~3자리
(100~999, 선행 0 없이)로 넓히면서, `_next_free_number`는 `cap` 인자(기본 99 —
HARN-21·HARN-73 동작·아래 테스트 불변)를 받고, `_suggest_number`는 하위(01~99)
재사용마저 없을 때만 `cap=999`로 다시 불러 3자리를 제안한다(`history="extended"`).
"정말 소진"의 경계는 99에서 **999**로 옮겨갔다 — 아래 `test_exactly_99_used_*` 류는
"99에서 3자리를 확장 제안한다"로, `test_truly_exhausted_*`는 999 기준으로 갱신했다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import backlog as cli


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _taken_full(prefix: str, numbers: range) -> dict[str, tuple[str, str]]:
    """`{prefix}-01`..`{prefix}-NN`(100 이상은 3자리 그대로)이 전부 점유된 taken 딕셔너리."""
    return {f"{prefix}-{i:02d}": (f"{prefix}-{i:02d}-task", "로컬 백로그") for i in numbers}


class TestNextFreeNumberFormatGuard:
    """단위 레벨 — 함수 자체의 경계값 동작."""

    def test_normal_range_still_returns_two_digit_string(self):
        """정상_범위는_여전히_2자리_문자열을_낸다 — 회귀 방지"""
        taken = _taken_full("E1", range(1, 5))  # E1-01..E1-04 점유
        assert cli._next_free_number("E1", taken) == "E1-05"

    def test_single_digit_index_is_zero_padded(self):
        """1자리_index도_0패딩된다"""
        assert cli._next_free_number("ZZ", {}) == "ZZ-01"

    def test_exactly_99_used_returns_none_not_three_digits(self):
        """99개_전부_소진되면_None을_반환한다 — 3자리(E1-100) 날조 금지"""
        taken = _taken_full("E1", range(1, 100))  # E1-01..E1-99 전부 점유
        assert cli._next_free_number("E1", taken) is None

    def test_boundary_98_used_still_suggests_99(self):
        """98개_소진_시엔_아직_99번을_제안할_수_있다 — 경계값 반대쪽"""
        taken = _taken_full("E1", range(1, 99))  # E1-01..E1-98 점유
        assert cli._next_free_number("E1", taken) == "E1-99"

    def test_taken_value_shape_matches_taken_id_numbers_return_type(self):
        """taken의_값_형태가_실제_taken_id_numbers_반환형(tuple[str,str])과_일치한다

        시그니처 애노테이션 정정(HARN-21) 검증 — 함수가 실제로 이 형태의 dict를
        받아 동작함을 실증한다(키만 순회하므로 값 타입이 달라도 런타임 버그는
        없었지만, 애노테이션이 이 형태를 정확히 반영해야 한다).
        """
        taken: dict[str, tuple[str, str]] = {"ZQ-01": ("ZQ-01-existing", "로컬 백로그")}
        assert cli._next_free_number("ZQ", taken) == "ZQ-02"


class TestCmdAddSurfacesExhaustionAsExplicitError:
    """CLI 종단 — 프리픽스 소진 시 cmd_add가 날조 대신 명시적 오류를 낸다."""

    def _add(self, task_id: str) -> int:
        return cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                task_id,
                "--title",
                "프리픽스 소진 테스트",
                "--track",
                "math-completion",
                "--stage",
                "S2",
            ]
        )

    def test_99_used_collision_extends_to_three_digit_suggestion(
        self, seeded_repo, monkeypatch, capsys
    ):
        """[HARN-97] 01~99가_전부_점유돼도_소진이_아니라_3자리로_확장_제안한다"""
        fake_taken = _taken_full("ZQ", range(1, 100))  # ZQ-01..ZQ-99 전부 로컬 점유로 가장

        def _fake_taken_id_numbers(root, backlog, policy):
            return dict(fake_taken)

        monkeypatch.setattr(cli, "_taken_id_numbers", _fake_taken_id_numbers)
        monkeypatch.setattr(cli, "_historically_used_numbers", lambda root, prefix: (set(), "ok"))

        capsys.readouterr()
        assert self._add("ZQ-01-my-new-slug") == 1, "번호 충돌은 여전히 거부돼야 한다"
        captured = capsys.readouterr()
        assert "ZQ-100" in captured.err, "01~99 소진 시 3자리(ZQ-100)를 제안해야 한다"
        assert "상위 2자리 번호 소진" in captured.err, captured.err
        assert "001~999" not in captured.err, "001~999 전부 소진 문구는 아직 나오면 안 된다"
        assert "사람의 결정" not in captured.err, "3자리 제안이 됐으면 사람의 결정은 필요 없다"

    def test_999_used_collision_fails_with_explicit_message_not_four_digit_suggestion(
        self, seeded_repo, monkeypatch, capsys
    ):
        """[HARN-97] 001~999까지_전부_점유되면_비로소_소진_오류를_낸다 — 4자리 날조 금지"""
        fake_taken = _taken_full("ZQ", range(1, 1000))  # ZQ-001..ZQ-999 전부 로컬 점유로 가장

        def _fake_taken_id_numbers(root, backlog, policy):
            return dict(fake_taken)

        monkeypatch.setattr(cli, "_taken_id_numbers", _fake_taken_id_numbers)
        monkeypatch.setattr(cli, "_historically_used_numbers", lambda root, prefix: (set(), "ok"))

        capsys.readouterr()
        assert self._add("ZQ-01-my-new-slug") == 1, "번호 충돌은 여전히 거부돼야 한다"
        captured = capsys.readouterr()
        assert "ZQ-1000" not in captured.err, "4자리 형식 위반 ID를 제안하면 안 된다"
        assert "소진" in captured.err, "프리픽스 소진 사실이 명시돼야 한다"
        assert "사람의 결정" in captured.err, "사람의 결정이 필요함을 알려야 한다"
        assert "001~999" in captured.err, captured.err


# ──────────────────────────────────────────────────────────────────────
# HARN-73 — 상위(최대+1) 소진 시 "한 번도 쓰인 적 없는" 가장 낮은 번호로 폴백
#
# 사고 경위(2026-09-06): EOS-99가 원격 브랜치에 선점되자 제안기가 None을 내고 cmd_add가
# "00~99번을 모두 소진"이라고 보고했다. 실측은 59/100 사용·40개는 한 번도 안 쓰임 —
# 오보고가 사람 결정 게이트(G-eos-task-prefix-exhausted)를 열었다.
# ──────────────────────────────────────────────────────────────────────


def _git(*argv: str, cwd: Path) -> str:
    result = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class TestSuggestNumberLowestUnusedFallback:
    """단위 — 2단계 제안기의 판정. 이력 조회는 호출 가능 객체로 주입한다."""

    def test_upper_exhausted_falls_back_to_lowest_never_used(self):
        """상위_소진_시_한_번도_안_쓰인_가장_낮은_번호를_제안한다"""
        taken = _taken_full("E1", range(44, 100))  # E1-44..E1-99 점유, 01..43 비어 있음
        verdict = cli._suggest_number("E1", taken, lambda _p: (set(), "ok"))
        assert verdict.suggestion == "E1-01"
        assert verdict.history == "ok" and verdict.max_used == 99
        assert verdict.free_lower[:3] == (1, 2, 3) and verdict.retired == ()

    def test_retired_numbers_are_skipped(self):
        """이력에_추가됐다_삭제된_번호는_건너뛴다 — 짧은 참조가 두 태스크를 가리키면 안 된다"""
        taken = _taken_full("E1", range(44, 100))
        verdict = cli._suggest_number("E1", taken, lambda _p: ({1, 2, 7}, "ok"))
        assert verdict.suggestion == "E1-03"
        assert verdict.retired == (1, 2, 7)

    def test_history_unavailable_yields_no_suggestion_but_lists_candidates(self):
        """이력_조회_불가면_제안하지_않고_후보만_돌려준다 — 모른다를 없다로 접지 않는다"""
        taken = _taken_full("E1", range(44, 100))
        verdict = cli._suggest_number("E1", taken, lambda _p: (None, "shallow"))
        assert verdict.suggestion is None and verdict.history == "unavailable"
        assert verdict.history_reason == "shallow"
        assert verdict.free_lower == tuple(range(1, 44))

    def test_upper_available_does_not_consult_history(self):
        """상위_여유_시_기존_동작(최대+1)이며_이력을_조회하지_않는다 — HARN-21 불변"""

        def _boom(_prefix: str) -> tuple[set[int], str]:
            raise AssertionError("상위 여유 시 이력 조회 금지")

        taken = _taken_full("E1", range(1, 5))
        verdict = cli._suggest_number("E1", taken, _boom)
        assert verdict.suggestion == "E1-05" and verdict.history == "not_needed"

    def test_01_to_99_full_extends_to_three_digit_not_none(self):
        """[HARN-97] 01~99가_전부_점유면_None_대신_3자리(E1-100)를_제안한다"""
        taken = _taken_full("E1", range(1, 100))
        verdict = cli._suggest_number("E1", taken, lambda _p: (set(), "ok"))
        assert verdict.suggestion == "E1-100" and verdict.free_lower == ()
        assert verdict.history == "extended"

    def test_all_free_numbers_retired_extends_to_three_digit_with_retired_list(self):
        """[HARN-97] 빈_번호가_전부_이력상_사용이면_3자리로_확장하고_retired에_그_목록이_남는다"""
        taken = _taken_full("E1", range(44, 100))
        verdict = cli._suggest_number("E1", taken, lambda _p: (set(range(1, 44)), "ok"))
        assert verdict.suggestion == "E1-100" and verdict.history == "extended"
        assert len(verdict.retired) == 43

    def test_999_used_returns_none(self):
        """[HARN-97] 001~999가_전부_점유돼야_비로소_None — 4자리 날조 금지는 그대로"""
        taken = _taken_full("E1", range(1, 1000))
        verdict = cli._suggest_number("E1", taken, lambda _p: (set(), "ok"))
        assert verdict.suggestion is None and verdict.free_lower == ()
        assert verdict.history == "ok"


class TestHistoricallyUsedNumbers:
    """실 git 이력 — 추가됐다 삭제된 번호가 잡히고, 조회 불가·shallow는 None(fail-closed)."""

    def test_deleted_three_digit_task_file_number_is_reported(self, git_repo: Path):
        """[HARN-97] 3자리(100 이상) 번호의 삭제된 태스크 파일도 이력에서 잡힌다 —
        `_HISTORY_TASK_FILE_RE`를 `\\d{2}`에서 `\\d{2,3}`로 넓힌 변경의 직접 검증."""
        tasks = git_repo / "backlog" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "ZQ-100-old.yaml").write_text("id: ZQ-100-old\n", encoding="utf-8")
        _git("add", ".", cwd=git_repo)
        _git("commit", "-m", "add ZQ-100", cwd=git_repo)
        (tasks / "ZQ-100-old.yaml").unlink()
        _git("add", "-A", cwd=git_repo)
        _git("commit", "-m", "rm ZQ-100", cwd=git_repo)
        assert cli._historically_used_numbers(git_repo, "ZQ") == ({100}, "ok")

    def test_deleted_task_file_number_is_reported(self, git_repo: Path):
        """삭제된_태스크_파일의_번호도_이력에서_잡힌다"""
        tasks = git_repo / "backlog" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "ZQ-07-old.yaml").write_text("id: ZQ-07-old\n", encoding="utf-8")
        _git("add", ".", cwd=git_repo)
        _git("commit", "-m", "add ZQ-07", cwd=git_repo)
        (tasks / "ZQ-07-old.yaml").unlink()
        _git("add", "-A", cwd=git_repo)
        _git("commit", "-m", "rm ZQ-07", cwd=git_repo)
        assert cli._historically_used_numbers(git_repo, "ZQ") == ({7}, "ok")
        assert cli._historically_used_numbers(git_repo, "ZX") == (set(), "ok")

    def test_renamed_task_file_destination_counts_as_used(self, git_repo: Path):
        """git_mv로_번호를_얻은_파일도_이력에_잡힌다 — rename 탐지가 켜지면 R로 분류돼 A 필터에서
        빠지므로 --no-renames가 필요하다(PR #1002 Codex P2)"""
        tasks = git_repo / "backlog" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "ZQ-07-old.yaml").write_text("id: ZQ-07-old\n", encoding="utf-8")
        _git("add", ".", cwd=git_repo)
        _git("commit", "-m", "add ZQ-07", cwd=git_repo)
        _git("mv", "backlog/tasks/ZQ-07-old.yaml", "backlog/tasks/ZQ-08-renamed.yaml", cwd=git_repo)
        _git("commit", "-m", "mv ZQ-07 -> ZQ-08", cwd=git_repo)
        (tasks / "ZQ-08-renamed.yaml").unlink()
        _git("add", "-A", cwd=git_repo)
        _git("commit", "-m", "rm ZQ-08", cwd=git_repo)
        assert cli._historically_used_numbers(git_repo, "ZQ") == ({7, 8}, "ok")

    def test_git_failure_yields_none_with_exception_name(self, git_repo: Path, monkeypatch):
        """git_실패는_None_+_예외_타입명 — 예외를 빈 집합으로 위장하지 않는다(침묵 실패 금지)"""

        def _raise(*_args, **_kwargs):
            raise OSError("git 없음")

        monkeypatch.setattr(cli.remote_claims, "_git", _raise)
        assert cli._historically_used_numbers(git_repo, "ZQ") == (None, "exception:OSError")

    def test_shallow_repository_yields_none(self, git_repo: Path, monkeypatch):
        """shallow_클론은_이력이_불완전하므로_None"""
        real = cli.remote_claims._git

        def _fake(root, *argv, **kwargs):
            if argv[:2] == ("rev-parse", "--is-shallow-repository"):
                return subprocess.CompletedProcess(
                    args=["git", *argv], returncode=0, stdout="true\n", stderr=""
                )
            return real(root, *argv, **kwargs)

        monkeypatch.setattr(cli.remote_claims, "_git", _fake)
        assert cli._historically_used_numbers(git_repo, "ZQ") == (None, "shallow")


def _add_cli(task_id: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "프리픽스 소진 테스트",
            "--track",
            "math-completion",
            "--stage",
            "S2",
        ]
    )


class TestCmdAddFallbackMessages:
    """CLI 종단 — 상위 소진 시 문구가 실측치를 말하고, 이력 불가 시 수동 절차를 안내한다."""

    def _upper_exhausted(self, monkeypatch) -> None:
        fake_taken = _taken_full("ZQ", range(44, 100))  # ZQ-44..ZQ-99 점유, 하위 43개 비어 있음
        monkeypatch.setattr(
            cli, "_taken_id_numbers", lambda root, backlog, policy: dict(fake_taken)
        )

    def test_upper_exhausted_collision_suggests_lowest_never_used(
        self, seeded_repo, monkeypatch, capsys
    ):
        """상위_소진_충돌은_'모두_소진'이_아니라_미사용_최저_번호를_제안한다"""
        self._upper_exhausted(monkeypatch)
        monkeypatch.setattr(cli, "_historically_used_numbers", lambda root, prefix: ({1, 2}, "ok"))
        capsys.readouterr()
        assert _add_cli("ZQ-99-my-new-slug") == 1
        err = capsys.readouterr().err
        assert "ZQ-03" in err and "미사용" in err, err
        assert "ZQ-100" not in err and "모두 소진" not in err, err

    def test_shallow_clone_prescribes_unshallow_not_manual_log(
        self, seeded_repo, monkeypatch, capsys
    ):
        """shallow면_unshallow_후_재실행을_안내하고_수동_git_log·--id_추론은_안내하지_않는다"""
        self._upper_exhausted(monkeypatch)
        monkeypatch.setattr(
            cli, "_historically_used_numbers", lambda root, prefix: (None, "shallow")
        )
        capsys.readouterr()
        assert _add_cli("ZQ-99-my-new-slug") == 1
        err = capsys.readouterr().err
        assert "ZQ-01" in err and "unshallow" in err and "다시 실행" in err, err
        assert "git log" not in err and "수동 확인" not in err, err
        assert "가장 낮은" not in err and "모두 소진" not in err, err

    def test_other_history_failure_names_reason_and_asks_rerun(
        self, seeded_repo, monkeypatch, capsys
    ):
        """git_오류면_사유(예외_타입명)를_말하고_해소_후_재실행을_안내한다"""
        self._upper_exhausted(monkeypatch)
        monkeypatch.setattr(
            cli, "_historically_used_numbers", lambda root, prefix: (None, "exception:OSError")
        )
        capsys.readouterr()
        assert _add_cli("ZQ-99-my-new-slug") == 1
        err = capsys.readouterr().err
        assert "exception:OSError" in err and "다시 실행" in err, err
        assert "unshallow" not in err and "git log" not in err, err
