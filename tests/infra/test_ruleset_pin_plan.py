"""`scripts/harness/ruleset_pin_plan.py` — 룰셋 PUT 본문 생성기의 **불변식·거부·변별력** 동결.

왜 이 테스트가 있는가
---------------------
룰셋 `PUT`은 본문이 잘못되면 브랜치 보호를 통째로 약화시킨다(규칙 누락·체크 소실). 그래서 본문을
만드는 로직은 저장소 코드로 두고, "중복 제거 + pin **외에는 아무것도 바꾸지 않는다**"를 여기서
결함 주입으로 확인한다. 픽스처는 2026-09-05 실측 구조(rulesets/16623542)를 그대로 따른다.

동결하는 계약
-------------
① as-found(항목 22·고유 16·unpinned 7) → 16건 전부 pin·중복 0·변경 7건
② 본문에 쓰기 가능 필드만 남고 읽기 전용 필드는 없다
③ status 외 규칙·status 규칙의 다른 파라미터·최상위 필드는 바이트 동일
④ 거부 4종(규칙 부재·타 앱 pin·branch-rules 형태·항목 형식 이상) → exit 2 + 고유 원인, 본문 미작성
⑤ 두 번째 방어선 `verify_invariants`가 변환 결함(체크 누락·pin 누락·필드 잔존·타 규칙 변조)을 잡는다
⑥ 입력 인코딩 관용(PS `>`의 UTF-16LE·Out-File의 BOM)
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "harness"))

import ruleset_drift  # noqa: E402
import ruleset_pin_plan as pin  # noqa: E402

_DOC = _REPO_ROOT / ".github" / "branch-protection-setup.md"
IID = ruleset_drift.GITHUB_ACTIONS_INTEGRATION_ID
GRADE_A = "concept-reach — mobile 호출 표면 회귀 가드"
TWINS = (
    "web — graphing-calculator test·build",
    "infra-contracts — 운영 자산 계약 테스트 (tests/infra)",
    "docker-build — 이미지 빌드·기동 스모크(/health/live)",
    "harness-integrity — backlog 무결성·claim 교차 검증",
    "declared-unwired-audit — 선언≠배선 4축 정적 감사 (OPS-22)",
    "corpus-authoring — 결정론 저작 도구 회귀 (생성기·배치)",
)


def _documented() -> list[str]:
    return sorted(ruleset_drift.parse_doc(_DOC).checks)


def _ruleset(checks: list[tuple[str, int | None]]) -> dict[str, Any]:
    """`GET /repos/{o}/{r}/rulesets/{id}` 응답 형태 — 2026-09-05 실측 최상위 키·규칙 5종 그대로."""
    return {
        "id": 16623542,
        "name": "main 보호",
        "target": "branch",
        "source_type": "Repository",
        "source": "doldori7/WhyMath",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "required_review_thread_resolution": True,
                    "require_last_push_approval": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": c, **({"integration_id": i} if i is not None else {})}
                        for c, i in checks
                    ],
                },
            },
            {"type": "required_linear_history"},
        ],
        "node_id": "RRS_lACqUmVwb3NpdG9yeQ",
        "created_at": "2026-05-14T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "bypass_actors": [],
        "current_user_can_bypass": "never",
        "_links": {
            "self": {"href": "https://api.github.com/repos/doldori7/WhyMath/rulesets/16623542"}
        },
    }


def _as_found() -> dict[str, Any]:
    """2026-09-05 실측 분포: pinned 15 + unpinned 7(그중 concept-reach는 pin 쌍 없음) = 22."""
    checks: list[tuple[str, int | None]] = [(n, IID) for n in _documented() if n != GRADE_A]
    checks += [(n, None) for n in TWINS] + [(GRADE_A, None)]
    assert len(checks) == 22
    return _ruleset(checks)


def _healthy() -> dict[str, Any]:
    return _ruleset([(n, IID) for n in _documented()])


def _status_checks(body: dict[str, Any]) -> list[dict[str, Any]]:
    rule = next(r for r in body["rules"] if r["type"] == "required_status_checks")
    return rule["parameters"]["required_status_checks"]


def _run(ruleset: Any, tmp_path: Path, encoding: str = "utf-8") -> tuple[int, Path]:
    src = tmp_path / "backup.json"
    text = json.dumps(ruleset, ensure_ascii=False)
    if encoding in ("utf-16-le", "utf-16-be"):
        src.write_bytes(("﻿" + text).encode(encoding))
    else:
        src.write_bytes(text.encode(encoding))
    out = tmp_path / "plan.json"
    rb = tmp_path / "rollback.json"
    return pin.main([str(src), "--out", str(out), "--rollback-out", str(rb)]), out


# ---------------------------------------------------------------------------
# 계약 ① — as-found → 전건 pin·중복 0
# ---------------------------------------------------------------------------


def test_as_found_is_normalized_to_sixteen_pinned(tmp_path: Path) -> None:
    plan = pin.build_plan(_as_found())
    after = _status_checks(plan.body)
    assert len(after) == 16
    assert {e["context"] for e in after} == set(_documented())
    assert all(e["integration_id"] == IID for e in after)
    assert len(plan.changed_rows) == 7, [r.context for r in plan.changed_rows]
    assert any(r.context == GRADE_A and r.before == (None,) for r in plan.changed_rows)

    code, out = _run(_as_found(), tmp_path)
    assert code == 0 and out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == plan.body


def test_already_healthy_is_a_noop_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """변경할 것이 없어도 exit 0 — 본문은 현 상태와 동치라 적용해도 무해."""
    plan = pin.build_plan(_healthy())
    assert not plan.changed_rows
    code, _ = _run(_healthy(), tmp_path)
    assert code == 0
    assert "변경할 것이 없다" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 계약 ②③ — 바꾸는 것 외에는 아무것도 바꾸지 않는다
# ---------------------------------------------------------------------------


def test_body_contains_only_writable_fields() -> None:
    body = pin.build_plan(_as_found()).body
    assert set(body) <= set(pin.WRITABLE_FIELDS), sorted(set(body) - set(pin.WRITABLE_FIELDS))
    assert not (set(body) & set(pin.READ_ONLY_FIELDS))
    for k in ("name", "target", "enforcement", "conditions", "bypass_actors", "rules"):
        assert k in body, f"{k} 누락"


def test_non_status_rules_and_top_level_are_byte_identical() -> None:
    original = _as_found()
    body = pin.build_plan(original).body
    for k in ("name", "target", "enforcement", "conditions", "bypass_actors"):
        assert body[k] == original[k]
    assert [r["type"] for r in body["rules"]] == [r["type"] for r in original["rules"]]
    for o, n in zip(original["rules"], body["rules"], strict=True):
        if o["type"] != "required_status_checks":
            assert o == n, o["type"]


def test_status_rule_other_parameters_are_preserved() -> None:
    body = pin.build_plan(_as_found()).body
    rule = next(r for r in body["rules"] if r["type"] == "required_status_checks")
    assert rule["parameters"]["strict_required_status_checks_policy"] is True
    assert rule["parameters"]["do_not_enforce_on_create"] is False


def test_build_plan_does_not_mutate_its_input() -> None:
    original = _as_found()
    snapshot = copy.deepcopy(original)
    pin.build_plan(original)
    assert original == snapshot


# ---------------------------------------------------------------------------
# 계약 ④ — 거부는 exit 2 + 고유 원인, 본문 미작성
# ---------------------------------------------------------------------------


def _without_status_rule() -> dict[str, Any]:
    r = _healthy()
    r["rules"] = [x for x in r["rules"] if x["type"] != "required_status_checks"]
    return r


def _foreign_pin() -> dict[str, Any]:
    r = _healthy()
    _status_checks(r)[0]["integration_id"] = 99999
    return r


def _malformed_entry() -> dict[str, Any]:
    r = _healthy()
    _status_checks(r).append({"integration_id": IID})
    return r


def _empty_list() -> dict[str, Any]:
    r = _healthy()
    _status_checks(r).clear()
    return r


_REFUSALS: list[tuple[str, Any, str]] = [
    ("status 규칙 부재", _without_status_rule(), "규칙이 없다"),
    ("체크 목록 빈 배열(OPS-08 동형 — 탐지기는 위반, 도구는 거부)", _empty_list(), "0건"),
    ("타 앱 pin", _foreign_pin(), "다른 앱"),
    ("branch-rules 형태(배열)", [{"type": "deletion"}], "룰셋 객체가 아니다"),
    ("항목 형식 이상", _malformed_entry(), "형식이 예상과 다르다"),
]


@pytest.mark.parametrize(("label", "ruleset", "reason"), _REFUSALS)
def test_refusal_exits_two_without_writing(
    label: str, ruleset: Any, reason: str, tmp_path: Path
) -> None:
    code, out = _run(ruleset, tmp_path)
    assert code == 2, f"{label}이 거부되지 않았다"
    assert (
        not out.exists()
    ), f"{label}: 거부했는데 본문 파일이 남았다 — 잘못된 본문이 적용될 수 있다"
    assert not (tmp_path / "rollback.json").exists(), f"{label}: 거부했는데 롤백 파일이 남았다"


@pytest.mark.parametrize(("label", "ruleset", "reason"), _REFUSALS)
def test_refusal_removes_stale_outputs_from_a_prior_run(
    label: str, ruleset: Any, reason: str, tmp_path: Path
) -> None:
    """직전 성공 실행의 산출물이 남아 있으면 **거부 실행이 그것을 지워야** 한다.

    안 지우면 "EXIT=2면 본문이 없다"는 런북의 약속이 거짓이 되고, 사람은 다음 줄의
    `gh api --input ruleset-plan.json`으로 **오래된 본문**을 그대로 적용한다(Codex P2).
    """
    (tmp_path / "plan.json").write_text('{"stale": true}', encoding="utf-8")
    (tmp_path / "rollback.json").write_text('{"stale": true}', encoding="utf-8")
    code, out = _run(ruleset, tmp_path)
    assert code == 2
    assert not out.exists(), f"{label}: 이전 변경안이 남았다"
    assert not (tmp_path / "rollback.json").exists(), f"{label}: 이전 롤백 본문이 남았다"


@pytest.mark.parametrize(("label", "ruleset", "reason"), _REFUSALS)
def test_refusal_reports_its_own_cause(label: str, ruleset: Any, reason: str) -> None:
    with pytest.raises(ruleset_drift.RulesetInputError, match=reason):
        pin.build_plan(ruleset)


# ---------------------------------------------------------------------------
# 계약 ④' — 롤백 본문은 적용보다 먼저, 원본과 완전 동일, 실행 가능해야 한다
# ---------------------------------------------------------------------------


def test_rollback_body_is_faithful_and_put_ready(tmp_path: Path) -> None:
    """백업 JSON을 그대로 PUT하면 읽기 전용 필드 때문에 거부될 수 있다 — 그러면 롤백이
    '실행 불가능한 절차'가 된다(Codex P1). 기계가 만든 롤백 본문은 그 결함이 없어야 한다."""
    original = _as_found()
    rb = pin.build_rollback(original)
    assert set(rb) <= set(pin.WRITABLE_FIELDS)
    assert not (set(rb) & set(pin.READ_ONLY_FIELDS))
    for k in pin.WRITABLE_FIELDS:
        assert (k in original) == (k in rb)
        if k in original:
            assert rb[k] == original[k], k
    # 롤백은 변경 전 상태 — 변경안과 달라야 한다(as-found에는 unpinned가 있다)
    assert rb["rules"] != pin.build_plan(original).body["rules"]

    code, out = _run(original, tmp_path)
    assert code == 0
    written = json.loads((tmp_path / "rollback.json").read_text(encoding="utf-8"))
    assert written == rb


def test_success_writes_both_files_atomically(tmp_path: Path) -> None:
    code, out = _run(_as_found(), tmp_path)
    assert code == 0
    assert out.is_file() and (tmp_path / "rollback.json").is_file()
    assert not list(tmp_path.glob("*.tmp")), "임시 파일이 남았다 — 교체가 원자적이지 않다"


@pytest.mark.parametrize(
    ("label", "corrupt", "reason"),
    [
        ("읽기 전용 잔존", lambda b: b.__setitem__("id", 1), "읽기 전용"),
        ("규칙 변조", lambda b: b["rules"].pop(), "원본과 다르다"),
        ("알 수 없는 필드", lambda b: b.__setitem__("bogus", 1), "알 수 없는 필드"),
    ],
)
def test_verify_rollback_catches_corruption(label: str, corrupt: Any, reason: str) -> None:
    original = _as_found()
    body = pin.build_rollback(original)
    corrupt(body)
    with pytest.raises(ruleset_drift.RulesetInputError, match=reason):
        pin.verify_rollback(original, body)


# ---------------------------------------------------------------------------
# 계약 ⑤ — 두 번째 방어선이 변환 결함을 잡는다
# ---------------------------------------------------------------------------


def _good_body() -> tuple[dict[str, Any], dict[str, Any]]:
    original = _as_found()
    return original, pin.build_plan(original).body


@pytest.mark.parametrize(
    ("label", "corrupt", "reason"),
    [
        (
            "체크 1건 누락",
            lambda b: _status_checks(b).pop(),
            "집합이 달라졌다",
        ),
        (
            "pin 누락",
            lambda b: _status_checks(b)[0].pop("integration_id"),
            "pin되지 않은",
        ),
        (
            "읽기 전용 필드 잔존",
            lambda b: b.__setitem__("id", 16623542),
            "읽기 전용 필드",
        ),
        (
            "타 규칙 변조",
            lambda b: b["rules"][0].__setitem__("type", "non_fast_forward"),
            "타입이 달라졌다",
        ),
        (
            "status 파라미터 변조",
            lambda b: next(r for r in b["rules"] if r["type"] == "required_status_checks")[
                "parameters"
            ].__setitem__("strict_required_status_checks_policy", False),
            "파라미터",
        ),
        (
            "최상위 필드 변조",
            lambda b: b.__setitem__("enforcement", "disabled"),
            "보존되지 않았다",
        ),
        (
            "중복 잔존",
            lambda b: _status_checks(b).append(dict(_status_checks(b)[0])),
            "중복",
        ),
        (
            "체크 전건 소실(빈 목록)",
            lambda b: _status_checks(b).clear(),
            "집합이 달라졌다|0건",
        ),
    ],
)
def test_verify_invariants_catches_corruption(label: str, corrupt: Any, reason: str) -> None:
    original, body = _good_body()
    corrupt(body)
    with pytest.raises(ruleset_drift.RulesetInputError, match=reason):
        pin.verify_invariants(original, body, IID)


# ---------------------------------------------------------------------------
# 계약 ⑥ — 입력 인코딩 관용
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16-le"])
def test_input_encodings_are_tolerated(encoding: str, tmp_path: Path) -> None:
    code, out = _run(_as_found(), tmp_path, encoding=encoding)
    assert code == 0 and out.is_file(), encoding


def test_plan_file_is_ascii_json(tmp_path: Path) -> None:
    """Windows에서 gh가 읽는 요청 본문 — 인코딩 모호성을 없애기 위해 ASCII로만 쓴다."""
    _, out = _run(_as_found(), tmp_path)
    raw = out.read_bytes()
    assert all(b < 128 for b in raw), "본문에 비ASCII 바이트가 있다"
    assert json.loads(raw.decode("ascii"))["rules"]


# ---------------------------------------------------------------------------
# 런북 — 경로 B가 문서에 실재하고 Windows PowerShell에서 실행 가능하다
# ---------------------------------------------------------------------------


def test_doc_has_api_path_runbook() -> None:
    text = _DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```powershell\n(.*?)```", text, flags=re.DOTALL)
    backup = [b for b in blocks if "rulesets/16623542" in b and "ruleset-backup.json" in b]
    plan = [b for b in blocks if "ruleset_pin_plan.py" in b]
    apply = [b for b in blocks if "-X PUT" in b and "--input ruleset-plan.json" in b]
    rollback = [b for b in blocks if "-X PUT" in b and "--input ruleset-rollback.json" in b]
    assert backup, "백업 블록이 없다"
    assert plan, "변경안 생성 블록이 없다"
    assert apply, "적용 블록이 없다"
    assert rollback, (
        "실행 가능한 롤백 블록이 없다 — 백업 JSON을 그대로 PUT하면 읽기 전용 필드로 거부될 수 "
        "있고, 사람이 보안 민감 본문을 손으로 고치게 된다(Codex P1)"
    )
    order = [
        blocks.index(backup[0]),
        blocks.index(plan[0]),
        blocks.index(apply[0]),
        blocks.index(rollback[0]),
    ]
    assert order == sorted(order), "백업 → 변경안 → 적용 → 롤백 순서가 아니다"
    assert not any(
        "--input ruleset-backup.json" in b for b in blocks
    ), "백업 JSON을 직접 PUT하는 블록이 있다 — 읽기 전용 필드 때문에 실행 불가"
    for b in backup + plan + apply + rollback:
        assert "&&" not in b and "python3 " not in b, "PowerShell 5.1에서 실행 불가한 표기"

    # 2026-09-05 실측: 미머지 상태에서 ②가 죽었는데 ③이 그대로 실행됐다(파일이 없어 gh가
    # 거부했기에 무사). ①은 도구 실재를, ③은 ② 산출물 두 개의 실재를 스스로 확인해야 한다.
    assert (
        "Test-Path scripts\\harness\\ruleset_pin_plan.py" in backup[0]
    ), "①에 변경안 도구 실재 자가검증이 없다 — 미머지 체크아웃에서 ②가 [Errno 2]로 죽는다"
    assert (
        "Test-Path ruleset-plan.json" in apply[0] and "Test-Path ruleset-rollback.json" in apply[0]
    ), "③이 ② 산출물 실재를 확인하지 않고 PUT한다 — 오래된 변경안이 그대로 적용될 수 있다"
    # 2026-09-05 실측: ④ 정합 직후 같은 메시지의 ⑤가 통째 붙여넣기되어 롤백이 실행됐다(게이트
    # 재개방·상태 파일 거짓). ⑤는 ④의 마지막 판정을 읽어 ok면 거부해야 한다.
    assert (
        "ruleset-check-state.json" in rollback[0] and "-ne 'ok'" in rollback[0]
    ), "⑤가 ④의 판정을 읽지 않고 되돌린다 — 정합 직후 붙여넣기 한 번에 게이트가 다시 열린다"
