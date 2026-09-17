"""데이터 접근 계층 감사 — ORM 세션·연결 직접 조작 실측 + baseline 정본 (ARCH-48).

## 이 파일이 답하는 질문

"Repository 계층 없이 api·l1~l4가 ORM 세션을 직접 잡는데, 그것을 재는 계약·감사가 0건이다."
— `docs/reviews/eos_source_docs_gap_review_2026-08-31.md:154`(36번 행)이 2026-08-31에 관측하고
2주간 소유자가 없던 갭. **이 스크립트와 `tests/infra/test_data_access_layer_contract.py`가
그 소유자다.** 처분 판정과 근거는 `docs/architecture/data_access_layer_disposition.md`.

## 처분 = (b) baseline 동결 + 신규 증가만 차단

실측 118파일(아래 `BASELINE`)은 Repository 계층으로 수렴시키기엔 너무 크다 — (a)를 지금 선언하면
118건의 **만료 없는 유예**가 생긴다(CLAUDE.md 금기). 그래서 현행을 관례로 인정하되 집합으로
얼린다. 늘면 RED, 줄면 RED(ratchet 지시) — `test_eos_dependency_direction.py`의
`CORE_PULL_BASELINE` 패턴과 동형이며, **만료가 날짜가 아니라 기계**인 형태다.

## ⚠️ 정본화 ≠ 집행

이 스크립트는 **측정만** 한다(계측기). 어떤 코드도 이 파일 때문에 차단되지 않는다.
집행 지점은 둘이며 축이 다르다:

| 축 | 집행 장치 | 무엇을 막나 |
|---|---|---|
| **호출 축** | `tests/infra/test_data_access_layer_contract.py` (CI `backend` 잡 pytest) | baseline 밖 파일이 세션·연결을 직접 조작하는 것 |
| **import 축** | `src/backend/pyproject.toml` forbidden 계약 (CI `backend` 잡 `lint-imports`) | 깨끗한 4계층(`schema`·`lang`·`l5`·`l6`)이 `sqlalchemy`·`whymath_backend.db`를 import하는 것 |

import-linter만으로는 호출 축을 볼 수 없다 — import 그래프 도구라 `session.execute(...)`라는
**메서드 호출**을 표현할 문법이 없다. 반대로 AST 가드만으로는 "아직 한 줄도 안 쓴 계층이
sqlalchemy를 끌어오기 시작하는" 순간을 import 시점에 못 막는다. 그래서 둘 다 둔다.

## 무엇을 세는가 (그리고 왜 정규식이 아닌가)

세션·연결 **수신자 이름**(`session`·`db`·`conn` 등, `self._session` 포함) 위의 SQLAlchemy 세션
메서드 호출을 AST로 센다. 정규식(`session\\.(query|execute|…)`)은 주석·문자열·`seen.add(...)`
같은 동명이인을 함께 세므로 baseline의 근거가 될 수 없다 — 실측에서 `.add(` 233건 중 대다수가
`set.add`였다.

**회피 차단**: 수신자 이름 목록에 기대는 판정은 "`session`을 `sesh`로 바꾸면 통과"라는 구멍을
낳는다. 그래서 `AsyncSession`/`Session`/`AsyncConnection`/`Connection`으로 **주석된 이름**을
따로 수집해 목록 밖 이름이 있으면 보고한다(가드는 그것을 RED로 만든다). 주석의 *머리* 타입만
본다 — `async_sessionmaker[AsyncSession]`은 세션 팩토리이지 세션이 아니다.

사용법:
    python3 scripts/analysis/data_access_layer_audit.py
    python3 scripts/analysis/data_access_layer_audit.py --json out.json

종료코드: 0 = 스캔 성공(baseline 일치 여부와 무관) · 1 = 스캔 **자체**가 실패(측정 불가).
  baseline 불일치로 exit 1을 내지 않는 이유: 이 파일은 게이트가 아니라 계측기다(위 표).
  단 **대상 0건은 exit 1**이다 — 아무것도 못 찾은 전수 스캔은 "위반 없음"이 아니라 측정 실패다.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from collections import defaultdict
from typing import Callable

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# ── 무엇을 데이터 접근으로 볼 것인가 ──────────────────────────────────────────
# 세션·연결로 쓰이는 수신자 이름. 선행 밑줄은 무시해 비교한다(`self._session` = `session`).
SESSION_RECEIVER_NAMES: frozenset[str] = frozenset(
    {"session", "db", "db_session", "async_session", "sess", "conn", "connection"}
)

# SQLAlchemy 세션/연결 메서드. ARCH-48 태스크가 적은 5종(query·execute·scalars·add·commit)에
# 세션 수명주기(commit·flush·rollback·refresh)와 2.0 스타일 조회(scalar_one 등)를 더했다 —
# 5종만 보면 `session.flush()`만 쓰는 신규 파일이 조용히 통과한다.
SESSION_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "query",
        "execute",
        "scalars",
        "scalar",
        "scalar_one",
        "scalar_one_or_none",
        "add",
        "add_all",
        "commit",
        "flush",
        "refresh",
        "merge",
        "rollback",
        "delete",
        "get",
        "stream",
        "stream_scalars",
    }
)

# 이 타입으로 주석된 이름은 세션·연결이다 — 수신자 이름 목록 밖이면 회피 신호로 본다.
SESSION_ANNOTATION_NAMES: frozenset[str] = frozenset(
    {"AsyncSession", "Session", "AsyncConnection", "Connection"}
)

# ── 깨끗한 계층 (import 축 — 유예 없이 0으로 동결) ───────────────────────────
# 2026-09-16 실측에서 sqlalchemy import·`whymath_backend.db` import·세션 호출이 **전부 0건**인
# 구역. 유예가 필요 없으므로 baseline이 아니라 금지다. 집행은 pyproject.toml forbidden 계약이며
# 이 목록과 계약의 정합을 가드가 동결한다(계약만 고치고 여기를 안 고치면 RED).
CLEAN_LAYERS: tuple[str, ...] = ("schema", "lang", "l5", "l6")

# ── baseline (처분 (b)의 정본) ───────────────────────────────────────────────
# 판정 기준: main 0f12e76af4ab2a48e266d47403779b182be9da4b (2026-09-16)
# key = `whymath_backend/` 아래 첫 경로 조각(계층) · value = 그 계층의 파일 집합(POSIX 상대경로).
# 단일 파일 모듈(`security.py` 등)은 "root".
#
# **늘리지 마라.** 새 파일이 여기에 추가된다는 것은 데이터 접근을 또 한 곳에 퍼뜨렸다는 뜻이며,
# 그 편집이 곧 "이 파일은 DB를 직접 잡는다"라는 서면 선언이 된다(리뷰에서 보이게 하는 것이 목적).
# 줄었으면 반드시 여기서 지운다 — 가드가 정확한 일치를 양방향으로 재므로 baseline이 썩지 않는다.
BASELINE: dict[str, frozenset[str]] = {
    "api": frozenset(
        {
            "api/_auth.py",
            "api/_concept_orchestration.py",
            "api/_device_store.py",
            "api/auth.py",
            "api/coach.py",
            "api/concepts.py",
            "api/curricula.py",
            "api/gating.py",
            "api/interactions.py",
            "api/me.py",
            "api/problems.py",
            "api/reports.py",
            "api/study.py",
            "api/users.py",
        }
    ),
    "db": frozenset(
        {
            "db/schema_version.py",
        }
    ),
    "harness": frozenset(
        {
            "harness/assessment_seat_reach_report.py",
            "harness/attempt_grading_shadow_report.py",
            "harness/attempt_skill_event_reach_report.py",
            "harness/attempt_skill_reach_probe.py",
            "harness/distractor_signal_dormancy_report.py",
            "harness/learning_metrics_rollup_cli.py",
            "harness/pilot_kpi_baseline.py",
            "harness/qa_pipeline.py",
            "harness/recommendation_outcome_report.py",
            "harness/standard_attainment_report.py",
            "harness/wh1_evaluation.py",
        }
    ),
    "l1": frozenset(
        {
            "l1/atom_graph/atom_backend_concept.py",
            "l1/atom_graph/atom_backend_edge.py",
            "l1/atom_graph/atom_node_projection.py",
            "l1/atom_graph/axis.py",
            "l1/atom_graph/embedding.py",
            "l1/atom_probe/projection.py",
            "l1/concept_atom_crosswalk/transfer.py",
            "l1/concept_content/projection.py",
            "l1/concept_content/resolve.py",
            "l1/concept_graph/backend_concept.py",
            "l1/concept_graph/backend_edge.py",
            "l1/concept_graph/embedding.py",
            "l1/concept_graph/node_projection.py",
            "l1/concept_visual_style/overlay.py",
            "l1/concept_visualization/overlay.py",
            "l1/curriculum/curriculum_loader.py",
            "l1/curriculum/curriculum_resolve.py",
            "l1/formula_graph/formula_node_projection.py",
            "l1/misconception/catalog_loader.py",
            "l1/misconception/crosslink_loader.py",
            "l1/misconception/crosslink_resolve.py",
            "l1/misconception/resolve.py",
            "l1/pedagogy/pack_loader.py",
            "l1/pedagogy/unit_compiler.py",
            "l1/problem_bank/embedding.py",
            "l1/problem_bank/populate.py",
            "l1/problem_bank/probe_candidates.py",
            "l1/problem_type_graph/problem_type_node_projection.py",
            "l1/rights/gateway.py",
            "l1/skill_graph/resolve.py",
            "l1/skill_graph/skill_node_projection.py",
            "l1/standards/alignment_query.py",
            "l1/standards/criteria_loader.py",
            "l1/standards/learning_map.py",
            "l1/standards/standard_loader.py",
            "l1/strategy_graph/strategy_node_projection.py",
        }
    ),
    "l2": frozenset(
        {
            "l2/ability_estimation.py",
            "l2/ability_tracking.py",
            "l2/attempt_skill_event.py",
            "l2/concept_diagnosis.py",
            "l2/evidence_event_store.py",
            "l2/item_calibration.py",
            "l2/learner_state.py",
            "l2/learning_event_trace.py",
            "l2/learning_metrics_rollup.py",
            "l2/learning_path.py",
            "l2/mastery_tracking.py",
            "l2/pedagogy_evidence.py",
            "l2/prerequisite_recommendation.py",
            "l2/recommendation_evidence.py",
            "l2/review_queue.py",
            "l2/skill_mastery_tracking.py",
            "l2/target_progress.py",
        }
    ),
    "l3": frozenset(
        {
            "l3/multi_solution.py",
            "l3/pedagogy/analogy_demand.py",
            "l3/pedagogy/analogy_generator.py",
            "l3/pedagogy/diag_item_projector.py",
            "l3/pedagogy/prescreen.py",
            "l3/pedagogy/review.py",
            "l3/pedagogy/slot_generator.py",
            "l3/solution_path_store.py",
        }
    ),
    "l4": frozenset(
        {
            "l4/misconception/evidence_store.py",
            "l4/misconception/hypothesis_store.py",
            "l4/misconception/semantic/pgvector_index.py",
            "l4/misconception/warmstart.py",
            "l4/pedagogy/adaptive/effectiveness.py",
            "l4/pedagogy/k_type_resolver.py",
        }
    ),
    "ops": frozenset(
        {
            "ops/account_bootstrap_cli.py",
            "ops/dialogue_encryption_preflight.py",
            "ops/integrity_violations_gate.py",
            "ops/pedagogy_content_slot_reach_report.py",
            "ops/recommendation_reach_report.py",
            "ops/repeat_recommendation_report.py",
            "ops/role_grant_cli.py",
            "ops/service_health.py",
            "ops/weekly_metrics_report.py",
        }
    ),
    "privacy": frozenset(
        {
            "privacy/audit.py",
            "privacy/authorize.py",
            "privacy/dialogue_content_backfill.py",
            "privacy/erasure.py",
            "privacy/export.py",
            "privacy/retention.py",
            "privacy/retention_purge_cli.py",
            "privacy/student_work_backfill.py",
        }
    ),
    "root": frozenset(
        {
            "app.py",
        }
    ),
    "whs": frozenset(
        {
            "whs/corpus_replay.py",
            "whs/dead_end_store.py",
            "whs/lemma_store.py",
            "whs/node_store.py",
            "whs/path_promotion.py",
            "whs/self_evolution_export_cli.py",
            "whs/solution_bank.py",
        }
    ),
}


# ── 재확인 지점 (만료 없는 유예 금지의 집행) ─────────────────────────────────
# 1차 만료는 **기계**다: 위 baseline은 관측과 정확히 일치해야 하므로, 어떤 리팩터든 이 표를
# 건드리게 된다(줄면 ratchet RED). 유예가 조용히 영구화될 통로가 없다.
#
# 2차 만료는 **날짜**다: 기계적 ratchet은 "이 처분이 여전히 옳은가"를 묻지 않는다 — 118건이
# 그대로 118건이면 영원히 green이다. 그래서 처분 (b) 자체의 재확인 기한을 둔다. 이 날짜가
# 지나면 가드가 RED를 내고, 사람은 셋 중 하나를 해야 한다:
#   ① 처분을 (a)/(c)로 승격하고 이행 태스크를 등재한다
#   ② 재확인했고 (b)가 여전히 옳다고 판단해 이 날짜를 옮긴다(그 커밋이 재확인의 증적이다)
#   ③ baseline을 줄이는 작업에 착수한다
# 날짜를 고르는 근거: EOS 12월 검증(계획서 100 §3.5)이 끝난 직후. 그 검증이 데이터 접근 형태를
# 실사용으로 시험하므로, 재확인에 필요한 실측이 그때 모인다.
BASELINE_REVIEW_BY = "2027-01-31"


def _normalized(name: str) -> str:
    """선행 밑줄을 떼고 비교한다 — `self._session`과 `session`은 같은 것이다."""
    return name.lstrip("_")


_NORMALIZED_RECEIVERS: frozenset[str] = frozenset(
    _normalized(name) for name in SESSION_RECEIVER_NAMES
)


def layer_of(relative_path: pathlib.PurePosixPath) -> str:
    """`whymath_backend/` 아래 첫 경로 조각. 단일 파일 모듈은 "root"."""
    return relative_path.parts[0] if len(relative_path.parts) > 1 else "root"


def _receiver_name(call: ast.Call) -> str | None:
    """`x.method(...)`·`self.x.method(...)`의 수신자 이름. 그 외 형태는 None."""
    if not isinstance(call.func, ast.Attribute):
        return None
    value = call.func.value
    if isinstance(value, ast.Name):
        return value.id
    # `self._session.execute(...)` — 한 단계 self 속성만 본다(더 깊은 체인은 세션이 아니다).
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "self"
    ):
        return value.attr
    return None


def _annotation_heads(node: ast.expr | None) -> set[str]:
    """타입 주석의 *머리* 이름들.

    `AsyncSession` → {AsyncSession} · `AsyncSession | None` → {AsyncSession, None} ·
    `async_sessionmaker[AsyncSession]` → {async_sessionmaker}(**세션 아님** — 팩토리다).
    문자열 주석(`"AsyncSession"`)도 파싱해 본다.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Subscript):
        return _annotation_heads(node.value)
    if isinstance(node, ast.BinOp):
        return _annotation_heads(node.left) | _annotation_heads(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _annotation_heads(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return set()
    return set()


def scan(
    source_root: pathlib.Path, log: Callable[[str], None]
) -> tuple[dict[str, set[str]], dict[str, int], list[tuple[str, str]], list[str]]:
    """전수 스캔.

    반환: (계층별 파일집합, 파일별 호출건수, 회피후보(경로, 이름), 파싱실패 경로).
    """
    files_by_layer: dict[str, set[str]] = defaultdict(set)
    calls_by_file: dict[str, int] = defaultdict(int)
    unknown_receivers: list[tuple[str, str]] = []
    parse_failures: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        relative = pathlib.PurePosixPath(path.relative_to(source_root).as_posix())
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # 침묵 실패 금지 — 예외 타입명을 남긴다(CLAUDE.md).
            log(f"[warn] 파싱 실패 {type(exc).__name__}: {relative} — {exc}")
            parse_failures.append(str(relative))
            continue

        layer = layer_of(relative)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in SESSION_METHOD_NAMES
            ):
                receiver = _receiver_name(node)
                if receiver and _normalized(receiver) in _NORMALIZED_RECEIVERS:
                    files_by_layer[layer].add(str(relative))
                    calls_by_file[str(relative)] += 1

            # 회피 후보 — 세션 타입으로 주석됐는데 수신자 이름 목록 밖인 것.
            target: str | None = None
            if isinstance(node, ast.arg):
                if _annotation_heads(node.annotation) & SESSION_ANNOTATION_NAMES:
                    target = node.arg
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if _annotation_heads(node.annotation) & SESSION_ANNOTATION_NAMES:
                    target = node.target.id
            if target and _normalized(target) not in _NORMALIZED_RECEIVERS:
                unknown_receivers.append((str(relative), target))

    return dict(files_by_layer), dict(calls_by_file), unknown_receivers, parse_failures


def baseline_diff(
    observed: dict[str, set[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """baseline 대비 (신규, 소멸). 신규 = 늘었다(RED) · 소멸 = 줄었다(ratchet 필요)."""
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for layer in sorted(set(observed) | set(BASELINE)):
        now = observed.get(layer, set())
        base = set(BASELINE.get(layer, frozenset()))
        if now - base:
            added[layer] = sorted(now - base)
        if base - now:
            removed[layer] = sorted(base - now)
    return added, removed


def render_markdown(
    observed: dict[str, set[str]],
    calls_by_file: dict[str, int],
    unknown_receivers: list[tuple[str, str]],
    parse_failures: list[str],
) -> str:
    added, removed = baseline_diff(observed)
    lines: list[str] = [
        "# 데이터 접근 계층 감사 (ARCH-48)",
        "",
        f"처분: **(b) baseline 동결 + 신규 증가만 차단** · 재확인 기한 {BASELINE_REVIEW_BY}",
        "",
        "| 계층 | 파일 | 호출 | baseline | 신규 | 소멸 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    total_files = 0
    total_calls = 0
    for layer in sorted(set(observed) | set(BASELINE)):
        files = sorted(observed.get(layer, set()))
        calls = sum(calls_by_file.get(f, 0) for f in files)
        total_files += len(files)
        total_calls += calls
        lines.append(
            f"| {layer} | {len(files)} | {calls} | {len(BASELINE.get(layer, frozenset()))} "
            f"| {len(added.get(layer, []))} | {len(removed.get(layer, []))} |"
        )
    lines.append(f"| **합계** | **{total_files}** | **{total_calls}** | | | |")
    lines += [
        "",
        f"깨끗한 계층(유예 없이 0 동결): {', '.join(CLEAN_LAYERS)}",
        f"회피 후보(세션 타입 주석 · 수신자 목록 밖): {len(unknown_receivers)}건",
        f"파싱 실패: {len(parse_failures)}건",
    ]
    if added:
        lines += ["", "## ❌ baseline 밖 신규 데이터 접근"]
        for layer, files in sorted(added.items()):
            for f in files:
                lines.append(f"- `{f}` ({layer})")
    if removed:
        lines += ["", "## ratchet 필요 (baseline을 줄여라)"]
        for layer, files in sorted(removed.items()):
            for f in files:
                lines.append(f"- `{f}` ({layer})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="데이터 접근 계층 감사 (ARCH-48)")
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    parser.add_argument("--markdown", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)  # 단계별 즉시 flush

    if not args.source.is_dir():
        log(f"[fatal] 소스 루트 없음: {args.source} (cwd={pathlib.Path.cwd()})")
        return 1

    try:
        observed, calls_by_file, unknown_receivers, parse_failures = scan(args.source, log)
    except Exception as exc:  # noqa: BLE001 — 최상위 계측기: 원인 타입을 남기고 실패한다
        log(f"[fatal] 스캔 실패 {type(exc).__name__}: {exc}")
        return 1

    total = sum(len(v) for v in observed.values())
    if total == 0:
        # 스캔 0건은 실패다 — 전수 가드가 대상을 하나도 못 찾으면 공허하게 통과한다.
        log("[fatal] 데이터 접근 파일 0건 — 측정 실패이지 '위반 없음'이 아니다")
        return 1

    markdown = render_markdown(observed, calls_by_file, unknown_receivers, parse_failures)
    print(markdown)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "review_by": BASELINE_REVIEW_BY,
                    "clean_layers": list(CLEAN_LAYERS),
                    "observed": {k: sorted(v) for k, v in sorted(observed.items())},
                    "calls_by_file": dict(sorted(calls_by_file.items())),
                    "unknown_receivers": [list(x) for x in unknown_receivers],
                    "parse_failures": parse_failures,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"[out] json → {args.json}")
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
        log(f"[out] markdown → {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
