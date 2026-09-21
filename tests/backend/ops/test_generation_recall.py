"""생성 산출물 리콜(generation_recall) 단위테스트 — 선별·처분 계획·격리 (EOS-97).

**핵심은 acceptance ⑤ 과다·과소 양방향**이다. 리콜이 무관한 산출물을 딸려 오면 멀쩡한
문항을 격리하고, 대상이 빠지면 결함이 살아남는다 — **양쪽 다 리콜을 위험하게 만든다.**
그래서 모든 셀렉터 테스트가 "N건만 정확히"를 확인한다(포함 + 배제 동시 단언).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from whymath_backend.ops.generation_recall import (
    MIN_HASH_PREFIX,
    RecallSelector,
    TargetRow,
    apply_quarantine,
    build_plan,
    load_slug_index,
    main,
    select_logs,
)
from whymath_backend.schema.provenance import GenerationLog


def _log(
    *,
    run_id: str | None = None,
    prompt_version: str | None = None,
    model_name: str | None = None,
    seed: int | None = None,
    snapshot: dict[str, object] | None = None,
    with_problem: bool = True,
    cu_slug: str | None = "cu-x",
) -> GenerationLog:
    return GenerationLog(
        problem_id=uuid.uuid4() if with_problem else None,
        run_id=run_id,
        prompt_version=prompt_version,
        model_name=model_name,
        seed=seed,
        input_snapshot=snapshot,
        cu_slug=cu_slug,
        generated_at=datetime.now(UTC),
    )


class TestSelectorPrecision:
    """과다·과소 양방향 — "그 N건만 정확히"."""

    def test_run_id_selects_exactly_its_own(self) -> None:
        target = [_log(run_id="RUN-A") for _ in range(3)]
        other = [_log(run_id="RUN-B") for _ in range(5)]
        picked = select_logs([*target, *other], RecallSelector(run_id="RUN-A"))
        assert len(picked) == 3  # 과소 아님
        assert all(log.run_id == "RUN-A" for log in picked)  # 과다 아님

    def test_null_run_id_is_not_matched_by_any_selector(self) -> None:
        """회차 미기록 행이 아무 회차에나 딸려 오면 안 된다(NULL=미기록의 의미)."""
        logs = [_log(run_id=None), _log(run_id="RUN-A")]
        assert len(select_logs(logs, RecallSelector(run_id="RUN-A"))) == 1

    def test_model_selector_is_exact_not_prefix(self) -> None:
        """모델명은 접두가 아니라 완전 일치다.

        [뮤테이션 경위] 처음에는 `qwen2-math:7b` vs `qwen2-math:1.5b`로 확인했는데, 둘은
        **서로 접두가 아니라** 완전 일치를 접두 일치로 바꾸는 뮤테이션이 검출되지 않았다
        (양쪽 다 1건 — 변별력 0). 한쪽이 다른 쪽의 접두인 쌍이어야 부등호가 실제로
        판정에 쓰이는지 보인다.
        """
        logs = [_log(model_name="qwen2.5:7b"), _log(model_name="qwen2.5:7b-instruct")]
        picked = select_logs(logs, RecallSelector(model_name="qwen2.5:7b"))
        assert len(picked) == 1  # 접두 일치였다면 2건이 딸려 온다(과다 처분)
        assert picked[0].model_name == "qwen2.5:7b"

    def test_seed_zero_is_a_real_value_not_absent(self) -> None:
        """seed=0은 유효한 시드다 — falsy라고 무시하면 그 회차를 리콜할 수 없다."""
        logs = [_log(seed=0), _log(seed=1), _log(seed=None)]
        picked = select_logs(logs, RecallSelector(seed=0))
        assert len(picked) == 1
        assert picked[0].seed == 0

    def test_hash_prefix_matches_and_excludes(self) -> None:
        """설계서의 짧은 해시 호출(--source-hash aa31) 지원 — 다만 무관한 건 안 딸려온다."""
        a = _log(snapshot={"prompt": "alpha"})
        b = _log(snapshot={"prompt": "beta"})
        assert a.input_sha256 is not None and b.input_sha256 is not None
        picked = select_logs([a, b], RecallSelector(input_sha256=a.input_sha256[:8]))
        assert len(picked) == 1
        assert picked[0].input_sha256 == a.input_sha256

    def test_prompt_version_prefix(self) -> None:
        logs = [
            _log(prompt_version="l3.equivalent@sha256:aa31beef"),
            _log(prompt_version="l3.equivalent@sha256:ffffffff"),
        ]
        picked = select_logs(logs, RecallSelector(prompt_version="l3.equivalent@sha256:aa31"))
        assert len(picked) == 1

    def test_selectors_are_and_not_or(self) -> None:
        """조건이 겹치면 좁아져야 한다 — OR로 동작하면 과다 처분이 된다."""
        logs = [
            _log(run_id="RUN-A", model_name="m1"),
            _log(run_id="RUN-A", model_name="m2"),
            _log(run_id="RUN-B", model_name="m1"),
        ]
        picked = select_logs(logs, RecallSelector(run_id="RUN-A", model_name="m1"))
        assert len(picked) == 1

    def test_empty_selector_matches_everything(self) -> None:
        """순수 함수는 전건 매치를 허용한다 — 그것을 막는 것은 CLI의 몫(별도 테스트)."""
        logs = [_log(), _log()]
        assert len(select_logs(logs, RecallSelector())) == 2
        assert RecallSelector().is_empty() is True


class TestPlanCounting:
    def test_unquarantinable_is_separated_not_dropped(self) -> None:
        """problem_id 없는 행을 분모에서 빼면 '전건 처분됨'으로 오독된다."""
        logs = [
            _log(run_id="R", with_problem=True),
            _log(run_id="R", with_problem=False),
            _log(run_id="R", with_problem=False),
        ]
        plan = build_plan(logs, RecallSelector(run_id="R"))
        assert plan.matched == 3
        assert len(plan.quarantinable) == 1
        assert len(plan.unquarantinable) == 2
        # 매치 수 = 격리가능 + 격리불가 (조용히 사라진 행이 없다)
        assert plan.matched == len(plan.quarantinable) + len(plan.unquarantinable)

    def test_scanned_denominator_is_reported(self) -> None:
        """'3건 걸림'이 전체 3건 중인지 3만 건 중인지 알 수 있어야 한다."""
        logs = [_log(run_id="R") for _ in range(2)] + [_log(run_id="X") for _ in range(48)]
        plan = build_plan(logs, RecallSelector(run_id="R"))
        assert plan.scanned == 50
        assert plan.matched == 2
        assert plan.to_json()["scanned"] == 50

    def test_load_errors_are_carried(self) -> None:
        plan = build_plan([], RecallSelector(run_id="R"), load_errors=["ValueError@line 3"])
        assert plan.to_json()["load_errors"] == ["ValueError@line 3"]


class TestTargetRow:
    def test_projection_keeps_identity_fields(self) -> None:
        log = _log(run_id="R", prompt_version="pv", model_name="m", seed=7)
        row = TargetRow.from_log(log)
        payload = row.to_json()
        assert payload["run_id"] == "R"
        assert payload["prompt_version"] == "pv"
        assert payload["model_name"] == "m"
        assert payload["seed"] == 7
        assert payload["problem_id"] == str(log.problem_id)


class TestApplyQuarantine:
    """처분 — 기존 PATCH를 부르고, 실패를 삼키지 않는다."""

    def _client(self, handler: object) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
            base_url="http://test",
        )

    def test_sends_contract_three_fields_to_existing_patch(self) -> None:
        """계약 §5 — 전용 엔드포인트가 아니라 PATCH /v1/problems/{id}에 3필드 동시 기입."""
        seen: list[tuple[str, str, dict[str, object]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"ok": True})

        plan = build_plan([_log(run_id="R")], RecallSelector(run_id="R"))
        with self._client(handler) as client:
            results = apply_quarantine(plan, client=client, reason="복수 정답")
        assert len(results) == 1 and results[0]["ok"] is True
        method, path, body = seen[0]
        assert method == "PATCH"
        assert path.startswith("/v1/problems/")  # 전용 격리 표면을 만들지 않았다
        assert body["review_status"] == "quarantined"
        assert body["quarantine_reason"] == "복수 정답"
        assert "quarantined_at" in body  # 3필드가 함께 간다

    def test_http_error_is_recorded_not_swallowed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        plan = build_plan([_log(run_id="R")], RecallSelector(run_id="R"))
        with self._client(handler) as client:
            results = apply_quarantine(plan, client=client, reason="사유")
        assert results[0]["ok"] is False
        assert results[0]["error"] == "ConnectError"  # 타입명이 남는다(침묵 실패 금지)

    def test_non_2xx_records_status_and_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        plan = build_plan([_log(run_id="R")], RecallSelector(run_id="R"))
        with self._client(handler) as client:
            results = apply_quarantine(plan, client=client, reason="사유")
        assert results[0]["ok"] is False
        assert results[0]["status_code"] == 403
        assert "forbidden" in results[0]["body"]  # 원인 규명 재료

    def test_unquarantinable_rows_are_not_sent(self) -> None:
        """problem_id 없는 행에 PATCH를 보내면 잘못된 URL을 친다."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200)

        plan = build_plan([_log(run_id="R", with_problem=False)], RecallSelector(run_id="R"))
        with self._client(handler) as client:
            results = apply_quarantine(plan, client=client, reason="사유")
        assert results == []
        assert calls == []


class TestCli:
    def _write(self, path: Path, logs: list[GenerationLog]) -> None:
        path.write_text("\n".join(log.model_dump_json() for log in logs) + "\n", encoding="utf-8")

    def test_dry_run_is_default_and_enumerates(self, tmp_path: Path, capsys: object) -> None:
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R"), _log(run_id="X")])
        code = main(["--genlog", str(genlog), "--run-id", "R"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        assert payload["dry_run"] is True  # 처분은 명시 플래그로만
        assert payload["scanned"] == 2
        assert payload["matched"] == 1

    def test_no_selector_is_rejected(self, tmp_path: Path) -> None:
        """셀렉터 없는 리콜은 전건 처분이다 — 기본값으로 두지 않는다."""
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R")])
        with pytest.raises(SystemExit) as exc:
            main(["--genlog", str(genlog)])
        assert exc.value.code == 2

    def test_missing_file_is_measurement_failure_not_zero_match(self, tmp_path: Path) -> None:
        """파일 부재를 '매치 0건'으로 내면 파이프라인 고장이 정상으로 보인다."""
        code = main(["--genlog", str(tmp_path / "nope.jsonl"), "--run-id", "R"])
        assert code == 2  # 1(매치 0건)과 구별된다

    def test_zero_match_exits_1_with_denominator(self, tmp_path: Path, capsys: object) -> None:
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="X") for _ in range(4)])
        code = main(["--genlog", str(genlog), "--run-id", "R"])
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "전체 4행" in captured.err  # 분모가 보인다

    def test_limit_reports_truncation_and_totals(self, tmp_path: Path, capsys: object) -> None:
        """자를 때는 자른 사실과 분모를 함께 낸다(부재 판정에 쓰이면 안 되므로)."""
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R") for _ in range(5)])
        code = main(["--genlog", str(genlog), "--run-id", "R", "--limit", "2"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        assert len(payload["quarantinable"]) == 2
        assert payload["truncated"]["quarantinable_total"] == 5  # 분모 동반
        assert payload["matched"] == 5

    def test_default_has_no_limit(self, tmp_path: Path, capsys: object) -> None:
        """기본은 전건이다 — 도구가 알아서 자르면 부재 판정이 오염된다."""
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R") for _ in range(7)])
        main(["--genlog", str(genlog), "--run-id", "R"])
        payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        assert len(payload["quarantinable"]) == 7
        assert "truncated" not in payload

    @pytest.mark.parametrize("flag", ["--input-sha256", "--prompt-version"])
    def test_too_short_prefix_rejected(self, tmp_path: Path, flag: str) -> None:
        """짧은 접두는 무관한 산출물을 끌어온다 — 과다 처분 방지."""
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R")])
        with pytest.raises(SystemExit) as exc:
            main(["--genlog", str(genlog), flag, "a" * (MIN_HASH_PREFIX - 1)])
        assert exc.value.code == 2

    def test_apply_requires_all_three_contract_inputs(self, tmp_path: Path) -> None:
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R")])
        with pytest.raises(SystemExit) as exc:
            main(["--genlog", str(genlog), "--run-id", "R", "--apply", "--api-base", "http://x"])
        assert exc.value.code == 2

    def test_unquarantinable_surfaces_on_stderr(self, tmp_path: Path, capsys: object) -> None:
        genlog = tmp_path / "g.jsonl"
        self._write(genlog, [_log(run_id="R", with_problem=False)])
        code = main(["--genlog", str(genlog), "--run-id", "R"])
        assert code == 0  # 매치는 있었다
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "격리 불가" in captured.err  # 조용히 넘어가지 않는다


class TestIdentityResolution:
    """#992 P1-1 — 배치 genlog는 problem_id가 전부 None이다.

    코퍼스 해결이 없으면 이 도구는 **지원 원천에서 한 건도 처분하지 못한다**. 여기서는
    그 실패 상태를 먼저 재현하고(결함 주입), 해결이 들어왔을 때만 승격되는지 본다 —
    정상 입력만 초록인 검증은 보호의 증거가 아니다(CLAUDE.md 2026-09-01).
    """

    def _corpus(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_batch_shaped_logs_are_all_unquarantinable_without_corpus(self) -> None:
        """결함 재현 — problem_id=None + cu_slug만 있는 배치 형태는 격리 대상 0건."""
        logs = [_log(run_id="R", with_problem=False, cu_slug=f"wm-x-{i}") for i in range(3)]
        plan = build_plan(logs, RecallSelector(run_id="R"))
        assert plan.matched == 3
        assert plan.quarantinable == []  # ← 코퍼스 없이는 아무것도 처분 못 한다
        assert len(plan.corpus_only) == 3
        assert plan.regeneration_slugs == ["wm-x-0", "wm-x-1", "wm-x-2"]

    def test_corpus_index_promotes_batch_rows_to_quarantinable(self) -> None:
        logs = [_log(run_id="R", with_problem=False, cu_slug="wm-x-0")]
        pid = str(uuid.uuid4())
        plan = build_plan(logs, RecallSelector(run_id="R"), slug_index={"wm-x-0": pid})
        assert [row.problem_id for row in plan.quarantinable] == [pid]
        assert plan.quarantinable[0].problem_id_source == "corpus"  # 출처를 밝힌다
        assert plan.corpus_only == []

    def test_genlog_problem_id_wins_over_corpus(self) -> None:
        """로그가 아는 값을 코퍼스 추정으로 덮어쓰지 않는다."""
        log = _log(run_id="R", with_problem=True, cu_slug="wm-x-0")
        plan = build_plan(
            [log], RecallSelector(run_id="R"), slug_index={"wm-x-0": str(uuid.uuid4())}
        )
        assert plan.quarantinable[0].problem_id == str(log.problem_id)
        assert plan.quarantinable[0].problem_id_source == "genlog"

    def test_unresolved_slug_stays_corpus_only(self) -> None:
        """색인에 없는 slug는 승격되지 않는다 — 과다 처분 금지(acceptance ⑤)."""
        logs = [_log(run_id="R", with_problem=False, cu_slug="wm-missing")]
        plan = build_plan(logs, RecallSelector(run_id="R"), slug_index={"wm-other": "id-1"})
        assert plan.quarantinable == []
        assert plan.regeneration_slugs == ["wm-missing"]

    def test_no_identity_at_all_is_not_a_regeneration_target(self) -> None:
        """cu_slug도 없는 행은 재생성 대상이 아니다 — 두 실패를 한 통에 담지 않는다."""
        logs = [_log(run_id="R", with_problem=False, cu_slug=None)]
        plan = build_plan(logs, RecallSelector(run_id="R"), slug_index={"wm-x": "id-1"})
        assert plan.quarantinable == []
        assert plan.corpus_only == []
        assert len(plan.unidentifiable) == 1
        assert plan.regeneration_slugs == []

    def test_slug_index_loads_and_reports_bad_rows(self, tmp_path: Path) -> None:
        corpus = tmp_path / "c.jsonl"
        corpus.write_text(
            '{"slug": "a", "problem_id": "id-a"}\n'
            "not json\n"
            '{"question_text": "키 없음"}\n'
            '{"slug": "b", "problem_id": "id-b"}\n',
            encoding="utf-8",
        )
        index, errors = load_slug_index([corpus])
        assert index == {"a": "id-a", "b": "id-b"}  # 유효 행은 살린다
        assert len(errors) == 2
        assert "JSONDecodeError" in errors[0]  # 타입명 보존(침묵 실패 금지)
        assert "KeyError" in errors[1]

    def test_slug_collision_keeps_first_and_reports(self, tmp_path: Path) -> None:
        """조용히 덮어쓰면 어느 UUID로 PATCH가 나갔는지 사후에 알 수 없다."""
        first, second = tmp_path / "c1.jsonl", tmp_path / "c2.jsonl"
        self._corpus(first, [{"slug": "a", "problem_id": "id-1"}])
        self._corpus(second, [{"slug": "a", "problem_id": "id-2"}])
        index, errors = load_slug_index([first, second])
        assert index == {"a": "id-1"}
        assert any("SlugCollision" in e for e in errors)

    def test_identical_duplicate_slug_is_not_a_collision(self, tmp_path: Path) -> None:
        """같은 값의 중복은 소음이 아니다 — 변별력 있는 경고만 낸다."""
        first, second = tmp_path / "c1.jsonl", tmp_path / "c2.jsonl"
        self._corpus(first, [{"slug": "a", "problem_id": "id-1"}])
        self._corpus(second, [{"slug": "a", "problem_id": "id-1"}])
        _, errors = load_slug_index([first, second])
        assert errors == []

    def test_cli_end_to_end_promotes_via_corpus(self, tmp_path: Path, capsys: object) -> None:
        """CLI 경로 실측 — 배치 형태 genlog + 코퍼스로 격리 대상이 실제로 생긴다."""
        genlog = tmp_path / "g.genlog.jsonl"
        logs = [_log(run_id="R", with_problem=False, cu_slug="wm-a")]
        genlog.write_text("\n".join(x.model_dump_json() for x in logs) + "\n", encoding="utf-8")
        corpus = tmp_path / "g.jsonl"
        self._corpus(
            corpus, [{"slug": "wm-a", "problem_id": "11111111-1111-1111-1111-111111111111"}]
        )
        code = main(["--genlog", str(genlog), "--corpus", str(corpus), "--run-id", "R"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        assert payload["quarantinable_count"] == 1
        assert payload["slug_index_size"] == 1

    def test_cli_missing_corpus_is_measurement_failure(self, tmp_path: Path) -> None:
        """코퍼스 경로 오타를 '해결 0건'으로 흘리면 재생성 대상으로 오분류된다."""
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(_log(run_id="R").model_dump_json() + "\n", encoding="utf-8")
        code = main(
            ["--genlog", str(genlog), "--corpus", str(tmp_path / "no.jsonl"), "--run-id", "R"]
        )
        assert code == 2

    def test_cli_without_corpus_hints_the_flag(self, tmp_path: Path, capsys: object) -> None:
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(
            _log(run_id="R", with_problem=False, cu_slug="wm-a").model_dump_json() + "\n",
            encoding="utf-8",
        )
        main(["--genlog", str(genlog), "--run-id", "R"])
        assert "--corpus" in capsys.readouterr().err  # type: ignore[attr-defined]


class TestApplyRefusesIncompletePlans:
    """#992 P1-2 / P2 — 부분 처분은 전건 처분보다 위험하다."""

    def _apply_argv(self, genlog: Path) -> list[str]:
        return [
            "--genlog",
            str(genlog),
            "--run-id",
            "R",
            "--apply",
            "--api-base",
            "http://x",
            "--token",
            "t",
            "--reason",
            "결함",
        ]

    def test_unreadable_row_blocks_apply_before_any_patch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
    ) -> None:
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(
            _log(run_id="R").model_dump_json() + "\n{ 깨진 행\n",
            encoding="utf-8",
        )
        sent: list[str] = []
        monkeypatch.setattr(
            "whymath_backend.ops.generation_recall.apply_quarantine",
            lambda *a, **k: sent.append("called") or [],
        )
        code = main(self._apply_argv(genlog))
        assert code == 2  # 매치는 있었지만 계획이 불완전하다 → 측정 실패
        assert sent == []  # **한 건도 보내지 않았다**
        assert "--apply를 거부" in capsys.readouterr().err  # type: ignore[attr-defined]

    def test_clean_plan_still_applies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """변별력 — 깨진 행이 없으면 그대로 처분된다(항상 거부하는 가드는 가드가 아니다)."""
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(_log(run_id="R").model_dump_json() + "\n", encoding="utf-8")
        sent: list[str] = []
        monkeypatch.setattr(
            "whymath_backend.ops.generation_recall.apply_quarantine",
            lambda *a, **k: (sent.append("called"), [{"problem_id": "p", "ok": True}])[1],
        )
        assert main(self._apply_argv(genlog)) == 0
        assert sent == ["called"]

    def test_corpus_load_error_also_blocks_apply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """코퍼스 쪽 손상도 같은 취급 — 해결 실패는 잘못된 재생성 분류를 낳는다."""
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(_log(run_id="R").model_dump_json() + "\n", encoding="utf-8")
        corpus = tmp_path / "c.jsonl"
        corpus.write_text("not json\n", encoding="utf-8")
        sent: list[str] = []
        monkeypatch.setattr(
            "whymath_backend.ops.generation_recall.apply_quarantine",
            lambda *a, **k: sent.append("called") or [],
        )
        code = main([*self._apply_argv(genlog), "--corpus", str(corpus)])
        assert code == 2
        assert sent == []

    def test_limit_with_apply_is_rejected(self, tmp_path: Path) -> None:
        """표시 상한이 처분 범위를 결정하면 보이는 것보다 많이 격리된다(#992 P2)."""
        genlog = tmp_path / "g.jsonl"
        genlog.write_text(_log(run_id="R").model_dump_json() + "\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            main([*self._apply_argv(genlog), "--limit", "1"])
        assert exc.value.code == 2
