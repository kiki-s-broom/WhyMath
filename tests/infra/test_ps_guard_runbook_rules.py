"""런북 코드펜스 가드 — 규칙별 변별력 동결 (OPS-57).

**왜 이 테스트가 필요한가**: `check_ps_scripts.py`는 실행 검증이 구조적으로 불가능한
구간(Windows 전용 PowerShell)의 유일한 방어선이다. 그런 도구가 조용히 무력해지면
"검사가 없다"가 아니라 **"검사가 통과했다"로 위장**된다 — 이 저장소가 반복해서 당한
형태다(2026-07-17 logconfig `delay:true`로 캡처 파일 미생성 → 사전 `Test-Path`가 정상
상태에서도 항상 False).

그래서 규칙마다 **위반 샘플 exit 1 · 정상 샘플 exit 0** 양쪽을 고정한다. 한쪽만 보면
"항상 통과"·"항상 거부"가 그대로 통과한다.

사고 경위(2026-09-01 관여도 트리아지 게이트 clear 런북): 결함 7건 중 3건이 여기서
고정하는 형태였다. 라이브에서 2건(CP949·main 직접 push)이 터졌고 리뷰가 2건을 더
찾았다(§7-3의 두 번째 main push · `reset --hard` 청결 확인 부재).
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_GUARD = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ops" / "check_ps_scripts.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_ps_scripts", _GUARD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load()


def _md(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    p = tmp_path / "runbook.md"
    p.write_text(body, encoding="utf-8")
    return p


def _fence(cmds: str) -> str:
    return f"# 런북\n\n```powershell\n{cmds}\n```\n"


class TestFenceExtraction:
    """① 코드펜스를 실제로 읽는가 — 이것이 0이면 아래 규칙 전부가 공허하게 통과한다."""

    def test_powershell_fence_is_found(self, tmp_path: pathlib.Path) -> None:
        blocks = guard.iter_powershell_blocks(_fence("Write-Host hi"))
        assert len(blocks) == 1
        assert "Write-Host hi" in blocks[0][1]

    def test_non_powershell_fence_is_ignored(self, tmp_path: pathlib.Path) -> None:
        """bash 펜스까지 PowerShell 규칙으로 재면 오탐이 쏟아진다."""
        assert guard.iter_powershell_blocks("```bash\ngit push origin main\n```") == []

    def test_document_without_fences_yields_nothing(self) -> None:
        assert guard.iter_powershell_blocks("# 제목\n\n본문뿐이다.\n") == []


class TestProtectedBranchPush:
    """④ `git push origin main`은 GH013으로 거부된다 — 절차의 마지막이 항상 실패한다."""

    def test_direct_main_push_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("git push origin main")))
        assert any("보호 브랜치 직접 push" in i for i in issues)

    def test_branch_push_passes(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("git push -u origin gates/relevance-triage-clear"))
        )
        assert issues == []

    def test_master_is_also_protected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("git push origin master")))
        assert any("보호 브랜치 직접 push" in i for i in issues)


class TestResetHardNeedsCleanCheck:
    """⑤ 미커밋 작업분을 무증상으로 지우는 형태 — 2026-08-10 사고 유형."""

    def test_bare_reset_hard_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("git checkout main\ngit reset --hard origin/main"))
        )
        assert any("git status --porcelain" in i for i in issues)

    def test_clean_check_in_the_same_block_is_not_protection(self, tmp_path: pathlib.Path) -> None:
        """초판이 이 형태를 축복했다 — codex P1 지적 수용 후 뒤집었다.

        붙여넣으면 PowerShell이 status를 찍고 **출력과 무관하게** 곧바로 reset을
        실행한다. 사람이 볼 틈이 없으므로 보호가 아니다. 오히려 "확인했다"는
        착각만 준다.
        """
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("git status --porcelain\ngit reset --hard origin/main"))
        )
        assert any("차단력 있는" in i for i in issues)

    def test_fail_closed_conditional_in_same_block_passes(self, tmp_path: pathlib.Path) -> None:
        """같은 블록이어도 비어있지 않을 때 중단하면 보호다 — 대안 경로를 막지 않는다."""
        issues = guard.check_runbook_markdown(
            _md(
                tmp_path,
                _fence(
                    'if (git status --porcelain) { throw "작업 트리가 비어 있지 않다" }\n'
                    "git reset --hard origin/main"
                ),
            )
        )
        assert issues == []

    def test_clean_check_in_earlier_block_passes(self, tmp_path: pathlib.Path) -> None:
        """런북은 블록을 나눠 사람에게 확인을 시킨다 — 그 형태만 보호로 인정한다."""
        body = (
            _fence("git status --porcelain")
            + "\n확인 후:\n\n"
            + _fence("git reset --hard origin/main")
        )
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_clean_check_after_the_reset_does_not_count(self, tmp_path: pathlib.Path) -> None:
        """순서가 뒤바뀌면 보호가 아니다 — 지운 뒤에 확인해 봐야 늦다."""
        body = _fence("git reset --hard origin/main") + "\n" + _fence("git status --porcelain")
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("git status --porcelain" in i for i in issues)


class TestPythonPipeNeedsUtf8:
    """⑥ 한국어 Windows에서 파이프 stdout은 cp949 — UnicodeEncodeError로 죽는다."""

    def test_piped_python_without_utf8_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence('python x.py | Select-String "foo"'))
        )
        assert any("UTF-8" in i for i in issues)

    def test_utf8_in_earlier_block_passes(self, tmp_path: pathlib.Path) -> None:
        body = _fence('$env:PYTHONUTF8="1"') + "\n" + _fence('python x.py | Select-String "foo"')
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_console_output_encoding_also_counts(self, tmp_path: pathlib.Path) -> None:
        body = _fence(
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
            'python x.py | Select-String "foo"'
        )
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_unpiped_python_needs_nothing(self, tmp_path: pathlib.Path) -> None:
        """콘솔로 바로 내보내면 이 결함이 나지 않는다 — 요구하면 변별력이 사라진다."""
        assert guard.check_runbook_markdown(_md(tmp_path, _fence("python x.py"))) == []

    def test_placeholder_angle_brackets_are_not_redirects(self, tmp_path: pathlib.Path) -> None:
        """실측 오탐(2026-09-01): `--until <종료YYYY-MM-DD> --next ...`를 리다이렉트로 오인.

        오탐이 있는 가드는 사람이 끄게 만든다 — 이 케이스는 반드시 통과해야 한다.
        """
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("python -m x --since <시작YYYY-MM-DD> --until <종료YYYY-MM-DD>"))
        )
        assert issues == []

    def test_real_redirect_is_still_caught(self, tmp_path: pathlib.Path) -> None:
        """오탐을 줄이느라 진짜 리다이렉트까지 놓치면 규칙이 죽는다."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("python x.py > out.txt")))
        assert any("UTF-8" in i for i in issues)


class TestBlockquotedFences:
    """① 인용문 안의 펜스도 붙여넣어 실행된다 — 못 보면 가드가 공허하게 통과한다.

    실측(2026-09-01): 런북 §7 롤백 절차가 전부 인용문 안에 있었고 그 안에
    `git reset --hard`가 있는데 가드가 한 줄도 보지 못했다. 대상을 하나도 못 찾은
    전수 가드는 "위반 0건"과 "검사 못 함"이 같은 화면을 낸다.
    """

    def test_blockquoted_fence_is_parsed(self, tmp_path: pathlib.Path) -> None:
        body = "> 설명:\n>\n> ```powershell\n> git push origin main\n> ```\n"
        assert len(guard.iter_powershell_blocks(body)) == 1

    def test_violation_inside_blockquote_is_caught(self, tmp_path: pathlib.Path) -> None:
        body = "> ```powershell\n> git push origin main\n> ```\n"
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("보호 브랜치 직접 push" in i for i in issues)

    def test_nested_blockquote_prefix_is_stripped(self, tmp_path: pathlib.Path) -> None:
        body = ">> ```powershell\n>> git reset --hard origin/main\n>> ```\n"
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("차단력 있는" in i for i in issues)


class TestUtf8MustBeEnabling:
    """③ 토큰 등장이 아니라 **활성화하는 대입**이어야 한다 (codex P2)."""

    def test_disabling_assignment_is_not_protection(self, tmp_path: pathlib.Path) -> None:
        """`="0"`이 보호로 계상되면 정확히 이 규칙이 막으려는 오류가 그대로 난다."""
        body = _fence('$env:PYTHONUTF8="0"') + "\n" + _fence('python x.py | Select-String "a"')
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("UTF-8" in i for i in issues)

    def test_mention_in_a_comment_is_not_protection(self, tmp_path: pathlib.Path) -> None:
        body = (
            _fence("# PYTHONUTF8 을 설정해야 한다")
            + "\n"
            + _fence('python x.py | Select-String "a"')
        )
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("UTF-8" in i for i in issues)

    def test_enabling_assignment_still_passes(self, tmp_path: pathlib.Path) -> None:
        """좁히다가 정상 형태까지 막으면 규칙이 죽는다."""
        body = _fence('$env:PYTHONUTF8="1"') + "\n" + _fence('python x.py | Select-String "a"')
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_ioencoding_value_must_be_utf8(self, tmp_path: pathlib.Path) -> None:
        body = (
            _fence('$env:PYTHONIOENCODING="cp949"')
            + "\n"
            + _fence('python x.py | Select-String "a"')
        )
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("UTF-8" in i for i in issues)


class TestAutoVariableAssignment:
    """⑦(OPS-60) 자동/예약 변수 대입 — 대입은 거부되는데 $home은 이미 참이라 위장 성공."""

    @pytest.mark.parametrize(
        "name", ["home", "host", "input", "error", "args", "pwd", "matches", "profile"]
    )
    def test_assignment_to_each_reserved_name_is_rejected(
        self, tmp_path: pathlib.Path, name: str
    ) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence(f'${name} = "x"')))
        assert any("자동/예약 변수 대입" in i for i in issues), name

    def test_case_insensitive_match(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('$HOME = "x"')))
        assert any("자동/예약 변수 대입" in i for i in issues)

    def test_similarly_named_variable_passes(self, tmp_path: pathlib.Path) -> None:
        """`$homeDir`는 다른 변수다 — 접두 일치만으로 오탐하면 안 된다."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('$homeDir = "C:\\temp"')))
        assert issues == []

    def test_comparison_is_not_assignment(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("if ($home -eq $null) {}")))
        assert issues == []

    def test_property_assignment_on_the_variable_passes(self, tmp_path: pathlib.Path) -> None:
        """`$Host.UI...`는 $Host 재대입이 아니라 멤버 대입 — 흔한 정상 패턴이라 통과해야 한다."""
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence('$Host.UI.RawUI.WindowTitle = "WhyMath"'))
        )
        assert issues == []

    def test_reading_the_variable_passes(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("Write-Host $args[0]")))
        assert issues == []


class TestInvokeWebRequestNeedsBasicParsing:
    """⑧(OPS-60) -UseBasicParsing 누락 — PS 5.1 IE 파싱이 무인 실행을 대화형으로 멈춘다."""

    def test_missing_flag_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence('Invoke-WebRequest "http://x/health"'))
        )
        assert any("-UseBasicParsing" in i for i in issues)

    def test_alias_iwr_is_also_checked(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('iwr "http://x/health"')))
        assert any("-UseBasicParsing" in i for i in issues)

    def test_flag_present_passes(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence('Invoke-WebRequest -UseBasicParsing "http://x/health"'))
        )
        assert issues == []

    def test_unrelated_command_passes(self, tmp_path: pathlib.Path) -> None:
        assert guard.check_runbook_markdown(_md(tmp_path, _fence("Write-Host hi"))) == []


class TestCatchResponseNeedsExistenceCheck:
    """⑨(OPS-60) catch 안 $_.Exception.Response 무가드 접근 — 전송 계층 오류에서 null."""

    def test_unguarded_property_access_is_rejected(self, tmp_path: pathlib.Path) -> None:
        body = _fence(
            "try {\n  Invoke-WebRequest -UseBasicParsing $u\n} catch {\n"
            "  $_.Exception.Response.StatusCode\n}"
        )
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("Exception.Response" in i for i in issues)

    def test_guarded_by_earlier_if_in_same_block_passes(self, tmp_path: pathlib.Path) -> None:
        body = _fence(
            "try {\n  Invoke-WebRequest -UseBasicParsing $u\n} catch {\n"
            "  if ($_.Exception.Response) {\n"
            "    $_.Exception.Response.StatusCode\n"
            "  }\n}"
        )
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_bare_mention_without_dot_access_passes(self, tmp_path: pathlib.Path) -> None:
        """대입만 하고 프로퍼티 체인으로 파고들지 않으면 이 좁은 규칙의 대상이 아니다."""
        body = _fence("catch {\n  $resp = $_.Exception.Response\n}")
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_guard_in_later_block_does_not_retroactively_protect(
        self, tmp_path: pathlib.Path
    ) -> None:
        body = (
            _fence("catch {\n  $_.Exception.Response.StatusCode\n}")
            + "\n"
            + _fence("if ($_.Exception.Response) {}")
        )
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("Exception.Response" in i for i in issues)


class TestFenceStartingWithBareElse:
    """④(OPS-60, 좁힌 채택) 펜스가 else/elseif로 시작 — 대응하는 if가 있을 수 없다."""

    def test_fence_starting_with_else_is_rejected(self, tmp_path: pathlib.Path) -> None:
        body = _fence("if ($x) {\n  Write-Host a\n}") + "\n" + _fence("else {\n  Write-Host b\n}")
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("else" in i and "펜스가" in i for i in issues)

    def test_fence_starting_with_elseif_is_rejected(self, tmp_path: pathlib.Path) -> None:
        body = _fence("elseif ($y) {\n  Write-Host b\n}")
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("펜스가" in i for i in issues)

    def test_if_else_in_the_same_fence_passes(self, tmp_path: pathlib.Path) -> None:
        body = _fence("if ($x) {\n  Write-Host a\n} else {\n  Write-Host b\n}")
        assert guard.check_runbook_markdown(_md(tmp_path, body)) == []

    def test_closing_brace_before_else_is_still_caught(self, tmp_path: pathlib.Path) -> None:
        """`} else {`처럼 닫는 중괄호가 붙어 시작해도 잡는다(`\\}?` 허용)."""
        body = _fence("if ($x) {\n  Write-Host a") + "\n" + _fence("} else {\n  Write-Host b\n}")
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("펜스가" in i for i in issues)

    def test_first_fence_is_also_checked(self, tmp_path: pathlib.Path) -> None:
        """맨 처음 펜스가 else로 시작해도(앞선 펜스 자체가 없어도) 구조적으로 깨져 있다."""
        body = _fence("else {\n  Write-Host b\n}")
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("펜스가" in i for i in issues)


class TestShellPromptPrefixInCode:
    """⑩(OPS-73) 셀 프롬프트 접두(`$ `·`PS>`·`PS C:\\...>`)가 실행용 코드로 남음."""

    def test_dollar_space_prefix_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("$ git status")))
        assert any("셀 프롬프트 접두" in i for i in issues)

    def test_ps_gt_prefix_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("PS> git status")))
        assert any("셀 프롬프트 접두" in i for i in issues)

    def test_ps_drive_prompt_prefix_is_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence(r"PS C:\Users\kiki\Desktop\__AI\WhyMath> git status"))
        )
        assert any("셀 프롬프트 접두" in i for i in issues)

    def test_variable_assignment_passes(self, tmp_path: pathlib.Path) -> None:
        """`$name = ...`는 정상 코드다 — `$` 뒤에 이름이 바로 오면 프롬프트가 아니다."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('$sha = "abc1234"')))
        assert issues == []

    def test_pipeline_variable_passes(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("Write-Host $_.Name")))
        assert issues == []


class TestArrowJudgementWordInCode:
    """⑪(OPS-73) 화살표(→/←) 뒤 판정어 — 실행 결과·증거를 실행용 펜스에 그대로 인용."""

    def test_incident_line_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """★ 실측 사고 재현 — 화살표 뒤 텍스트가 git의 두 번째 인자로 파싱된다."""
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("git cat-file -e origin/main:backlog/gates.yaml  → 존재"))
        )
        assert any("화살표" in i for i in issues)

    def test_left_arrow_is_also_checked(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("결과 ← 성공")))
        assert any("화살표" in i for i in issues)

    def test_arrow_inside_comment_passes(self, tmp_path: pathlib.Path) -> None:
        """주석 안의 화살표는 면제(acceptance③) — strip_noncode가 이미 지운다."""
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("# 흐름: 입력 → 완료 순서로 진행된다\nWrite-Host hi"))
        )
        assert issues == []

    def test_arrow_inside_string_literal_passes(self, tmp_path: pathlib.Path) -> None:
        """문자열 리터럴 안의 화살표도 면제(acceptance③)."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('Write-Host "상태: → 완료"')))
        assert issues == []

    def test_arrow_without_judgement_word_passes(self, tmp_path: pathlib.Path) -> None:
        """판정어가 없으면 통과 — 오탐을 좁히는 쪽(acceptance③)."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("# A → B 흐름도")))
        assert issues == []


class TestCommitHashLineInCode:
    """⑫(OPS-73) 커밋 해시+메시지 형태의 줄 — 실행 결과를 그대로 인용."""

    def test_incident_line_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """★ 실측 사고 재현 — 메시지의 (#1234)가 PowerShell에서 식으로 파싱된다."""
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("b64f470d  OPS-72: 실행용 코드펜스 증거 혼입 가드 (#1065)"))
        )
        assert any("커밋 해시" in i for i in issues)

    def test_full_length_hash_is_also_rejected(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(
            _md(tmp_path, _fence("c7ada85a4db52de87d1ef245f7ba3d4997a10d26 fix(backup): OPS-64"))
        )
        assert any("커밋 해시" in i for i in issues)

    def test_variable_assignment_with_hash_string_passes(self, tmp_path: pathlib.Path) -> None:
        """줄이 `$`로 시작하는 변수 대입은 해시가 값이어도 통과한다."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence('$sha = "b64f470d"')))
        assert issues == []

    def test_short_token_below_minimum_length_passes(self, tmp_path: pathlib.Path) -> None:
        """7자 미만은 커밋 해시로 보기엔 짧다 — 오탐을 좁히는 쪽."""
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("ab12cd Write-Host hi")))
        assert issues == []

    def test_ordinary_command_passes(self, tmp_path: pathlib.Path) -> None:
        issues = guard.check_runbook_markdown(_md(tmp_path, _fence("Write-Host hi")))
        assert issues == []


class TestRepositoryAssetsStayGreen:
    """기존 자산 전건이 새 규칙에서 green이어야 CI 차단으로 승격할 수 있다 (acceptance ③)."""

    def test_all_repo_targets_pass(self) -> None:
        root = _GUARD.resolve().parents[2]
        targets = sorted((root / "scripts").rglob("*.ps1")) + sorted((root / "docs").rglob("*.md"))
        targets += sorted((root / ".claude" / "commands").glob("*.md"))
        offenders: dict[str, list[str]] = {}
        for t in targets:
            issues = (
                guard.check_runbook_markdown(t)
                if t.suffix.lower() == ".md"
                else guard.check_file(t)
            )
            if issues:
                offenders[str(t.relative_to(root))] = issues
        assert not offenders, f"기존 자산 위반: {offenders}"


class TestCommandsDirIsScannedByDefault:
    """acceptance① 배선 — `main()`이 인자 없이 돌 때 `.claude/commands/*.md`도 대상이다."""

    def test_main_includes_commands_dir_without_explicit_args(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        root = tmp_path
        (root / "scripts").mkdir()
        (root / "docs").mkdir()
        commands_dir = root / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        offender = commands_dir / "example.md"
        offender.write_text(_fence("git cat-file -e origin/main:x  → 존재"), encoding="utf-8")

        monkeypatch.chdir(root)
        code = guard.main(["check_ps_scripts.py"])
        out = capsys.readouterr().out
        assert code == 1, "새 규칙 위반이 있는데 exit 0이면 배선이 안 된 것"
        assert "example.md" in out

    def test_absent_commands_dir_does_not_crash(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`.claude/commands`가 없는 체크아웃(예: 부분 clone)에서도 죽지 않는다."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "docs").mkdir()
        monkeypatch.chdir(tmp_path)
        assert guard.main(["check_ps_scripts.py"]) == 0


class TestHistoricalIncidentIsCaught:
    """평가 — 이 가드가 **실제 사고를 잡았을 것인가**.

    2026-09-01 관여도 트리아지 런북의 결함을 재구성해 검출을 확인한다. 규칙이 사고를
    잡지 못하면 그 규칙은 사고와 무관한 것을 재고 있는 것이다.
    """

    def test_the_three_mechanical_defects_are_all_caught(self, tmp_path: pathlib.Path) -> None:
        body = (
            _fence('python scripts/harness/backlog.py gates list | Select-String "gate"')
            + "\n"
            + _fence('git add backlog/\ngit commit -m "clear"\ngit push origin main')
            + "\n"
            + _fence("git checkout main\ngit reset --hard origin/main")
        )
        issues = guard.check_runbook_markdown(_md(tmp_path, body))
        assert any("UTF-8" in i for i in issues), "CP949 결함 미검출"
        assert any("보호 브랜치 직접 push" in i for i in issues), "main 직접 push 미검출"
        assert any("git status --porcelain" in i for i in issues), "reset --hard 결함 미검출"

    @pytest.mark.parametrize("cmd", ["git push origin main", "git reset --hard origin/main"])
    def test_bash_fence_is_out_of_scope(self, tmp_path: pathlib.Path, cmd: str) -> None:
        """정직한 한계 — bash 펜스는 이 가드의 대상이 아니다(리눅스 세션이 직접 실행).

        이 테스트는 통과를 요구하는 것이 아니라 **범위를 명시적으로 고정**한다. 나중에
        bash까지 넓히기로 하면 이 테스트가 먼저 실패해 결정을 강제한다.
        """
        assert guard.check_runbook_markdown(_md(tmp_path, f"```bash\n{cmd}\n```\n")) == []
