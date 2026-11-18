# ruff select에 BLE·S를 넣을 것인가 — 조용한 실패 규칙 도입 판정

> **판정 기준**: `origin/main` `ad35b096` · 2026-11-18 · Windows 11
> **측정 트리**: 로컬 HEAD `3374bf18` — `ad35b096`과의 차이는 `src/backend/pyproject.toml`(계약 1개)·`tests/infra` 1파일뿐이고 `src/backend/whymath_backend` 변경은 0줄이다(GOLD-27).
> **도구**: ruff **0.15.22**(CI 고정 `infra/ci/constraints-py312.txt`) · 로컬 venv 0.15.20과 **건수 동일**을 확인했다.
> **성격**: 결정 문서. **린트 설정을 바꾸지 않았다** — `pyproject.toml` 변경 0줄. 집행은 Kiki 승인 뒤 별도 태스크.
> 출처: 태스크 `GOLD-26` · `golden/RESCUE_REVIEW.md` §6 F-4 · RS G2 지시문 `golden/prompts_rescue/단계02_병렬_3개_백엔드대장-잠금/RS-단계02-G2-잠금-조용한실패게이트.md`.

---

## 0. 한 줄 결론

**지금은 전역 `select`를 바꾸지 않는다(다안).** 골든 구역의 조용한 실패는 **G2 게이트가 소유**하고, 옛 구역은 **건수 기록만** 한다.

이유는 셋이다.
1. **전역 도입은 골든 기간의 "옛 코드 읽기 전용"과 정면 충돌한다** — 켜는 순간 옛 코드에 260건(아래 §3)이 red가 되고, 초록으로 만들려면 옛 코드를 260줄 고치거나 `noqa`를 붙여야 한다. 둘 다 지금 규칙 밖이다.
2. **골든만 켜는 안은 G2와 같은 일을 두 번 한다** — G2 지시문이 이미 "골든 구역 0건 강제 + 허용 목록 + 주입 2종"으로 설계돼 있다.
3. **BLE·S는 "예외 타입명" 축을 대체하지 못한다**(§5). 40건 가운데 31건은 이미 타입명을 남기고 있고, 진짜 무음은 7곳(9건)뿐이며, 그중 3곳은 `return None/False`라 S110·S112가 **아예 보지 못한다**.

---

## 1. 착수 시점 실측

### 1-1. 현행 설정

| 항목 | 값 | 위치 |
|---|---|---|
| `select` | `["E", "F", "I", "N", "B", "W"]` | `src/backend/pyproject.toml:194` |
| `ignore` | `[]` | 같은 절 |
| 루트 설정 | **동일해야 한다**는 거버넌스 주석이 있다 | 주석 `pyproject.toml:54-55` · `select` 줄은 `pyproject.toml:56`·`src/data-pipeline/pyproject.toml:81` |
| `E722`(맨 `except:`) | `E`에 포함 — **0건** | — |
| `BLE001`·`S110`·`S112` | **미선택** | — |

### 1-2. 건수 (백엔드 소스 `src/backend/whymath_backend`)

| 규칙 | 건수 | 비고 |
|---|---:|---|
| `BLE001` blind-except | **37** | 넓은 `except Exception`을 잡는다 |
| `S110` try-except-pass | **3** | 본문이 `pass`인 것만 |
| `S112` try-except-continue | **3** | 본문이 `continue`인 것만 |
| `E722` bare-except | **0** | 이미 검사 중 |
| 합계(3규칙) | **43** | 40(G2 축) + S112 3 |

`40`은 **일일 검출 건수이지 상한이 아니다** — 새 코드가 들어오면 늘어난다. 이 문서의 모든 수는 `ad35b096` 시점의 스냅숏이다.

### 1-3. 골든 구역 (G2 지시문의 명령 그대로)

`python -m ruff check golden ../../tests/golden --select BLE001,S110,E722` → **0건, exit 0**.
`S112`를 더해도 **0건**이다. 즉 골든 구역은 현재 깨끗하고, 게이트는 **순수 예방**이다.

### 1-4. 저장소 전역 (CI 잡의 대상 경로 그대로 · `BLE001,S110,S112`)

| 잡(대상 경로) | 건수 | 비고 |
|---|---:|---|
| backend (`. ../../tests/backend ../../tests/constitution`) | 176 | 소스 43 · 테스트 133 |
| data-pipeline (`. ../../tests/data_pipeline`) | 9 | 소스 0 · 테스트 9 |
| harness (`scripts tests/harness tools`) | 75 | `scripts` 74 · `tests/harness` 1 · `tools` 0 |
| infra (`tests/infra infra conftest.py …`) | 0 | — |
| golden-path (`golden ../../tests/golden`) | 0 | — |
| **합계** | **260** | 소스 43 · 테스트 142 · 스크립트 74 · 도구 1 |

**`S`를 통째로 켜는 안은 사실상 불가능하다.** `S`(flake8-bandit 전체)는 backend 잡 **46,969건**, harness 잡 5,086건, data 잡 2,006건 — 합계 **약 54,061건**이고 그 **98.6%** 가 **`S101`(assert)** 이다(backend 46,591 · harness 4,719 · data 1,999 = **53,309건**). 테스트의 `assert`를 전부 예외 처리해야 하므로 선택지가 아니다. 그래서 이 문서에서 "S"는 **`S110`+`S112`(조용한 실패 축)만** 뜻한다.

### 1-5. 기존 억제 표시

`whymath_backend`에 `# noqa: BLE001`이 **343줄** 있다(D2 보고와 일치). 즉 이 저장소는 이미 "넓게 잡되 이유를 적고 면제"하는 관행을 쓰고 있다. 전역 도입은 이 343개를 *살아 있는* 면제로 만들고, 아래 §2의 5곳처럼 **면제 표시가 다른 줄에 있어 여전히 red가 되는** 곳을 드러낸다.

---

## 2. 40건 줄별 분류 — 무엇을 삼키는가

분류 기준은 하나다. **예외가 발생했을 때 그 사실(특히 타입명)이 어디로 가는가.**
"로그"는 `logger.warning/error/debug` 호출이 있는 경우, "구조"는 로그가 아니라 반환값·payload·리포트에 타입명이 들어가는 경우다.

### A. 로그에 예외 타입명을 남긴다 — 19건

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 3 | `api/coach.py:2823` | served_hint 조회 실패 → 힌트 없이 진행 | warning + 타입명 |
| 7 | `harness/hint_verdict_gui.py:635` | 오류 창 표시 실패 | error + 타입명 |
| 8 | `harness/hint_verdict_gui.py:639` | 판정 창 닫기 실패 | error + 타입명 |
| 9 | `harness/hint_verdict_gui.py:867` | 예약 작업 취소 실패 | warning + 타입명 |
| 10 | `harness/hint_verdict_gui.py:904` | 판정 기록 중 예상 못한 오류 → 세션 멈춤 | error + 화면 |
| 11 | `harness/hint_verdict_gui.py:1065` | 창 정리(destroy) 실패 | warning + 타입명 |
| 12 | `harness/hint_verdict_gui.py:1162` | 창 생성·루프 오류 → exit 2 | error + `GUI_ERROR=` |
| 15 | `harness/review_session_gui.py:812` | 검수 제출 중 예상 못한 예외 → 멈춤 | error + traceback + 화면 |
| 16 | `harness/review_session_gui.py:1008` | 창 앞으로 올리기 실패 | warning + 타입명 |
| 17 | `harness/review_session_gui.py:1050` | started 기록 실패 → 판정 중단 | error + 화면 |
| 18 | `harness/review_session_gui.py:1194` | 예약 작업 취소 실패 | warning + 타입명 |
| 19 | `harness/review_session_gui.py:1226` | 창 닫기 중 기록 실패 → 창 유지 | warning + 화면 |
| 23 | `l3/isolated_call.py:262` | 호출 대상 pickle 불가 → 스레드 폴백 | warning + 폴백 계수 |
| 24 | `l3/isolated_call.py:353` | 워커 kill 실패 | warning + 타입명 |
| 29 | `l3/isolated_call.py:375` | 교체 워커 선기동 실패 | warning + 타입명 |
| 30 | `l3/trace/langfuse_sink.py:300` | flush 실패 → 비차단 계속 | warning + 타입명 |
| 32 | `l4/content_supply.py:600` | 전략 카드 조회 실패 → 카드 없이 생성 | warning + 타입명 |
| 34 | `l4/pedagogy/runtime_selector.py:398` | 카탈로그 적재 실패 → 규칙표 원판정 | warning + reason_code |
| 35 | `ops/cost_report.py:647` | Langfuse 조회 실패 → 모은 것만 집계 | warning + 타입명 |

### B. 로그지만 타입명 없이 traceback만 — 2건

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 2 | `api/coach.py:1175` | 의미 매처 실패 → substring 폴백 | warning + `exc_info=True` |
| 4 | `app.py:978` | 웜업 실패 → 첫 요청 때 lazy 재시도 | warning + `exc_info=True` |

`exc_info=True`는 traceback에 타입명을 포함하므로 **타입명 축은 충족**한다. 다만 로그 한 줄만 보면 타입명이 안 보인다.

### C. 로그(debug)에 타입명 — 2건

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 31 | `l3/verify_answer.py:434` | condition 파싱 불가 → 보수적 `unverifiable` | debug + 타입명 |
| 33 | `l4/misconception/derivative_signature.py:734` | 변환 계산 불가 → 그 규칙 건너뜀 | debug + 타입명 |

운영 로그 레벨이 INFO면 **보이지 않는다**. "타입명을 남긴다"를 형식적으로 충족하지만 실효는 낮다.

### D. 로그가 아니라 구조로 타입명을 남긴다 — 6건

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 5 | `harness/ai_quality_eval.py:223` | 판정기 예외 → 측정 실패로 계수 | `FailureCase`에 타입명 |
| 14 | `harness/residue_cross_verify_eval_v2.py:364` | 도메인 verifier 예외 → unverifiable | 목록에 타입명 |
| 22 | `l3/isolated_call.py:167` | 결과/예외 pickle 불가 | `("werr", 타입명, 대상)` 전송 |
| 37 | `ops/phase1_structure_report.py:234` | 의존 감사 모듈 적재 실패 | `Metric(measured=False, 타입명)` |
| 38 | `ops/phase1_structure_report.py:245` | 감사 실행 실패 | `Metric(measured=False, 타입명)` |
| 39 | `ops/phase1_structure_report.py:282` | DB 도달 실패 | `Metric(measured=False, 타입명)` |

### E. 삼키지 않는다 — 재전파·즉시 실패 — 2건

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 1 | `api/_device_store.py:1234` | 재시도 루프 | 마지막 예외를 `raise last_exc`로 재전파 |
| 13 | `harness/learning_metrics_rollup_cli.py:157` | 잘못된 타임존 | `parser.error(…타입명)`로 즉시 종료 |

### F. 아무것도 남기지 않는다 — 9건 / 물리 지점 7곳 ★

| # | 경로:줄 | 무엇을 삼키는가 | 처리 |
|---:|---|---|---|
| 6 | `harness/attempt_grading_shadow_report.py:186` | 코퍼스 파일 읽기 실패 → 그 은행 건너뜀 | `continue` |
| 20 | `l3/dsl/compiler.py:144` | DSL 컴파일 실패 | `return None` |
| 21 | `l3/dsl/variable_engine.py:161` | bool 평가 실패 | `return False` |
| 25·26 | `l3/isolated_call.py:357` (S110·BLE001) | `conn.close()` 실패 | `pass` |
| 27·28 | `l3/isolated_call.py:361` (S110·BLE001) | `process.join()` 실패 | `pass` |
| 36 | `ops/dialogue_encryption_preflight.py:47` (S110) | `stdout.reconfigure()` 실패 | `pass` |
| 40 | `ops/phase1_structure_report.py:350` | `Settings()` 실패 | `database_url = None` |

**여기에 S112 2곳이 더 있다**(40건 밖): `l3/equivalent/authoring_guard.py:474` · `l3/equivalent/structural_dedup.py:183` — 둘 다 "후보 조합을 못 읽으면 다음 후보로"이며, 같은 줄 `# noqa: BLE001`이 **BLE001만** 면제하고 S112는 면제하지 않는다. 그래서 S112를 켜면 새로 red가 된다.

**분류 합계**: 19 + 2 + 2 + 6 + 2 + 9 = **40**.
**무음은 9건(7곳)** 이며, 그중 3곳(`compiler.py:144`·`variable_engine.py:161`·`phase1:350`)은 `pass`도 `continue`도 아니라 **S110·S112가 보지 못한다.**

### F-1. `noqa`가 다른 줄에 있는 5곳 (전역 도입 시 형식만 고치면 되는 것)

`residue_cross_verify_eval_v2.py:364` · `langfuse_sink.py:300` · `verify_answer.py:434` · `derivative_signature.py:734` · `cost_report.py:647` — 모두 여러 줄 `except (` 형태라 `Exception`과 `# noqa: BLE001`이 서로 다른 줄에 있다. ruff는 위반을 `Exception` 줄에 붙이므로 **면제가 적용되지 않는다**. 전역 도입을 결정하면 이 5곳은 코드 변경이 아니라 **주석 위치 이동**으로 해소된다.

---

## 3. 세 안 비교

| 축 | 가. 저장소 전체 | 나. 골든 구역만 | 다. 켜지 않는다 |
|---|---|---|---|
| **실측 위반** | 260건 (`BLE001+S110+S112`) · S 전체는 54,061건 | **0건** | 0건 |
| **고칠 양** | 260곳 — 소스 43 · 테스트 142 · 스크립트 74 · 도구 1. **옛 코드가 읽기 전용인 골든 기간에는 고칠 수 없다** | 0 | 0 |
| **억제 비용** | 기존 `noqa: BLE001` 343줄이 살아남. 미배치 5곳은 여전히 red. 260곳마다 "고침/면제+사유" 판단 필요 | 0 (허용 목록 불필요) | 0 |
| **설정 변경 범위** | 3개 `pyproject.toml`(루트·backend·data-pipeline) — "규칙은 위치와 무관하게 같아야 한다" 거버넌스 주석과 함께 | `pyproject.toml` 변경 0. `check.py`의 ruff 스텝 + CI golden-path 스텝(2곳) | 없음 |
| **지금 끄면 무엇이 계속 새는가** | — | 골든 밖 새 코드는 무방비. 골든 안은 G2가 막는다 | 옛 구역 무음 7곳이 그대로. 새 코드도 golden 밖에서는 무방비 |
| **G2와의 관계** | G2의 허용 목록·기준선을 무의미하게 만든다(전역이 이미 red) | **G2와 같은 일 2벌** | G2가 골든을, D2가 옛 구역 건수를 소유 |
| **판정** | **불가**(골든 기간 규칙 충돌) | **중복**(G2 소유) | **권고** |

**가안의 결정적 문제**: 위반 260건을 초록으로 만들려면 옛 코드를 고쳐야 한다. 골든 규칙("golden/ 바깥은 읽기 전용")을 지키면서 초록을 만들려면 `noqa`를 260줄 추가해야 하는데, 그것도 옛 코드 편집이다. 즉 **"설정만 바꾸는 결정"처럼 보이지만 실제로는 옛 코드 260줄 편집을 강제하는 결정**이다.

---

## 4. 권고

**다안 + G2 위임.** 구체적으로:

1. `src/backend/pyproject.toml`·루트·data-pipeline의 `select`를 **바꾸지 않는다**.
2. 골든 구역의 강제는 **G2 게이트**가 맡는다(G2 지시문 그대로: `BLE001,S110,E722` + 허용 목록 + 주입 2종). GOLD-26은 같은 장치를 만들지 않는다.
3. 옛 구역은 **건수 기록만** 한다. 기준선 표(`golden/reports_rescue/G2/옛구역_기준선.tsv`)는 **G2 소유**이며, 이 태스크는 만들지 않았다(§6).
4. 전역 도입은 **옛 코드가 편집 가능해진 뒤**(S74 삭제 판정 뒤, 또는 살리기 캠페인이 옛 코드를 실제로 고치기 시작한 시점) **재판정**한다. 재판정 때 이 문서의 260건·343 noqa·5 미배치를 그대로 입력으로 쓴다.

**권고에 붙는 두 가지 보강**(승인 항목 §7의 ②·③):
- G2 규칙 집합에 **`S112`를 추가**한다 — 현 지시문은 `BLE001,S110,E722`만이라 `continue`로 삼키는 3곳을 놓친다.
- `return None/False` 무음 3곳은 **어떤 ruff 규칙으로도 안 잡힌다.** 필요하면 AST 검사 태스크를 별도로 만든다(§5).

---

## 5. 예외 타입명 축 — BLE·S가 대체할 수 없다

### 5-1. 왜 대체 못 하는가 (실측 근거)

| 축 | BLE001 | S110 | S112 | 타입명 규칙 |
|---|---|---|---|---|
| 넓은 `except Exception` 탐지 | ✅ | ❌ | ❌ | ❌ |
| `pass` 본문 탐지 | ❌ | ✅ | ❌ | ❌ |
| `continue` 본문 탐지 | ❌ | ❌ | ✅ | ❌ |
| `return None/False` 무음 탐지 | ❌ | ❌ | ❌ | ❌ |
| **로그에 타입명이 있는지** 검사 | ❌ | ❌ | ❌ | ✅ (유일) |

- **BLE001은 타입명을 보지 않는다.** 타입명을 남기는 19건도 전부 잡는다(오탐 31/40).
- **S110·S112는 본문 형태만 본다.** `return None`으로 삼키는 `compiler.py:144`·`variable_engine.py:161`·`phase1:350`은 **셋 다 통과**한다.
- **좁은 예외로 삼키는 경우는 아무 규칙도 못 잡는다** — `except ValueError: return None`은 BLE001도 S110도 아니다.

### 5-2. 세 후보

| 후보 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **별도 ruff 규칙** | 설정 1줄 | 해당 규칙이 **없다**. ruff의 `TRY` 계열은 `logger.exception` 권장(TRY400)이지 타입명 검사가 아니다. S는 보안 규칙이다 | **불가** |
| **AST 검사** | `return None`·좁은 예외까지 볼 수 있다. 허용 목록으로 예외를 명시할 수 있다 | 오탐 위험 — 타입명이 payload·Metric·화면 문자열로 가는 6건(D분류)은 "로그 없음"으로 잡힌다. 검사기 자체의 뮤테이션 검증이 필요하다 | **가능 · 별도 태스크** |
| **수동 검토** | 즉시 가능 | 측정 불가 — "검토했다"가 판정 근거가 될 수 없다. CLAUDE.md 「검증 없는 기계 게이트를 인간 검수 대체로 선언 금지」에 걸린다 | **보조로만** |

### 5-3. AST 검사 설계 초안 (승인 시 별도 태스크)

검사 대상: `ast.Try`의 각 `handler`에 대해 다음 중 하나를 만족해야 통과.

1. `raise`(재전파) — 예외를 삼키지 않는다.
2. 핸들러 본문에 `type(<exc>).__name__` 또는 `exc_info=True` 또는 `logger.exception(` 호출이 있다.
3. 타입명을 구조로 넘긴다 — 반환값·payload 생성자에 `type(<exc>).__name__`이 들어 있다.
4. 허용 목록(`경로:줄 · 이유`)에 있다 — 정리(cleanup) 경로 등.

한계(명시): ③은 데이터 흐름 분석이 아니라 **같은 함수 안에 타입명 표현이 있는지**만 본다. 대리 변수(`name = type(exc).__name__` 뒤 `logger.warning(name)`)는 놓친다 — 이 경우 허용 목록으로 처리한다.

**이 태스크는 검사기를 만들지 않는다.** 설계만 남기고 승인 항목 ③으로 올린다.

---

## 6. RS G2 게이트와의 경계

### 6-1. G2가 소유하는 것 (지시문 원문)

`golden/prompts_rescue/단계02_병렬_3개_백엔드대장-잠금/RS-단계02-G2-잠금-조용한실패게이트.md` §작업 지시:

- **골든 구역 0건 강제** — `tests/golden/rescue/test_silent_failure_gate.py`가 ruff를 하위 프로세스로 돌려 `silent_failure_allow.txt`와 **정확히 같아야** 통과. 허용 목록에 없는 새 건 → 실패, 허용 목록에만 있고 실제로 없는 줄 → 실패.
- **옛 구역은 건수 기록만** — `golden/reports_rescue/G2/옛구역_기준선.tsv`. **게이트는 걸지 않는다.**
- `pyproject.toml`의 린트 설정은 **고치지 않는다**(G2 지시문 4항).
- 주입 2종(새 삼키기 추가 · 허용 목록에 없는 줄 남기기)에서 각각 실패해야 한다.

### 6-2. G2 산출물 실재 여부 (실측)

| 산출물 | 실재 | 근거 |
|---|---|---|
| `golden/reports_rescue/G2/` | **없음** | `ls golden/reports_rescue` → `D0 D2 D4 D5 D6 R0 R1` |
| `golden/reports_rescue/G2/옛구역_기준선.tsv` | **없음** | 같은 명령 |
| `tests/golden/rescue/test_silent_failure_gate.py` | **없음** | `ls tests/golden/rescue` → `__init__.py test_ledger.py test_outline.py` |
| G2 하네스 태스크 | **없음** | `grep -rln "조용한 실패 게이트" backlog/tasks` → `GOLD-25`·`GOLD-26`(이 문서의 출처)뿐 |

**따라서 G2 기준선 tsv는 인용할 수 없다.** 가장 가까운 증거는 선행 산출물 D2(`golden/reports_rescue/D2/끊김_건수.tsv`)이며, 패키지별 `BLE001`/`S110`은 이렇게 나뉜다 — l3 10/2 · harness 15/0 · ops 5/1 · l4 3/0 · api 3/0 · app.py 1/0 · 나머지 0. 합계 37/3으로 이 문서 §1-2와 일치한다.

### 6-3. 경계선

| 질문 | 소유 |
|---|---|
| 골든 구역에 새 무음 실패가 들어왔는가 | **G2** (허용 목록 게이트) |
| 옛 구역 패키지별 무음 건수는 얼마인가 | **G2** (기준선 tsv) · D2가 1차 측정 |
| 저장소 전역 `select`에 BLE·S를 넣을 것인가 | **GOLD-26**(이 문서) → Kiki 승인 |
| 전역 도입 시 260건을 어떻게 처리할 것인가 | **후속 태스크**(승인 뒤) |

**중복 방지**: GOLD-26은 `test_silent_failure_gate.py`·`silent_failure_allow.txt`·`옛구역_기준선.tsv`를 만들지 않았다. G2가 만든다.

---

## 7. Kiki 승인 요청 목록 (5건)

| # | 결정 사항 | 권고 | 근거 |
|---:|---|---|---|
| ① | 전역 `select`에 `BLE001`·`S110`·`S112`를 **지금 넣지 않는다**(다안) | **승인 권고** | §3 — 260건이 옛 코드 편집을 강제 |
| ② | G2 규칙 집합에 **`S112` 추가**(현 지시문은 `BLE001,S110,E722`) | **승인 권고** | §2 — `continue` 무음 3곳(옛 코드 3 · 골든 0). 골든은 현재 0건이라 비용 없음 |
| ③ | `return None/False` 무음 3곳을 잡는 **AST 검사 태스크 등재** | **승인 권고** | §5 — ruff 3규칙으로 불가 |
| ④ | 옛 구역 무음 7곳(9건)의 처분 — 골든 기간에는 **기록만**, S74 삭제 판정 뒤 재판정 | **승인 권고** | 골든 기간 옛 코드 읽기 전용 |
| ⑤ | 전역 도입 **재판정 시점·조건** — S74 이후 또는 옛 코드 편집이 시작된 시점 | **승인 권고** | §3 — 그때는 `noqa`/수정이 규칙 안 |

**승인 항목 수: 5건.** 이 문서는 `pyproject.toml`을 바꾸지 않았고, 집행 태스크도 등재하지 않았다 — 승인 뒤 별도 태스크로 분리한다.

---

## 7-1. 승인 결과 (2026-11-18 Kiki) — 5건 승인 · 집행 범위

Kiki가 §7의 5건을 전부 승인했다. 승인 뒤 실제로 한 일과 하지 않은 일은 이렇다.

| # | 결정 | 결과 | 증거 |
|---:|---|---|---|
| ① | 전역 `select`에 BLE·S를 지금 넣지 않는다(다안) | **승인 · 설정 변경 0줄** | `src/backend/pyproject.toml` `select` 무변경 |
| ② | G2 규칙 집합에 `S112` 추가 | **승인 · 집행 완료** | `tests/golden/rescue/test_silent_failure_gate.py` `_RULES` · `silent_failure_allow.txt` 머리말 · G2 지시문 1·3항 · `옛구역_기준선.tsv` S112 열 |
| ③ | `return None/False` 무음 AST 검사 태스크 등재 | **승인 · `GOLD-28` 등재** | `backlog/tasks/GOLD-28.yaml` |
| ④ | 옛 구역 무음 7곳(9건)은 기록만, S74 삭제 판정 뒤 재판정 | **승인 · 옛 코드 변경 0줄** | `golden/reports_rescue/G2/옛구역_기준선.tsv`(S112 열만 추가) |
| ⑤ | 전역 도입 재판정 시점 = S74 이후 또는 옛 코드 편집이 시작된 시점 | **승인 · 시점만 고정**(태스크 등재는 그때) | — |

### 7-1-1. ② S112를 넣었지만 새로 잡히는 위반은 0건이다

승인대로 넣었고 게이트는 초록이지만, **탐지력이 늘어난 것은 아니다.** 실측을 그대로 적는다.

- **S112는 `except Exception:`·`except:` + `continue`에서만 뜬다.** 좁은 예외에는 뜨지 않는다 — 2026-11-18 프로브에서 `except ValueError: continue`는 "All checks passed!", `except Exception: continue`는 S112 검출이었다.
- 따라서 S112가 잡는 자리는 **항상 BLE001 또는 E722와 같은 줄**이다. 옛 구역 S112 3곳(`l3/equivalent/authoring_guard.py:474` · `l3/equivalent/structural_dedup.py:183` · `harness/attempt_grading_shadow_report.py:186`)을 실측하니 **3곳 모두 같은 줄에서 BLE001도 떴다.** 골든 구역은 0건이다.
- 즉 **S112 ⊆ BLE001 ∪ E722**이고, §7 표의 "옛 코드 3 · 골든 0"은 ①의 BLE001 37건에 이미 포함돼 있던 3건이다. ②가 더 잡는 것은 없다.
- **그래도 넣는 이유**: 규칙 이름이 패턴을 지목한다. 나중에 골든에 `except Exception: continue`가 들어오면 게이트가 "BLE001 한 줄"이 아니라 **"S112도 걸린 줄"**로 보여 준다. **비용**: 그런 코드가 들어오면 허용 목록에 두 줄을 적어야 한다(규칙마다 한 줄).
- §7 ②의 근거 "골든은 현재 0건이라 비용 없음"은 그대로 맞다 — 다만 "3곳을 더 잡는다"는 뜻은 아니었다.

### 7-1-2. ②가 닿은 곳 (집행 지점 — 정본화 ≠ 집행)

| 파일 | 바뀐 것 |
|---|---|
| `tests/golden/rescue/test_silent_failure_gate.py` | `_RULES`에 `S112` · 합성 파일에 `except Exception: continue` 사례 추가(변별력) · 문면 "세 규칙"→"네 규칙" |
| `tests/golden/rescue/silent_failure_allow.txt` | 머리말 규칙 목록에 `S112` 추가. **허용 항목 4건은 그대로** — 골든 S112가 0건이라 줄이 늘지 않는다 |
| `golden/prompts_rescue/단계02_병렬_3개_백엔드대장-잠금/RS-단계02-G2-잠금-조용한실패게이트.md` | 사전 실측 사실 · 재현 명령 · 게이트 설명 · 기준선 열 안내를 네 규칙으로 |
| `golden/reports_rescue/G2/옛구역_기준선.tsv` | `ruff_S112`·`ruff_S112_noqa무시` 열 추가(합계 3/3 · l3 2/2 · harness 1/1 · 나머지 0) |
| `golden/reports_rescue/G2/보고.md` | 「추가 기록」 절로 S112 추가 경위·수치를 덧붙임(기존 보고 본문은 고치지 않는다) |

### 7-1-3. ③ GOLD-28의 경계

`GOLD-28`은 **검사기를 만드는 태스크**이고, 이 문서는 설계 초안(§5-3)만 남긴다. 착수 시점은 골든 패스 범위(중2 일차함수 30문항)와 무관하게 열 수 있으나, 골든 기간의 완료 기준(`tests/golden/` 초록불)을 흔들지 않도록 **게이트 추가는 `tests/golden/rescue/` 안에서만** 한다.

---

## 8. 재현 명령

모두 `src/backend`에서 실행한다(전역 측정은 저장소 루트에서 경로를 맞춘다).

```powershell
# 0) CI 고정 버전 준비 (로컬 venv가 0.15.20이면)
python -m pip install --target "$env:TEMP\ruff1522" "ruff==0.15.22"
$Ruff = "$env:TEMP\ruff1522\bin\ruff.exe"

# 1) 백엔드 소스 3규칙
& $Ruff check --select BLE001,S110,S112 --statistics .

# 2) G2 축(지시문 그대로)
& $Ruff check --select BLE001,S110,E722 --statistics .

# 3) 골든 구역 (G2 명령)
& $Ruff check golden ../../tests/golden --select BLE001,S110,E722

# 4) CI backend 잡 대상
& $Ruff check --extend-select BLE001,S110,S112 --statistics . ../../tests/backend ../../tests/constitution

# 5) 저장소 전역 S 전체가 얼마나 큰가
& $Ruff check --extend-select S --statistics . ../../tests/backend ../../tests/constitution
```

`-q`·`| tail`로 자르지 않고 **종료 코드**로 판정한다. 0건이면 exit 0, 1건 이상이면 exit 1이다.

---

## 9. 정직한 공백

- **옛 구역 기준선 tsv는 없다.** G2가 아직 실행되지 않았다. 이 문서의 패키지별 수치는 D2 보고에서 인용했고, G2가 자기 기준선을 만들 때 다시 재야 한다.
- **이 문서는 "무엇을 고칠지"를 정하지 않았다.** 40건 분류는 *무엇을 삼키는가*의 분류일 뿐, 각 지점을 고쳐야 하는지의 판정이 아니다. 설계된 강등(예: `verify_answer`의 보수적 `unverifiable`, `coach`의 substring 폴백)은 고치면 오히려 계약이 깨질 수 있다.
- **`noqa` 343줄의 내용은 검토하지 않았다.** 개수만 셌다. 전역 도입 시 343개 각각이 유효한 사유인지 별도 검토가 필요하다.
- **S 전체의 54,061건은 "그 규칙을 켰을 때"의 수**이며, 그중 98.6%(53,309건)가 테스트 `assert`(S101)다. 실제로는 테스트를 제외하거나 `per-file-ignores`로 S101을 빼야 의미가 생긴다 — 그 설계는 이 태스크 범위 밖이다.
- **`debug` 레벨 로그 2건**(`verify_answer:434`·`derivative_signature:734`)은 "타입명을 남긴다"를 형식적으로 충족하지만, 운영 로그 레벨에서 보이는지는 별도 확인이 필요하다.
- 로컬 venv ruff는 0.15.20, CI 고정은 0.15.22다. 핵심 건수(37/3/3/0)는 **두 버전에서 동일**함을 확인했으나, 전체 규칙 집합의 모든 차이를 비교한 것은 아니다.
