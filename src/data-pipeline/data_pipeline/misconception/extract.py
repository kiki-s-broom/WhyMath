"""7계층 본문 JSON → 정규화 오개념 레코드(순수·openpyxl 불요).

각 개념의 `L5_META.오개념` 리스트를 평탄화해 한글 소스 키를 안정 영문 키로 매핑한다(데이터카드 §2).
`mis_id`는 유일 PK이므로 중복은 *마지막 우선*이 아니라 *첫 등장 우선*으로 dedup하고 누락/중복을
정직하게 셀 수 있도록 순수 함수로 둔다(조용한 누락 금지 — CLAUDE.md 신뢰 원칙).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger("data_pipeline.misconception.extract")


class MisconceptionRecord(TypedDict):
    """정규화 오개념 1건 — 한글 소스 키 → 안정 영문 키(데이터카드 §2).

    `mis_id`만 필수(PK). 나머지는 소스 채우율이 52~100%라 빈 값이면 None으로 둔다(자유텍스트 잔차
    방지). 개념·성취기준 해소(`concept_src_id`→concept.code·`standard_code`→norm_id)는 백엔드 로더
    책임이므로 여기서는 원천 코드를 *그대로 보존*한다(ncic concept_src_id 선례).
    """

    mis_id: str
    canonical_statement: str | None
    student_wrong_thinking: str | None
    distractor_rule: str | None
    error_type: str | None
    difficulty: str | None
    correction_point: str | None
    ccss_code: str | None
    concept_src_id: str | None
    standard_code: str | None
    school_level: str | None
    domain: str | None
    subunit: str | None
    mapping_confidence: str | None
    mapping_score: float | None
    provenance_note: str | None


# 한글 소스 키 → 영문 키 매핑(문자열 필드만 — mapping_score는 별도 수치 처리).
_STR_FIELDS: dict[str, str] = {
    "오개념": "canonical_statement",
    "학생의_잘못된_사고": "student_wrong_thinking",
    "distractor_규칙": "distractor_rule",
    "error_type": "error_type",
    "난이도": "difficulty",
    "교정포인트": "correction_point",
    "매칭_CCSS": "ccss_code",
    "개념ID": "concept_src_id",
    "성취기준코드": "standard_code",
    "학교급": "school_level",
    "2022_영역": "domain",
    "세부단원_개념": "subunit",
    "매핑신뢰도": "mapping_confidence",
    "생성·검수": "provenance_note",
}


# 원천 839행 전부에 값이 있는 공통 메타 열(MISC-61 ① 실측 2026-10-09) — 오개념의 내용을 나르는 키가
# 아니므로 *의도적으로* 매핑하지 않는다. 이 목록에 없는 미매핑 키에 값이 있으면 경고한다(아래).
_UNMAPPED_META_KEYS: frozenset[str] = frozenset(
    {"출처", "원본_영역", "성취기준요약", "매핑개념명_참조", "코드정밀도"}
)
# 위 둘 외에 추출기가 읽는 키 — 경고 대상 판정에서 "이미 읽는 키"로 센다.
_READ_KEYS: frozenset[str] = frozenset(_STR_FIELDS) | {"mis_id", "매핑점수"}


def _has_value(value: object) -> bool:
    """값이 있는가 — None·빈 문자열·공백·빈 리스트/매핑은 '없음'(0·False는 값)."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _clean_str(value: object) -> str | None:
    """문자열 정제 — 정제 후 빈 값이면 None(미존재로 취급)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_float(value: object) -> float | None:
    """수치 정제 — float 변환 실패/빈 값이면 None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load_json(path: str | Path) -> list[dict[str, Any]]:
    """7계층 본문 JSON 로드 — 최상위 개념 배열을 반환(형식 위반은 명확히 오류)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(
            f"7계층 JSON 최상위는 개념 배열이어야 합니다(got {type(payload).__name__})."
        )
    return payload


def extract_misconceptions(
    concepts: list[dict[str, Any]],
) -> tuple[list[MisconceptionRecord], int]:
    """개념 배열 → (정규화 오개념 레코드 목록, mis_id 중복 skip 수).

    각 개념의 `L5_META.오개념` 리스트를 평탄화한다. `mis_id` 없는 레코드는 건너뛰고(PK 결손),
    이미 본 `mis_id`는 *첫 등장 우선*으로 dedup하며 중복 수를 *정직하게* 집계해 반환한다.

    **값을 조용히 버리지 않는다(MISC-61)**: 읽는 키도, 의도적 비매핑 메타 열
    (`_UNMAPPED_META_KEYS`)도 아닌 키에 값이 있으면 그 *키 이름과 행 수*를 WARNING 한 줄로
    남긴다(값 본문은 남기지 않는다). 원천에 값이 있는 `오개념_원인` 키를 읽지 않아 `원본` 공란
    21행이 빈 칸이 됐을 가능성을 사후에야 원천 대조로 규명해야 했던 일(MISC-61)의 재발 방지 —
    반환값은 바뀌지 않는다. (`distractor 연결됨` 88행은 원천부터 비어 있어 이 경고와 무관하다.)
    """
    records: list[MisconceptionRecord] = []
    seen: set[str] = set()
    duplicates = 0
    dropped_keys: Counter[str] = Counter()
    for concept in concepts:
        meta = concept.get("L5_META") or {}
        rows = meta.get("오개념") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mis_id = _clean_str(row.get("mis_id"))
            if mis_id is None:
                continue  # PK 결손 — 카탈로그 레코드로 부적격(건너뜀).
            if mis_id in seen:
                duplicates += 1
                continue
            seen.add(mis_id)
            record: MisconceptionRecord = {
                "mis_id": mis_id,
                "canonical_statement": None,
                "student_wrong_thinking": None,
                "distractor_rule": None,
                "error_type": None,
                "difficulty": None,
                "correction_point": None,
                "ccss_code": None,
                "concept_src_id": None,
                "standard_code": None,
                "school_level": None,
                "domain": None,
                "subunit": None,
                "mapping_confidence": None,
                "mapping_score": _clean_float(row.get("매핑점수")),
                "provenance_note": None,
            }
            for src_key, dst_key in _STR_FIELDS.items():
                record[dst_key] = _clean_str(row.get(src_key))  # type: ignore[literal-required]
            for src_key, value in row.items():
                if src_key in _READ_KEYS or src_key in _UNMAPPED_META_KEYS:
                    continue
                if _has_value(value):
                    dropped_keys[str(src_key)] += 1
            records.append(record)
    if dropped_keys:
        summary = ", ".join(f"{key}={count}행" for key, count in sorted(dropped_keys.items()))
        logger.warning(
            "추출기가 읽지 않는 원천 키에 값이 있어 버렸다(%d종): %s — 키 매핑 확인 필요",
            len(dropped_keys),
            summary,
        )
    return records, duplicates
