"""ARCH-38 판정("AssessmentResult 좌석 분리하지 않음")의 **전제 동결**.

왜 이 파일이 있는가 (Codex P2 · PR #997)
----------------------------------------
`ARCH-38`은 정본 `docs/architecture/canonical_entity_model_v1.md` §3-C에 "혼입 유지"를
판정하며 **재확인 지점 3종**을 적었다. 그런데 초판은 그 재확인을 후속 태스크(`ARCH-40`)로만
등재했고, 그 태스크는 `status: todo`·`depends_on: []`·`requires_gates: []`라 **selector가
곧바로 착수 후보로 계산했다**(실측: `backlog.py next --n 534 --json` 후보 124건에 포함).

즉 "트리거가 성립하면 재판정한다"고 적어 놓고 **트리거를 기다리는 장치가 없었다** — 지금
실행하면 전부 False로 확인하고 또 하나의 즉시-후보를 재생성할 뿐이고, 방치하면 재확인은
집행되지 않는다. `ARCH-38` 자신이 인용한 "정본화를 집행으로 착각한 완료 선언 금지"를
그 판정의 *재확인 축*에서 되풀이한 셈이다. 이 파일이 그 공백의 **자동 축**을 메운다.

무엇을 강제하는가 — 판정 근거 ①의 부정을 RED로 만든다
--------------------------------------------------
판정의 첫 근거는 *"W8 경로(채점→오개념→Mastery)가 `assessment`를 읽지도 쓰지도 않는다"*였다.
그 근거가 무너지는 순간 = **채점 경로가 ORM `Assessment`를 참조하기 시작하는 순간**이고,
그때 분리 판정은 다시 계산돼야 한다. 이 테스트는 그 순간에 RED를 낸다.

설계 결정 4가지 (같은 부류의 가드가 뚫린 전례를 피한다)
-----------------------------------------------------
1. **문자열이 아니라 AST를 본다** — "이 문자열을 쓰지 마라" 형태는 표기 변형(`as` 별칭·
   줄바꿈·주석)에서 뚫린다. `ast.ImportFrom` 노드의 실제 이름 목록을 본다
   (CLAUDE.md 2026-09-01 ① "금지 패턴 열거 대신 산출물 검사").
2. **저장소 전수 스캔 + 허용목록** — "W8 경로 모듈 N개만 검사"는 목록을 좁히는 순간 사각이
   생긴다(경로가 하나 늘면 가드 밖). 반대로 `Assessment`를 임포트하는 파일 **전건**을 모아
   허용목록과 대조하면, 새 임포터가 *어디서 생기든* 걸린다.
3. **스캔 0건은 실패** — 임포터를 하나도 못 찾으면 그것은 "위반 없음"이 아니라 **스캐너가
   깨졌다**는 뜻이다(모듈 경로 변경·파서 오류). 공허한 통과를 금지한다
   (CLAUDE.md 2026-09-01 ④).
4. **허용목록 항목에 사유를 강제** — 무사유 예외 금지. 사라진 항목도 RED로 낸다(파일이
   옮겨졌는데 가드가 조용히 통과하면, 그 사이 새 임포터가 들어와도 안 보인다).

**한계(있는 척 금지)**: 이 가드는 `from ... import Assessment` 형태만 본다. `import
whymath_backend.db.models.assessment as m` 뒤 `m.Assessment` 속성 접근은 잡지 않는다 —
저장소 실측 0건이라 지금은 공백이 아니지만, *잡지 못한다는 사실 자체*는 적어 둔다.
또한 이 가드는 판정 근거 **①만** 자동화한다. 근거 ②(갱신 writer 등장)·③(값을 읽는 서빙
reader 착지)은 정적으로 확정하기 어려워 **날짜 리마인더 게이트**
(`G-arch38-verdict-recheck` → `ARCH-40`의 `requires_gates`)가 담당한다. 자동 축과 일정 축을
합쳐야 재확인이 닫힌다 — 어느 한쪽도 단독으로는 충분하지 않다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PKG_ROOT = _REPO_ROOT / "src" / "backend" / "whymath_backend"
_CANON_DOC = _REPO_ROOT / "docs" / "architecture" / "canonical_entity_model_v1.md"

# ORM `Assessment`를 노출하는 두 경로 — 모듈 직접 임포트와 `db/models/__init__` 재수출.
# 재수출 경로를 빼면 `from whymath_backend.db.models import Assessment` 한 줄로 우회된다.
_ASSESSMENT_MODULES: frozenset[str] = frozenset(
    {"whymath_backend.db.models.assessment", "whymath_backend.db.models"}
)
_ORM_CLASS = "Assessment"

# ORM `Assessment`를 임포트해도 되는 파일과 **그 사유**(무사유 예외 금지).
# 2026-09-06 실측 전건이며, 어느 것도 채점→오개념→Mastery 경로가 아니다 — 그것이 판정 근거 ①.
_ALLOWED_IMPORTERS: dict[str, str] = {
    "db/models/__init__.py": "ORM 재수출(패키지 표면) — 좌석 정의 자신",
    "api/me.py": "유일한 writer·reader 표면 5종(capture·assemble·list·complete·delete)",
    "privacy/erasure.py": "GDPR 삭제 계획(_ERASURE_PLAN) 등재 — 파기 대상 테이블",
    "privacy/export.py": "본인 반출 직렬화(_STUDENT_FACING_SERIALIZERS)",
    "privacy/retention.py": "보존기간 파기 계획 — 기준 컬럼 started_at",
    "harness/assessment_seat_reach_report.py": "오프라인 도달 관측 리포트(게이트 아님·CLI)",
    # EOS-11(2026-09-16): 학습 시간선 투영의 읽기 전용 원천 하나. 추가 시 재판정 트리거 1·3을
    # 둘 다 대조했고 **어느 쪽도 발동하지 않았다**:
    #   · 트리거 1(W8 경로 접촉) — 이 모듈은 채점→오개념→Mastery 경로가 아니다. 쓰기 0건
    #     (session.add·commit 0)이고, W8 런타임 어디에서도 호출되지 않는 조회 표면이다.
    #   · 트리거 3(5필드를 값으로 읽어 판단) — 읽는 컬럼은 `started_at`·`completed_at`·
    #     `assessment_type` 뿐이며 예측 5필드(estimated_grade·estimated_score·
    #     estimated_percentile·target_university_id·admission_probability)를 건드리지 않는다.
    #     읽은 값은 시간선 항목으로 **직렬화**될 뿐 판단에 쓰이지 않는다(§3-C가 "응답에 실어
    #     보내는 직렬화는 소비가 아니다"라고 명시한 축).
    # 즉 판정 근거 ①·③은 그대로 성립한다 — 초록을 만들려고 넣은 예외가 아니라, 근거를
    # 대조한 뒤의 등재다. 5필드를 읽기 시작하면 `ARCH-40` 재판정 대상이 된다.
    "l2/learning_event_trace.py": (
        "학습 시간선 읽기 투영(EOS-11) — started_at·completed_at·assessment_type만 읽는 "
        "읽기 전용 원천. W8 경로 아님·쓰기 0건·예측 5필드 미접촉"
    ),
}

# 판정 근거 ①이 "접촉 0"이라고 단언한 채점→오개념→Mastery 경로.
# 존재 자체를 확인한다 — 파일이 옮겨졌는데 가드가 조용히 통과하면 근거가 검증되지 않는다.
_W8_PATH_MODULES: tuple[str, ...] = (
    "api/coach.py",
    "l2/mastery_tracking.py",
    "l2/skill_mastery_tracking.py",
    "l2/attempt_skill_event.py",
)


def _orm_assessment_importers() -> dict[str, list[int]]:
    """`Assessment`(ORM)를 임포트하는 파일 → 줄번호. AST 기준(문자열 검색 아님)."""
    found: dict[str, list[int]] = {}
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 예외 타입명 동반 — 침묵 실패 금지
            raise AssertionError(
                f"{path.relative_to(_PKG_ROOT)}: AST 파싱 실패({type(exc).__name__}: {exc}) — "
                "파싱 못 한 파일은 스캔에서 조용히 빠진다."
            ) from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module not in _ASSESSMENT_MODULES:
                continue
            if any(alias.name == _ORM_CLASS for alias in node.names):
                found.setdefault(str(path.relative_to(_PKG_ROOT)), []).append(node.lineno)
    return found


def test_scan_is_not_vacuous() -> None:
    """설계 ③ — 임포터 0건은 '위반 없음'이 아니라 스캐너가 깨진 것이다."""
    assert _PKG_ROOT.is_dir(), f"패키지 루트가 없다: {_PKG_ROOT} — 스캔 대상이 통째로 사라졌다."
    importers = _orm_assessment_importers()
    assert importers, (
        "ORM `Assessment` 임포터를 한 건도 찾지 못했다 — 좌석이 사라졌거나 모듈 경로가 바뀌어 "
        f"스캐너가 무력해졌다(대상 모듈: {sorted(_ASSESSMENT_MODULES)}). "
        "공허한 통과를 내지 않는다(CLAUDE.md '스캔 0건은 실패')."
    )


def test_allowlist_entries_still_exist() -> None:
    """설계 ④ — 허용목록의 파일이 사라지면 RED. 조용히 줄어든 목록은 가드가 아니다."""
    missing = [rel for rel in _ALLOWED_IMPORTERS if not (_PKG_ROOT / rel).is_file()]
    assert not missing, (
        f"허용목록의 파일이 없다: {missing} — 옮겼다면 이 상수를 함께 고쳐라. "
        "목록만 낡으면 새 임포터가 들어와도 대조가 성립하지 않는다."
    )


def test_w8_path_modules_exist() -> None:
    """판정 근거 ①이 지목한 채점→오개념→Mastery 경로가 실재한다(대조 대상 실종 방지)."""
    missing = [rel for rel in _W8_PATH_MODULES if not (_PKG_ROOT / rel).is_file()]
    assert not missing, (
        f"판정 근거 ①이 '접촉 0'이라고 단언한 모듈이 없다: {missing}\n"
        "경로가 바뀌었다면 이 상수를 고치고, 그 김에 ARCH-38 판정 전제도 다시 확인하라 "
        f"(정본 {_CANON_DOC.relative_to(_REPO_ROOT)} §3-C)."
    )


def test_grading_path_does_not_touch_assessment_orm() -> None:
    """**핵심** — ARCH-38 판정 근거 ①의 부정을 RED로 낸다.

    허용목록 밖에서 ORM `Assessment`를 임포트하면, 판정의 전제("W8 경로가 이 테이블을 읽지도
    쓰지도 않는다")가 더 이상 사실이 아닐 수 있다는 뜻이다. 그때 필요한 것은 이 테스트를
    통과시키는 것이 **아니라** 분리 판정을 다시 계산하는 것이다.
    """
    importers = _orm_assessment_importers()
    unexpected = {rel: lines for rel, lines in importers.items() if rel not in _ALLOWED_IMPORTERS}

    on_w8_path = sorted(set(unexpected) & set(_W8_PATH_MODULES))
    detail = "\n".join(f"  · {rel}:{lines}" for rel, lines in sorted(unexpected.items()))
    assert not unexpected, (
        "ORM `Assessment`의 새 임포터가 생겼다 — ARCH-38 '혼입 유지' 판정의 근거 ①"
        "(W8 경로 접촉 0건)이 흔들린다.\n"
        f"{detail}\n"
        + (
            f"⚠ 그중 {on_w8_path} 는 채점→오개념→Mastery 경로 자체다 — 재판정 트리거 1이 "
            "**발동**했다.\n"
            if on_w8_path
            else ""
        )
        + f"조치: 정본 {_CANON_DOC.relative_to(_REPO_ROOT)} §5 절차로 `ARCH-40`을 착수해 "
        "분리 여부를 다시 판정하라. 이 목록에 사유 없이 추가해 초록을 만들지 않는다 "
        "— 그러면 이 가드는 위장이 된다."
    )


def _canon_section_3c() -> str:
    """정본에서 §3-C **절만** 잘라 낸다 — 문서 전역 substring 검색이 아니다.

    전역 검색은 두 방향으로 뚫린다: ⑴판정 문구가 §3-C 밖(각주·목차)에만 남아도 통과하고
    ⑵`판정` → `판정XX`처럼 **덧붙이는** 변형에서 원 문자열이 부분문자열로 살아남아 통과한다.
    실제로 이 파일의 초판이 ⑵로 뚫렸다(PR #997 뮤테이션 M6가 RED를 못 냈다) — 그래서
    `test_canonical_entity_model_freeze.py`의 `_slice` 선례대로 절 단위로 좁힌다.
    """
    assert _CANON_DOC.is_file(), f"정본 문서가 없다: {_CANON_DOC}"
    text = _CANON_DOC.read_text(encoding="utf-8")
    start_marker, end_marker = "### §3-C.", "### §3-D."
    i, j = text.find(start_marker), text.find(end_marker)
    assert i != -1, f"정본에서 절 머리를 찾지 못했다: {start_marker!r}"
    assert j > i, f"정본 절 순서가 어긋났다: {start_marker!r} → {end_marker!r}"
    return text[i:j]


def test_verdict_is_recorded_in_canon_section() -> None:
    """가드와 정본이 같은 판정을 가리키는지 — 한쪽만 바뀌면 드리프트가 무증상으로 진행된다.

    §3-C **절 안에서** 판정 마커를 찾는다. 마커는 정확히 일치해야 하며(부분문자열 허용 시
    덧붙이기 변형이 통과한다), 판정을 뒤집으려면 이 테스트도 함께 처분해야 한다 — 가드만
    남아 낡은 판정을 지키는 상태를 금지한다.
    """
    section = _canon_section_3c()
    marker = "혼입 유지로 판정"
    occurrences = section.count(marker)
    assert occurrences >= 1, (
        f"{_CANON_DOC.relative_to(_REPO_ROOT)} §3-C 절에서 판정 마커 {marker!r}를 찾지 못했다 — "
        "판정이 뒤집혔거나 절 구조가 바뀌었다. 뒤집혔다면 이 테스트 파일도 함께 처분하라."
    )
    # 덧붙이기 변형 차단 — 마커 뒤에 한글·영숫자가 이어 붙으면 다른 문구다.
    tail_corrupted = re.search(marker + r"[0-9A-Za-z\uac00-\ud7a3]", section)
    assert tail_corrupted is None, (
        f"§3-C의 판정 마커가 변형됐다: {tail_corrupted.group(0)!r} — "
        "부분문자열로 살아남은 마커는 판정의 증거가 아니다."
    )
