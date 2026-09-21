"""HARN-121 ④ — 규칙 인덱스 린트의 계약 동결.

이 파일이 지키는 것은 "린트가 존재한다"가 아니라 **"위반 상태에서 실제로 exit 1을
낸다"** 이다. 그래서 L1~L6 각각에 *위반 주입*과 *정상 대조군*을 쌍으로 둔다 —
대조군이 없으면 "전부 거부"라는 과잉 수정이 그대로 통과한다(2026-09-08 교훈).

특히 조심한 것: 이 린트는 **정상 상태에서 조용해야** 한다. 상시 위반을 보고하는
판정기는 사람이 판정기를 끄게 만들고(CLAUDE.md fail-open 항목), 그러면 동결이
글자만 남는다. 그래서 `test_live_repo_is_green`이 맨 앞에 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import rules as rules_mod

import backlog as cli

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rule(**over: object) -> rules_mod.Rule:
    base: dict[str, object] = {
        "id": "R-001",
        "slug": "sample-rule",
        "title": "표본 규칙 금지",
        "origin": "incident",
        "status": "code",
        "enforced_by": ["scripts/harness/rules.py"],
    }
    base.update(over)
    return rules_mod.Rule(**base)  # type: ignore[arg-type]


def _lint(text: str, rules: list[rules_mod.Rule], **kw: object) -> list[rules_mod.Finding]:
    params: dict[str, object] = {
        "constitution_text": text,
        "rules": rules,
        "schema_errors": [],
        "repo_root": REPO_ROOT,
        "known_task_ids": {"HARN-118", "HARN-118-incident-ledger-structured"},
        "prose_baseline": 1,
    }
    params.update(kw)
    return rules_mod.lint(**params)  # type: ignore[arg-type]


def _checks(findings: list[rules_mod.Finding]) -> set[str]:
    return {f.check for f in findings}


# ── 0. 저장소 현재 상태 — 린트는 정상에서 조용해야 한다 ──────────────────────


class TestLiveRepo:
    def test_live_repo_is_green(self) -> None:
        """상시 위반을 내는 판정기는 사람이 끄게 만든다 — 그 순간 동결은 글자만 남는다."""
        findings = rules_mod.lint_repo(REPO_ROOT)
        assert findings == [], [str(f) for f in findings[:8]]

    def test_ledger_has_every_constitution_rule(self) -> None:
        parsed = rules_mod.parse_constitution(
            (REPO_ROOT / rules_mod.CONSTITUTION).read_text(encoding="utf-8")
        )
        rules, errors = rules_mod.load_rules(REPO_ROOT)
        assert errors == []
        assert {p.title for p in parsed} == {r.title for r in rules}
        assert len(rules) == len(parsed)

    def test_rendered_index_matches_the_ledger(self) -> None:
        """문서는 렌더 결과다 — 손편집하면 이 테스트가 잡는다."""
        rules, _ = rules_mod.load_rules(REPO_ROOT)
        expected = rules_mod.render_index(rules, prose_baseline=rules_mod.PROSE_BASELINE)
        assert (REPO_ROOT / rules_mod.INDEX_DOC).read_text(encoding="utf-8") == expected

    def test_prose_baseline_matches_the_ledger_exactly(self) -> None:
        """기준선이 실제보다 크면 래칫이 느슨해진다 — 빚이 조용히 늘 여지를 남긴다."""
        rules, _ = rules_mod.load_rules(REPO_ROOT)
        assert sum(1 for r in rules if r.status == "prose") == rules_mod.PROSE_BASELINE


# ── 1. 파서 ─────────────────────────────────────────────────────────────────


class TestParser:
    def test_three_shapes_are_distinguished(self) -> None:
        text = (
            "## 금기\n"
            "- ❌ **볼드 규칙 금지** — 본문\n"
            "- ❌ 평문 창건 원칙\n"
            "  - **확장 — 어떤 축 (2026-09-01)**: 본문\n"
        )
        items = rules_mod.parse_constitution(text)
        assert [(i.origin, i.title) for i in items] == [
            ("incident", "볼드 규칙 금지"),
            ("founding", "평문 창건 원칙"),
            ("extension", "확장 — 어떤 축 (2026-09-01)"),
        ]

    def test_guidance_section_items_are_rules(self) -> None:
        """`❌` 없이 규칙이 사는 절 — 빼면 E 분류가 통째로 인덱스 밖으로 나간다."""
        text = "## 📐 Kiki 개인 선호 (저장된 패턴)\n- **실행 블록 규칙** — 본문\n"
        items = rules_mod.parse_constitution(text)
        assert [(i.origin, i.title) for i in items] == [("guidance", "실행 블록 규칙")]

    def test_bold_items_outside_that_section_are_not_rules(self) -> None:
        """오탐 억제 — 기술 스택·인덱스 목록의 볼드 항목까지 규칙으로 잡으면 린트가 소음이 된다."""
        text = "## 🛠️ 기술 스택\n- **PostgreSQL 16** — RDB\n"
        assert rules_mod.parse_constitution(text) == []

    def test_line_numbers_are_one_based(self) -> None:
        items = rules_mod.parse_constitution("첫 줄\n- ❌ **규칙 금지** — 본문\n")
        assert items[0].line == 2


# ── 2. L1 전수 귀속 ─────────────────────────────────────────────────────────


class TestL1Attribution:
    def test_clean_pair_is_green(self) -> None:
        """대조군 — 이것이 통과하지 않으면 아래 거부들은 변별력이 없다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        assert _lint(text, [_rule()]) == []

    def test_constitution_rule_missing_from_index_is_caught(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n- ❌ **인덱스에 없는 규칙 금지** — 본문\n"
        assert "L1" in _checks(_lint(text, [_rule()]))

    def test_index_entry_missing_from_constitution_is_caught(self) -> None:
        """역방향 — 한쪽만 보면 '유령 규칙'(제목이 바뀐 뒤 남은 행)을 놓친다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(), _rule(id="R-002", slug="ghost", title="사라진 규칙 금지")]
        assert "L1" in _checks(_lint(text, rules))

    def test_renamed_title_breaks_the_pairing(self) -> None:
        """제목 문자열이 대응 키다 — 제목을 고치면 red가 난다(고칠 수 있는 red)."""
        text = "- ❌ **표본 규칙 금지(제목이 바뀜)** — 본문\n"
        findings = _lint(text, [_rule()])
        assert len([f for f in findings if f.check == "L1"]) == 2  # 양방향 각 1건


# ── 3. L2 산문 동결 (acceptance ④의 핵심) ───────────────────────────────────


class TestL2ProseFreeze:
    def test_new_prose_rule_is_rejected(self) -> None:
        """동결 위반 단락 1건 주입 → RED (acceptance ④ 변별력 문면 그대로)."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status="prose", enforced_by=[], grandfathered=False)]
        assert "L2" in _checks(_lint(text, rules))

    @pytest.mark.parametrize(
        ("status", "ref"),
        [("code", "scripts/harness/rules.py"), ("task", "HARN-118")],
    )
    def test_attaching_enforcement_makes_it_green(self, status: str, ref: str) -> None:
        """대장 참조를 붙이면 GREEN — 이 대비가 동결의 변별력이다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status=status, enforced_by=[ref], grandfathered=False)]
        assert _lint(text, rules) == []

    def test_grandfathered_prose_is_allowed(self) -> None:
        """동결 이전 29건을 즉시 위반으로 만들면 대장 전체가 red가 되고 사람이 린트를 끈다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status="prose", enforced_by=[], grandfathered=True)]
        assert "L2" not in _checks(_lint(text, rules))

    def test_policy_status_cannot_launder_an_incident_rule(self) -> None:
        """사고 규칙에 '집행 요구 없음'을 붙이면 동결이 통째로 무력해진다 — 스키마가 막는다."""
        errors = _rule(status="policy", enforced_by=[]).validate()
        assert errors and any("founding" in e for e in errors)

    def test_policy_is_fine_for_a_founding_rule(self) -> None:
        assert _rule(origin="founding", status="policy", enforced_by=[]).validate() == []


# ── 4. L3 사고 경위 동결 ────────────────────────────────────────────────────


class TestL3NarrativeFreeze:
    def test_new_narrative_paragraph_is_rejected(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문 (사고 경위: 어제 이런 일이 있었다)\n"
        assert "L3" in _checks(_lint(text, [_rule()]))

    def test_ledger_reference_makes_it_green(self) -> None:
        """경위는 대장에 등재하고 여기엔 참조만 남긴다."""
        text = (
            "- ❌ **표본 규칙 금지** — 본문 "
            "(사고 경위: `backlog/incidents.ndjson` 참조 — `incident series` 로 회차 확인)\n"
        )
        assert "L3" not in _checks(_lint(text, [_rule()]))

    def test_grandfathered_narrative_is_allowed(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문 (사고 경위: 2026-07 이런 일)\n"
        assert "L3" not in _checks(_lint(text, [_rule(narrative_grandfathered=True)]))

    def test_the_two_grandfather_axes_are_independent(self) -> None:
        """코드로 상환된 규칙이 자기 사고 경위 단락 때문에 L3에 걸리면 안 된다.

        첫 구현이 정확히 그랬다 — 한 필드로 묶었더니 `enforced_by`를 채우는 순간
        멀쩡한 규칙 18건이 L3 위반이 됐다.
        """
        text = "- ❌ **표본 규칙 금지** — 본문 (사고 경위: 옛날 일)\n"
        rule = _rule(status="code", grandfathered=False, narrative_grandfathered=True)
        assert _lint(text, [rule]) == []

    def test_meta_mention_without_colon_is_not_a_narrative(self) -> None:
        """「실수 관리」 절의 '사고 경위 1줄 병기는 유지한다'가 위반이 되면 고칠 수 없는 red다."""
        text = "- ❌ **표본 규칙 금지** — 기존 규칙의 사고 경위 1줄 병기는 유지한다\n"
        assert "L3" not in _checks(_lint(text, [_rule()]))


# ── 5. L4 집행 참조 실재 ────────────────────────────────────────────────────


class TestL4EnforcementExists:
    def test_missing_path_is_caught(self) -> None:
        """인덱스가 있지도 않은 집행 지점을 가리키면 그것이 곧 '정본화 ≠ 집행'이다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(enforced_by=["tests/harness/test_does_not_exist.py"])]
        assert "L4" in _checks(_lint(text, rules))

    def test_existing_path_is_green(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        assert _lint(text, [_rule(enforced_by=["scripts/harness/rules.py"])]) == []

    def test_node_id_suffix_is_stripped_before_checking(self) -> None:
        """`파일::테스트명` 표기에서 파일 실재만 본다 — 노드명까지 검사하면 거짓 실패가 난다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(enforced_by=["scripts/harness/rules.py::test_something"])]
        assert _lint(text, rules) == []

    def test_unknown_task_id_is_caught(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status="task", enforced_by=["ZZZ-99"])]
        assert "L4" in _checks(_lint(text, rules))

    def test_known_task_id_is_green(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        assert _lint(text, [_rule(status="task", enforced_by=["HARN-118"])]) == []

    def test_unknown_is_not_absent_when_the_task_list_is_missing(self) -> None:
        """모른다 ≠ 아니다 — 태스크 목록을 못 받았으면 '없는 태스크'라고 단정하지 않는다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status="task", enforced_by=["ZZZ-99"])]
        assert _lint(text, rules, known_task_ids=None) == []

    def test_repo_root_none_skips_the_path_axis(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(enforced_by=["tests/nope.py"])]
        assert _lint(text, rules, repo_root=None) == []


# ── 6. L5 래칫 ──────────────────────────────────────────────────────────────


class TestL5Ratchet:
    def test_growing_prose_debt_is_caught(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n- ❌ **두 번째 규칙 금지** — 본문\n"
        rules = [
            _rule(status="prose", enforced_by=[], grandfathered=True),
            _rule(
                id="R-002",
                slug="second",
                title="두 번째 규칙 금지",
                status="prose",
                enforced_by=[],
                grandfathered=True,
            ),
        ]
        assert "L5" in _checks(_lint(text, rules, prose_baseline=1))

    def test_debt_at_the_baseline_is_green(self) -> None:
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        rules = [_rule(status="prose", enforced_by=[], grandfathered=True)]
        assert _lint(text, rules, prose_baseline=1) == []

    def test_shrinking_debt_is_green(self) -> None:
        """래칫은 줄어드는 방향으로만 열린다."""
        text = "- ❌ **표본 규칙 금지** — 본문\n"
        assert _lint(text, [_rule()], prose_baseline=1) == []


# ── 7. L6 공허한 통과 금지 ──────────────────────────────────────────────────


class TestL6VacuousPass:
    def test_empty_constitution_fails(self) -> None:
        """스캔 0건은 실패다 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다."""
        assert "L6" in _checks(_lint("", [_rule()]))

    def test_empty_ledger_fails(self) -> None:
        assert "L6" in _checks(_lint("- ❌ **표본 규칙 금지** — 본문\n", []))

    def test_missing_constitution_file_fails(self, tmp_path: Path) -> None:
        findings = rules_mod.lint_repo(tmp_path)
        assert "L6" in _checks(findings)


# ── 8. 스키마 ───────────────────────────────────────────────────────────────


class TestSchema:
    def test_minimal_rule_is_valid(self) -> None:
        assert _rule().validate() == []

    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [
            ("id", "R-1", "id"),
            ("slug", "Bad_Slug", "slug"),
            ("title", "  ", "title"),
            ("origin", "invented", "origin"),
            ("status", "maybe", "status"),
            ("grandfathered", "yes", "grandfathered"),
            ("narrative_grandfathered", 1, "narrative_grandfathered"),
            ("claude_md_line", -1, "claude_md_line"),
        ],
    )
    def test_field_violations_are_caught(self, field: str, value: object, needle: str) -> None:
        errors = _rule(**{field: value}).validate()
        assert errors and any(needle in e for e in errors), errors

    def test_code_status_requires_an_enforcement_point(self) -> None:
        errors = _rule(status="code", enforced_by=[]).validate()
        assert errors and any("enforced_by" in e for e in errors)

    def test_prose_status_must_not_carry_one(self) -> None:
        errors = _rule(status="prose", enforced_by=["x"]).validate()
        assert errors and any("enforced_by" in e for e in errors)

    def test_extension_requires_a_parent(self) -> None:
        assert _rule(origin="extension", parent="").validate()
        assert _rule(origin="extension", parent="R-001").validate() == []

    def test_parent_is_extension_only(self) -> None:
        assert _rule(origin="incident", parent="R-001").validate()

    def test_unknown_key_is_an_error(self) -> None:
        rule, errors = rules_mod.from_dict(
            {
                "id": "R-001",
                "slug": "s",
                "title": "t",
                "origin": "incident",
                "status": "prose",
                "enforcedby": [],
            },
            source="x",
        )
        assert rule is None and "enforcedby" in errors[0]

    def test_duplicate_ids_are_caught(self, tmp_path: Path) -> None:
        rules_mod.save_rules(tmp_path, [_rule(), _rule(title="다른 규칙 금지", slug="other")])
        _, errors = rules_mod.load_rules(tmp_path)
        assert errors and any("중복" in e for e in errors)

    def test_corrupt_line_names_the_exception_type(self, tmp_path: Path) -> None:
        (tmp_path / "backlog").mkdir()
        (tmp_path / "backlog" / rules_mod.LEDGER_NAME).write_text("{oops\n", encoding="utf-8")
        _, errors = rules_mod.load_rules(tmp_path)
        assert len(errors) == 1 and "JSONDecodeError" in errors[0]

    def test_roundtrip_preserves_every_field(self, tmp_path: Path) -> None:
        original = _rule(
            parent="",
            claude_md_line=42,
            series_id="unmerged-isolation",
            grandfathered=False,
            narrative_grandfathered=True,
            note="비고",
        )
        rules_mod.save_rules(tmp_path, [original])
        loaded, errors = rules_mod.load_rules(tmp_path)
        assert errors == [] and loaded == [original]


# ── 9. CLI ──────────────────────────────────────────────────────────────────


class TestCli:
    def test_lint_exits_0_on_the_live_repo(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["rules", "lint"]) == 0
        assert "green" in capsys.readouterr().out

    def test_render_check_detects_a_hand_edited_doc(self, monkeypatch, tmp_path, capsys) -> None:
        """문서는 렌더 결과다 — 손편집은 exit 1이어야 한다."""
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["rules", "render", "--check"]) == 0
        capsys.readouterr()
        doc = REPO_ROOT / rules_mod.INDEX_DOC
        original = doc.read_bytes()
        try:
            doc.write_text(original.decode("utf-8") + "\n손편집한 줄\n", encoding="utf-8")
            assert cli.main(["rules", "render", "--check"]) == 1
            assert "어긋났다" in capsys.readouterr().err
        finally:
            doc.write_bytes(original)
        assert doc.read_bytes() == original

    def test_report_json_shape(self, monkeypatch, capsys) -> None:
        monkeypatch.chdir(REPO_ROOT)
        assert cli.main(["rules", "report", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == data["prose_count"] + data["enforced_count"] + data[
            "by_status"
        ].get("policy", 0)
        assert data["prose_baseline"] == rules_mod.PROSE_BASELINE
