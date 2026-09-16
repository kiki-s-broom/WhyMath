"""Phase 1 구조 지표 리포터 동결 — 계획서 200 §36 (EOS-08).

이 파일이 막는 것은 **세 가지 위장**이다.

1. **미측정이 0으로 위장** — 산출 불가한 지표가 `value=0`으로 나오면 소비처는 "그 축이
   깨끗하다"로 읽는다. `measured=False`인 지표는 `value`가 **반드시 None**이어야 한다.
2. **리포터가 판정기로 승격** — 지표 값이 나쁘다고 exit 1을 내기 시작하면 스코어카드와
   서로 다른 합격을 말하게 되고, 그때 "무엇을 통과했는가"가 결정 불가가 된다.
3. **분모의 조용한 확장** — 비율의 분모는 계획서가 고정한 목록이다. 분모를 늘리면 같은
   분자로 비율이 내려가고, 줄이면 올라간다. 즉 **분모를 건드리는 것만으로 지표를 조작할 수
   있으므로**, 개수와 출처를 여기서 동결한다.

집행 지점 표(`CONTRACT_CHECKS`·`SLICE_STAGES`)는 경로와 심볼을 박아 둔다 — 그 지점이
옮겨지면 이 테스트가 RED로 알린다(정적 경로 참조가 썩는 것을 막는 유일한 방법이다).
"""

from __future__ import annotations

from whymath_backend.ops import phase1_structure_report as rep


class TestDenominatorsAreFrozenToThePlan:
    def test_contract_checks_match_plan_section_27(self) -> None:
        """계획서 200 §27이 든 계약 검사는 6종이다 — 늘리려면 계획서가 바뀌어야 한다."""
        assert len(rep.CONTRACT_CHECKS) == 6
        assert len({c[0] for c in rep.CONTRACT_CHECKS}) == 6, "문면 중복 — 분모가 부풀었다"

    def test_slice_stages_match_plan_section_39(self) -> None:
        """계획서 200 §39가 든 관통 단계는 12종이다."""
        assert len(rep.SLICE_STAGES) == 12
        assert len({s[0] for s in rep.SLICE_STAGES}) == 12, "단계명 중복 — 분모가 부풀었다"

    def test_every_claimed_evidence_path_actually_exists(self) -> None:
        """근거로 지목한 파일이 실재하는가 — 경로가 썩으면 비율이 조용히 떨어진다.

        빈 경로는 "아직 안 덮는다"는 정직한 표기이므로 대상이 아니다.
        """
        missing = [
            (label, path)
            for label, path, _needle in (*rep.CONTRACT_CHECKS, *rep.SLICE_STAGES)
            if path and not (rep._REPO_ROOT / path).is_file()
        ]
        assert not missing, f"근거 경로가 실재하지 않는다(집행 지점이 옮겨졌나): {missing}"

    def test_evidence_needles_are_specific_enough_to_mean_something(self) -> None:
        """근거 문자열이 **그 단계를 가리키는가** — 흔한 토큰이면 비율이 부풀려진다.

        실측(뮤테이션 M8·2026-09-16): 아직 안 덮는 단계에 `"def "`를 붙이면 그 단계가 커버로
        계상되고 비율이 오른다. 경로 실재만 보는 검사는 그것을 통과시킨다.

        그래서 두 축을 요구한다 — ① 최소 길이 ② 도메인 표식(경로 `/`·식별자 `_`·대문자) 중
        하나. 둘 다 없는 문자열은 언어 키워드나 범용 토큰이라 단계를 식별하지 못한다.
        보강으로 **적중 수 상한**을 둔다: 한 파일에서 수십 번 나오는 문자열은 그 단계의
        증거가 아니라 그 파일의 배경이다.

        **이 검사의 한계(명시)**: 표는 손으로 유지하는 *증거*이지 증명이 아니다. 작정하고
        그럴듯한 문자열을 고르면 여전히 부풀릴 수 있다 — 이 검사가 막는 것은 부패(경로가
        썩음)와 **눈에 띄는** 부풀림이지, 의도적 위조가 아니다.
        """
        weak: list[tuple[str, str, str]] = []
        for label, path, needle in (*rep.CONTRACT_CHECKS, *rep.SLICE_STAGES):
            if not path or not needle:
                continue  # 빈 값은 "아직 안 덮는다"는 정직한 표기다
            specific = len(needle) >= 6 and any(
                ch == "/" or ch == "_" or ch.isupper() for ch in needle
            )
            hits = (
                (rep._REPO_ROOT / path).read_text(encoding="utf-8", errors="replace").count(needle)
            )
            if not specific:
                weak.append((label, needle, "구체성 부족(길이·도메인 표식)"))
            elif hits > 30:
                weak.append((label, needle, f"적중 {hits}회 — 단계의 증거가 아니라 파일의 배경"))
        assert not weak, f"근거 문자열이 단계를 식별하지 못한다: {weak}"

    def test_each_stage_has_its_own_evidence_not_a_borrowed_one(self) -> None:
        """한 단계의 근거를 다른 단계가 **빌려 쓰지** 않는가 — 가장 현실적인 부풀림 경로다.

        아직 안 덮는 단계에 *이미 통하는* 근거 문자열을 복사해 붙이면 비율이 오른다. 그 문자열은
        구체적이고 실제로 적중하므로 위의 두 축(경로 실재·구체성)을 전부 통과한다. 근거의
        **유일성**만이 그것을 잡는다.

        잡지 못하는 것(정직 표기): 빌려 쓰지 않고 *새로* 그럴듯한 문자열을 고르면 여전히 통과한다
        — 그 판정은 "이 문자열이 이 단계를 증명하는가"라는 의미 판단이라 정적 검사로 갈 수 없다.
        이 표는 손으로 유지하는 **증거**이지 증명이 아니다(위 docstring의 한계와 같은 축).
        """
        seen: dict[str, str] = {}
        borrowed: list[str] = []
        for label, path, needle in (*rep.CONTRACT_CHECKS, *rep.SLICE_STAGES):
            if not path or not needle:
                continue
            key = f"{path}::{needle}"
            if key in seen:
                borrowed.append(f"{label!r} 이 {seen[key]!r} 의 근거를 그대로 쓴다: {needle!r}")
            seen[key] = label
        assert not borrowed, "근거를 빌려 쓴 단계가 있다(비율 부풀림): " + "; ".join(borrowed)


class TestUnmeasuredIsNeverZero:
    def test_unmeasured_metric_carries_none_not_zero(self) -> None:
        """`measured=False`인데 값이 0이면 '깨끗하다'로 읽힌다 — 정반대 의미다."""
        report = rep.build_report(database_url=None)
        for metric in report.metrics:
            if not metric.measured:
                assert (
                    metric.value is None
                ), f"{metric.name}: 미측정인데 value={metric.value!r} — 0/값은 위장이다"
                assert metric.detail, f"{metric.name}: 미측정 사유가 비었다"

    def test_db_absent_reports_integrity_as_unmeasured(self) -> None:
        """DB URL이 없으면 무결성은 **0건이 아니라 미측정**이다."""
        report = rep.build_report(database_url=None)
        integrity = next(m for m in report.metrics if m.name == "Data integrity violations")
        assert integrity.measured is False
        assert integrity.value is None

    def test_migration_percent_is_unmeasured_by_design(self) -> None:
        """이관 완료율은 분자가 없다 — 장부에 진척 필드가 생기기 전까지 미측정이다."""
        report = rep.build_report(database_url=None)
        migration = next(m for m in report.metrics if m.name == "EOS migration %")
        assert migration.measured is False
        assert migration.value is None


class TestReporterNeverBecomesAVerdict:
    def test_all_five_numbers_are_present(self) -> None:
        report = rep.build_report(database_url=None)
        assert [m.name for m in report.metrics] == [
            "Contract coverage",
            "EOS migration %",
            "Broken dependency count",
            "Data integrity violations",
            "Vertical Slice pass %",
        ]

    def test_exit_code_does_not_depend_on_metric_values(self) -> None:
        """지표가 나빠도 exit 0이다 — 합격 선언은 스코어카드의 몫이다."""
        assert rep.main([]) == 0

    def test_render_marks_unmeasured_visibly_and_disclaims_verdict(self) -> None:
        """출력이 미측정을 눈에 띄게 표시하고, 판정기가 아님을 화면에서도 말하는가."""
        text = rep.render(rep.build_report(database_url=None))
        assert "미측정" in text
        assert "판정기가 아니다" in text, "화면에서 판정기 아님을 말하지 않으면 오인된다"
        assert "validation_scorecard" in text, "진짜 판정기를 지목하지 않는다"
