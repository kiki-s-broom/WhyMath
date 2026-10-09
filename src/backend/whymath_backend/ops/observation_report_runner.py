"""관측 리포트 러너 — 리포트 CLI를 실제로 돌리고 "돌았는가"를 산출물로 남긴다 (OPS-19).

왜 이 모듈이 있는가
-------------------
`*_report.py` 관측 리포트 CLI는 20개인데, 2026-10-08 실측으로 **러너(CI 스텝·cron·compose
서비스)를 가진 것은 3개뿐**이었다(`eos_unit_structure_observation_report`·`weekly_metrics_report`·
`cost_report`). 나머지 17개는 산출이 0회였고, 그래서 "측정한 적 없음"이 "문제 없음"으로 읽혔다.
이 모듈은 그 17개 중 **자동 실행이 성립하는 16개**에 러너를 준다. 신규 리포트 로직은 0 —
기존 CLI를 `python -m`으로 부르기만 한다(SEC-12 `retention-purge` 선례와 같은 원칙).

세 부류 — 섞지 않는다 (acceptance ③)
------------------------------------
실측(2026-10-08, DB 없는 환경에서 17개를 전부 직접 실행)으로 갈랐다. 모듈 위치(`harness/` vs
`ops/`)가 아니라 **어디서 완전하게 돌 수 있는가**가 기준이다 — 위치와 DB 의존은 일치하지 않는다
(`harness/` 안에도 DB를 요구하는 것이 9개다).

- `ci` — 저장소 체크아웃만 필요(DB 0·인자 0). `harness-integrity` 잡이 돌린다.
- `db` — 도달 가능한 DB가 필요하고, 읽는 파일은 이미지에 동봉되는 `data/`뿐이다.
  `docker-compose.prod.yml`의 `observation-reports` 서비스가 같은 이미지로 돌린다.
- `checkout_db` — 저장소 체크아웃(`src/`·`tests/`)과 DB가 **둘 다** 필요하다. CI 잡엔 DB가 없고
  배포 이미지엔 `tests/`가 없어 어느 자동 경로도 완전하지 않다 — 운영자 머신(런북)만 돌린다.
  이미지에서 돌리면 파일 부재가 "0건"으로 읽힌다(그래서 `db`에 섞지 않았다).

섞으면 안 되는 이유: DB 필요 리포트를 DB 없는 CI에 넣으면 "접속 실패"가 매 PR마다 나거나,
리포트가 접속 실패를 삼키면 "0건"이 된다 — 이 태스크가 고치려는 위장을 그대로 재현한다.

"0을 보고함" ≠ "돌지 못함" (acceptance ④ · ops/cost_probe 이중 회계 승계)
------------------------------------------------------------------------
리포트 CLI의 종료 코드 관례는 0=산출 성공(수치가 0이어도), 비-0=실행 오류다. 이 러너는 그것을
**서로 다른 상태값**으로 매니페스트에 남긴다.

- `ran_ok`      — 종료 코드 0. 수치가 0이어도 이 값이다(관측 전용 — 좋고 나쁨을 판정하지 않는다)
- `run_failed`  — 종료 코드 비-0. 측정값이 없다. stderr 꼬리(비밀번호 가림)를 원인으로 남긴다
- `run_timeout` — 제한 시간 초과. 멈춘 사실 자체가 증거다
- `spawn_error` — 프로세스를 띄우지 못함(인터프리터·모듈 경로 문제)
- `running`     — 시작했으나 끝나지 않음. **최종 매니페스트에 남아 있으면 러너가 중간에 죽었다는
  증거**다(리포트마다 즉시 flush하므로 마지막 한 번 저장 방식이 잃는 증거를 남긴다)

러너 종료 코드: 전부 `ran_ok`면 0, 하나라도 아니면 1, 인자 오류는 2(argparse). 대상 부류에 리포트가
0개여도 1이다 — 스캔 0건은 통과가 아니라 실패다.

의도적으로 하지 않는 것 (정직한 공백)
-------------------------------------
- 리포트 **내용**의 좋고 나쁨은 판정하지 않는다(게이트화는 범위 밖). 수치가 나빠도 exit 0이다.
- `ran_ok`는 "프로세스가 0으로 끝났다"일 뿐 "측정이 완전했다"가 아니다. 리포트가 본문에
  `미측정`이라 쓰고 exit 0으로 끝나는 설계(예: `phase1_structure_report`의 DB 지표)는 본문에
  남는다 — 이 러너는 본문을 해석하지 않는다.
- 실행 결과의 **전달**(Slack·이메일)은 `OPS-30` 몫이다. 이 러너는 산출물과 종료 코드까지만 낸다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "CLASSES",
    "CLASS_CHECKOUT_DB",
    "CLASS_CI",
    "CLASS_DB",
    "ELSEWHERE",
    "INPUT_DEPENDENT",
    "REPORTS",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_RUNNING",
    "STATUS_SPAWN",
    "STATUS_TIMEOUT",
    "ReportSpec",
    "main",
    "redact",
    "run_reports",
    "select",
]

CLASS_CI = "ci"
CLASS_DB = "db"
CLASS_CHECKOUT_DB = "checkout_db"
CLASSES: tuple[str, ...] = (CLASS_CI, CLASS_DB, CLASS_CHECKOUT_DB)

STATUS_OK = "ran_ok"
STATUS_FAILED = "run_failed"
STATUS_TIMEOUT = "run_timeout"
STATUS_SPAWN = "spawn_error"
STATUS_RUNNING = "running"

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_S = 300.0
_STDERR_TAIL_CHARS = 2000


@dataclass(frozen=True)
class ReportSpec:
    """러너가 부르는 리포트 1건. `module`은 `whymath_backend.` 접두를 뗀 dotted name이다.

    접두를 뗀 형태는 `declared_unwired_audit`의 CLI 축 키와 같다 — 면제 사전과 1:1 대조용이다.
    """

    module: str
    klass: str
    args: tuple[str, ...] = ()


# 러너가 자동 실행하는 리포트 17건(최초 16건 + 병합 시 PB-10이 추가한 item_calibration 1건).
# 새 `*_report.py`를 만들면 여기·ELSEWHERE·INPUT_DEPENDENT 중 한 곳에 반드시 귀속해야 한다 —
# `tests/backend/ops/test_observation_report_registry.py`가 전수 강제한다.
REPORTS: tuple[ReportSpec, ...] = (
    # ── ci: 저장소 체크아웃만 필요(2026-10-08 DB 없이 rc=0 실측) ──────────────────
    ReportSpec("harness.concept_reach_report", CLASS_CI),
    ReportSpec("harness.curriculum_revision_crosswalk_report", CLASS_CI),
    ReportSpec("harness.formula_reach_report", CLASS_CI),
    ReportSpec("harness.learning_path_orderability_report", CLASS_CI),
    ReportSpec("harness.visualization_reach_report", CLASS_CI),
    # ── db: 실 DB 필요(2026-10-08 DB 없이 rc=2 — 접속 실패를 정직하게 보고하는 것을 실측) ──
    ReportSpec("harness.assessment_seat_reach_report", CLASS_DB),
    ReportSpec("harness.attempt_grading_shadow_report", CLASS_DB),
    ReportSpec("harness.attempt_skill_event_reach_report", CLASS_DB),
    ReportSpec("harness.distractor_signal_dormancy_report", CLASS_DB),
    ReportSpec("harness.item_calibration_reach_report", CLASS_DB),
    ReportSpec("harness.recommendation_outcome_report", CLASS_DB),
    ReportSpec("harness.standard_attainment_report", CLASS_DB),
    # 접속 실패를 잡지 못하고 트레이스백으로 죽는다(rc=1) — 그래도 비-0이라 `run_failed`로 구분된다.
    ReportSpec("harness.surrogate_baseline_report", CLASS_DB),
    ReportSpec("ops.pedagogy_content_slot_reach_report", CLASS_DB),
    ReportSpec("ops.recommendation_reach_report", CLASS_DB),
    ReportSpec("ops.repeat_recommendation_report", CLASS_DB),
    # ── checkout_db: 저장소 파일(src/·tests/)과 DB가 둘 다 필요 — 운영자 머신 전용 ──
    ReportSpec("ops.phase1_structure_report", CLASS_CHECKOUT_DB),
)

# 이 러너 밖에서 이미 실행 경로를 가진 리포트 → (근거 파일, 그 파일에 있어야 할 문자열).
# 근거는 테스트가 실제 파일을 열어 확인한다 — 주장만으로는 귀속이 아니다.
ELSEWHERE: dict[str, tuple[str, str]] = {
    "harness.eos_unit_structure_observation_report": (
        ".github/workflows/ci.yml",
        "whymath_backend.harness.eos_unit_structure_observation_report",
    ),
    "harness.cross_school_connectivity_report": (
        ".github/workflows/ci.yml",
        "whymath_backend.harness.cross_school_connectivity_report",
    ),
    "ops.weekly_metrics_report": (
        ".github/workflows/weekly-metrics.yml",
        "whymath_backend.ops.weekly_metrics_report",
    ),
    "ops.cost_report": ("scripts/fill_live_cost_table.py", "cost_report"),
}

# 입력 파일 없이는 실행 자체가 성립하지 않는 리포트 → 사유. 자동 러너 대상이 아니다.
INPUT_DEPENDENT: dict[str, str] = {
    "harness.generation_seed_adoption_report": (
        "분모가 실제 생성 배치의 genlog JSONL(위치 인자 필수)이다 — 인자 없이는 argparse 오류로 "
        "죽는다. 상주 입력이 없어 자동 실행하면 '돌지 못함'만 영구히 쌓인다. 운영자가 genlog를 "
        "지정해 돌린다(런북 참조)"
    ),
}

# 자격 정보가 섞여 들어올 수 있는 `scheme://user:password@host` 형태의 비밀번호를 가린다.
_URL_PASSWORD = re.compile(r"(://[^:/\s@]+:)[^@\s]+@")


def redact(text: str) -> str:
    """오류 꼬리에서 접속 문자열의 비밀번호를 가린다(원인은 남기고 비밀은 남기지 않는다)."""
    return _URL_PASSWORD.sub(r"\1***@", text)


def select(klass: str, reports: Sequence[ReportSpec] | None = None) -> list[ReportSpec]:
    """부류에 속한 리포트만 고른다. 알 수 없는 부류는 빈 목록이 아니라 예외다."""
    if klass not in CLASSES:
        raise ValueError(f"알 수 없는 부류 {klass!r} — {CLASSES} 중 하나여야 한다")
    # 기본값을 정의 시점에 묶지 않는다 — 호출 시점의 REPORTS를 읽어야 목록 교체가 반영된다.
    pool = REPORTS if reports is None else reports
    return [spec for spec in pool if spec.klass == klass]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """원자적 교체 — 쓰는 도중 죽어도 읽을 수 없는 반쪽 파일이 남지 않는다."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _child_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    """자식 프로세스 환경 — 출력 인코딩을 UTF-8로 못박는다.

    Windows 한국어 로케일은 파이프 stdout을 cp949로 내보내므로, 명시하지 않으면 한글 본문이
    UTF-8로 저장·해시되는 바이트와 어긋난다.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _run_one(
    spec: ReportSpec,
    out_dir: Path,
    timeout_s: float,
    python: str,
    cwd: Path | None,
    env: Mapping[str, str],
    module_prefix: str,
) -> dict[str, Any]:
    """리포트 1건을 실행해 기록 1건을 돌려준다. 어떤 실패도 예외로 새지 않는다."""
    entry: dict[str, Any] = {
        "report": spec.module,
        "class": spec.klass,
        "status": STATUS_RUNNING,
        "returncode": None,
        "duration_s": None,
        "output_file": None,
        "output_bytes": None,
        "output_sha256": None,
        "stderr_tail": None,
    }
    command = [python, "-m", f"{module_prefix}{spec.module}", *spec.args]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_s,
            cwd=cwd,
            env=dict(env),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        entry["status"] = STATUS_TIMEOUT
        entry["stderr_tail"] = f"제한 시간 {timeout_s:g}초 초과 — 프로세스를 종료했다"
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
    except OSError as exc:
        entry["status"] = STATUS_SPAWN
        entry["stderr_tail"] = redact(f"{type(exc).__name__}: {exc}")[-_STDERR_TAIL_CHARS:]
        stdout = b""
    else:
        stdout = completed.stdout
        entry["returncode"] = completed.returncode
        if completed.returncode == 0:
            entry["status"] = STATUS_OK
        else:
            entry["status"] = STATUS_FAILED
            tail = completed.stderr.decode("utf-8", errors="replace")
            entry["stderr_tail"] = redact(tail)[-_STDERR_TAIL_CHARS:]
    entry["duration_s"] = round(time.monotonic() - started, 2)
    if stdout:
        output_path = out_dir / f"{spec.module}.txt"
        output_path.write_bytes(stdout)
        entry["output_file"] = output_path.name
        entry["output_bytes"] = len(stdout)
        entry["output_sha256"] = hashlib.sha256(stdout).hexdigest()
    return entry


def run_reports(
    specs: Sequence[ReportSpec],
    out_dir: Path,
    *,
    klass: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    python: str | None = None,
    cwd: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    module_prefix: str = "whymath_backend.",
) -> dict[str, Any]:
    """`specs`를 순서대로 실행하고 매니페스트를 돌려준다. 리포트 하나가 끝날 때마다 즉시 flush한다.

    한 리포트의 실패가 뒤 리포트를 막지 않는다 — 전부 돌린 뒤에 종료 코드로 판정한다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    env = _child_env(extra_env)
    interpreter = python or sys.executable
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex[:12],
        "class": klass,
        "started_at": _now(),
        "finished_at": None,
        "complete": False,
        "timeout_s": timeout_s,
        "reports": [],
    }
    _write_manifest(manifest_path, manifest)

    for spec in specs:
        # 시작 전에 `running`을 먼저 남긴다 — 이 리포트 도중에 러너가 죽으면 이 줄이 유일한 증거다.
        manifest["reports"].append(
            {"report": spec.module, "class": spec.klass, "status": "running"}
        )
        _write_manifest(manifest_path, manifest)
        # 결과 flush는 다음 리포트의 시작 전 flush(위)나 마지막 요약 기록이 겸한다.
        manifest["reports"][-1] = _run_one(
            spec, out_dir, timeout_s, interpreter, cwd, env, module_prefix
        )

    statuses = [item["status"] for item in manifest["reports"]]
    manifest["summary"] = {
        "total": len(statuses),
        "ran_ok": statuses.count(STATUS_OK),
        "not_ok": len(statuses) - statuses.count(STATUS_OK),
    }
    manifest["finished_at"] = _now()
    manifest["complete"] = True
    _write_manifest(manifest_path, manifest)
    return manifest


def _render(manifest: Mapping[str, Any]) -> str:
    lines = [f"관측 리포트 러너 — 부류={manifest['class']} run_id={manifest['run_id']}"]
    for item in manifest["reports"]:
        suffix = ""
        if item["status"] != STATUS_OK:
            tail = (item.get("stderr_tail") or "").strip().splitlines()
            suffix = f" — {tail[-1][:160]}" if tail else ""
        lines.append(
            f"  [{item['status']:<11}] {item['report']} "
            f"(rc={item['returncode']}, {item['duration_s']}s){suffix}"
        )
    summary = manifest["summary"]
    lines.append(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "class": manifest["class"],
                "total": summary["total"],
                "ran_ok": summary["ran_ok"],
                "not_ok": summary["not_ok"],
            },
            ensure_ascii=False,
        )
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.observation_report_runner",
        description=(
            "관측 리포트 CLI를 부류별로 실행하고 실행 여부를 manifest.json으로 남긴다. "
            "종료 코드: 0=전부 ran_ok(수치가 0이어도), 1=하나라도 돌지 못함 또는 대상 0건."
        ),
    )
    parser.add_argument("--class", dest="klass", required=True, choices=CLASSES)
    parser.add_argument("--out", dest="out_dir", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="리포트당 초")
    parser.add_argument("--cwd", type=Path, default=None, help="자식 프로세스 작업 디렉터리")
    args = parser.parse_args(argv)

    specs = select(args.klass)
    if not specs:
        # 스캔 0건은 통과가 아니다 — 부류가 비었다면 목록이 잘못 편집된 것이다.
        sys.stderr.write(f"부류 {args.klass!r}에 리포트가 0건이다 — REPORTS 목록을 확인하라\n")
        return 1
    manifest = run_reports(
        specs, args.out_dir, klass=args.klass, timeout_s=args.timeout, cwd=args.cwd
    )
    sys.stdout.write(_render(manifest))
    return 0 if manifest["summary"]["not_ok"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
