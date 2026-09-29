"""의미 중복 태스크 탐지 — 이름이 달라도 같은 문제를 겨누는 태스크를 고지한다 (HARN-51).

## 왜 필요한가 (실사고)

2026-08-31~09-01, `HARN-45`와 `HARN-48`이 **같은 뿌리**(차단이 교차 세션 보호를 지운다)를
반대 극성으로 각자 구현됐다. 같은 기간 동종 6건 중 앞선 5건은 전부 *같은 식별자*를 두
세션이 배정한 형태라 번호 가드(HARN-10/15)가 **전건 실거부**했으나, 이 건은 ID가 서로
달라 번호 가드·claim 대장·`scan_remote_task_files` **어디에도 걸리지 않았다**. 실제 발견
경로는 기계가 아니라 상대 세션이 자기 YAML에 중복을 스스로 적어 둔 것이었다.

## 신호 — 왜 IDF 가중 희소어인가 (임베딩이 아니라)

두 태스크가 공유한 결정적 단어는 `차단`·`block`·`세션` 같은 일반어가 아니라
**`cmd_block`·`_release_remote_claim` 같은 희소 식별자**였다(코퍼스 485건 중 각 2건에만
등장). 그래서 공유어를 문서빈도의 역수(IDF)로 가중한다 — 흔한 말은 거의 기여하지 않고,
저장소 안에서 드문 말이 점수를 만든다. **IDF는 이 백로그 자신에서 산출**하므로 외부
모델·네트워크·임베딩이 필요 없다(하네스 CLI의 네트워크 0 계약 유지 · 과공학 방지).

## 실측 (2026-09-01 · 코퍼스 485건)

등재 시점 원본으로 대조했다 — 현재 YAML에는 사후에 쓴 cancel 사유가 서로를 직접
언급하고 있어 그대로 재면 점수가 부풀려진다.

- 표적(`HARN-45` ↔ `HARN-48`) = **0.1365**, in-flight 대조군 189건 중 **1위**.
  근거로 표시된 공유어: `_release_remote_claim`, `cmd_block`, `자리를`, `force`, `방향만`
- 무관 후보 최고점 0.0733 — 표적/잡음 **1.86배**
- 채택값(floor 0.13 · 상위 3건)으로 485건 전수 재현:
  평균 후보 **0.86건** · 최대 **3건** · 완전 침묵 **53%** · 후보 1건 이하 **75%**

**정직한 한계 3가지**

1. **침묵률 53%** — `HARN-43`의 고지(조건이 성립할 때만 발화)와 달리 이쪽은 절반가량의
   `add`에서 후보를 1건 내외 보여준다. 유사도에는 정답이 없어 이 비율을 0으로 만들려면
   임계를 올리는 수밖에 없는데, 그러면 실사고를 놓친다(floor 0.15에서 표적 누락).
   그래서 **차단하지 않고**, 후보를 한 줄로·공유한 희소어까지 함께 보여 한눈에 기각하게 한다.
2. **표적/잡음 1.86배** — 여유가 크지 않다. 1위 지목은 신뢰할 만하지만 점수 자체를
   "중복이다"의 증거로 읽으면 안 된다. 판단은 사람이 한다.
3. **어휘가 겹쳐야 보인다** — 같은 문제를 완전히 다른 말로 적으면 못 잡는다. 이 신호가
   작동한 것은 두 태스크가 같은 코드 식별자를 지목했기 때문이며, 그것이 없는 중복은
   여전히 관측 범위 밖이다.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

# 토큰: 영문 식별자(snake_case 포함, 3자 이상) 또는 한글 2자 이상.
# 1~2자 영문·숫자만인 토큰은 버린다 — 날짜·번호가 잡음을 만든다.
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[가-힣]{2,}")

# 채택값의 근거는 모듈 docstring의 실측표다. 바꾸려면 같은 측정을 다시 돌린다.
# **두 값만 남긴 이유**: 초안에는 "자기 점수 분포의 중앙값 대비 N배" 이상치 조건도
# 있었으나, 실코퍼스 485건 측정에서 기여가 없었다(평균 후보 1.75→1.77 · 침묵 20%→19%).
# 밀집 계열의 후보 폭주를 실제로 막는 것은 그 조건이 아니라 `MAX_CANDIDATES`였다
# (상한 제거 시 최대 3→23). 측정으로 무기여가 확인된 손잡이는 남기지 않는다 —
# 뮤테이션에도 안 걸리는 코드는 '선언됐지만 배선되지 않은' 것과 같다.
SIMILARITY_FLOOR = 0.13
MAX_CANDIDATES = 3


@dataclass(frozen=True)
class SimilarTask:
    """유사 후보 1건."""

    task_id: str
    score: float
    origin: str  # "로컬" 또는 "origin/<branch>"
    shared_terms: tuple[str, ...]  # 점수를 만든 희소어 상위 몇 개 (사람이 판단할 근거)


def tokenize(text: str) -> set[str]:
    """비교 단위 = 소문자 토큰 집합. 빈도가 아니라 유무만 본다 —
    긴 notes가 같은 말을 반복한다고 더 유사해지면 안 된다."""
    return {t.lower() for t in _TOKEN.findall(text)}


def task_text(title: str, notes: str, acceptance: Iterable[str]) -> str:
    """비교 대상 본문 — 제목·notes·acceptance를 합친다.

    셋 다 넣는 이유: 제목만으로는 이번 실사고가 안 잡힌다(공유어가 `차단`·`block`뿐).
    결정적 신호(`cmd_block`·`_release_remote_claim`)는 notes와 acceptance에 있었다.
    """
    return " ".join([title or "", notes or "", *(str(a) for a in acceptance or ())])


class SimilarityIndex:
    """코퍼스에서 IDF를 산출해 두고 신규 태스크를 대조한다.

    코퍼스(IDF 산출용)와 대조군(후보로 제시할 집합)은 **다르다** — IDF는 done/cancelled를
    포함한 전체에서 뽑아야 '무엇이 흔한 말인지'가 안정되고, 후보는 아직 진행 가능한
    것만 보여야 의미가 있다.
    """

    def __init__(self, corpus: dict[str, str]) -> None:
        self._tokens = {tid: tokenize(text) for tid, text in corpus.items()}
        self._n = max(len(self._tokens), 1)
        self._df: dict[str, int] = {}
        for toks in self._tokens.values():
            for t in toks:
                self._df[t] = self._df.get(t, 0) + 1
        self._weight: dict[str, float] = {
            tid: sum(self._idf(t) for t in toks) or 1.0 for tid, toks in self._tokens.items()
        }

    def _idf(self, term: str) -> float:
        return math.log(self._n / (1 + self._df.get(term, 0)))

    def score(self, tokens_a: set[str], tokens_b: set[str]) -> tuple[float, tuple[str, ...]]:
        """(점수, 기여 상위 공유어). 점수는 공유어 IDF 합을 양쪽 IDF 합의
        기하평균으로 정규화한 값 — 긴 문서가 자동으로 유리해지지 않게 한다."""
        shared = tokens_a & tokens_b
        if not shared:
            return 0.0, ()
        wa = sum(self._idf(t) for t in tokens_a) or 1.0
        wb = sum(self._idf(t) for t in tokens_b) or 1.0
        value = sum(self._idf(t) for t in shared) / math.sqrt(wa * wb)
        # IDF 동률일 때 표시 순서가 실행마다 바뀌면 안 된다(set 순회는 해시 무작위) —
        # 사람이 읽는 근거이자 테스트가 보는 값이므로 사전순으로 결정적 정렬한다.
        top = tuple(sorted(shared, key=lambda t: (-self._idf(t), t))[:5])
        return value, top

    def candidates(
        self,
        new_text: str,
        pool: dict[str, str],
        *,
        origins: dict[str, str] | None = None,
        floor: float = SIMILARITY_FLOOR,
        limit: int = MAX_CANDIDATES,
    ) -> list[SimilarTask]:
        """신규 태스크 본문 vs 대조군 → 고지할 후보(없으면 빈 리스트).

        두 손잡이가 각자 다른 일을 한다(실측 근거는 모듈 상단 상수의 주석):
          · `floor` — 아무와도 안 닮은 태스크에서 억지 후보를 만들지 않는다.
            제거하면 침묵률이 20%에서 3%로 무너진다(= 거의 매번 발화).
          · `limit` — 같은 계열 문서가 여러 건인 밀집 구간에서 후보가 쏟아지는 것을 막는다.
            제거하면 한 번에 최대 23건까지 나온다.
        """
        origins = origins or {}
        tokens = tokenize(new_text)
        if not tokens or not pool:
            return []
        scored: list[tuple[float, str, tuple[str, ...]]] = []
        for tid, text in pool.items():
            value, top = self.score(tokens, tokenize(text))
            scored.append((value, tid, top))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [
            SimilarTask(tid, value, origins.get(tid, "로컬"), top)
            for value, tid, top in scored[:limit]
            if value >= floor
        ]


# ── 슬러그 대조 — 본문이 없는 원격 claim·예약용 (HARN-111 ⑦(가)) ────────────────
#
# 위 IDF 본문 대조는 **본문(제목·notes·acceptance)이 있어야** 성립한다. 그런데 원격 claim
# 대장과 번호 예약에는 본문이 없고 **full ID(= 번호 + 슬러그)만** 있다. 2026-09-28
# `HARN-183`↔`OPS-69` 이중 등재는 슬러그까지 같았는데(`harness-integrity-timeout-budget`)
# 그 claim의 브랜치가 이 클론에 없어 본문 대조가 아예 성립하지 않았다.
#
# 왜 본문 점수에 claim ID를 섞지 않는가 (실측 2026-09-29 · 실코퍼스 891건): `HARN-183` 본문
# vs `OPS-69` full ID 문자열의 IDF 점수는 **0.091**로 floor 0.13 아래였다 — 짧은 문서는
# 정규화(기하평균)에서 불리하다. 같은 쌍의 **슬러그끼리 가중 자카드는 1.00**이다. 그래서
# 슬러그는 슬러그끼리 따로 잰다.
#
# 임계 보정 (같은 실측 — 슬러그 코퍼스 882건 · 순서 없는 쌍 388,521개):
#   가중 자카드 ≥ 0.5 → 쌍 57개(0.015%) · 1건 이상 걸리는 태스크 7.1%
#   ≥ 0.4 → 쌍 103개 · 15.8% / ≥ 0.6 → 쌍 44개 · 4.4%
# 대조군은 코퍼스 전체가 아니라 **로컬에 없는 원격 claim·예약**뿐이다(실측 당시 claim 16건 중
# 로컬 부재 2건) — 그래서 0.5에서 add 한 번당 오탐 기대치는 1% 미만이다. 0.5를 넘는 쌍의
# 상당수는 의도적 연작(`ARCH-0N-playbook-audit` 등)이며, 고지이지 차단이 아니므로 허용한다.
SLUG_FLOOR = 0.5

_SLUG_NUMBER = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+-?")


def slug_tokens(task_id: str) -> frozenset[str]:
    """`HARN-183-harness-integrity-timeout-budget` → {harness, integrity, timeout, budget}.

    번호 접두는 뗀다 — 번호는 번호 가드의 몫이고, 여기서 번호가 섞이면 같은 접두끼리
    점수가 부풀려진다. 1글자 토큰은 버린다(`bucket-b`의 `b` 같은 연작 꼬리표).
    """
    slug = _SLUG_NUMBER.sub("", task_id)
    return frozenset(t for t in slug.lower().split("-") if len(t) >= 2)


class SlugIndex:
    """슬러그 토큰 IDF — 가중 자카드로 두 full ID의 슬러그를 대조한다.

    IDF를 쓰는 이유는 본문 대조와 같다: `harness`·`gate`·`contract` 같은 흔한 슬러그 단어만
    겹친 쌍을 걸러야 한다. IDF는 호출자가 준 ID 목록(로컬 백로그 + 대조군) 자신에서 산출한다
    — 네트워크·외부 모델 없음.
    """

    def __init__(self, task_ids: Iterable[str]) -> None:
        token_sets = [slug_tokens(t) for t in task_ids]
        self._n = max(len(token_sets), 1)
        self._df: dict[str, int] = {}
        for toks in token_sets:
            for t in toks:
                self._df[t] = self._df.get(t, 0) + 1

    def _idf(self, term: str) -> float:
        # +1: 모든 ID에 있는 단어도 가중 0이 되지 않게 — 슬러그는 짧아서 토큰 하나가
        # 0이 되면 합집합이 비어 점수가 정의되지 않는 쌍이 생긴다.
        return math.log((self._n + 1) / (1 + self._df.get(term, 0))) + 1.0

    def score(self, a: str, b: str) -> tuple[float, tuple[str, ...]]:
        """(가중 자카드, 공유 토큰). 슬러그가 없는 쪽이 있으면 0."""
        ta, tb = slug_tokens(a), slug_tokens(b)
        union = ta | tb
        if not ta or not tb or not union:
            return 0.0, ()
        shared = ta & tb
        value = sum(self._idf(t) for t in shared) / sum(self._idf(t) for t in union)
        return value, tuple(sorted(shared, key=lambda t: (-self._idf(t), t)))
