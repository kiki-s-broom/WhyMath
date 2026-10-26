"""②진단문항·③소크라테스 PG 프로젝션 적재 — `atom_probe` code 키 멱등 upsert (Phase 3 Slice 3).

`l1/concept_content/projection.py`(콘텐츠 4종 code 키 프로젝션 적재)의 *교수학 탐침* 짝이며, 소스
읽기는 `l1/misconception/atom_catalog.py`(atom 백본 graph.json 투영) 방식을 따른다. 원자 백본 코퍼스
(`data/corpus/atom_graph_v1/graph.json`)의 세부개념 원자가 보유한 **②진단문항**(`diagnostic_item`·
`diagnostic_answer`·`diagnostic_signal`)과 **③소크라테스 질문**(`socratic`)을 `atom_probe`(PG)에
멱등 upsert한다 — 학습 장면(L2 진단·L4 소크라테스 코칭·L6)이 PG 조인으로 탐침을 끌어쓰기 위한 *적재*
좌석(조회·조인은 후속).

`atom_node_projection.py`(메타 프로젝션)는 ①②③ 4요소 *본문을 의도적으로 미적재*했다(Phase 3 승격
대상 명시). Slice 2(`atom_catalog.py`)가 ①오개념을, 이 모듈이 ②진단문항·③소크라테스를 승격한다 —
②③는 같은 원자 행·code 1:1이라 한 테이블 `atom_probe`에 묶는다(concept_content가 4종을 묶은 선례).

매핑(원천 보유 필드만·날조 0):
  - `code`·`name`·`school_level`·`subject_area`·`subunit` = 원자 안전 메타 그대로
  - `diagnostic_item`·`diagnostic_answer`·`diagnostic_signal` = ②진단문항 3필드(자체/AI 작성)
  - `socratic_question` ← `socratic`(③소크라테스 질문·키 rename만)
  - `intrinsic_difficulty` = 난이도 1~5(정수)
  - `standard_codes` = 연결 성취기준 *코드* 목록(본문 아님·redaction-safe)
  - `review_status` = 슬롯 없음 — 적재기가 상수 'ai_estimated'로 박는다(AI 추정·정직 표기)

────────────────────────────────────────────────────────────────────────────
법적·노출 (CLAUDE.md 우선순위 #2)
────────────────────────────────────────────────────────────────────────────
②진단문항·③소크라테스는 전량 자체/AI 작성이라 보유 허용이다. NCIC 성취기준 *본문*은 코퍼스에 *없고*
(연결 `standard_codes` 코드만 다리), 적재기도 코드만 읽는다. `AtomProbeRecord`에 성취기준 본문
슬롯을 두지 않아 구조적으로 차단한다(concept_content·atom_node 동형).

sync 엔진은 슬3 `_build_sync_engine`을 *그대로 재사용*한다(신규 seam 0·concept_content 동형·sync
URL은 `Settings.sync_database_url` env 파생·자격증명 하드코딩 0).

7계층: L1 데이터 기반의 *영속 프로젝션 적재*. 탐침 조회·소비(L2/L4/L6)는 후속(역방향 의존 금지).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.atom_probe import ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — concept_content/atom_node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# atom 판별 level 값(세부개념 = 원자) — 단원·소단원은 ②③ 탐침 미보유.
_ATOM_LEVEL = "세부개념"


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(atom_catalog `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: object) -> int | None:
    """정수 옵션 파싱 — None·빈 문자열·비정수 → None, 그 외 int(난이도 1~5)."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool은 int 하위형이라 명시 제외(난이도 아님).
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class AtomProbeRecord:
    """프로젝션 대상 한 원자(세부개념)의 ②진단문항 3필드 + ③소크라테스 질문 + 메타.

    `graph.json`의 한 concept 항목(level=='세부개념')에서 탐침 키만 추린 값이다. **성취기준 *본문*
    슬롯은 없다**(코퍼스에 본문 부재·standard_codes 코드만·구조적 차단). 적재기가 code 키로 upsert
    한다. `review_status`는 슬롯이 없다 — 적재기가 상수로 박는다(AI 추정).
    """

    code: str
    name: str
    school_level: str | None
    subject_area: str | None
    subunit: str | None
    diagnostic_item: str | None
    diagnostic_answer: str | None
    diagnostic_signal: str | None
    socratic_question: str | None
    intrinsic_difficulty: int | None
    standard_codes: tuple[str, ...]


def load_atom_probes_from_json(path: Path) -> list[AtomProbeRecord]:
    """atom 백본 `graph.json` → ②진단문항·③소크라테스 레코드 목록(원자 code 키 투영).

    `concepts` 배열에서 **원자(level=='세부개념')**만 골라 `AtomProbeRecord`로 투영한다 — 단원·
    소단원(②③ 미보유)·code/name 없는 항목·②③가 *전부 빈 값*인 항목은 *건너뛴다*(조용한 빈 적재 X).
    `socratic`은 `socratic_question`으로 rename하고, 성취기준 본문 슬롯은 두지 않는다(구조 차단).
    `standard_codes`는 리스트가 아니면 빈 튜플로 둔다. 정상 코퍼스 기대 = 원자 전건
    (`docs/data/corpus_facts.md`의 `atom_graph.atoms` — ②③가 전부 빈 원자는 빠진다).

    빈/누락 `concepts`는 빈 목록을 낸다(graceful).

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[AtomProbeRecord] = []
    for record in payload.get("concepts", []):
        if _opt_str(record.get("level")) != _ATOM_LEVEL:
            continue  # 단원·소단원은 ②③ 탐침 없음 — 원자만 승격.
        code = _opt_str(record.get("code"))
        name = _opt_str(record.get("name"))
        if code is None or name is None:
            # 필수 식별·표시 필드 누락(오염 입력) — NOT NULL 위반 대신 건너뛴다(정직).
            # 정상 코퍼스는 code·name을 항상 보유하므로 실제 경로에선 발생하지 않는다.
            continue

        diagnostic_item = _opt_str(record.get("diagnostic_item"))
        diagnostic_answer = _opt_str(record.get("diagnostic_answer"))
        diagnostic_signal = _opt_str(record.get("diagnostic_signal"))
        socratic_question = _opt_str(record.get("socratic"))
        if (
            diagnostic_item is None
            and diagnostic_answer is None
            and diagnostic_signal is None
            and socratic_question is None
        ):
            continue  # ②③ 전부 빈 값 — 적재할 탐침 없음(의미 없는 행 방지·정직).

        raw_codes = record.get("standard_codes")
        codes: tuple[str, ...] = (
            tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        )
        out.append(
            AtomProbeRecord(
                code=code,
                name=name,
                school_level=_opt_str(record.get("school_level")),
                subject_area=_opt_str(record.get("subject_area")),
                subunit=_opt_str(record.get("subunit")),
                diagnostic_item=diagnostic_item,
                diagnostic_answer=diagnostic_answer,
                diagnostic_signal=diagnostic_signal,
                socratic_question=socratic_question,
                intrinsic_difficulty=_opt_int(record.get("intrinsic_difficulty")),
                standard_codes=codes,
            )
        )
    return out


class AtomProbeStore:
    """②진단문항·③소크라테스 PG 프로젝션 적재기 — `atom_probe` 테이블 code 키 멱등 upsert(sync).

    `ConceptContentStore`(콘텐츠 4종 프로젝션)의 *교수학 탐침* 짝이다. `upsert`는 PK 충돌 upsert
    (`INSERT ... ON CONFLICT(code) DO UPDATE`)로 멱등 적재한다(같은 code 재적재 → 행 갱신·
    updated_at 갱신). `review_status`는 상수 'ai_estimated'로 박는다(탐침은 AI 추정·정직 표기).
    sync 엔진은 슬3 `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0). 벡터 컬럼이
    없어 검색 메서드는 두지 않는다 — *적재 전용* 좌석이다(조회·조인은 후속).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(concept_content 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, record: AtomProbeRecord) -> None:
        """단일 탐침 레코드 upsert (멱등·code PK 충돌 갱신).

        `INSERT ... ON CONFLICT(code) DO UPDATE` — ②진단문항 3필드·③소크라테스·난이도·standard_codes
        + review_status('ai_estimated' 상수) + updated_at(now())을 갱신한다. 성취기준 *본문* 컬럼은
        없다(코퍼스 부재·레코드 슬롯 부재의 이중 차단). standard_codes는 PG TEXT[]로 바인딩한다.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.atom_probe import AtomProbe

        stmt = pg_insert(AtomProbe).values(
            code=record.code,
            name=record.name,
            school_level=record.school_level,
            subject_area=record.subject_area,
            subunit=record.subunit,
            diagnostic_item=record.diagnostic_item,
            diagnostic_answer=record.diagnostic_answer,
            diagnostic_signal=record.diagnostic_signal,
            socratic_question=record.socratic_question,
            intrinsic_difficulty=record.intrinsic_difficulty,
            standard_codes=list(record.standard_codes),
            review_status=ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED,
        )
        # PK 충돌 시 갱신 — updated_at은 now()로 새로 찍는다(server_default는 INSERT 전용).
        stmt = stmt.on_conflict_do_update(
            index_elements=[AtomProbe.code],
            set_={
                "name": stmt.excluded.name,
                "school_level": stmt.excluded.school_level,
                "subject_area": stmt.excluded.subject_area,
                "subunit": stmt.excluded.subunit,
                "diagnostic_item": stmt.excluded.diagnostic_item,
                "diagnostic_answer": stmt.excluded.diagnostic_answer,
                "diagnostic_signal": stmt.excluded.diagnostic_signal,
                "socratic_question": stmt.excluded.socratic_question,
                "intrinsic_difficulty": stmt.excluded.intrinsic_difficulty,
                "standard_codes": stmt.excluded.standard_codes,
                "review_status": stmt.excluded.review_status,
                "updated_at": func.now(),
            },
        )
        with self._get_engine().begin() as conn:
            conn.execute(stmt)


def populate_atom_probes(
    records: Sequence[AtomProbeRecord],
    *,
    settings: Settings | None = None,
    store: AtomProbeStore | None = None,
) -> int:
    """②진단문항·③소크라테스 레코드를 `atom_probe`에 멱등 upsert 적재(영속 프로젝션). 반환=행수.

    `populate_concept_content`의 *교수학 탐침* 짝이다 — 각 레코드를 code 키로 upsert한다(멱등·재실행
    시 갱신). store 미주입 시 슬3 sync 엔진 재사용 `AtomProbeStore`를 만든다.
    """
    resolved = settings if settings is not None else get_settings()
    probe_store = store if store is not None else AtomProbeStore(settings=resolved)
    for record in records:
        probe_store.upsert(record)
    return len(records)


__all__ = [
    "AtomProbeRecord",
    "AtomProbeStore",
    "load_atom_probes_from_json",
    "populate_atom_probes",
]
