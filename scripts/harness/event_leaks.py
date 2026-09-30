"""테스트 누출이 남긴 가짜 `policy_warn` 묶음을 **서명으로** 식별한다 (HARN-170 ⑤).

왜 지우지 않는가
---------------
이벤트 대장은 append 전용이다 — 되돌릴 수 없는 기록이라야 감사 로그로서 믿을 수 있다. 그래서
이미 main에 커밋된 누출분은 삭제하지 않고, 집계(`backlog.py policy report`)에서 식별해 뺀다.
누출 자체는 `tests/harness/conftest.py`의 격리(HARN-170 ①②)가 막는다 — 이 모듈은 그 이전에
쌓인 것을 세는 쪽이다.

어디서 온 줄인가
---------------
`tests/harness/test_jit_rules.py::TestCheckEditHook`(HARN-121 ③ · 2026-09-21 #1246 착지)가
실제 저장소 루트에서 `check-edit`를 불렀다. claim이 걸린 세션에서는 scope_drift가, 원격 claim
캐시에 `scripts/harness/backlog.py`를 덮는 타 세션 태스크가 있으면 path_overlap이 발화해 실제
세션 샤드에 썼다 — 그 클래스는 backlog.py로 3번, README.md로 1번 check-edit를 불렀다.

서명 (2026-09-29 main 전수 실측으로 정했다 — 수치 근거는 각 상수 주석)
--------------------------------------------------------------------
한 샤드의 policy_warn을 시각순으로 놓고 이웃 간격이 `GAP_SECONDS` 이하이면 한 묶음으로 잇는다.
그 묶음이 다섯 조건을 모두 만족하면 누출 묶음이다.
  ① 파일이 {backlog.py, README.md}뿐이고 backlog.py가 있다
  ② backlog.py 경고가 규칙마다 정확히 3건이다(클래스의 backlog.py 호출 수)
  ③ README.md 경고는 0~1건이고 scope_drift뿐이다(같은 클래스의 cold path 호출)
  ④ 묶음 전체가 `SPAN_SECONDS` 안이고, 같은 샤드의 다른 경고와 앞뒤로 `ISOLATION_SECONDS`
     이상 떨어져 있다 — 한 테스트 클래스가 연달아 돌고 끝난다. 사람(세션)의 연속 편집은
     앞뒤로 다른 편집 경고가 붙어 있다
  ⑤ 첫 경고가 `LEAK_EPOCH`(누출 경로의 착지일) 이후다 — 그 전에는 이 경로가 없었다

한계 (정직한 공백)
-----------------
④⑤를 모두 통과하는 실제 편집(착지일 이후, 앞뒤 30초 안에 다른 경고가 없는 채로 backlog.py를
정확히 3번 고친 경우)은 서명이 같아 집계에서 빠진다 — 과소 집계 방향이다. 실측으로는 누출
묶음의 고립 거리가 최소 79초, 같은 모양의 실제 편집 묶음은 9·12초였다(2026-09-07 한 세션).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import store

LEAK_FILES: frozenset[str] = frozenset({"scripts/harness/backlog.py", "README.md"})
HOT_FILE = "scripts/harness/backlog.py"
COLD_FILE = "README.md"
HOT_CALLS_PER_RULE = 3  # TestCheckEditHook의 backlog.py check-edit 호출 수(누출 당시)

# 착지일 — TestCheckEditHook이 main에 들어온 날(2026-09-21 #1246). 그 전에는 누출 경로가 없다.
# 실측: 이 조건이 없으면 2026-09-07 한 세션의 실제 연속 편집 묶음 2개가 같은 모양으로 걸린다.
LEAK_EPOCH = date(2026, 9, 21)

# 묶음을 잇는 이웃 간격 상한. 실측(2026-09-29 main): 6·8·10초 모두 누출 묶음 97개·465건으로
# 같다(4초면 90개 — 묶음 안 최대 간격이 6초다). 느린 머신 여유를 두고 고원 가운데 8초를 쓴다.
GAP_SECONDS = 8.0

# 묶음 전체 길이 상한. 실측 최대 9초 · 12~30초 모두 97개로 같다 — 여유를 두고 20초.
SPAN_SECONDS = 20.0

# 앞뒤 고립 거리 하한. 실측: 누출 묶음 최소 79초 · 같은 모양의 실제 편집 묶음 9·12초.
ISOLATION_SECONDS = 30.0


@dataclass(frozen=True)
class WarnEvent:
    """policy_warn 한 줄 — 어느 샤드의 몇 번째 줄인지(식별 키)와 판정에 쓰는 필드만."""

    shard: str
    line: int
    moment: datetime
    rule: str
    file: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.shard, self.line)


def _bundles(events: list[WarnEvent]) -> list[list[WarnEvent]]:
    """한 샤드의 경고를 시각순으로 놓고 간격 `GAP_SECONDS` 이하로 잇는다."""
    ordered = sorted(events, key=lambda e: (e.moment, e.line))
    bundles: list[list[WarnEvent]] = []
    for event in ordered:
        if bundles and (event.moment - bundles[-1][-1].moment).total_seconds() <= GAP_SECONDS:
            bundles[-1].append(event)
        else:
            bundles.append([event])
    return bundles


def _has_leak_shape(bundle: list[WarnEvent]) -> bool:
    files = {e.file for e in bundle}
    if not files <= LEAK_FILES or HOT_FILE not in files:  # ①
        return False
    per_rule = Counter((e.file, e.rule) for e in bundle)
    hot = [count for (file, _rule), count in per_rule.items() if file == HOT_FILE]
    if any(count != HOT_CALLS_PER_RULE for count in hot):  # ②
        return False
    cold = [(rule, count) for (file, rule), count in per_rule.items() if file == COLD_FILE]
    if sum(count for _rule, count in cold) > 1 or any(rule != "scope_drift" for rule, _ in cold):
        return False  # ③
    return (bundle[-1].moment - bundle[0].moment).total_seconds() <= SPAN_SECONDS  # ④ 길이


def leak_bundles(events: Iterable[WarnEvent]) -> list[list[WarnEvent]]:
    """누출 서명과 맞는 묶음 전부 — 샤드별로 따로 본다(다른 세션의 경고는 섞지 않는다)."""
    by_shard: dict[str, list[WarnEvent]] = {}
    for event in events:
        by_shard.setdefault(event.shard, []).append(event)
    found: list[list[WarnEvent]] = []
    for shard_events in by_shard.values():
        bundles = _bundles(shard_events)
        for index, bundle in enumerate(bundles):
            if bundle[0].moment.date() < LEAK_EPOCH:  # ⑤
                continue
            if not _has_leak_shape(bundle):
                continue
            before = bundles[index - 1][-1].moment if index > 0 else None
            after = bundles[index + 1][0].moment if index + 1 < len(bundles) else None
            if (
                before is not None
                and (bundle[0].moment - before).total_seconds() < ISOLATION_SECONDS
            ):
                continue  # ④ 고립 — 앞
            if (
                after is not None
                and (after - bundle[-1].moment).total_seconds() < ISOLATION_SECONDS
            ):
                continue  # ④ 고립 — 뒤
            found.append(bundle)
    return found


def leak_keys(events: Iterable[WarnEvent]) -> set[tuple[str, int]]:
    """누출 묶음에 속한 줄의 (샤드, 줄 번호) — 집계에서 뺄 대상."""
    return {event.key for bundle in leak_bundles(events) for event in bundle}


def read_warn_events(root: Path) -> list[tuple[WarnEvent, dict, bool]]:
    """이벤트 대장 전 파일(레거시 + 세션 샤드)의 policy_warn — (판정 레코드, 원본, 오프셋 실측).

    샤드 키는 `backlog/` 기준 상대 경로다(`events.ndjson`·`events/<세션>.ndjson`) — 이름만 쓰면
    레거시 파일과 `events`라는 브랜치의 샤드가 같은 키가 된다. 줄 번호는 1부터다.
    """
    backlog_root = store.backlog_dir(root)
    found: list[tuple[WarnEvent, dict, bool]] = []
    for path in store.event_paths(root):
        shard = path.relative_to(backlog_root).as_posix()
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("action") != "policy_warn":
                continue
            moment = store.parse_event_ts(event.get("ts"))
            if moment is None:
                continue
            record = WarnEvent(
                shard=shard,
                line=lineno,
                moment=moment.moment,
                rule=str(event.get("rule", "")),
                file=str(event.get("file", "")),
            )
            found.append((record, event, moment.offset_known))
    return found
