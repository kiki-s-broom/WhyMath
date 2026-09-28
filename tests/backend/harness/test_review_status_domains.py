"""[EOS-136 ④] `review_status` 각인 도구 2종의 적용 대상 계약 — 분리가 코드로 강제되는가.

왜 이 테스트가 있는가
--------------------
코퍼스 단위 백필과 사람 판정 각인은 같은 `review_status` 축을 쓰고, 둘 다 "이미 채워진 값은
덮어쓰지 않는다". 그래서 **먼저 쓴 쪽이 영구히 이긴다** — 코퍼스 단위 백필이 회차 코퍼스에 먼저
닿으면(다른 코퍼스의 감사 근거로) 수용분 전원이 approved가 되고, 그 뒤 사람 판정은 영영 각인될 수
없다. 두 도구의 대상을 가르는 규칙이 산문(계약 문서)에만 있으면 그 사고는 조용히 난다.

이 파일은 세 가지를 붙든다:
  ① 부류 판정(`classify_corpus`) 5종과 두 도구의 거부 술어 — 각 부류를 실제로 만들어 확인한다.
  ② CI 드리프트 가드(`--all --check`)가 회차 코퍼스를 **오판하지 않는다** — 순회 대상(고정 7종)이
     전부 `fixed`이고, 회차 코퍼스가 목록에 끼어들면 "미백필"이 아니라 exit 2로 빨개진다.
  ③ 계약 문서(`docs/standards/review_status_stamping_contract.md`)와 코드가 어긋나지 않는다 — 문서가
     이름 붙인 함수가 실재하고, 문서의 표 수치가 코드로 다시 계산된다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import golden_promotion_gate as gate
from whymath_backend.harness import problem_corpus_review_status_backfill as review_cli
from whymath_backend.harness import review_status_domains as domains
from whymath_backend.harness import review_status_verdict_bridge as bridge
from whymath_backend.harness.anchor_round_ledger import default_round_ledger_path
from whymath_backend.harness.problem_corpus_persona_fit_backfill import KNOWN_CORPORA
from whymath_backend.harness.wilson import wilson_upper_bound

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_DOC = _REPO_ROOT / "docs" / "standards" / "review_status_stamping_contract.md"


def _write_corpus(path: Path, *, ledger: bool, review_status: str | None = None) -> Path:
    """레코드 1건짜리 코퍼스(+ 선택적 회차 대장). review_status=None이면 키가 없다(미각인)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "slug": "wm-x",
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(path))),
        "question_text": "이차방정식 x^2 - 5x + 6 = 0 의 큰 근",
    }
    if review_status is not None:
        row["review_status"] = review_status
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    if ledger:
        default_round_ledger_path(path).write_text('{"run_id": "r1"}\n', encoding="utf-8")
    return path


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """가짜 레포 루트 — `KNOWN_CORPORA`·`data/corpus`는 레포 루트 상대경로 규약이라 cwd를 옮긴다."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _arm_write_explosives(monkeypatch: pytest.MonkeyPatch) -> None:
    """쓰기 경로 진입 즉시 실패 — 거부가 '아무것도 쓰지 않았다'를 산출물이 아니라 구조로 확인."""

    def _boom(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"거부 경로가 파일에 썼다(금지): {self}")

    monkeypatch.setattr(Path, "write_text", _boom)
    monkeypatch.setattr(Path, "mkdir", _boom)


# ══════════════════════════════════════════════════════════════════════════
class TestClassifyCorpus:
    def test_round_corpus_is_identified_by_the_ledger_sidecar(self, tmp_path: Path) -> None:
        corpus = _write_corpus(tmp_path / "acc.jsonl", ledger=True)
        assert domains.classify_corpus(corpus) == ("round", None)

    def test_corpus_without_ledger_outside_known_is_other(self, tmp_path: Path) -> None:
        corpus = _write_corpus(tmp_path / "acc.jsonl", ledger=False)
        assert domains.classify_corpus(corpus) == ("other", None)

    def test_known_path_is_fixed_and_with_a_ledger_is_conflict(self, fake_repo: Path) -> None:
        fixed = _write_corpus(fake_repo / KNOWN_CORPORA["v1"], ledger=False)
        assert domains.classify_corpus(fixed) == ("fixed", None)
        default_round_ledger_path(fixed).write_text("{}\n", encoding="utf-8")
        assert domains.classify_corpus(fixed) == ("conflict", None)

    def test_unreadable_ledger_state_is_unknown_not_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """권한 거부를 '대장 없음'으로 접지 않는다 — 접으면 회차 코퍼스가 `other`처럼 통과한다."""
        corpus = _write_corpus(tmp_path / "acc.jsonl", ledger=True)
        ledger = default_round_ledger_path(corpus)
        real_is_file = Path.is_file

        def _denied(self: Path) -> bool:
            if self == ledger:
                raise PermissionError("EACCES 주입")
            return real_is_file(self)

        monkeypatch.setattr(Path, "is_file", _denied)
        assert domains.classify_corpus(corpus) == ("unknown", "PermissionError")

    def test_kind_vocabulary_is_closed(self) -> None:
        assert domains.CORPUS_KINDS == ("fixed", "round", "other", "conflict", "unknown")


class TestRefusals:
    def test_corpus_level_backfill_refuses_round_and_conflict(self, fake_repo: Path) -> None:
        round_corpus = _write_corpus(fake_repo / "out" / "acc.jsonl", ledger=True)
        refusal = domains.corpus_backfill_refusal(round_corpus, "v1")
        assert refusal is not None
        assert "회차 코퍼스" in refusal and "review_status_verdict_bridge" in refusal

        conflict = _write_corpus(fake_repo / KNOWN_CORPORA["v1"], ledger=True)
        assert domains.corpus_backfill_refusal(conflict, "v1") is not None

    def test_corpus_level_backfill_refuses_borrowed_evidence(self, fake_repo: Path) -> None:
        """코퍼스 키 K의 판정은 K의 코퍼스에만 — 다른 고정 코퍼스·레포의 다른 코퍼스는 거부."""
        v1 = _write_corpus(fake_repo / KNOWN_CORPORA["v1"], ledger=False)
        assert domains.corpus_backfill_refusal(v1, "v1") is None  # 제 짝은 통과(양성 대조)
        borrowed = domains.corpus_backfill_refusal(v1, "killer_v0")
        assert borrowed is not None and "근거 차용" in borrowed

        batch = _write_corpus(
            fake_repo / "data" / "corpus" / "problem_bank_batch_v0" / "problems.jsonl",
            ledger=False,
        )
        refusal = domains.corpus_backfill_refusal(batch, "generated_v0")
        assert refusal is not None and "근거 차용" in refusal

    def test_corpus_level_backfill_allows_out_of_repo_copies(self, tmp_path: Path) -> None:
        """레포 밖 사본(테스트·`--out` 실험)은 막지 않는다 — 기존 단일 파일 모드 계약 보존."""
        copy = _write_corpus(tmp_path / "copy" / "problems.jsonl", ledger=False)
        assert domains.corpus_backfill_refusal(copy, "v1") is None

    def test_verdict_bridge_accepts_only_round_corpora(self, fake_repo: Path) -> None:
        round_corpus = _write_corpus(fake_repo / "out" / "acc.jsonl", ledger=True)
        assert domains.verdict_bridge_refusal(round_corpus) is None
        other = _write_corpus(fake_repo / "out2" / "acc.jsonl", ledger=False)
        other_refusal = domains.verdict_bridge_refusal(other)
        assert other_refusal is not None and "회차 코퍼스가 아니다" in other_refusal
        fixed = _write_corpus(fake_repo / KNOWN_CORPORA["killer_v0"], ledger=False)
        fixed_refusal = domains.verdict_bridge_refusal(fixed)
        assert fixed_refusal is not None and "고정 코퍼스" in fixed_refusal


class TestCorpusLevelBackfillCli:
    """코퍼스 단위 백필 CLI가 적용 대상 위반에 exit 2 · 무기록인가(단일 파일·`--all` 둘 다)."""

    def test_round_corpus_is_refused_even_in_check_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        corpus = _write_corpus(tmp_path / "acc.jsonl", ledger=True)
        audit = tmp_path / "audit.jsonl"
        _arm_write_explosives(monkeypatch)
        code = review_cli.main(
            ["--in", str(corpus), "--corpus", "v1", "--audit-out", str(audit), "--check"]
        )
        assert code == 2
        assert "[적용 대상 위반]" in capsys.readouterr().err

    def test_round_corpus_is_refused_in_write_mode_without_touching_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _write_corpus(tmp_path / "acc.jsonl", ledger=True)
        before = corpus.read_bytes()
        audit = tmp_path / "audit.jsonl"
        code = review_cli.main(["--in", str(corpus), "--corpus", "v1", "--audit-out", str(audit)])
        capsys.readouterr()
        assert code == 2
        assert corpus.read_bytes() == before and not audit.exists()

    def test_a_round_corpus_registered_as_fixed_turns_the_ci_guard_red(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """누군가 회차 코퍼스를 `KNOWN_CORPORA`에 넣으면 CI 가드는 '미백필'이 아니라 exit 2다.

        '미백필'(exit 1)로 읽으면 운영자는 코퍼스 단위 백필을 돌리라는 안내를 받고, 그 순간
        그 회차의 사람 판정은 영영 각인될 수 없다(먼저 채운 쪽이 이긴다).
        """
        monkeypatch.chdir(_REPO_ROOT)  # 나머지 고정 7종은 실제 레포 경로로 해석된다
        injected = _write_corpus(tmp_path / "acc.jsonl", ledger=True)
        monkeypatch.setitem(KNOWN_CORPORA, "round_misregistered", injected)
        _arm_write_explosives(monkeypatch)
        code = review_cli.main(["--all", "--check"])
        err = capsys.readouterr().err
        assert code == 2
        assert str(injected) in err and "회차 코퍼스" in err


class TestCiDriftGuardDoesNotMisjudgeRoundCorpora:
    """④ — CI 드리프트 가드(`--all --check`)와 회차 코퍼스의 관계를 실물로 확인한다."""

    def test_every_fixed_corpus_in_the_repo_classifies_as_fixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """가드가 순회하는 7종은 전부 `fixed` — 회차 대장이 붙은 것이 없다(순회 대상 = 고정 코퍼스)."""
        monkeypatch.chdir(_REPO_ROOT)
        kinds = {key: domains.classify_corpus(path)[0] for key, path in KNOWN_CORPORA.items()}
        assert kinds == {key: "fixed" for key in KNOWN_CORPORA}
        assert len(kinds) == 7

    def test_real_guard_passes_with_the_domain_check_wired(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CI 스텝과 같은 명령 — 적용 대상 검사가 배선된 뒤에도 실 레포에서 초록이다."""
        monkeypatch.chdir(_REPO_ROOT)
        _arm_write_explosives(monkeypatch)
        code = review_cli.main(["--all", "--check"])
        captured = capsys.readouterr()
        assert code == 0, captured.err
        assert len(json.loads(captured.out)) == 7


@pytest.fixture(scope="module")
def doc() -> str:
    """계약 문서 본문 — 부재면 '통과'가 아니라 실패다(대조할 대상이 없다)."""
    assert _CONTRACT_DOC.is_file(), f"계약 문서 부재: {_CONTRACT_DOC}"
    return _CONTRACT_DOC.read_text(encoding="utf-8")


class TestContractDocMatchesCode:
    """계약 문서가 이름 붙인 것이 코드에 실재하고, 문서의 수치가 코드로 다시 계산된다."""

    def test_every_corpus_kind_has_a_row(self, doc: str) -> None:
        for kind in domains.CORPUS_KINDS:
            assert f"| `{kind}` |" in doc, kind

    def test_named_enforcement_points_exist(self, doc: str) -> None:
        named = {
            "classify_corpus": domains,
            "corpus_backfill_refusal": domains,
            "verdict_bridge_refusal": domains,
            "run_bridge": bridge,
            "read_human_verdict_ledger": gate,
            "certifies_current_content": gate,
            "PromotionGateReport": gate,
            "_load_backfill_audit": gate,
        }
        for name, module in named.items():
            assert name in doc, name
            assert hasattr(module, name), f"{module.__name__}.{name} 부재 — 문서가 낡았다"

    def test_sidecar_names_are_the_code_names(self, doc: str) -> None:
        corpus = Path("problems.jsonl")
        ledger_suffix = default_round_ledger_path(corpus).name.removeprefix("problems")
        audit_suffix = bridge.default_stamp_audit_path(corpus).name.removeprefix("problems")
        assert f"<corpus>{ledger_suffix}" in doc
        assert f"<corpus>{audit_suffix}" in doc

    def test_minimum_batch_table_is_recomputed(self, doc: str) -> None:
        """§5.5 표(결함 k건 → 최소 검수 배치)가 게이트 기본 임계로 다시 계산된다."""
        for defects in range(3):
            trials = defects + 1
            while wilson_upper_bound(defects, trials, 0.95) > 0.02:
                trials += 1
            assert f"| {defects} | {trials} |" in doc, (defects, trials)

    def test_the_judged_denominator_is_what_the_gate_reports(self, doc: str) -> None:
        """문서의 판정((II) 생성 배치 품질)과 게이트 산출물의 범위 표식이 같은 말을 한다."""
        assert "(II) 생성 배치 품질" in doc
        report = gate.evaluate_promotion(
            ["wm-a"],
            queue_slugs=set(),
            human_verdicts={"wm-a": "approved", "wm-b": "rejected"},
            backfilled_status={"wm-a": "approved"},
            corpus_review_status={"wm-a": "approved"},
        )
        assert report.to_json()["defect_scope"] == "review_batch"
        assert report.reviewed == 2 and report.defects == 1  # 제안 밖 반려가 분모·분자에 있다

    def test_modules_point_back_to_the_contract(self) -> None:
        """코드가 계약 문서 경로를 가리킨다 — 문서를 옮기거나 지우면 여기서 빨개진다."""
        relative = "docs/standards/review_status_stamping_contract.md"
        for module in (domains, bridge, gate, review_cli):
            source = Path(module.__file__ or "").read_text(encoding="utf-8")
            assert relative in source, module.__name__
