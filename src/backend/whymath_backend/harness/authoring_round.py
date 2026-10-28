"""저작 회차 한 줄 실행 — 런북 [A]~[L] 오케스트레이터 (EOS-208).

무엇을 하는가
-------------
EOS-197 회차(2026-10-27~28)에서 Kiki가 붙여넣기 블록 15개 이상을 손으로 돌리며 겪은 마찰 —
Ollama 기본 타임아웃 30초 공전, 목표 미달 시 블록 재작성 왕복, 판정 29건인데 업로드 시도, 블록 순서
혼동 — 을 없애려고 런북 단계를 CLI 하나로 묶는다. 사람이 하는 일은 **검수**와
(최초 1회) **키 등록**뿐이다.

    python -m whymath_backend.harness.authoring_round --config <회차 설정.yaml>
        [--stage <이름> | --from <이름>] [--dry-run]

단계(런북 블록 대응):
        preflight     [B]~[E]  작업 트리·코드 출처·탐침(라우팅·좌석·키 형태·타임아웃)·모델
        author-local  [F]      로컬 좌석 저작 — 목표 CU 또는 시도 예산 소진까지 회차를 덧붙인다
        author-cloud  [G]      유료 좌석 저작 — 같은 규칙 · 시도 예산 상한 필수
        check         [H]      산출물·GenerationLog 4필드·과목/slug·provenance_audit
        queue         [I]      좌석 번갈아 섞은 검수 큐(slug 중복 제외 · 덮어쓰지 않음)
        review        [J-G]    검수 창(대화형) — 끝나면 판정 수를 큐 행 수와 대조
        summarize     [K]      HIT·비용·주간 KPI 미리보기(파일 입력 모드 · 원장 미기록)
        deliver       [L]      산출물 브랜치 커밋·push·원격 대조

인자 없이(`--stage`·`--from` 없이) 실행하면 처음부터 훑되 **실물로 끝난 쓰기 단계는 건너뛴다** —
중간에 멈추거나 창을 닫아도 같은 한 줄을 다시 붙여넣으면 이어서 간다. 완료 판정은 상태 파일이 아니라
산출물 실재·행 수·원격 대조로 한다(상태 파일과 실물이 다르면 실물 기준 + `STATE_MISMATCH` 경고).
읽기 전용 단계(preflight·check·summarize)는 매번 다시 계산한다(멱등·저렴).

안전(acceptance ④) — 쓰기 단계는 실행 직전에 선행 조건을 **스스로 다시 계산해 거부**한다
(출력은 흐름을 멈추지 못한다 — HARN-106 교훈). 거부하면 무엇이 False인지 `WRITE_REFUSED=True`
줄에 적고 exit 1. 코드 출처는 이 모듈과 자식 프로세스가 실제로 import한 파일 경로로 대조한다.
시크릿은 길이·형태 불리언 외에는 출력하지 않는다. 실패는
`STAGE_FAILED stage=… error=<예외 타입명>`과
원인(stderr 꼬리·HTTP 본문 요약)을 남긴다(침묵 실패 금지).

로직 복제 금지(과공학 방지): 저작·검수·HIT·주간 KPI·감사는 **기존 CLI를 자식 프로세스로** 부른다.
여기서 직접 계산하는 것은 런북 블록에 인라인으로 있던 것뿐이다 — 좌석 산출물 4필드 계수([H])·검수
큐 조립([I])·집계 창 계산([K]).

종료 코드: 0 요청한 단계 전부 완료 / 1 거부·실패·미완(검수 남음 등) / 2 설정·인자 오류.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from whymath_backend.harness.authoring_round_config import (
    RoundConfig,
    RoundConfigError,
    SeatConfig,
    load_round_config,
)
from whymath_backend.harness.authoring_round_ports import (
    Clock,
    HttpGetJson,
    ProcessRunner,
    RunMode,
    RunResult,
    SubprocessRunner,
    SystemClock,
    UrllibHttp,
    mask_secrets,
)

STAGES: tuple[str, ...] = (
    "preflight",
    "author-local",
    "author-cloud",
    "check",
    "queue",
    "review",
    "summarize",
    "deliver",
)
# 실물로 완료를 판정해 건너뛸 수 있는 쓰기 단계. 나머지(읽기 전용)는 매번 다시 계산한다.
WRITE_STAGES: frozenset[str] = frozenset(
    {"author-local", "author-cloud", "queue", "review", "deliver"}
)
STAGE_KIND = {"author-local": "local", "author-cloud": "cloud"}

# 회차 크기 규칙(런북 [F]·[G]): min(남은 예산, max(5, min(20, (목표 − 현재 행 수) × 2)))
ROUND_MIN = 5
ROUND_MAX = 20

_GIT_TIMEOUT_S = 60.0
_GIT_PUSH_TIMEOUT_S = 300.0
_PROBE_TIMEOUT_S = 180.0
_METRICS_TIMEOUT_S = 300.0
_HTTP_TIMEOUT_S = 10.0
_STATE_SCHEMA = 1


class StageRefusedError(Exception):
    """선행 조건 재검사 불통과 — 아무것도 쓰지 않았다."""

    def __init__(self, stage: str, checks: Mapping[str, object], hint: str) -> None:
        self.stage = stage
        self.checks = dict(checks)
        self.hint = hint
        super().__init__(stage)


class StageFailedError(Exception):
    """실행했지만 실패했다 — 원인(예외 타입명·stderr 꼬리)을 담는다."""

    def __init__(self, stage: str, error: str, cause: str) -> None:
        self.stage = stage
        self.error = error
        self.cause = cause
        super().__init__(f"{stage}: {error}")


@dataclass
class StageOutcome:
    status: str  # done | incomplete
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Boundaries:
    """외부 경계 묶음 — 테스트는 가짜를 넣는다."""

    runner: ProcessRunner
    http: HttpGetJson
    clock: Clock
    python: str
    out: TextIO
    module_file: Path


def default_boundaries() -> Boundaries:
    return Boundaries(
        runner=SubprocessRunner(),
        http=UrllibHttp(),
        clock=SystemClock(),
        python=sys.executable,
        out=sys.stdout,
        module_file=Path(__file__).resolve(),
    )


# ── 순수 헬퍼 ──────────────────────────────────────────────────────────────


def is_under(child: Path | str, parent: Path | str) -> bool:
    """`child`가 `parent` 아래(같음 포함)인가 — Windows 대소문자·구분자 차이를 정규화해 비교한다."""
    c = os.path.normcase(os.path.abspath(str(child)))
    p = os.path.normcase(os.path.abspath(str(parent)))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False  # 다른 드라이브(C: vs D:) — 아래일 수 없다


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL을 읽는다. 파일이 없으면 빈 목록. 깨진 줄은 숨기지 않고 예외로 올린다."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{n}: {type(exc).__name__}") from exc
        if isinstance(row, dict):
            rows.append(row)
        else:
            raise ValueError(f"{path.name}:{n}: TypeError(not a JSON object)")
    return rows


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())


def next_round_size(lines: int, tried: int, target: int, budget: int) -> int:
    """런북 [F]·[G]의 회차 크기 규칙 — 남은 예산을 절대 넘지 않는다."""
    want = max(ROUND_MIN, min(ROUND_MAX, (target - lines) * 2))
    return max(0, min(budget - tried, want))


def seat_consumption(seat_dir: Path) -> dict[str, int]:
    """좌석 폴더의 시도 소진 **실물 근거** — 상태 파일이 깨지거나 지워져도 여기서 다시 나온다.

    - `ledger_rounds`·`ledger_attempts` — 회차 대장(`cu.rounds.jsonl`)의 회차 수·시도 합. 저작 CLI는
      회차가 정상 종료하면 수용 0건이어도 대장에 1행을 남긴다(`--stagnation-window` 도움말: "회차
      이력은 대장에 항상 적재"). 회차 수가 늘지 않은 실행은 비정상 종료(임포트 실패·강제 종료)다.
    - `unrecorded_calls` — 생성 로그(`cu.genlog.jsonl`, 호출마다 즉시 기록) 중 run_id가 대장에
      **없는** 행 수 = 대장 없이 끊긴 회차(Ctrl+C·타임아웃)가 실제로 한 호출. run_id가 없는 행도
      여기 센다(모르면 소진 쪽으로 — 보수적).
    """
    rounds = read_jsonl(seat_dir / "cu.rounds.jsonl")
    recorded_ids = {str(r.get("run_id")) for r in rounds if r.get("run_id")}
    genlog = read_jsonl(seat_dir / "cu.genlog.jsonl")
    unrecorded = sum(
        1 for g in genlog if not g.get("run_id") or str(g.get("run_id")) not in recorded_ids
    )
    return {
        "ledger_rounds": len(rounds),
        "ledger_attempts": sum(int(r.get("attempted", 0) or 0) for r in rounds),
        "unrecorded_calls": unrecorded,
    }


def seat_artifact_stats(seat_dir: Path) -> dict[str, Any]:
    """좌석 산출물 4필드 계수(런북 [H] `$SeatCheckPy`와 같은 규칙).

    CU 1행마다 그 CU를 만든 성공 생성 호출(`cu_slug`가 같은 genlog 행)을 찾아
    `model_name`·`prompt_version`·`seed`·`input_sha256` 결손을 센다.
    """
    cu = read_jsonl(seat_dir / "cu.jsonl")
    genlog = read_jsonl(seat_dir / "cu.genlog.jsonl")
    ok: dict[str, dict[str, Any]] = {}
    for row in genlog:
        slug = row.get("cu_slug")
        if slug and row.get("success"):
            ok[str(slug)] = row
    missing = {"genlog": 0, "model_name": 0, "prompt_version": 0, "seed": 0, "input_sha256": 0}
    slugs = [str(r.get("slug")) for r in cu]
    for slug in slugs:
        hit = ok.get(slug)
        if hit is None:
            missing["genlog"] += 1
            continue
        for key in ("model_name", "prompt_version", "seed", "input_sha256"):
            if hit.get(key) is None:
                missing[key] += 1
    models = sorted({str(r.get("model_name")) for r in genlog if r.get("success")})
    costs = [r.get("cost_usd") for r in genlog]
    return {
        "cu_lines": len(cu),
        "distinct_slugs": len(set(slugs)),
        "subjects": sorted({str(r.get("subject")) for r in cu}),
        "slugs": slugs,
        "genlog_rows": len(genlog),
        "genlog_success": sum(1 for r in genlog if r.get("success")),
        "models": models,
        "missing": missing,
        "cost_usd_sum": sum(float(c) for c in costs if c is not None),
        "cost_null_rows": sum(1 for c in costs if c is None),
    }


def assemble_queue(seat_rows: Sequence[Sequence[str]]) -> tuple[list[str], int]:
    """좌석 산출물 줄들을 **한 건씩 번갈아** 섞고 같은 slug는 한 번만 싣는다(런북 [I])."""
    out: list[str] = []
    seen: set[str] = set()
    dup = 0
    for raw in itertools.chain.from_iterable(itertools.zip_longest(*seat_rows)):
        if raw is None:
            continue
        slug = json.loads(raw).get("slug")
        if slug in seen:
            dup += 1
            continue
        seen.add(slug)
        out.append(raw)
    return out, dup


def parse_porcelain_z(raw: str) -> list[str]:
    """`git status --porcelain=v1 -z` → 경로 목록(이름 변경은 새 경로·옛 경로 둘 다)."""
    paths: list[str] = []
    parts = raw.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in xy or "C" in xy:
            if i < len(parts) and parts[i]:
                paths.append(parts[i])
            i += 1
    return paths


def last_json_object(text: str) -> dict[str, Any] | None:
    """stdout에서 마지막 JSON 객체를 찾는다(앞에 진행 로그가 섞여도 리포트를 읽는다)."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.rfind("\n{")
    while start != -1:
        try:
            value = json.loads(stripped[start + 1 :])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            start = stripped.rfind("\n{", 0, start)
    if stripped.startswith("{"):
        try:
            value = json.loads(stripped)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


# ── 오케스트레이터 ─────────────────────────────────────────────────────────


class AuthoringRound:
    def __init__(self, cfg: RoundConfig, io: Boundaries, *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.io = io
        self.dry_run = dry_run
        self._state_writable = False
        self._state_corrupt = False
        self._lock_path: Path | None = None
        self.state: dict[str, Any] = self._load_state()

    # ── 출력 ──
    def kv(self, line: str) -> None:
        """기계 판정 줄(KEY=VALUE)."""
        print(line, file=self.io.out, flush=True)

    def say(self, text: str) -> None:
        """사람이 읽을 한국어 요약 줄."""
        print(f"▶ {text}", file=self.io.out, flush=True)

    # ── 상태 파일 ──
    def _load_state(self) -> dict[str, Any]:
        path = self.cfg.state_path()
        base: dict[str, Any] = {
            "schema_version": _STATE_SCHEMA,
            "round_name": self.cfg.round_name,
            "stages": {},
            "seats": {},
            "history": [],
        }
        if not path.exists():
            return base
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # 깨진 상태 파일은 실물 판정으로 대체한다 — 상태 파일은 보조 기록일 뿐이다.
            self.kv(f"STATE_UNREADABLE=True error={type(exc).__name__} — 실물 기준으로 진행")
            self._state_corrupt = True
            return base
        if not isinstance(loaded, dict) or loaded.get("round_name") != self.cfg.round_name:
            self.kv("STATE_UNREADABLE=True error=RoundNameMismatch — 실물 기준으로 진행")
            self._state_corrupt = True
            return base
        for key in ("stages", "seats", "history"):
            loaded.setdefault(key, base[key])
        return loaded

    def _save_state(self) -> bool:
        """상태 파일을 원자적으로 쓴다. 쓰기 실패는 타입명 줄을 내고 False(원시 traceback 금지).

        읽지 못한 상태 파일은 덮어쓰기 전에 `.unreadable-<시각>`으로 옮겨 증거를 남긴다.
        """
        if self.dry_run or not self._state_writable:
            return self.dry_run
        path = self.cfg.state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if self._state_corrupt and path.exists():
                stamp = self.io.clock.now().strftime("%Y%m%dT%H%M%S")
                os.replace(path, path.with_name(f"{path.name}.unreadable-{stamp}"))
                self._state_corrupt = False
            self.state["updated_at"] = self.io.clock.now().isoformat()
            self.state["config_sha256"] = self.cfg.source_sha256
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            self.kv(f"STATE_WRITE_FAILED=True error={type(exc).__name__} path={path}")
            return False
        # 실제로 쓰인 설정을 산출물과 함께 남긴다(설정을 바꿔 재실행해도 무엇으로 돌았는지 남는다).
        snap = self.cfg.review_dir() / "round_config.yaml"
        try:
            src = self.cfg.source_path.read_bytes()
            if not snap.exists() or snap.read_bytes() != src:
                snap.write_bytes(src)
        except OSError as exc:
            self.kv(f"CONFIG_SNAPSHOT_FAILED=True error={type(exc).__name__}")
        return True

    def _record(self, stage: str, status: str, detail: Mapping[str, Any]) -> None:
        now = self.io.clock.now().isoformat()
        self.state["stages"][stage] = {"status": status, "at": now, "detail": dict(detail)}
        self.state["history"].append({"at": now, "stage": stage, "status": status})
        self._save_state()

    def _state_status(self, stage: str) -> str | None:
        entry = self.state.get("stages", {}).get(stage)
        return entry.get("status") if isinstance(entry, dict) else None

    # ── 자식 프로세스 ──
    def child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # PYTHONPATH는 덧붙이지 않고 **교체**한다 — 평소 클론 경로가 앞에 남으면 그쪽이 import된다.
        env["PYTHONPATH"] = str(self.cfg.worktree / "src" / "backend")
        env["WHYMATH_OLLAMA_REQUEST_TIMEOUT_S"] = str(self.cfg.ollama_request_timeout_s)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def run_child(
        self, args: Sequence[str], *, timeout_s: float, mode: RunMode = "capture"
    ) -> RunResult:
        return self.io.runner.run(
            [self.io.python, *args],
            cwd=self.cfg.worktree,
            env=self.child_env(),
            timeout_s=timeout_s,
            mode=mode,
        )

    def git(self, *args: str, timeout_s: float = _GIT_TIMEOUT_S) -> RunResult:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"  # 인증 프롬프트로 무한 대기하지 않는다
        return self.io.runner.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=self.cfg.worktree,
            env=env,
            timeout_s=timeout_s,
        )

    def probe(self, seat: SeatConfig | None, *, check_tk: bool = False) -> dict[str, Any]:
        """탐침을 자식 환경에서 돌린다.

        spec 계획은 설정에서 만든 임시 파일로 준다(준비 점검을 읽기 전용으로 유지).
        """
        with tempfile.TemporaryDirectory(prefix="authoring_round_probe_") as tmp:
            plan = Path(tmp) / "spec_plan.jsonl"
            plan.write_text(self.cfg.spec_plan_text(), encoding="utf-8")
            args = [
                "-m",
                "whymath_backend.harness.authoring_round_probe",
                "--spec-plan",
                str(plan),
            ]
            if seat is not None and seat.kind == "local" and seat.authoring_tier:
                args += ["--local-tier", seat.authoring_tier]
            if seat is not None and seat.kind == "cloud":
                args += [
                    "--cloud-subscription",
                    str(seat.subscription),
                    "--cloud-budget-krw",
                    str(seat.budget_krw),
                ]
            if check_tk:
                args.append("--check-tk")
            result = self.run_child(args, timeout_s=_PROBE_TIMEOUT_S)
        if not result.ok:
            raise StageFailedError("probe", "ProbeFailed", result.failure_reason())
        parsed = last_json_object(result.stdout)
        if parsed is None:
            raise StageFailedError("probe", "ProbeOutputUnreadable", result.stdout.strip()[-200:])
        return parsed

    # ── 공통 가드 ──
    def base_guard(self) -> dict[str, object]:
        """모든 단계 공통 — 이 모듈이 지정 워크트리에서 import됐고 그것이 격리 워크트리인가."""
        wt = self.cfg.worktree
        checks: dict[str, object] = {
            "CODE_FROM_WORKTREE": is_under(self.io.module_file, wt),
            "WORKTREE_EXISTS": wt.is_dir(),
            # 연결 워크트리는 `.git`이 디렉터리가 아니라 파일이다 — 평소 클론에서 돌면 False.
            "WORKTREE_ISOLATED": (wt / ".git").is_file(),
        }
        if all(v is True for v in checks.values()):
            self._state_writable = True
        return checks

    def child_code_checks(self, probe: Mapping[str, Any]) -> dict[str, object]:
        wt = self.cfg.worktree
        acc = probe.get("accumulate_file")
        own = probe.get("probe_file")
        checks: dict[str, object] = {
            "CHILD_CODE_FROM_WORKTREE": bool(
                acc and own and is_under(acc, wt) and is_under(own, wt)
            ),
            "CLI_FLAGS_OK": probe.get("cli_flags_missing") == [],
            "SPEC_PLAN_OK": probe.get("spec_ids") == [a.spec_id for a in self.cfg.anchors],
        }
        if self.cfg.expected_subject is not None:
            checks["SUBJECT_OK"] = probe.get("subject") == self.cfg.expected_subject
        if self.cfg.expected_slug_prefix is not None:
            checks["SLUG_PREFIX_OK"] = probe.get("slug_prefix") == self.cfg.expected_slug_prefix
        return checks

    def seeds_check(self) -> dict[str, object]:
        missing = [s for s in self.cfg.seeds if not (self.cfg.worktree / s).is_file()]
        return {"SEEDS_PRESENT": not missing, "SEEDS_MISSING": len(missing)}

    def seat_checks(self, seat: SeatConfig, probe: Mapping[str, Any]) -> dict[str, object]:
        """좌석별 판정(런북 [C]·[D]). 값은 bool/숫자/짧은 문자열만 — 시크릿은 싣지 않는다."""
        p = seat.name.upper().replace("-", "_")
        if seat.kind == "local":
            checks: dict[str, object] = {
                # 타임아웃 주입이 자식에게 실제로 닿았는가(EOS-197 30초 공전 재발 방지).
                f"{p}_TIMEOUT_INJECTED": probe.get("ollama_request_timeout_s")
                == self.cfg.ollama_request_timeout_s,
                f"{p}_MODEL_ROUTED": probe.get("local_model") == seat.model,
                f"{p}_LOCAL_ONLY": probe.get("local_only") is True,
            }
            checks[f"{p}_OLLAMA_MODEL_PRESENT"] = self._ollama_has(
                str(probe.get("ollama_host") or ""), seat.model
            )
            return checks
        return {
            f"{p}_SEAT": probe.get("cloud_seat") == seat.provider,
            f"{p}_PIN": probe.get("cloud_pin_mid") == seat.model,
            f"{p}_ALLOWED_PROVIDERS": probe.get("cloud_allowed_providers")
            == list(seat.expected_allowed_providers),
            f"{p}_JURISDICTION": probe.get("cloud_jurisdiction") == seat.expected_jurisdiction,
            f"{p}_ANTHROPIC_OFF": probe.get("anthropic_api_enabled") is False
            and probe.get("anthropic_configured") is False,
            f"{p}_KEY_SHAPE_OK": probe.get("key_shape_ok") is True,
            f"{p}_CLOUD_REACH_PAID": probe.get("cloud_reach_paid") is True,
        }

    def _ollama_has(self, host: str, model: str) -> bool:
        if not host:
            return False
        url = host.rstrip("/") + "/api/tags"
        try:
            data = self.io.http.get_json(url, timeout_s=_HTTP_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — 실패를 타입명으로 남긴다(판정은 False)
            self.kv(f"OLLAMA_REACHABLE=False error={type(exc).__name__} url={url}")
            return False
        models = data.get("models", []) if isinstance(data, dict) else []
        names = {str(m.get("name") or m.get("model")) for m in models if isinstance(m, dict)}
        return model in names

    @staticmethod
    def _passed(checks: Mapping[str, object]) -> bool:
        # 숫자 항목(…_MISSING 등)은 정보용이다 — 판정은 불리언 항목만 본다.
        return all(v is True for v in checks.values() if isinstance(v, bool))

    def _emit_checks(self, prefix: str, checks: Mapping[str, object]) -> None:
        self.kv(prefix + " " + " ".join(f"{k}={v}" for k, v in checks.items()))

    def refuse_unless(self, stage: str, checks: Mapping[str, object], hint: str) -> None:
        self._emit_checks(f"PRECHECK stage={stage}", checks)
        if not self._passed(checks):
            raise StageRefusedError(stage, checks, hint)

    # ── 실물 판정 ──
    def seat_progress(self, seat: SeatConfig) -> dict[str, int]:
        """좌석의 행 수와 시도 소진.

        - `evidenced` = 대장 시도 합 + 대장 밖 genlog 행(끊긴 회차의 실제 호출) — 산출 파일 근거.
        - `reserved_attempts` = 상태 파일의 예약 누계. 호출 **전에** 더하고 **절대 줄이지 않는다**
          (단조 증가 — 앞서 끊긴 회차의 예약이 뒤 정상 회차에 덮여 지워지면 유료 좌석이 같은 예산을
          두 번 쓴다. EOS-208 리뷰 P1 재현: 예산 30에 50시도).
        - `tried` = max(evidenced, reserved) — 회차 크기·예산 상한은 항상 이 보수적 값으로 정한다.
        - `unevidenced` = tried − evidenced — 호출 기록이 없는 예약(시작 직후 실패한 실행 등).
        """
        cons = seat_consumption(self.cfg.seat_dir(seat))
        reserved = int(self.state.get("seats", {}).get(seat.name, {}).get("reserved_attempts", 0))
        evidenced = cons["ledger_attempts"] + cons["unrecorded_calls"]
        tried = max(evidenced, reserved)
        return {
            "lines": count_lines(self.cfg.seat_out(seat)),
            **cons,
            "evidenced": evidenced,
            "reserved_attempts": reserved,
            "tried": tried,
            "unevidenced": tried - evidenced,
        }

    def seat_complete(self, seat: SeatConfig) -> bool:
        """저작 완료 = 목표 달성 또는 **실물 근거로** 예산 소진 · 또는 검수 큐가 이미 있다(동결).

        근거 없는 예약만으로 예산이 찬 상태는 완료가 아니다(리뷰 P2-1 — 호출 0건 실패 두 번이 거짓
        '예산 소진 완료'로 다음 단계에 넘어가던 결함). 그 상태는 저작 단계가 거부로 안내한다.
        """
        if self.cfg.queue_path().exists():
            return True
        prog = self.seat_progress(seat)
        return prog["lines"] >= seat.target_cu or prog["evidenced"] >= seat.attempt_budget

    def judged_count(self) -> tuple[int, int]:
        """(큐 행 수, 판정 완료 수) — 판정 = 판정 파일의 승인·수정승인·반려 ∩ 종결 이벤트 ∩ 큐."""
        from whymath_backend.harness.review_session import completed_slugs, load_review_items

        if not self.cfg.queue_path().exists():
            return 0, 0
        items, _ = load_review_items(self.cfg.queue_path())
        queue_slugs = {i.slug for i in items}
        decided = {
            str(r.get("slug"))
            for r in read_jsonl(self.cfg.verdicts_path())
            if r.get("verdict") in ("approved", "approved_with_edit", "rejected")
        }
        finished = completed_slugs(self.cfg.events_path())
        return len(queue_slugs), len(queue_slugs & decided & finished)

    def remote_branch_sha(self) -> str | None:
        """원격 브랜치 끝 sha. 없으면 "" · 모르면 None(모른다 ≠ 없다)."""
        res = self.git("ls-remote", "--heads", "origin", self.cfg.deliver_branch)
        if not res.ok:
            self.kv(f"REMOTE_QUERY_FAILED=True reason={res.failure_reason()}")
            return None
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == f"refs/heads/{self.cfg.deliver_branch}":
                return parts[0]
        return ""

    def head_sha(self) -> str:
        res = self.git("rev-parse", "HEAD")
        return res.stdout.strip() if res.ok else ""

    def is_complete(self, stage: str) -> bool:
        if stage in STAGE_KIND:
            return all(self.seat_complete(s) for s in self.cfg.seats_of(STAGE_KIND[stage]))
        if stage == "queue":
            return count_lines(self.cfg.queue_path()) > 0
        if stage == "review":
            total, judged = self.judged_count()
            return total > 0 and judged == total
        if stage == "deliver":
            remote = self.remote_branch_sha()
            return bool(remote) and remote == self.head_sha()
        return False

    # ── 단계 ──
    def stage_preflight(self, pending: set[str]) -> StageOutcome:
        base = self.base_guard()
        self._emit_checks("PREFLIGHT_BASE", base)
        if not self._passed(base):
            raise StageRefusedError(
                "preflight",
                base,
                "이 명령은 격리 워크트리(런북 한 줄 실행 절 [R1])에서 그 워크트리의 코드로 "
                "돌아야 한다 — PYTHONPATH와 설정의 worktree 값을 확인하세요",
            )
        needs_local = "author-local" in pending and bool(self.cfg.seats_of("local"))
        needs_cloud = "author-cloud" in pending and bool(self.cfg.seats_of("cloud"))
        needs_tk = "review" in pending and self.cfg.review_ui == "gui"
        probe = self.probe(None, check_tk=needs_tk)
        checks: dict[str, object] = dict(self.child_code_checks(probe))
        checks.update(self.seeds_check())
        if needs_tk:
            checks["TK_OK"] = probe.get("tk_ok") is True
        for seat in self.cfg.seats:
            if (seat.kind == "local" and needs_local) or (seat.kind == "cloud" and needs_cloud):
                checks.update(self.seat_checks(seat, self.probe(seat)))
        errors = probe.get("errors") or {}
        if errors:
            self.kv("PROBE_ERRORS " + " ".join(f"{k}={v}" for k, v in errors.items()))
        self._emit_checks("PREFLIGHT", checks)
        self.kv(f"WORKTREE_HEAD={self.head_sha()[:12]} MAIN_HEAD={self._main_sha()[:12]}")
        for seat in self.cfg.seats:
            prog = self.seat_progress(seat)
            self.kv(
                f"SEAT name={seat.name} kind={seat.kind} lines={prog['lines']} "
                f"target={seat.target_cu} tried={prog['tried']} budget={seat.attempt_budget}"
            )
        total, judged = self.judged_count()
        self.kv(f"QUEUE_LINES={total} JUDGED={judged}")
        ready = self._passed(checks)
        self.kv(f"READY_PREFLIGHT={ready}")
        if not ready:
            raise StageRefusedError(
                "preflight",
                checks,
                "False 항목을 고친 뒤 같은 한 줄을 다시 실행하세요(키 없음이면 런북 [C-1]·[C-2])",
            )
        self.say("준비 점검 통과 — 코드 출처·좌석·타임아웃 주입·모델이 모두 맞습니다")
        return StageOutcome("done", {"checks": {k: v for k, v in checks.items()}})

    def _main_sha(self) -> str:
        res = self.git("rev-parse", "origin/main")
        return res.stdout.strip() if res.ok else ""

    def _ensure_spec_plan(self) -> None:
        path = self.cfg.spec_plan_path()
        text = self.cfg.spec_plan_text()
        if path.exists():
            if path.read_text(encoding="utf-8") != text:
                raise StageRefusedError(
                    "author",
                    {"SPEC_PLAN_UNCHANGED": False},
                    "이 회차의 spec 계획(anchors)이 처음 저작 때와 다르다 — 회차 중간에 "
                    "spec을 바꾸면 좌석 비교가 오염된다. 새 round_name으로 설정을 만드세요",
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _author_argv(self, seat: SeatConfig, n: int) -> list[str]:
        argv = [
            "-m",
            "whymath_backend.harness.problem_corpus_accumulate",
            "--out",
            str(self.cfg.seat_out(seat)),
        ]
        for seed in self.cfg.seeds:
            argv += ["--seed", str(self.cfg.worktree / seed)]
        argv += ["--spec-file", str(self.cfg.spec_plan_path()), "--n", str(n)]
        if seat.kind == "local":
            argv += ["--authoring-tier", str(seat.authoring_tier)]
        else:
            # 클라우드는 두 신호가 **함께**여야 간다(하나만이면 라우터가 LOCAL로 강제).
            argv += [
                "--subscription",
                str(seat.subscription),
                "--budget-krw",
                str(seat.budget_krw),
            ]
        argv += [
            "--avoid-recent",
            str(self.cfg.avoid_recent),
            "--canary",
            str(self.cfg.canary),
            "--abort-window",
            str(self.cfg.abort_window),
        ]
        return argv

    def stage_author(self, stage: str) -> StageOutcome:
        kind = STAGE_KIND[stage]
        seats = self.cfg.seats_of(kind)
        detail: dict[str, Any] = {}
        if not seats:
            self.say(f"{kind} 좌석이 설정에 없어 건너뜁니다")
            return StageOutcome("done", {"seats": {}})
        for seat in seats:
            detail[seat.name] = self._author_seat(stage, seat)
        if any(d.get("dry_run") for d in detail.values()):
            return StageOutcome("incomplete", {"dry_run": True})
        return StageOutcome("done", {"seats": detail})

    def _author_seat(self, stage: str, seat: SeatConfig) -> dict[str, Any]:
        prog = self.seat_progress(seat)
        if prog["unevidenced"] > 0:
            self.kv(
                f"STATE_MISMATCH seat={seat.name} evidenced={prog['evidenced']} "
                f"(ledger={prog['ledger_attempts']} unrecorded_genlog={prog['unrecorded_calls']}) "
                f"reserved={prog['reserved_attempts']} — 큰 쪽({prog['tried']})으로 예산을 센다"
            )
        if self.cfg.queue_path().exists():
            # 검수 큐가 생긴 뒤에는 저작을 덧붙이지 않는다(검수 분모가 바뀐다) — 거부가 아니라 동결.
            # 목표·예산 상향은 큐를 만들기 전에만 의미가 있다.
            self.kv(f"AUTHOR_FROZEN seat={seat.name} reason=queue_exists lines={prog['lines']}")
            self.say(
                f"좌석 {seat.name}: 검수 큐가 이미 있어 저작을 더 하지 않습니다(목표·예산 상향은 "
                "큐를 만들기 전에만 반영됩니다 — 더 저작하려면 새 round_name으로 회차를 시작)"
            )
            return {"outcome": "frozen_by_queue", **prog}
        if prog["lines"] >= seat.target_cu or prog["evidenced"] >= seat.attempt_budget:
            return self._seat_summary(seat)
        self._refuse_unevidenced(stage, seat, prog)
        # ── 쓰기 직전 재검사(이 좌석 기준) ──
        probe = self.probe(seat)
        checks: dict[str, object] = {**self.base_guard(), **self.child_code_checks(probe)}
        checks.update(self.seeds_check())
        checks.update(self.seat_checks(seat, probe))
        checks["BUDGET_LEFT"] = prog["tried"] < seat.attempt_budget
        self.refuse_unless(
            stage,
            checks,
            "호출하지 않았다(과금 0). 키·모델·타임아웃 항목은 준비 점검 안내를 따르세요",
        )
        if self.dry_run:
            n = next_round_size(prog["lines"], prog["tried"], seat.target_cu, seat.attempt_budget)
            self.kv(
                f"DRY_RUN_PLAN stage={stage} seat={seat.name} n={n} "
                f"argv={self._author_argv(seat, n)}"
            )
            return {"dry_run": True}
        self._ensure_spec_plan()
        stopped: tuple[str, str] | None = None
        while True:
            prog = self.seat_progress(seat)
            if prog["lines"] >= seat.target_cu or prog["tried"] >= seat.attempt_budget:
                break
            n = next_round_size(prog["lines"], prog["tried"], seat.target_cu, seat.attempt_budget)
            if n <= 0:
                break
            if self.cfg.queue_path().exists():
                stopped = (
                    "QueueAppeared",
                    "저작 도중 검수 큐가 생겼다 — 다른 창에서 같은 회차가 돌고 있는지 확인",
                )
                break
            # 예산을 **호출 전에** 예약한다 — 단조 증가(줄이지 않는다). 못 쓰면 호출하지 않는다.
            seats_state = self.state.setdefault("seats", {}).setdefault(seat.name, {})
            seats_state["reserved_attempts"] = prog["tried"] + n
            if not self._save_state():
                raise StageFailedError(
                    stage,
                    "ReservationNotSaved",
                    "시도 예약을 상태 파일에 쓰지 못해 호출하지 않았다",
                )
            rounds_before = prog["ledger_rounds"]
            self.kv(
                f"ROUND_START seat={seat.name} n={n} lines_before={prog['lines']} "
                f"tried_before={prog['tried']} at={self.io.clock.now().isoformat()}"
            )
            res = self.run_child(
                self._author_argv(seat, n), timeout_s=n * seat.attempt_timeout_s, mode="stream"
            )
            report = last_json_object(res.stdout) or {}
            after = self.seat_progress(seat)
            recorded = after["ledger_rounds"] > rounds_before
            exit_label = "timeout" if res.timed_out else str(res.returncode)
            self.kv(
                f"ROUND_END seat={seat.name} exit={exit_label} lines_after={after['lines']} "
                f"tried_after={after['tried']} evidenced_after={after['evidenced']} "
                f"outcome_counts={json.dumps(report.get('outcome_counts'), ensure_ascii=False)}"
            )
            if res.launch_error is not None:
                stopped = ("LaunchError", f"저작 CLI를 실행하지 못했다 — {res.failure_reason()}")
                break
            if res.timed_out:
                stopped = (
                    "RoundTimeout",
                    f"회차 시간 상한({n * seat.attempt_timeout_s:.0f}초)을 넘겨 중단했다 — Ollama "
                    "응답이 멈췄는지 확인하세요. 그때까지의 호출은 genlog로 소진에 계상된다",
                )
                break
            if res.returncode == 2:
                stopped = (
                    "RoundExit2",
                    f"저작 CLI exit 2 — 연속 무진전 알람 또는 설정 오류다({res.failure_reason()})",
                )
                break
            if not recorded:
                stopped = (
                    "LedgerNotWritten",
                    "회차 대장 없이 끝났다 — 저작 CLI가 시작 직후 실패했을 수 있다(임포트·설정 "
                    f"오류 등 · {res.failure_reason()}). 같은 실패를 반복하지 않으려 멈췄다",
                )
                break
        if stopped is not None:
            self._seat_summary(seat)
            raise StageFailedError(
                stage,
                "RoundStopped",
                f"좌석 {seat.name}: [{stopped[0]}] {stopped[1]} — 위 출력을 회신하세요",
            )
        prog = self.seat_progress(seat)
        if prog["lines"] < seat.target_cu and prog["evidenced"] < seat.attempt_budget:
            self._refuse_unevidenced(stage, seat, prog)
        return self._seat_summary(seat)

    def _refuse_unevidenced(self, stage: str, seat: SeatConfig, prog: Mapping[str, int]) -> None:
        """근거 없는 예약만으로 예산이 찼으면 '소진 완료'가 아니라 거부한다(리뷰 P2-1)."""
        if prog["tried"] < seat.attempt_budget or prog["evidenced"] >= seat.attempt_budget:
            return
        self.kv(
            f"AUTHOR_UNEVIDENCED seat={seat.name} evidenced={prog['evidenced']} "
            f"reserved={prog['reserved_attempts']} unevidenced={prog['unevidenced']} "
            f"budget={seat.attempt_budget}"
        )
        raise StageRefusedError(
            stage,
            {f"{seat.name.upper().replace('-', '_')}_BUDGET_EVIDENCED": False},
            f"좌석 {seat.name}: 시도 예산 {seat.attempt_budget} 중 실물 근거(대장·genlog)는 "
            f"{prog['evidenced']}건이고 {prog['unevidenced']}건은 호출 기록이 없는 예약이다"
            "(시작 직후 "
            "실패한 실행). 앞 실행의 STAGE_FAILED 원인을 고친 뒤, 그 예약을 풀려면 같은 한 줄에 "
            "--release-unevidenced를 붙여 실행하세요(풀어 준 수가 상태 파일 이력에 남는다)",
        )

    def _seat_summary(self, seat: SeatConfig) -> dict[str, Any]:
        prog = self.seat_progress(seat)
        if prog["lines"] >= seat.target_cu:
            outcome = "target_met"
        elif prog["evidenced"] >= seat.attempt_budget:
            outcome = "budget_exhausted"
        else:
            outcome = "stopped"
        self.kv(
            f"AUTHOR_DONE seat={seat.name} lines={prog['lines']} tried={prog['tried']} "
            f"evidenced={prog['evidenced']} target={seat.target_cu} "
            f"budget={seat.attempt_budget} outcome={outcome}"
        )
        if outcome == "target_met":
            self.say(f"좌석 {seat.name}: 목표 {seat.target_cu}건 달성({prog['lines']}건)")
        elif outcome == "budget_exhausted":
            self.say(
                f"좌석 {seat.name}: 시도 예산 {seat.attempt_budget}건을 다 써서 멈췄습니다 — "
                f"{prog['lines']}/{seat.target_cu}건(목표 미달). 더 저작하려면 설정의 target_cu·"
                "attempt_budget을 바꾸고 같은 한 줄을 다시 실행하세요(검수 큐를 만들기 전까지만)"
            )
        return {"outcome": outcome, **prog}

    def release_unevidenced(self) -> None:
        """사람이 명시적으로 근거 없는 예약을 실물 근거로 되돌린다(`--release-unevidenced`)."""
        for seat in self.cfg.seats:
            prog = self.seat_progress(seat)
            if prog["unevidenced"] <= 0:
                continue
            seats_state = self.state.setdefault("seats", {}).setdefault(seat.name, {})
            seats_state["reserved_attempts"] = prog["evidenced"]
            self.state["history"].append(
                {
                    "at": self.io.clock.now().isoformat(),
                    "stage": "release-unevidenced",
                    "status": "released",
                    "seat": seat.name,
                    "reserved_before": prog["reserved_attempts"],
                    "evidenced": prog["evidenced"],
                }
            )
            self.kv(
                f"RESERVATION_RELEASED seat={seat.name} from={prog['reserved_attempts']} "
                f"to={prog['evidenced']}"
            )
        self._save_state()

    def check_core(self) -> tuple[bool, dict[str, Any]]:
        """런북 [H] — 좌석별 4필드·과목·slug 계수 + provenance_audit --require-runs."""
        ok = True
        detail: dict[str, Any] = {}
        total = 0
        for seat in self.cfg.seats:
            try:
                st = seat_artifact_stats(self.cfg.seat_dir(seat))
            except ValueError as exc:
                raise StageFailedError("check", "JSONLParseError", str(exc)) from exc
            total += st["cu_lines"]
            miss = st["missing"]
            seat_ok = (
                miss["genlog"] == 0
                and miss["model_name"] == 0
                and miss["prompt_version"] == 0
                and miss["input_sha256"] == 0
                # seed: 로컬은 0이어야 한다. 클라우드는 구조적으로 null(G-C · Kiki 결정).
                and (seat.kind != "local" or miss["seed"] == 0)
                and set(st["models"]) <= {seat.model}
            )
            subj_calc = slug_ok = st["cu_lines"]
            if self.cfg.expected_subject is not None:
                subj_calc = sum(
                    1
                    for r in read_jsonl(self.cfg.seat_out(seat))
                    if r.get("subject") == self.cfg.expected_subject
                )
                seat_ok = seat_ok and subj_calc == st["cu_lines"]
            if self.cfg.expected_slug_prefix is not None:
                slug_ok = sum(
                    1 for s in st["slugs"] if s.startswith(self.cfg.expected_slug_prefix + "-")
                )
                seat_ok = seat_ok and slug_ok == st["cu_lines"]
            self.kv(
                f"SEAT_CHECK seat={seat.name} CU_LINES={st['cu_lines']} "
                f"DISTINCT_SLUGS={st['distinct_slugs']} GENLOG_ROWS={st['genlog_rows']} "
                f"GENLOG_SUCCESS={st['genlog_success']} MODELS={','.join(st['models'])} "
                + " ".join(f"CU_MISSING_{k.upper()}={v}" for k, v in miss.items())
                + f" CU_SUBJECT_OK={subj_calc} CU_SLUG_PREFIX_OK={slug_ok}"
                f" COST_USD_SUM={st['cost_usd_sum']:.6f} COST_NULL_ROWS={st['cost_null_rows']}"
                f" SEAT_OK={seat_ok}"
            )
            ok = ok and seat_ok
            detail[seat.name] = {"cu_lines": st["cu_lines"], "ok": seat_ok, "missing": miss}
        res = self.run_child(
            [
                "-m",
                "whymath_backend.ops.provenance_audit",
                "--require-runs",
                "--runs-root",
                str(self.cfg.runs_dir()),
            ],
            timeout_s=_METRICS_TIMEOUT_S,
        )
        prov_exit = "timeout" if res.timed_out else res.returncode
        for line in res.stdout.splitlines()[-30:]:
            if line.strip():
                self.kv(f"PROVENANCE| {line.rstrip()}")
        self.kv(f"PROVENANCE_EXIT={prov_exit}")
        if not res.ok:
            self.kv(f"PROVENANCE_CAUSE={res.failure_reason()}")
        enough = total >= self.cfg.min_queue_cu
        self.kv(f"TOTAL_CU_LINES={total} MIN_QUEUE_CU={self.cfg.min_queue_cu} ENOUGH={enough}")
        ok = ok and res.ok and enough
        detail.update({"total_cu": total, "provenance_exit": prov_exit})
        return ok, detail

    def stage_check(self) -> StageOutcome:
        ok, detail = self.check_core()
        self.kv(f"CHECK_OK={ok}")
        if not ok:
            raise StageFailedError(
                "check",
                "ArtifactCheckFailed",
                "SEAT_OK=False·PROVENANCE_EXIT≠0·ENOUGH=False 중 하나 — 위 줄을 회신하세요",
            )
        self.say(f"산출물 검사 통과 — 합계 {detail['total_cu']}건, GenerationLog 4필드 결손 0")
        return StageOutcome("done", detail)

    def stage_queue(self) -> StageOutcome:
        ok, detail = self.check_core()
        queue = self.cfg.queue_path()
        checks: dict[str, object] = {
            **self.base_guard(),
            "CHECK_OK": ok,
            "QUEUE_ABSENT": not queue.exists(),
        }
        self.refuse_unless(
            "queue",
            checks,
            "큐를 만들지 않았다. QUEUE_ABSENT=False면 이미 큐가 있다 — "
            "검수는 review 단계가 이어서 한다",
        )
        rows = [
            (
                [
                    ln
                    for ln in self.cfg.seat_out(s).read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                ]
                if self.cfg.seat_out(s).exists()
                else []
            )
            for s in self.cfg.seats
        ]
        out, dup = assemble_queue(rows)
        if self.dry_run:
            self.kv(f"DRY_RUN_PLAN stage=queue lines={len(out)} cross_seat_dup={dup}")
            return StageOutcome("incomplete", {"dry_run": True})
        queue.parent.mkdir(parents=True, exist_ok=True)
        tmp = queue.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(ln + "\n" for ln in out), encoding="utf-8")
        os.replace(tmp, queue)
        back = count_lines(queue)
        self.kv(f"QUEUE_WRITTEN=True QUEUE_LINES={back} CROSS_SEAT_DUP_SLUGS={dup}")
        if back != len(out):
            raise StageFailedError(
                "queue", "QueueReadbackMismatch", f"썼다 {len(out)} 읽었다 {back}"
            )
        self.say(f"검수 큐 {back}건을 만들었습니다 — 이 숫자가 검수 완주 분모입니다")
        return StageOutcome("done", {"queue_lines": back, "cross_seat_dup": dup, **detail})

    def stage_review(self) -> StageOutcome:
        total, judged = self.judged_count()
        if total > 0 and judged == total:
            self.kv(f"REVIEW_JUDGED={judged} QUEUE_LINES={total} REVIEW_DONE=True")
            return StageOutcome("done", {"judged": judged, "queue_lines": total})
        checks: dict[str, object] = {**self.base_guard(), "QUEUE_PRESENT": total > 0}
        self.refuse_unless("review", checks, "검수 큐가 없다 — queue 단계를 먼저 돌리세요")
        module = (
            "whymath_backend.harness.review_session_gui"
            if self.cfg.review_ui == "gui"
            else "whymath_backend.harness.review_session"
        )
        argv = [
            "-m",
            module,
            "--queue",
            str(self.cfg.queue_path()),
            "--events",
            str(self.cfg.events_path()),
            "--verdicts",
            str(self.cfg.verdicts_path()),
            "--reviewer-id",
            self.cfg.reviewer_id,
            "--resume",  # 처음이어도 무해 — 이미 종결한 건은 건너뛴다(이중 계측 방지)
        ]
        if self.dry_run:
            self.kv(f"DRY_RUN_PLAN stage=review argv={argv}")
            return StageOutcome("incomplete", {"dry_run": True})
        self.say(
            f"검수를 시작합니다 — {total}건 중 {judged}건 판정됨. 창에서 판정하고, "
            "쉬려면 창을 닫으세요"
            "(같은 한 줄을 다시 실행하면 이어서 합니다)"
        )
        res = self.run_child(argv, timeout_s=self.cfg.review_timeout_s, mode="inherit")
        total, judged = self.judged_count()
        done = total > 0 and judged == total
        self.kv(
            f"REVIEW_EXIT={'timeout' if res.timed_out else res.returncode} "
            f"REVIEW_JUDGED={judged} QUEUE_LINES={total} REVIEW_DONE={done}"
        )
        if not res.ok:
            # 창이 비정상 종료(입력 실패·tkinter 없음·기록 실패·타임아웃) — 미완이 아니라 실패다.
            raise StageFailedError("review", "ReviewToolFailed", res.failure_reason())
        if not done:
            self.say(
                f"검수 {total - judged}건이 남았습니다 — "
                "같은 한 줄을 다시 실행하면 남은 것부터 이어갑니다"
            )
            return StageOutcome("incomplete", {"judged": judged, "queue_lines": total})
        self.say(f"검수 완주 — {judged}/{total}건")
        return StageOutcome("done", {"judged": judged, "queue_lines": total})

    def _window(self) -> tuple[str, str, int]:
        """집계 창 = 검수 이벤트 recorded_at·좌석 genlog generated_at의 최소~최대+1초([K])."""
        stamps: list[datetime] = []
        sources = [(self.cfg.events_path(), "recorded_at")] + [
            (self.cfg.seat_dir(s) / "cu.genlog.jsonl", "generated_at") for s in self.cfg.seats
        ]
        for path, key in sources:
            try:
                rows = read_jsonl(path)
            except ValueError as exc:
                raise StageFailedError("summarize", "WindowInputBroken", str(exc)) from exc
            for row in rows:
                value = row.get(key)
                if not value:
                    continue
                try:
                    stamp = datetime.fromisoformat(str(value))
                except ValueError as exc:
                    raise StageFailedError(
                        "summarize", "WindowInputBroken", f"{path.name}: {type(exc).__name__}"
                    ) from exc
                stamps.append(stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc))
        if not stamps:
            raise StageFailedError("summarize", "WindowUnknown", "시각이 찍힌 행이 0건(측정 실패)")
        return (
            min(stamps).isoformat(),
            (max(stamps) + timedelta(seconds=1)).isoformat(),
            len(stamps),
        )

    def stage_summarize(self) -> StageOutcome:
        from whymath_backend.l3.router import USD_TO_KRW

        checks: dict[str, object] = {
            **self.base_guard(),
            "EVENTS_PRESENT": self.cfg.events_path().exists(),
            "VERDICTS_PRESENT": self.cfg.verdicts_path().exists(),
        }
        self.refuse_unless("summarize", checks, "검수 기록이 없다 — review 단계를 먼저 하세요")
        detail: dict[str, Any] = {}
        failed: list[str] = []
        for seat in self.cfg.seats:
            res = self.run_child(
                [
                    "-m",
                    "whymath_backend.ops.hit_cu_metrics",
                    "--events",
                    str(self.cfg.events_path()),
                    "--verdicts",
                    str(self.cfg.verdicts_path()),
                    "--generation-log",
                    str(self.cfg.seat_dir(seat) / "cu.genlog.jsonl"),
                    "--json",
                ],
                timeout_s=_METRICS_TIMEOUT_S,
            )
            report = last_json_object(res.stdout)
            p = seat.name.upper().replace("-", "_")
            if report is None or not res.ok:
                failed.append(f"hit:{seat.name}")
                self.kv(
                    f"HIT_{p}_EXIT={res.returncode} REPORT_UNREADABLE=True "
                    f"cause={res.failure_reason()}"
                )
                continue
            self.kv(
                f"HIT_{p}_EXIT={res.returncode} CU_MEASURED={report.get('cu_measured')} "
                f"HIT_MEDIAN_S={report.get('hit_median_seconds')} "
                f"IMPLAUSIBLE_MAJORITY={report.get('hit_implausible_majority')} "
                f"CU_WITH_COST={report.get('cu_with_cost')} "
                f"COST_USD_COMPLETE={report.get('cost_usd_complete_total')} "
                f"COVERAGE={report.get('coverage_rate')}"
            )
            detail[f"hit_{seat.name}"] = {
                k: report.get(k)
                for k in ("cu_measured", "hit_median_seconds", "hit_implausible_majority")
            }
        start, end, n = self._window()
        self.kv(f"WINDOW_START={start} WINDOW_END={end} TIMESTAMPED_ROWS={n}")
        weekly = ["-m", "whymath_backend.ops.weekly_metrics_report", "--dry-run"]
        weekly += ["--events-jsonl", str(self.cfg.events_path())]
        for seat in self.cfg.seats:
            weekly += ["--generation-log-jsonl", str(self.cfg.seat_dir(seat) / "cu.genlog.jsonl")]
        weekly += ["--week-start", start, "--week-end", end, "--krw-per-usd", str(USD_TO_KRW)]
        res = self.run_child(weekly, timeout_s=_METRICS_TIMEOUT_S)
        for line in res.stderr_tail.splitlines():
            # [K] 판정 항목 — 창 안 행 수가 전체 행 수와 같은지(회차 행이 창 밖으로 빠지지 않았는지)
            if "[파일 입력]" in line or "중복 제거" in line:
                self.kv(f"WEEKLY| {line.rstrip()}")
        rec = last_json_object(res.stdout)
        if rec is None or not res.ok:
            failed.append("weekly")
            self.kv(
                f"WEEKLY_CLI_EXIT={res.returncode} PREVIEW_UNREADABLE=True "
                f"cause={res.failure_reason()}"
            )
        else:
            kpis = rec.get("kpis") or {}
            self.kv(
                f"WEEKLY_CLI_EXIT={res.returncode} WEEK_START={rec.get('week_start')} "
                f"WEEK_END={rec.get('week_end')}"
            )
            for key in ("hit_seconds", "unit_cost_krw"):
                v = kpis.get(key) or {}
                self.kv(
                    f"PREVIEW_{key.upper()}_MEASURED={v.get('measured')} VALUE={v.get('value')} "
                    f"REASON={v.get('reason')}"
                )
                detail[f"preview_{key}"] = {"measured": v.get("measured"), "value": v.get("value")}
        self.kv("PREVIEW_ONLY=True LEDGER_WRITTEN=False")
        if failed:
            raise StageFailedError("summarize", "MetricsUnreadable", ",".join(failed))
        self.say(
            "집계 미리보기 완료 — 원장(metrics/weekly.json)에는 쓰지 않았습니다"
            "(세션이 같은 창으로 기록)"
        )
        return StageOutcome("done", {**detail, "window": [start, end]})

    def _round_rel_dirs(self, *, existing_only: bool = False) -> list[str]:
        out: list[str] = []
        for d in self.cfg.round_dirs():
            if existing_only and not d.is_dir():
                continue  # 산출물이 없는 좌석 폴더는 git add 대상이 아니다(pathspec 오류 방지)
            rel = os.path.relpath(d, self.cfg.worktree).replace("\\", "/")
            out.append(rel)
        return out

    def _classify_dirty(self) -> tuple[list[str], list[str], list[str]]:
        """(회차 산출물 변경, 허용된 설정 파일 변경, 그 밖의 변경). 판정 불가면 예외."""
        res = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if not res.ok:
            raise StageFailedError("deliver", "GitStatusFailed", res.failure_reason())
        rel_dirs = self._round_rel_dirs()
        config_rel: str | None = None
        if is_under(self.cfg.source_path, self.cfg.worktree):
            config_rel = os.path.relpath(self.cfg.source_path, self.cfg.worktree).replace("\\", "/")
        ours: list[str] = []
        config: list[str] = []
        other: list[str] = []
        for path in parse_porcelain_z(res.stdout):
            norm = path.replace("\\", "/")
            if any(norm == d or norm.startswith(d + "/") for d in rel_dirs):
                ours.append(norm)
            elif config_rel is not None and norm == config_rel:
                config.append(norm)
            else:
                other.append(norm)
        return ours, config, other

    def stage_deliver(self) -> StageOutcome:
        total, judged = self.judged_count()
        email = self.git("config", "user.email")
        ours, config_changed, other = self._classify_dirty()
        remote = self.remote_branch_sha()
        required = [self.cfg.queue_path(), self.cfg.events_path(), self.cfg.verdicts_path()]
        head = self.head_sha()
        main_sha = self._main_sha()
        branch_res = self.git("rev-parse", "--abbrev-ref", "HEAD")
        on_branch = branch_res.ok and branch_res.stdout.strip() == self.cfg.deliver_branch
        # 앞 실행이 커밋까지 하고 push에서 실패했을 수 있다 — 새 파일이 없어도 보낼 것이 있다.
        prior_commit = on_branch and bool(head) and head != main_sha
        ref_ok = self.git("check-ref-format", "--branch", self.cfg.deliver_branch).ok
        checks: dict[str, object] = {
            **self.base_guard(),
            "BRANCH_NAME_VALID": ref_ok,
            "EMAIL_SET": email.ok and bool(email.stdout.strip()),
            "REVIEW_COMPLETE": total > 0 and judged == total,
            "JUDGED": judged,
            "QUEUE_LINES": total,
            "ROUND_FILES_PENDING": bool(ours) or prior_commit,
            "OTHER_DIRTY_ZERO": not other,
            "OTHER_DIRTY": len(other),
            "REMOTE_BRANCH_ABSENT": remote == "",
            "REQUIRED_FILES_PRESENT": all(p.exists() for p in required),
        }
        if other:
            self.kv("OTHER_DIRTY_PATHS " + " ".join(other[:10]))
        if config_changed:
            self.kv(
                f"CONFIG_MODIFIED=True path={config_changed[0]} — 회차 설정 수정은 허용"
                "(산출물에 스냅샷)"
            )
        self.refuse_unless(
            "deliver",
            checks,
            "커밋·push하지 않았다. REVIEW_COMPLETE=False면 검수가 남았다(JUDGED<QUEUE_LINES) · "
            "OTHER_DIRTY_ZERO=False면 산출물 밖 변경이 있다(위 경로 회신) · "
            "REMOTE_BRANCH_ABSENT=False면 "
            "이미 원격 브랜치가 있거나(앞 push 성공 가능) 원격 조회가 실패했다 — 회신하세요",
        )
        if self.dry_run:
            self.kv(
                f"DRY_RUN_PLAN stage=deliver branch={self.cfg.deliver_branch} files={len(ours)}"
            )
            return StageOutcome("incomplete", {"dry_run": True})
        # 커밋 직전에 상태를 기록해 커밋에 실린다(무엇까지 했는지가 산출물과 함께 간다).
        self._record("deliver", "running", {"judged": judged, "queue_lines": total})
        self._git_ok(self.git("checkout", "-B", self.cfg.deliver_branch), "GitCheckoutFailed")
        self._git_ok(
            self.git("add", "--", *self._round_rel_dirs(existing_only=True)), "GitAddFailed"
        )
        staged = self.git("diff", "--cached", "--name-only", "-z")
        self._git_ok(staged, "GitDiffFailed")
        if [p for p in staged.stdout.split("\0") if p]:
            self._git_ok(self.git("commit", "-m", self.cfg.commit_message), "GitCommitFailed")
        local_sha = self.head_sha()
        shown = self.git("show", "--name-only", "--format=", "-z", "HEAD")
        self._git_ok(shown, "GitShowFailed")
        rel_dirs = self._round_rel_dirs()
        committed = [p for p in shown.stdout.replace("\n", "\0").split("\0") if p]
        committed_round = [
            p for p in committed if any(p == d or p.startswith(d + "/") for d in rel_dirs)
        ]
        head_not_main = bool(local_sha) and local_sha != main_sha
        self.kv(
            f"LOCAL_SHA={local_sha} MAIN_SHA={main_sha} HEAD_NOT_MAIN={head_not_main} "
            f"COMMITTED_ROUND_FILES={len(committed_round)} COMMITTED_FILES={len(committed)}"
        )
        if not head_not_main or not committed_round or len(committed_round) != len(committed):
            raise StageFailedError(
                "deliver",
                "CommitVerificationFailed",
                "커밋이 만들어지지 않았거나 산출물 밖 파일이 섞였다 — push하지 않았다",
            )
        push = self.git(
            "push",
            "-u",
            "origin",
            f"HEAD:refs/heads/{self.cfg.deliver_branch}",
            timeout_s=_GIT_PUSH_TIMEOUT_S,
        )
        if not push.ok:
            raise StageFailedError("deliver", "GitPushFailed", push.failure_reason())
        remote_after = self.remote_branch_sha()
        verified = bool(remote_after) and remote_after == local_sha
        self.kv(f"REMOTE_SHA={remote_after} PUSH_VERIFIED={verified}")
        if not verified:
            raise StageFailedError(
                "deliver", "RemoteMismatch", "원격 브랜치 끝이 방금 커밋과 다르다"
            )
        self.say(f"산출물을 브랜치 {self.cfg.deliver_branch}로 보냈습니다 — 원격 대조 일치")
        return StageOutcome("done", {"local_sha": local_sha, "remote_sha": remote_after})

    @staticmethod
    def _git_ok(res: RunResult, error: str) -> None:
        if not res.ok:
            raise StageFailedError("deliver", error, res.failure_reason())

    # ── 실행 계획 ──
    def run_stage(self, stage: str, pending: set[str]) -> StageOutcome:
        if stage == "preflight":
            return self.stage_preflight(pending)
        if stage in STAGE_KIND:
            return self.stage_author(stage)
        handlers: dict[str, Callable[[], StageOutcome]] = {
            "check": self.stage_check,
            "queue": self.stage_queue,
            "review": self.stage_review,
            "summarize": self.stage_summarize,
            "deliver": self.stage_deliver,
        }
        return handlers[stage]()

    # ── 단일 실행 잠금 ──
    def _lock_file(self) -> Path | None:
        """잠금 파일 경로 — 워크트리의 git 디렉터리 안(작업 트리 밖 — 산출물·커밋에 안 섞인다)."""
        res = self.git("rev-parse", "--absolute-git-dir")
        if not res.ok or not res.stdout.strip():
            return None
        return Path(res.stdout.strip()) / f"whymath_authoring_round_{self.cfg.round_name}.lock"

    def acquire_lock(self) -> bool:
        """O_EXCL로 잠금을 만든다. 이미 있으면 거부하고 내용·지우는 방법을 보인다."""
        path = self._lock_file()
        if path is None:
            self.kv(
                "LOCK_REFUSED=True reason=GitDirUnknown — 워크트리의 git 디렉터리를 찾지 못했다"
            )
            return False
        body = json.dumps(
            {"pid": os.getpid(), "started_at": self.io.clock.now().isoformat()}, ensure_ascii=False
        )
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                held = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                held = f"(읽기 실패 {type(exc).__name__})"
            self.kv(f"LOCK_HELD=True path={path} holder={held}")
            self.say(
                "같은 회차가 이미 실행 중입니다(다른 창 확인). 실행 중인 창이 정말 없으면"
                "(앞 실행이 "
                f'강제 종료됨) 이 파일을 지운 뒤 다시 실행하세요: Remove-Item "{path}"'
            )
            return False
        except OSError as exc:
            self.kv(f"LOCK_REFUSED=True reason={type(exc).__name__} path={path}")
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        self._lock_path = path
        self.kv(f"LOCK_ACQUIRED=True path={path}")
        return True

    def release_lock(self) -> None:
        path = self._lock_path
        if path is None:
            return
        try:
            path.unlink()
        except OSError as exc:
            self.kv(f"LOCK_RELEASE_FAILED=True error={type(exc).__name__} path={path}")
        self._lock_path = None

    def run(
        self,
        *,
        only: str | None = None,
        start: str | None = None,
        release_unevidenced: bool = False,
    ) -> int:
        self.kv(
            f"ROUND={self.cfg.round_name} CONFIG_SHA256={self.cfg.source_sha256[:12]} "
            f"DRY_RUN={self.dry_run} WORKTREE={self.cfg.worktree}"
        )
        # 잠금은 격리 워크트리에서 이 모듈이 돌 때만 건다(아니면 준비 점검이 거부한다 — 평소 클론의
        # git 디렉터리에 파일을 남기지 않는다). 드라이런은 쓰지 않으므로 잠그지 않는다.
        if not self.dry_run and self._passed(self.base_guard()):
            if not self.acquire_lock():
                return 1
        try:
            if release_unevidenced and not self.dry_run:
                try:
                    self.release_unevidenced()
                # 깨진 대장·genlog 등 — 단계 이름·타입명을 남기고 멈춘다(침묵 실패 금지).
                except Exception as exc:  # noqa: BLE001
                    return self._fail(
                        StageFailedError("release-unevidenced", type(exc).__name__, str(exc)[:300])
                    )
            return self._run_plan(only=only, start=start)
        finally:
            self.release_lock()

    def _run_plan(self, *, only: str | None, start: str | None) -> int:
        if only is not None:
            plan = [only]
            forced = {only}
        elif start is not None:
            plan = list(STAGES[STAGES.index(start) :])
            forced = {start}
        else:
            plan = list(STAGES)
            forced = set()
        # 미완 쓰기 단계 계산(준비 점검이 어느 좌석·창 항목을 요구할지 정한다).
        try:
            # 계획 밖 단계까지 본다 — `--stage preflight`도 남은 단계가 요구하는 항목을 검사한다.
            pending = {
                s for s in STAGES if s in WRITE_STAGES and (s in forced or not self._real_done(s))
            }
        except StageFailedError as exc:
            return self._fail(exc)
        # 실물 판정 중 깨진 파일 등도 타입명을 남기고 멈춘다(침묵 실패 금지).
        except Exception as exc:  # noqa: BLE001
            return self._fail(StageFailedError("plan", type(exc).__name__, str(exc)[:300]))
        if only is None and start is None and pending:
            first = next(s for s in STAGES if s in pending)
            self.kv(f"RESUME_FROM={first}")
        for stage in plan:
            if stage in WRITE_STAGES and stage not in forced and stage not in pending:
                self.kv(f"STAGE_SKIP stage={stage} reason=실물_완료")
                continue
            self.kv(f"STAGE_START stage={stage}")
            try:
                outcome = self.run_stage(stage, pending)
            except StageRefusedError as exc:
                self._record(stage, "refused", {"checks": _jsonable(exc.checks)})
                bad = " ".join(f"{k}={v}" for k, v in exc.checks.items() if v is False)
                self.kv(f"WRITE_REFUSED=True stage={stage} FALSE: {bad}")
                self.say(f"[{stage}] 거부 — {exc.hint}")
                return 1
            except StageFailedError as exc:
                return self._fail(exc, stage=stage)
            except KeyboardInterrupt:
                self._record(stage, "interrupted", {})
                self.kv(f"STAGE_INTERRUPTED stage={stage}")
                self.say("중단했습니다 — 같은 한 줄을 다시 실행하면 이어서 갑니다")
                return 130
            # 예기치 못한 실패도 단계·타입명을 남기고 멈춘다(traceback으로 흐름을 잃지 않게).
            except Exception as exc:  # noqa: BLE001
                return self._fail(
                    StageFailedError(stage, type(exc).__name__, str(exc)[:300]), stage=stage
                )
            self._record(stage, outcome.status, outcome.detail)
            self.kv(f"STAGE_END stage={stage} status={outcome.status}")
            if outcome.status != "done":
                self.kv(f"ROUND_STATUS=incomplete NEXT_STAGE={stage}")
                return 1
        complete = only is None and not self.dry_run
        self.kv(f"ROUND_STATUS={'complete' if complete else 'stage_done'}")
        if complete:
            self.say("회차 완료 — 세션에 이 출력 전체를 회신하세요")
        return 0

    def _real_done(self, stage: str) -> bool:
        real = self.is_complete(stage)
        recorded = self._state_status(stage)
        if recorded == "done" and not real:
            self.kv(f"STATE_MISMATCH stage={stage} state=done real=incomplete — 실물 기준")
        elif real and recorded not in (None, "done"):
            self.kv(f"STATE_MISMATCH stage={stage} state={recorded} real=done — 실물 기준")
        return real

    def _fail(self, exc: StageFailedError, *, stage: str | None = None) -> int:
        name = stage or exc.stage
        cause = mask_secrets(exc.cause)[:500]
        self._record(name, "failed", {"error": exc.error, "cause": cause})
        self.kv(f"STAGE_FAILED stage={name} error={exc.error}")
        self.kv(f"STAGE_FAILED_CAUSE={cause}")
        self.say(
            f"[{name}] 실패({exc.error}) — 위 원인 줄을 회신하세요. "
            "고친 뒤 같은 한 줄로 이어갑니다"
        )
        return 1


def _jsonable(checks: Mapping[str, object]) -> dict[str, Any]:
    return {
        k: (v if isinstance(v, (bool, int, float, str)) or v is None else str(v))
        for k, v in checks.items()
    }


def main(argv: list[str] | None = None, *, io: Boundaries | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.authoring_round",
        description="저작 회차 한 줄 실행 — 런북 [A]~[L] 오케스트레이터(EOS-208)",
    )
    parser.add_argument("--config", type=Path, required=True, help="회차 설정 YAML")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stage", choices=STAGES, help="이 단계 하나만 실행(선행 조건 검사 유지)")
    group.add_argument("--from", dest="start", choices=STAGES, help="이 단계부터 끝까지 실행")
    parser.add_argument(
        "--worktree", type=Path, default=None, help="설정의 worktree 값 대신 쓸 경로"
    )
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 다음에 할 일만 보인다")
    parser.add_argument(
        "--release-unevidenced",
        action="store_true",
        help="호출 기록(대장·genlog)이 없는 시도 예약을 풀어 준다(사람 판단 · 이력에 남음)",
    )
    args = parser.parse_args(argv)
    boundaries = io or default_boundaries()
    try:
        cfg = load_round_config(args.config, worktree_override=args.worktree)
    except RoundConfigError as exc:
        print(f"CONFIG_ERROR={exc}", file=boundaries.out, flush=True)
        return 2
    return AuthoringRound(cfg, boundaries, dry_run=args.dry_run).run(
        only=args.stage, start=args.start, release_unevidenced=args.release_unevidenced
    )


if __name__ == "__main__":
    raise SystemExit(main())
