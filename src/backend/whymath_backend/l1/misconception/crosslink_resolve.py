"""오개념 crosswalk read-time 해석 — kebab-id → M-id(들) 조회(학생 데이터 rekey 불필요).

학생 데이터(`misconception_hypothesis`·`evidence_links`)는 kebab-id를 *그대로* 보존한다(rekey·
마이그레이션·미성년 PII 이동 0). 학부모/학생 리포트 등에서 M-id 콘텐츠가 필요하면 *조회 시점*에
이 resolver로 `misconception_crosslink`를 조인해 동적으로 해석한다 — risk_register Q10-⑥
"단일 canonical 정체성"을 rekey 없이 실현(math_dsl_remediation_design.md §1).

**canonical 선택 정책**(M2 — 오귀속 방지·정직 우선): canonical M-id는 *confidence NOT NULL인
'직접매핑' 링크* 중 **strict 최대 confidence가 단독**일 때만 선정한다(`select_canonical`).
- 최고 confidence 동률 → canonical 없음 + `ambiguous=True`(reason `"tie"`) — 자동 임의 선택은
  오도된 코칭·리포트로 이어지므로(우선순위 #1·#3) 사람 정책 확정 전까지 정직하게 미선정.
- 직접매핑 부재(부분매핑·개념겹침만, 또는 직접매핑 전부 confidence NULL) → reason `"no_direct"`.
- 링크 자체 부재 → reason `"no_links"`.
- confidence 임계(예 0.6) 강제는 *매핑 승격(promote)* 단계 몫 — resolver는 정책을 중복하지 않는다
  (단일 진실 원천·이중 게이트 드리프트 방지).

순수 read: 어떤 학생 데이터·게이트도 변경하지 않는다. 매핑이 없으면 `[]`(graceful — 골격만 깔린
초기엔 전부 빈 결과·정직). `MisconceptionCatalogStore` 등과 동일 sync 엔진 좌석(신규 seam 0)이라
fake 엔진 주입으로 단위테스트 가능하다. async API 결선은 후속(본 슬라이스 비목표).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from whymath_backend.config import Settings, get_settings
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.misconception_crosslink import CrosslinkType

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import Engine

# canonical 선정 대상 연결 의미 — schema 닫힌 어휘(`CrosslinkType` Literal) 재사용. 어휘가 schema
# 에서 바뀌면 이 상수가 mypy에서 즉시 깨진다(리터럴 재정의·드리프트 방지).
_DIRECT_LINK_TYPE: CrosslinkType = "직접매핑"


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    """kebab-id 하나에 해석된 crosswalk 링크 1건 — link_type·confidence 포함(read-only 값 객체)."""

    mis_id: str
    link_type: str
    confidence: float | None


@dataclass(frozen=True, slots=True)
class CanonicalSelection:
    """canonical M-id 선정 결과 — 미선정도 *사유와 함께* 정직하게 반환(조용한 폴백 금지).

    `direct_count`는 canonical 후보 자격이 있는 링크 수 = confidence NOT NULL인 '직접매핑' 링크
    수다(NULL confidence 직접매핑은 검수 신뢰도 부재로 후보 제외 — 보수).
    """

    canonical_mis_id: str | None
    ambiguous: bool
    """직접매핑 최고 confidence 동률(tie) — canonical 플립 전 사람 정책 확정 필요 신호."""
    direct_count: int
    reason: Literal["ok", "no_links", "no_direct", "tie"]


def select_canonical(links: Sequence[ResolvedLink]) -> CanonicalSelection:
    """링크 목록 → canonical 선정(순수 함수·DB 0 — 정책 단위테스트 좌석).

    정책: confidence NOT NULL인 '직접매핑' 링크 중 **strict 최대 confidence 단독**일 때만 선정.
    동률이면 자동 임의 선택 대신 미선정+`ambiguous`(오귀속 방지 — 우선순위 #1·#3). 임계(0.6 등)
    강제는 promote 단계 몫이라 여기 없다(정책 중복 금지).
    """
    if not links:
        return CanonicalSelection(
            canonical_mis_id=None, ambiguous=False, direct_count=0, reason="no_links"
        )

    best_link: ResolvedLink | None = None
    best_conf: float | None = None
    tie = False
    direct_count = 0
    for link in links:
        conf = link.confidence
        # NULL confidence 직접매핑은 후보 제외(검수 신뢰도 부재 — 보수)·비직접(부분/개념겹침) 제외.
        if link.link_type != _DIRECT_LINK_TYPE or conf is None:
            continue
        direct_count += 1
        if best_conf is None or conf > best_conf:
            best_link, best_conf, tie = link, conf, False
        elif conf == best_conf:
            tie = True

    if best_link is None:
        return CanonicalSelection(
            canonical_mis_id=None, ambiguous=False, direct_count=0, reason="no_direct"
        )
    if tie:
        return CanonicalSelection(
            canonical_mis_id=None, ambiguous=True, direct_count=direct_count, reason="tie"
        )
    return CanonicalSelection(
        canonical_mis_id=best_link.mis_id,
        ambiguous=False,
        direct_count=direct_count,
        reason="ok",
    )


CanonicalLoadVerdictKind = Literal["ok", "wrong_winner", "tie"]


@dataclass(frozen=True, slots=True)
class CanonicalLoadVerdict:
    """kebab 하나에 대한 적재 후 canonical 시뮬 판정(HARN-216) — 코퍼스 자신의 선택과 비교한다.

    `corpus`는 적재 파일의 행**만**으로 계산한 선택(코퍼스가 의도한 canonical), `after_load`는
    라이브 잔존 행과 합친 집합의 선택이다. `rivals`는 코퍼스에 없는(=업서트가 지우지 못하는)
    라이브 직접매핑
    행 — 두 선택이 갈린 원인 후보이며 신뢰도 내림차순이다.
    """

    kebab_id: str
    verdict: CanonicalLoadVerdictKind
    corpus: CanonicalSelection
    after_load: CanonicalSelection
    corpus_confidence: float | None
    """코퍼스 canonical의 신뢰도(미선정이면 None) — 메시지에서 라이브 행과 비교하게 한다."""
    rivals: tuple[ResolvedLink, ...]


def _triplet(link: ResolvedLink) -> tuple[str, str]:
    """의미 유일키의 kebab 이후 부분 `(mis_id, link_type)` — 적재기 ON CONFLICT 키와 같다."""
    return (link.mis_id, link.link_type)


def simulate_load_canonical(
    live: Mapping[str, Sequence[ResolvedLink]],
    incoming: Mapping[str, Sequence[ResolvedLink]],
) -> list[CanonicalLoadVerdict]:
    """적재 **전에** 적재 후 canonical을 계산해 코퍼스 의도와 다른 kebab을 가린다(순수·DB 0).

    업서트(`ON CONFLICT DO UPDATE`)는 같은 `(kebab, mis_id, link_type)`만 덮어쓰고 코퍼스에 없는
    라이브 행은 **지우지 못한다**. 그래서 코퍼스를 그대로 다시 적재해도 오귀속 행이 살아남아 더 높은
    신뢰도로
    정답을 이기거나(wrong_winner) 같은 신뢰도로 동률을 만들 수 있다(tie) — 적재가 오류를 고친 것처럼
    보이면서 고치지 못하는 상태다. 이 함수는 그 결과를 쓰기 전에 보여 준다.

    - `live`: 적재 직전 DB의 kebab별 링크(적재 대상 kebab만 있으면 충분하다).
    - `incoming`: 적재 예정 링크. 같은 트리플 중복은 적재기와 같이 **마지막 우선**으로 접는다.
    - 반환: 적재 대상(incoming) kebab 전부, kebab 오름차순. 비교는 `(canonical_mis_id, reason)` —
      같으면 `ok`, 다르면서 적재 후가 동률이면 `tie`, 그 밖에는 `wrong_winner`.
      라이브에만 있고 코퍼스에 없는 kebab은 이 적재가 건드리지 않으므로 판정하지 않는다.
    """
    verdicts: list[CanonicalLoadVerdict] = []
    for kebab_id in sorted(incoming):
        corpus_by_key = {_triplet(link): link for link in incoming[kebab_id]}  # 마지막 우선
        corpus_links = list(corpus_by_key.values())
        # 라이브 중 코퍼스와 같은 트리플은 업서트가 코퍼스 값으로 덮으므로 *남는* 것은 나머지뿐이다.
        survivors = [link for link in live.get(kebab_id, ()) if _triplet(link) not in corpus_by_key]

        corpus = select_canonical(corpus_links)
        after_load = select_canonical([*corpus_links, *survivors])

        if (corpus.canonical_mis_id, corpus.reason) == (
            after_load.canonical_mis_id,
            after_load.reason,
        ):
            kind: CanonicalLoadVerdictKind = "ok"
        elif after_load.reason == "tie":
            kind = "tie"
        else:
            kind = "wrong_winner"

        corpus_conf = next(
            (
                link.confidence
                for link in corpus_links
                if link.mis_id == corpus.canonical_mis_id and link.link_type == _DIRECT_LINK_TYPE
            ),
            None,
        )
        rivals = tuple(
            sorted(
                (
                    link
                    for link in survivors
                    if link.link_type == _DIRECT_LINK_TYPE and link.confidence is not None
                ),
                key=lambda link: (-(link.confidence or 0.0), link.mis_id),
            )
        )
        verdicts.append(
            CanonicalLoadVerdict(
                kebab_id=kebab_id,
                verdict=kind,
                corpus=corpus,
                after_load=after_load,
                corpus_confidence=corpus_conf,
                rivals=rivals,
            )
        )
    return verdicts


class MisconceptionCrosslinkResolver:
    """kebab-id → M-id 해석기 — `misconception_crosslink` 조회(read-only·sync).

    `resolve`는 한 kebab-id에 매핑된 M-id 목록을, `resolve_many`는 여러 kebab-id의 매핑을 한 번에
    반환한다(N+1 회피). `min_confidence`를 주면 그 이상만(NULL confidence는 제외 — 보수). 결과는
    confidence 내림차순(NULL 마지막)·mis_id 보조정렬로 결정론적이다.

    `resolve_links`/`resolve_links_many`는 같은 조회의 link_type 포함 일반화(`ResolvedLink`),
    `resolve_canonical`은 그 위에 `select_canonical` 정책을 얹은 파생이다 — 기존 메서드도 동일
    내부 조회(`_fetch_links`)의 파생이라 진실 원천이 하나다.
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
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    # ── 내부 단일 조회 (모든 공개 메서드의 진실 원천) ──────────────────────
    def _fetch_links(
        self,
        kebab_ids: Sequence[str],
        *,
        min_confidence: float | None = None,
    ) -> dict[str, list[ResolvedLink]]:
        """여러 kebab-id → {kebab_id: [ResolvedLink...]} (단일 조회·N+1 0). 없는 kebab은 키 부재.

        정렬은 기존 `resolve_many` 결정론 그대로(confidence 내림차순·NULL 마지막·mis_id 보조) +
        link_type 최종 보조(같은 mis_id 다중 link_type도 결정론).
        """
        if not kebab_ids:
            return {}

        import sqlalchemy as sa

        from whymath_backend.db.models.misconception_crosslink import MisconceptionCrosslink

        stmt = sa.select(
            MisconceptionCrosslink.kebab_id,
            MisconceptionCrosslink.mis_id,
            MisconceptionCrosslink.link_type,
            MisconceptionCrosslink.confidence,
        ).where(MisconceptionCrosslink.kebab_id.in_(list(dict.fromkeys(kebab_ids))))
        if min_confidence is not None:
            # NULL confidence는 미만 취급(제외) — 검수 신뢰도 없는 매핑은 임계 적용 시 배제(보수).
            stmt = stmt.where(MisconceptionCrosslink.confidence >= min_confidence)

        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()

        result: dict[str, list[ResolvedLink]] = {}
        for row in rows:
            conf = row.confidence
            result.setdefault(row.kebab_id, []).append(
                ResolvedLink(
                    mis_id=row.mis_id,
                    link_type=row.link_type,
                    # DB Numeric(Decimal) → float 정규화(fake 엔진 float 입력은 항등).
                    confidence=float(conf) if conf is not None else None,
                )
            )

        # confidence 내림차순(NULL 마지막)·mis_id·link_type 보조정렬로 결정론적 순서.
        def _sort_key(link: ResolvedLink) -> tuple[int, float, str, str]:
            conf = link.confidence
            has_conf = 0 if conf is not None else 1  # 값 있는 것 먼저
            return (has_conf, -conf if conf is not None else 0.0, link.mis_id, link.link_type)

        for links in result.values():
            links.sort(key=_sort_key)
        return result

    # ── link_type 포함 일반화 ────────────────────────────────────────────
    def resolve_links_many(self, kebab_ids: Sequence[str]) -> dict[str, list[ResolvedLink]]:
        """여러 kebab-id → {kebab_id: [ResolvedLink...]}(link_type·confidence 포함·전량)."""
        return self._fetch_links(kebab_ids)

    def resolve_links(self, kebab_id: str) -> list[ResolvedLink]:
        """한 kebab-id의 링크 전량(link_type·confidence 포함) — 매핑 없으면 []."""
        return self.resolve_links_many([kebab_id]).get(kebab_id, [])

    # ── canonical 선정 (정책 = select_canonical 위임) ───────────────────
    def resolve_canonical(self, kebab_id: str) -> CanonicalSelection:
        """한 kebab-id의 canonical M-id 선정 — `select_canonical` 정책(오귀속 방지) 적용."""
        return select_canonical(self.resolve_links(kebab_id))

    # ── 기존 API (의미 불변 — _fetch_links 파생) ─────────────────────────
    def resolve(self, kebab_id: str, *, min_confidence: float | None = None) -> list[str]:
        """한 kebab-id에 매핑된 M-id 목록(매핑 없으면 []). min_confidence 미만·NULL은 제외(보수)."""
        return self.resolve_many([kebab_id], min_confidence=min_confidence).get(kebab_id, [])

    def resolve_many(
        self,
        kebab_ids: Sequence[str],
        *,
        min_confidence: float | None = None,
    ) -> dict[str, list[str]]:
        """여러 kebab-id → {kebab_id: [mis_id...]} (단일 조회·N+1 0). 없는 kebab은 키 부재."""
        fetched = self._fetch_links(kebab_ids, min_confidence=min_confidence)
        return {kebab: [link.mis_id for link in links] for kebab, links in fetched.items()}


__all__ = [
    "CanonicalLoadVerdict",
    "CanonicalLoadVerdictKind",
    "CanonicalSelection",
    "MisconceptionCrosslinkResolver",
    "ResolvedLink",
    "select_canonical",
    "simulate_load_canonical",
]
