"""브랜치 보호 required check의 **라이브 설정** 드리프트 탐지 (HARN-63).

왜 이 도구가 있는가 — 저장소 경계 밖이라서 (3회차 재발)
--------------------------------------------------------
`tests/infra/test_required_checks_doc.py`는 **문서 ↔ `ci.yml`**을 대조한다. 두 축 다 저장소
*안*이다. 라이브 GitHub 설정은 저장소 *밖*이라 어떤 테스트도 보지 않는다. 그래서 문서가
정확하고 `ci.yml`이 정확해도 **설정이 비어 있으면 전부 초록으로 통과**한다.

실제로 같은 계급의 사고가 3회 났다.
  (1) 2026-07-26 — 문서가 3종만 나열하고 `backend — lint·type·test`가 빠짐 → PR #606이
      `1 failed`로 머지·main red.
  (2) 같은 실측 — 그 3종조차 `enforcement_level=off`·`checks=[]`로 통째 미강제(OPS-08).
  (3) 2026-09-03 — 문서 16건 중 **10건이 라이브에 미등록**. 또 `backend — lint·type·test`다.

조회는 사람·판정은 기계 (설계 전제)
-----------------------------------
세션·CI 토큰으로는 브랜치 보호 설정을 읽을 수 없다(`Resource not accessible by integration`
— 2026-07-26 실측). 그러나 **Kiki 머신의 `gh` 토큰으로는 읽힌다**(2026-09-03 실측 EXIT=0).
따라서 이 도구는 **JSON을 파일 경로로 받는다** — 스스로 조회하지 않는다. 자동 상시 실행이
불가능하다는 것이 정직한 제약이며, 그 제약 위에서 "조회는 사람·판정은 기계"로 분업한다.

    gh api repos/{owner}/{repo}/rules/branches/main > ruleset.json
    python3 scripts/harness/ruleset_drift.py ruleset.json --record

exit code (셋 다 서로 구별된다 — "측정 실패"가 "위반 0 통과"로 위장되면 안 된다)
    0 = 정합 (권고 사항만 있어도 0)
    1 = 드리프트 **위반** 있음
    2 = **측정 실패** — 입력이 비었거나·필드가 없거나·파싱 불가. 판정을 못 한 것이지
        통과가 아니다(CLAUDE.md "측정·게이트 도구의 이중 회계·측정 실패 가시화").

판정 등급 — unpinned를 일괄 '삭제 대상'으로 다루지 않는다 (⑦)
-------------------------------------------------------------
required check 항목은 보고 주체를 특정 앱(GitHub Actions=15368)으로 pin할 수 있다. pin이
없으면 *어느 주체든* 같은 컨텍스트 이름으로 성공을 보고하면 충족된다 — "이름만 같으면 통과하는
좌석"이다. 그렇다고 unpinned를 일괄 제거하면 **pin된 쌍이 없는 항목은 완전 미강제로 되돌아간다**
(2026-09-03 `concept-reach`가 실제로 그 상태였다 — 방금 고친 사고의 재생산). 그래서 세 등급:

    ⓐ pin 항목 0건   → **위반**. 시정 순서: pin 항목 **추가가 먼저**, 제거는 그다음.
    ⓑ pin+unpin 혼재 → 권고. unpinned 쪽만 제거(pin된 쌍이 남는다).
    ⓒ pin만          → 정상.

또한 비교는 **개수가 아니라 집합**으로 한다 — 중복 등록 때문에 항목 22 vs 문서 16이 나오고,
개수로 보면 정상 상태가 위반으로 오판된다(2026-09-03 실측).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# GitHub Actions 앱의 integration_id. required check 항목을 이 앱으로 pin하면 다른 주체가
# 같은 컨텍스트 이름으로 성공을 보고해도 충족되지 않는다.
GITHUB_ACTIONS_INTEGRATION_ID = 15368

# 마지막 라이브 확인이 이 일수를 넘으면 SessionStart 브리핑이 재확인을 리마인드한다.
# 30일 근거: 같은 계급 사고가 3회(2026-07-26 두 축·2026-09-03) 났고 매번 *머지 게이트*가
# 통째로 무력했다. 분기(90일)는 그 사이에 한 분기치 PR이 무방비로 지나간다.
STALE_AFTER_DAYS = 30

# Kiki 머신(Windows PowerShell) 그대로 복사-실행 가능한 조회 명령. 세 가지가 강제된다:
#   · `;` 구분 — Windows PowerShell 5.1은 `&&`를 받지 않는다
#   · `python` — 이 저장소의 Windows 안내는 `python3`가 아니다
#   · `cmd /c "gh api ... > file"` — gh의 출력 바이트를 **PowerShell에 통과시키지 않는다**.
#     PS 5.1은 네이티브 명령의 stdout을 `[Console]::OutputEncoding`(한국어 Windows 기본
#     **cp949**)으로 디코딩한 뒤 다시 인코딩한다. 필수 체크 이름의 `—`·`·`는 UTF-8
#     3바이트인데 cp949는 2바이트 조합이라 경계가 어긋나고, 선행바이트가 뒤따르는
#     `"`(0x22)를 트레일로 삼켜 **JSON 구조 문자가 소실된다**. 2026-09-14 실측:
#     `...가드","app_id"`가 `...媛??,"app_id"`가 되어 2,659→2,618자로 41자 유실,
#     판정기는 `Expecting ',' delimiter: line 1 column 1828`로 exit 2.
#
#     이전 세대(`| Out-File -Encoding utf8`)는 `>`의 UTF-16LE만 피했을 뿐 디코딩
#     경유는 그대로였다 — **인코딩을 명시해도 이미 깨진 문자열을 명시한 인코딩으로
#     쓸 뿐이다.** `cmd /c`는 그 경유 자체를 없앤다.
POWERSHELL_FETCH_RUNBOOK = (
    "cd C:\\Users\\kiki\\Desktop\\__AI\\WhyMath; "
    'cmd /c "gh api repos/{owner}/{repo}/rules/branches/main > ruleset.json"; '
    "python scripts\\harness\\ruleset_drift.py ruleset.json --record"
)

_DOC_RELPATH = Path(".github") / "branch-protection-setup.md"
_STATE_RELPATH = Path(".github") / "ruleset-check-state.json"

_CHECKS_BEGIN = "<!-- REQUIRED_CHECKS_BEGIN"
_CHECKS_END = "<!-- REQUIRED_CHECKS_END -->"
_POLICY_BEGIN = "<!-- RULESET_POLICY_BEGIN"
_POLICY_END = "<!-- RULESET_POLICY_END -->"
_DEVIATION_BEGIN = "<!-- RULESET_DEVIATIONS_BEGIN"
_DEVIATION_END = "<!-- RULESET_DEVIATIONS_END -->"


class RulesetInputError(Exception):
    """입력(라이브 JSON·문서 선언)을 판정에 쓸 수 없다 — exit 2(측정 실패)로 이어진다.

    '위반 0'과 반드시 구별한다. 빈 JSON·필드 부재를 조용히 빈 집합으로 접으면 미설정 상태가
    정합으로 보고된다 — 이 도구가 막으려는 바로 그 사고다.
    """


# ---------------------------------------------------------------------------
# 문서(의도) 파싱
# ---------------------------------------------------------------------------


def _block(text: str, begin: str, end: str, label: str, source: str) -> str:
    start = text.find(begin)
    stop = text.find(end)
    if start == -1 or stop == -1 or stop <= start:
        raise RulesetInputError(
            f"{source}: {label} 마커 블록을 찾지 못했다(begin={start}, end={stop}). "
            "블록을 옮겼다면 마커도 함께 옮겨라."
        )
    return text[start:stop]


@dataclass(frozen=True)
class Deviation:
    """문서 선언과 라이브가 다른 것을 *알면서* 유예한 축. 만료가 반드시 있다.

    CLAUDE.md "만료 없는 유예·제외 금지" — 만료일이 지나면 유예는 위반으로 승격된다.
    """

    key: str
    until: date
    reason: str


@dataclass(frozen=True)
class DocDeclaration:
    """문서가 선언한 *의도*. 라이브에 맞춰 낮추지 않는다 — 문서가 의도이고 라이브가 결함이다."""

    checks: frozenset[str]
    params: dict[str, Any]
    deviations: dict[str, Deviation]
    integration_id: int


def parse_doc(path: Path) -> DocDeclaration:
    """문서의 3개 마커 블록을 판정 가능한 선언으로 파싱.

    마커 부재·빈 블록은 **예외로 실패**시킨다 — 조용히 빈 선언을 돌려주면 라이브가 무엇이든
    "위반 0"으로 통과해 이 도구 전체가 위장이 된다.
    """
    text = path.read_text(encoding="utf-8")
    source = path.name

    checks = re.findall(
        r"^-\s+`([^`]+)`\s*$",
        _block(text, _CHECKS_BEGIN, _CHECKS_END, "REQUIRED_CHECKS", source),
        flags=re.MULTILINE,
    )
    if not checks:
        raise RulesetInputError(f"{source}: REQUIRED_CHECKS 블록에 체크 이름이 하나도 없다.")

    policy_block = _block(text, _POLICY_BEGIN, _POLICY_END, "RULESET_POLICY", source)
    params: dict[str, Any] = {}
    for key, raw in re.findall(r"^-\s+`([^`]+)`\s*=\s*`([^`]+)`", policy_block, flags=re.MULTILINE):
        params[key] = _coerce(raw)
    if not params:
        raise RulesetInputError(f"{source}: RULESET_POLICY 블록에 선언이 하나도 없다.")

    integration_id = params.pop("required_check_integration_id", None)
    if not isinstance(integration_id, int):
        raise RulesetInputError(
            f"{source}: RULESET_POLICY 블록에 정수 `required_check_integration_id` 선언이 없다 "
            f"(얻은 값: {integration_id!r}). pin 판정의 기준이라 없으면 판정할 수 없다."
        )

    deviations: dict[str, Deviation] = {}
    dev_block = _block(text, _DEVIATION_BEGIN, _DEVIATION_END, "RULESET_DEVIATIONS", source)
    for key, until, reason in re.findall(
        r"^-\s+`([^`]+)`\s+until\s+`(\d{4}-\d{2}-\d{2})`\s*—\s*(.+?)\s*$",
        dev_block,
        flags=re.MULTILINE,
    ):
        if not reason.strip():
            raise RulesetInputError(f"{source}: 유예 `{key}`에 사유가 없다.")
        deviations[key] = Deviation(key=key, until=date.fromisoformat(until), reason=reason.strip())

    return DocDeclaration(
        checks=frozenset(checks),
        params=params,
        deviations=deviations,
        integration_id=integration_id,
    )


def _coerce(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        return raw.strip()


# ---------------------------------------------------------------------------
# 라이브 JSON 파싱
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveCheck:
    context: str
    integration_id: int | None


@dataclass(frozen=True)
class LiveRuleset:
    checks: tuple[LiveCheck, ...]
    params: dict[str, Any]
    rule_types: frozenset[str]
    # status check 강제 자체가 꺼져 있는가. **측정 실패가 아니라 판정 결과다** — 응답을
    # 읽는 데 성공했는데 규칙이 없다면 그것은 "모른다"가 아니라 "보호가 없다"이다.
    # 이것을 exit 2로 올리면 write_state가 돌지 않아 직전의 `ok` 기록이 그대로 남고,
    # main이 완전 무방비인 채로 브리핑이 최대 30일간 침묵한다(2026-09-05 Codex P1 지적).
    status_checks_enforced: bool = True


def parse_live(payload: Any, source: str = "<입력>") -> LiveRuleset:
    """`gh api repos/<owner>/<repo>/rules/branches/main` 출력(규칙 배열)을 파싱.

    이 엔드포인트는 규칙 객체의 **배열**을 돌려준다. 권한 오류·빈 응답은 배열이 아니거나 빈
    배열이며, 그것을 "규칙 0건 = 위반 0"으로 접지 않고 측정 실패로 올린다.
    """
    if isinstance(payload, dict):
        # 오류 응답({"message": "Not Found", ...})을 규칙 없음으로 오독하지 않는다.
        raise RulesetInputError(
            f"{source}: 규칙 배열이 아니라 객체가 왔다 — API 오류 응답일 수 있다. "
            f"앞부분: {json.dumps(payload, ensure_ascii=False)[:200]}"
        )
    if not isinstance(payload, list):
        raise RulesetInputError(f"{source}: 규칙 배열이 아니다(type={type(payload).__name__}).")
    if not payload:
        # 규칙 0건 = main에 적용되는 보호가 하나도 없다. 읽기는 성공했으므로 판정 가능하며,
        # 이 저장소가 실제로 겪은 최악 상태다(2026-07-26 OPS-08). 아래 compare가 문서 선언
        # 전건을 미강제 위반으로 보고한다.
        return LiveRuleset(
            checks=(),
            params={k: False for k in ("required_linear_history", "deletion", "non_fast_forward")},
            rule_types=frozenset(),
            status_checks_enforced=False,
        )

    rule_types = frozenset(
        str(rule.get("type")) for rule in payload if isinstance(rule, dict) and rule.get("type")
    )

    checks: list[LiveCheck] = []
    params: dict[str, Any] = {}
    saw_status_rule = False

    for rule in payload:
        if not isinstance(rule, dict):
            continue
        rtype = rule.get("type")
        rparams = rule.get("parameters") or {}
        if not isinstance(rparams, dict):
            rparams = {}

        if rtype == "required_status_checks":
            saw_status_rule = True
            raw_checks = rparams.get("required_status_checks")
            if not isinstance(raw_checks, list):
                raise RulesetInputError(
                    f"{source}: required_status_checks 규칙에 체크 목록 필드가 없다 "
                    f"(얻은 값: {raw_checks!r})."
                )
            for entry in raw_checks:
                if not isinstance(entry, dict) or not entry.get("context"):
                    raise RulesetInputError(f"{source}: 체크 항목 형식이 예상과 다르다: {entry!r}")
                iid = entry.get("integration_id")
                checks.append(
                    LiveCheck(
                        context=str(entry["context"]),
                        integration_id=int(iid) if isinstance(iid, int) else None,
                    )
                )
            params["strict_required_status_checks_policy"] = rparams.get(
                "strict_required_status_checks_policy"
            )
        elif rtype == "pull_request":
            for key in (
                "required_approving_review_count",
                "dismiss_stale_reviews_on_push",
                "require_code_owner_review",
                "required_review_thread_resolution",
            ):
                params[key] = rparams.get(key)

    # 규칙 타입 자체의 존재 여부도 선언 축이다(required_linear_history 등은 파라미터가 없다).
    #
    # `merge_queue`는 2026-09-07~09-08 동안 **의도적으로 여기 없었다** — 그때 이 저장소는
    # owner.type=User(개인 계정 doldori7)였고 GitHub merge queue는 조직 소유 전용이라 켤 수
    # 없었다. 충족 불가한 것을 선언하면 위반이 상시 보고돼 판정기 전체가 소음이 되므로
    # (CLAUDE.md '상시 실패하는 fail-open 보호') 빼 두고, "저장소가 조직으로 이관되면 그때
    # 이 튜플에 추가한다"는 조건을 주석에 박아 뒀다.
    #
    # **그 조건이 충족됐다(2026-09-09)**: 저장소가 kiki-s-broom(Organization)으로 전환되고
    # main 룰셋에 merge queue가 켜졌다. 근거는 라이브 룰셋 덤프가 아니라 **큐가 실제로 일한
    # 사실**이다 — PR #1067이 큐 브랜치 `gh-readonly-queue/main/pr-1067-94d1f28a`에서
    # merge_group CI(run 34318528035)를 거쳐 머지됐고 그 head가 그대로 main(a374d2e0)이 됐다.
    # 이제 큐가 머지 경로를 지탱하므로 **감시 축에서 빠져 있는 것이 위험**이다: 누가 큐를 꺼도
    # 판정기가 모르는, 보호가 있다고 믿는 무보호 상태가 된다.
    for rtype in ("required_linear_history", "deletion", "non_fast_forward", "merge_queue"):
        params[rtype] = rtype in rule_types

    # 규칙은 읽혔는데 status check 강제가 없거나 목록이 비었다 — 확정된 회귀다(측정 실패 아님).
    return LiveRuleset(
        checks=tuple(checks),
        params=params,
        rule_types=rule_types,
        status_checks_enforced=bool(saw_status_rule and checks),
    )


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


@dataclass
class Report:
    violations: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def compare(doc: DocDeclaration, live: LiveRuleset, today: date) -> Report:
    """문서 선언(의도) ↔ 라이브 설정(실태) 대조. 개수가 아니라 **집합**으로 본다."""
    report = Report()

    if not live.status_checks_enforced:
        report.violations.append(
            "🔴 status check 강제가 통째로 꺼져 있다 — required check 0건이라 **어떤 CI 잡도 "
            "머지를 막지 못한다**(2026-07-26 OPS-08과 동형). 아래 미강제 목록 전체가 그 결과다."
        )
        report.remediation.append(
            "먼저 ruleset에 required status check 규칙을 만들고 문서 선언 전건을 등록한다 — "
            "다른 어떤 항목보다 앞선다."
        )

    live_contexts = [c.context for c in live.checks]
    live_unique = set(live_contexts)

    missing = sorted(doc.checks - live_unique)
    for name in missing:
        report.violations.append(f"미강제 — 문서가 선언한 체크가 라이브에 없다: `{name}`")
    if missing:
        report.remediation.append(
            f"미강제 {len(missing)}건을 ruleset에 등록한다(가장 급한 축 — 그 잡이 red여도 "
            "머지가 막히지 않는다)."
        )

    for name in sorted(live_unique - doc.checks):
        report.violations.append(
            f"미선언 — 라이브에만 있는 체크다(문서에 없다): `{name}`. 문서에 등재하거나 "
            "ruleset에서 제거해 의도를 일치시켜라."
        )

    # 중복은 **권고** — 막는 힘 자체를 약화시키지는 않는다.
    duplicated = sorted(name for name in live_unique if live_contexts.count(name) > 1)
    for name in duplicated:
        report.advisories.append(
            f"중복 등록 {live_contexts.count(name)}건: `{name}` (막는 힘은 그대로 — 정리 권고)"
        )

    # pin 등급 (⑦) — 문서에도 있는 체크만 본다. 미선언은 위 축이 이미 위반으로 잡았다.
    pin_missing: list[str] = []
    for name in sorted(doc.checks & live_unique):
        entries = [c for c in live.checks if c.context == name]
        pinned = [c for c in entries if c.integration_id == doc.integration_id]
        mispinned = [
            c
            for c in entries
            if c.integration_id is not None and c.integration_id != doc.integration_id
        ]
        unpinned = [c for c in entries if c.integration_id is None]

        for c in mispinned:
            report.violations.append(
                f"오pin — `{name}` 항목이 다른 앱(integration_id={c.integration_id})으로 pin됐다 "
                f"(기대: {doc.integration_id})."
            )
        if not pinned and unpinned:
            # ⓐ pin 항목 0건 — 이름만 같으면 어느 주체든 충족시킬 수 있는 좌석.
            pin_missing.append(name)
            report.violations.append(
                f"소스 미pin(등급ⓐ pin 항목 0건) — `{name}`: 어느 주체든 같은 컨텍스트 이름으로 "
                "성공을 보고하면 충족된다."
            )
        elif pinned and unpinned:
            # ⓑ 혼재 — unpinned 쪽만 제거하면 pin된 쌍이 남는다.
            report.advisories.append(
                f"소스 pin 혼재(등급ⓑ) — `{name}`: unpinned 항목만 제거 권고(pin된 쌍이 남는다)"
            )

    if pin_missing:
        report.remediation.append(
            f"등급ⓐ {len(pin_missing)}건({', '.join(f'`{n}`' for n in pin_missing)})은 "
            "**Actions로 pin된 항목 추가가 먼저**다. 순서를 뒤집어 unpinned를 먼저 지우면 "
            "항목이 하나도 남지 않아 완전 미강제로 되돌아간다(= 방금 고친 사고의 재생산)."
        )
    if any(a.startswith("소스 pin 혼재") for a in report.advisories):
        report.remediation.append("등급ⓑ의 unpinned 항목 제거(비차단 — pin된 쌍이 이미 막고 있다).")

    # 정책 파라미터 축 (②) — 체크 목록만 보면 놓친다.
    for key, expected in sorted(doc.params.items()):
        actual = live.params.get(key)
        if actual == expected:
            continue
        message = f"정책 불일치 — `{key}`: 문서 선언 {expected!r} vs 라이브 {actual!r}"
        deviation = doc.deviations.get(key)
        if deviation is None:
            report.violations.append(message)
        elif deviation.until < today:
            report.violations.append(
                f"{message} — 유예가 {deviation.until.isoformat()}에 **만료**됐다. "
                f"사유: {deviation.reason}"
            )
        else:
            report.waived.append(
                f"{message} — {deviation.until.isoformat()}까지 유예. 사유: {deviation.reason}"
            )

    # 쓸모를 다한 유예는 제거 권고 — 유예가 필요 없어졌는데 선언만 남으면, 나중에 같은 축이
    # 다시 어긋났을 때 **조용히 면제**된다(유예가 그 자리에 이미 있으므로). 만료일이 있어도
    # 만료 전까지는 가려지므로, 불필요해진 시점에 지우는 것이 두 번째 방어선이다.
    for key, deviation in sorted(doc.deviations.items()):
        if key in doc.params and live.params.get(key) == doc.params[key]:
            report.advisories.append(
                f"유예 불필요 — `{key}`는 이미 문서 선언과 일치한다. 유예 선언을 제거하라 "
                f"(남겨 두면 다음 드리프트가 조용히 면제된다). 사유였던 것: {deviation.reason}"
            )

    return report


# ---------------------------------------------------------------------------
# 확인 기록 (④ 실행 리듬 배선)
# ---------------------------------------------------------------------------


def read_json_text(path: Path) -> str:
    """입력 JSON을 **산출 인코딩에 관용적으로** 읽는다.

    Windows PowerShell 5.1의 `>` 리다이렉트는 네이티브 명령 출력을 **UTF-16LE**로 쓰고,
    `Out-File -Encoding utf8`은 **BOM 있는 UTF-8**로 쓴다. 둘 다 `encoding="utf-8"` 읽기에서
    깨진다 — 전자는 `UnicodeDecodeError`(OSError가 아니라 잡히지 않고 트레이스백으로 죽었다),
    후자는 `json` 단계에서 BOM 오류다. 2026-09-05 실측·Codex P1 지적.

    CLAUDE.md "외부 도구가 읽는 설정 파일은 그 도구의 읽기 인코딩을 확인하고 맞춘다"의
    *우리가 읽는 쪽* 대응이다(HARN-19 서브프로세스 디코딩과 같은 축). 산출측도 런북에서
    UTF-8로 맞추지만(`POWERSHELL_FETCH_RUNBOOK`), 읽기측이 관용해야 실수 한 번이 판정
    자체를 죽이지 않는다.

    **관용의 한계(2026-09-14 실측)**: 이 폴백은 *인코딩*만 가린다. gh 출력을 PowerShell
    파이프라인에 태우면 cp949 디코딩 왕복에서 바이트가 실제로 **유실**되는데, 그 결과물은
    UTF-8로 멀쩡히 디코딩되고 JSON 단계에서야 깨진다. 즉 산출측을 `cmd /c`로 고치는 것이
    유일한 방어이고 읽기측 관용은 그 축을 막지 못한다.
    """
    raw = path.read_bytes()  # OSError는 호출부가 잡는다
    for encoding in ("utf-8-sig", "utf-16"):  # utf-16은 BOM으로 LE/BE를 스스로 가린다
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RulesetInputError(
        f"{path}: 텍스트로 디코딩하지 못했다(시도: utf-8/utf-8-sig/utf-16). "
        "PowerShell에서는 gh 출력을 파이프에 태우지 말고 "
        '`cmd /c "gh api ... > file"`로 받는다.'
    )


def write_state(root: Path, today: date, report: Report | None, source: str) -> Path:
    """라이브 확인 사실을 기록한다. SessionStart 브리핑이 이 파일의 나이를 읽어 리마인드한다."""
    path = root / _STATE_RELPATH
    # report=None = 측정 자체가 실패한 회차. 그 사실을 기록하지 않으면 **직전의 `ok` 기록이
    # 그대로 남아** 브리핑이 최대 30일간 조용하다 — 측정 실패가 통과로 위장되는 경로다.
    verdict = "measure_fail" if report is None else ("ok" if report.ok else "drift")
    path.write_text(
        json.dumps(
            {
                "last_checked": today.isoformat(),
                "verdict": verdict,
                "violations": 0 if report is None else len(report.violations),
                "advisories": 0 if report is None else len(report.advisories),
                "waived": 0 if report is None else len(report.waived),
                "source": source,
                "_note": (
                    "scripts/harness/ruleset_drift.py --record 가 쓴다. 손편집 금지 — "
                    "확인하지 않고 날짜만 미루면 리마인드가 위장이 된다."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def state_reminder(root: Path, today: date) -> str | None:
    """브리핑 한 줄. 정상(최근 확인·정합)이면 None — 조용한 것이 기본이다.

    기록 부재·경과·드리프트 잔존을 각각 다른 문구로 낸다. 셋을 하나로 뭉치면 "확인한 적 없음"과
    "확인했고 위반이 있음"이 같은 글자로 보인다.
    """
    path = root / _STATE_RELPATH
    if not path.is_file():
        return (
            "⚠ 브랜치 보호 라이브 확인 기록 없음 — 문서·ci.yml 대조만으로는 3회차 사고(HARN-63)를 "
            f"못 막는다. Kiki 머신(PowerShell): {POWERSHELL_FETCH_RUNBOOK}"
        )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        last = date.fromisoformat(str(state["last_checked"]))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        # 침묵 실패 금지 — 예외 타입명을 남긴다(훅은 stderr를 버리므로 반환 문자열에).
        return (
            f"⚠ 브랜치 보호 확인 기록을 읽지 못했다({type(exc).__name__}) — "
            f"{path.name} 확인 필요"
        )

    age = (today - last).days
    if str(state.get("verdict")) == "measure_fail":
        # 측정 실패는 드리프트와 다른 문구여야 한다 — "위반 N건"과 "판정 자체를 못 했다"를
        # 같은 글자로 보이게 하면 고치는 사람이 어디를 볼지 알 수 없다.
        return (
            f"⚠ 브랜치 보호 **측정 실패** 상태(마지막 시도 {last.isoformat()}·{age}일 경과) — "
            f"판정을 못 한 것이지 통과가 아니다. 재시도: {POWERSHELL_FETCH_RUNBOOK}"
        )
    if str(state.get("verdict")) != "ok":
        return (
            f"⚠ 브랜치 보호 드리프트 미해소 — 위반 {state.get('violations')}건 "
            f"(마지막 확인 {last.isoformat()}·{age}일 경과). 시정: 게이트 "
            "G-required-checks-live-drift-fix"
        )
    if age > STALE_AFTER_DAYS:
        return (
            f"⚠ 브랜치 보호 라이브 확인 {age}일 경과(임계 {STALE_AFTER_DAYS}일·마지막 "
            f"{last.isoformat()}) — 재확인 필요(PowerShell): {POWERSHELL_FETCH_RUNBOOK}"
        )
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render(report: Report, source: str) -> str:
    lines = [f"[브랜치 보호 드리프트 대조] 입력: {source}"]
    if report.violations:
        lines.append(f"❌ 위반 {len(report.violations)}건")
        lines += [f"  · {v}" for v in report.violations]
    if report.advisories:
        lines.append(f"⚠ 권고 {len(report.advisories)}건 (비차단)")
        lines += [f"  · {a}" for a in report.advisories]
    if report.waived:
        lines.append(f"⏳ 유예 {len(report.waived)}건 (만료 전)")
        lines += [f"  · {w}" for w in report.waived]
    if report.remediation:
        lines.append("시정 순서 (순서를 지켜라 — 뒤집으면 미강제로 되돌아간다):")
        # 번호는 렌더 시점에 매긴다 — compare()에 박아 두면 앞 축이 없을 때 ②부터 시작해
        # "①은 어디 갔나"를 읽는 사람에게 남긴다.
        lines += [f"  {i}. {r}" for i, r in enumerate(report.remediation, start=1)]
    if report.ok:
        lines.append("✔ 문서 선언과 라이브 설정이 정합 (위반 0)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "브랜치 보호 required check 라이브 드리프트 탐지 — "
            "gh api repos/<owner>/<repo>/rules/branches/main 출력(JSON 파일)을 입력으로 받는다."
        )
    )
    parser.add_argument("ruleset_json", type=Path, help="gh api 출력 JSON 파일 경로")
    parser.add_argument(
        "--doc",
        type=Path,
        default=None,
        help="대조할 문서(기본 .github/branch-protection-setup.md)",
    )
    parser.add_argument(
        "--record", action="store_true", help="확인 사실을 상태 파일에 기록(브리핑 리마인드용)"
    )
    parser.add_argument(
        "--today", type=date.fromisoformat, default=None, help="기준일(YYYY-MM-DD·테스트용)"
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    today = args.today or date.today()
    doc_path = args.doc or (root / _DOC_RELPATH)

    def _measurement_failed(message: str) -> int:
        """측정 실패를 보고하고 **그 사실도 기록**한다.

        기록하지 않으면 직전의 `ok` 상태가 남아 브리핑이 조용해진다 — 측정 실패가 통과로
        위장되는 경로이며, 이 도구가 막으려는 것과 정확히 같은 형태의 구멍이다.
        """
        print(f"❌ 측정 실패 — {message}", file=sys.stderr)
        if args.record:
            path = write_state(root, today, None, str(args.ruleset_json))
            print(f"기록: {path.relative_to(root)} (verdict=measure_fail)", file=sys.stderr)
        return 2

    try:
        raw = read_json_text(args.ruleset_json)
    except OSError as exc:
        return _measurement_failed(f"입력 파일을 읽지 못했다({type(exc).__name__}): {exc}")
    except RulesetInputError as exc:
        return _measurement_failed(str(exc))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _measurement_failed(
            f"JSON 파싱 불가: {exc}\n앞 200자: {raw[:200]}\n"
            "흔한 원인 — PowerShell 경유 수집(cp949 디코딩)으로 구조 문자가 유실됐다. "
            f"재수집: {POWERSHELL_FETCH_RUNBOOK}"
        )

    try:
        doc = parse_doc(doc_path)
        live = parse_live(payload, source=str(args.ruleset_json))
    except RulesetInputError as exc:
        return _measurement_failed(str(exc))

    report = compare(doc, live, today)
    print(render(report, str(args.ruleset_json)))

    if args.record:
        path = write_state(root, today, report, str(args.ruleset_json))
        print(f"기록: {path.relative_to(root)} (last_checked={today.isoformat()})")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
