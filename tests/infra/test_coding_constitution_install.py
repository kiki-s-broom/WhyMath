"""CONST-02 — 코딩 헌법 설치 무결성과 위헌 심사 도구 패치의 변별력 동결.

왜 이 테스트가 있는가
--------------------
2026-09-26 Kiki가 코딩 헌법 꾸러미(v1.0 제정·v1.1 갱신)를 주고 이식을 지시했다. 헌법은
"사람만 수정"(제9조)이므로 설치 후 AI가 내용을 고칠 수 없다 — 그래서 **설치가 온전한가**와
**심사 도구가 헌법을 제대로 읽는가**를 기계가 상시 확인해야 한다. 또 이식 중 원본 audit.py에서
실측 결함 3건(빈 run 침묵 통과 · 자리표시자 version 통과 · 심사 불가와 위반이 같은 종료 코드)을
고쳤으므로, 그 패치가 되돌아가면 red가 나야 한다.

검증 계약
--------
① constitution/ 5종(헌법·규칙 등록부·단계·개정 기록·판례) 실재 · STAGE는 1~6 정수 ·
   헌법 본문에 제1조~제11조 전건
② rules.yaml 형식 — 규칙 필수 필드·ID 유일·sources에 규칙처럼 생긴 항목 0
③ docs/standard-book/INDEX.md 의 장 링크가 전부 실재 파일(링크 0건이면 실패 — 공허 통과 금지)
④ pipeline.yaml 이 헌법 필수 노드·저작권 직접 선행 조건을 통과
⑤ audit.py 가 심사 가능 상태(종료 코드 0·1)이며 심사 불가(2)가 아니다
⑥ 변별력 — tmp 사본에 결함을 주입하면 각 패치가 실제로 잡는다(주입 적용 단언 포함)

의도적으로 검증하지 않는 것
-------------------------
- 헌법 본문의 바이트 고정(sha256 핀). 헌법은 Kiki가 개정할 수 있어야 하므로 내용을 테스트에
  얼리지 않는다 — 개정 절차(개정 기록 동반)는 R0-02 집행 장치(CONST-03)의 몫이다.
- 원본 등록부의 경로 정합(현재 차단 7건). 그것은 래칫(test_coding_constitution_audit_wiring)이
  '늘지 않음'으로 지키고, 0으로 만드는 일은 게이트 G-const-sources-registry-adopt 의 몫이다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONST = _REPO_ROOT / "constitution"
_AUDIT = _REPO_ROOT / "scripts" / "constitution" / "audit.py"
_PIPE_CHECK = _REPO_ROOT / "scripts" / "constitution" / "pipeline_check.py"
_PIPELINE = _REPO_ROOT / "pipeline.yaml"
_BOOK_INDEX = _REPO_ROOT / "docs" / "standard-book" / "INDEX.md"
_REQUIRED_RULE_FIELDS = {"id", "article", "chapter", "axis", "statement", "level", "stage"}


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PATH": ""},
    )


def _sandbox(tmp_path: Path) -> Path:
    """헌법·심사 도구·파이프라인을 tmp에 같은 상대 구조로 복제한다(저장소 파일은 건드리지 않는다)."""
    root = tmp_path / "repo"
    shutil.copytree(_CONST, root / "constitution")
    (root / "scripts" / "constitution").mkdir(parents=True)
    shutil.copy2(_AUDIT, root / "scripts" / "constitution" / "audit.py")
    shutil.copy2(_PIPE_CHECK, root / "scripts" / "constitution" / "pipeline_check.py")
    shutil.copy2(_PIPELINE, root / "pipeline.yaml")
    return root


def _mutate(path: Path, old: str, new: str) -> None:
    """주입 1건을 적용하고 실제로 바뀌었는지 단언한다(주입이 조용히 실패하면 검출처럼 보인다)."""
    original = path.read_text(encoding="utf-8")
    assert original.count(old) == 1, f"주입 대상이 정확히 1건이어야 한다: {old!r}"
    mutated = original.replace(old, new)
    assert mutated != original
    path.write_text(mutated, encoding="utf-8")


# ── ① 설치 ─────────────────────────────────────────────────────────────────


def test_constitution_files_exist() -> None:
    for rel in ("CONSTITUTION.md", "rules.yaml", "STAGE"):
        assert (_CONST / rel).is_file(), f"constitution/{rel} 없음"
    assert list((_CONST / "amendments").glob("A*.md")), "개정 기록(amendments/A*.md) 0건"
    assert list((_CONST / "precedents").glob("P*.md")), "판례(precedents/P*.md) 0건"


def test_stage_is_integer_in_ladder() -> None:
    raw = (_CONST / "STAGE").read_text(encoding="utf-8").strip()
    assert raw.isdigit() and 1 <= int(raw) <= 6, f"STAGE는 1~6 정수여야 한다: {raw!r}"


def test_constitution_has_all_articles() -> None:
    text = (_CONST / "CONSTITUTION.md").read_text(encoding="utf-8")
    missing = [n for n in range(1, 12) if f"**제{n}조(" not in text]
    assert not missing, f"조문 누락: 제{missing}조"


# ── ② rules.yaml 형식 ──────────────────────────────────────────────────────


def _registry() -> dict:
    data = yaml.safe_load((_CONST / "rules.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("rules"), list)
    return data


def test_rules_have_required_fields_and_unique_ids() -> None:
    rules = _registry()["rules"]
    assert rules, "규칙 0건 — 등록부를 못 읽었다"
    for rule in rules:
        missing = _REQUIRED_RULE_FIELDS - set(rule)
        assert not missing, f"{rule.get('id')}: 필수 필드 누락 {sorted(missing)}"
        assert rule["level"] in {"L1", "L2", "L3", "L4", "L5"}
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "규칙 ID 중복"


def test_sources_hold_no_rule_shaped_items() -> None:
    sources = _registry().get("sources") or []
    assert sources, "원본 등록부 0건"
    for src in sources:
        assert "statement" not in src and "level" not in src, f"sources에 규칙 흡수: {src}"


# ── ③ 표준북 색인 ──────────────────────────────────────────────────────────


def test_standard_book_index_links_resolve() -> None:
    text = _BOOK_INDEX.read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)]+\.md)\)", text)
    assert len(links) >= 40, f"색인 링크가 너무 적다({len(links)}건) — 파서 위장 의심"
    missing = [link for link in links if not (_BOOK_INDEX.parent / link).is_file()]
    assert not missing, f"색인이 가리키는 장 파일 없음: {missing}"


# ── ④ 파이프라인 그래프 ────────────────────────────────────────────────────


def test_pipeline_graph_passes_constitution_checks() -> None:
    proc = _run(
        [
            sys.executable,
            str(_PIPE_CHECK),
            "--require",
            "copyright,backup,curriculum_review",
            "--upstream-of",
            "publish:copyright",
            "--direct-upstream-of",
            "publish:copyright",
        ],
        _REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── ⑤ 심사 가능 상태 ───────────────────────────────────────────────────────


def test_audit_is_judgeable() -> None:
    proc = _run([sys.executable, str(_AUDIT), "--no-run"], _REPO_ROOT)
    assert proc.returncode in (0, 1), f"심사 불가(exit {proc.returncode}): {proc.stderr}"
    assert "심사 항목" in proc.stdout


# ── ⑥ 변별력 ───────────────────────────────────────────────────────────────


def test_rule_appended_to_file_end_is_refused(tmp_path: Path) -> None:
    """규칙을 파일 맨 끝에 붙이면 sources로 흡수된다 — 심사는 exit 2로 멈춰야 한다."""
    root = _sandbox(tmp_path)
    rules = root / "constitution" / "rules.yaml"
    rules.write_text(
        rules.read_text(encoding="utf-8")
        + "\n  - id: RX-01\n    article: 제4조\n    chapter: 1\n    axis: 흐름\n"
        "    statement: 주입\n    level: L5\n    stage: 1\n",
        encoding="utf-8",
    )
    proc = _run([sys.executable, "scripts/constitution/audit.py", "--no-run"], root)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "규칙처럼 보이는 항목" in proc.stderr


def test_empty_run_is_not_silently_passed(tmp_path: Path) -> None:
    """패치 ⓑ — run 이 빈 L5 규칙은 '집행 장치 없음'이어야 한다(원본은 침묵 통과)."""
    root = _sandbox(tmp_path)
    rules = root / "constitution" / "rules.yaml"
    _mutate(
        rules,
        "    run: python scripts/constitution/pipeline_check.py\n    stage: 3\n",
        '    run: ""\n    stage: 3\n',
    )
    (root / "scripts" / "constitution" / "pipeline_check.py").touch()
    proc = _run([sys.executable, "scripts/constitution/audit.py", "--no-run", "--stage", "3"], root)
    assert "run 미지정" in proc.stdout, proc.stdout
    assert re.search(r"\| R1-01 \| L5 \| 📭 집행 장치 없음 \| run 미지정", proc.stdout)


def test_placeholder_version_is_a_violation(tmp_path: Path) -> None:
    """패치 ⓒ — 외부 원본 version 자리표시자는 위반. 실값으로 바꾸면 통과(대조군)."""
    root = _sandbox(tmp_path)
    rules = root / "constitution" / "rules.yaml"
    text = rules.read_text(encoding="utf-8")
    assert "확인 후 기입" in text, "전제: 설치본에 자리표시자 version이 있다"
    proc = _run([sys.executable, "scripts/constitution/audit.py", "--sources-only"], root)
    assert "version이 자리표시자" in proc.stdout
    _mutate(rules, 'version: "고시 번호·판 확인 후 기입"', 'version: "교육부 고시 제2022-33호"')
    proc = _run([sys.executable, "scripts/constitution/audit.py", "--sources-only"], root)
    assert "version이 자리표시자" not in proc.stdout


def test_stage_preview_does_not_touch_stage_file(tmp_path: Path) -> None:
    """패치 ⓐ — --stage 미리보기는 STAGE 파일을 바꾸지 않고 규칙을 켠다."""
    root = _sandbox(tmp_path)
    before = (root / "constitution" / "STAGE").read_bytes()
    proc = _run([sys.executable, "scripts/constitution/audit.py", "--no-run", "--stage", "3"], root)
    assert "(미리보기 --stage 3)" in proc.stdout
    assert "⏳ 예정 | 3단계" not in proc.stdout
    assert (root / "constitution" / "STAGE").read_bytes() == before


def test_direct_upstream_catches_bypass_that_transitive_misses(tmp_path: Path) -> None:
    """--upstream-of(추이적)는 우회를 못 잡고 --direct-upstream-of 는 잡는다."""
    root = _sandbox(tmp_path)
    pipe = root / "pipeline.yaml"
    _mutate(
        pipe,
        "publish: { needs: [promotion_gate, copyright, signature_tagging] }",
        "publish: { needs: [promotion_gate, signature_tagging] }",
    )
    base = [sys.executable, "scripts/constitution/pipeline_check.py"]
    transitive = _run(base + ["--upstream-of", "publish:copyright"], root)
    direct = _run(base + ["--direct-upstream-of", "publish:copyright"], root)
    assert transitive.returncode == 0, "전제: 추이적 검사는 다른 경로로 통과한다"
    assert direct.returncode == 1 and "직접 선행 누락" in direct.stdout


def test_pipeline_cycle_is_detected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    _mutate(
        root / "pipeline.yaml",
        "  concept_graph: { needs: [standards] }",
        "  concept_graph: { needs: [standards, publish] }",
    )
    proc = _run([sys.executable, "scripts/constitution/pipeline_check.py"], root)
    assert proc.returncode == 1 and "[순환]" in proc.stdout


@pytest.mark.parametrize("content", ["nodes: {}\n", "not_nodes: 1\n"])
def test_empty_or_broken_pipeline_is_measurement_failure(tmp_path: Path, content: str) -> None:
    root = _sandbox(tmp_path)
    (root / "pipeline.yaml").write_text(content, encoding="utf-8")
    proc = _run([sys.executable, "scripts/constitution/pipeline_check.py"], root)
    assert proc.returncode == 2, "노드 0개·형식 오류는 '정상'이 아니라 측정 실패"
