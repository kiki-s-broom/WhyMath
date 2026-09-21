"""룰셋 소스 pin 변경안 생성 (HARN-64) — 브랜치 보호 PUT 본문을 **오프라인에서** 만들고 검증한다.

왜 이 도구가 있는가
-------------------
HARN-63 첫 라이브 실측(2026-09-05)이 `concept-reach` 등급ⓐ 위반 1건(pin 항목 0건)과 권고
12건(중복 6·혼재 6)을 냈다. 시정은 룰셋 `PUT`인데, **본문이 잘못되면 보호를 통째로 약화**시킬
수 있다(규칙이 빠지거나 체크가 사라지거나). 그래서 본문을 만드는 로직을 저장소 코드로 두고
불변식을 코드가 집행하며 테스트로 동결한다 — "검증 없는 실행 안내 금지"를 지키는 유일한 길이다.

분업 (ruleset_drift와 같은 전제)
-------------------------------
이 도구는 **네트워크 호출을 하지 않는다.** 조회(`GET rulesets/{id}`)와 적용(`PUT`)은 관리자
토큰을 가진 Kiki의 `gh api`가 한다. 도구는 백업 JSON → 변경안 JSON + 사람이 읽는 표만 낸다.

    gh api repos/{owner}/{repo}/rulesets/16623542 | Out-File -Encoding utf8 ruleset-backup.json
    python scripts\\harness\\ruleset_pin_plan.py ruleset-backup.json --out ruleset-plan.json
        → ruleset-plan.json(변경안) + ruleset-rollback.json(되돌리기) 두 파일.
          둘 다 검증 통과 후에만 쓴다.
    (표를 확인한 뒤)
    gh api -X PUT repos/{owner}/{repo}/rulesets/16623542 --input ruleset-plan.json
    (문제가 있으면)
    gh api -X PUT repos/{owner}/{repo}/rulesets/16623542 --input ruleset-rollback.json

무엇을 바꾸고 무엇을 바꾸지 않는가 (불변식 — 코드가 집행·위반 시 본문을 쓰지 않는다)
--------------------------------------------------------------------------------------
바꾸는 것: `required_status_checks` 항목을 **컨텍스트별 1건**으로 중복 제거하고 전건
`integration_id`=GitHub Actions(15368)로 pin한다. 그것뿐이다.
바꾸지 않는 것:
  · 컨텍스트 **집합** — 체크를 추가하지도 빼지도 않는다(집합이 다르면 exit 2)
  · status 외 규칙(deletion·pull_request·linear_history…) — 바이트 동일
  · status 규칙의 다른 파라미터(strict 정책 등) — 그대로
  · `name`·`target`·`enforcement`·`conditions`·`bypass_actors` — 그대로
제거하는 것: 읽기 전용 필드(`id`·`node_id`·`created_at`·`updated_at`·`source`·`source_type`·
`_links`·`current_user_can_bypass`) — PUT 본문에 있으면 안 된다.

거부하는 것 (exit 2 · 사람 판단이 필요한 상태)
---------------------------------------------
  · status 규칙 부재 **또는 체크 목록 빈 배열** — 이 도구는 규칙·체크를 *만들지* 않는다
    (빈 목록은 강제가 꺼진 상태라 드리프트 탐지기가 위반으로 판정한다 — 여기서 "무해"라고
    하면 두 도구가 모순된다)
  · 다른 앱으로 pin된 항목 — 15368로 바꾸면 의미가 달라진다. 사람이 봐야 한다
  · 입력 형식 이상 — 규칙 배열이 아니거나 항목에 context가 없거나

exit code: 0 = 변경안·롤백 본문 작성 / 2 = 거부(본문 미작성 — **이전 실행의 산출물도 먼저
지운다**, 남겨 두면 오래된 본문이 PUT된다). 변경할 것이 없어도 0이다(본문은 현 상태와 동치).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ruleset_drift import (  # noqa: E402
    GITHUB_ACTIONS_INTEGRATION_ID,
    RulesetInputError,
    read_json_text,
)

# GitHub `PUT /repos/{owner}/{repo}/rulesets/{id}`가 받는 필드. 이 밖의 것은 본문에 넣지 않는다.
WRITABLE_FIELDS: tuple[str, ...] = (
    "name",
    "target",
    "enforcement",
    "bypass_actors",
    "conditions",
    "rules",
)
# GET 응답에만 있는 읽기 전용 필드 — 본문에 남아 있으면 불변식 위반.
READ_ONLY_FIELDS: tuple[str, ...] = (
    "id",
    "node_id",
    "created_at",
    "updated_at",
    "source",
    "source_type",
    "_links",
    "current_user_can_bypass",
)
_STATUS_RULE = "required_status_checks"


@dataclass(frozen=True)
class PlanRow:
    """사람이 읽는 표의 한 줄 — 컨텍스트 하나의 before(pin 목록) → after(pin 하나)."""

    context: str
    before: tuple[int | None, ...]
    after: int

    @property
    def changed(self) -> bool:
        return self.before != (self.after,)


@dataclass(frozen=True)
class Plan:
    body: dict[str, Any]
    rows: tuple[PlanRow, ...]

    @property
    def changed_rows(self) -> tuple[PlanRow, ...]:
        return tuple(r for r in self.rows if r.changed)


def _status_rule_index(rules: Any, source: str) -> int:
    if not isinstance(rules, list):
        raise RulesetInputError(f"{source}: `rules`가 배열이 아니다(type={type(rules).__name__}).")
    hits = [i for i, r in enumerate(rules) if isinstance(r, dict) and r.get("type") == _STATUS_RULE]
    if not hits:
        raise RulesetInputError(
            f"{source}: {_STATUS_RULE} 규칙이 없다 — 이 도구는 규칙을 만들지 않는다. "
            "규칙 신설은 GitHub UI에서 사람이 한다(훨씬 큰 변경)."
        )
    if len(hits) > 1:
        raise RulesetInputError(f"{source}: {_STATUS_RULE} 규칙이 {len(hits)}개다 — 예상 밖 구조.")
    return hits[0]


def build_plan(
    ruleset: Any, integration_id: int = GITHUB_ACTIONS_INTEGRATION_ID, source: str = "<입력>"
) -> Plan:
    """GET 응답(딕셔너리) → PUT 본문 + 표. 불변식 위반은 예외로 올려 본문을 쓰지 못하게 한다."""
    if not isinstance(ruleset, dict):
        raise RulesetInputError(
            f"{source}: 룰셋 객체가 아니다(type={type(ruleset).__name__}). "
            "`rules/branches/main` 출력이 아니라 `rulesets/{id}` 출력을 넣어라."
        )
    rules = ruleset.get("rules")
    idx = _status_rule_index(rules, source)
    status_rule = rules[idx]
    params = status_rule.get("parameters")
    if not isinstance(params, dict) or not isinstance(params.get(_STATUS_RULE), list):
        raise RulesetInputError(f"{source}: {_STATUS_RULE} 규칙에 체크 목록 필드가 없다.")
    if not params[_STATUS_RULE]:
        # 규칙은 있는데 목록이 비었다 = status check 강제가 꺼진 상태(OPS-08 동형). 드리프트
        # 탐지기가 이것을 위반으로 판정하는데, 시정 도구가 "변경 없음·무해"로 통과시키면
        # 두 도구가 서로 모순된다. 이 도구는 체크를 *추가하지* 않으므로 거부한다.
        raise RulesetInputError(
            f"{source}: required check가 0건이다 — status check 강제가 꺼진 상태(OPS-08 동형). "
            "이 도구는 체크를 추가하지 않는다. 체크 등록은 GitHub UI에서 사람이 한다."
        )

    # 컨텍스트별로 묶는다(첫 등장 순서 유지 — 표가 사람이 비교하기 쉽게).
    seen: dict[str, list[int | None]] = {}
    for entry in params[_STATUS_RULE]:
        if not isinstance(entry, dict) or not entry.get("context"):
            raise RulesetInputError(f"{source}: 체크 항목 형식이 예상과 다르다: {entry!r}")
        iid = entry.get("integration_id")
        pin = int(iid) if isinstance(iid, int) else None
        if pin is not None and pin != integration_id:
            raise RulesetInputError(
                f"{source}: `{entry['context']}`가 다른 앱(integration_id={pin})으로 pin돼 있다 — "
                f"{integration_id}로 바꾸면 보고 주체가 달라진다. 사람이 판단할 항목이라 거부한다."
            )
        seen.setdefault(str(entry["context"]), []).append(pin)

    rows = tuple(PlanRow(ctx, tuple(pins), integration_id) for ctx, pins in seen.items())

    new_rule = copy.deepcopy(status_rule)
    new_rule["parameters"][_STATUS_RULE] = [
        {"context": ctx, "integration_id": integration_id} for ctx in seen
    ]
    new_rules = [copy.deepcopy(r) if i != idx else new_rule for i, r in enumerate(rules)]

    body = _writable_subset(ruleset)
    body["rules"] = new_rules

    verify_invariants(ruleset, body, integration_id, source)
    return Plan(body=body, rows=rows)


def _writable_subset(ruleset: dict[str, Any]) -> dict[str, Any]:
    """GET 응답에서 PUT이 받는 필드만 깊은 복사. 읽기 전용 필드는 여기서 떨어진다."""
    return {k: copy.deepcopy(ruleset[k]) for k in WRITABLE_FIELDS if k in ruleset}


def build_rollback(ruleset: dict[str, Any], source: str = "<입력>") -> dict[str, Any]:
    """적용 *전* 상태로 되돌리는 PUT 본문 — 변경안과 **함께**, 적용보다 **먼저** 만든다.

    왜 따로 만드나: 백업 JSON(GET 응답)을 그대로 `--input`으로 보내면 읽기 전용 필드 때문에
    GitHub이 거부할 수 있다. 그러면 "롤백 절차"가 실행 불가능한 절차가 된다 — 보호가
    약해진 직후, 사람이 보안 민감 본문을 손으로 고쳐야 하는 최악의 타이밍에(Codex P1 지적).
    그래서 롤백 본문도 기계가 만들고 같은 불변식으로 검증한다.
    """
    if not isinstance(ruleset, dict):
        raise RulesetInputError(f"{source}: 룰셋 객체가 아니다(type={type(ruleset).__name__}).")
    body = _writable_subset(ruleset)
    verify_rollback(ruleset, body, source)
    return body


def verify_rollback(original: dict[str, Any], body: dict[str, Any], source: str = "<입력>") -> None:
    """롤백 본문 = 원본의 쓰기 가능 필드와 **완전 동일**, 읽기 전용 필드 0."""
    leaked = [k for k in READ_ONLY_FIELDS if k in body]
    if leaked:
        raise RulesetInputError(f"{source}: 롤백 본문에 읽기 전용 필드가 남았다: {leaked}")
    unknown = [k for k in body if k not in WRITABLE_FIELDS]
    if unknown:
        raise RulesetInputError(f"{source}: 롤백 본문에 알 수 없는 필드가 있다: {unknown}")
    for k in WRITABLE_FIELDS:
        if (k in original) != (k in body) or (k in original and original[k] != body[k]):
            raise RulesetInputError(f"{source}: 롤백 본문의 `{k}`가 원본과 다르다.")
    if not isinstance(body.get("rules"), list) or not body["rules"]:
        raise RulesetInputError(f"{source}: 롤백 본문에 규칙이 없다 — 되돌릴 대상이 없다.")


def verify_invariants(
    original: dict[str, Any], body: dict[str, Any], integration_id: int, source: str = "<입력>"
) -> None:
    """변경안이 '중복 제거 + pin' **외에는 아무것도** 바꾸지 않았는지 독립적으로 재검사.

    build_plan이 옳더라도 이 검사는 따로 둔다 — 변환 로직에 결함이 생겼을 때 잘못된 본문이
    파일로 나가는 것을 막는 두 번째 방어선이다(뮤테이션 테스트가 이 경로를 실측한다).
    """
    leaked = [k for k in READ_ONLY_FIELDS if k in body]
    if leaked:
        raise RulesetInputError(f"{source}: 읽기 전용 필드가 본문에 남았다: {leaked}")
    for k in WRITABLE_FIELDS:
        if k == "rules":
            continue
        if (k in original) != (k in body) or (k in original and original[k] != body[k]):
            raise RulesetInputError(f"{source}: `{k}`가 보존되지 않았다.")

    orig_rules, new_rules = original["rules"], body.get("rules")
    if not isinstance(new_rules, list) or len(new_rules) != len(orig_rules):
        raise RulesetInputError(
            f"{source}: 규칙 수가 달라졌다({len(orig_rules)}→"
            f"{len(new_rules) if isinstance(new_rules, list) else '?'})."
        )
    for i, (o, n) in enumerate(zip(orig_rules, new_rules, strict=True)):
        if o.get("type") != n.get("type"):
            raise RulesetInputError(
                f"{source}: 규칙 #{i} 타입이 달라졌다({o.get('type')}→{n.get('type')})."
            )
        if o.get("type") != _STATUS_RULE and o != n:
            raise RulesetInputError(f"{source}: status 외 규칙 `{o.get('type')}`이 변조됐다.")

    idx = _status_rule_index(orig_rules, source)
    op, np_ = orig_rules[idx]["parameters"], new_rules[idx]["parameters"]
    for k in set(op) | set(np_):
        if k == _STATUS_RULE:
            continue
        if op.get(k) != np_.get(k):
            raise RulesetInputError(f"{source}: status 규칙 파라미터 `{k}`가 달라졌다.")

    before = {str(e["context"]) for e in op[_STATUS_RULE]}
    after_list = np_[_STATUS_RULE]
    after = [str(e["context"]) for e in after_list]
    if set(after) != before:
        raise RulesetInputError(
            f"{source}: 컨텍스트 집합이 달라졌다 — 사라짐 {sorted(before - set(after))} · "
            f"생김 {sorted(set(after) - before)}"
        )
    if len(after) != len(set(after)):
        raise RulesetInputError(f"{source}: 변경안에 중복 컨텍스트가 남았다.")
    unpinned = [e["context"] for e in after_list if e.get("integration_id") != integration_id]
    if unpinned:
        raise RulesetInputError(f"{source}: pin되지 않은 항목이 남았다: {unpinned}")
    if not after_list:
        raise RulesetInputError(f"{source}: 변경안의 required check가 0건이다 — 강제가 꺼진다.")


def render(plan: Plan, integration_id: int) -> str:
    def fmt(pin: int | None) -> str:
        return str(pin) if pin is not None else "없음"

    lines = [
        f"[룰셋 소스 pin 변경안] 고유 체크 {len(plan.rows)}건 · "
        f"변경 {len(plan.changed_rows)}건 · pin={integration_id}"
    ]
    width = max(len(r.context) for r in plan.rows) if plan.rows else 10
    for r in plan.rows:
        mark = "→ 변경" if r.changed else "  유지"
        lines.append(
            f"  {mark}  {r.context.ljust(width)}  "
            f"[{', '.join(fmt(p) for p in r.before)}] → [{r.after}]"
        )
    if not plan.changed_rows:
        lines.append("변경할 것이 없다 — 본문은 현 상태와 동치(적용해도 무해).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="룰셋 백업 JSON → 소스 pin 정규화 PUT 본문 + 표 (네트워크 호출 없음)"
    )
    parser.add_argument(
        "backup_json", type=Path, help="gh api repos/<o>/<r>/rulesets/<id> 출력 파일"
    )
    parser.add_argument(
        "--out", type=Path, default=Path("ruleset-plan.json"), help="PUT 본문 출력 경로"
    )
    parser.add_argument("--integration-id", type=int, default=GITHUB_ACTIONS_INTEGRATION_ID)
    parser.add_argument(
        "--rollback-out",
        type=Path,
        default=Path("ruleset-rollback.json"),
        help="적용 전 상태로 되돌리는 PUT 본문 출력 경로(적용보다 먼저 만들어 둔다)",
    )
    args = parser.parse_args(argv)

    # 이전 실행의 산출물을 **먼저** 지운다. 남겨 두면 이번 실행이 거부돼도 "EXIT=2면 본문이
    # 없다"는 런북의 약속이 거짓이 되고, 오래된 본문이 그대로 PUT될 수 있다(Codex P2 지적).
    for stale in (args.out, args.rollback_out):
        if stale.exists():
            stale.unlink()
            print(f"이전 산출물 제거: {stale}", file=sys.stderr)

    try:
        raw = read_json_text(args.backup_json)
        ruleset = json.loads(raw)
        plan = build_plan(ruleset, args.integration_id, source=str(args.backup_json))
        rollback = build_rollback(ruleset, source=str(args.backup_json))
    except OSError as exc:
        print(f"❌ 거부 — 입력 파일을 읽지 못했다({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"❌ 거부 — JSON 파싱 불가: {exc}", file=sys.stderr)
        return 2
    except RulesetInputError as exc:
        print(f"❌ 거부 — {exc}", file=sys.stderr)
        return 2

    print(render(plan, args.integration_id))
    # 모든 검증이 끝난 뒤에만 쓴다. 임시 파일 → 교체로 부분 기록을 남기지 않는다.
    # ASCII 강제 — Windows에서 gh가 읽는 요청 본문의 인코딩 모호성을 없앤다(\uXXXX는 유효 JSON).
    _publish(args.rollback_out, rollback)
    _publish(args.out, plan.body)
    print(
        f"변경안 작성: {args.out} · 롤백 본문 작성: {args.rollback_out} — 표를 확인한 뒤 "
        f"gh api -X PUT ... --input {args.out} 로 적용한다. "
        f"되돌릴 때는 --input {args.rollback_out}."
    )
    return 0


def _publish(path: Path, body: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(body, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(tmp, path)


if __name__ == "__main__":
    raise SystemExit(main())
