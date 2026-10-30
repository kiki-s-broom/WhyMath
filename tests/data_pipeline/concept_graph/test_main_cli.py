"""concept_graph CLI 단위테스트 — seed · validate · load(가드). 라이브 인프라 불요."""

from __future__ import annotations

import csv
import json
import shutil
from importlib.util import find_spec
from pathlib import Path

import pytest
import yaml
from data_pipeline.concept_graph.__main__ import app
from data_pipeline.concept_graph.seed import build_concept_id
from data_pipeline.ncic.load import write_json
from data_pipeline.ncic.models import AchievementStandard
from typer.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

runner = CliRunner()


def _standards_json(tmp_path: Path) -> Path:
    stds = [
        AchievementStandard(
            norm_id="2022_12미적I_01_01",
            code="[12미적Ⅰ01-01]",
            grade_band="고등학교",
            school_type="고등학교",
            subject="미적분Ⅰ",
            domain="함수의 극한",
            statement="극한의 뜻을 안다.",
            source_url="https://www.ncic.go.kr/a",
        ),
        AchievementStandard(
            norm_id="2022_12미적I_01_02",
            code="[12미적Ⅰ01-02]",
            grade_band="고등학교",
            school_type="고등학교",
            subject="미적분Ⅰ",
            domain="함수의 극한",
            statement="극한값을 계산한다.",
            source_url="https://www.ncic.go.kr/b",
            parent_codes=["[12미적Ⅰ01-01]"],
        ),
    ]
    out = tmp_path / "standards.json"
    write_json(stds, out)
    return out


def _write_filled_concepts(path: Path, ids: list[str]) -> None:
    """전문가가 채운 concepts.csv 모사(검증 통과용). source_id=concept_id(신규 후보).

    표시이름(name_ko/en/ja)은 노드 비내장(P2d)이라 CSV 컬럼이 없다(locale 레이어 소관).
    """
    fields = [
        "concept_id",
        "source_id",
        "aliases",
        "domain",
        "grade_band_hint",
        "prerequisite_concept_ids",
        "misconception_codes",
        "visualization_card_keys",
        "standard_codes",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for cid in ids:
            w.writerow(
                {
                    "concept_id": cid,
                    "source_id": cid,  # 신규 후보 = 자기 정체
                    "aliases": "",
                    "domain": "미적분",
                    "grade_band_hint": "고등학교",
                    "prerequisite_concept_ids": "",
                    "misconception_codes": "",
                    "visualization_card_keys": "",
                    "standard_codes": "",
                    "notes": "",
                }
            )


def _write_filled_edges(path: Path, pairs: list[tuple[str, str]]) -> None:
    fields = [
        "src_concept_id",
        "dst_concept_id",
        "relation",
        "strength",
        "evidence",
        "evidence_source",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for src, dst in pairs:
            w.writerow(
                {
                    "src_concept_id": src,
                    "dst_concept_id": dst,
                    "relation": "prerequisite",
                    "strength": "0.9",
                    "evidence": "NCIC 인접",
                    "evidence_source": "ncic",
                }
            )


class TestHelp:
    def test_help_lists_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        out = result.stdout.lower()
        assert "seed" in out
        assert "validate" in out
        assert "load" in out
        assert "transform-v1" in out


class TestTransformV1:
    def test_validates_real_corpus(self, corpus_dir: Path) -> None:
        """실데이터 transform-v1(검증만) → PASS 종료코드 0."""
        result = runner.invoke(app, ["transform-v1", "--corpus-dir", str(corpus_dir)])
        assert result.exit_code == 0, result.output
        assert "개념 437개" in result.stdout
        assert "엣지 581개" in result.stdout
        assert "PASS" in result.stdout

    def test_writes_outputs(self, corpus_dir: Path, tmp_path: Path) -> None:
        """--output-dir 주면 graph.json·id_map.csv·ids.yaml·locales 저장 + redaction 유지."""
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            ["transform-v1", "--corpus-dir", str(corpus_dir), "--output-dir", str(out)],
        )
        assert result.exit_code == 0, result.output
        graph = out / "graph.json"
        idmap = out / "id_map.csv"
        assert graph.exists()
        assert idmap.exists()
        # P2d co-generate: registry(ids.yaml)·locale(ko/en/ja) 동반 산출
        assert (out / "ids.yaml").exists()
        assert (out / "locales" / "ko.json").exists()
        assert (out / "locales" / "en.json").exists()
        text = graph.read_text(encoding="utf-8")
        # redaction: 산출 JSON에 본문 *키* 없음(참조 키 `formal_definition_ref`는 본문 아님·허용).
        assert '"description"' not in text
        assert '"formal_definition"' not in text  # 본문 키(따옴표 종결) — `_ref`와 구분
        # 표시이름은 노드 비내장 → 어떤 concept 노드에도 name_* 키가 없다(raw 패스스루는 별개).
        payload = json.loads(text)
        for concept in payload["concepts"]:
            assert "name_ko" not in concept
            assert "name_en" not in concept
            assert "name_ja" not in concept
        with idmap.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert (
            len(rows) == _FACTS["concept_graph.concepts"]
        )  # src_id → concept_id 매핑(공통 403 + 기본수학 34)
        ko = json.loads((out / "locales" / "ko.json").read_text(encoding="utf-8"))
        assert len(ko) == _FACTS["concept_graph.concepts"]  # 표시이름은 locale(ko)로 분리

    def test_missing_corpus_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["transform-v1", "--corpus-dir", str(tmp_path / "nope")])
        assert result.exit_code == 2

    def test_missing_concepts_file_exits_2(self, tmp_path: Path) -> None:
        """디렉토리는 있으나 concepts.jsonl 없음 → 종료코드 2."""
        (tmp_path / "empty").mkdir()
        result = runner.invoke(app, ["transform-v1", "--corpus-dir", str(tmp_path / "empty")])
        assert result.exit_code == 2


class TestGenIds:
    def _corpus_copy(self, corpus_dir: Path, tmp_path: Path) -> Path:
        """실 코퍼스를 tmp로 복제(원본 불변) + graph.json을 canonical로 재생성."""
        dst = tmp_path / "corpus"
        dst.mkdir()
        for name in (
            "concepts.jsonl",
            "prerequisite_edges.jsonl",
            "flashcards.jsonl",
            "ccss_only_intl.jsonl",
        ):
            src = corpus_dir / name
            if src.exists():
                shutil.copy(src, dst / name)
        # 커밋된 canonical graph.json을 tmp에 생성(transform-v1로).
        assert (
            runner.invoke(
                app,
                ["transform-v1", "--corpus-dir", str(dst), "--output-dir", str(dst)],
            ).exit_code
            == 0
        )
        return dst

    def test_gen_ids_regenerates_and_validates(self, corpus_dir: Path, tmp_path: Path) -> None:
        """gen-ids가 ids.yaml·locale을 재생성하고 graph.json에 대해 검증 통과(종료코드 0)."""
        dst = self._corpus_copy(corpus_dir, tmp_path)
        (dst / "ids.yaml").unlink()  # 재생성 대상 삭제 후 gen-ids로 복원
        result = runner.invoke(app, ["gen-ids", "--corpus-dir", str(dst)])
        assert result.exit_code == 0, result.output
        assert (dst / "ids.yaml").exists()
        registry = yaml.safe_load((dst / "ids.yaml").read_text(encoding="utf-8"))
        assert registry["version"] == 1
        assert len(registry["concepts"]) == _FACTS["concept_graph.concepts"]
        ko = json.loads((dst / "locales" / "ko.json").read_text(encoding="utf-8"))
        assert len(ko) == _FACTS["concept_graph.concepts"]

    def test_gen_ids_missing_graph_exits_2(self, corpus_dir: Path, tmp_path: Path) -> None:
        """graph.json 없으면 종료코드 2(검증 대상 부재)."""
        dst = tmp_path / "nograph"
        dst.mkdir()
        shutil.copy(corpus_dir / "concepts.jsonl", dst / "concepts.jsonl")
        result = runner.invoke(app, ["gen-ids", "--corpus-dir", str(dst)])
        assert result.exit_code == 2


class TestSeed:
    def test_seed_writes_csvs(self, tmp_path: Path) -> None:
        ncic = _standards_json(tmp_path)
        out_dir = tmp_path / "seed"
        result = runner.invoke(
            app,
            [
                "seed",
                "--ncic",
                str(ncic),
                "--domain-filter",
                "미적분",
                "--output-dir",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "concepts.csv").exists()
        assert (out_dir / "edges.csv").exists()
        with (out_dir / "concepts.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2  # 미적분Ⅰ 2건
        with (out_dir / "edges.csv").open(encoding="utf-8-sig") as f:
            edges = list(csv.DictReader(f))
        assert len(edges) == 1  # parent_codes 1건 → prerequisite 엣지 1

    def test_seed_missing_input_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["seed", "--ncic", str(tmp_path / "nope.json")])
        assert result.exit_code == 2


class TestValidate:
    def test_validate_filled_graph_succeeds(self, tmp_path: Path) -> None:
        a, b = build_concept_id("[12미적Ⅰ01-01]"), build_concept_id("[12미적Ⅰ01-02]")
        cpath, epath = tmp_path / "c.csv", tmp_path / "e.csv"
        _write_filled_concepts(cpath, [a, b])
        _write_filled_edges(epath, [(a, b)])
        result = runner.invoke(app, ["validate", "--concepts", str(cpath), "--edges", str(epath)])
        assert result.exit_code == 0, result.output
        assert "그래프 검증" in result.stdout

    def test_validate_unfilled_seed_reports_parse_errors(self, tmp_path: Path) -> None:
        """빈칸(strength·evidence) seed 엣지 CSV는 파싱 실패 → 종료코드 1."""
        ncic = _standards_json(tmp_path)
        out_dir = tmp_path / "seed"
        runner.invoke(
            app,
            [
                "seed",
                "--ncic",
                str(ncic),
                "--domain-filter",
                "미적분",
                "--output-dir",
                str(out_dir),
            ],
        )
        result = runner.invoke(
            app,
            [
                "validate",
                "--concepts",
                str(out_dir / "concepts.csv"),
                "--edges",
                str(out_dir / "edges.csv"),
            ],
        )
        assert result.exit_code == 1
        assert "파싱 실패" in result.stdout

    def test_validate_detects_cycle_exits_1(self, tmp_path: Path) -> None:
        a, b = "math.calculus.aa", "math.calculus.bb"
        cpath, epath = tmp_path / "c.csv", tmp_path / "e.csv"
        _write_filled_concepts(cpath, [a, b])
        _write_filled_edges(epath, [(a, b), (b, a)])  # 순환
        result = runner.invoke(app, ["validate", "--concepts", str(cpath), "--edges", str(epath)])
        assert result.exit_code == 1
        assert "prerequisite_cycle" in result.stdout

    def test_validate_missing_csv_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "validate",
                "--concepts",
                str(tmp_path / "x.csv"),
                "--edges",
                str(tmp_path / "y.csv"),
            ],
        )
        assert result.exit_code == 2


class TestLoad:
    """load 명령 — graph.json → Neo4j 멱등 적재. CI(neo4j 미설치)는 드라이버 사전체크에서 안내.

    실 적재 왕복은 test_load_neo4j_integration.py(통합·기본 SKIP)가 검증한다. 여기서는 드라이버
    부재·입력 누락 등 *CLI 표면*만 확인한다(라이브 Neo4j 불요).
    """

    def _graph_json(self, tmp_path: Path) -> Path:
        """transform-v1 산출과 동형의 최소 graph.json(개념 1·엣지 0)."""
        out = tmp_path / "graph.json"
        out.write_text(
            json.dumps(
                {
                    "source_citation": "x",
                    "concepts": [
                        {
                            "concept_id": "math.calculus.geukhan",
                            "source_id": "H:12미적Ⅰ01-01",
                            "aliases": [
                                "HIGH-CALC-001",
                                "UC.calc1.a01.h-12-01-01",
                                "H:12미적Ⅰ01-01",
                            ],
                            "domain": "미적분",
                            "review_status": "reviewed",
                        }
                    ],
                    "edges": [],
                    "flashcards_raw": [],
                    "intl_raw": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return out

    @pytest.mark.skipif(
        find_spec("neo4j") is not None,
        reason="neo4j 드라이버가 설치돼 사전체크 안내 경로가 아님(통합테스트가 적재 검증)",
    )
    def test_load_without_driver_guides_install(self, tmp_path: Path) -> None:
        """neo4j 미설치 → 드라이버 사전체크에서 extra 설치 안내·종료코드 3."""
        graph = self._graph_json(tmp_path)
        result = runner.invoke(app, ["load", "--graph", str(graph)])
        assert result.exit_code == 3
        assert "[neo4j]" in result.output

    def test_load_requires_graph_option(self) -> None:
        """--graph 미지정 → typer 필수 옵션 오류(종료코드 2)."""
        result = runner.invoke(app, ["load"])
        assert result.exit_code == 2
