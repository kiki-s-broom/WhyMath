"""사람이 **복사해 실행하는** clear 명령이 주체 플래그를 달고 있는가 (HARN-60 배선).

**왜 이 파일이 있는가 — 기록이 없는 것보다 나쁜 상태**

`HARN-60`이 `--as`를 만들어도, Kiki가 실제로 복사하는 명령(보드의 '해소 명령', 런북·도시에의
복붙 블록)이 그 플래그를 빼먹으면 **사람이 실행한 clear가 대장에 `cleared_by: claude`로 남는다.**
그건 미기록보다 나쁘다 — 대장이 "에이전트가 닫았다"고 *적극적으로 거짓을* 말하고, 준수 감사는
그 거짓을 근거로 판정한다. 즉 계약(`--as`)만 만들고 **집행 지점(복붙 경로)을 안 고치면 HARN-60은
목적을 정확히 거꾸로 달성한다**(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").

지적: PR #978 codex P2.

**설계 원칙 3가지**

1. **문자열 금지 목록이 아니라 산출물을 본다** — 보드는 소스의 템플릿 문자열이 아니라
   `build_board`가 실제로 낸 HTML을 검사한다. 소스를 어떻게 고쳐 쓰든 *나오는 명령*이 옳아야 한다.
2. **스캔 0건은 실패다** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다. 파일별로
   "최소 1건은 찾았다"를 함께 못박는다.
3. **면제는 이유와 함께 열거한다** — 자리표시자(`<id>`)만 있는 일반 usage와 날짜가 박힌 과거
   스냅샷은 복붙 대상이 아니므로 제외하되, 그 목록을 여기 적어 다음 사람이 판단을 되짚을 수 있게 한다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import board
import store

_REPO = Path(__file__).resolve().parents[2]

# 사람이 그대로 복사해 실행하는 clear 명령이 사는 파일 — 여기 있는 구체 게이트 ID 명령은
# 전부 `--as`를 달아야 한다.
_HUMAN_COPY_PASTE_FILES = [
    "scripts/demo/README.md",
    "docs/ops/eos_relevance_triage_gate_runbook.md",
    "docs/standards/crosswalk_gate_contract.md",
    "docs/standards/eos_verification_design_v1.md",
    "docs/data/misconception_crosslink_review_dossier.md",
    # MGMT-04(2026-09-07) — 변호사 자문 브리핑 §8의 게이트 clear 명령.
    # 초판(PR #1038)이 --as·--no-base를 모두 빠뜨렸는데 이 스캐너가 못 잡았다: 파일이
    # 목록에 없으면 가드는 그 파일에 대해 아무것도 지키지 않으면서 초록을 낸다.
    "docs/legal/export_prediction_disclosure_counsel_brief.md",
    # HARN-83(2026-09-08) — 저장소 전수 분류에서 드러난 미등재 사람용 명령 2건.
    # 목록이 손으로 관리되는 한 이런 누락은 계속 생기므로, 아래
    # `TestEveryRunnableClearCommandIsTriaged`가 "어느 목록에도 없는 명령"을 red로 만든다.
    ".claude/commands/demo-doctor.md",
    "docs/ops/ip_separation_evidence_gate_runbook.md",
]

# `gates clear` 뒤에 **구체 게이트 ID**(G-로 시작)가 오는 형태만 잡는다.
# `<id>`·`<G-id>` 자리표시자는 실행 대상이 아니라 문법 설명이므로 애초에 매치되지 않는다.
#
# HARN-83 — 이 정규식은 두 가지로 뚫려 있었다. 원형: `r"gates clear\s+(G-...)((?:\s+\S+)*)"`
#
#   ⓐ **tail이 개행을 넘는다**: `\s`가 개행을 포함하므로 `(?:\s+\S+)*`가 명령의 나머지 인자가
#      아니라 *파일의 나머지 전부*를 삼켰다. 그래서 파일 어딘가에 `--as`가 **산문으로라도**
#      한 번 나오면 `"--as" not in tail`이 통과한다 — 가드가 명령을 검사하지 못한다.
#      실측(2026-09-07): 이 목록에 `export_prediction_disclosure_counsel_brief.md`를 등재한 뒤
#      그 §8 명령에서 `--as kiki`를 지우는 뮤테이션을 넣었는데 **RED가 나오지 않았다** —
#      같은 파일 산문의 "`--as {kiki,partner}`" 설명이 tail에 삼켜졌기 때문이다.
#   ⓑ **뒤 명령까지 먹는다**: 삼킨 tail 안에 다음 명령이 들어가므로 `finditer`가 파일당 사실상
#      1건만 낸다. `scripts/demo/README.md`에는 clear 명령이 2건인데 원형은 1건만 봤다.
#
# 고침: 공백류를 `[^\S\n]`(개행 제외)로 바꿔 tail을 **같은 줄**로 묶는다.
#
# 그리고 앞에 `backlog.py`를 **요구**한다 — 실행 가능한 명령과 산문 인용을 가르는 축이다.
# 실측: `eos_verification_design_v1.md:172`는 문장 중간의 `` `gates clear G-...` `` 인용이라
# 플래그가 없는 것이 정상인데, 줄 한정만 하면 이것이 오탐으로 잡힌다. 저장소 전수 확인 결과
# *실행 형태는 전부* `backlog.py`를 포함하므로(별칭·`-m` 형태 0건) 이 요구는 사각을 만들지 않는다.
_CONCRETE_CLEAR = re.compile(
    r"backlog\.py[^\S\n]+gates clear[^\S\n]+(G-[A-Za-z0-9-]+)((?:[^\S\n]+\S+)*)"
)

# 면제 — 복붙 대상이 아닌 곳. 이유를 함께 남긴다(만료 없는 예외 금지의 정신).
_EXEMPT = {
    # 날짜가 박힌 과거 스냅샷 — 고치면 그때의 기록을 사후 수정하는 것이 된다.
    "docs/strategy/human_bottleneck_status_2026-07-26.md": "2026-07-26 시점 스냅샷(역사 보존)",
    # 결정 로그 — 당시 실행된 명령을 그대로 인용한 것이라 수정 대상이 아니다.
    "MEMORY.md": "결정 로그(당시 인용)",
    # ── HARN-83(2026-09-08) 전수 분류 ─────────────────────────────────────────
    # **에이전트가 실행하는 명령** — `--as`는 사람 전용 플래그다(담당자가 claude면
    # `--as claude`라는 선택지 자체가 없다·`board.py`의 `g.assignee !== 'claude'` 참조).
    # 여기에 `--as`를 요구하면 오히려 틀린 명령을 만든다. **이 항목이 저장소 전수 스캔을
    # 채택하지 않은 이유다** — 정규식은 "누가 실행하는가"를 볼 수 없고, 그 구분은 사람이
    # 목록으로만 표현할 수 있다.
    "docs/architecture/db_backup_dr_runbook.md": "세션(에이전트)이 실행 — 본문이 '세션은 ... 실행하고'로 명시",
    # 날짜가 박힌 기록 — 선언·리뷰의 그때 상태를 사후 수정하지 않는다(위 스냅샷과 동일 원칙).
    "docs/strategy/domain_partner_handoff_2026-07.md": "2026-07 시점 핸드오프 기록",
    "docs/strategy/eos_transition_declaration_2026-08-30.md": "2026-08-30 전환 선언(서명 문서)",
    "docs/reviews/eos_number_collision_root_cause_2026-08-31.md": "2026-08-31 사고 리뷰 — 초안 명령을 *인용*한 것",
    # 백로그 대장 — 복붙 런북이 아니라 태스크 acceptance 본문이다. 이 태스크(MGMT-06)는
    # acceptance ⑥에서 정본 명령을 브리핑 §8로 넘겼고, acceptance는 append 전용이라
    # ④의 옛 문면을 고칠 수 없다(그 사실이 ⑥에 적혀 있다).
    "backlog/tasks/MGMT-06-export-prediction-disclosure-counsel.yaml": "백로그 acceptance 본문(복붙 런북 아님·정본은 브리핑 §8)",
}
# CLAUDE.md는 여기 없다: 구체 게이트 ID 명령이 0건이라(자리표시자 서술뿐) 면제할 대상 자체가
# 없다. 처음엔 넣었다가 `test_exemptions_are_real_and_named`가 유령 면제로 잡아냈다 —
# 가드가 자기 목록의 거짓을 잡은 사례라 기록으로 남긴다.


def _lines_with_concrete_clear(text: str) -> list[tuple[str, str]]:
    """(게이트 ID, 명령 꼬리) — 구체 ID를 가진 clear 명령만."""
    return [(m.group(1), m.group(2)) for m in _CONCRETE_CLEAR.finditer(text)]


# 증거 전체가 URL인 형태 — 마크다운 인라인 코드의 닫는 백틱이 붙어 올 수 있다.
_EVIDENCE_URL = re.compile(r'^"?https?://[^"\s]*"?$')


def _evidence_value(tail: str) -> str | None:
    """꼬리에서 `--evidence` 바로 뒤 토큰을 꺼낸다(없으면 None)."""
    parts = tail.split()
    for i, tok in enumerate(parts):
        if tok == "--evidence" and i + 1 < len(parts):
            return parts[i + 1].rstrip("`")
    return None


# ── 판정 함수 ───────────────────────────────────────────────────────────────
# 저장소 스캔과 **합성 픽스처가 같은 함수를 공유**한다. 판정을 테스트 메서드 안에 인라인으로
# 두면 그 판정문을 지우는 뮤테이션(`if "--as" not in tail:` → `if False:`)이 살아남는다 —
# 자기 단언을 지운 테스트는 자기가 못 잡기 때문이다(2026-09-08 실측 M6·M7 생존).
# 함수로 빼고 "위반 입력에서 실제로 위반을 보고하는가"를 별도로 못박으면 그 뮤테이션이 RED가 된다.


def _as_flag_violations(rel: str, text: str) -> list[str]:
    """`--as`가 없는 실행형 clear 명령."""
    return [
        f"{rel} :: gates clear {gate_id}"
        for gate_id, tail in _lines_with_concrete_clear(text)
        if "--as" not in tail
    ]


def _no_base_violations(rel: str, text: str) -> list[str]:
    """증거가 **링크뿐인데** `--no-base`가 없는 명령 — HARN-68이 반드시 exit 1로 거부한다."""
    out: list[str] = []
    for gate_id, tail in _lines_with_concrete_clear(text):
        value = _evidence_value(tail)
        if value is None or not _EVIDENCE_URL.match(value):
            continue
        if "--no-base" not in tail:
            out.append(f"{rel} :: gates clear {gate_id} --evidence {value}")
    return out


def _unclassified_files(found: dict[str, list[str]]) -> list[str]:
    """실행형 clear 명령이 있는데 사람용 목록에도 면제에도 없는 파일."""
    known = set(_HUMAN_COPY_PASTE_FILES) | set(_EXEMPT)
    return sorted(set(found) - known)


def _url_evidence_commands(rel: str, text: str) -> list[str]:
    """증거가 링크뿐인 명령 전건 — 검사 대상이 0건이 아님을 확인하는 데 쓴다."""
    return [
        f"{rel} :: {gate_id}"
        for gate_id, tail in _lines_with_concrete_clear(text)
        if (v := _evidence_value(tail)) is not None and _EVIDENCE_URL.match(v)
    ]


class TestHumanCopyPasteCommandsCarryTheFlag:
    """복붙 경로의 구체 clear 명령은 전부 `--as`를 단다."""

    def test_every_human_facing_command_has_as_flag(self):
        """사람용_복붙명령_전건에_주체플래그"""
        offenders: list[str] = []
        found_total = 0
        for rel in _HUMAN_COPY_PASTE_FILES:
            path = _REPO / rel
            assert path.exists(), f"대상 파일이 사라졌다 — 목록을 갱신하라: {rel}"
            hits = _lines_with_concrete_clear(path.read_text(encoding="utf-8"))
            # 파일별 0건도 실패다 — 파일이 개편돼 명령이 사라졌다면 이 목록이 낡은 것이고,
            # 그 상태로 통과시키면 가드가 아무것도 지키지 않으면서 초록을 낸다.
            assert hits, f"{rel}: 구체 clear 명령 0건 — 목록이 낡았거나 정규식이 깨졌다"
            found_total += len(hits)
            offenders.extend(_as_flag_violations(rel, path.read_text(encoding="utf-8")))
        assert found_total >= len(_HUMAN_COPY_PASTE_FILES), "스캔 대상이 비정상적으로 적다"
        assert not offenders, (
            "사람이 복사해 실행하는 clear 명령에 --as 가 없다 — 실행하면 대장에 "
            "cleared_by: claude(거짓 주체)가 남는다:\n  " + "\n  ".join(offenders)
        )

    def test_syntax_reference_shows_the_flag(self):
        """규약 정본(build_harness.md)의 *문법* 참조도 플래그를 노출한다.

        이 파일은 구체 게이트 ID가 아니라 `<id>` 자리표시자를 쓰므로 위 전수 스캔의 대상이
        아니다. 그러나 여기가 사람이 문법을 배우는 곳이라, 플래그가 안 보이면 복붙 명령을
        직접 쓸 때 빠뜨린다. 그래서 별도로 못박는다.
        """
        text = (_REPO / "docs" / "standards" / "build_harness.md").read_text(encoding="utf-8")
        assert "gates clear" in text, "정본에서 gates clear 서술이 사라졌다 — 목록을 갱신하라"
        clear_lines = [ln for ln in text.splitlines() if "gates clear" in ln]
        assert clear_lines
        assert any(
            "--as" in ln for ln in clear_lines
        ), "규약 정본의 gates clear 서술 어디에도 --as 가 없다"

    def test_exemptions_are_real_and_named(self):
        """면제는 *실재하는* 대상에만 붙고 사유가 적혀 있다(유령 면제·조용한 예외 금지)."""
        assert _EXEMPT, "면제가 없다면 목록 자체를 지워라 — 빈 dict는 의도를 감춘다"
        for rel, reason in _EXEMPT.items():
            assert reason.strip(), f"{rel}: 면제 사유가 비어 있다"
            assert rel not in _HUMAN_COPY_PASTE_FILES, f"{rel}: 스캔 대상이면서 면제일 수 없다"
            path = _REPO / rel
            assert path.exists(), f"{rel}: 면제 대상이 존재하지 않는다(유령 면제)"
            # 면제가 의미를 가지려면 그 파일에 실제로 구체 clear 명령이 있어야 한다.
            assert _lines_with_concrete_clear(
                path.read_text(encoding="utf-8")
            ), f"{rel}: 구체 clear 명령이 없다 — 면제할 것이 없으므로 목록에서 빼라"


class TestBoardEmitsAttributedCommand:
    """보드는 **생성된 산출물**로 검사한다 — 소스 문자열이 아니라 실제로 나오는 명령."""

    def test_generated_board_command_includes_assignee(self, git_repo: Path, monkeypatch):
        """보드가_낸_해소명령에_담당자플래그 — 대기 게이트가 있어야 의미가 있다."""
        monkeypatch.chdir(git_repo)
        import backlog as cli

        assert cli.main(["seed"]) == 0
        backlog_data, errors = store.load_backlog(git_repo)
        assert not errors, errors
        pending = [g for g in backlog_data.gates.values() if g.status == "pending"]
        assert pending, "seed에 대기 게이트가 없으면 이 검사는 아무것도 재현하지 못한다"
        assert any(g.assignee == "kiki" for g in pending), "kiki 담당 대기 게이트가 필요하다"

        payload = board.build_board(backlog_data, errors, date.today())
        html = board.render_html(payload)

        # 산출물에 담당자 인지형 플래그 조립이 들어 있어야 한다. 상수 문자열로 박아 두면
        # 담당자가 partner인 게이트에서 틀린 명령이 나오므로, 조립식인지를 본다.
        assert "--as ${g.assignee}" in html, "보드 명령이 담당자를 싣지 않는다"
        # 그리고 담당자 데이터가 실제로 payload에 실려 있어야 조립이 성립한다.
        assert '"assignee": "kiki"' in html or '"assignee":"kiki"' in html

    def test_agent_owned_gate_gets_no_flag(self):
        """담당자가 claude면 플래그를 붙이지 않는다 — `--as claude`는 선택지 자체가 아니다.

        이 방향이 없으면 "항상 --as를 붙이는" 구현도 통과한다(그 구현은 에이전트 소유 게이트에서
        argparse exit 2를 낸다).
        """
        source = (_REPO / "scripts" / "harness" / "board.py").read_text(encoding="utf-8")
        assert "g.assignee !== 'claude'" in source, "claude 담당 게이트의 예외 처리가 없다"


class TestEveryRunnableClearCommandIsTriaged:
    """HARN-83 — 저장소의 **모든** 실행형 clear 명령이 분류돼 있는가.

    막으려는 구멍
    -----------
    위 `TestHumanCopyPasteCommandsCarryTheFlag`는 `_HUMAN_COPY_PASTE_FILES`에 **적힌 파일만**
    본다. 즉 목록에 없는 파일은 가드가 아무것도 지키지 않으면서 초록을 낸다 — 그리고 그 목록은
    **손으로 관리된다**. 2026-09-07 PR #1038이 정확히 그렇게 뚫렸다: 새 런북(`docs/legal/
    export_prediction_disclosure_counsel_brief.md`)이 `--as`·`--no-base`를 모두 빠뜨린 채
    통과했고, 리뷰 봇이 잡을 때까지 가드는 초록이었다.

    그래서 이 검사는 **목록이 아니라 저장소**를 본다: 실행형 clear 명령을 담은 파일은 전부
    셋 중 하나여야 한다 — 사람용 목록 / 면제(사유 포함) / (없음 = **red**). 새 명령을 어디에
    쓰든 저자가 **분류를 강요당한다**.

    왜 '전부 --as를 요구'가 아닌가
    ---------------------------
    `--as`는 **사람 전용** 플래그다 — 담당자가 claude인 게이트에는 `--as claude`라는 선택지가
    없고(`board.py`의 `g.assignee !== 'claude'`), 붙이면 argparse exit 2가 난다. 그런데 정규식은
    "누가 실행하는가"를 볼 수 없다. 실측 반례: `docs/architecture/db_backup_dr_runbook.md`는
    본문이 "**세션은** ... 실행하고"라고 명시한 에이전트 실행 명령이라 `--as`가 없는 것이 옳다.
    그래서 전수 스캔은 *플래그를 강제*하지 않고 *분류를 강제*한다.
    """

    def _repo_files(self) -> list[str]:
        import subprocess

        out = subprocess.run(
            ["git", "ls-files"], cwd=_REPO, capture_output=True, text=True, check=True
        ).stdout
        return [f for f in out.split("\n") if f]

    def _files_with_runnable_clear(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for rel in self._repo_files():
            # 세션 이벤트 대장은 기계 기록이고, 이 파일 자신은 정규식 원문을 담는다.
            if rel.startswith("backlog/events/") or "test_gate_clear_command_attribution" in rel:
                continue
            path = _REPO / rel
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            hits = _lines_with_concrete_clear(text)
            if hits:
                found[rel] = [g for g, _ in hits]
        return found

    def test_no_runnable_clear_command_is_unclassified(self):
        """어디에도 분류되지 않은 실행형 clear 명령이 있으면 red — 목록 드리프트를 막는다."""
        found = self._files_with_runnable_clear()
        # 스캔 0건은 실패다 — 정규식이 깨지면 이 검사가 공허하게 통과한다.
        assert found, "저장소에서 실행형 clear 명령을 하나도 못 찾았다 — 정규식이 깨졌다"
        unclassified = _unclassified_files(found)
        assert not unclassified, (
            "실행형 clear 명령이 있는데 어느 목록에도 없다 — 가드가 그 파일을 지키지 않는다.\n"
            "  사람이 복사해 실행하면 _HUMAN_COPY_PASTE_FILES에, 아니면 사유와 함께 _EXEMPT에 넣어라:\n  "
            + "\n  ".join(f"{f} :: {found[f]}" for f in unclassified)
        )

    def test_listed_files_are_actually_found_by_the_scan(self):
        """목록의 파일이 전수 스캔에도 잡히는가 — 두 경로가 같은 정규식을 쓰는지 확인한다.

        한쪽만 보면 위장이 된다: 목록에 적어 두고 정규식이 그 파일을 못 잡으면, 전건 검사는
        `assert hits`에서 터지지만 이 전수 검사는 '분류됨'으로 조용히 넘어간다.
        """
        found = self._files_with_runnable_clear()
        missing = [f for f in _HUMAN_COPY_PASTE_FILES if f not in found]
        assert not missing, f"목록에 있는데 스캔에 안 잡힌다(정규식 불일치): {missing}"


class TestUrlOnlyEvidenceCarriesNoBase:
    """HARN-83 ⑥ — 증거가 **링크뿐인** clear 명령은 `--no-base`를 달아야 한다.

    왜 이것만 검사하는가 (= `--no-base` 축을 전면 도입하지 **않은** 판정)
    ------------------------------------------------------------------
    `HARN-68`은 `--evidence`에 판정 기준(커밋 해시·PR 참조)이 없으면 exit 1로 거부하고,
    `--no-base <사유>`로만 통과시킨다. 그래서 "복붙 명령에 `--no-base`가 있는가"를 `--as`와
    같은 형태로 전수 검사하고 싶어진다. **그러나 그 축은 대부분의 명령에서 판정 불능이다** —
    2026-09-08 실측으로 세 가지 이유가 확인됐다.

    1. **값이 실행 시점에 정해진다.** 런북의 증거는 `"<커밋/문서/기록>"`·`"..."` 같은 자리이거나
       `"$Verdict"`처럼 셸 변수다. 기준의 유무는 *사람이 그때 무엇을 치느냐*에 달렸고 정규식은
       그것을 볼 수 없다 — 모르는 것을 위반으로 접으면 CLAUDE.md의 "모른다 ≠ 아니다"를 어긴다.
    2. **꼬리가 줄 단위다.** 위 `_CONCRETE_CLEAR`는 개행을 넘지 않도록 고친 것이라(ⓐ 결함),
       PowerShell 백틱 줄이음으로 다음 줄에 `--evidence`를 두는 명령
       (`docs/ops/ip_separation_evidence_gate_runbook.md`)에서는 꼬리에 증거가 아예 없다.
       전면 검사는 그 파일을 **거짓 위반**으로 보고한다. (`--as`는 줄이음 앞에 오므로 무사하다.)
    3. **산문 축약형이 섞여 있다.** `--evidence ...`처럼 문법만 보여 주는 인용은 검사 대상이
       아니다.

    그래서 **구조적으로 결정 가능한 부분집합만** 못박는다: 증거 전체가 URL인 명령. 영상·문서
    링크는 사람이 무엇을 치든 `_has_judgment_base`를 통과할 수 없으므로(실측: 녹화 링크·구글
    드라이브 링크·유튜브 링크 전부 False), `--no-base` 없이는 **반드시** exit 1이다. 자리표시자든
    실제 링크든 결론이 같다는 점이 이 부분집합을 판정 가능하게 만든다.

    사고 경위: 2026-09-08 실측에서 `G-kiki-device-demo`의 복붙 명령 3건(README ×2 ·
    demo-doctor ×1)이 전부 이 상태였다 — 시연을 마친 Kiki가 안내대로 링크를 넣고 실행하면
    게이트가 안 닫히고 exit 1만 본다.
    """

    def test_link_only_evidence_commands_declare_no_base(self):
        """링크뿐인_증거는_no_base_동반"""
        offenders: list[str] = []
        checked = 0
        for rel in _HUMAN_COPY_PASTE_FILES:
            text = (_REPO / rel).read_text(encoding="utf-8")
            checked += len(_url_evidence_commands(rel, text))
            offenders.extend(_no_base_violations(rel, text))
        # 스캔 0건은 실패다 — 정규식이나 꼬리 파싱이 깨지면 이 검사가 공허하게 통과한다.
        assert checked, "증거가 링크뿐인 명령을 하나도 못 찾았다 — 파싱이 깨졌다"
        assert not offenders, (
            "증거가 링크뿐인데 --no-base 가 없다 — 실행하면 HARN-68 이 exit 1 로 거부한다"
            "(사람은 게이트가 안 닫히는 이유를 모른 채 되돌아온다):\n  " + "\n  ".join(offenders)
        )


class TestTailRegexIsLineBounded:
    r"""HARN-83 — 정규식 **자신**의 변별력을 합성 픽스처로 동결한다.

    왜 필요한가 — 이 파일이 스스로에게 걸린 함정
    ------------------------------------------
    위 검사들은 전부 *저장소의 실제 파일*을 본다. 그런데 저장소가 이미 옳은 상태이면
    (모든 명령에 `--as`·필요한 `--no-base`가 붙어 있으면) **결함형 정규식으로 되돌려도 전부
    통과한다** — 결함형은 꼬리에 파일 나머지를 삼켜 검사를 무력화할 뿐, 없는 위반을 만들어
    내지는 않기 때문이다. 실측(2026-09-08 뮤테이션 M3): 정규식을 원형
    `r"backlog\.py\s+gates clear\s+(G-...)((?:\s+\S+)*)"`으로 되돌렸더니 이 파일이 **그대로
    초록**이었다. 즉 HARN-83이 고친 결함이 어떤 테스트로도 동결돼 있지 않았다.

    그래서 여기서는 저장소가 아니라 **그 절이 없으면 통과해 버리는 입력**을 직접 만들어
    먹인다(CLAUDE.md 2026-09-07 "픽스처가 그 절을 실제로 밟는가" — 절마다 그 절의 반례를
    픽스처에 넣는다).
    """

    def test_tail_stops_at_end_of_line(self):
        """꼬리는_같은_줄에서_끝난다 — 절 `[^\\S\\n]`의 반례.

        결함형(`\\s`)이면 뒤 산문의 `--as`가 꼬리에 삼켜져 "플래그 있음"으로 오판한다.
        """
        text = (
            'python3 scripts/harness/backlog.py gates clear G-fixture --evidence "x"\n'
            "\n"
            "위 명령의 주체는 `--as kiki`로 적는다.\n"
        )
        hits = _lines_with_concrete_clear(text)
        assert len(hits) == 1
        gate_id, tail = hits[0]
        assert gate_id == "G-fixture"
        assert "--as" not in tail, (
            "꼬리가 개행을 넘어 뒤 산문의 --as 를 삼켰다 — 이 상태에서는 가드가 "
            "명령을 검사하지 못하고 공허하게 통과한다"
        )

    def test_multiple_commands_in_one_file_are_all_found(self):
        """한_파일의_명령을_전건_찾는다 — 같은 절의 두 번째 반례(결함 ⓑ).

        결함형이면 첫 명령의 꼬리가 두 번째 명령까지 삼켜 파일당 1건만 나온다.
        실제로 `scripts/demo/README.md`에는 clear 명령이 2건이다.
        """
        text = (
            "python3 scripts/harness/backlog.py gates clear G-first --as kiki\n"
            "설명 한 줄.\n"
            "python3 scripts/harness/backlog.py gates clear G-second\n"
        )
        assert [g for g, _ in _lines_with_concrete_clear(text)] == ["G-first", "G-second"]

    def test_prose_quotation_without_backlog_py_is_not_a_command(self):
        """산문_인용은_명령이_아니다 — 절 `backlog\\.py` 요구의 반례.

        이 절이 없으면 `eos_verification_design_v1.md:172`류의 문장 중 인용이 오탐으로 잡히고,
        플래그가 없는 것이 정상인 인용에 red가 난다.
        """
        text = "이 게이트는 `gates clear G-quoted`로 닫는다(주체는 사람).\n"
        assert not _lines_with_concrete_clear(text)

    def test_placeholder_id_is_not_a_command(self):
        """자리표시자_ID는_명령이_아니다 — 절 `(G-[A-Za-z0-9-]+)`의 반례.

        문법 설명(`gates clear <id>`)은 실행 대상이 아니므로 애초에 잡히면 안 된다.
        """
        text = 'python3 scripts/harness/backlog.py gates clear <id> --evidence "..."\n'
        assert not _lines_with_concrete_clear(text)


class TestJudgmentFunctionsActuallyReportViolations:
    """판정 함수가 **위반 입력에서 위반을 보고하는가** — 가드 자신의 무력화를 막는다.

    막으려는 것
    ----------
    위 저장소 스캔들은 판정을 호출할 뿐이다. 판정 자체가 빈 목록을 돌려주도록 바뀌면
    (`if "--as" not in tail:` → `if False:`, `return [...]` → `return []`) 저장소가 이미 옳으므로
    **모든 검사가 그대로 초록이다**. 실측(2026-09-08 뮤테이션 M6·M7): 판정문을 테스트 메서드
    안에 인라인으로 두었을 때 두 뮤테이션이 전부 생존했다 — 자기 단언을 지운 테스트는 자기가
    못 잡는다.

    그래서 판정을 순수 함수로 빼고, 여기서 **일부러 위반인 입력**을 먹여 보고 여부를 못박는다.
    양방향으로 본다: 위반이면 보고하고(변별력), 준수면 보고하지 않는다(오탐 없음).
    """

    def test_missing_as_flag_is_reported(self):
        """--as_없는_명령을_보고한다"""
        bad = 'python3 scripts/harness/backlog.py gates clear G-x --evidence "PR #1"\n'
        assert _as_flag_violations("f.md", bad), "--as 가 없는데 위반으로 보고하지 않는다"

    def test_present_as_flag_is_not_reported(self):
        """--as_있는_명령은_보고하지_않는다 (오탐 대조군)"""
        ok = 'python3 scripts/harness/backlog.py gates clear G-x --as kiki --evidence "PR #1"\n'
        assert not _as_flag_violations("f.md", ok)

    def test_url_evidence_without_no_base_is_reported(self):
        """링크증거에_no_base_없으면_보고한다"""
        bad = 'python3 scripts/harness/backlog.py gates clear G-x --as kiki --evidence "https://v/1"\n'
        assert _no_base_violations("f.md", bad), "링크뿐인 증거인데 위반으로 보고하지 않는다"

    def test_url_evidence_with_no_base_is_not_reported(self):
        """링크증거에_no_base_있으면_보고하지_않는다 (오탐 대조군)"""
        ok = (
            "python3 scripts/harness/backlog.py gates clear G-x --as kiki "
            '--evidence "https://v/1" --no-base "영상 링크"\n'
        )
        assert not _no_base_violations("f.md", ok)

    def test_non_url_evidence_is_out_of_scope(self):
        """링크가_아닌_증거는_판정_대상이_아니다.

        자리표시자·셸 변수는 실행 시점에 값이 정해지므로 이 축으로 판정할 수 없다
        (`TestUrlOnlyEvidenceCarriesNoBase` 도크스트링 참조). '모른다'를 '위반'으로 접지 않는다.
        """
        for ev in ('"<커밋/문서/기록>"', '"$Verdict"', '"..."'):
            cmd = f"python3 scripts/harness/backlog.py gates clear G-x --as kiki --evidence {ev}\n"
            assert not _no_base_violations("f.md", cmd), ev
            assert not _url_evidence_commands("f.md", cmd), ev

    def test_triage_reports_an_unclassified_file(self):
        """분류되지_않은_파일을_보고한다 — 전수 분류 검사의 변별력.

        `TestEveryRunnableClearCommandIsTriaged`는 미분류 목록이 비면 통과한다. 저장소가 이미
        전부 분류돼 있으므로 그 판정을 `[]`로 바꿔도 초록이다(실측 M9 생존 → 공유 함수로 승격).
        여기서 미분류 파일을 합성해 판정 자체의 변별력을 못박는다.

        **뮤테이션 한계(명시)**: 판정을 공유 함수로 뺀 것까지가 이 파일이 자기 자신을 지킬 수
        있는 경계다. 테스트 메서드 안의 *맨 단언*(예: `test_exemptions_are_real_and_named`의
        `assert path.exists()`)을 지우는 뮤테이션은 여전히 생존한다(실측 M11) — 그것은 가드의
        판정을 무력화하는 것이 아니라 **테스트를 지우는 것**이고, 어떤 테스트도 자기 삭제를
        검출하지 못한다. 그 축을 막는 것은 이 파일이 아니라 커버리지·리뷰다.
        """
        found = {"docs/새로_쓴_런북.md": ["G-new"]}
        assert _unclassified_files(found) == ["docs/새로_쓴_런북.md"]
        # 그리고 실제 목록의 파일은 미분류로 잡히지 않는다(대조군).
        assert not _unclassified_files({rel: ["G-x"] for rel in _HUMAN_COPY_PASTE_FILES})
