"""저작 회차 설정 파일 로더 (EOS-208 ②) — 회차 하나를 기술하는 YAML을 검증된 값 객체로 읽는다.

무엇을 담는가
-------------
EOS-197 런북([A]~[L])에서 블록마다 손으로 박혀 있던 값 — 회차 이름·좌석(모델·목표 CU·시도
예산)·앵커 spec·시드 코퍼스·Ollama 타임아웃·검수자·산출물 브랜치 — 을 파일 하나로 모은다.
다음 회차는 이 파일을 복사해 값만 바꾼다(오케스트레이터 코드는 그대로).

왜 YAML인가: 저장소의 사람 편집 설정(`backlog/`·`anchors.yaml`)이 YAML이다. 로더는
`yaml.safe_load`만 쓴다(임의 객체 역직렬화 금지 — 백엔드 pyyaml 핀 주석과 같은 규칙).

검증은 **전부 fail-loud**다(`RoundConfigError`, CLI exit 2). 특히 유료 좌석(cloud)은 시도 예산
상한이 없으면 거부한다 — 예산 없는 유료 저작은 "목표에 닿을 때까지" 끝없이 돈다(EOS-197
런북이 상한 45를 둔 이유). 오타로 4500을 적는 사고를 막으려 절대 상한도 둔다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 유료 좌석의 시도 예산 절대 상한 — 설정 오타(45 → 450 → 4500)가 그대로 과금이 되지 않게.
# EOS-197 실측 시도당 약 $0.0015라 300건이어도 약 $0.45(약 700원)다.
CLOUD_ATTEMPT_HARD_CAP = 300
# 로컬 좌석도 상한은 둔다(무한 루프 방지) — 비용이 아니라 시간 축이라 더 넉넉하다.
LOCAL_ATTEMPT_HARD_CAP = 1000

SEAT_KINDS = ("local", "cloud")
REVIEW_UIS = ("gui", "terminal")
# 클라우드 좌석이 쓸 수 있는 셀렉터 값 — ARCH-66(2026-12-31까지 Anthropic API 중단)에 따라
# 이 오케스트레이터는 openrouter만 받는다. 다른 좌석이 필요해지면 여기를 넓히는 결정이 먼저다.
CLOUD_PROVIDERS = ("openrouter",)


class RoundConfigError(ValueError):
    """설정 파일이 계약을 어겼다 — 사유에는 필드 경로만 싣는다(값 원문은 최소화)."""


# 매핑마다 받는 키 — 모르는 키는 거부한다(오타 `attempt_budjet`이 검사를 조용히 끄지 않게).
_TOP_KEYS = frozenset(
    {
        "schema_version",
        "round_name",
        "task_id",
        "worktree",
        "output_root",
        "ollama_request_timeout_s",
        "seats",
        "anchors",
        "seeds",
        "authoring_args",
        "expected_subject",
        "expected_slug_prefix",
        "min_queue_cu",
        "review",
        "deliver",
    }
)
_SEAT_KEYS = frozenset(
    {
        "name",
        "kind",
        "model",
        "target_cu",
        "attempt_budget",
        "attempt_timeout_s",
        "authoring_tier",
        "provider",
        "subscription",
        "budget_krw",
        "expected_jurisdiction",
        "expected_allowed_providers",
    }
)
_ANCHOR_KEYS = frozenset({"spec_id", "standard_code", "difficulty", "topic_hint"})
_AUTHORING_KEYS = frozenset({"avoid_recent", "canary", "abort_window"})
_REVIEW_KEYS = frozenset({"reviewer_id", "ui", "timeout_s"})
_DELIVER_KEYS = frozenset({"branch", "commit_message"})


def _no_unknown_keys(data: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(str(k) for k in data if k not in allowed)
    if unknown:
        raise RoundConfigError(f"{where}: 모르는 키 {unknown} — 오타인지 확인하세요")


@dataclass(frozen=True)
class AnchorSpec:
    """spec 순환 계획 한 줄(저작 CLI `--spec-file` JSONL 한 행과 같은 4필드)."""

    spec_id: str
    standard_code: str
    difficulty: float
    topic_hint: str

    def as_plan_row(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "standard_code": self.standard_code,
            "difficulty": self.difficulty,
            "topic_hint": self.topic_hint,
        }


@dataclass(frozen=True)
class SeatConfig:
    """저작 좌석 하나 — 산출 폴더 `<output_root>/<round_name>-<name>/`에 쌓인다."""

    name: str
    kind: str  # local | cloud
    model: str
    target_cu: int
    attempt_budget: int
    attempt_timeout_s: float
    authoring_tier: str | None = None  # local 전용(mid|quality)
    provider: str | None = None  # cloud 전용(openrouter)
    subscription: str | None = None  # cloud 전용 라우팅 신호
    budget_krw: float | None = None  # cloud 전용 라우팅 신호(지출 상한이 아니다)
    expected_jurisdiction: str | None = None  # cloud 전용(예: us)
    expected_allowed_providers: tuple[str, ...] = ()  # cloud 전용(런북 [C] ALLOWED=deepinfra)


@dataclass(frozen=True)
class RoundConfig:
    """검증을 마친 회차 설정."""

    source_path: Path
    source_sha256: str
    round_name: str
    task_id: str
    worktree: Path
    output_root: str  # 워크트리 기준 상대 경로(posix 표기)
    ollama_request_timeout_s: float
    seats: tuple[SeatConfig, ...]
    anchors: tuple[AnchorSpec, ...]
    seeds: tuple[str, ...]  # 워크트리 기준 상대 경로
    avoid_recent: int
    canary: int
    abort_window: int
    expected_subject: str | None
    expected_slug_prefix: str | None
    min_queue_cu: int
    reviewer_id: str
    review_ui: str
    review_timeout_s: float
    deliver_branch: str
    commit_message: str

    # ── 경로 파생(한 곳에서만 계산 — 단계마다 다시 조립하면 갈라진다) ──
    def runs_dir(self) -> Path:
        return self.worktree / self.output_root

    def seat_dir(self, seat: SeatConfig) -> Path:
        return self.runs_dir() / f"{self.round_name}-{seat.name}"

    def seat_out(self, seat: SeatConfig) -> Path:
        return self.seat_dir(seat) / "cu.jsonl"

    def review_dir(self) -> Path:
        return self.runs_dir() / f"{self.round_name}-review"

    def queue_path(self) -> Path:
        return self.review_dir() / "canary_review_queue.jsonl"

    def events_path(self) -> Path:
        return self.review_dir() / "canary_review_events.jsonl"

    def verdicts_path(self) -> Path:
        return self.review_dir() / "canary_review_verdicts.jsonl"

    def state_path(self) -> Path:
        return self.review_dir() / "round_state.json"

    def spec_plan_path(self) -> Path:
        return self.review_dir() / "spec_plan.jsonl"

    def round_dirs(self) -> tuple[Path, ...]:
        """이 회차가 쓰는 폴더 전부 — deliver가 커밋하는 범위이자 '산출물 안'의 정의."""
        return tuple(self.seat_dir(s) for s in self.seats) + (self.review_dir(),)

    def seats_of(self, kind: str) -> tuple[SeatConfig, ...]:
        return tuple(s for s in self.seats if s.kind == kind)

    def spec_plan_text(self) -> str:
        """저작 CLI `--spec-file`에 줄 JSONL 본문(결정적 — 같은 설정이면 같은 바이트)."""
        return "".join(
            json.dumps(a.as_plan_row(), ensure_ascii=False, sort_keys=True) + "\n"
            for a in self.anchors
        )


def _req(data: dict[str, Any], key: str, where: str) -> Any:
    if key not in data or data[key] is None:
        raise RoundConfigError(f"{where}.{key}: 필수 필드가 없다")
    return data[key]


def _as_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoundConfigError(f"{where}: 비어 있지 않은 문자열이어야 한다")
    return value.strip()


def _as_int(value: Any, where: str, *, minimum: int, maximum: int | None = None) -> int:
    # bool은 int의 하위형이라 명시적으로 막는다(`true`를 1로 받는 실수 방지).
    if isinstance(value, bool) or not isinstance(value, int):
        raise RoundConfigError(f"{where}: 정수여야 한다")
    if value < minimum or (maximum is not None and value > maximum):
        upper = "" if maximum is None else f" 이하({maximum})"
        raise RoundConfigError(f"{where}: {minimum} 이상{upper}이어야 한다(값 {value})")
    return value


def _as_float(value: Any, where: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoundConfigError(f"{where}: 숫자여야 한다")
    number = float(value)
    if number < minimum:
        raise RoundConfigError(f"{where}: {minimum} 이상이어야 한다(값 {number})")
    return number


def _parse_seat(raw: Any, index: int, ollama_timeout_s: float) -> SeatConfig:
    where = f"seats[{index}]"
    if not isinstance(raw, dict):
        raise RoundConfigError(f"{where}: 매핑이어야 한다")
    _no_unknown_keys(raw, _SEAT_KEYS, where)
    name = _as_str(_req(raw, "name", where), f"{where}.name")
    if not name.replace("-", "").replace("_", "").isalnum() or not name.isascii():
        raise RoundConfigError(f"{where}.name: 영문·숫자·-·_만 쓴다(폴더 이름이 된다)")
    kind = _as_str(_req(raw, "kind", where), f"{where}.kind")
    if kind not in SEAT_KINDS:
        raise RoundConfigError(f"{where}.kind: {SEAT_KINDS} 중 하나여야 한다")
    model = _as_str(_req(raw, "model", where), f"{where}.model")
    target = _as_int(_req(raw, "target_cu", where), f"{where}.target_cu", minimum=1)
    cap = CLOUD_ATTEMPT_HARD_CAP if kind == "cloud" else LOCAL_ATTEMPT_HARD_CAP
    # 시도 예산은 좌석 종류와 무관하게 필수다 — 특히 cloud(유료)는 상한 없는 저작을 허용하지 않는다.
    budget = _as_int(
        _req(raw, "attempt_budget", where), f"{where}.attempt_budget", minimum=1, maximum=cap
    )
    default_timeout = ollama_timeout_s * 2 + 60 if kind == "local" else 180.0
    attempt_timeout = _as_float(
        raw.get("attempt_timeout_s", default_timeout), f"{where}.attempt_timeout_s", minimum=1.0
    )
    if kind == "local":
        tier = _as_str(raw.get("authoring_tier", "quality"), f"{where}.authoring_tier")
        if tier not in ("mid", "quality"):
            raise RoundConfigError(f"{where}.authoring_tier: mid|quality 중 하나여야 한다")
        for key in ("provider", "subscription", "budget_krw", "expected_allowed_providers"):
            if raw.get(key) is not None:
                # 로컬 좌석에 클라우드 신호를 주면 라우터가 클라우드로 보낼 수 있다(유료 호출 위험).
                raise RoundConfigError(f"{where}.{key}: local 좌석에는 쓸 수 없다")
        return SeatConfig(
            name=name,
            kind=kind,
            model=model,
            target_cu=target,
            attempt_budget=budget,
            attempt_timeout_s=attempt_timeout,
            authoring_tier=tier,
        )
    provider = _as_str(_req(raw, "provider", where), f"{where}.provider")
    if provider not in CLOUD_PROVIDERS:
        raise RoundConfigError(f"{where}.provider: {CLOUD_PROVIDERS} 중 하나여야 한다(ARCH-66)")
    subscription = _as_str(_req(raw, "subscription", where), f"{where}.subscription")
    budget_krw = _as_float(_req(raw, "budget_krw", where), f"{where}.budget_krw", minimum=0.0)
    jurisdiction = _as_str(
        _req(raw, "expected_jurisdiction", where), f"{where}.expected_jurisdiction"
    )
    if raw.get("authoring_tier") is not None:
        raise RoundConfigError(f"{where}.authoring_tier: cloud 좌석에는 쓰이지 않는다")
    allowed_raw = _req(raw, "expected_allowed_providers", where)
    if not isinstance(allowed_raw, list) or not allowed_raw:
        raise RoundConfigError(
            f"{where}.expected_allowed_providers: 비어 있지 않은 목록이어야 한다"
        )
    allowed = tuple(
        _as_str(v, f"{where}.expected_allowed_providers[{i}]") for i, v in enumerate(allowed_raw)
    )
    return SeatConfig(
        name=name,
        kind=kind,
        model=model,
        target_cu=target,
        attempt_budget=budget,
        attempt_timeout_s=attempt_timeout,
        provider=provider,
        subscription=subscription,
        budget_krw=budget_krw,
        expected_jurisdiction=jurisdiction,
        expected_allowed_providers=allowed,
    )


def parse_round_config(
    data: Any, *, source_path: Path, source_sha256: str, worktree_override: Path | None = None
) -> RoundConfig:
    """YAML 파싱 결과(매핑) → `RoundConfig`. 계약 위반은 `RoundConfigError`."""
    if not isinstance(data, dict):
        raise RoundConfigError("최상위가 매핑이어야 한다")
    _no_unknown_keys(data, _TOP_KEYS, "config")
    version = data.get("schema_version")
    if version != 1:
        raise RoundConfigError("schema_version: 1이어야 한다")
    round_name = _as_str(_req(data, "round_name", "config"), "round_name")
    if not round_name.isascii() or " " in round_name or "/" in round_name or "\\" in round_name:
        raise RoundConfigError("round_name: 공백·경로 구분자 없는 영문 이름이어야 한다")
    task_id = _as_str(_req(data, "task_id", "config"), "task_id")
    worktree_raw = (
        str(worktree_override)
        if worktree_override is not None
        else _as_str(_req(data, "worktree", "config"), "worktree")
    )
    output_root = _as_str(data.get("output_root", "data/runs"), "output_root").replace("\\", "/")
    if output_root.startswith("/") or ".." in output_root.split("/"):
        raise RoundConfigError("output_root: 워크트리 안의 상대 경로여야 한다")
    timeout = _as_float(
        data.get("ollama_request_timeout_s", 180.0), "ollama_request_timeout_s", minimum=1.0
    )
    seats_raw = _req(data, "seats", "config")
    if not isinstance(seats_raw, list) or not seats_raw:
        raise RoundConfigError("seats: 좌석이 1개 이상인 목록이어야 한다")
    seats = tuple(_parse_seat(raw, i, timeout) for i, raw in enumerate(seats_raw))
    names = [s.name for s in seats]
    if len(set(names)) != len(names) or "review" in names:
        raise RoundConfigError("seats[].name: 서로 달라야 하고 'review'는 쓸 수 없다")
    anchors_raw = _req(data, "anchors", "config")
    if not isinstance(anchors_raw, list) or not anchors_raw:
        raise RoundConfigError("anchors: spec이 1개 이상인 목록이어야 한다")
    anchors: list[AnchorSpec] = []
    for i, raw in enumerate(anchors_raw):
        where = f"anchors[{i}]"
        if not isinstance(raw, dict):
            raise RoundConfigError(f"{where}: 매핑이어야 한다")
        _no_unknown_keys(raw, _ANCHOR_KEYS, where)
        anchors.append(
            AnchorSpec(
                spec_id=_as_str(_req(raw, "spec_id", where), f"{where}.spec_id"),
                standard_code=_as_str(_req(raw, "standard_code", where), f"{where}.standard_code"),
                difficulty=_as_float(
                    _req(raw, "difficulty", where), f"{where}.difficulty", minimum=1.0
                ),
                topic_hint=_as_str(_req(raw, "topic_hint", where), f"{where}.topic_hint"),
            )
        )
    if len({a.spec_id for a in anchors}) != len(anchors):
        raise RoundConfigError("anchors[].spec_id: 서로 달라야 한다")
    seeds_raw = data.get("seeds", [])
    if not isinstance(seeds_raw, list):
        raise RoundConfigError("seeds: 목록이어야 한다")
    seeds = tuple(_as_str(s, f"seeds[{i}]").replace("\\", "/") for i, s in enumerate(seeds_raw))
    authoring = data.get("authoring_args", {}) or {}
    if not isinstance(authoring, dict):
        raise RoundConfigError("authoring_args: 매핑이어야 한다")
    review = _req(data, "review", "config")
    deliver = _req(data, "deliver", "config")
    if not isinstance(review, dict) or not isinstance(deliver, dict):
        raise RoundConfigError("review·deliver: 매핑이어야 한다")
    _no_unknown_keys(authoring, _AUTHORING_KEYS, "authoring_args")
    _no_unknown_keys(review, _REVIEW_KEYS, "review")
    _no_unknown_keys(deliver, _DELIVER_KEYS, "deliver")
    review_ui = _as_str(review.get("ui", "gui"), "review.ui")
    if review_ui not in REVIEW_UIS:
        raise RoundConfigError(f"review.ui: {REVIEW_UIS} 중 하나여야 한다")
    branch = _as_str(_req(deliver, "branch", "deliver"), "deliver.branch")
    if branch in ("main", "master") or branch.startswith("-") or " " in branch:
        raise RoundConfigError("deliver.branch: main이 아닌 새 브랜치 이름이어야 한다")
    expected_subject = data.get("expected_subject")
    expected_prefix = data.get("expected_slug_prefix")
    return RoundConfig(
        source_path=source_path,
        source_sha256=source_sha256,
        round_name=round_name,
        task_id=task_id,
        worktree=Path(worktree_raw),
        output_root=output_root,
        ollama_request_timeout_s=timeout,
        seats=seats,
        anchors=tuple(anchors),
        seeds=seeds,
        avoid_recent=_as_int(
            authoring.get("avoid_recent", 10), "authoring_args.avoid_recent", minimum=0, maximum=20
        ),
        canary=_as_int(authoring.get("canary", 0), "authoring_args.canary", minimum=0),
        abort_window=_as_int(
            authoring.get("abort_window", 0), "authoring_args.abort_window", minimum=0
        ),
        expected_subject=(
            None if expected_subject is None else _as_str(expected_subject, "expected_subject")
        ),
        expected_slug_prefix=(
            None if expected_prefix is None else _as_str(expected_prefix, "expected_slug_prefix")
        ),
        min_queue_cu=_as_int(data.get("min_queue_cu", 15), "min_queue_cu", minimum=1),
        reviewer_id=_as_str(_req(review, "reviewer_id", "review"), "review.reviewer_id"),
        review_ui=review_ui,
        review_timeout_s=_as_float(
            review.get("timeout_s", 8 * 3600.0), "review.timeout_s", minimum=60.0
        ),
        deliver_branch=branch,
        commit_message=_as_str(
            deliver.get("commit_message", f"{task_id}: {round_name} 저작 회차 산출물"),
            "deliver.commit_message",
        ),
    )


def load_round_config(path: Path, *, worktree_override: Path | None = None) -> RoundConfig:
    """설정 파일을 읽어 검증한다. 읽기·파싱 실패도 `RoundConfigError`(예외 타입명 동반)."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise RoundConfigError(f"설정 파일을 읽지 못했다({type(exc).__name__}): {path}") from exc
    try:
        # utf-8-sig: Windows 메모장·PowerShell 5.1이 붙이는 BOM을 허용한다.
        text = raw_bytes.decode("utf-8-sig")
        data = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RoundConfigError(f"설정 파일 파싱 실패({type(exc).__name__}): {path}") from exc
    return parse_round_config(
        data,
        source_path=path,
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        worktree_override=worktree_override,
    )
