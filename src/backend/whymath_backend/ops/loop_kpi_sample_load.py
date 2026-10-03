"""루프 KPI ①②④ 판정 표본 산출 경로 — 결정론 합성 부하 (EOS-38).

────────────────────────────────────────────────────────────────────────────
왜 이 경로인가 — Gate 2 판정 4회가 같은 모양으로 막혔다 (9/19·9/24·9/25·9/29)
────────────────────────────────────────────────────────────────────────────
공식 실측의 `loop_kpi_gate` ①②④는 분모 0으로 미측정이었다. 판정 하네스가 회차마다 학습자를
운영 삭제권 경로(`DELETE /v1/me`)로 **스스로 지우기** 때문이다. 학습자 1명을 남긴 보조 측정에서는
측정은 됐지만 표본 크기 때문에 FAIL이었다(① 1/1 → Wilson 하한 0.27 · ② 0/12 → 상한 0.18).
통과에 필요한 최소 표본은 ① 전건 성공 세션 52건 · ② 무위반 스캔 268행이다(`CONFIDENCE` 0.95).

세 후보 중 **(나) 결정론 합성 부하를 전용 DB에 쌓고 그 위에서 CLI를 돈다**를 골랐다. 근거:

  (가) 테스트 계정 세션을 관측창에 쌓는다 — 기각. 표본 52·268은 *사람이 쌓아야* 하고 판정 시점에
       그만큼 있다는 보장이 없다(ARCH-66 ⑥은 실학생 참여를 12/31 이후로 미뤘다). 재현도 안 된다.
  (다) "표본 부족 FAIL은 미측정과 같게 계상" — 기각. 측정이 *되게* 하는 경로가 아니라 측정 안 된
       것을 측정 안 됐다고 다시 부르는 것이다. 판정 4회가 막힌 이유를 한 줄도 바꾸지 못한다.
       게다가 미측정(exit 2)과 위반(exit 1)의 구별을 흐려 표본 부족이 결함 신호로 위장될 수 있다.
  (나) 채택 — 같은 입력이면 같은 부하(결정론)이고, 삭제하지 않으며, 판정 DB와 분리해
       *충분한 표본에서 수집기·임계·판정 경로가 설계대로 PASS/FAIL을 내는가*를 잰다.

────────────────────────────────────────────────────────────────────────────
이 부하가 말해 주는 것과 말해 주지 않는 것 (정직 표기)
────────────────────────────────────────────────────────────────────────────
**말해 주는 것**: 충분한 표본이 있을 때 ①②④가 측정되고, 위반 주입이 각 KPI를 FAIL로 바꾼다.
**말해 주지 않는 것**: 실제 학생이 루프를 끝까지 돈다는 것. 합성 부하는 **실사용 검증으로 계상하지
않는다**(P3-13 ARCH-66 ⑥ 단서와 같다). 그래서 판정 CLI에 `--sample-basis synthetic` 표지를 두고,
리포트·JSON에 그 사실이 각인되게 했다 — 판정 규칙은 `live`와 같고 라벨만 다르다.

② 분모는 학습자 행이 아니라 *콘텐츠·이벤트 행*이다(`integrity_violations_gate`가 `concept_node`·
`attempt_event` 등을 센다). 그래서 이 부하는 학습자 여정이 만드는 `attempt_event`(`문제시도`·
`시각화조작`)로 ②의 분모를 쌓는다 — 직접 INSERT하지 않고 공개 HTTP 표면으로만 만든다.

────────────────────────────────────────────────────────────────────────────
안전 장치 — 실DB에 합성 행을 섞지 않는다 (fail-closed)
────────────────────────────────────────────────────────────────────────────
  1. DB 이름이 `_kpi_sample`로 끝나야 한다. 아니면 **아무것도 하기 전에** 거부한다.
  2. 그 DB의 `user_profile`에 합성 도메인(`@kpi-sample.invalid`)이 아닌 학습자가 1명이라도 있으면
     거부한다 — 이름만 흉내 낸 실DB를 막는 두 번째 방어선이다.
  3. 외부 IdP 응답만 스텁한다(`_SyntheticIdentityProvider`). 그 뒤의 사용자 생성·JWT 발급·세션 기록·
     추천 기록은 운영 코드 그대로다. 이 스텁은 이 모듈이 만든 *프로세스 안의 앱*에만 주입되므로
     운영 서버의 provider 레지스트리에 닿지 않는다.

사용 (전용 DB는 `alembic upgrade head`가 적용된 빈 DB여야 한다):

    WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath_kpi_sample \\
      python -m whymath_backend.ops.loop_kpi_sample_load --learners 60 --manifest out/m.json
    WHYMATH_DATABASE_URL=... python -m whymath_backend.ops.loop_kpi_gate \\
      --since-hours 24 --sample-basis synthetic

종료 코드: 0 = 부하 완주 · 3 = 실행 거부/오류(전용 DB 가드·여정 실패 포함).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops.loop_kpi_gate import (
    CONFIDENCE,
    Direction,
    LoopKpi,
    spec_for,
)

__all__ = [
    "SAMPLE_DB_SUFFIX",
    "SYNTHETIC_EMAIL_DOMAIN",
    "DedicatedDatabaseError",
    "RequiredSamples",
    "assert_dedicated_database_name",
    "required_sample_sizes",
    "synthetic_email",
    "main",
]

SAMPLE_DB_SUFFIX: Final = "_kpi_sample"
#: 합성 학습자의 이메일 도메인 — `.invalid`는 RFC 2606 예약 TLD라 실주소와 겹치지 않는다.
SYNTHETIC_EMAIL_DOMAIN: Final = "kpi-sample.invalid"
_PROVIDER_NAME: Final = "demo"
_REDIRECT_URI: Final = "http://localhost:8000/kpi-sample/callback"
_BIRTH_YEAR: Final = 2006  # 비미성년 — 동의 게이트를 정상 경로로 통과한다.

# 콘텐츠 id 네임스페이스 — 같은 입력이면 같은 id(결정론·재실행 멱등).
_NAMESPACE: Final = uuid.UUID("3b1c8c52-6a0e-5d7e-9a3b-6b1d8f2f0a38")
_CONCEPT_COUNT: Final = 2
_PROBLEMS_PER_CONCEPT: Final = 3
#: 학습자 1명이 `시각화조작` 이벤트를 몇 건 남기는가 — ② 분모(attempt_event)를 쌓는 축.
_INTERACTIONS_PER_LEARNER: Final = 6
_DEFAULT_MARGIN: Final = 8  # 최소 표본 위 여유(순수 최소치는 경계라 한 건 어긋나도 FAIL).


class DedicatedDatabaseError(RuntimeError):
    """전용 DB가 아니다 — 합성 부하를 쌓지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class RequiredSamples:
    """KPI 통과에 필요한 최소 표본 — 임계·신뢰수준은 `loop_kpi_gate`가 정본이다(복제 금지)."""

    loop_completion_sessions: int  # ① 전건 성공 세션 수
    state_integrity_rows: int  # ② 무위반 스캔 행 수


def required_sample_sizes(*, search_limit: int = 100_000) -> RequiredSamples:
    """게이트의 임계·방향·신뢰수준에서 최소 표본을 **계산**한다 — 52·268을 상수로 적지 않는다.

    숫자를 적어 두면 임계가 바뀔 때 두 곳이 어긋난다(정본은 `LOOP_KPI_SPECS`). 그래서 같은
    `wilson_*_bound`와 `CONFIDENCE`로 다시 찾는다. 못 찾으면(임계가 도달 불가) 예외 — 조용히
    0을 돌려주면 "표본 없이도 통과"로 읽힌다.
    """
    loop = spec_for(LoopKpi.LOOP_COMPLETION)
    integrity = spec_for(LoopKpi.STATE_INTEGRITY)
    if loop.direction is not Direction.AT_LEAST or integrity.direction is not Direction.AT_MOST:
        raise RuntimeError("KPI 방향이 바뀌었다 — 최소 표본 산식을 다시 확인한다.")

    def _first(predicate: Any) -> int:
        for n in range(1, search_limit + 1):
            if predicate(n):
                return n
        raise RuntimeError(f"{search_limit}건 안에 임계에 도달할 수 없다 — 임계·신뢰수준 확인.")

    return RequiredSamples(
        loop_completion_sessions=_first(
            lambda n: wilson_lower_bound(n, n, CONFIDENCE) >= loop.threshold
        ),
        state_integrity_rows=_first(
            lambda n: wilson_upper_bound(0, n, CONFIDENCE) <= integrity.threshold
        ),
    )


def assert_dedicated_database_name(database_url: str) -> str:
    """DB 이름이 전용 접미사로 끝나는지 본다. 통과하면 DB 이름을 돌려준다.

    *이름 검사는 첫 번째 방어선일 뿐이다* — 두 번째(학습자 비합성 0건)는 연결 후
    `_assert_only_synthetic_learners`가 본다.
    """
    name = make_url(database_url).database
    if not name:
        raise DedicatedDatabaseError("DB 이름이 없는 URL이다 — 전용 DB를 지정한다.")
    if not name.endswith(SAMPLE_DB_SUFFIX):
        raise DedicatedDatabaseError(
            f"DB 이름 {name!r}이 {SAMPLE_DB_SUFFIX!r}로 끝나지 않는다 — 합성 부하는 전용 DB에만 "
            "쌓는다(실DB·판정 DB 오염 방지)."
        )
    return name


def synthetic_email(index: int) -> str:
    return f"learner-{index:04d}@{SYNTHETIC_EMAIL_DOMAIN}"


def _content_id(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"kpi-sample/{kind}/{key}")


async def _assert_only_synthetic_learners(database_url: str, *, learners: int) -> None:
    """전용 DB 두 번째 방어선 — 비합성 학습자가 1명이라도 있으면 거부한다."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            # email_hash만 저장돼(평문 미저장) 도메인으로 직접 거를 수 없다 — 합성 학습자의
            # 해시 집합과 대조한다. 합성이 아닌 행이 하나라도 있으면 그 DB는 전용이 아니다.
            from whymath_backend.api.auth import email_hash

            rows = (await conn.execute(text("SELECT email_hash FROM user_profile"))).scalars().all()
            # 합성 학습자 색인은 0부터 연속이다(부하가 항상 0에서 시작) — 기존 행 수와 이번 요청 중
            # 큰 쪽까지만 해시를 만들면 이전에 더 크게 돌린 부하의 행도 포함된다.
            synthetic = {email_hash(synthetic_email(i)) for i in range(max(len(rows), learners))}
            foreign = [h for h in rows if h not in synthetic]
            if foreign:
                raise DedicatedDatabaseError(
                    f"user_profile에 합성 학습자가 아닌 행이 {len(foreign)}건 있다 — 전용 DB가 "
                    "아니다. 이름만 흉내 낸 실DB일 수 있어 거부한다."
                )
    finally:
        await engine.dispose()


async def _seed_content(
    database_url: str,
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, uuid.UUID]]]:
    """저작 콘텐츠(개념·문항·매핑)를 결정론 id로 멱등 시딩한다 — 학습자 상태는 쓰지 않는다."""
    from whymath_backend.db.models.concept import Concept, ProblemConcept
    from whymath_backend.db.models.problem import Problem
    from whymath_backend.schema.concept import Concept as ConceptSchema
    from whymath_backend.schema.concept import ProblemConcept as ProblemConceptSchema
    from whymath_backend.schema.enums import (
        ConceptLevel,
        ConceptRole,
        Curriculum,
        ReviewStatus,
        SourceType,
        Subject,
    )
    from whymath_backend.schema.problem import Problem as ProblemSchema

    concept_ids: list[uuid.UUID] = []
    problem_concept: list[tuple[uuid.UUID, uuid.UUID]] = []
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for c in range(_CONCEPT_COUNT):
                cid = _content_id("concept", str(c))
                concept_ids.append(cid)
                await session.merge(
                    Concept.from_schema(
                        ConceptSchema(
                            concept_id=cid,
                            code=f"UC.kpisample.{c}",
                            name_ko=f"합성표본개념{c}",
                            level=ConceptLevel.세부개념,
                            behavior_skills=[],
                        )
                    )
                )
                for k in range(_PROBLEMS_PER_CONCEPT):
                    pid = _content_id("problem", f"{c}-{k}")
                    problem_concept.append((pid, cid))
                    await session.merge(
                        Problem.from_schema(
                            ProblemSchema(
                                problem_id=pid,
                                source_type=SourceType.자체생성,
                                review_status=ReviewStatus.approved,
                                curriculum_version=Curriculum.REVISION_2022,
                                valid_from_year=2022,
                                subject=Subject.공통,
                                unit_codes=[f"U-kpisample-{c}-{k}"],
                                # 난이도를 서로 다르게 — 추천이 θ 근방 최근접을 고른다.
                                difficulty_overall=2.0 + c * 1.5 + k * 0.7,
                                answer="kpi-sample-synthetic-answer",
                            )
                        )
                    )
                    await session.merge(
                        ProblemConcept.from_schema(
                            ProblemConceptSchema(
                                problem_id=pid, concept_id=cid, role=ConceptRole.PRIMARY
                            )
                        )
                    )
            await session.commit()
    finally:
        await engine.dispose()
    return concept_ids, problem_concept


class _SyntheticIdentityProvider:
    """외부 IdP 스텁 — 현재 지정된 합성 학습자의 신원만 돌려준다(검증 없음·프로세스 내부 전용)."""

    def __init__(self) -> None:
        self.index = 0

    async def fetch_identity(self, code: str, redirect_uri: str) -> Any:
        from whymath_backend.api.auth import OAuthIdentity

        return OAuthIdentity(
            provider=_PROVIDER_NAME,
            subject=f"kpi-sample-{self.index:04d}",
            email=synthetic_email(self.index),
            birth_year=_BIRTH_YEAR,
        )


def _run_journey(
    client: Any,
    provider: _SyntheticIdentityProvider,
    index: int,
    problems: list[uuid.UUID],
    concept_codes: list[str],
) -> dict[str, int]:
    """학습자 1명의 루프 1바퀴 — 로그인 → 진단 출제 → 시도 3건 → 조작 이벤트 → 다음 추천.

    **삭제하지 않는다**(판정 하네스가 스스로 지운 것이 4회 공전의 원인이다). 어느 단계든
    기대한 응답이 아니면 예외로 중단한다 — 부분 부하를 "완주"로 보고하면 표본 부족이 스며든다.
    """
    provider.index = index
    state = client.get(f"/v1/auth/{_PROVIDER_NAME}/state")
    _expect(state.status_code == 200, "state 발급", state)
    login = client.post(
        f"/v1/auth/{_PROVIDER_NAME}/callback",
        json={"code": "kpi-sample", "redirect_uri": _REDIRECT_URI, "state": state.json()["state"]},
    )
    _expect(login.status_code == 200, "로그인", login)
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    diag = client.get("/v1/me/next-problem?purpose=diagnosis", headers=auth)
    _expect(diag.status_code == 200, "진단 출제", diag)

    # 시도 3건: 오답 2 → 정답 1. 학습자마다 시작 문항을 돌려 문항 풀 전체를 쓴다(결정론).
    attempts = 0
    for step in range(3):
        pid = problems[(index + step) % len(problems)]
        answered = client.post(
            "/v1/me/attempts",
            headers=auth,
            json={
                "problem_id": str(pid),
                "is_correct": step == 2,
                "student_answer": "kpi-sample-synthetic-answer" if step == 2 else "0",
            },
        )
        _expect(answered.status_code == 201, f"시도 {step}", answered)
        attempts += 1

    interactions = 0
    for k in range(_INTERACTIONS_PER_LEARNER):
        posted = client.post(
            "/v1/interactions",
            headers=auth,
            json={
                "type": "param_change",
                "payload": {"name": "a", "value": k},
                "concept_id": concept_codes[k % len(concept_codes)],
                "scene_id": f"kpi-sample-scene-{k}",
            },
        )
        _expect(posted.status_code == 204, f"조작 이벤트 {k}", posted)
        interactions += 1

    # 첫 시도 *이후*의 추천 — ① 분자가 요구하는 흐름(Attempt → … → Recommendation).
    nxt = client.get("/v1/me/next-problem", headers=auth)
    _expect(nxt.status_code == 200, "다음 추천", nxt)
    return {"attempts": attempts, "interactions": interactions}


def _expect(ok: bool, step: str, response: Any) -> None:
    if not ok:
        # 응답 본문을 남긴다(원인 유실 금지) — 시크릿은 응답에 없다(토큰은 로그인 성공 본문에만).
        raise RuntimeError(
            f"여정 단계 실패: {step} → HTTP {response.status_code} {response.text[:300]}"
        )


async def _count(database_url: str) -> dict[str, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            out: dict[str, int] = {}
            for key, sql in (
                ("learners", "SELECT count(*) FROM user_profile"),
                ("sessions", "SELECT count(*) FROM learning_session"),
                ("attempts", "SELECT count(*) FROM problem_attempt"),
                ("attempt_events", "SELECT count(*) FROM attempt_event"),
                (
                    "recommendation_events",
                    "SELECT count(*) FROM evidence_event"
                    " WHERE event_type = 'recommendation_render'",
                ),
            ):
                out[key] = int((await conn.execute(text(sql))).scalar_one())
            return out
    finally:
        await engine.dispose()


def run_load(learners: int, *, database_url: str) -> dict[str, Any]:
    """합성 부하를 쌓는다. 전용 DB 가드를 **먼저** 통과해야 한다."""
    assert_dedicated_database_name(database_url)
    asyncio.run(_assert_only_synthetic_learners(database_url, learners=learners))

    from fastapi.testclient import TestClient

    from whymath_backend.api._rate_limit import reset_store
    from whymath_backend.app import create_app
    from whymath_backend.config import Settings, get_settings

    _, problem_concept = asyncio.run(_seed_content(database_url))
    problems = [pid for pid, _ in problem_concept]
    concept_codes = [f"UC.kpisample.{c}" for c in range(_CONCEPT_COUNT)]

    # 이 프로세스 안의 일회용 앱에만 쓰는 임의 서명 키 — 저장·출력하지 않는다(하드코딩 금지).
    settings = Settings(
        jwt_secret_key=SecretStr(secrets.token_urlsafe(32)),
        oauth_redirect_uri_allowlist=_REDIRECT_URI,
    )
    provider = _SyntheticIdentityProvider()
    app = create_app(oauth_providers={_PROVIDER_NAME: provider})
    app.dependency_overrides[get_settings] = lambda: settings

    total_attempts = 0
    total_interactions = 0
    with TestClient(app) as client:
        for index in range(learners):
            # 이 프로세스 안의 일회용 앱의 IP 버킷만 비운다 — 운영 서버가 아니다(테스트 격리용 API).
            asyncio.run(reset_store())
            result = _run_journey(client, provider, index, problems, concept_codes)
            total_attempts += result["attempts"]
            total_interactions += result["interactions"]

    counts = asyncio.run(_count(database_url))
    needed = required_sample_sizes()
    return {
        "sample_basis": "synthetic",
        "note": "합성 부하 — 실사용 검증으로 계상하지 않는다(P3-13 ARCH-66 ⑥ 단서).",
        "database": make_url(database_url).database,
        "generated_at": datetime.now(UTC).isoformat(),
        "learners_requested": learners,
        "journeys": {"attempts": total_attempts, "interactions": total_interactions},
        "db_counts": counts,
        "required": {
            "loop_completion_sessions": needed.loop_completion_sessions,
            "state_integrity_rows": needed.state_integrity_rows,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.loop_kpi_sample_load",
        description="루프 KPI ①②④ 판정 표본 — 결정론 합성 부하를 전용 DB에 쌓는다(EOS-38).",
    )
    required = required_sample_sizes()
    parser.add_argument(
        "--learners",
        type=int,
        default=required.loop_completion_sessions + _DEFAULT_MARGIN,
        help=(
            f"합성 학습자 수(기본 {required.loop_completion_sessions + _DEFAULT_MARGIN} = ① 최소 "
            f"{required.loop_completion_sessions} + 여유 {_DEFAULT_MARGIN}). 학습자 1명 = 세션 1개."
        ),
    )
    parser.add_argument("--manifest", default=None, help="부하 요약 JSON 저장 경로(선택).")
    args = parser.parse_args(argv)

    if args.learners <= 0:
        print("[loop_kpi_sample_load] --learners는 양수여야 한다.", file=sys.stderr)
        return 3

    from whymath_backend.config import Settings

    try:
        manifest = run_load(args.learners, database_url=Settings().database_url)
    except DedicatedDatabaseError as exc:
        print(f"[loop_kpi_sample_load] 거부: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - 부분 부하를 완주로 보이지 않게 타입명과 함께 보고
        print(f"[loop_kpi_sample_load] 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    text_out = json.dumps(manifest, ensure_ascii=False, indent=2)
    print(text_out)
    if args.manifest:
        path = Path(args.manifest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text_out + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - 엔트리포인트
    raise SystemExit(main())
