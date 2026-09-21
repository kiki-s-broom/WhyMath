"""오프라인 진단정확도(`compute_diagnostic_recall`)·라벨 프로브 패키지 데이터 단위테스트.

이 슬라이스는 WH-1 0단계 ②(진단-실제 오개념 일치율)를 *오프라인 진단정확도*로 계측한다 —
라벨된 recall 프로브(틀린 진술→`expected_id` 오개념)에 substring 매처 `diagnose`를 돌려 top-1
일치율(recall)을 낸다. 본 테스트는 세 갈래를 검증한다:

  ① **패키지 데이터 로드**: 프로브셋이 *프로덕션 패키지 데이터*(`probes_v1.jsonl`)로 단일화돼
     `importlib.resources`로 로드된다(설치 트리·개발 트리 공통·tests/fixtures 의존 제거).
  ② **recall 산출**(실 프로브 + 실 `diagnose`): recall 프로브만 대상(expected_id null=FP 제외)·
     top-1 expected_id 일치를 hit으로 세는 결정론 substring recall.
  ③ **정직 스코프**: 오프라인·시스템 지표·FP/precision 미포함을 모듈 docstring으로 박는다.

`diagnose`·`semantic_eval` 로직은 무변경(이 테스트는 *소비*만 한다).
"""

from __future__ import annotations

import json

import pytest

from whymath_backend.l4.misconception import probes as probes_mod
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.probes import (
    PROBES_RESOURCE,
    _iter_fp_probes,
    compute_diagnostic_recall,
    probes_path,
    probes_resource,
    read_probes_text,
)


# ──────────────────────────────────────────────────────────────────────────
# ① 패키지 데이터 로드 — 설치 트리·개발 트리 공통(importlib.resources)
# ──────────────────────────────────────────────────────────────────────────
class TestPackageDataLoading:
    def test_resource_name_and_existence(self) -> None:
        # 프로덕션 패키지 데이터 리소스가 실제로 존재한다(설치 경로에서도 접근 가능).
        assert PROBES_RESOURCE == "probes_v1.jsonl"
        assert probes_resource().is_file()

    def test_read_probes_text_is_nonempty_jsonl(self) -> None:
        text = read_probes_text()
        assert text.strip()  # 비어있지 않음
        # 각 (주석·빈 줄 아닌) 줄이 JSON 객체다.
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        # 150 + 843 트랜치5 recall·FP 각 6건 + MISC-21 recall 3·FP 4건(#1068 P1 회귀 FP 1건 추가)
        assert len(lines) == 169
        for ln in lines:
            rec = json.loads(ln)
            assert "statement" in rec

    def test_probes_path_yields_real_file(self) -> None:
        # `load_probes(path: Path)` 호환 — 컨텍스트 동안 실파일 경로를 빌려준다.
        with probes_path() as path:
            assert path.is_file()
            assert path.read_text(encoding="utf-8").strip()

    def test_probeset_recall_fp_split(self) -> None:
        # recall 프로브(expected_id 설정)와 FP 프로브(expected_id null) 둘 다 포함.
        recall = 0
        fp = 0
        for ln in read_probes_text().splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            rec = json.loads(s)
            if rec.get("expected_id") is not None:
                recall += 1
            else:
                fp += 1
        assert recall == 98  # recall 프로브 수(843 트랜치5 +6 + MISC-21 +3)
        assert fp == 71  # FP 프로브(843 트랜치5 +6 + MISC-21 +4 — #1068 P1 회귀 1건 포함)

    def test_all_expected_ids_in_catalog(self) -> None:
        # recall 프로브의 expected_id는 모두 카탈로그 id(매처가 잡을 수 있는 라벨).
        for ln in read_probes_text().splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            rec = json.loads(s)
            eid = rec.get("expected_id")
            if eid is not None:
                assert eid in CATALOG_BY_ID


# ──────────────────────────────────────────────────────────────────────────
# ② recall 산출 — 실 프로브 + 실 `diagnose`(결정론 substring·DB 0)
# ──────────────────────────────────────────────────────────────────────────
class TestComputeDiagnosticRecall:
    def test_returns_hits_and_total_recall_probes(self) -> None:
        hits, total = compute_diagnostic_recall()
        # total = recall 프로브 수(expected_id null=FP 제외) = 98.
        assert total == 98
        # hits ∈ [0, total](실측 — substring·regex 매처 품질).
        assert 0 <= hits <= total

    def test_deterministic(self) -> None:
        # 순수·결정론(임베딩·DB·네트워크 0) — 두 번 호출 동일.
        assert compute_diagnostic_recall() == compute_diagnostic_recall()

    def test_recall_matches_manual_top1_over_recall_probes_only(self) -> None:
        """수동 재현 — recall 프로브만 대상·top-1 expected_id 일치를 hit으로(FP 프로브 제외).

        `compute_diagnostic_recall`이 *recall 프로브만*(expected_id not null) 대상으로
        *top-1*(`diagnose(...)[0].misconception.id == expected_id`)을 세는지, 실 프로브셋과 실
        `diagnose`로 독립 재현해 정확히 일치시킨다(FP 프로브가 섞이지 않음을 보장).
        """
        manual_hits = 0
        manual_total = 0
        for ln in read_probes_text().splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            rec = json.loads(s)
            eid = rec.get("expected_id")
            if eid is None:  # FP 프로브 — recall 대상 아님
                continue
            manual_total += 1
            matches = diagnose(rec["statement"])
            if matches and matches[0].misconception.id == eid:
                manual_hits += 1
        assert (manual_hits, manual_total) == compute_diagnostic_recall()

    def test_fp_probes_excluded_from_total(self) -> None:
        # total(recall 프로브 98) < 전체 프로브(169) — FP 프로브 71건이 제외됐다.
        _, total = compute_diagnostic_recall()
        all_probes = sum(
            1
            for ln in read_probes_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        )
        assert all_probes == 169
        assert total == 98
        assert total < all_probes


# ──────────────────────────────────────────────────────────────────────────
# 파싱 관용성 — 빈 줄/주석 무시·잘못된 JSON은 줄 번호와 함께 ValueError(load_probes 동형)
# ──────────────────────────────────────────────────────────────────────────
class TestParsingTolerance:
    def test_blank_and_comment_lines_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 빈 줄·`#` 주석은 무시하고, expected_id 설정 줄만 recall 프로브로 센다.
        # (statement에 distribution-over-power 카탈로그 신호를 심어 hit 1건 확정.)
        eid = "distribution-over-power"
        signals = "".join(CATALOG_BY_ID[eid].signals)
        fake = "\n".join(
            [
                "  # 주석 줄",
                "",
                json.dumps({"statement": signals, "expected_id": eid, "kind": "paraphrase"}),
                json.dumps({"statement": "올바른 진술", "expected_id": None, "near_id": eid}),
            ]
        )
        monkeypatch.setattr(probes_mod, "read_probes_text", lambda: fake)
        hits, total = compute_diagnostic_recall()
        assert total == 1  # recall 프로브 1건(FP·주석·빈 줄 제외)
        assert hits == 1  # 심은 신호로 top-1 매칭

    def test_malformed_json_raises_with_line_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 잘못된 JSON 줄은 줄 번호 컨텍스트와 함께 ValueError로 던진다(load_probes 동형).
        fake = "\n".join(
            [
                json.dumps({"statement": "ok", "expected_id": "x"}),
                "{ not valid json",
            ]
        )
        monkeypatch.setattr(probes_mod, "read_probes_text", lambda: fake)
        with pytest.raises(ValueError, match="line 2"):
            compute_diagnostic_recall()

    def test_zero_recall_probes_returns_zero_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # FP 프로브만 있으면 recall 프로브 0 → (0, 0)(하네스가 NO_DATA로 분기·날조 0 회피).
        fake = json.dumps({"statement": "올바른 진술", "expected_id": None, "near_id": "x"})
        monkeypatch.setattr(probes_mod, "read_probes_text", lambda: fake)
        assert compute_diagnostic_recall() == (0, 0)


# ──────────────────────────────────────────────────────────────────────────
# ②' FP 프로브 추출 — 정밀도 회귀 가드(harness/agreement_gate)의 입력 좌석
# ──────────────────────────────────────────────────────────────────────────
class TestIterFpProbes:
    def test_returns_only_fp_statements(self) -> None:
        # 실 프로브셋의 FP(올바른 진술·expected_id null)만 추출 — 수는 split 테스트와 일치(70).
        fp = _iter_fp_probes()
        assert len(fp) == 71
        assert all(isinstance(s, str) and s for s in fp)
        # FP statement 집합은 recall statement와 서로소여야(같은 진술이 양쪽일 수 없음).
        recall_statements = {
            json.loads(ln)["statement"]
            for ln in read_probes_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#") and json.loads(ln).get("expected_id")
        }
        assert recall_statements.isdisjoint(set(fp))

    def test_blank_comment_and_recall_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 빈 줄·주석·recall 프로브(expected_id 설정)는 제외하고 FP(null)만 남긴다.
        fake = "\n".join(
            [
                "  # 주석",
                "",
                json.dumps({"statement": "틀린 진술", "expected_id": "x"}),  # recall → 제외
                json.dumps({"statement": "올바른 진술 A", "expected_id": None, "near_id": "x"}),
                json.dumps({"statement": "올바른 진술 B", "expected_id": None}),
            ]
        )
        monkeypatch.setattr(probes_mod, "read_probes_text", lambda: fake)
        assert _iter_fp_probes() == ["올바른 진술 A", "올바른 진술 B"]

    def test_malformed_json_raises_with_line_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 잘못된 JSON 줄은 줄 번호 컨텍스트와 함께 ValueError(recall 이터레이터 동형).
        fake = "\n".join(
            [
                json.dumps({"statement": "올바른 진술", "expected_id": None}),
                "{ not valid json",
            ]
        )
        monkeypatch.setattr(probes_mod, "read_probes_text", lambda: fake)
        with pytest.raises(ValueError, match="line 2"):
            _iter_fp_probes()


# ──────────────────────────────────────────────────────────────────────────
# ③ 정직 스코프 — 오프라인·시스템 지표·precision 미포함을 모듈 docstring으로 박는다
# ──────────────────────────────────────────────────────────────────────────
class TestHonestyScope:
    def test_module_docstring_marks_offline_system_metric(self) -> None:
        import whymath_backend.l4.misconception.probes as probes_mod

        doc = probes_mod.__doc__ or ""
        # LIVE 학생별 ground-truth가 아니라 시스템 지표
        assert "ground-truth" in doc
        assert "시스템 진단엔진 품질" in doc
        # substring 보수적 기준선·FP/precision 범위 밖
        assert "substring" in doc
        assert "precision" in doc or "FP율" in doc

    def test_compute_docstring_defines_top1(self) -> None:
        doc = compute_diagnostic_recall.__doc__ or ""
        assert "top-1" in doc
        assert "expected_id" in doc
