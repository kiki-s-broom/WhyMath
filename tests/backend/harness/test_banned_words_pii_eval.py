"""학생 대면 산문 금칙어·PII 배치 스캔 테스트(ARCH-24) — hermetic·변별력 실측.

대상: `whymath_backend.harness.banned_words_pii_eval`. 실 코퍼스·DB·LLM·네트워크 0 —
전부 tmp_path에 만든 소형 픽스처로 검증한다(`test_problem_bank_coverage.py` 패턴 답습).

**변별력 실측**(CLAUDE.md "변별력 없는 검증 스텝 금지" — acceptance 명시 의무): 금칙어 1개를
주입한 fixture는 실제로 `main()` exit 1을 내고, 무결 fixture는 실제로 exit 0을 낸다는 것을
양쪽 다 CLI 통합 테스트로 실행·확인한다. PII 두 방향(third_party·self_reflection)도 각각
최소 1개 양성 케이스로 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import banned_words_pii_eval as bwp

# ──────────────────────────────────────────────────────────────────────────
# 픽스처 헬퍼 — 코퍼스 3종의 실측 스키마를 최소 재현
# ──────────────────────────────────────────────────────────────────────────


def _write_problem_bank(
    corpus_root: Path,
    name: str,
    problems: list[dict[str, object]],
) -> None:
    bank = corpus_root / name
    bank.mkdir(parents=True)
    lines = [json.dumps(p, ensure_ascii=False) for p in problems]
    (bank / "problems.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_concept_content(corpus_root: Path, items: list[dict[str, object]]) -> None:
    d = corpus_root / "concept_content_v1"
    d.mkdir(parents=True)
    payload = {"content": items}
    (d / "content.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_misconceptions(corpus_root: Path, items: list[dict[str, object]]) -> None:
    d = corpus_root / "misconceptions_v1"
    d.mkdir(parents=True)
    payload = {"misconceptions": items}
    (d / "misconceptions.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _clean_corpus(corpus_root: Path) -> None:
    """3종 코퍼스 전부 무결(위반 0건) 상태로 채운다 — exit 0 기준 픽스처."""
    _write_problem_bank(
        corpus_root,
        "problem_bank_v1",
        [
            {
                "problem_id": "p1",
                "question_text": "이차방정식 x^2-5x+6=0의 두 근을 구하시오.",
                "answer_explanation": "인수분해하면 (x-2)(x-3)=0이므로 근은 2와 3이다.",
            }
        ],
    )
    _write_concept_content(
        corpus_root,
        [
            {
                "code": "N1",
                "explanation": "수의 필요성을 알고 0~100까지 세고 읽고 쓴다.",
                "metaphor": "사물 하나에 손가락 하나씩 짝지어 센다.",
                "formal_definition_internal": "수는 사물의 개수와 순서를 나타낸다.",
            }
        ],
    )
    _write_misconceptions(
        corpus_root,
        [
            {
                "mis_id": "M0001",
                "student_wrong_thinking": "서수와 기수를 혼동한다.",
                "correction_point": "개수를 셀 때는 기수, 차례를 셀 때는 서수를 쓴다.",
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────────
# scan_field(순수) — 금칙어·PII 판정 단위테스트
# ──────────────────────────────────────────────────────────────────────────


class TestScanField:
    def test_clean_text_no_hits(self) -> None:
        result = bwp.scan_field("이차방정식의 두 근을 구하시오.")
        assert result == bwp.FieldScanResult(
            banned_word_hit=False, pii_third_party_hit=False, pii_self_reflection_hit=False
        )

    def test_banned_word_detected(self) -> None:
        word = next(iter(bwp.BANNED_WORDS_KO))
        result = bwp.scan_field(f"이렇게 풀면 {word} 안 된다고 생각했다.")
        assert result.banned_word_hit is True

    def test_email_pii_detected_as_third_party_by_default(self) -> None:
        result = bwp.scan_field("문의는 student.example@test.com 으로 연락하세요.")
        assert result.pii_third_party_hit is True
        assert result.pii_self_reflection_hit is False

    def test_korean_phone_pii_detected_as_third_party_by_default(self) -> None:
        result = bwp.scan_field("보호자 연락처는 010-1234-5678 입니다.")
        assert result.pii_third_party_hit is True
        assert result.pii_self_reflection_hit is False

    def test_known_student_pii_classifies_as_self_reflection(self) -> None:
        # 방향 1(self_reflection) 양성 케이스 — known_student_pii에 매치값이 있으면 반사로 분류.
        result = bwp.scan_field(
            "학생이 남긴 연락처 student.example@test.com 을 그대로 돌려줬다.",
            known_student_pii=frozenset({"student.example@test.com"}),
        )
        assert result.pii_self_reflection_hit is True
        assert result.pii_third_party_hit is False


class TestClassifyPiiMatch:
    def test_third_party_when_not_known(self) -> None:
        assert bwp.classify_pii_match("010-1234-5678") == "third_party"

    def test_self_reflection_when_known(self) -> None:
        # 방향 1(self_reflection) 양성 케이스 — 분류 함수 자체의 변별력.
        assert (
            bwp.classify_pii_match("010-1234-5678", known_student_pii=frozenset({"010-1234-5678"}))
            == "self_reflection"
        )


# ──────────────────────────────────────────────────────────────────────────
# 로더 — 정직 회계(파싱 실패·타입 위반 카운트)
# ──────────────────────────────────────────────────────────────────────────


class TestLoaders:
    def test_load_problem_bank_fields_reads_question_and_explanation(self, tmp_path: Path) -> None:
        _write_problem_bank(
            tmp_path,
            "problem_bank_v1",
            [{"problem_id": "p1", "question_text": "문제", "answer_explanation": "해설"}],
        )
        fields, errors = bwp.load_problem_bank_fields(tmp_path)
        assert errors == []
        assert {f.field for f in fields} == {"question_text", "answer_explanation"}
        assert {f.corpus for f in fields} == {"problem_bank_v1"}

    def test_load_problem_bank_fields_counts_malformed_line(self, tmp_path: Path) -> None:
        bank = tmp_path / "problem_bank_v1"
        bank.mkdir(parents=True)
        (bank / "problems.jsonl").write_text(
            '{"problem_id": "p1", "question_text": "문제"}\nNOT_JSON\n', encoding="utf-8"
        )
        fields, errors = bwp.load_problem_bank_fields(tmp_path)
        assert len(fields) == 1  # question_text만(answer_explanation 없음)
        assert len(errors) == 1
        assert errors[0].error_type == "JSONDecodeError"

    def test_load_problem_bank_fields_counts_non_string_field_type(self, tmp_path: Path) -> None:
        _write_problem_bank(
            tmp_path,
            "problem_bank_v1",
            [{"problem_id": "p1", "question_text": 12345, "answer_explanation": "해설"}],
        )
        fields, errors = bwp.load_problem_bank_fields(tmp_path)
        assert len(fields) == 1  # answer_explanation만
        assert len(errors) == 1
        assert errors[0].error_type == "TypeError"

    def test_load_concept_content_fields_reads_three_fields(self, tmp_path: Path) -> None:
        _write_concept_content(
            tmp_path,
            [
                {
                    "code": "N1",
                    "explanation": "설명",
                    "metaphor": "비유",
                    "formal_definition_internal": "정의",
                }
            ],
        )
        fields, errors = bwp.load_concept_content_fields(tmp_path)
        assert errors == []
        assert {f.field for f in fields} == {
            "explanation",
            "metaphor",
            "formal_definition_internal",
        }

    def test_load_misconceptions_fields_reads_two_fields(self, tmp_path: Path) -> None:
        _write_misconceptions(
            tmp_path,
            [{"mis_id": "M0001", "student_wrong_thinking": "오개념", "correction_point": "교정"}],
        )
        fields, errors = bwp.load_misconceptions_fields(tmp_path)
        assert errors == []
        assert {f.field for f in fields} == {"student_wrong_thinking", "correction_point"}

    def test_missing_corpus_files_are_not_errors(self, tmp_path: Path) -> None:
        # 코퍼스 디렉터리 자체가 없으면 "데이터없음"(정당한 상태) — 에러로 세지 않는다.
        fields, errors = bwp.discover_fields(tmp_path)
        assert fields == []
        assert errors == []


# ──────────────────────────────────────────────────────────────────────────
# run() — 집계 정확성
# ──────────────────────────────────────────────────────────────────────────


class TestRun:
    def test_clean_corpus_zero_hits(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        report = bwp.run(tmp_path)
        assert report.fields_scanned == 2 + 3 + 2  # 문제은행2 + 콘텐츠3 + 오개념2
        assert report.banned_word_hits == 0
        assert report.pii_third_party_hits == 0
        assert report.pii_self_reflection_hits == 0
        assert report.parse_error_count == 0

    def test_injected_banned_word_counted(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        word = next(iter(bwp.BANNED_WORDS_KO))
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty",
            [
                {
                    "problem_id": "bad1",
                    "question_text": f"이 문제는 {word} 표현을 포함한다.",
                    "answer_explanation": "정상 해설.",
                }
            ],
        )
        report = bwp.run(tmp_path)
        assert report.banned_word_hits == 1

    def test_injected_third_party_pii_counted(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty",
            [
                {
                    "problem_id": "bad2",
                    "question_text": "정상 문제.",
                    "answer_explanation": "연락처는 010-9999-8888 로 문의하세요.",
                }
            ],
        )
        report = bwp.run(tmp_path)
        assert report.pii_third_party_hits == 1
        assert report.pii_self_reflection_hits == 0

    def test_by_corpus_breakdown_present(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        report = bwp.run(tmp_path)
        assert "problem_bank_v1" in report.by_corpus
        assert "concept_content_v1" in report.by_corpus
        assert "misconceptions_v1" in report.by_corpus


class TestViolationRateUpperBound:
    def test_zero_hits_gives_small_positive_upper_bound(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        report = bwp.run(tmp_path)
        upper = report.violation_rate_upper_bound()
        # Wilson 상한은 유한 표본에서 절대 정확히 0이 아니다(모듈 docstring 근거 절). 작은
        # fixture(7건)는 표본이 작아 상한이 크다(≈0.28) — 기본 임계(0.001)는 실제 코퍼스
        # 규모(7,780건)를 기준으로 근거를 남긴 상수라 이 작은 fixture에는 적용하지 않는다
        # (아래 `test_real_repo_corpus_passes_default_threshold`가 실제 규모를 검증한다).
        assert 0.0 < upper < 1.0

    def test_real_repo_corpus_passes_default_threshold(self) -> None:
        """실제 커밋 코퍼스(hermetic 아님·`qa_pipeline` CLI 통합테스트와 동일 관례)로 기본
        임계 0.001의 근거(모듈 docstring "게이트" 절)가 실측과 맞는지 회귀 검증한다."""
        report = bwp.run(bwp.DEFAULT_CORPUS_ROOT)
        assert report.fields_scanned > 0
        assert report.violation_rate_upper_bound() <= bwp._DEFAULT_MAX_VIOLATION_RATE_UPPER


# ──────────────────────────────────────────────────────────────────────────
# CLI 통합 — main()을 실제로 끝까지 돌려 exit code 실측(acceptance 변별력 의무)
# ──────────────────────────────────────────────────────────────────────────


class TestCliMain:
    def test_clean_fixture_exits_zero(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        # 소형 fixture(7건)는 Wilson 상한이 표본 크기 때문에 크다(≈0.28, 모듈 docstring
        # "게이트" 절 근거) — 기본 임계(0.001)는 실 코퍼스 규모(7,780건)에 맞춘 상수라
        # 여기서는 "위반 0건이면 통과한다"는 배관 자체를 검증하도록 넉넉한 임계를 명시한다.
        # (기본 임계의 실제 규모 회귀는 `test_real_repo_corpus_passes_default_threshold`.)
        rc = bwp.main(["--corpus-root", str(tmp_path), "--max-violation-rate-upper", "0.9"])
        assert rc == 0

    def test_injected_banned_word_exits_one(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        word = next(iter(bwp.BANNED_WORDS_KO))
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty",
            [
                {
                    "problem_id": "bad1",
                    "question_text": f"{word} 라는 표현이 섞였다.",
                    "answer_explanation": "정상 해설.",
                }
            ],
        )
        rc = bwp.main(["--corpus-root", str(tmp_path)])
        assert rc == 1

    def test_injected_third_party_pii_exits_one(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty",
            [
                {
                    "problem_id": "bad2",
                    "question_text": "정상 문제.",
                    "answer_explanation": "예시 학생 이메일은 real.student@example.com 입니다.",
                }
            ],
        )
        rc = bwp.main(["--corpus-root", str(tmp_path)])
        assert rc == 1

    def test_empty_corpus_root_exits_input_error(self, tmp_path: Path) -> None:
        rc = bwp.main(["--corpus-root", str(tmp_path)])
        assert rc == 2

    def test_json_report_written(self, tmp_path: Path) -> None:
        _clean_corpus(tmp_path)
        json_path = tmp_path / "out.json"
        rc = bwp.main(
            [
                "--corpus-root",
                str(tmp_path),
                "--json",
                str(json_path),
                "--max-violation-rate-upper",
                "0.9",
            ]
        )
        assert rc == 0
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["fields_scanned"] == 7
        assert payload["banned_word_hits"] == 0
        assert "violation_rate_upper_bound" in payload

    def test_custom_threshold_can_tolerate_injected_pii(self, tmp_path: Path) -> None:
        # 변별력 대조 — 임계를 1.0으로 완화하면 같은 위반 주입 fixture도 exit 0이어야
        # 한다(게이트가 실제로 임계값을 보고 있다는 증거, 하드코딩된 exit 1이 아님).
        _clean_corpus(tmp_path)
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty",
            [{"problem_id": "bad3", "question_text": "정상.", "answer_explanation": "정상."}],
        )
        word = next(iter(bwp.BANNED_WORDS_KO))
        _write_problem_bank(
            tmp_path,
            "problem_bank_dirty2",
            [
                {
                    "problem_id": "bad4",
                    "question_text": f"{word}",
                    "answer_explanation": "정상.",
                }
            ],
        )
        rc = bwp.main(["--corpus-root", str(tmp_path), "--max-violation-rate-upper", "1.0"])
        assert rc == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


class TestKoreanAdjacentPii:
    """SEC-38 — 조사가 붙은 PII도 검출한다(종전 테스트는 `… 으로`처럼 띄어 써서 사각을 비껴갔다)."""

    def test_phone_followed_by_particle_is_detected(self) -> None:
        result = bwp.scan_field("보호자 연락처는 010-1234-5678로 문의하세요.")
        assert result.pii_third_party_hit is True

    def test_email_followed_by_particle_is_detected(self) -> None:
        result = bwp.scan_field("문의는 student.example@test.com으로 연락하세요.")
        assert result.pii_third_party_hit is True
