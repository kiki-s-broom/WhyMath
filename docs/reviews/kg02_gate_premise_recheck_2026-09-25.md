# KG-02 게이트 전제 재점검 — `G-kg02-review-promotion-llm-session` (2026-09-25)

> **판정 기준**: main `3a7a7315`. 실측은 `f138f894`에서 했고, 두 커밋 사이에 이 판정이 읽는 경로
> (`l4/content_supply.py`·`api/concepts.py`·`api/study.py`·`l1/**`·`l3/render/**`·`l3/router.py`·
> `harness/concept_content_review_{batch,apply}.py`·코퍼스 3종·`alembic/`)의 diff는 **0**이다.
>
> **판정**: Kiki 2026-09-25 — 3택 중 **"보류 + 대장 정정"**. 세션이 조사·실측·대장 정정을 했다.
> 사람 게이트를 닫거나 면제하지 않았다(게이트는 `pending` 그대로).

---

## 1. 요약 (먼저 읽을 것)

| 축 | 결론 |
|---|---|
| 재개 경로 | 등재 문면의 경로 ⓐ(S4-16 강등전 통과)가 **소멸**했다 — S4-16이 오늘 기각(cancelled)됐다. `review_gate.py`의 승격 서명 권한은 `HUMAN_REVIEWERS = ("kiki",)` 하나이고 `CERTIFIED_MACHINE_REVIEWERS`는 빈 튜플이다. LLM 검수 배치는 **선별 보조**이며, 그 결과로 승격되는 행은 0이다. |
| 게이트 목적 표면 | 등재 문면의 목적("KG-01 ③ 관측 축 `/concepts/search reviewed_only=true`가 실제로 소비되는 상태")은 **이 승격으로 달성할 수 없다**. search는 `atom_node`를 읽고, 승격은 `concept_content`를 바꾼다. 주입 실측: content 0→2, search 0→0(§3). |
| 학생 영향 | 학생 `/study` 공급(`get_concept_dsl`)은 `review_status`를 **읽지 않는다** — `ai_estimated` 행도 공급된다(§4). 따라서 지금 승격해도 학생 화면은 바뀌지 않는다. 그 노출 게이트의 판정·집행은 신규 `CONT-05`가 소유한다. |
| LLM 배치 통과 가능성 | 표본 52건 중 **1건만** 결함 판정돼도 상한 8.17%로 불합격(기준 5%). 이 도구는 응답 파싱 실패를 결함으로 센다 — 로컬 `qwen3:30b-a3b`는 다른 프롬프트에서 파싱 실패율 16%가 측정됐다(OPS-48). 통과는 기대하기 어렵다(§5). |
| 판정 | **보류 + 정정.** 게이트 입력 작업 = `CONT-05`(입력 없음 사유 자동 해제), 독촉 14일 → 35일(2026-10-26, P3 착수일). KG-02 acceptance ⑦에 관측 표면 정정 항을 덧붙였다. |

---

## 2. 등재(2026-09-21) 이후 바뀐 사실

1. **S4-16 기각** — 게이트 `G-s416-round2-live-battle`의 2차 정본 회차(v4 프로덕션, 로컬
   `qwen3:30b-a3b`)가 무결함 오검출 33/33(Wilson 상한 1.0000)을 냈고, Kiki가 3안("이 경로를 인간
   검수 대체 후보에서 내린다")을 택했다. S4-16은 `cancelled`다. 등재 문면이 적은 "S4-16 자신이
   blocked다"는 더 이상 사실이 아니다 — 대기할 것이 아니라 **닫힌 경로**다.
2. **1회차는 리허설로 강등** — 2026-09-23 Kiki 머신 회차가 로컬 전용 브랜치
   (`claude/adoring-mccarthy-sle0uj` HEAD `0367fce4`)에서 돌아 코드 출처를 main과 대조할 수 없었다
   (`HARN-163` 사고 경위). 결과는 표본 52건 중 33건 결함 판정 · Wilson 상한 73.5% · `BATCH_EXIT=1`.
3. **KG-08 착지** — 그 회차는 깨끗한 대조군이 없어 "콘텐츠가 나쁜가, rubric이 과민한가"를 가를 수
   없었다. KG-08(PR #1258)이 대조군 2건과 오검출 게이트를 넣었다. **대조군이 들어간 뒤의 재측정은
   아직 없다.**
4. **비용 축 전제 정정** — 2026-09-22 KG-02에 `ARCH-62` 선행을 붙인 사유("MID 좌석 = OpenRouter
   에서 실 LLM 호출")는 코드와 다르다. `concept_content_review_batch._build_provider`는 로컬
   `OllamaProvider`만 만든다. `ARCH-62`가 done이라 차단 영향은 없다.

---

## 3. 실측 ① — 승격이 어느 표면에 반영되는가 (주입)

### 3.1 환경

이 세션 컨테이너에 PostgreSQL 16.13을 띄우고 pgvector 0.8.0을 소스 빌드해 넣었다. alembic head
`8e4c2a7f1b93`까지 적용(테이블 87개), Python 3.12 venv에 backend `[dev]`를 설치했다.

적재:

- `concept_content` 846행 — `concept_content_v1`(437) + `concept_content_university_v1`(409)
- `atom_node` 2,683행 — `atom_graph_v1/graph.json` 전량
- `atom_embedding` 1,823행 — 세부개념 원자만, `FakeEmbeddingProvider`(적재·조회가 같은 공간)

### 3.2 구조 사실

| 사실 | 값 |
|---|---|
| 콘텐츠 code 중 `atom_embedding`(= search가 돌려줄 수 있는 집합)에 있는 수 | **0** / 846 |
| 콘텐츠 code 중 `atom_node`에 있는 수 | 409 — 전부 대학 소단원 노드(임베딩 대상 아님) |
| K-12 콘텐츠 437 code 중 `graph.json`에 있는 수 | 0 |
| `atom_node.review_status` 분포 | `ai_estimated` 2,683 (적재 시 상수) |

### 3.3 주입 단계와 결과

실제 승격 CLI(`concept_content_review_apply.main`)로 `N1`(K-12)·`AALG1-U1-S1`(대학, 원자 code와
겹치는 쪽)을 `reviewed_by: kiki` 서명으로 승격했다. 코퍼스 경로는 임시 사본으로 넘겨 저장소 파일은
건드리지 않았다. search 질의는 대상 두 콘텐츠의 이름과, 양성 대조용 원자 1건의 정확한 임베딩
텍스트 3종이다(각각 `reviewed_only=false`에서 20건씩 반환 — 검색 자체는 작동한다).

| 단계 | `/v1/concepts/content?reviewed_only=true` 건수 | `/v1/concepts/search` `reviewed_only=true` 히트 합 |
|---|---|---|
| S0 기준선 | 0 | 0 |
| S1 승격 CLI 실행 | exit 0 · DB 2건 · 코퍼스 사본 2건 갱신 | — |
| S2 승격 후 | **2** | **0** |
| S3 양성 대조 — 원자 1건을 직접 `reviewed`로 | 2 | **1** |
| S4 원복 | 0 | 0 |
| G 자기승인 차단 — `reviewed_by: "claude"` 라벨 | exit 1 · DB 무변경(0) | — |

**판정**: 가설 성립. content 표면은 승격을 반영하고(0→2→0 양방향), search 표면은 승격에 반응하지
않는다. S3가 search의 `reviewed_only` 필터가 살아 있음(항상 0을 내는 위장이 아님)을 보인다 — 필터는
`atom_node`를 읽는다. 대상 두 code는 어느 단계에서도 search 히트에 나타나지 않았다.

### 3.4 부수 실측 — 승격은 코퍼스 커밋까지가 한 동작이다

`ConceptContentStore.upsert`는 코퍼스 레코드의 `review_status`를 그대로 쓴다. 그래서 DB만 승격하면
다음 적재가 되돌린다. 대조군까지 넣어 확인했다:

| 단계 | `N1.review_status` |
|---|---|
| 기준선 | `ai_estimated` |
| DB만 승격(`mark_review_status`) | `reviewed` |
| 저장소 코퍼스로 재적재 | **`ai_estimated`** (되돌아감) |
| 대조: 승격을 반영한 코퍼스 사본으로 재적재 | `reviewed` (유지) |

승격 CLI는 코퍼스 JSON과 DB를 함께 바꾸므로, KG-02 회차는 **코퍼스 변경을 PR로 커밋하는 것**까지
해야 승격이 남는다.

---

## 4. 실측 ② — 학생 공급 경로가 검수 상태를 보는가 (주입)

학생 대면 `POST /v1/me/objectives/{objective_id}/study`는 `l4/content_supply.supply()`를 부르고,
그 안의 `get_concept_dsl`이 `session.get(ConceptContent, code)`로 행을 읽는다.

| 입력 | `get_concept_dsl` 결과 |
|---|---|
| `N1` — `ai_estimated` | DSL 있음 |
| `N1` — `reviewed`로 바꾼 뒤 | DSL 있음 |
| 없는 code | `None` (대조 — 검사가 항상 non-None을 내지 않음) |

**판정**: 공급 경로는 `review_status`를 보지 않는다. `knowledge_module_gap_review.md` 표의 "자동 정의
생성: 무검증 학생 노출 금지 — `review_status=ai_estimated` + 검수 게이팅 필수(의도적 제약 §2-③)"와
어긋날 수 있는 지점이다. `review_gate.py`·`concept_content_review_apply.py` docstring은 "reviewed가
학생 노출 게이팅 기준이며 `l1/concept_graph/retrieval.py`·`l1/atom_graph/retrieval.py`가 이 값으로
히트를 거른다"고 적는데, 두 retrieval은 `concept_content`가 아니라 `concept_node`·`atom_node`를 읽는다.

**재지 않은 것**: 실제 학생 요청이 콘텐츠 행에 닿는지(목표의 `concept_nodes[0]` code와 콘텐츠 code의
매칭)는 이 세션이 재지 않았다. §3.2의 코드 공간 사실상 K-12 콘텐츠는 원자 code와 겹치지 않으므로
도달이 0일 수도 있다. 그 측정이 `CONT-05` ①이다.

---

## 5. LLM 배치 통과 가능성 (계산 · main에서 dry-run/fake-llm 실행)

- main에서 `--dry-run`·`--fake-llm` 두 모드 모두 **56건 평가**(표본 52 + 주입 결함 2 + 대조군 2) ·
  exit 0으로 CLI 실재·동작을 확인했다. 표본 수는 `min_n_for_zero_defects(0.05, 0.95) = 52`다.
- Wilson 95% 단측 상한(저장소 `harness/wilson.py`로 계산): 0/52 = **4.95%**(통과) · 1/52 = **8.17%**
  (불합격) · 33/52 = 73.53%(1회차 리허설과 일치).
- `_parse_llm_response`는 JSON 파싱 실패를 결함으로 기록한다. OPS-48이 `qwen3:30b-a3b`에서 잰 파싱
  실패율 16%가 이 프롬프트에서도 비슷하다면 56콜 무실패 확률은 0.84^56 ≈ 0.000057이다(5%면 0.057,
  1%면 0.57). **이 프롬프트의 실제 파싱 실패율은 재지 않았다** — 추정이다.
- 같은 모델이 S4-16 2차에서 무결함 33/33을 결함으로 찍었다(프로토콜은 다르다).

**결론**: 배치는 승격 권한이 없고, 이 모델로 게이트 통과는 기대하기 어렵다. 선별 보조로서의 가치
(어느 행이 의심스러운가)는 남는다.

---

## 6. 판정 3택과 Kiki 판정

| 안 | 내용 | Kiki 시간·머신 | 승격 |
|---|---|---|---|
| **① 보류 + 대장 정정 (채택)** | 틀린 전제를 대장에서 고치고, 공급 경로 검수 게이트 판정 태스크(`CONT-05`)를 이 게이트의 입력으로 건다 | 0 | 0 |
| ② LLM 재측정 | main 워크트리 런북으로 배치 재실행 — KG-08 ③(과민 vs 불량) 판정용 | 56콜 · 약 5~15분 · 0원 | 0 |
| ③ 사람 표본 검수 | K-12 표본을 검수지로 만들어 Kiki가 건별 승인·반려 → 승인분만 서명 승격 | 52건 기준 약 1~2시간 | 승인 건수 |

①을 권한 이유: 지금 승격이 바꾸는 것은 내부 표면(`/v1/concepts/content`)의 표기뿐이고, LLM 재측정은
승격을 낳지 않는다. 학생 안전과 실제로 닿는 질문은 공급 경로(§4)에 있다. 공급이 `reviewed`만 통과시키게
되면(CONT-05 ⓐ) 그때 승격이 학생 공급을 여는 유일한 문이 되므로, 사람 검수 회차는 그 뒤에 여는 것이
순서다.

---

## 7. 이 판정이 바꾼 대장

| 대상 | 변경 |
|---|---|
| `CONT-05-concept-content-supply-review-gate` | **신규**(priority 2 · EOS P1) — 도달 실측 → 택1 판정(기본값 ⓐ fail-closed) → 공급 경로·캐시 적중 경로 집행 → 변별력 → docstring 정정 → 게이트 연동 |
| `G-kg02-review-promotion-llm-session` | `gates amend` — 제목 정정(위 사실 3건 + 재판정 3택), 입력 작업 `CONT-05` 부착(입력 없음 사유 자동 해제), 독촉 14 → 35일 |
| `KG-02-concept-content-review-promotion` | `amend` — acceptance ⑦(관측 표면 정정 · 코퍼스 커밋 필요 · 학생 영향은 CONT-05 판정에 달림) + notes 정정 기록 |
| `MEMORY.md` | 결정 로그 2026-09-25 항 |

---

## 부록 — 재현

환경 준비는 §3.1과 같다(`WHYMATH_DATABASE_URL` 기본값 `postgresql+asyncpg://whymath@127.0.0.1:5432/whymath`,
`alembic upgrade head`). 아래 세 스크립트는 **저장소 루트에서** backend venv의 python으로 실행한다.
코퍼스 사본·라벨은 임시 폴더에만 쓰고 끝에 원복하므로 저장소 파일과 DB 상태를 남기지 않는다.
각 스크립트는 가설이 성립하면 exit 0, 아니면 exit 1이다.

<details>
<summary>A. 관측 표면 주입 (§3.3)</summary>

```python
"""관측 표면 불일치 실측 — concept_content 승격이 어느 API 표면에 반영되는가."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["WHYMATH_VECTOR_STORE"] = "pgvector"
os.environ["WHYMATH_DB_DISABLE_POOL"] = "1"

REPO = Path.cwd()
SCRATCH = Path(tempfile.mkdtemp(prefix="kg02_surface_"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from whymath_backend.api.concepts import get_embedding_provider  # noqa: E402
from whymath_backend.app import create_app  # noqa: E402
from whymath_backend.config import Settings, get_settings  # noqa: E402
from whymath_backend.db.models.concept_content import (  # noqa: E402
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.harness import concept_content_review_apply as apply_cli  # noqa: E402
from whymath_backend.l1.atom_graph.atom_node_projection import (  # noqa: E402
    load_atom_nodes_from_graph_json,
    populate_atom_nodes,
)
from whymath_backend.l1.atom_graph.embedding import (  # noqa: E402
    load_atoms_from_graph_json,
    populate_atom_embeddings,
)
from whymath_backend.l1.concept_content.projection import (  # noqa: E402
    load_concept_content_from_json,
    populate_concept_content,
)
from whymath_backend.l4.misconception.semantic.provider import (  # noqa: E402
    FakeEmbeddingProvider,
)

get_settings.cache_clear()
settings = Settings()
engine = create_engine(settings.sync_database_url, poolclass=NullPool)
K12 = REPO / "data/corpus/concept_content_v1/content.json"
UNIV = REPO / "data/corpus/concept_content_university_v1/content.json"
GRAPH = REPO / "data/corpus/atom_graph_v1/graph.json"
TARGETS = ["N1", "AALG1-U1-S1"]


def sql(q: str, **kw: object) -> list[tuple]:
    with engine.begin() as conn:
        result = conn.execute(text(q), kw)
        return list(result.fetchall()) if result.returns_rows else []


records = load_concept_content_from_json(K12, scope=CONTENT_SCOPE_K12) + load_concept_content_from_json(
    UNIV, scope=CONTENT_SCOPE_UNIVERSITY
)
populate_concept_content(records, settings=settings)
populate_atom_nodes(load_atom_nodes_from_graph_json(GRAPH), settings=settings)
provider = FakeEmbeddingProvider(dim=settings.embedding_dim)
atoms = load_atoms_from_graph_json(GRAPH)
populate_atom_embeddings(atoms, provider, settings=settings)
print("FACTS", sql("SELECT count(*) FROM concept_content c JOIN atom_embedding e ON e.code = c.code"))

app = create_app()
app.dependency_overrides[get_embedding_provider] = lambda: provider
client = TestClient(app)
name_by_code = {r.code: r.name for r in records}
control_atom = atoms[0]
QUERIES = [name_by_code["N1"], name_by_code["AALG1-U1-S1"], control_atom.text]


def content_reviewed_count() -> int:
    resp = client.get("/v1/concepts/content", params={"reviewed_only": "true", "limit": 200})
    assert resp.status_code == 200, resp.text
    return len(resp.json())


def search_reviewed_hits() -> int:
    total = 0
    for q in QUERIES:
        resp = client.get("/v1/concepts/search", params={"q": q, "k": 20, "reviewed_only": "true"})
        assert resp.status_code == 200 and resp.json()["vector_store_enabled"] is True, resp.text
        total += len(resp.json()["results"])
    return total


s0 = (content_reviewed_count(), search_reviewed_hits())
k12_copy, univ_copy = SCRATCH / "k12.json", SCRATCH / "univ.json"
shutil.copyfile(K12, k12_copy)
shutil.copyfile(UNIV, univ_copy)
labels = SCRATCH / "labels.jsonl"
labels.write_text(
    "".join(
        json.dumps({"code": c, "review_status": "reviewed", "reviewed_by": "kiki",
                    "reviewed_at": "2026-09-25T00:00:00Z"}) + "\n"
        for c in TARGETS
    ),
    encoding="utf-8",
)
apply_exit = apply_cli.main(["--labels", str(labels), "--k12", str(k12_copy), "--university", str(univ_copy)])
s2 = (content_reviewed_count(), search_reviewed_hits())
sql("UPDATE atom_node SET review_status='reviewed' WHERE code=:c", c=control_atom.code)
s3 = (content_reviewed_count(), search_reviewed_hits())
sql("UPDATE atom_node SET review_status='ai_estimated' WHERE code=:c", c=control_atom.code)
sql("UPDATE concept_content SET review_status='ai_estimated' WHERE code = ANY(:cs)", cs=TARGETS)
s4 = (content_reviewed_count(), search_reviewed_hits())
print("S0", s0, "S2", s2, "S3", s3, "S4", s4, "APPLY_EXIT", apply_exit)
holds = s0 == (0, 0) and s2 == (2, 0) and s3[1] >= 1 and s4 == (0, 0) and apply_exit == 0
engine.dispose()
sys.exit(0 if holds else 1)
```

</details>

<details>
<summary>B. 학생 공급 경로 주입 (§4)</summary>

```python
"""get_concept_dsl이 concept_content.review_status를 보는가."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ["WHYMATH_DB_DISABLE_POOL"] = "1"

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from whymath_backend.config import Settings  # noqa: E402
from whymath_backend.db.session import get_sessionmaker  # noqa: E402
from whymath_backend.l4.content_supply import get_concept_dsl  # noqa: E402


class _DictCache:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._d.get(key)

    async def set(self, key: str, value: str, ttl_s: int) -> None:  # noqa: ARG002
        self._d[key] = value


engine = create_engine(Settings().sync_database_url, poolclass=NullPool)


def set_status(code: str, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE concept_content SET review_status=:v WHERE code=:c"), {"v": value, "c": code})


async def has_dsl(code: str) -> bool:
    async with get_sessionmaker()() as session:
        return await get_concept_dsl(code, session=session, cache=_DictCache()) is not None


async def main() -> int:
    ai_estimated = await has_dsl("N1")
    set_status("N1", "reviewed")
    reviewed = await has_dsl("N1")
    set_status("N1", "ai_estimated")
    missing = await has_dsl("__NO_SUCH_CODE__")
    print("AI_ESTIMATED_DSL", ai_estimated, "REVIEWED_DSL", reviewed, "MISSING_DSL", missing)
    return 0 if (ai_estimated and reviewed and not missing) else 1


sys.exit(asyncio.run(main()))
```

</details>

<details>
<summary>C. 재적재 되돌림 + 대조 (§3.4)</summary>

```python
"""DB만 승격하면 재적재가 되돌리는가 — 승격을 반영한 코퍼스 사본이 대조군."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["WHYMATH_DB_DISABLE_POOL"] = "1"

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from whymath_backend.config import Settings  # noqa: E402
from whymath_backend.db.models.concept_content import CONTENT_SCOPE_K12  # noqa: E402
from whymath_backend.l1.concept_content.projection import (  # noqa: E402
    ConceptContentStore,
    load_concept_content_from_json,
    populate_concept_content,
)

K12 = Path.cwd() / "data/corpus/concept_content_v1/content.json"
settings = Settings()
engine = create_engine(settings.sync_database_url, poolclass=NullPool)


def status() -> str:
    with engine.begin() as conn:
        return str(conn.execute(text("SELECT review_status FROM concept_content WHERE code='N1'")).scalar_one())


def load(path: Path) -> None:
    populate_concept_content(load_concept_content_from_json(path, scope=CONTENT_SCOPE_K12), settings=settings)


load(K12)
seen = [status()]
ConceptContentStore(settings=settings).mark_review_status(("N1",), "reviewed")
seen.append(status())
load(K12)
seen.append(status())
copy = Path(tempfile.mkdtemp(prefix="kg02_repop_")) / "k12.json"
data = json.loads(K12.read_text(encoding="utf-8"))
hits = [r for r in data["content"] if r.get("code") == "N1"]
assert len(hits) == 1
hits[0]["review_status"] = "reviewed"
copy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
load(copy)
seen.append(status())
load(K12)
seen.append(status())
print("N1", seen)
engine.dispose()
sys.exit(0 if seen == ["ai_estimated", "reviewed", "ai_estimated", "reviewed", "ai_estimated"] else 1)
```

</details>
