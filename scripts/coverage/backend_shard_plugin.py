"""backend pytest **잡 단위** 샤딩 플러그인 (OPS-83).

왜 필요한가
-----------
`backend — lint·type·test` 잡이 머지 큐 회전의 지배 항이 됐다. 2026-10-26 merge_group 15회 중
4회가 `timeout-minutes: 50` 상한에서 취소됐고, 통과 11회의 pytest 스텝이 잡의 84.5%(중앙
2,346초/2,775초)였다. OPS-58이 러너 1대 안에서 xdist로 코어를 나눴으니(잡 *내부* 병렬화),
남은 축은 러너 N대로 파일을 나누는 것(잡 *단위* 분할)이다.

어떻게 나누는가
---------------
`-p backend_shard_plugin --shard K/N --shard-report <경로>`로 켠다(플래그가 없으면 아무 일도
하지 않는다 — 로컬·야간 직렬 실행은 영향이 없다).

* **분배 단위 = 테스트 파일.** 같은 파일의 테스트는 반드시 같은 샤드에 간다. `--dist loadfile`과
  같은 성질이며, 이 저장소의 파일 내부 순서 의존(OPS-06/07/09) 이력 때문에 그보다 잘게
  자르지 않는다.
* **배정의 우주 = pytest 자신의 수집 결과.** 파일 목록을 따로 계산해 인자로 넘기지 않는다 —
  그러면 pytest가 수집하는 파일과 우리가 나눈 파일이 어긋나도(새 명명 규칙·conftest 수집 훅 등)
  조용히 빠진다. 모든 샤드가 전건을 수집한 뒤 *자기 몫이 아닌 파일을 deselect*하므로, 수집된
  것은 반드시 어느 한 샤드에 배정된다.
* **배정 규칙 = 파일 경로의 sha256 mod N.** 파일 하나의 샤드는 그 파일의 경로만으로 정해진다 —
  다른 파일이 수집됐는지, 어떤 순서인지(pytest-randomly)와 무관하므로 샤드·워커마다 수집 결과가
  조금 달라도 배정이 어긋나지 않고, 파일을 추가해도 기존 파일의 샤드가 움직이지 않는다.
  항목 수 기준 LPT와 경로 정렬 라운드로빈도 실측으로 비교했다(OPS-83 · 2026-10-26 로컬 전건
  junit의 파일별 소요 998파일·6,586초로 샤드 안 xdist 4워커 무작위 순서를 30회 모사). n=3 샤드
  최대 벽시계 평균이 해시 837초 · 라운드로빈 893초 · 항목 LPT 925초였다 — 항목 수는 매개변수화가
  많은 가벼운 파일을 한쪽에 몰아 시간 균형이 가장 나빴다. 측정 소요를 가중치로 쓰는 LPT(862초)는
  가중치 파일을 저장소에 두고 계속 갱신해야 하는데 이득이 없어 채택하지 않았다(샤드 벽시계의 하한은
  최대 단일 파일 636초가 정하고, 그 파일이 늦게 시작되는 순서 효과가 배정 차이보다 크다).
* **완전성 증거 = 배정 보고서.** 샤드마다 `--shard-report`에 (전체 항목·파일 수, 전체 파일 목록
  지문, 자기 몫 파일 목록)을 쓴다. 집계 잡이 `backend_shard_verdict.py reports`로 "모든 샤드가
  같은 우주를 봤고, 몫이 서로 겹치지 않으며, 합이 우주와 같다"를 검사한다. 샤드 하나가 덜
  수집했거나 `K/N`을 잘못 적었으면 거기서 red가 된다 — "13,000건 통과"가 "일부만 돌았다"를
  가리지 못하게 하는 장치다(OPS-83 ⑥).

xdist 아래에서
--------------
수집·`pytest_collection_modifyitems`는 각 워커가 한다. 워커마다 같은 배정을 계산하므로 xdist
컨트롤러의 "워커 수집 결과 일치" 검사를 그대로 통과한다. 보고서는 한 프로세스만 쓴다(xdist가
없으면 그 프로세스, 있으면 `gw0`). gw0가 죽으면 보고서가 없고, 집계 잡은 그것을 실패로 센다
(fail-closed).

이 파일은 `whymath_backend`를 import하지 않는다 — 테스트 인프라이지 제품 코드가 아니다.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

#: 보고서 형식 판. 필드를 바꾸면 올리고 `backend_shard_verdict.py`의 기대 판도 함께 올린다.
REPORT_SCHEMA = 1

_SHARD_KEY = pytest.StashKey[tuple[int, int]]()


def parse_shard(spec: str) -> tuple[int, int]:
    """`"K/N"`을 (K, N)으로 읽는다. 1 ≤ K ≤ N이 아니면 ValueError."""
    k_raw, sep, n_raw = spec.strip().partition("/")
    if not sep:
        raise ValueError(f"--shard는 'K/N' 형식이어야 한다: {spec!r}")
    try:
        k, n = int(k_raw), int(n_raw)
    except ValueError as exc:
        raise ValueError(f"--shard의 K·N이 정수가 아니다: {spec!r}") from exc
    if n < 1 or not 1 <= k <= n:
        raise ValueError(f"--shard는 1 ≤ K ≤ N이어야 한다: {spec!r}")
    return k, n


def shard_of(path: str, total_shards: int) -> int:
    """파일 경로 → 샤드 번호(1부터). sha256(경로) mod N — 경로 하나만의 함수다."""
    if total_shards < 1:
        raise ValueError(f"샤드 수는 1 이상이어야 한다: {total_shards}")
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest(), 16) % total_shards + 1


def assign_files(paths: Iterable[str], total_shards: int) -> dict[str, int]:
    """파일들 → 샤드 번호. 파일이 적으면 빈 샤드가 생길 수 있다 — 그 샤드는 pytest가 "수집 0건"
    (exit 5)으로 실패하고 집계 판정기도 "배정 0건"으로 잡으므로 조용히 통과하지 않는다."""
    return {p: shard_of(p, total_shards) for p in paths}


def files_digest(paths: Iterable[str]) -> str:
    """파일 경로 집합의 지문 — 순서와 무관(정렬 후 해시)."""
    return hashlib.sha256("\n".join(sorted(set(paths))).encode("utf-8")).hexdigest()


def file_of(nodeid: str) -> str:
    """노드 ID에서 파일 부분만(rootdir 기준 상대 경로 — 머신과 무관하다)."""
    return nodeid.split("::", 1)[0]


def build_report(
    shard: int, total_shards: int, item_counts: Mapping[str, int], assignment: Mapping[str, int]
) -> dict[str, Any]:
    """샤드 하나의 배정 보고서(집계 잡이 완전성을 검사하는 입력)."""
    mine = sorted(p for p, s in assignment.items() if s == shard)
    return {
        "schema": REPORT_SCHEMA,
        "shard": shard,
        "total_shards": total_shards,
        "total_items": sum(item_counts.values()),
        "total_files": len(item_counts),
        "files_digest": files_digest(item_counts),
        "selected_items": sum(item_counts[p] for p in mine),
        "selected_files": mine,
    }


def _is_reporting_process(config: pytest.Config) -> bool:
    workerinput = getattr(config, "workerinput", None)
    return workerinput is None or workerinput.get("workerid") == "gw0"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("whymath-shard", "잡 단위 샤딩 (OPS-83)")
    group.addoption(
        "--shard",
        default=None,
        metavar="K/N",
        help="수집 결과를 파일 단위로 N개로 나눠 K번째 몫만 실행한다.",
    )
    group.addoption(
        "--shard-report",
        default=None,
        metavar="PATH",
        help="배정 보고서(JSON) 경로 — 집계 잡이 샤드 완전성을 검사하는 입력.",
    )


def pytest_configure(config: pytest.Config) -> None:
    spec = config.getoption("--shard")
    report = config.getoption("--shard-report")
    if spec is None:
        if report is not None:
            raise pytest.UsageError("--shard-report는 --shard와 함께만 쓸 수 있다.")
        return
    if report is None:
        # 보고서 없는 샤드는 완전성을 증명할 수 없다 — 조용히 돌게 두지 않는다.
        raise pytest.UsageError("--shard를 쓰면 --shard-report도 지정해야 한다(완전성 증거).")
    try:
        config.stash[_SHARD_KEY] = parse_shard(spec)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """마커 선택(`-m`)·다른 수집 훅이 끝난 *뒤의* 항목을 우주로 삼아 자기 몫만 남긴다."""
    shard_spec = config.stash.get(_SHARD_KEY, None)
    if shard_spec is None:
        return
    shard, total = shard_spec
    counts = Counter(file_of(item.nodeid) for item in items)
    assignment = assign_files(counts, total)
    selected = [item for item in items if assignment[file_of(item.nodeid)] == shard]
    deselected = [item for item in items if assignment[file_of(item.nodeid)] != shard]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected

    if _is_reporting_process(config):
        path = Path(str(config.getoption("--shard-report")))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(
            json.dumps(build_report(shard, total, counts, assignment), ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
