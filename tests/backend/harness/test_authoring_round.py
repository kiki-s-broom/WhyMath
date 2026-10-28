"""저작 회차 오케스트레이터 — 단계 흐름·이어하기·거부 가드·실패 출력 (EOS-208 ⑥).

정본: `harness/authoring_round.py`. 외부 경계는 이렇게 둔다:

- **git은 진짜다** — tmp_path에 저장소·bare 원격·연결 워크트리(`git worktree add --detach`)를 만들어
  deliver의 커밋·push·원격 대조를 실물로 검증한다(가짜 git은 '원격 브랜치 기존재'·'산출물 밖 변경'
  판정의 변별력을 증명하지 못한다).
- **파이썬 자식 프로세스는 가짜다** — 저작 CLI·탐침·감사·검수·HIT·주간 KPI를 모듈 이름으로 가로채
  산출 파일 형태만 흉내 낸다(라이브 LLM·Ollama·창 없음 — CI 헤드리스).
- 검수 흉내는 진짜 `review_session.open_review_item`/`close_review_item`으로 기록한다 — 판정 수 대조가
  실제 이벤트·판정 형식 위에서 돈다.

각 거부 가드는 "그 가드가 없으면 실패하는" 반례 테스트를 가진다(뮤테이션 RED 확인은 PR 보고 참조).
"""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import authoring_round as ar
from whymath_backend.harness.authoring_round_config import parse_round_config
from whymath_backend.harness.authoring_round_ports import RunResult, SubprocessRunner
from whymath_backend.harness.review_session import (
    close_review_item,
    load_review_items,
    open_review_item,
)

_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_SEED_REL = "data/corpus/seed_bank/problems.jsonl"


# ── 실물 git 워크트리 ──────────────────────────────────────────────────────


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout.strip()


@dataclass
class Repo:
    main: Path
    origin: Path
    wt: Path


def _make_repo(tmp_path: Path) -> Repo:
    main = tmp_path / "main"
    origin = tmp_path / "origin.git"
    wt = tmp_path / "wt"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "kiki@example.invalid")
    _git(main, "config", "user.name", "kiki")
    _git(main, "config", "commit.gpgsign", "false")
    (main / "README.md").write_text("repo\n", encoding="utf-8")
    seed = main / _SEED_REL
    seed.parent.mkdir(parents=True)
    seed.write_text('{"slug": "seed-1"}\n', encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "init")
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(main, "remote", "add", "origin", str(origin))
    _git(main, "push", "-q", "origin", "main")
    _git(main, "fetch", "-q", "origin")
    _git(main, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    return Repo(main=main, origin=origin, wt=wt)


# ── 가짜 자식 프로세스 ──────────────────────────────────────────────────────


@dataclass
class World:
    """가짜 자식 프로세스의 상태·조절 손잡이."""

    wt: Path
    probe_overrides: dict[str, Any] = field(default_factory=dict)
    accept: Callable[[str, int], int] = lambda seat, n: n  # 좌석·시도 수 → 수용 수
    author_exit_override: int | None = None
    author_stderr: str = ""
    author_writes_ledger: bool = True
    drop_seed: bool = False
    review_limit: int | None = None  # 이번 검수 실행에서 판정할 최대 건수(None=전부)
    probe_exit: int = 0
    probe_stderr: str = ""
    calls: list[list[str]] = field(default_factory=list)
    counter: int = 0

    def module_calls(self, module: str) -> list[list[str]]:
        return [c for c in self.calls if len(c) > 2 and c[1] == "-m" and c[2] == module]


def _arg(argv: Sequence[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


def _append(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _fake_probe(world: World, argv: Sequence[str], env: Mapping[str, str]) -> RunResult:
    if world.probe_exit != 0:
        return RunResult(world.probe_exit, "", world.probe_stderr)
    src = world.wt / "src" / "backend" / "whymath_backend" / "harness"
    result: dict[str, Any] = {
        "accumulate_file": str(src / "problem_corpus_accumulate.py"),
        "probe_file": str(src / "authoring_round_probe.py"),
        "cli_flags_missing": [],
        # 타임아웃은 *주입된 환경변수*를 그대로 읽는다 — 실제 탐침이 Settings()로 읽는 것과 같다.
        "ollama_request_timeout_s": float(env.get("WHYMATH_OLLAMA_REQUEST_TIMEOUT_S", "30")),
        "ollama_host": "http://127.0.0.1:11434",
        "spec_ids": [],
        "subject": "미적분",
        "slug_prefix": "wm-gen-calc1",
        "errors": {},
    }
    plan = _arg(argv, "--spec-plan")
    if plan:
        lines = Path(plan).read_text(encoding="utf-8").splitlines()
        result["spec_ids"] = [json.loads(ln)["spec_id"] for ln in lines if ln.strip()]
    if "--local-tier" in argv:
        result.update(local_model="qwen3:30b-a3b", local_only=True, local_cost_tier="local")
    if "--cloud-subscription" in argv:
        result.update(
            cloud_seat="openrouter",
            cloud_pin_mid="deepseek/deepseek-v4.1-flash",
            cloud_jurisdiction="us",
            anthropic_api_enabled=False,
            anthropic_configured=False,
            key_length=40,
            key_shape_ok=True,
            cloud_reach_paid=True,
        )
    if "--check-tk" in argv:
        result["tk_ok"] = True
    result.update(world.probe_overrides)
    return RunResult(0, json.dumps(result, ensure_ascii=False), "")


def _fake_author(world: World, argv: Sequence[str]) -> RunResult:
    out = Path(str(_arg(argv, "--out")))
    n = int(str(_arg(argv, "--n")))
    cloud = "--subscription" in argv
    seat = out.parent.name
    k = min(n, world.accept(seat, n))
    cu_rows: list[dict[str, Any]] = []
    gen_rows: list[dict[str, Any]] = []
    stamp = (_NOW + timedelta(minutes=world.counter)).isoformat()
    for i in range(n):
        world.counter += 1
        slug = f"wm-gen-calc1-{seat}-{world.counter:04d}"
        ok = i < k
        gen_rows.append(
            {
                "cu_slug": slug if ok else None,
                "success": ok,
                "model_name": "deepseek/deepseek-v4.1-flash" if cloud else "qwen3:30b-a3b",
                "prompt_version": "l3.equivalent@sha256:test",
                "seed": None if (cloud or world.drop_seed) else 7,
                "input_sha256": "sha256:in",
                "cost_usd": 0.001 if cloud else 0.0,
                "generated_at": stamp,
            }
        )
        if ok:
            cu_rows.append({"slug": slug, "subject": "미적분", "license": "WHYMATH_GENERATED"})
    if cu_rows:
        _append(out, cu_rows)
    _append(out.with_suffix(".genlog.jsonl"), gen_rows)
    if world.author_writes_ledger:
        _append(
            out.with_suffix(".rounds.jsonl"),
            [{"attempted": n, "accepted": k, "appended": k, "recorded_at": stamp}],
        )
    code = world.author_exit_override
    if code is None:
        code = 0 if k > 0 else 1
    report = {"outcome_counts": {"accepted_stored": k, "generation_failed": n - k}}
    return RunResult(code, json.dumps(report), world.author_stderr)


def _fake_review(world: World, argv: Sequence[str]) -> RunResult:
    queue = Path(str(_arg(argv, "--queue")))
    events = Path(str(_arg(argv, "--events")))
    verdicts = Path(str(_arg(argv, "--verdicts")))
    items, _ = load_review_items(queue)
    done: set[str] = set()
    if events.exists():
        for ln in events.read_text(encoding="utf-8").splitlines():
            row = json.loads(ln)
            if row.get("event_type") == "finished":
                done.add(row["cu_slug"])
    ticks = [0]

    def mono() -> int:
        ticks[0] += 60_000_000_000  # 건당 60초 — HIT 하한 가드(30초) 위
        return ticks[0]

    judged = 0
    for item in items:
        if item.slug in done:
            continue
        if world.review_limit is not None and judged >= world.review_limit:
            break
        opened = open_review_item(
            item, events_path=events, reviewer_id="kiki", monotonic_ns=mono, now_utc=lambda: _NOW
        )
        close_review_item(
            opened,
            action="approved",
            failure_code=None,
            note=None,
            events_path=events,
            verdicts_path=verdicts,
            reviewer_id="kiki",
            monotonic_ns=mono,
            now_utc=lambda: _NOW,
        )
        judged += 1
    return RunResult(0, "", "")


class FakeRunner:
    """git은 진짜로, 파이썬 자식은 가짜로."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.real = SubprocessRunner()

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
        mode: str = "capture",
    ) -> RunResult:
        assert timeout_s > 0  # 모든 외부 호출에 타임아웃이 실린다
        if argv[0] == "git":
            return self.real.run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
        self.world.calls.append(list(argv))
        module = argv[2]
        if module == "whymath_backend.harness.authoring_round_probe":
            return _fake_probe(self.world, argv, env)
        if module == "whymath_backend.harness.problem_corpus_accumulate":
            return _fake_author(self.world, argv)
        if module == "whymath_backend.ops.provenance_audit":
            return RunResult(0, "", "")
        if module in (
            "whymath_backend.harness.review_session_gui",
            "whymath_backend.harness.review_session",
        ):
            assert mode == "inherit"  # 대화형 창은 화면을 그대로 물려받는다
            return _fake_review(self.world, argv)
        if module == "whymath_backend.ops.hit_cu_metrics":
            report = {
                "cu_measured": 3,
                "hit_median_seconds": 60.0,
                "hit_implausible_majority": False,
                "cu_with_cost": 3,
                "cost_usd_complete_total": 0.003,
                "coverage_rate": 1.0,
            }
            return RunResult(0, json.dumps(report), "")
        if module == "whymath_backend.ops.weekly_metrics_report":
            rec = {
                "week_start": _arg(argv, "--week-start"),
                "week_end": _arg(argv, "--week-end"),
                "kpis": {
                    "hit_seconds": {"measured": True, "value": 60.0, "reason": None},
                    "unit_cost_krw": {"measured": True, "value": 1.5, "reason": None},
                },
            }
            return RunResult(0, json.dumps(rec), "")
        raise AssertionError(f"예상 밖 자식 프로세스: {argv}")


class FakeHttp:
    def __init__(self, models: Sequence[str] = ("qwen3:30b-a3b",), error: Exception | None = None):
        self.models = models
        self.error = error

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        assert timeout_s > 0
        if self.error is not None:
            raise self.error
        return {"models": [{"name": m} for m in self.models]}


class FixedClock:
    def now(self) -> datetime:
        return _NOW


# ── 회차 조립 ──────────────────────────────────────────────────────────────


def _config_dict(wt: Path, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "round_name": "t1",
        "task_id": "EOS-208",
        "worktree": str(wt),
        "output_root": "data/runs",
        "ollama_request_timeout_s": 180,
        "seats": [
            {
                "name": "local",
                "kind": "local",
                "model": "qwen3:30b-a3b",
                "authoring_tier": "quality",
                "target_cu": 3,
                "attempt_budget": 10,
            },
            {
                "name": "openrouter",
                "kind": "cloud",
                "provider": "openrouter",
                "model": "deepseek/deepseek-v4.1-flash",
                "subscription": "premium",
                "budget_krw": 5000,
                "expected_jurisdiction": "us",
                "target_cu": 3,
                "attempt_budget": 10,
            },
        ],
        "anchors": [
            {
                "spec_id": "a",
                "standard_code": "[12미적Ⅰ-02-05]",
                "difficulty": 2.5,
                "topic_hint": "x",
            },
            {
                "spec_id": "b",
                "standard_code": "[12미적Ⅰ-02-07]",
                "difficulty": 3.0,
                "topic_hint": "y",
            },
        ],
        "seeds": [_SEED_REL],
        "authoring_args": {"avoid_recent": 10, "canary": 0, "abort_window": 0},
        "expected_subject": "미적분",
        "expected_slug_prefix": "wm-gen-calc1",
        "min_queue_cu": 3,
        "review": {"reviewer_id": "kiki", "ui": "gui"},
        "deliver": {"branch": "round/t1-output", "commit_message": "EOS-208: 테스트 회차 산출물"},
    }
    data.update(over)
    return data


@dataclass
class Harness:
    repo: Repo
    world: World
    out: io.StringIO
    cfg_path: Path
    module_file: Path
    http: FakeHttp

    def make(
        self, *, dry_run: bool = False, data: dict[str, Any] | None = None
    ) -> ar.AuthoringRound:
        if data is not None:
            self.cfg_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        raw = self.cfg_path.read_bytes()
        cfg = parse_round_config(
            json.loads(raw.decode("utf-8")), source_path=self.cfg_path, source_sha256="0" * 64
        )
        io_ = ar.Boundaries(
            runner=FakeRunner(self.world),  # type: ignore[arg-type]
            http=self.http,
            clock=FixedClock(),
            python="python",
            out=self.out,
            module_file=self.module_file,
        )
        return ar.AuthoringRound(cfg, io_, dry_run=dry_run)

    def run(self, **kw: Any) -> int:
        dry = kw.pop("dry_run", False)
        return self.make(dry_run=dry).run(**kw)

    @property
    def text(self) -> str:
        return self.out.getvalue()

    def runs(self) -> Path:
        return self.repo.wt / "data" / "runs"


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    repo = _make_repo(tmp_path)
    cfg_path = tmp_path / "round.yaml"  # 워크트리 밖(설정 파일 수정이 산출물 밖 변경이 되지 않게)
    cfg_path.write_text(json.dumps(_config_dict(repo.wt), ensure_ascii=False), encoding="utf-8")
    module_file = repo.wt / "src" / "backend" / "whymath_backend" / "harness" / "authoring_round.py"
    return Harness(
        repo=repo,
        world=World(wt=repo.wt),
        out=io.StringIO(),
        cfg_path=cfg_path,
        module_file=module_file,
        http=FakeHttp(),
    )


def _remote_has_branch(repo: Repo, branch: str) -> bool:
    return bool(_git(repo.main, "ls-remote", "--heads", "origin", branch))


# ── 전체 흐름·이어하기 ──────────────────────────────────────────────────────


def test_full_round_runs_every_stage_and_pushes_verified(h: Harness) -> None:
    code = h.run()
    assert code == 0, h.text
    for stage in ar.STAGES:
        assert f"STAGE_END stage={stage} status=done" in h.text
    assert "PUSH_VERIFIED=True" in h.text
    assert "ROUND_STATUS=complete" in h.text
    assert _remote_has_branch(h.repo, "round/t1-output")
    # 커밋된 파일은 전부 이 회차 폴더 안이다.
    _git(h.repo.main, "fetch", "-q", "origin")
    files = _git(h.repo.main, "show", "--name-only", "--format=", "origin/round/t1-output")
    assert files and all(f.startswith("data/runs/t1-") for f in files.splitlines())
    # 한국어 요약 줄과 기계 판정 줄이 함께 나온다.
    assert "▶ 검수 완주" in h.text
    assert "QUEUE_WRITTEN=True QUEUE_LINES=12" in h.text


def test_author_child_gets_timeout_env_and_worktree_pythonpath(h: Harness) -> None:
    seen: list[Mapping[str, str]] = []
    runner_run = FakeRunner.run

    def spy(self: FakeRunner, argv: Sequence[str], **kw: Any) -> RunResult:
        if argv[0] != "git":
            seen.append(kw["env"])
        return runner_run(self, argv, **kw)

    FakeRunner.run = spy  # type: ignore[method-assign]
    try:
        assert h.run(only="author-local") == 0, h.text
    finally:
        FakeRunner.run = runner_run  # type: ignore[method-assign]
    assert seen
    for env in seen:
        assert env["WHYMATH_OLLAMA_REQUEST_TIMEOUT_S"] == "180.0"
        assert env["PYTHONPATH"] == str(h.repo.wt / "src" / "backend")


def test_resume_skips_finished_write_stages_and_continues_review(h: Harness) -> None:
    h.world.review_limit = 11  # 12건 중 11건만 판정하고 창을 닫았다
    assert h.run() == 1
    assert "REVIEW_JUDGED=11 QUEUE_LINES=12 REVIEW_DONE=False" in h.text
    assert "ROUND_STATUS=incomplete NEXT_STAGE=review" in h.text
    assert not _remote_has_branch(h.repo, "round/t1-output")
    author_calls = len(h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate"))

    h.world.review_limit = None
    h.out.truncate(0)
    h.out.seek(0)
    assert h.run() == 0, h.text
    assert "RESUME_FROM=review" in h.text
    assert "STAGE_SKIP stage=author-local" in h.text
    assert "STAGE_SKIP stage=queue" in h.text
    # 저작은 다시 부르지 않았다(실물 완료 — 과금 0).
    assert len(h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")) == (
        author_calls
    )
    assert "PUSH_VERIFIED=True" in h.text


def test_budget_exhausted_seat_continues_and_raised_budget_resumes(h: Harness) -> None:
    h.world.accept = lambda seat, n: 1 if seat.endswith("local") else n  # 로컬 수용률 낮음
    data = _config_dict(h.repo.wt)
    data["seats"][0]["target_cu"] = 5
    data["seats"][0]["attempt_budget"] = 6
    h.make(data=data)
    assert h.run(only="author-local") == 0, h.text
    assert "outcome=budget_exhausted" in h.text
    tried_1 = sum(
        int(str(_arg(c, "--n")))
        for c in h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")
    )
    assert tried_1 == 6  # 예산을 정확히 다 쓰고 넘지 않는다
    # 설정에서 예산을 올리고 다시 실행하면 남은 예산으로 이어서 저작한다.
    data["seats"][0]["attempt_budget"] = 12
    h.make(data=data)
    assert h.run(only="author-local") == 0, h.text
    tried_2 = sum(
        int(str(_arg(c, "--n")))
        for c in h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")
    )
    assert 6 < tried_2 <= 12


# ── 거부 가드(각각 반례 동반) ─────────────────────────────────────────────


def _prepare_reviewed(h: Harness, *, judge: int | None) -> None:
    """저작·큐까지 돌리고 검수를 judge건만 한다(deliver 거부 시험의 공통 준비)."""
    h.world.review_limit = judge
    h.run()
    h.out.truncate(0)
    h.out.seek(0)


def test_deliver_refused_when_judged_less_than_queue(h: Harness) -> None:
    _prepare_reviewed(h, judge=11)  # 29/30 축소판 — 12건 중 11건
    assert h.run(only="deliver") == 1
    assert "WRITE_REFUSED=True stage=deliver" in h.text
    assert "REVIEW_COMPLETE=False" in h.text
    assert not _remote_has_branch(h.repo, "round/t1-output")


def test_deliver_allowed_when_judged_equals_queue(h: Harness) -> None:
    """반례 대조군 — 판정 수 = 큐 행 수면 같은 경로가 push한다."""
    _prepare_reviewed(h, judge=None)
    assert _remote_has_branch(h.repo, "round/t1-output")


def test_deliver_refused_on_change_outside_round_folders(h: Harness) -> None:
    _prepare_reviewed(h, judge=11)
    h.world.review_limit = None
    assert h.run(only="review") == 0
    (h.repo.wt / "README.md").write_text("다른 세션의 수정\n", encoding="utf-8")
    h.out.truncate(0)
    h.out.seek(0)
    assert h.run(only="deliver") == 1
    assert "OTHER_DIRTY_ZERO=False" in h.text
    assert "OTHER_DIRTY_PATHS README.md" in h.text
    assert not _remote_has_branch(h.repo, "round/t1-output")


def test_deliver_allows_modified_config_inside_worktree(h: Harness) -> None:
    """반례 대조군 — 회차 설정 파일 수정(목표·예산 변경)은 산출물 밖 변경으로 세지 않는다."""
    cfg_in = h.repo.wt / "docs" / "round.yaml"
    cfg_in.parent.mkdir(parents=True)
    cfg_in.write_text(h.cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
    h.cfg_path = cfg_in  # 추적되지 않는 새 파일이지만 '허용된 설정 파일'로 분류돼야 한다
    assert h.run() == 0, h.text
    assert "CONFIG_MODIFIED=True" in h.text


def test_deliver_refused_when_remote_branch_exists(h: Harness) -> None:
    _prepare_reviewed(h, judge=11)
    h.world.review_limit = None
    assert h.run(only="review") == 0
    _git(h.repo.main, "push", "-q", "origin", "main:refs/heads/round/t1-output")
    h.out.truncate(0)
    h.out.seek(0)
    assert h.run(only="deliver") == 1
    assert "REMOTE_BRANCH_ABSENT=False" in h.text
    assert "LOCAL_SHA=" not in h.text  # 커밋 단계에 들어가지 않았다


def test_cloud_budget_never_exceeded_even_with_zero_acceptance(h: Harness) -> None:
    h.world.accept = lambda seat, n: 0
    data = _config_dict(h.repo.wt)
    data["seats"][1]["attempt_budget"] = 7
    data["seats"][1]["target_cu"] = 15
    h.make(data=data)
    assert h.run(only="author-cloud") == 0, h.text
    calls = h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")
    assert sum(int(str(_arg(c, "--n"))) for c in calls) == 7
    assert "outcome=budget_exhausted" in h.text


def test_reserved_attempts_count_against_budget_without_ledger(h: Harness) -> None:
    """중단된 회차(대장 미기록)의 예약분도 소진으로 센다 — 재실행이 같은 예산을 다시 쓰지 않는다."""
    state = h.runs() / "t1-review" / "round_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "round_name": "t1",
                "stages": {},
                "seats": {"openrouter": {"reserved_attempts": 10}},
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    assert h.run(only="author-cloud") == 0, h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []
    assert "outcome=budget_exhausted" in h.text


def test_refused_when_module_not_from_worktree(h: Harness) -> None:
    h.module_file = h.repo.main / "src" / "backend" / "whymath_backend" / "harness" / "x.py"
    assert h.run() == 1
    assert "CODE_FROM_WORKTREE=False" in h.text
    assert "WRITE_REFUSED=True stage=preflight" in h.text
    assert not (h.runs() / "t1-review" / "round_state.json").exists()  # 상태 파일도 안 쓴다
    assert h.world.calls == []


def test_refused_when_child_imports_code_outside_worktree(h: Harness) -> None:
    h.world.probe_overrides = {"accumulate_file": str(h.repo.main / "acc.py")}
    assert h.run() == 1
    assert "CHILD_CODE_FROM_WORKTREE=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []


def test_refused_when_not_isolated_worktree(h: Harness) -> None:
    data = _config_dict(h.repo.main)  # 평소 클론(.git이 디렉터리)
    h.module_file = h.repo.main / "src" / "backend" / "m.py"
    h.make(data=data)
    assert h.run() == 1
    assert "WORKTREE_ISOLATED=False" in h.text


def test_refused_when_openrouter_key_missing(h: Harness) -> None:
    h.world.probe_overrides = {"key_shape_ok": False, "key_length": 0}
    assert h.run(only="author-cloud") == 1
    assert "OPENROUTER_KEY_SHAPE_OK=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []
    assert "sk-or-" not in h.text.replace("sk-or- 시작", "")  # 키 값·접두 노출 없음


def test_refused_when_timeout_not_injected(h: Harness) -> None:
    h.world.probe_overrides = {"ollama_request_timeout_s": 30.0}  # 기본값 — 주입이 안 닿음
    assert h.run(only="author-local") == 1
    assert "LOCAL_TIMEOUT_INJECTED=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []


def test_refused_when_router_picks_other_local_model(h: Harness) -> None:
    h.world.probe_overrides = {"local_model": "qwen2.5:7b"}  # authoring_tier 기본값(mid)의 핀
    assert h.run(only="author-local") == 1
    assert "LOCAL_MODEL_ROUTED=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []


def test_refused_when_local_seat_could_reach_cloud(h: Harness) -> None:
    h.world.probe_overrides = {"local_only": False}  # 신호 없는 저작이 클라우드에 닿는다(유료 위험)
    assert h.run(only="author-local") == 1
    assert "LOCAL_LOCAL_ONLY=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []


def test_refused_when_ollama_model_absent(h: Harness) -> None:
    h.http = FakeHttp(models=("qwen2.5:7b",))
    assert h.run(only="author-local") == 1
    assert "LOCAL_OLLAMA_MODEL_PRESENT=False" in h.text


def test_refused_author_when_queue_already_exists(h: Harness) -> None:
    queue = h.runs() / "t1-review" / "canary_review_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text('{"slug": "x"}\n', encoding="utf-8")
    assert h.run(only="author-local") == 1
    assert "QUEUE_ABSENT=False" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []


def test_refused_when_spec_plan_changed_mid_round(h: Harness) -> None:
    h.world.accept = lambda seat, n: 1
    data = _config_dict(h.repo.wt)
    data["seats"][0]["target_cu"] = 50
    data["seats"][0]["attempt_budget"] = 5
    h.make(data=data)
    assert h.run(only="author-local") == 0
    data["seats"][0]["attempt_budget"] = 10
    data["anchors"][0]["topic_hint"] = "바뀐 힌트"
    h.make(data=data)
    assert h.run(only="author-local") == 1
    assert "SPEC_PLAN_UNCHANGED=False" in h.text


def test_queue_refused_when_queue_exists_and_not_overwritten(h: Harness) -> None:
    assert h.run(only="author-local") == 0
    assert h.run(only="author-cloud") == 0
    assert h.run(only="queue") == 0
    queue = h.runs() / "t1-review" / "canary_review_queue.jsonl"
    before = queue.read_bytes()
    assert h.run(only="queue") == 1
    assert "QUEUE_ABSENT=False" in h.text
    assert queue.read_bytes() == before


# ── 실패 출력(침묵 실패 금지) ─────────────────────────────────────────────


def test_author_exit2_stops_with_stage_and_cause(h: Harness) -> None:
    h.world.author_exit_override = 2
    h.world.author_stderr = "[알람] 연속 무진전 3회차"
    assert h.run(only="author-local") == 1
    assert "STAGE_FAILED stage=author-local error=RoundStopped" in h.text
    assert "연속 무진전 3회차" in h.text
    assert len(h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")) == 1


def test_author_without_ledger_is_abnormal_and_stops(h: Harness) -> None:
    """대장 없이 끝난 실행(임포트 실패 등)을 예산이 바닥날 때까지 반복하지 않는다."""
    h.world.author_writes_ledger = False
    h.world.author_exit_override = 1
    h.world.author_stderr = "ModuleNotFoundError: No module named 'x'"
    assert h.run(only="author-local") == 1
    assert "LedgerNotWritten" in h.text
    assert "ModuleNotFoundError" in h.text
    assert len(h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate")) == 1


def test_probe_failure_reports_exception_type(h: Harness) -> None:
    h.world.probe_exit = 1
    h.world.probe_stderr = "Traceback ...\nImportError: cannot import name 'resolve_model'"
    assert h.run() == 1
    assert "STAGE_FAILED stage=preflight error=ProbeFailed" in h.text
    assert "ImportError" in h.text


def test_ollama_unreachable_names_exception_type(h: Harness) -> None:
    h.http = FakeHttp(error=ConnectionRefusedError("refused"))
    assert h.run(only="author-local") == 1
    assert "OLLAMA_REACHABLE=False error=ConnectionRefusedError" in h.text


# ── 상태 파일·드라이런·요약 ───────────────────────────────────────────────


def test_state_mismatch_warns_and_uses_real_artifacts(h: Harness) -> None:
    state = h.runs() / "t1-review" / "round_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "round_name": "t1",
                "stages": {"queue": {"status": "done"}},
                "seats": {},
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    h.run(dry_run=True)
    assert "STATE_MISMATCH stage=queue state=done real=incomplete" in h.text


def test_dry_run_writes_nothing(h: Harness) -> None:
    assert h.run(dry_run=True) == 1
    assert "DRY_RUN_PLAN stage=author-local seat=local" in h.text
    assert h.world.module_calls("whymath_backend.harness.problem_corpus_accumulate") == []
    assert not h.runs().exists()


def test_summarize_prints_hit_and_weekly_preview(h: Harness) -> None:
    assert h.run() == 0
    assert "HIT_LOCAL_EXIT=0 CU_MEASURED=3" in h.text
    assert "HIT_OPENROUTER_EXIT=0" in h.text
    assert "PREVIEW_HIT_SECONDS_MEASURED=True" in h.text
    assert "PREVIEW_ONLY=True LEDGER_WRITTEN=False" in h.text
    weekly = h.world.module_calls("whymath_backend.ops.weekly_metrics_report")[0]
    assert "--dry-run" in weekly and weekly.count("--generation-log-jsonl") == 2


def test_check_fails_when_local_seed_missing(h: Harness) -> None:
    h.world.drop_seed = True  # 로컬 좌석 genlog의 seed를 비운다(G-C는 클라우드만 허용)
    assert h.run() == 1
    assert "CU_MISSING_SEED=6" in h.text
    assert "STAGE_FAILED stage=check error=ArtifactCheckFailed" in h.text
    # 큐는 만들어지지 않았다 — 검사 실패가 다음 쓰기 단계를 막는다.
    assert not (h.runs() / "t1-review" / "canary_review_queue.jsonl").exists()


def test_main_returns_2_on_bad_config(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\nround_name: x\n", encoding="utf-8")
    out = io.StringIO()
    io_ = ar.Boundaries(
        runner=SubprocessRunner(),
        http=FakeHttp(),
        clock=FixedClock(),
        python="python",
        out=out,
        module_file=tmp_path / "m.py",
    )
    assert ar.main(["--config", str(bad)], io=io_) == 2
    assert "CONFIG_ERROR=" in out.getvalue()
