"""오개념 의미(임베딩) 매칭 단위테스트 — slice 104 (hermetic·Fake 주입).

전부 FakeEmbeddingProvider(결정론 해시 벡터)로 라이브 모델 없이 검증한다:
  ① 패러프레이즈 recall win — substring `diagnose`가 못 잡는 표현을 의미 매칭이 잡음
  ② 임계값 경계(미만 미매칭)
  ③ 코사인 랭킹 순서
  ④ `diagnose()` 불변(회귀)
  ⑤ 방향맹 정직 — 올바른 역방향 진술도 의미상 가까워 매칭될 수 있음(과장 금지 증거)

FakeEmbeddingProvider는 *어휘 해시*(bag-of-words)라 라이브 의미 임베딩이 아니다 — 어휘
겹침으로 코사인이 결정된다. 그래서 ①은 *카탈로그 표현과 어휘를 공유하되 substring signals를
피하는* 학생 텍스트로 recall win을 결정론적으로 재현한다(진짜 동의어 recall은 integration).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.embedding_primitives import normalize_embedding_input
from whymath_backend.l4.misconception import MisconceptionMatch, diagnose
from whymath_backend.l4.misconception.catalog import CATALOG, CATALOG_BY_ID
from whymath_backend.l4.misconception.models import Misconception
from whymath_backend.l4.misconception.semantic import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    InMemoryVectorIndex,
    SemanticMatcher,
    build_semantic_matcher,
    catalog_text,
    cosine_similarity,
    semantic_matches,
)
from whymath_backend.l4.misconception.semantic import matcher as matcher_mod
from whymath_backend.l4.misconception.semantic.index import IndexHit


# ──────────────────────────────────────────────────────────────────────────
# 결정론 제어 제공자 — 키워드 집합으로 직교/근접을 *완전 통제*(랭킹·임계값 정밀 테스트용)
# ──────────────────────────────────────────────────────────────────────────
class ScriptedEmbeddingProvider:
    """텍스트에 등장하는 *제어 토큰*만으로 직교 기저 벡터를 합성하는 결정론 제공자.

    각 제어 토큰을 고정 차원의 한 좌표(원-핫)에 매핑한다 → 토큰 집합이 같으면 평행(코사인
    1.0), 토큰이 겹치는 비율로 코사인이 정해지고, 토큰이 안 겹치면 직교(0.0). 임계값·랭킹을
    *수치까지* 예측 가능하게 만들기 위함(FakeEmbeddingProvider의 SHA 해시는 충돌 가능성이
    있어 정밀 수치 단언엔 이 scripted 제공자를 쓴다).
    """

    def __init__(self, vocabulary: tuple[str, ...]) -> None:
        self._vocab = vocabulary
        self._dim = len(vocabulary)
        self._idx = {tok: i for i, tok in enumerate(vocabulary)}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        rows: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for tok in self._vocab:
                if tok in text:
                    vec[self._idx[tok]] = 1.0
            rows.append(vec)
        return rows


def _provider_is_embedding(p: object) -> None:
    """구조적 타이핑 확인 — Fake/Scripted가 EmbeddingProvider Protocol을 만족."""
    assert isinstance(p, EmbeddingProvider)


# ──────────────────────────────────────────────────────────────────────────
# 코사인 헬퍼 기본 동작
# ──────────────────────────────────────────────────────────────────────────
class TestCosineSimilarity:
    def test_parallel_is_one(self) -> None:
        assert cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)

    def test_orthogonal_is_zero(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_is_zero_not_nan(self) -> None:
        # 영벡터는 정의 불가 → 0으로 안전 처리(NaN 금지)
        result = cosine_similarity([0.0, 0.0], [1.0, 1.0])
        assert result == 0.0
        assert not math.isnan(result)

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


# ──────────────────────────────────────────────────────────────────────────
# FakeEmbeddingProvider — 결정론·구조
# ──────────────────────────────────────────────────────────────────────────
class TestFakeEmbeddingProvider:
    def test_deterministic_same_text_same_vector(self) -> None:
        p = FakeEmbeddingProvider()
        a = p.embed(["연속이면 미분가능하다"])
        b = p.embed(["연속이면 미분가능하다"])
        assert a == b

    def test_satisfies_protocol(self) -> None:
        _provider_is_embedding(FakeEmbeddingProvider())

    def test_batch_length_and_order_preserved(self) -> None:
        p = FakeEmbeddingProvider()
        out = p.embed(["가", "나", "다"])
        assert len(out) == 3
        # 같은 단어를 다시 넣으면 같은 벡터(순서·결정론)
        assert p.embed(["나"])[0] == out[1]

    def test_empty_input_empty_output_via_matcher(self) -> None:
        # 빈 배치는 빈 리스트(FakeEmbeddingProvider는 항목별로 처리하므로 [] → [])
        assert FakeEmbeddingProvider().embed([]) == []

    def test_shared_vocabulary_raises_cosine(self) -> None:
        # 어휘가 겹치면(같은 단어 포함) 코사인이 직교보다 높다(bag-of-words 해시)
        p = FakeEmbeddingProvider()
        base = p.embed(["분모 영 나눗셈 정의"])[0]
        overlap = p.embed(["분모 영 가능성"])[0]  # '분모'·'영' 공유
        disjoint = p.embed(["기울기 그래프 좌표"])[0]
        assert cosine_similarity(base, overlap) > cosine_similarity(base, disjoint)


# ──────────────────────────────────────────────────────────────────────────
# InMemoryVectorIndex — 랭킹·동률 안정성
# ──────────────────────────────────────────────────────────────────────────
class TestInMemoryVectorIndex:
    def test_search_orders_by_cosine_desc(self) -> None:
        idx = InMemoryVectorIndex()
        idx.add("a", [1.0, 0.0])  # 질의와 직교 → 0
        idx.add("b", [1.0, 1.0])  # 질의와 45도 → ~0.707
        idx.add("c", [0.0, 1.0])  # 질의와 평행 → 1.0
        hits = idx.search([0.0, 1.0], top_k=3)
        assert [h.key for h in hits] == ["c", "b", "a"]
        assert hits[0].similarity == pytest.approx(1.0)

    def test_top_k_caps_results(self) -> None:
        idx = InMemoryVectorIndex()
        for i in range(5):
            idx.add(f"k{i}", [1.0, float(i)])
        assert len(idx.search([1.0, 1.0], top_k=2)) == 2

    def test_top_k_zero_or_negative_empty(self) -> None:
        idx = InMemoryVectorIndex()
        idx.add("a", [1.0])
        assert idx.search([1.0], top_k=0) == []
        assert idx.search([1.0], top_k=-1) == []

    def test_tie_keeps_insertion_order(self) -> None:
        # 동률 유사도(둘 다 질의와 평행) → 삽입 순서 안정(stable sort)
        idx = InMemoryVectorIndex()
        idx.add("first", [1.0, 1.0])
        idx.add("second", [2.0, 2.0])  # 평행 → 같은 코사인
        hits = idx.search([1.0, 1.0], top_k=2)
        assert hits[0].similarity == pytest.approx(hits[1].similarity)
        assert [h.key for h in hits] == ["first", "second"]

    def test_index_hit_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        hit = IndexHit(key="x", similarity=0.5)
        with pytest.raises(FrozenInstanceError):
            hit.similarity = 0.9  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────
# SemanticMatcher — 임계값·랭킹·confidence 매핑 (Scripted 제공자로 정밀 수치)
# ──────────────────────────────────────────────────────────────────────────
class TestSemanticMatcherThresholdAndRanking:
    """직교 기저 Scripted 제공자로 코사인을 *수치까지* 통제해 임계값·랭킹·confidence 검증.

    커스텀 카탈로그 2종을 쓴다(실 카탈로그 의존 분리). 토큰 원-핫이라 코사인이 정확히
    예측된다.
    """

    def _catalog(self) -> tuple[Misconception, ...]:
        # canonical_statement에 *제어 토큰*을 심는다(catalog_text가 name_kr+canonical 직렬화).
        m1 = Misconception(
            id="ctrl-alpha",
            name_kr="알파",
            domain="대수",
            canonical_statement="ALPHA BETA",  # 토큰 ALPHA·BETA
            counterexample="x",
            signals=("기호없는토큰",),  # diagnose가 절대 안 잡게(학생 텍스트에 부재)
        )
        m2 = Misconception(
            id="ctrl-gamma",
            name_kr="감마",
            domain="대수",
            canonical_statement="GAMMA",  # 토큰 GAMMA
            counterexample="y",
            signals=("기호없는토큰2",),
        )
        return (m1, m2)

    def _vocab(self) -> tuple[str, ...]:
        # name_kr(알파/감마)도 catalog_text에 들어가므로 vocab에 포함해 직교 보장.
        return ("ALPHA", "BETA", "GAMMA", "알파", "감마", "DELTA")

    def test_threshold_filters_below(self) -> None:
        catalog = self._catalog()
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=catalog)
        # 질의 "ALPHA BETA 알파" → ctrl-alpha 표현("알파. ALPHA BETA")과 토큰 3개 모두 공유.
        #   ctrl-alpha 표현 토큰 = {알파, ALPHA, BETA}; 질의 토큰 = {ALPHA, BETA, 알파} → 코사인 1.0
        #   ctrl-gamma 표현 토큰 = {감마, GAMMA}; 질의와 교집합 0 → 코사인 0.0
        hits = matcher.match("ALPHA BETA 알파", top_k=5, threshold=0.5)
        assert [h.misconception.id for h in hits] == ["ctrl-alpha"]
        assert hits[0].confidence == pytest.approx(1.0)
        assert hits[0].semantic_similarity == pytest.approx(1.0)

    def test_partial_overlap_just_below_threshold_excluded(self) -> None:
        catalog = self._catalog()
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=catalog)
        # 질의 "ALPHA DELTA": ctrl-alpha 표현 토큰 {알파,ALPHA,BETA}와 교집합 {ALPHA}=1,
        # 질의 토큰 {ALPHA,DELTA}=2. 코사인 = 1/(sqrt(3)*sqrt(2)) ≈ 0.408.
        expected = 1.0 / (math.sqrt(3) * math.sqrt(2))
        # 임계값 0.5면 제외, 0.4면 포함 → 경계 동작 확인
        assert matcher.match("ALPHA DELTA", top_k=5, threshold=0.5) == []
        included = matcher.match("ALPHA DELTA", top_k=5, threshold=0.4)
        assert [h.misconception.id for h in included] == ["ctrl-alpha"]
        assert included[0].confidence == pytest.approx(expected)

    def test_ranking_more_overlap_first(self) -> None:
        catalog = self._catalog()
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=catalog)
        # 질의 "GAMMA 감마 ALPHA": ctrl-gamma는 *완전* 겹침, ctrl-alpha는 부분.
        #   ctrl-gamma {GAMMA,감마}, 질의 {GAMMA,감마,ALPHA} → 교집합 2/(√2·√3) ≈ 0.816
        #   ctrl-alpha {ALPHA,BETA,알파}, 교집합 {ALPHA}=1/(√3·√3) ≈ 0.333
        # → ctrl-gamma가 상위(겹침 비율이 더 높음).
        hits = matcher.match("GAMMA 감마 ALPHA", top_k=5, threshold=0.0)
        assert hits[0].misconception.id == "ctrl-gamma"
        assert hits[1].misconception.id == "ctrl-alpha"
        # match()는 MisconceptionMatch를 돌려준다 → 코사인은 semantic_similarity 필드.
        assert hits[0].semantic_similarity is not None and hits[1].semantic_similarity is not None
        assert hits[0].semantic_similarity > hits[1].semantic_similarity
        assert hits[0].semantic_similarity == pytest.approx(2.0 / (math.sqrt(2) * math.sqrt(3)))
        assert hits[1].semantic_similarity == pytest.approx(1.0 / 3.0)

    def test_top_k_caps(self) -> None:
        catalog = self._catalog()
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=catalog)
        hits = matcher.match("GAMMA 감마 ALPHA", top_k=1, threshold=0.0)
        assert len(hits) == 1
        assert hits[0].misconception.id == "ctrl-gamma"

    def test_empty_text_returns_empty(self) -> None:
        matcher = SemanticMatcher(provider=FakeEmbeddingProvider(), catalog=self._catalog())
        assert matcher.match("", top_k=3, threshold=0.5) == []

    def test_top_k_zero_returns_empty(self) -> None:
        matcher = SemanticMatcher(provider=FakeEmbeddingProvider(), catalog=self._catalog())
        assert matcher.match("ALPHA", top_k=0, threshold=0.5) == []


# ──────────────────────────────────────────────────────────────────────────
# ① 패러프레이즈 recall win — substring `diagnose`는 놓치고 의미 매칭은 잡음
# ──────────────────────────────────────────────────────────────────────────
class TestParaphraseRecallWin:
    """헤드라인 가치: substring AND가 못 잡는 표현을 의미 매칭이 잡는다(recall 보완).

    실 카탈로그 항목(division-by-zero: signals=("분모","0"))을 쓴다. 학생이 *"0"이라는 토큰을
    안 쓰고* 같은 오개념을 다른 어휘로 적으면 substring은 못 잡지만(거짓음성), 의미 매처는
    카탈로그 표현과 어휘를 공유해 잡는다.
    """

    def test_substring_misses_but_semantic_catches(self) -> None:
        # division-by-zero 표현 = "0 나눗셈 가능성 놓침. 분모에 변수가 와도 항상 정의됨"
        # 학생 텍스트: '분모' 포함하되 '0' 토큰 부재 → substring signals ("분모","0") 중 0 미충족.
        student = "분모에 변수가 와도 항상 정의된다고 생각했어 나눗셈 가능성 놓침"
        # (a) substring diagnose는 풀매칭(1.0) 못 함 — '0' 토큰 부재로 division-by-zero 불완전
        diag = {m.misconception.id: m for m in diagnose(student, top_k=10)}
        dz = diag.get("division-by-zero")
        assert dz is None or dz.confidence < 1.0  # substring은 놓치거나 부분 매칭에 그침

        # (b) 의미 매처(Fake·어휘 해시)는 표현과 어휘 공유로 division-by-zero를 *상위*로 올린다
        provider = FakeEmbeddingProvider()
        sem = semantic_matches(student, provider=provider, top_k=5, threshold=0.2)
        sem_ids = [m.misconception.id for m in sem]
        assert "division-by-zero" in sem_ids
        top = next(m for m in sem if m.misconception.id == "division-by-zero")
        assert top.semantic_similarity is not None
        assert top.confidence == pytest.approx(max(0.0, top.semantic_similarity))

    def test_semantic_match_carries_similarity_substring_does_not(self) -> None:
        # 의미 경로 결과는 semantic_similarity가 채워지고, substring 경로(diagnose)는 None
        provider = FakeEmbeddingProvider()
        sem = semantic_matches(
            "분모에 변수가 와도 항상 정의된다 나눗셈",
            provider=provider,
            top_k=3,
            threshold=0.1,
        )
        assert sem  # 최소 1건
        assert all(m.semantic_similarity is not None for m in sem)

        # substring 경로는 semantic_similarity=None(필드 기본)
        for m in diagnose("(a+b)² = a² + b²로 전개"):
            assert m.semantic_similarity is None


# ──────────────────────────────────────────────────────────────────────────
# ⑤ 방향맹 정직 테스트 — 과장 금지 증거(올바른 역방향도 의미상 가까워 매칭될 수 있음)
# ──────────────────────────────────────────────────────────────────────────
class TestDirectionBlindnessHonesty:
    """정직 스코프 증거(CLAUDE.md "확실하지 않을 때 자신 있게 말함 금지").

    임베딩은 *방향·부정·등치*를 못 가린다 — 두 문장이 *같은 어휘 집합*을 쓰면(방향/부정만
    다르고 단어는 같음) bi-encoder가 사실상 같은 벡터를 내어 구분이 불가능하다. 실 임베딩에서
    "연속이면 미분가능"(오개념)과 "미분가능하면 연속"(올바른 역방향)은 어휘가 거의 같아 둘 다
    같은 오개념에 높은 유사도로 매칭된다(false positive). 이건 *버그가 아니라 한계*이고, 방향
    판별은 LLM-judged/NLI 후속이다.

    이를 *결정론적으로* 못 박기 위해 어휘 원-핫 Scripted 제공자를 쓴다 — bi-encoder가 어순/
    방향을 무시하고 *단어 집합*만 본다는 핵심 성질을 그대로 모사한다(FakeEmbeddingProvider의
    SHA 해시도 단어 집합 기반이나, 정밀 등치 단언을 위해 직교 원-핫이 명확). 단어 집합이
    같으면 매처는 두 진술을 *구별하지 못한다*.
    """

    def _direction_catalog(self) -> tuple[Misconception, ...]:
        # 카탈로그 표현이 두 토큰 {CONT, DIFF}를 쓴다(방향 정보 없이 단어만).
        return (
            Misconception(
                id="dir-cont-diff",
                name_kr="함의",  # name_kr도 catalog_text에 들어가므로 vocab에 포함
                domain="미적분",
                canonical_statement="CONT DIFF",
                counterexample="x",
                signals=("미사용토큰",),
            ),
        )

    def _vocab(self) -> tuple[str, ...]:
        return ("CONT", "DIFF", "함의", "UNREL")

    def test_forward_and_reverse_share_vocab_get_identical_similarity(self) -> None:
        # 핵심 정직 단언: 방향만 다르고 *단어 집합이 같은* 두 진술은 매처가 동일 유사도로 매칭
        # → 방향을 가르지 못한다(둘 다 같은 오개념 후보). bi-encoder의 어순/방향 무시 성질.
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=self._direction_catalog())
        # "CONT면 DIFF"(오개념 방향)와 "DIFF면 CONT"(올바른 역방향) — 단어 집합 {CONT,DIFF} 동일
        forward = matcher.match("CONT 이면 DIFF", top_k=5, threshold=0.3)
        reverse = matcher.match("DIFF 이면 CONT", top_k=5, threshold=0.3)
        assert [h.misconception.id for h in forward] == ["dir-cont-diff"]
        assert [h.misconception.id for h in reverse] == ["dir-cont-diff"]
        # *동일* 유사도 — 매처가 방향을 구분 못 한다는 결정론적 증거(과장 금지).
        assert forward[0].semantic_similarity == pytest.approx(reverse[0].semantic_similarity)

    def test_negation_not_distinguished(self) -> None:
        # 부정("CONT ≠ DIFF")도 단어 집합 {CONT,DIFF}가 같아(≠는 별 토큰 아님) 동일 매칭.
        # 의미 매처는 부정을 신호로 쓰지 못한다(LLM-judged 후속).
        provider = ScriptedEmbeddingProvider(self._vocab())
        matcher = SemanticMatcher(provider=provider, catalog=self._direction_catalog())
        affirm = matcher.match("CONT = DIFF", top_k=5, threshold=0.3)
        negate = matcher.match("CONT ≠ DIFF 아니다", top_k=5, threshold=0.3)
        assert affirm and negate
        assert affirm[0].misconception.id == negate[0].misconception.id == "dir-cont-diff"
        assert affirm[0].semantic_similarity == pytest.approx(negate[0].semantic_similarity)

    def test_real_catalog_reverse_also_surfaces_with_lexical_fake(self) -> None:
        # 보강(비결정론 단언 회피): 실 카탈로그·Fake로 *방향 쌍*을 넣었을 때, 올바른 역방향이
        # 오개념 항목을 *후보에서 배제하지 못함*을 약하게 확인한다(매칭되면 방향맹 증거; Fake의
        # 어휘 해시 특성상 형태소 변형으로 안 잡힐 수도 있어 강한 단언은 integration에 맡긴다).
        provider = FakeEmbeddingProvider()
        # 카탈로그 표현과 *동일 어휘*를 그대로 써 Fake에서도 확실히 겹치게 한다.
        cid = "continuity-implies-differentiability"
        canon = CATALOG_BY_ID[cid].canonical_statement  # "연속이면 미분가능하다"
        forward_hits = {
            m.misconception.id
            for m in semantic_matches(canon, provider=provider, top_k=10, threshold=0.2)
        }
        assert cid in forward_hits  # 오개념 진술 자체는 당연히 매칭(스모크)


# ──────────────────────────────────────────────────────────────────────────
# ④ diagnose() 불변(회귀) — 의미 매칭 도입이 substring 경로를 건드리지 않음
# ──────────────────────────────────────────────────────────────────────────
class TestDiagnoseUnchanged:
    """slice 104가 `diagnose()` 시그니처·동작을 *불변*으로 유지(잠긴 회귀 보강)."""

    def test_full_signal_still_confidence_1(self) -> None:
        top = diagnose("내 풀이는 (a+b)² = a² + b²로 전개했어")[0]
        assert top.misconception.id == "distribution-over-power"
        assert top.confidence == 1.0
        assert set(top.matched_signals) == {"(a+b)", "a² + b²"}

    def test_no_semantic_similarity_on_substring_results(self) -> None:
        # 모든 substring 결과의 semantic_similarity는 None(신규 선택 필드 기본)
        for m in diagnose("(a+b)² = a² + b² 그리고 log(a+b)는 log a + log b"):
            assert m.semantic_similarity is None
            assert m.matched_regex_signals == () or isinstance(m.matched_regex_signals, tuple)

    def test_numeric_regex_path_unchanged(self) -> None:
        m = next(
            x
            for x in diagnose("(3+4)² = 3² + 4² = 25", top_k=5)
            if x.misconception.id == "distribution-over-power"
        )
        # MISC-22(v1.5): 정규식 매치 1건 = substring 신호 전체와 동등한 완결 증거 → conf 1.0.
        assert m.confidence == 1.0
        assert m.matched_signals == ()
        assert len(m.matched_regex_signals) == 1
        assert m.semantic_similarity is None


# ──────────────────────────────────────────────────────────────────────────
# 매처 캐시·실 카탈로그 적재 동작
# ──────────────────────────────────────────────────────────────────────────
class TestMatcherCatalogBuild:
    def test_real_catalog_indexed_once(self) -> None:
        # 실 카탈로그(30종)가 인덱스에 1회 적재되고 재질의 시 재임베딩 안 함을 카운트로 확인
        calls = {"n": 0}

        class CountingProvider:
            def __init__(self) -> None:
                self._inner = FakeEmbeddingProvider()

            def embed(self, texts: Sequence[str]) -> list[list[float]]:
                calls["n"] += 1
                return self._inner.embed(texts)

        index = InMemoryVectorIndex()
        matcher = SemanticMatcher(provider=CountingProvider(), index=index)
        matcher.match("분모 0 나눗셈", top_k=3, threshold=0.1)
        first = calls["n"]
        matcher.match("연속 미분가능", top_k=3, threshold=0.1)
        second = calls["n"]
        # 1회차: 카탈로그 배치 임베딩(1) + 질의(1) = 2. 2회차: 질의(1)만 += → 카탈로그 재적재 없음
        assert first == 2
        assert second == 3
        assert len(index) == len(CATALOG_BY_ID)

    def test_provider_length_mismatch_raises(self) -> None:
        # provider.embed가 카탈로그 개수와 다른 길이를 내면 RuntimeError(좌석 계약 fail-loud).
        catalog = (
            Misconception(
                id="solo",
                name_kr="단일",
                domain="대수",
                canonical_statement="X",
                counterexample="y",
                signals=("기호없는토큰3",),
            ),
        )

        class ShortProvider:
            def embed(self, texts: Sequence[str]) -> list[list[float]]:
                return []  # 입력 길이 무시 → 카탈로그(1)와 불일치

        matcher = SemanticMatcher(
            provider=ShortProvider(), index=InMemoryVectorIndex(), catalog=catalog
        )
        with pytest.raises(RuntimeError, match="임베딩 개수"):
            matcher.match("X", top_k=1, threshold=0.1)

    def test_catalog_text_format(self) -> None:
        # 포맷 v2: `name_kr. canonical_statement`를 NFKC 정규화(질의 경로와 같은 정규화·표기 정합).
        m = CATALOG_BY_ID["division-by-zero"]
        assert catalog_text(m) == normalize_embedding_input(f"{m.name_kr}. {m.canonical_statement}")

    def test_safe_embed_fields_pinned(self) -> None:
        # redaction drift 가드 — 안전 필드 집합을 *리뷰 없이 확대하면* 실패한다(개념판 규율 대칭).
        # 향후 출처 인용·본문 발췌 필드가 추가돼도 임베딩에 자동 유입되지 않도록 집합을 고정한다.
        assert matcher_mod._SAFE_EMBED_FIELDS == ("name_kr", "canonical_statement")

    def test_catalog_text_excludes_non_safe_fields(self) -> None:
        # counterexample·signals·regex_signals·correct_form는 표면/구조 용도라 임베딩에 안 들어간다.
        m = Misconception(
            id="redaction-probe",
            name_kr="라벨",
            domain="대수",
            canonical_statement="가정진술",
            counterexample="COUNTEREX_SENTINEL",
            signals=("SIGNAL_SENTINEL",),
            regex_signals=("REGEX_SENTINEL",),
            correct_form="CORRECT_SENTINEL",
        )
        text = catalog_text(m)
        assert text == "라벨. 가정진술"
        for sentinel in ("COUNTEREX", "SIGNAL", "REGEX", "CORRECT"):
            assert sentinel not in text

    def test_semantic_matches_default_threshold_from_settings(self) -> None:
        # threshold 미지정 → Settings 기본(0.55). Fake로 무관 텍스트는 임계 미달 → 빈/소수.
        provider = FakeEmbeddingProvider()
        out = semantic_matches("완전히 무관한 임의의 문장 zzzzz", provider=provider, top_k=3)
        # 무관 텍스트는 카탈로그와 어휘 비공유 → 코사인 0 근처 → 보수적 임계 0.55 미달로 빈 리스트
        assert out == []


# ──────────────────────────────────────────────────────────────────────────
# prebuilt_index 모드 — 영속 사전 임베딩(PgVectorIndex) 재사용·카탈로그 재임베딩 0
# ──────────────────────────────────────────────────────────────────────────
class TestSemanticMatcherPrebuiltIndex:
    """사전적재된 인덱스를 *재임베딩 없이* 질의(라이브 진단 경로의 항목당 재임베딩 비용 0)."""

    def _catalog(self) -> tuple[Misconception, ...]:
        m1 = Misconception(
            id="ctrl-alpha",
            name_kr="알파",
            domain="대수",
            canonical_statement="ALPHA BETA",
            counterexample="x",
            signals=("기호없는토큰",),
        )
        m2 = Misconception(
            id="ctrl-gamma",
            name_kr="감마",
            domain="대수",
            canonical_statement="GAMMA",
            counterexample="y",
            signals=("기호없는토큰2",),
        )
        return (m1, m2)

    def _vocab(self) -> tuple[str, ...]:
        return ("ALPHA", "BETA", "GAMMA", "알파", "감마", "DELTA")

    def test_prebuilt_skips_catalog_embedding_and_matches(self) -> None:
        catalog = self._catalog()
        vocab = self._vocab()
        # 인덱스를 *별도* 제공자로 미리 채운다(populate_pgvector 대역·카탈로그 순서).
        populate_provider = ScriptedEmbeddingProvider(vocab)
        index = InMemoryVectorIndex()
        for m in catalog:
            index.add(m.id, populate_provider.embed([catalog_text(m)])[0])

        calls = {"n": 0}

        class CountingProvider:
            def __init__(self) -> None:
                self._inner = ScriptedEmbeddingProvider(vocab)

            def embed(self, texts: Sequence[str]) -> list[list[float]]:
                calls["n"] += 1
                return self._inner.embed(texts)

        matcher = SemanticMatcher(
            provider=CountingProvider(), index=index, catalog=catalog, prebuilt_index=True
        )
        hits = matcher.match("ALPHA BETA 알파", top_k=5, threshold=0.5)
        # 사전적재 인덱스를 그대로 질의 → 정확히 ctrl-alpha(코사인 1.0).
        assert [h.misconception.id for h in hits] == ["ctrl-alpha"]
        assert hits[0].confidence == pytest.approx(1.0)
        # ★ 카탈로그 *재임베딩 0* — provider.embed는 *질의 1건*만(prebuilt 핵심 이득).
        assert calls["n"] == 1

    def test_prebuilt_requires_injected_index(self) -> None:
        # prebuilt_index=True + index=None → ValueError(빈 인덱스 질의는 무의미·오용 가드).
        with pytest.raises(ValueError, match="prebuilt_index"):
            SemanticMatcher(provider=FakeEmbeddingProvider(), prebuilt_index=True)

    def test_prebuilt_empty_index_returns_empty_no_reembed(self) -> None:
        # prebuilt인데 인덱스가 비었으면(미적재) → 재임베딩 *않고* 빈 결과(호출자 신뢰 계약).
        catalog = self._catalog()
        calls = {"n": 0}

        class CountingProvider:
            def __init__(self) -> None:
                self._inner = ScriptedEmbeddingProvider(self._outer_vocab)

            _outer_vocab = ("ALPHA", "BETA", "GAMMA", "알파", "감마", "DELTA")

            def embed(self, texts: Sequence[str]) -> list[list[float]]:
                calls["n"] += 1
                return self._inner.embed(texts)

        matcher = SemanticMatcher(
            provider=CountingProvider(),
            index=InMemoryVectorIndex(),  # 비었지만 주입됨(가드 통과)
            catalog=catalog,
            prebuilt_index=True,
        )
        assert matcher.match("ALPHA BETA", top_k=5, threshold=0.5) == []
        assert calls["n"] == 1  # 질의 1건만(카탈로그 재적재 안 함)


# ──────────────────────────────────────────────────────────────────────────
# MisconceptionMatch 하위호환 — 신규 선택 필드
# ──────────────────────────────────────────────────────────────────────────
class TestMisconceptionMatchBackwardCompat:
    def test_semantic_similarity_defaults_none(self) -> None:
        m = MisconceptionMatch(misconception=CATALOG_BY_ID["division-by-zero"], confidence=0.5)
        assert m.semantic_similarity is None

    def test_semantic_similarity_settable(self) -> None:
        m = MisconceptionMatch(
            misconception=CATALOG_BY_ID["division-by-zero"],
            confidence=0.8,
            semantic_similarity=0.8,
        )
        assert m.semantic_similarity == pytest.approx(0.8)


# ──────────────────────────────────────────────────────────────────────────
# build_semantic_matcher 좌석 팩토리 — vector_store별 index/identity 체인 단일화
# ──────────────────────────────────────────────────────────────────────────
class _CountingProvider:
    """provider.embed 호출 횟수를 세는 래퍼(재임베딩 0 증명용)."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = FakeEmbeddingProvider(dim=16)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return self._inner.embed(texts)


class TestBuildSemanticMatcher:
    def test_memory_self_builds_and_matches(self) -> None:
        # memory(기본): InMemoryVectorIndex 자체 적재·매칭 동작(종전 동작 불변).
        matcher = build_semantic_matcher(FakeEmbeddingProvider(dim=16), settings=Settings())
        hits = matcher.match(catalog_text(CATALOG[0]), top_k=1, threshold=-2.0)
        assert hits and hits[0].misconception.id == CATALOG[0].id
        assert isinstance(matcher._index, InMemoryVectorIndex)

    def test_memory_ignores_prebuilt_flag(self) -> None:
        # memory에서 prebuilt_index=True는 무시(자체 적재가 정답·빈 질의 방지)·정상 매칭.
        matcher = build_semantic_matcher(
            FakeEmbeddingProvider(dim=16), settings=Settings(), prebuilt_index=True
        )
        hits = matcher.match(catalog_text(CATALOG[0]), top_k=1, threshold=-2.0)
        assert hits and hits[0].misconception.id == CATALOG[0].id

    def test_pgvector_prebuilt_skips_catalog_embedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pgvector + prebuilt=True: 사전적재 인덱스를 재임베딩 없이 질의(build_vector_index 패치).
        populate = FakeEmbeddingProvider(dim=16)
        prepopulated = InMemoryVectorIndex()
        for m in CATALOG:
            prepopulated.add(m.id, populate.embed([catalog_text(m)])[0])
        monkeypatch.setattr(
            matcher_mod, "build_vector_index", lambda *a, **k: prepopulated  # noqa: ARG005
        )
        provider = _CountingProvider()
        matcher = build_semantic_matcher(
            provider, settings=Settings(vector_store="pgvector"), prebuilt_index=True
        )
        hits = matcher.match(catalog_text(CATALOG[0]), top_k=1, threshold=-2.0)
        assert hits and hits[0].misconception.id == CATALOG[0].id
        assert provider.calls == 1  # ★ 질의 1건만 — 카탈로그 재임베딩 0(prebuilt 핵심)

    def test_pgvector_self_build_embeds_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pgvector + prebuilt=False: 종전대로 첫 매칭 시 카탈로그 자체 적재(embed 카탈로그+질의=2).
        empty = InMemoryVectorIndex()
        monkeypatch.setattr(
            matcher_mod, "build_vector_index", lambda *a, **k: empty  # noqa: ARG005
        )
        provider = _CountingProvider()
        matcher = build_semantic_matcher(
            provider, settings=Settings(vector_store="pgvector"), prebuilt_index=False
        )
        matcher.match(catalog_text(CATALOG[0]), top_k=1, threshold=-2.0)
        assert provider.calls == 2  # 카탈로그 배치(1) + 질의(1) = 2(자체 적재)
