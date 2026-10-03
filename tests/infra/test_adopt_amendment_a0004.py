"""CONST-12 ⑩ — 채택 도우미 `plan_a0004`(원본 등록부 3건 추가) 계약 동결.

왜 이 테스트가 있는가
--------------------
A0004 는 `constitution/rules.yaml` 의 `sources:` 절 끝에 항목을 덧붙이는 개정이다. 사람이 손으로
하면 BOM·CRLF·서명 칸 누락 사고가 나고(런북 §0), 순서를 틀리면(A0003 이전) 등록부가 어긋난다.
도우미가 쓰는 것은 **정확히 '현재 + 추가분'** 이어야 하고, 규칙·단계·조문은 바뀌지 않아야 한다.

테스트 입력은 저장소의 현재 `constitution/rules.yaml` 이 아니라 **합성 기준선**이다 — 그래야 Kiki 가
A0004 를 실제로 채택해 저장소 등록부가 12건이 된 뒤에도 이 테스트가 같은 값을 낸다(채택 후에 깨지는
테스트는 채택 자체를 막는 압력이 된다). 추가분·초안은 저장소의 실제 제안 파일을 복사해 쓴다.

의도적으로 검증하지 않는 것
-------------------------
- 반영 후 위헌 심사(audit.py) 결과 — 그것은 Kiki 머신의 런북 단계이며 이 파일의 범위 밖이다.
- `constitution/` 에 실제로 쓰는 일 — 이 테스트는 임시 폴더에만 쓴다(제9조).
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADOPT = _REPO_ROOT / "scripts" / "constitution" / "adopt_amendment.py"
_PROPOSALS = _REPO_ROOT / "docs" / "constitution_proposals"

_BASELINE = """\
# 합성 기준선 — 테스트 전용
version: "v1.0.1 (합성)"

rules:
  - id: R0-01
    article: "제9조"
    statement: "합성 규칙"
    level: L5
    stage: 2

# ── 원본 등록부 ──
sources:
  - name: 성취기준
    external: true
    path: "교육부 고시 (합성)"
    version: "합성 판"
    derived: [성취기준 추출]

  - name: 파이프라인 실행 순서
    path: pipeline.yaml
    derived: [런북]
"""


def _load_adopt(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _ADOPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """도우미 모듈의 경로 상수(ROOT 포함)를 임시 폴더로 돌린다 — 실제 저장소에는 쓰지 않는다."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    adopt = _load_adopt("adopt_amendment_a0004")
    const = tmp_path / "constitution"
    (const / "amendments").mkdir(parents=True)
    (const / "rules.yaml").write_text(_BASELINE, encoding="utf-8", newline="\n")
    (const / "STAGE").write_text("2\n", encoding="utf-8", newline="\n")
    for name in ("A0001_제정.md", "A0002_파트II-VII규칙.md", "A0003_원본등록부정정.md"):
        (const / "amendments" / name).write_text("기록\n", encoding="utf-8", newline="\n")
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    for name in (
        "rules_v1.0.2_sources_additions.yaml",
        "A0004_sources_registry_additions_draft.md",
    ):
        shutil.copy2(_PROPOSALS / name, proposals / name)
    # ROOT 도 임시 폴더로 돌린다(show() 가 경로를 ROOT 기준 상대경로로 찍는다). 등록할 원본 경로는
    # 추가분에서 읽어 스텁 파일로 만든다 — 실재 검사(R4-01 사전 차단)가 통과하는 최소 구성.
    additions_text = (proposals / "rules_v1.0.2_sources_additions.yaml").read_text(encoding="utf-8")
    first_item = re.search(r"^  - name:", additions_text, re.M)
    assert first_item is not None
    for entry in yaml.safe_load(additions_text[first_item.start() :]):
        stub = tmp_path / entry["path"]
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("스텁\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(adopt, "ROOT", tmp_path)
    monkeypatch.setattr(adopt, "CONST", const)
    monkeypatch.setattr(adopt, "RULES", const / "rules.yaml")
    monkeypatch.setattr(adopt, "STAGE", const / "STAGE")
    monkeypatch.setattr(adopt, "AMENDMENTS", const / "amendments")
    monkeypatch.setattr(adopt, "A0004_ADDITIONS", proposals / "rules_v1.0.2_sources_additions.yaml")
    monkeypatch.setattr(
        adopt, "A0004_DRAFT", proposals / "A0004_sources_registry_additions_draft.md"
    )
    return adopt


def _rules_text(adopt: ModuleType) -> str:
    return adopt.RULES.read_text(encoding="utf-8")


def _sources(text: str) -> list[dict]:
    return yaml.safe_load(text)["sources"]


# ── 정상 경로 ────────────────────────────────────────────────────────────────────


def test_plan_appends_three_sources_and_keeps_rules_and_stage(sandbox: ModuleType) -> None:
    before = yaml.safe_load(_rules_text(sandbox))
    plan = sandbox.plan_a0004("Kiki", "2026-10-03")
    assert set(plan) == {sandbox.RULES, sandbox.AMENDMENTS / sandbox.A0004_TARGET}
    after = yaml.safe_load(plan[sandbox.RULES])
    assert len(before["sources"]) == 2 and len(after["sources"]) == 5  # 2 + 추가분 3건
    assert after["sources"][:2] == before["sources"]  # 기존 항목은 그대로, 뒤에만 덧붙는다
    assert after["rules"] == before["rules"] and after["version"] == before["version"]
    assert sandbox.STAGE not in plan  # 단계는 올리지 않는다
    names = [s["name"] for s in after["sources"][2:]]
    assert names == [
        "프로젝트 규칙 (개발 헌법 본문)",
        "LLM 모델 핀 (로컬 Ollama)",
        "LLM 모델 핀 (클라우드)",
    ]


def test_amendment_record_is_stamped_and_signed(sandbox: ModuleType) -> None:
    record = sandbox.plan_a0004("Kiki", "2026-10-03")[sandbox.AMENDMENTS / sandbox.A0004_TARGET]
    first = record.splitlines()[0]
    assert first.startswith("# 개정 기록 A0004") and not first.endswith("(초안)")
    assert "- 상태: **채택** — 채택일 2026-10-03 · 개정자 Kiki" in record
    assert "원본 등록부 2건 → 5건" in record
    assert "____" not in record and "**초안" not in record  # 서명 칸·초안 표지가 남지 않는다


def test_written_files_are_utf8_lf_without_bom(sandbox: ModuleType, tmp_path: Path) -> None:
    for path, text in sandbox.plan_a0004("Kiki", "2026-10-03").items():
        sandbox.write(path, text)
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
        raw.decode("utf-8")


def test_added_entries_have_existing_repo_paths(sandbox: ModuleType) -> None:
    """심사 R4-01 이 새 차단 사유를 내지 않도록, 등록하는 경로는 저장소에 실재해야 한다."""
    after = yaml.safe_load(sandbox.plan_a0004("Kiki", "2026-10-03")[sandbox.RULES])
    for entry in after["sources"][2:]:
        assert (_REPO_ROOT / entry["path"]).exists(), entry["path"]


# ── 거부 경로(전제 불충족 — 아무것도 쓰지 않는다) ────────────────────────────────


def test_refuses_when_a0003_not_adopted(sandbox: ModuleType) -> None:
    (sandbox.AMENDMENTS / "A0003_원본등록부정정.md").unlink()
    with pytest.raises(sandbox.RefusalError, match="A0003 미채택"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


def test_refuses_when_a0004_already_adopted(sandbox: ModuleType) -> None:
    (sandbox.AMENDMENTS / sandbox.A0004_TARGET).write_text("기록\n", encoding="utf-8")
    with pytest.raises(sandbox.RefusalError, match="A0004 이미 채택됨"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


def test_refuses_duplicate_source_name(sandbox: ModuleType) -> None:
    text = _rules_text(sandbox).rstrip("\n") + (
        '\n\n  - name: "프로젝트 규칙 (개발 헌법 본문)"\n    path: CLAUDE.md\n    derived: [x]\n'
    )
    sandbox.RULES.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(sandbox.RefusalError, match="겹치는 원본 이름"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


def test_refuses_missing_source_path(sandbox: ModuleType) -> None:
    text = sandbox.A0004_ADDITIONS.read_text(encoding="utf-8")
    broken = re.sub(r"path: CLAUDE\.md", "path: no/such/file.md", text, count=1)
    assert broken != text  # 주입 적용 단언
    sandbox.A0004_ADDITIONS.write_text(broken, encoding="utf-8", newline="\n")
    with pytest.raises(sandbox.RefusalError, match="저장소에 없다"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


def test_refuses_when_sources_is_not_the_last_section(sandbox: ModuleType) -> None:
    sandbox.RULES.write_text(_rules_text(sandbox) + "\nextra:\n  - 1\n", encoding="utf-8")
    with pytest.raises(sandbox.RefusalError, match="sources"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


@pytest.mark.parametrize(
    ("key", "wrong", "message"),
    [
        ("rules", [], "규칙 목록이 현재와 다르다"),
        ("sources", [{"name": "엉뚱한 항목", "path": "x"}], "'현재 \\+ 추가분'과 다르다"),
        ("version", "v9.9.9", "sources 외 항목"),
    ],
)
def test_refuses_when_merge_result_deviates_from_plan(
    sandbox: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    wrong: object,
    message: str,
) -> None:
    """결과 검증 3종(규칙·등록부·그 밖 항목)이 실제로 거부한다 — 병합 결과를 일부러 어긋나게 주입.

    입력 파일만으로는 이 어긋남에 도달할 수 없다(추가분은 sources 끝에만 붙는다). 그래서 방어선이
    살아 있는지는 결과 해석 단계에 결함을 주입해야만 잴 수 있다.
    """
    real_parse = sandbox.parse

    def faulty(text: str, label: str) -> dict:
        data = real_parse(text, label)
        if label == "반영 결과":
            data[key] = wrong
        return data

    monkeypatch.setattr(sandbox, "parse", faulty)
    with pytest.raises(sandbox.RefusalError, match=message):
        sandbox.plan_a0004("Kiki", "2026-10-03")


def test_refuses_malformed_additions(sandbox: ModuleType) -> None:
    sandbox.A0004_ADDITIONS.write_text("# 항목 없음\n", encoding="utf-8")
    with pytest.raises(sandbox.RefusalError, match="항목을 찾지 못함"):
        sandbox.plan_a0004("Kiki", "2026-10-03")
    sandbox.A0004_ADDITIONS.write_text("  - name: 이름만 있다\n", encoding="utf-8")
    with pytest.raises(sandbox.RefusalError, match="name·path"):
        sandbox.plan_a0004("Kiki", "2026-10-03")


# ── CLI 계약(미리보기·반영·AI 세션 거부) ────────────────────────────────────────


def _run_cli(
    sandbox: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["adopt_amendment.py", *argv])
    code = sandbox.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_preview_shows_source_count_change_and_writes_nothing(
    sandbox: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _rules_text(sandbox)
    code, out, _err = _run_cli(sandbox, monkeypatch, capsys, "A0004")
    assert code == 0
    assert "ADOPT_RESULT=preview" in out and "SOURCES_PLAN=2->5" in out
    assert _rules_text(sandbox) == before
    assert not (sandbox.AMENDMENTS / sandbox.A0004_TARGET).exists()


def test_cli_apply_writes_then_second_run_is_refused(
    sandbox: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _err = _run_cli(sandbox, monkeypatch, capsys, "A0004", "--apply")
    assert code == 0 and "ADOPT_RESULT=applied" in out and "SOURCES_COUNT=5" in out
    assert len(_sources(_rules_text(sandbox))) == 5
    assert (sandbox.AMENDMENTS / sandbox.A0004_TARGET).exists()
    code, out, err = _run_cli(sandbox, monkeypatch, capsys, "A0004", "--apply")
    assert code == 1 and "ADOPT_RESULT=refused" in out and "이미 채택됨" in err


def test_cli_apply_is_refused_in_ai_session(
    sandbox: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _rules_text(sandbox)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _err = _run_cli(sandbox, monkeypatch, capsys, "A0004", "--apply")
    assert code == 3 and "refused_ai_session" in out
    assert _rules_text(sandbox) == before  # 제9조 이중 방어 — 아무것도 쓰지 않는다


def test_cli_stage_flag_is_rejected_for_a0004(
    sandbox: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _out, err = _run_cli(sandbox, monkeypatch, capsys, "A0004", "--stage", "3")
    assert code == 2 and "--stage" in err
