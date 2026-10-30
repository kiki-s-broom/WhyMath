"""idmap 단위테스트 — src_id → canonical concept_id(`math.<area>.<slug>`) + 오버레이 별칭.

정본: docs/data/concept_graph.md §2.4(ID 규약)·§3.5(ID 안정성) +
docs/standards/part9_id_policy_review.md(P2d 재ID) + P2a/P2d 결정 로그(MEMORY.md).

P2d로 canonical(build_id_map)은 `math.<area>.<slug>`를 산출하고, 옛 `{TRACK}-{AREA}-{NNN}` NNN
번호매김은 오버레이 함수 `build_curriculum_axis_map`으로 보존됐다(별칭·matrix 개념축).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_pipeline.concept_graph.idmap import (
    _AREA_SLUG_MAP,
    _TOPIC_AREA_MAP,
    build_alias_map,
    build_curriculum_axis_map,
    build_id_map,
    build_legacy_uc_map,
    strip_level_prefix,
    to_csv_rows,
    track_for_record,
)
from data_pipeline.concept_graph.models import (
    CONCEPT_ID_PATTERN,
    CURRICULUM_AXIS_PATTERN,
    LEGACY_UC_PATTERN,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
# 고정 지점이 사실 파일 한 곳이다 — 값이 바뀌면 그 파일의 diff가 의식적 리뷰 지점이다.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# 코퍼스 37개 category 전수(접두사 포함 원본) — area_map_total 검증·합성 픽스처 공용.
_ALL_CATEGORIES: tuple[str, ...] = (
    "[고]경제 수학",
    "[고]기하",
    "[고]대수",
    "[고]미적분",
    "[고]수학과 문화",
    "[고]수학과제 탐구",
    "[고]실용 통계",
    "[고]인공지능 수학",
    "[고]직무 수학",
    "[고]확률·통계",
    "[공통]경우의 수",
    "[공통]도형의 방정식",
    "[공통]식·방정식·부등식",
    "[공통]집합과 명제",
    "[공통]함수",
    "[공통]행렬",
    "[중]기하",
    "[중]문자·식·방정식",
    "[중]수와 연산",
    "[중]자료와 가능성",
    "가능성",
    "곱셈",
    "규칙·대응",
    "나눗셈",
    "덧셈·뺄셈",
    "도형(평면·입체)",
    "도형의 요소",
    "둘레·넓이·부피",
    "분수",
    "비와 비율",
    "소수",
    "수의 성질·어림",
    "자료·그래프",
    "자연수·자릿값",
    "측정(단위)",
    "합동·대칭·이동",
)


def _rec(src_id: str, name_ko: str, category: str, **over: object) -> dict[str, object]:
    """합성 concepts 레코드(canonical build_id_map은 name_ko 필수)."""
    rec: dict[str, object] = {
        "src_id": src_id,
        "name_ko": name_ko,
        "category": category,
        "standard_codes": [],
    }
    rec.update(over)
    return rec


class TestStripLevelPrefix:
    @pytest.mark.parametrize(
        "category, expected",
        [
            ("[고]미적분", "미적분"),
            ("[중]기하", "기하"),
            ("[공통]함수", "함수"),
            ("분수", "분수"),  # 접두사 없음(초등)
            ("자연수·자릿값", "자연수·자릿값"),
        ],
    )
    def test_strips_known_prefixes(self, category: str, expected: str) -> None:
        assert strip_level_prefix(category) == expected


class TestTopicAreaMap:
    def test_every_category_maps(self) -> None:
        """37개 category 전수가 AREA로 매핑된다(어간 기준·미매핑 0)."""
        stems = {strip_level_prefix(c) for c in _ALL_CATEGORIES}
        unmapped = [s for s in stems if s not in _TOPIC_AREA_MAP]
        assert unmapped == []

    def test_all_area_codes_pass_token_shape(self) -> None:
        """모든 AREA 코드가 2~8 대문자/숫자(교육과정축 코드 AREA 슬롯 규약)."""
        import re

        token = re.compile(r"^[A-Z0-9]{2,8}$")
        bad = {area for area in _TOPIC_AREA_MAP.values() if not token.match(area)}
        assert bad == set()

    def test_kiki_specified_examples(self) -> None:
        """Kiki가 못박은 대표 매핑 고정(taxonomy 회귀 가드)."""
        assert _TOPIC_AREA_MAP["미적분"] == "CALC"
        assert _TOPIC_AREA_MAP["기하"] == "GEO"
        assert _TOPIC_AREA_MAP["분수"] == "FRAC"
        assert _TOPIC_AREA_MAP["확률·통계"] == "PROB"
        assert _TOPIC_AREA_MAP["함수"] == "FUN"
        assert _TOPIC_AREA_MAP["대수"] == "ALG"
        assert _TOPIC_AREA_MAP["식·방정식·부등식"] == "EQN"
        assert _TOPIC_AREA_MAP["도형의 방정식"] == "COORD"
        assert _TOPIC_AREA_MAP["집합과 명제"] == "LOGIC"
        assert _TOPIC_AREA_MAP["자연수·자릿값"] == "NPLACE"

    def test_shared_stem_shares_area(self) -> None:
        """레벨만 다른 어간([중]기하·[고]기하)은 같은 AREA(TRACK이 구분)."""
        assert strip_level_prefix("[중]기하") == strip_level_prefix("[고]기하")
        assert _TOPIC_AREA_MAP[strip_level_prefix("[중]기하")] == "GEO"


class TestAreaSlugMap:
    """canonical `<area>` 세그먼트 사상 — _TOPIC_AREA_MAP 값과 1:1·교육과정-독립 영역어."""

    def test_covers_every_topic_area(self) -> None:
        """_AREA_SLUG_MAP이 _TOPIC_AREA_MAP AREA 코드 전수를 커버(누락·잉여 0)."""
        assert set(_AREA_SLUG_MAP) == set(_TOPIC_AREA_MAP.values())

    def test_slugs_are_lowercase_hyphen_tokens(self) -> None:
        """영역어는 소문자로 시작하는 [a-z0-9-] 토큰(canonical area 규약)."""
        import re

        token = re.compile(r"^[a-z][a-z0-9-]*$")
        bad = {v for v in _AREA_SLUG_MAP.values() if not token.match(v)}
        assert bad == set()

    def test_representative_mappings(self) -> None:
        """대표 영역어 고정(GEO→geometry·CALC→calculus·NPLACE→place-value)."""
        assert _AREA_SLUG_MAP["GEO"] == "geometry"
        assert _AREA_SLUG_MAP["CALC"] == "calculus"
        assert _AREA_SLUG_MAP["NPLACE"] == "place-value"


class TestTrackDerivation:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("[2수01-01]", "ELEM"),
            ("[4수03-20]", "ELEM"),
            ("[6수01-06]", "ELEM"),
            ("[9수01-01]", "MID"),
            ("[10공수1-01-01]", "HIGH"),
            ("[12미적Ⅰ01-01]", "HIGH"),
        ],
    )
    def test_track_from_first_standard_code(self, code: str, expected: str) -> None:
        """첫 standard_code 학년대수 → TRACK(2/4/6=ELEM·9=MID·10/12=HIGH)."""
        assert track_for_record([code], None) == expected

    def test_track_uses_first_parseable_code(self) -> None:
        """파싱 불가 코드는 건너뛰고 첫 파싱 성공 코드로 결정."""
        assert track_for_record(["bad", "[9수01-01]"], None) == "MID"

    def test_track_tier_fallback_when_no_codes(self) -> None:
        """standard_codes 없으면 difficulty_tier 밴드 폴백(0~8 ELEM·9~16 MID·17~24 HIGH)."""
        assert track_for_record([], 3) == "ELEM"
        assert track_for_record([], 12) == "MID"
        assert track_for_record([], 20) == "HIGH"

    def test_track_last_resort_when_no_codes_no_tier(self) -> None:
        """코드도 tier도 없으면 최종 폴백 MID(중립)."""
        assert track_for_record([], None) == "MID"


class TestBuildIdMap:
    """canonical build_id_map — `math.<area>.<slug>` 결정론·충돌 접미·규약·override."""

    def test_real_data_all_unique(self, concept_records: list[dict[str, object]]) -> None:
        """실데이터 전 개념 → 전량 유일 canonical ID(충돌 0)."""
        id_map = build_id_map(concept_records)
        assert len(id_map) == _FACTS["concept_graph.concepts"]
        assert len(set(id_map.values())) == _FACTS["concept_graph.concepts"]  # 충돌 0

    def test_real_data_all_pass_pattern(self, concept_records: list[dict[str, object]]) -> None:
        """모든 생성 ID가 CONCEPT_ID_PATTERN(`math.<area>.<slug>`) 통과."""
        id_map = build_id_map(concept_records)
        bad = [cid for cid in id_map.values() if not CONCEPT_ID_PATTERN.match(cid)]
        assert bad == []

    def test_deterministic_across_runs(self, concept_records: list[dict[str, object]]) -> None:
        """두 번 빌드해도 동일 매핑(멱등)."""
        assert build_id_map(concept_records) == build_id_map(concept_records)

    def test_area_and_slug_composed(self) -> None:
        """canonical = math.<area 영역어>.<name_ko 로마자화>."""
        records = [_rec("F1", "분수", "분수", standard_codes=["[6수01-01]"])]
        id_map = build_id_map(records)
        assert id_map["F1"] == "math.fraction.bunsu"

    def test_collision_suffix_deterministic(self) -> None:
        """같은 (area, slug) 충돌 → 첫 항목 무접미·이후 -2(그룹 내 (tier, src_id) 정렬)."""
        records = [
            _rec("B", "분수", "분수", difficulty_tier="5", standard_codes=["[6수01-02]"]),
            _rec("A", "분수", "분수", difficulty_tier="3", standard_codes=["[6수01-01]"]),
        ]
        id_map = build_id_map(records)
        # tier 3(A) 먼저 → 무접미, tier 5(B) → -2
        assert id_map["A"] == "math.fraction.bunsu"
        assert id_map["B"] == "math.fraction.bunsu-2"
        # 입력 순서를 바꿔도 동일(정렬 키가 tier·src_id라 멱등)
        assert build_id_map(list(reversed(records))) == id_map

    def test_distinct_names_no_suffix(self) -> None:
        """다른 name_ko는 다른 slug라 접미 없음(충돌 아님)."""
        records = [
            _rec("F1", "분수", "분수", standard_codes=["[6수01-01]"]),
            _rec("F2", "자연수", "분수", standard_codes=["[6수01-02]"]),
        ]
        id_map = build_id_map(records)
        assert id_map["F1"] == "math.fraction.bunsu"
        assert id_map["F2"] == "math.fraction.jayeonsu"

    def test_shared_area_shares_area_segment(self) -> None:
        """같은 AREA(기하→geometry)면 학년 달라도 area 세그먼트를 공유(교육과정-독립)."""
        records = [
            _rec("MG", "기하 변환", "[중]기하", standard_codes=["[9수04-01]"]),
            _rec("HG", "공간 기하", "[고]기하", standard_codes=["[12기하01-01]"]),
        ]
        id_map = build_id_map(records)
        assert id_map["MG"].startswith("math.geometry.")
        assert id_map["HG"].startswith("math.geometry.")
        assert id_map["MG"] != id_map["HG"]  # slug가 다름

    def test_unmapped_category_raises_keyerror(self) -> None:
        """미수록 category는 침묵 폴백 없이 KeyError(taxonomy 누수 가드)."""
        records = [_rec("Z1", "외계", "외계수학", standard_codes=["[6수01-01]"])]
        with pytest.raises(KeyError):
            build_id_map(records)

    def test_undecodable_name_raises_valueerror(self) -> None:
        """romanize 불가 name_ko(한자·기호만)는 ValueError(loud fail — slug 원천 확인 유도)."""
        records = [_rec("H1", "漢字", "분수", standard_codes=["[6수01-01]"])]
        with pytest.raises(ValueError):
            build_id_map(records)

    def test_override_applied(self) -> None:
        """override 주입 시 그 src_id는 자동 발급 대신 override canonical_id."""
        records = [_rec("N1", "수 개념", "자연수·자릿값", standard_codes=["[2수01-01]"])]
        id_map = build_id_map(records, overrides={"N1": "math.place-value.custom"})
        assert id_map["N1"] == "math.place-value.custom"

    def test_override_must_pass_pattern(self) -> None:
        """override가 canonical 규약 위반이면 ValueError(옛 UC·축코드 거부)."""
        records = [_rec("N1", "분수", "분수", standard_codes=["[6수01-01]"])]
        with pytest.raises(ValueError):
            build_id_map(records, overrides={"N1": "UC.calc.limit.def"})
        with pytest.raises(ValueError):
            build_id_map(records, overrides={"N1": "ELEM-FRAC-001"})  # 축코드는 canonical 아님

    def test_override_collision_rejected(self) -> None:
        """서로 다른 src_id를 같은 override ID로 매핑하면 ValueError."""
        records = [
            _rec("N1", "분수", "분수", standard_codes=["[6수01-01]"]),
            _rec("N2", "자연수", "분수", standard_codes=["[6수01-02]"]),
        ]
        with pytest.raises(ValueError):
            build_id_map(
                records,
                overrides={"N1": "math.fraction.x", "N2": "math.fraction.x"},
            )

    def test_duplicate_src_id_rejected(self) -> None:
        """src_id 중복은 ValueError."""
        records = [
            _rec("N1", "분수", "분수", standard_codes=["[6수01-01]"]),
            _rec("N1", "자연수", "분수", standard_codes=["[6수01-02]"]),
        ]
        with pytest.raises(ValueError):
            build_id_map(records)

    def test_empty_src_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_id_map([_rec("", "분수", "분수")])

    def test_preserves_insertion_order(self) -> None:
        records = [
            _rec("N3", "삼", "분수", standard_codes=["[6수01-03]"]),
            _rec("N1", "일", "분수", standard_codes=["[6수01-01]"]),
        ]
        assert list(build_id_map(records).keys()) == ["N3", "N1"]


class TestBuildCurriculumAxisMap:
    """오버레이 build_curriculum_axis_map — 옛 `{TRACK}-{AREA}-{NNN}`(별칭·matrix 개념축)."""

    def test_all_pass_axis_pattern(self) -> None:
        records = [_rec("F1", "분수", "분수", standard_codes=["[6수01-01]"])]
        axis = build_curriculum_axis_map(records)
        assert CURRICULUM_AXIS_PATTERN.match(axis["F1"])

    def test_nnn_idempotent_and_sorted(self) -> None:
        """(TRACK, AREA) 그룹 안 (tier, src_id) 정렬 → 001·002… 결정론적."""
        records = [
            _rec("B", "b", "분수", difficulty_tier="5", standard_codes=["[6수01-01]"]),
            _rec("A", "a", "분수", difficulty_tier="5", standard_codes=["[6수01-02]"]),
            _rec("C", "c", "분수", difficulty_tier="3", standard_codes=["[6수01-03]"]),
        ]
        axis = build_curriculum_axis_map(records)
        # tier 3(C) 먼저 → 001, tier 5는 src_id 사전순(A<B) → A=002·B=003
        assert axis["C"] == "ELEM-FRAC-001"
        assert axis["A"] == "ELEM-FRAC-002"
        assert axis["B"] == "ELEM-FRAC-003"
        assert build_curriculum_axis_map(list(reversed(records))) == axis

    def test_separate_groups_restart_numbering(self) -> None:
        """(TRACK, AREA)가 다르면 NNN이 각자 001부터."""
        records = [
            _rec("F1", "분수", "분수", difficulty_tier="2", standard_codes=["[6수01-01]"]),
            _rec(
                "G1",
                "기하",
                "[중]기하",
                difficulty_tier="10",
                standard_codes=["[9수04-01]"],
            ),
        ]
        axis = build_curriculum_axis_map(records)
        assert axis["F1"] == "ELEM-FRAC-001"
        assert axis["G1"] == "MID-GEO-001"

    def test_track_disambiguates_shared_area(self) -> None:
        """같은 AREA(기하→GEO)라도 TRACK이 다르면 축코드가 충돌하지 않는다."""
        records = [
            _rec(
                "MG",
                "중기하",
                "[중]기하",
                difficulty_tier="10",
                standard_codes=["[9수04-01]"],
            ),
            _rec(
                "HG",
                "고기하",
                "[고]기하",
                difficulty_tier="20",
                standard_codes=["[12기하01-01]"],
            ),
        ]
        axis = build_curriculum_axis_map(records)
        assert axis["MG"] == "MID-GEO-001"
        assert axis["HG"] == "HIGH-GEO-001"

    def test_tier_fallback_for_codeless_record(self) -> None:
        """standard_codes 없으면 tier 밴드로 TRACK 결정(폴백 경로)."""
        records = [_rec("X1", "무코드", "분수", difficulty_tier="20", standard_codes=[])]
        axis = build_curriculum_axis_map(records)
        assert axis["X1"] == "HIGH-FRAC-001"

    def test_override_must_pass_axis_pattern(self) -> None:
        """override는 CURRICULUM_AXIS_PATTERN을 지켜야 함(canonical 형식 거부)."""
        records = [_rec("N1", "분수", "분수", standard_codes=["[6수01-01]"])]
        with pytest.raises(ValueError):
            build_curriculum_axis_map(records, overrides={"N1": "math.fraction.x"})


class TestBuildAliasMap:
    def test_aliases_contain_axis_uc_and_src_id(self) -> None:
        """별칭 = [교육과정축 코드, 옛 UC, src_id](순서 고정)."""
        records = [
            _rec(
                "HK01",
                "다항식의 사칙연산",
                "[공통]식·방정식·부등식",
                standard_codes=["[10공수1-01-01]"],
            )
        ]
        alias_map = build_alias_map(records)
        aliases = alias_map["HK01"]
        assert aliases == ["HIGH-EQN-001", "UC.common1.a01.hk01", "HK01"]
        assert CURRICULUM_AXIS_PATTERN.match(aliases[0])
        assert LEGACY_UC_PATTERN.match(aliases[1])
        assert aliases[2] == "HK01"

    def test_legacy_fallback_uc_for_codeless(self) -> None:
        """standard_codes 없으면 옛 폴백 UC(UC.x.misc.<slug>) 보존·축코드 tier 폴백."""
        records = [_rec("Z9", "무코드분수", "분수", standard_codes=[])]
        alias_map = build_alias_map(records)
        assert alias_map["Z9"] == ["MID-FRAC-001", "UC.x.misc.z9", "Z9"]

    def test_real_data_every_concept_has_full_aliases(
        self, concept_records: list[dict[str, object]]
    ) -> None:
        """실데이터 전건 모두 별칭에 교육과정축 코드·옛 UC·src_id 보존."""
        alias_map = build_alias_map(concept_records)
        assert len(alias_map) == _FACTS["concept_graph.concepts"]
        for src_id, aliases in alias_map.items():
            assert src_id in aliases
            assert any(CURRICULUM_AXIS_PATTERN.match(a) for a in aliases)
            assert any(LEGACY_UC_PATTERN.match(a) for a in aliases)


class TestBuildLegacyUcMap:
    def test_uc_map_matches_pattern(self) -> None:
        records = [
            _rec(
                "HK01",
                "다항식",
                "[공통]식·방정식·부등식",
                standard_codes=["[10공수1-01-01]"],
            )
        ]
        uc_map = build_legacy_uc_map(records)
        assert uc_map["HK01"] == "UC.common1.a01.hk01"
        assert LEGACY_UC_PATTERN.match(uc_map["HK01"])


class TestToCsvRows:
    def test_csv_rows_shape(self) -> None:
        rows = to_csv_rows(
            {"N1": "math.place-value.su-gaenyeom", "N2": "math.place-value.jaritgap"}
        )
        assert rows == [
            {"src_id": "N1", "concept_id": "math.place-value.su-gaenyeom"},
            {"src_id": "N2", "concept_id": "math.place-value.jaritgap"},
        ]
