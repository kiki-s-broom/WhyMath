"""오개념 카탈로그 정의 충족도 감사 단위테스트 — WH-1 0단계 ③.

실 `CATALOG`(canned 아님)에 대한 순수·결정론 집계를 검증한다. 카탈로그가 진화해도 깨지지
않도록 *실측에 일관한* 단언(정확치 또는 범위)을 쓴다. **정직 스코프**: 본 감사는 카탈로그
*정의* 충족도이며 학생 예시 코퍼스 충족률(§8.4 L193·LIVE)이 아님을 코드로 강제하진 않으나
(docstring 명시), 측정 대상이 정적 카탈로그임을 DB 미접근(순수)으로 보장한다.
"""

from __future__ import annotations

from whymath_backend.l4.misconception.audit import (
    CatalogAuditItem,
    CatalogAuditReport,
    DomainAuditSummary,
    audit_catalog_coverage,
)
from whymath_backend.l4.misconception.catalog import BODY_CATALOG, CATALOG


class TestReportShape:
    def test_total_matches_catalog(self) -> None:
        report = audit_catalog_coverage()
        # 감사 대상은 본문 채널 항목(P3-61: 선지 역추적 전용은 신호가 정의상 0이라 제외) — 전체 카탈로그보다
        # 정확히 그만큼 적다(제외가 조용히 사라지거나 과다해지지 않게 차이를 함께 고정한다).
        assert report.total == len(BODY_CATALOG)
        assert len(report.items) == len(BODY_CATALOG)
        assert len(CATALOG) - report.total == 4

    def test_report_field_set(self) -> None:
        assert set(CatalogAuditReport.model_fields) == {
            "total",
            "items",
            "canonical_rate",
            "counterexample_rate",
            "signals_ge_min_rate",
            "regex_coverage_rate",
            "saturation_rate",
            "by_domain",
        }

    def test_item_field_set(self) -> None:
        assert set(CatalogAuditItem.model_fields) == {
            "misconception_id",
            "domain",
            "signals_count",
            "regex_signals_count",
            "has_counterexample",
            "has_canonical_statement",
            "is_signal_saturated",
        }

    def test_domain_summary_field_set(self) -> None:
        assert set(DomainAuditSummary.model_fields) == {
            "domain",
            "n",
            "n_saturated",
            "n_signals_ge_min",
            "saturation_rate",
        }

    def test_report_and_items_are_frozen(self) -> None:
        report = audit_catalog_coverage()
        assert report.model_config.get("frozen") is True
        assert report.items[0].model_config.get("frozen") is True
        assert report.by_domain[0].model_config.get("frozen") is True


class TestRates:
    def test_canonical_and_counterexample_fully_filled(self) -> None:
        # 현 카탈로그 30종 전부 canonical_statement·counterexample이 채워져 있다.
        report = audit_catalog_coverage()
        assert report.canonical_rate == 1.0
        assert report.counterexample_rate == 1.0
        assert all(it.has_canonical_statement for it in report.items)
        assert all(it.has_counterexample for it in report.items)

    def test_signals_ge_min_rate_in_unit_interval(self) -> None:
        report = audit_catalog_coverage()
        assert 0.0 < report.signals_ge_min_rate <= 1.0

    def test_all_rates_in_unit_interval(self) -> None:
        report = audit_catalog_coverage()
        for rate in (
            report.canonical_rate,
            report.counterexample_rate,
            report.signals_ge_min_rate,
            report.regex_coverage_rate,
            report.saturation_rate,
        ):
            assert 0.0 <= rate <= 1.0

    def test_regex_coverage_and_saturation_consistent(self) -> None:
        # 시연된 regex_signals 종 수가 곧 regex_coverage·saturation 분자(현 카탈로그는
        # regex 보유 항목이 모두 signals>=2라 두 율이 일치).
        report = audit_catalog_coverage()
        n_regex = sum(1 for m in BODY_CATALOG if len(m.regex_signals) >= 1)
        assert report.regex_coverage_rate == n_regex / len(BODY_CATALOG)
        n_saturated = sum(
            1 for m in BODY_CATALOG if len(m.signals) >= 2 and len(m.regex_signals) >= 1
        )
        assert report.saturation_rate == n_saturated / len(BODY_CATALOG)

    def test_rates_match_item_counts(self) -> None:
        report = audit_catalog_coverage()
        total = report.total
        assert report.signals_ge_min_rate == (
            sum(1 for it in report.items if it.signals_count >= 2) / total
        )
        assert report.saturation_rate == (
            sum(1 for it in report.items if it.is_signal_saturated) / total
        )


class TestSignalSaturationDefinition:
    def test_saturation_requires_signals_ge_2_and_regex_ge_1(self) -> None:
        # is_signal_saturated 정의: signals_count >= 2 AND regex_signals_count >= 1.
        report = audit_catalog_coverage()
        for it in report.items:
            expected = it.signals_count >= 2 and it.regex_signals_count >= 1
            assert it.is_signal_saturated is expected

    def test_saturation_implies_signals_ge_min(self) -> None:
        # 포화 항목은 반드시 신호 권장치를 충족한다(상위 조건).
        report = audit_catalog_coverage()
        for it in report.items:
            if it.is_signal_saturated:
                assert it.signals_count >= 2


class TestByDomain:
    def test_domain_n_sum_equals_total(self) -> None:
        report = audit_catalog_coverage()
        assert sum(d.n for d in report.by_domain) == report.total

    def test_domains_sorted_by_value(self) -> None:
        report = audit_catalog_coverage()
        domains = [d.domain for d in report.by_domain]
        assert domains == sorted(domains)

    def test_per_domain_counts_accurate(self) -> None:
        report = audit_catalog_coverage()
        for summary in report.by_domain:
            members = [m for m in BODY_CATALOG if m.domain == summary.domain]
            assert summary.n == len(members)
            assert summary.n_signals_ge_min == sum(1 for m in members if len(m.signals) >= 2)
            assert summary.n_saturated == sum(
                1 for m in members if len(m.signals) >= 2 and len(m.regex_signals) >= 1
            )
            expected_rate = summary.n_saturated / summary.n if summary.n else 0.0
            assert summary.saturation_rate == expected_rate

    def test_domain_saturation_rate_in_unit_interval(self) -> None:
        report = audit_catalog_coverage()
        for d in report.by_domain:
            assert 0.0 <= d.saturation_rate <= 1.0


class TestOrderingAndDeterminism:
    def test_items_sorted_by_id(self) -> None:
        report = audit_catalog_coverage()
        ids = [it.misconception_id for it in report.items]
        assert ids == sorted(ids)

    def test_deterministic_across_calls(self) -> None:
        # 인자 0·DB 0·순수 — 2회 호출이 동일 리포트.
        assert audit_catalog_coverage() == audit_catalog_coverage()

    def test_no_mutation_of_catalog(self) -> None:
        before = tuple((m.id, m.signals, m.regex_signals) for m in CATALOG)
        audit_catalog_coverage()
        after = tuple((m.id, m.signals, m.regex_signals) for m in CATALOG)
        assert before == after
