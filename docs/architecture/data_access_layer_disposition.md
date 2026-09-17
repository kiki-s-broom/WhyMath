# 데이터 접근 계층 처분 — (b) baseline 동결 + 신규 증가 차단

> **판정 기준: main `0f12e76af4ab2a48e266d47403779b182be9da4b`** (2026-09-16 실측)
> 소유 태스크: `ARCH-48-data-access-layer-audit`
> 계측·baseline 정본: `scripts/analysis/data_access_layer_audit.py`
> 집행: `tests/infra/test_data_access_layer_contract.py` (호출 축) · `src/backend/pyproject.toml` (import 축)

---

## 0. 이 문서가 닫는 공백

`docs/reviews/eos_source_docs_gap_review_2026-08-31.md:154` 36번 행이 2026-08-31에 이렇게
적었다 — **"Repository 계층 — ORM 직접 접근이 서비스 계층에 남아 있음(부분)"**. 그 문서 §5는
B급 8건을 "Kiki 판정 대기"로 남겼고, 이 행은 그 뒤 2주간 **소유자가 없었다**. CLAUDE.md
"소유자 없는 알려진 결함을 만들지 않는다"의 미이행 구간이다.

**`ARCH-48`이 그 행의 소유자다.** 이 문서가 처분을, 위 두 집행 장치가 그 처분의 기계적
강제를 맡는다.

---

## 1. 실측 (재측정)

2026-09-15 등재 시점 수치는 정규식(`session\.(query|execute|scalars|add|commit)`) 기반이었고,
이 문서의 수치는 **AST 기반 재측정**이다. 정규식은 주석·문자열·동명이인(`set.add` 233건)을
함께 세므로 baseline의 근거가 될 수 없다.

### 1.1 검색 방법 (부재 주장은 검색 방법이 옳아야 성립한다)

| 무엇 | 방법 |
|---|---|
| Repository 계층 실재 | `find . -iname "*repositor*" -not -path "./.git/*"` → **0건** (2026-09-15와 동일). 이름 축 보강: 역할로 재검색 — `whymath_backend` 전수에 `*Repository` 클래스·`_REPO`/`REGISTRY` 류 데이터 접근 레지스트리 없음. `db/session.py`의 `get_session()` FastAPI 의존성이 유일한 공통 접근 관문이고, 그 뒤는 각 호출부가 세션을 직접 다룬다 |
| 세션·연결 직접 조작 | AST. 수신자 이름(`session`·`db`·`db_session`·`async_session`·`sess`·`conn`·`connection`, 선행 밑줄 무시 → `self._session` 포함) 위의 SQLAlchemy 세션 메서드 17종 호출 |
| 회피 후보 | `AsyncSession`/`Session`/`AsyncConnection`/`Connection`으로 **주석된 이름** 중 위 목록 밖 → **0건**. 주석의 *머리* 타입만 본다(`async_sessionmaker[AsyncSession]`은 팩토리이지 세션이 아니다) |
| 깨끗한 계층 | `sqlalchemy` import · `whymath_backend.db` import · 세션 호출 **세 축 모두 0** |

범위: `src/backend/whymath_backend/` 전수(667 파일 · import-linter 그래프 기준 662 모듈). 테스트·마이그레이션·`scripts/`는 제외한다
— 이 처분이 다루는 것은 **서빙·도메인 코드의 데이터 접근 형태**다.

### 1.2 계층별 수치와 2026-09-15 대비 델타

| 계층 | 파일(AST, 전체 메서드) | 파일(AST, 5종·`session` 수신자만) | 2026-09-15 정규식 | 델타 | 비고 |
|---|---:|---:|---:|---:|---|
| api | 14 | 12 | 12 | 0 | 42파일 중 14 (33%) |
| l1 | 36 | 7 | 6 | +1 | `conn.execute`(엔진 직접) 28파일이 정규식 사각이었다 |
| l2 | 17 | 16 | 15 | +1 | |
| l3 | 8 | 2 | 2 | 0 | |
| l4 | 6 | 4 | 4 | 0 | |
| db | 1 | 1 | 1 | 0 | 설계상 여기가 집이다 |
| harness | 11 | 11 | 11 | 0 | |
| ops | 9 | 8 | 8 | 0 | |
| privacy | 8 | 7 | (미계상) | — | 원 측정이 열거하지 않은 구역 |
| whs | 7 | 7 | (미계상) | — | 〃 |
| root | 1 | 1 | (미계상) | — | 단일 파일 모듈 |
| **합계** | **118** (호출 507건) | **76** | — | | |
| schema · lang · l5 · l6 | **0** | 0 | — | | 74파일 — 세 축 모두 0 |

**정규식 수치는 거의 정확했다** — 재측정이 뒤집은 것은 두 가지다.
① `conn`(엔진 직접 연결) 축을 통째로 놓쳤다 → l1이 6에서 36으로.
② `privacy`·`whs`·`root`가 회계에서 빠져 있었다(15파일).

원시 SQL `text("…")`: `whymath_backend` 안에서는 **27호출·7파일**(ops 25·api 1·db 1)뿐이다.
등재 시 적힌 150건은 마이그레이션·테스트·스크립트를 포함한 수치이며, 서빙 코드의 원시 SQL은
이 축의 주된 문제가 아니다 — 문제는 세션 자체의 편재다.

---

## 2. 처분: **(b)**

> 현행 세션 직접 접근을 관례로 인정하고 **baseline 동결 + 신규 증가만 차단**한다.

### 2.1 (a) Repository 계층 신설로 수렴 — 기각

**118파일·507호출**이다. 지금 (a)를 선언하면 118건이 전부 즉시 위반이 되고, 실제 이행은
여러 분기에 걸친 리팩터다. 그 간극을 메울 수단은 **만료 없는 유예**뿐인데 그것은 CLAUDE.md
절대 금기다("만료 없는 유예·제외 금지"). 즉 (a)는 지금 *선언할 수 없는* 처분이지 틀린 방향이
아니다 — 방향으로서의 (a)는 §4 후속에 남긴다.

### 2.2 (c) 계층별 차등(api 금지 · l1~l4 허용) — 기각

두 쪽이 다 성립하지 않는다.

- **"api 금지"** — api는 42파일 중 **14파일이 이미 접근한다**(`users`·`gating`·`curricula`·
  `auth`·`coach`·`study`·`problems`·`me`·`reports`·`interactions`·`concepts`·`_auth`·
  `_concept_orchestration`·`_device_store`). 리팩터 없이 금지를 선언하면 14건의 만료 없는
  유예가 생긴다 — (a)와 같은 이유로 막힌다. 리팩터는 이 태스크의 범위 밖이다(행동 변경 0).
- **"l1~l4 허용"** — l1~l4는 **67파일**로 가장 큰 구역이다. 여기를 무제한 허용하면 이 축의
  집행은 사실상 없다. 오늘 api를 막아도 내일 `l4`에 붙으면 같은 결합이 라벨만 바꿔 옮겨 간다.

즉 실측상 **(c)는 (b)로 퇴화한다** — 유예를 만들지 않으려면 api도 "현재 집합 동결"일 수밖에
없고, l1~l4도 열어 둘 수 없다. (c)의 *차등 축 자체*는 버리지 않고 baseline을 **계층별 집합**
으로 보관해, 나중에 api만 따로 조일 수 있게 남긴다(§4).

### 2.3 (b)를 고른 이유

1. **유예를 만들지 않는다** — 현행을 "빚"이 아니라 **관례**로 인정하므로 만료가 필요한 면제가
   0건이다. 막는 것은 *확산*이다.
2. **행동 변경 0** — 코드를 한 줄도 옮기지 않는다.
3. **기계적 만료가 내장된다** — baseline은 관측과 **정확히 일치**해야 한다(늘면 RED, 줄면
   ratchet RED). 어떤 리팩터든 이 표를 건드리게 되므로 표가 썩지 않는다. `CORE_PULL_BASELINE`
   (`tests/infra/test_eos_dependency_direction.py`)이 같은 형태로 이미 검증된 패턴이다.
4. **편집이 곧 선언이 된다** — 새 파일이 DB를 잡으려면 baseline에 한 줄을 추가해야 하고,
   그 줄이 리뷰에 보인다. 조용히 퍼지는 경로가 없다.

---

## 3. 집행 지점 (정본화와 **별항**)

`scripts/analysis/data_access_layer_audit.py`는 **계측기다 — 아무것도 막지 않는다.**
막는 것은 아래 둘이며, 축이 다르고 서로를 대체하지 못한다.

| 축 | 장치 | CI 스텝 | 막는 것 | 못 막는 것 |
|---|---|---|---|---|
| **호출 축** | `tests/infra/test_data_access_layer_contract.py` | `infra-contracts` 잡 `python3 -m pytest tests/infra` | baseline 밖 파일의 세션·연결 직접 조작 / baseline 썩음 / 수신자 개명 회피 / 재확인 기한 만료 | 동적 호출(`getattr(session, "execute")`) |
| **import 축** | `src/backend/pyproject.toml` forbidden 계약 "데이터 접근 금지 (baseline 0 — 아직 DB를 모르는 구역)" | `backend` 잡 `lint-imports` | `schema`·`lang`·`l5`·`l6`이 `sqlalchemy`·`whymath_backend.db`를 import하는 것 | 메서드 호출(문법이 없다) · 경유 의존 |

### 3.1 왜 import-linter만으로 안 되는가

기존 계약 2축(7계층 단방향 · EOS Core→Adapter 금지)은 **데이터 접근 축을 보지 않는다**
(`[tool.importlinter]` 전수 확인 — 계약 3건 중 해당 0건). 그리고 새로 추가한 계약도 한계가
분명하다: import-linter는 import 그래프 도구라 `session.execute(...)`라는 **메서드 호출**을
표현할 문법이 없다. 그래서 이미 잡고 있는 118파일은 import 축으로 셀 수 없고, AST 가드가
맡는다. 반대로 AST 가드는 "아직 한 줄도 안 쓴 계층이 sqlalchemy를 끌어오는" 순간을 import
시점에 못 막는다. **둘 다 둔다.**

### 3.2 새 import 계약은 유예가 0이다

`schema`(45파일) · `lang`(2) · `l5`(10) · `l6`(17) — 74파일이 세 축 모두 0이다. 깨끗한 구역은
baseline이 아니라 **금지**로 동결한다(EOS-67의 "baseline 0 — 이미 깨끗한 구역" 계약과 같은
형태). `include_external_packages = true`가 이 계약의 전제이며, 도입 전후로 기존 3계약의 판정은
바뀌지 않는다(실측 2026-09-16: 3 kept → 4 kept, 0 broken).

---

## 4. 재확인 (만료 없는 유예 금지)

만료가 **두 겹**이다.

1. **기계** (주) — baseline 정확한 일치. 유예가 조용히 영구화될 통로가 없다.
2. **날짜** (부) — `BASELINE_REVIEW_BY = 2027-01-31`. 기계적 ratchet은 "118이 여전히 118"인
   상태를 영원히 green으로 둔다 — 처분 *자체*가 여전히 옳은지는 묻지 않는다. 기한이 지나면
   가드가 RED를 내고 사람은 셋 중 하나를 해야 한다:
   - ① 처분을 (a)/(c)로 승격하고 이행 태스크를 등재한다
   - ② 재확인했고 (b)가 여전히 옳다고 판단해 기한을 옮긴다 (**그 커밋이 재확인의 증적이다**)
   - ③ baseline을 줄이는 작업에 착수한다

   날짜 근거: EOS 12월 검증(계획서 100 §3.5) 직후. 그 검증이 데이터 접근 형태를 실사용으로
   시험하므로 재확인에 필요한 실측이 그때 모인다.

이 저장소의 관용은 "만료가 날짜가 아니라 기계"다(`scripts/harness/models.py`
`EOS_PRIORITY_BACKFILL_GATE` 선례 — 해소 태스크·게이트가 종결되면 면제가 만료된다). 여기서
날짜를 함께 쓰는 이유는 **아직 이행 태스크가 등재되지 않았기 때문**이다. 승격 태스크가 생기면
그 id에 만료를 다시 묶고 날짜를 걷어내는 것이 더 낫다(§5).

---

## 5. 범위 밖 (이 태스크가 하지 않은 것)

- **Repository 계층 구현** — (a)로 승격할 때의 이행. 118파일·507호출 규모라 별건이다.
- **api 14파일의 접근 제거** — (c)의 "api 금지"를 실제로 성립시키려면 선행돼야 한다.
- **`harness`·`ops`·`whs`·`privacy`(35파일)의 위치 판정** — 이들이 서빙 코드인지 도구인지에
  따라 처분이 갈릴 수 있다. 지금은 동일하게 동결만 한다.
- **동적 접근**(`getattr(session, ...)`) — 실측 0건이라 가드가 보지 않는다. 생기면 보이지 않는
  구멍이 된다.
- **원시 SQL 27호출** — ORM 우회 축(CLAUDE.md "원시 SQL 최소화")은 이 처분이 세기만 하고
  집행하지 않는다.

---

## 6. 갱신 규칙

- baseline을 늘리려면 `data_access_layer_audit.py`의 `BASELINE`을 고친다. **그 편집이 선언이다.**
- `CLEAN_LAYERS`를 고치면 `pyproject.toml` 계약도 함께 고쳐야 한다(가드가 정확한 일치를 잰다).
- 이 문서의 수치를 갱신할 때는 **상단의 판정 기준 커밋 해시도 함께 바꾼다** — 해시 없는 판정은
  재현 불가이고, 재현 불가한 판정은 며칠 뒤 조용히 거짓이 된다.
