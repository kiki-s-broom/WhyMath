# ARCH-32 — Source 엔티티 분리·이관 계획

> **판정 기준**: 작업 브랜치 `claude/happy-turing-ustq5u` (main `a05eb49a` 위). 근거 코드는 전부 이 트리에서 실측.
> **결정 출처**: `docs/standards/eos_identity_layer_011_1_decision.md` 8번 — "`source_type`/`source_detail` → 별도 `source` 테이블로 점진 이관".

## 1. 핵심 결론 — 새 테이블을 만들지 않는다

인수 조건은 "Source Pydantic 모델 및 ORM 설계"를 요구하지만, **그 좌석은 LIC-01(2026-08-23, 리비전 `a1b2c3d4e5f6`)이 이미 만들었다.**

| 요구 필드 | 이미 있는 좌석 | 비고 |
|---|---|---|
| `source_id` | `source_entity.source_id` (UUID PK) | `schema/rights.py::SourceEntity` · `db/models/rights.py::SourceEntity` |
| `source_type` | `source_entity.source_type` (String 64) | 자유 문자열(`public_institution`/`dataset`/…). `Problem.source_type`(8값 enum)과 **어휘가 다르다** → §3 |
| `uri` | `source_entity.original_url` + `archive_uri` | 원본 URL과 스냅샷 URI를 분리해 둔 쪽이 더 정밀 |
| `publisher` | `source_entity.publisher` | |
| `retrieved_at` | `source_entity.retrieved_at` | |
| `license` | **`source_entity`에 없다 — 의도적** | 라이선스는 `rights_entity`(+`content_rights` N:M)가 권리 primitive로 정규화. 출처에 문자열로 넣으면 같은 사실의 두 좌석 |

새 `source` 테이블을 또 만들면 `source_entity`와 같은 사실의 두 번째 좌석이 되고, 저작권 레일(`l1/rights/*`)이 어느 쪽을 정본으로 읽을지 갈린다. 그래서 **모델 설계는 신설이 아니라 대응표(위)로 갈음**한다. 이 결정은 인수 조건 ①의 문면(신규 설계)과 다르므로 `backlog` notes에 사유를 남긴다.

## 2. 이번 리비전이 더하는 것 — `problem.source_id`

리비전 `b4d8e2a6c0f3`(`alembic/versions/20261002_1200_b4d8e2a6c0f3_problem_source_id.py`):

- `problem.source_id` UUID **nullable**, FK → `source_entity.source_id`, 인덱스 `idx_problem_source_id`.
- `schema.Problem.source_id: uuid.UUID | None = None`, `db.models.problem.Problem.source_id` 동반.
- **NULL = 미이관. 기존 행을 채우지 않는다**(백필 금지). 기존 행에 출처 엔티티를 날조해 넣으면 등록된 적 없는 출처를 만드는 것이다(DP-03 `event_uuid`와 같은 규약).
- downgrade는 인덱스·FK·컬럼을 대칭 제거한다.

## 3. `source_type` / `source_detail`을 지금 지우지 않는 이유

1. **저작권 불변식의 근거다.** `schema/problem.py::_METADATA_ONLY_SOURCES`(평가원·EBS·교과서)와 `Problem` after-validator가 `source_type`으로 "본문 보유 불법 출처"를 막는다. 이 값을 지우면 법적 방어선이 사라진다.
2. **소비처가 넓다.** `l1/problem_bank/populate.py`·`provenance_gate.py`·`l6/*/gating.py`·`ops/provenance_audit.py` 등이 읽는다.
3. **어휘가 달라 1:1 치환이 안 된다.** `Problem.source_type`은 `{평가원, EBS, AIHub, 교육청학평, 사설모의고사, 자체생성, 사용자자작, 교과서}`, `source_entity.source_type`은 자유 문자열이다. 매핑표 없이 옮기면 의미가 샌다.

그래서 이관은 **병행 기간**을 둔다: 신규 쓰기는 `source_id`를 채우되 `source_type`도 계속 쓴다.

## 4. 이관 단계 (이 PR은 ①만 착지)

| 단계 | 내용 | 상태 |
|---|---|---|
| ① 좌석 | `problem.source_id` nullable FK (본 리비전) | **이 PR** |
| ② 어휘 매핑 | `Problem.source_type` 8값 → `source_entity` (유형·`source_authority`) 대응표 확정. 법률 검토가 걸린 값(평가원·EBS·교과서)은 변호사 검토 전제 | 미착수 — 후속 태스크 |
| ③ 백필 | distinct `(source_type, source_detail.publisher/year/edition)` 단위로 `source_entity` 행을 만들고 `problem.source_id` 채움. 드라이런 기본·멱등·`content_source` 연동 | 미착수 — 후속 태스크 |
| ④ 이중 쓰기 검증 | `source_id`와 `source_type`이 모순되는 행 0건을 감사 | 미착수 |
| ⑤ 축소 판정 | `source_detail`의 구조 메타가 `source_entity.extra`·`content_source.original_reference`로 완전히 옮겨졌는지 확인 뒤에만 컬럼 제거 여부를 결정(`source_type`은 불변식 근거라 제거 대상이 아닐 가능성이 높다) | 게이트 필요 |

**`content_source`(N:M)와의 역할 분담(결정 필요)**: `problem.source_id`는 "주 출처" 1건, `content_source`는 `secondary`/`inspiration` 및 `original_reference`(문항번호 등)를 담는다. 다만 `content_source.role`의 기본값이 `primary`라 두 좌석이 같은 주 출처를 가리킬 수 있다. 이 분담을 확정하는 것은 ③ 착수 전 Kiki 판단 사항이다 — 이 PR은 FK만 더하고 N:M 쪽 의미는 바꾸지 않는다.

## 5. 기존 `_provenance.json` 사이드카와의 관계

세 가지가 **서로 다른 층위**이며 대체 관계가 아니다.

| 층위 | 단위 | 위치 | 역할 |
|---|---|---|---|
| 코퍼스 사이드카 | **코퍼스(파일 묶음) 1개** | `data/corpus/*/_provenance.json` (`schema/corpus_provenance.py::CorpusProvenanceSidecar`) | "이 코퍼스가 어디서 왔고 어떤 풀(pool)인가". `pool` + 서지 1건만 강제, 나머지 자유형(ARCH-20). 소비처 = `ops/provenance_audit.py` |
| `source_entity` | **원본 출처 1건** | DB `source_entity` (LIC-01) | 출처의 정규화 엔티티(URL·취득일·해시·신뢰도). 콘텐츠와는 FK/N:M으로 연결 |
| `problem.source_id` | **문항 1건 → 출처 1건** | DB `problem.source_id` (본 리비전) | 문항이 어느 출처 엔티티에서 왔는지의 포인터 |

- 사이드카는 **파이프라인 산출물의 감사 메타**(파일 시스템), `source_entity`는 **런타임 정본**(DB)이다. 사이드카를 `source_entity`로 대체하지 않는다 — 사이드카는 검수 이력 서술(`reviewer`/`reviewed_on` 등)을 자유형으로 보존해야 하고, 그것을 단일 스키마에 맞추면 감사 이력이 훼손된다(`corpus_provenance.py` docstring).
- **연결 방향**: ③ 백필이 사이드카의 `source_citation`을 `source_entity.title/extra`의 입력으로 *참조*할 수는 있으나, 사이드카가 `source_entity`를 *가리키지는* 않는다(코퍼스는 문항보다 거친 단위라 1:1이 아니다).
- `ops/provenance_audit.py`는 이 PR에서 **수정하지 않는다**(태스크 `paths`에 포함돼 있었으나 사이드카 계약이 불변이므로 변경 사유가 없다).

## 6. 검증

- `tests/backend/db/test_problem_source_id_arch32.py` — ORM 컬럼·FK·인덱스, schema 왕복, 마이그레이션 파일 대칭성·체인 연결.
- 실 PG 왕복(`alembic downgrade -1 → upgrade head`)은 CI `backend — 마이그레이션·통합 (실 PG)` 잡이 전구간으로 수행한다. 이 세션 환경은 PG 미도달이라 로컬 실행하지 못했다.
