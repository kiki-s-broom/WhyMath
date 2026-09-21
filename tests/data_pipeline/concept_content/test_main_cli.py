"""K-12 콘텐츠 CLI 단위테스트 — 합성 xlsx로 개념+암기카드 조인·대학 필터·NCIC 본문 컬럼 미수록.

2026-09-06부터 CLI는 `--standards`(NCIC 성취기준 코퍼스)를 읽어 `explanation` 겹침을 실측하고
그 숫자로 라이선스 선언을 합성한다. 측정 없이 선언을 쓰지 않으므로 코퍼스가 없으면 exit 2다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from data_pipeline.concept_content.__main__ import main  # noqa: E402

_CONCEPT_HDR = [
    "순서",
    "학교급",
    "과목",
    "단원(영역)",
    "개념ID",
    "개념명",
    "성취기준 문장",
    "성취기준 요약(간결)",
    "분류",
    "난이도층",
    "연결 성취기준",
    "매칭 CCSS",
    "설명",
    "은유",
    "오개념",
    "정식정의(내부·학생비노출)",
    "허용표현(인정 표현)",
    "정의출처",
    "암기카드수",
    "비고",
    "연결 성취기준(원본·2015)",
]
_CARD_HDR = [
    "등급",
    "단원(분류)",
    "난이도층",
    "개념ID",
    "개념명",
    "앞면(front)",
    "뒷면(back)",
    "암기보조(mnemonic)",
    "노출조건",
]


_EXPLANATION = "정규확장→갈루아군"
"""합성 행의 `설명` 컬럼 값 — 겹침 실측 테스트가 이 값을 성취기준 본문으로 재사용한다."""


def _concept_row(
    code: str,
    school: str = "초등(1~2학년군)",
    linked: str = "[2수01-01]",
) -> list[object]:
    return [
        "1",
        school,
        "수학(초1~2)",
        "수와 연산",
        code,
        "수 감각",
        "NCIC 성취기준 본문 문장 — 미수록 대상",
        "NCIC 요약 — 미수록 대상",
        "분류",
        "28",
        linked,
        "-",
        _EXPLANATION,
        "은유문",
        "오개념문",
        "정식정의문",
        "허용표현문",
        "자체작성",
        "1",
        "비고",
        "-",
    ]


def _make_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "개념"
    ws.append(_CONCEPT_HDR)
    ws.append(_concept_row("N1", linked="[2수01-01]"))
    ws.append(_concept_row("T2", school="중학교", linked="[2수03-08]; [2수03-09]; [4수03-13]"))
    ws.append(_concept_row("GALOIS-U1-S1", school="대학교"))  # 대학 — 비추출
    cards = wb.create_sheet("암기카드(목록화)")
    cards.append(_CARD_HDR)
    cards.append(["A", "수", "1", "N1", "수 감각", "앞", "뒤", "암기", "마스터 후"])
    cards.append(
        ["B", "함수", "25", "GALOIS-U1-S1", "분해체", "앞", "뒤", None, "마스터 후"]
    )  # 대학 카드 — 무시
    wb.save(str(path))


def _make_standards(path: Path, statement: str = "NCIC 성취기준 본문 문장") -> Path:
    """겹침 실측의 대조군 — 합성 xlsx의 `연결 성취기준` 코드와 맞춰 둔다."""
    path.write_text(
        json.dumps(
            {
                "standards": [
                    {"code": "[2수01-01]", "statement": statement},
                    {"code": "[2수03-08]", "statement": "다른 성취기준 본문"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_cli_builds_content_corpus(tmp_path: Path) -> None:
    xlsx = tmp_path / "m.xlsx"
    _make_xlsx(xlsx)
    std = _make_standards(tmp_path / "standards.json")
    out = tmp_path / "corpus"
    assert main(["--input", str(xlsx), "--output-dir", str(out), "--standards", str(std)]) == 0

    data = json.loads((out / "content.json").read_text(encoding="utf-8"))
    content = data["content"]
    # K-12 2건만(대학 GALOIS 필터)·개념ID 조인된 카드.
    assert data["scope"] == "K-12"
    assert len(content) == 2
    codes = {c["code"] for c in content}
    assert codes == {"N1", "T2"}
    n1 = next(c for c in content if c["code"] == "N1")
    assert len(n1["flashcards"]) == 1  # 개념ID로 카드 조인
    assert n1["formal_definition_internal"] == "정식정의문"
    # 연결 성취기준 → 코드만(';'·',' 분할).
    assert n1["standard_codes"] == ["[2수01-01]"]
    t2 = next(c for c in content if c["code"] == "T2")
    assert t2["standard_codes"] == ["[2수03-08]", "[2수03-09]", "[4수03-13]"]
    assert "자체" in data["source_citation"]
    # 대학 카드(GALOIS)는 섞이지 않았다.
    assert all(not c["code"].startswith("GALOIS") for c in content)


def test_cli_redacts_ncic_body(tmp_path: Path) -> None:
    xlsx = tmp_path / "m.xlsx"
    _make_xlsx(xlsx)
    std = _make_standards(tmp_path / "standards.json")
    out = tmp_path / "corpus"
    assert main(["--input", str(xlsx), "--output-dir", str(out), "--standards", str(std)]) == 0
    raw = (out / "content.json").read_text(encoding="utf-8")
    # NCIC 본문 키·본문 텍스트가 코퍼스에 일절 없어야 한다.
    for key in ("성취기준 문장", "성취기준 요약(간결)", "성취기준 요약", "핵심명제"):
        assert f'"{key}"' not in raw
    assert "NCIC 성취기준 본문 문장" not in raw
    assert "NCIC 요약" not in raw


def test_cli_missing_input(tmp_path: Path) -> None:
    assert main(["--input", str(tmp_path / "no.xlsx"), "--output-dir", str(tmp_path / "o")]) == 2


def test_cli_missing_standards_refuses_to_write(tmp_path: Path) -> None:
    """측정 없이 선언을 쓰지 않는다 — 성취기준 코퍼스가 없으면 exit 2, 산출물 0."""
    xlsx = tmp_path / "m.xlsx"
    _make_xlsx(xlsx)
    out = tmp_path / "corpus"
    code = main(
        ["--input", str(xlsx), "--output-dir", str(out), "--standards", str(tmp_path / "no.json")]
    )
    assert code == 2
    assert not (out / "content.json").exists(), "실측 없이 코퍼스를 썼다"


def test_cli_declaration_follows_the_data(tmp_path: Path) -> None:
    """같은 xlsx라도 성취기준 본문이 다르면 선언이 달라진다 — 하드코딩 회귀 방어.

    이것이 PR #998 리뷰가 지적한 축이다. 선언을 상수로 두면 아래 두 실행이 **같은 문장**을 낸다.
    """
    xlsx = tmp_path / "m.xlsx"
    _make_xlsx(xlsx)

    # ⓐ 합성 행의 `설명` 컬럼 값과 성취기준 본문이 글자 그대로 같은 경우 → 겹침이 잡힌다.
    same = tmp_path / "same"
    assert (
        main(
            [
                "--input",
                str(xlsx),
                "--output-dir",
                str(same),
                "--standards",
                str(_make_standards(tmp_path / "s_same.json", _EXPLANATION)),
            ]
        )
        == 0
    )
    # ⓑ 전혀 다른 본문 → 겹침 0.
    diff = tmp_path / "diff"
    assert (
        main(
            [
                "--input",
                str(xlsx),
                "--output-dir",
                str(diff),
                "--standards",
                str(_make_standards(tmp_path / "s_diff.json", "전혀 다른 성취기준")),
            ]
        )
        == 0
    )

    a = json.loads((same / "content.json").read_text(encoding="utf-8"))["license_notice"]
    b = json.loads((diff / "content.json").read_text(encoding="utf-8"))["license_notice"]
    assert a != b, "데이터가 달라도 선언이 같다 — 상수 하드코딩 회귀"
    assert "공공누리" in a and "공공누리" not in b

    sidecar = json.loads((same / "_provenance.json").read_text(encoding="utf-8"))
    assert sidecar["ncic_statement_overlap"]["count"] >= 1
    zero = json.loads((diff / "_provenance.json").read_text(encoding="utf-8"))
    assert zero["ncic_statement_overlap"]["count"] == 0


def test_cli_regeneration_preserves_existing_sidecar_keys(tmp_path: Path) -> None:
    """재생성이 `pool` 같은 기존 키를 지우지 않는다 — 통째 덮어쓰기 회귀 방어."""
    xlsx = tmp_path / "m.xlsx"
    _make_xlsx(xlsx)
    std = _make_standards(tmp_path / "standards.json")
    out = tmp_path / "corpus"
    assert main(["--input", str(xlsx), "--output-dir", str(out), "--standards", str(std)]) == 0

    sidecar = out / "_provenance.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["pool"] = "whymath-original"
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert main(["--input", str(xlsx), "--output-dir", str(out), "--standards", str(std)]) == 0
    again = json.loads(sidecar.read_text(encoding="utf-8"))
    assert again["pool"] == "whymath-original"
    assert "ncic_statement_overlap" in again
