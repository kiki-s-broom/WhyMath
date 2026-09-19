"""[P-11] 계획서 300 §12 필수 API 12종 매핑표의 **실측 동결**.

왜 이 테스트가 있는가
--------------------
매핑표를 문서에만 적으면 **조용히 낡는다**. 라우트가 개명·삭제돼도 마크다운 표는 그대로
`있음`이라고 말하고, 그 표를 읽은 다음 세션은 없는 표면을 전제로 설계한다. 이 저장소는
2026-09-03 갭 리뷰에서 실제로 그 형태의 오판을 냈다 — `GET /contents/{id}` 행이 목록 좌석
(`GET /v1/concepts/content`)을 근거로 `충족`으로 적혔는데, 목록과 단건은 다른 표면이라
**단건 조회 경로는 0건**이었다.

그래서 매핑의 정본은 문서가 아니라 아래 `REQUIRED_SURFACES`이고, 이 테스트가 세 축을 붙든다:

  ① **경로 실재** — 매핑된 (메서드, 경로)가 *실제 앱 라우트 표*에 있다. 라우트 추출은
     재구현하지 않고 저장소의 단일 진실 원천(`ops.declared_unwired_audit.app_route_entries`)을
     쓴다. 그 모듈이 존재하는 이유 자체가 순진한 `app.routes` 순회가 `/v1/**`를 통째로
     누락한다는 실측이다(FastAPI 0.140 `_IncludedRouter`).
  ② **문서 정합** — `docs/architecture/phase2_required_api_surface_map.md`의 표가 이 자료구조와
     글자까지 일치한다. 문서만 고치거나 코드만 고치면 red다.
  ③ **부재의 실재** — `없음`으로 적은 것이 정말 없다. 부재 주장은 검색 방법이 옳아야
     성립하므로 존재 주장보다 오류율이 구조적으로 높다(CLAUDE.md 부재 판정 절차) — 그래서
     부재도 라우트 표 대조로 기계가 판정한다.

수집기 파손 방어
---------------
라우트 표가 비거나 비정상적으로 작으면 ①은 "전부 없음"이 아니라 **위장 통과**가 될 수 있다
(모든 경로가 없다고 나오면 `없음` 행만 통과하고 나머지는 실패하니 실제로는 시끄럽게 깨지지만,
반대로 부재 검사 ③은 조용히 통과한다). 그래서 하한을 두고 미만이면 판정이 아니라 입력 오류로
실패한다.

**이 테스트가 보지 않는 것(정직한 공백)**: 응답 스키마·권한·상태코드는 보지 않는다. 여기서
보는 것은 *표면의 실재와 표의 정합*뿐이고, 표면들이 실제로 **이어지는가**는
`test_p11_five_stage_loop_chain.py`가 따로 판정한다.
"""

from __future__ import annotations

import pathlib
import re

from whymath_backend.ops.declared_unwired_audit import app_route_entries

#: 매핑표 정본. (계획서 API, 저장소 경로 튜플, 판정) — 문서의 표와 1:1 대응한다.
#: 판정 어휘는 문서 상단 정의를 따른다: 있음 / 다른 이름으로 있음 / 없음.
REQUIRED_SURFACES: tuple[tuple[str, tuple[tuple[str, str], ...], str], ...] = (
    (
        "POST /diagnostics",
        (
            ("POST", "/v1/me/assessments/capture"),
            ("POST", "/v1/me/assessments/assemble"),
            ("GET", "/v1/me/diagnosis/summary"),
            ("GET", "/v1/me/diagnosis/concepts"),
        ),
        "다른 이름으로 있음",
    ),
    ("GET /learner-state", (("GET", "/v1/me/learner-state"),), "있음"),
    ("GET /learning/next", (("GET", "/v1/me/next-problem"),), "다른 이름으로 있음"),
    ("GET /concepts/{id}", (("GET", "/v1/concepts/{concept_id}"),), "있음"),
    ("GET /contents/{id}", (("GET", "/v1/concepts/content/{code}"),), "있음"),
    ("GET /problems/{id}", (("GET", "/v1/problems/{problem_id}"),), "있음"),
    ("POST /attempts", (("POST", "/v1/me/attempts"),), "있음"),
    (
        "POST /assessments",
        (
            ("POST", "/v1/me/assessments/capture"),
            ("POST", "/v1/me/assessments/assemble"),
        ),
        "다른 이름으로 있음",
    ),
    (
        "GET /recommendations/next",
        (
            ("GET", "/v1/me/next-problem"),
            ("GET", "/v1/me/weak-concepts/{concept_id}/learning-path"),
            ("GET", "/v1/me/review-queue"),
        ),
        "다른 이름으로 있음",
    ),
    (
        "POST /tutor/query",
        (
            ("POST", "/v1/coach"),
            ("POST", "/v1/coach/sessions/{dialogue_id}/turns"),
        ),
        "다른 이름으로 있음",
    ),
    (
        "GET /sessions/{id}",
        (
            ("GET", "/v1/coach/sessions/{dialogue_id}"),
            ("GET", "/v1/me/sessions"),
        ),
        "다른 이름으로 있음",
    ),
    (
        "GET /learning/result",
        (
            ("GET", "/v1/me/learning-metrics"),
            ("GET", "/v1/me/target-progress"),
            ("POST", "/v1/me/objectives/{objective_id}/outcome"),
        ),
        "다른 이름으로 있음",
    ),
)

#: 매핑표 문서 — 표가 위 자료구조와 일치해야 한다.
DOC = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docs/architecture/phase2_required_api_surface_map.md"
)

#: 라우트 표 하한 — 이보다 적으면 수집기가 깨진 것이다(판정이 아니라 입력 오류).
#: 판정 기준 main `40f78795`에서 실측 119건. 라우트가 절반 이하로 줄 일은 정상 변경이 아니다.
_MIN_ROUTES = 60


def _routes() -> set[tuple[str, str]]:
    """앱 라우트 표 — 재구현 0(저장소 단일 진실 원천 경유)."""
    entries = {(m, p) for m, p in app_route_entries()}
    assert len(entries) >= _MIN_ROUTES, (
        f"라우트 수집이 {len(entries)}건뿐이다(하한 {_MIN_ROUTES}) — 판정이 아니라 수집기 "
        "파손이다. 이 상태에서 '부재'를 판정하면 전건이 공허하게 통과한다."
    )
    return entries


def test_every_planned_surface_maps_to_a_live_route() -> None:
    """① 매핑된 경로가 실제 앱 라우트 표에 있다(`없음` 판정 행은 제외)."""
    live = _routes()
    missing: list[str] = []
    for planned, mapped, verdict in REQUIRED_SURFACES:
        if verdict == "없음":
            continue
        for method, path in mapped:
            if (method, path) not in live:
                missing.append(f"{planned} → {method} {path}")
    assert (
        not missing
    ), "매핑표가 가리키는 경로가 앱에 없다 — 표가 낡았거나 라우트가 사라졌다:\n  " + "\n  ".join(
        missing
    )


def test_surfaces_marked_absent_are_really_absent() -> None:
    """③ `없음`으로 적은 것이 정말 없다 — 부재 주장도 기계가 판정한다.

    `없음` 행이 0건이어도 이 테스트는 공허하지 않다: 라우트 하한 검사가 먼저 돌고, 아래
    루프가 비면 "현재 부재 주장이 없다"는 사실 자체가 ①과 문서 대조로 이미 고정돼 있다.
    """
    live = _routes()

    # 음성 대조군 — 부재 판정 자체가 변별력이 있는지 먼저 본다. 현재 `없음` 행이 0건이라
    # 아래 루프만 두면 이 검사는 **공허하게 통과**한다("스캔 0건은 실패" — CLAUDE.md). 있지도
    # 않은 경로를 라우트 표가 '있다'고 말하면 부재 판정 전체가 무의미하므로 그것을 먼저 배제한다.
    fabricated = ("GET", "/v1/__surface_map_negative_control__")
    assert fabricated not in live, (
        f"존재하지 않아야 할 합성 경로가 라우트 표에 있다: {fabricated} — 라우트 대조가 "
        "무엇이든 '있다'고 답하고 있으므로 부재 판정을 신뢰할 수 없다."
    )

    wrongly_absent: list[str] = []
    for planned, mapped, verdict in REQUIRED_SURFACES:
        if verdict != "없음":
            continue
        for method, path in mapped:
            if (method, path) in live:
                wrongly_absent.append(f"{planned} → {method} {path}")
    assert (
        not wrongly_absent
    ), "`없음`으로 적었는데 라우트가 실재한다 — 표가 부재를 오보하고 있다:\n  " + "\n  ".join(
        wrongly_absent
    )


def test_doc_table_matches_the_canonical_mapping() -> None:
    """② 문서의 표가 자료구조와 글자까지 일치한다(문서만/코드만 고치면 red)."""
    assert DOC.exists(), f"매핑표 문서가 없다: {DOC}"
    text = DOC.read_text(encoding="utf-8")

    # 표 본문 행만 추출한다 — `| 1 | \`POST /diagnostics\` | ... | 판정 |`
    rows = re.findall(r"^\|\s*(\d+)\s*\|(.+?)\|(.+?)\|(.+?)\|\s*$", text, flags=re.MULTILINE)
    assert len(rows) == len(REQUIRED_SURFACES), (
        f"문서 표의 행 수({len(rows)})가 정본({len(REQUIRED_SURFACES)})과 다르다 — "
        "한쪽만 고쳤다."
    )

    mismatches: list[str] = []
    for (idx, planned_cell, mapped_cell, verdict_cell), (planned, mapped, verdict) in zip(
        rows, REQUIRED_SURFACES, strict=True
    ):
        want_planned = f"`{planned}`"
        got_planned = planned_cell.strip()
        if got_planned != want_planned:
            mismatches.append(f"#{idx} 계획서 API: 문서={got_planned!r} 정본={want_planned!r}")
        want_mapped = " · ".join(f"`{m} {p}`" for m, p in mapped)
        got_mapped = mapped_cell.strip()
        if got_mapped != want_mapped:
            mismatches.append(f"#{idx} 매핑: 문서={got_mapped!r} 정본={want_mapped!r}")
        if verdict_cell.strip() != verdict:
            mismatches.append(f"#{idx} 판정: 문서={verdict_cell.strip()!r} 정본={verdict!r}")

    assert not mismatches, "문서 표와 정본 매핑이 어긋났다:\n  " + "\n  ".join(mismatches)


def test_doc_pins_its_judgement_base_commit() -> None:
    """판정 문서는 기준 커밋 해시를 박는다 — 해시 없는 판정은 재현 불가다(CLAUDE.md)."""
    text = DOC.read_text(encoding="utf-8")
    assert re.search(r"판정 기준:\s*main\s*`[0-9a-f]{8,40}`", text), (
        "매핑표 문서 상단에 `판정 기준: main <해시>`가 없다 — 판정은 시점에 종속되므로 "
        "해시 없는 표는 며칠 뒤 조용히 거짓이 된다."
    )


def test_all_twelve_planned_surfaces_are_covered() -> None:
    """계획서 §12가 지정한 12종을 하나도 빠뜨리지 않았다(중복 계상도 금지)."""
    planned = [p for p, _m, _v in REQUIRED_SURFACES]
    assert len(planned) == 12, f"12종이어야 한다: {len(planned)}종"
    assert len(set(planned)) == 12, f"중복이 있다: {planned}"
