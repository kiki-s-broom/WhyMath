> **[OPS-38 회수 2026-10-08 — 이식 주석]** 이 문서는 고립 브랜치 `claude/whymath-ai-recommendation-review-q8tvcx`(커밋 `ee9df6dc`, 판정 기준 `origin/main` 2026-08-04)에서 회수했다. 원 파일명은 `data_platform_module_gap_review_r2.md`였으나, 같은 파일명의 다른 문서(`t608mk`의 외부 EOS 틀 대조 r2 — OPS-41이 `data_platform_eos_frame_gap_review_2026-08-11.md`로 이름을 바꿔 회수)와 충돌하지 않도록 이름을 바꿨다. **본문 판정은 수정하지 않았다**(아래 현황 표는 이 주석에만 있다).
>
> **번호 매핑**(본문은 등재 당시 번호): `OPS-19 → OPS-38`(본 회수 태스크) · `SEC-13 → SEC-32` · `OPS-20 → OPS-67` · `OPS-21 → OPS-32` · `HARN-15`는 번호 유지.
>
> **발견별 현황 — 판정 기준 `origin/main` `ec1f9dc7`(2026-10-08), 전부 실측:**
>
> | 발견 | 현황 | 근거 |
> |---|---|---|
> | A1 `qa_pipeline` 부모 잡 skip | **해소** | `COLLAB-07`(#817)이 `data-pipeline` 잡 `if`에 `corpus`를 OR 편입. 회귀 가드: `test_ci_contract_fixture_trigger_wiring.py::test_no_dead_changes_flag`(문자열 포함 판정) + `tests/infra/test_ci_gate_reachability.py`(OPS-38 · **의미 평가** — 잡 `if`의 OR→AND 뮤테이션을 포함 가드는 통과시키고 이 테스트는 RED로 잡는다) |
> | A2 코퍼스 읽는 검사기가 코퍼스 PR에서 안 돎 | **해소(원 해법과 다른 방식)** | 원 커밋 `592c961f`의 "data-pipeline 잡에 notation_coverage 중복 스텝 추가"는 **이식하지 않았다**. `COLLAB-07`이 `backend` 필터에 `data/corpus/`를 편입해(`ci.yml` changes 잡 backend 블록) backend 잡의 상시 `notation_coverage` 스텝이 코퍼스 PR에서 돈다 |
> | A3 `__main__` 있는데 워크플로 호출 0 | **상시 감시로 흡수** | `OPS-22` `declared_unwired_audit`(CI `declared-unwired-audit` 잡, exit 0·위반 0 실측). `harness.problem_bank_coverage`·`harness.visualization_reach_report`는 `_OFFLINE_REPORT`로 유예 분류, `ops.cost_report`는 `status: reached`. cost_report는 라이브 Langfuse 트레이스가 입력인 운영자 수동 계측 도구라 CI 직접 호출은 설계상 부적합 — 신규 태스크 불필요 |
> | B1 이벤트 페이로드 계약 미강제 | **미해소** | `OPS-67`(todo)이 소유. 이 문서 §2-B1과 부록 B1 실측이 그 유일한 상세 근거다 |
> | C1 삭제·반출 매니페스트 양방향 오류 | **해소** | `SEC-32`(done) |
> | C2 런타임 의존 6종 사용처 0 | **미해소** | 6종 모두 `src/backend/pyproject.toml:53-59`에 선언돼 있고 `src/`·`tests/`·`scripts/` import 0건(2026-10-08 실측). `OPS-32`(todo)가 소유하는 것은 **3종**(`opentelemetry-api`·`opentelemetry-sdk`·`structlog`)이었고, 나머지 3종(`pandas`·`polars`·`great-expectations`)은 소유 태스크가 없어 OPS-38 회수 시 `OPS-32` 수락 조건 ⑥으로 편입했다 |
> | C3 번호 충돌 가드의 타 브랜치 선점 맹점 | **해소** | `HARN-15`(done · #758) |
>
> **읽는 법**: 본문의 「🔴 최대」·「0건」 같은 서술은 2026-08-04 시점 사실이다. 현황은 위 표가 정본이고, A1·A2·C1·C3은 닫혔으며 B1·C2만 열려 있다.

# 데이터 플랫폼 모듈 — 갭 재점검 r2: 판정·선언의 진실성 (2026-08-04)

> **범위**: 외부 참고 문서 『1단계 데이터 플랫폼』(모듈 **84 이벤트 분석** · **85 품질 모니터링**
> — WhyMath 전용이 아닌 **일반적 데이터 플랫폼 틀**, Kiki 제공)에 대한 **2회차** 점검.
> **형식**: `operations_module_gap_review_r2.md`·`problem_bank_gap_review_r2.md`(r2 답습 시리즈) 준용.
>
> **r1과의 관계**: `data_platform_module_gap_review.md`(2026-08-03)가 이 틀의 84·85 **전 항목을
> 빠짐없이** crosswalk 했다. 이 r2는 **틀 항목을 다시 세지 않는다** — r1이 남긴 방법론 교훈을
> r1 자신의 나머지 판정에 적용한 결과다. r1을 대체하지 않고 **누적**한다.
>
> **r1이 남긴 교훈**(§1-85① 정정 기록): *"방어 코드가 존재한다"를 "위험이 없다"로 읽은 것이고,
> 이 저장소가 반복해 온 「존재함 ≠ 돌아감」 오류의 변종이다. **코드 존재 확인이 아니라 데이터
> 전수 집계가 판정 근거**여야 했다.*
>
> r1은 이 교훈을 중복 축(D3) **한 항목에만** 적용하고 문서를 닫았다. 이 r2는 같은 잣대를 r1의
> **나머지 ✅ 판정 전체**에 댄다.
>
> **결론**: r1이 ✅로 판정한 항목 중 **근거가 「코드가 존재한다」에 머물러 실측과 어긋나는 것
> 5건**을 발견했다. 그중 **3건은 r1의 기술을 정정**한다. 가장 큰 것은 저장소에서 가장 비싼 품질
> 게이트(`qa_pipeline`)가 **그것이 지키기로 한 PR에서 구조적으로 실행되지 않는다**는 사실이며,
> 그것을 막으려고 만든 배선 동결 테스트 5건이 **전부 green으로 통과한다**. 신규 태스크 5건 등재.
>
> **r2의 논지**: r1은 **"공급→소비 단절"**(만들고 입력을 잇지 않음)을 다뤘다. r2는 **"판정·선언이
> 실재와 어긋나는 축"**을 다룬다 — 게이트가 판정하지 않고(**A**), 계약이 강제되지 않고(**B**),
> 선언이 실재와 다른(**C**) 세 표면. 두 축은 다르며 중복이 아니다.

관련 정본: `data_platform_module_gap_review.md`(r1·기준선) ·
`docs/standards/superhuman_verification_standard.md`(검증 권위 서열·6축) ·
`docs/standards/build_harness.md`(백로그 규약·HARN-10) ·
`CLAUDE.md`(금기: *검증 장치를 만들고 배선 확인 없이 완료 선언 금지* · *변별력 없는 검증 스텝
금지* · *상시 실패하는 fail-open 보호를 「보호 있음」으로 신뢰 금지*) · `MEMORY.md`(2026-08-04).

---

## §0. 이 문서가 존재하는 이유 — 방법론 하나

r1은 자기 초고를 스스로 뒤집었다. 중복 축을 "생성 시점 가드가 실배선되어 있으므로 ✅ 충족"으로
판정했다가, 코퍼스 전수 집계로 **은행 간 slug 충돌 392건·발문 동일 279그룹**을 발견하고 🔴로
정정했다. 그 정정에서 r1은 원인을 정확히 짚었다 — **가드가 덮는 범위와 실제 위험 표면이 달랐다.**

그런데 r1은 그 잣대를 **한 항목에만** 댔다. §1의 나머지 ✅는 여전히 *"검사기 파일이 있다 →
충족"* 형태로 판정되어 있다. 이 r2가 하는 일은 단 하나다:

> **r1의 모든 ✅에 대해 "그 판정의 근거가 코드의 *존재*인가, 실행·강제·실재의 *측정*인가"를
> 되묻는다.**

결과는 아래 표다. 되물은 항목 중 5건에서 답이 갈렸다.

### §0-1. 기준선 의존 명시 (정직한 전제)

r1은 이 문서 작성 시점에 **미머지**다 — 브랜치 `claude/whymath-data-platform-design-8ceaf5` ·
커밋 `f3d312f0`. 이 r2는 그 위에 얹히도록 썼으나, **§2의 발견과 §3의 설계는 r1의 머지 여부와
무관하게 독립적으로 유효**하다(전부 `origin/main` 기준 코드에서 실측했다). r1이 끝내 머지되지
않아도 §3의 태스크 5건은 그대로 성립한다. 반대로 r1이 머지되면 §5의 중복 등재 금지 대장이
경계를 지킨다.

---

## §1. r1 판정 재검증 — 근거 유형별

`근거 유형`: **측정** = 실행·데이터·전수 집계로 확인 / **존재** = 파일·심볼이 있음으로 확인.

### 모듈 84 (이벤트 분석)

| r1 항목 | r1 판정 | 근거 유형 | r2 재판정 |
|---|---|---|---|
| 이벤트 페이로드 계약(`extra="forbid"` seam) | ✅ *"생산자가 반드시 경유"* | **존재** | ⚠️ **정정 → §2-B1**. 3/3 경유는 사실이나 **강제하는 테스트가 0건**. 우회문이 열려 있다 |
| 저장 좌석(hypertable·봉투 암호화) | ✅ | 존재 | ✅ 유지 — 스키마·마이그레이션 실재 |
| Event Store(`attempt_event`가 대행) | ✅ | 존재 | ✅ 유지 |
| 오개念 탐지(843건·인코딩 64종) | ✅ | **측정** | ✅ 유지 |
| A/B(McNemar·shadow 9종) | ✅ | 존재 | ⚠️ 부분 — `agreement_gate`는 **워크플로 호출 0건**(§2-A3). 자산은 실재하나 상시 판정은 아님 |
| 문제 제출·정답·풀이 시간 | ⚠️ 기존 추적(`REC-01`) | 측정 | ⚠️ 유지 — 클라 호출 0건 재확인 |
| 휴면 EventType 8종 | ⚠️ 기존 추적(`S3-16`) | 측정 | ⚠️ 유지 (11종 중 8종 휴면 = 73%) |

### 모듈 85 (품질 모니터링)

| r1 항목 | r1 판정 | 근거 유형 | r2 재판정 |
|---|---|---|---|
| 수식 렌더링 검사(`notation_coverage` **CI 상시**) | ✅ | **존재** | 🔴 **정정 → §2-A2**. "상시"가 아니라 `backend` 플래그 종속 — **코퍼스를 스캔하는데 코퍼스 PR에서 안 돈다** |
| 누락 데이터 탐지(4종 리포트) | ✅ | **존재** | 🔴 **정정 → §2-A3**. 4종 중 2종(`problem_bank_coverage`·`visualization_reach_report`)은 **워크플로 호출 0건** |
| 문제·정답 오류 검출(3상태 `AnswerVerdict`) | ✅ | 존재 | ✅ 유지 — 3상태 설계는 틀보다 엄격 |
| 생성 콘텐츠 평가(`corpus_audit_eval`) | ✅ | 존재 | ⚠️ **§2-A1 종속** — 전용 스텝 없이 `qa_pipeline` 축으로만 실행되므로 아래 A1이 그대로 적용된다 |
| AI Tutor 응답 품질(`coach_prose_leak_eval`) | ✅ | **측정** | ✅ 유지 — `backend` 잡 강제 스텝(ci.yml:275) |
| 결함주입 강등전(`defect_detection_eval`) | ✅ | **측정** | ✅ 유지 — `backend` 잡 강제 스텝(ci.yml:269) |
| 시스템 품질(`ServiceMetrics` 슬라이딩 창) | ✅ (`OPS-01` 상환) | **측정** | ✅ 유지 — 전역 HTTP 미들웨어(app.py:622)라 구조적으로 우회 불가. 단 인메모리·경로 차원 0(기지 한계) |
| ETL·일관성 검증(`validate.py` 11종) | ✅ | 존재 | ✅ 유지 |
| 품질 이력 관리 | 🔴 → D2 | 측정 | 🔴 유지 — **다만 D2의 전제가 정정된다**(§2-A1) |

### 모듈 84·85 공통 (r1 §2 미채택 판정 재검토)

| r1 미채택 | r2 재판정 |
|---|---|
| ① ClickHouse·Event Bus·Data Lake (6번째 store 회피) | **유지 — 그리고 강화**. §2-C1이 그 판정의 *귀결*을 처리하지 않았음을 발견했다(미도입 store가 매니페스트에 선언된 채 남았다) |
| ② 클릭스트림·행동 추적 (미성년자 PII 금기) | 유지 — 이견 없음 |
| ③ 퍼널을 KPI로 승격 (교수학 금기 충돌) | 유지 — 이견 없음. r1 §1-③ 블록쿼트가 정본 |
| ④ 실시간 대시보드 (1인 capacity) | 유지 |
| ⑤~⑩ | 유지 — 특히 ⑧(SymPy 서명 동일 ≠ 중복)의 반례 2쌍은 **측정** 근거라 견고하다 |

---

## §2. 발견 (전부 `origin/main` 기준 실측)

### A. 게이트가 판정하지 않는다 (실행 진실성)

#### A1 — `qa_pipeline` 게이트가 그것이 지키기로 한 PR에서 **구조적으로 실행되지 않는다** 🔴 최대

| 요소 | 실측 |
|---|---|
| 스텝 조건 | `if: needs.changes.outputs.corpus == 'true'` — `ci.yml:179` |
| **부모 잡 조건** | `data-pipeline` 잡: `if: (… \|\| needs.changes.outputs.data_pipeline == 'true') && …` — `ci.yml:114` |
| `corpus` 플래그 발화 조건 | `^(data/corpus/\|\.github/workflows/ci\.yml$)` — `ci.yml:95-96` |
| `data_pipeline` 플래그 발화 조건 | `^(src/data-pipeline/\|tests/data_pipeline/\|conftest\.py$\|\.github/workflows/ci\.yml$)` — `ci.yml:74-75` |

두 조건을 동시에 참으로 만드는 변경은 **`ci.yml` 자기 자신**(양쪽 정규식에 공통으로 들어 있다)
뿐이다. 따라서:

> **코퍼스만 바꾸는 PR에서는 부모 잡이 통째로 skip되어, 게이트가 시작조차 하지 않는다.**

이것은 `continue-on-error: true`(`ci.yml:186`)로 무음화되는 것보다 **한 단계 앞선** 결함이다.
무음 실패는 최소한 실행은 된다. 여기서는 실행 자체가 없다. 저장소에서 가장 비싼 품질 게이트
(ARCH-21이 검사 8축을 조립한 단일 판정)가 **설계 대상 PR에서 한 번도 돌지 않는다**.

**그리고 이것을 막기 위해 만든 배선 동결 테스트가 통과한다.** `tests/infra/test_qa_pipeline_wiring.py`
5건이 검사하는 것:

| 테스트 | 줄 | 검사 대상 |
|---|---|---|
| `test_qa_pipeline_step_exists_in_data_pipeline_job` | :61 | 스텝 존재 |
| `test_qa_pipeline_step_uses_module_invocation_not_bare_script` | :69 | `-m` 호출형 |
| `test_qa_pipeline_step_is_conditional_on_corpus_changes` | :92 | **스텝 if에 `corpus` 문자열이 있는가** |
| `test_qa_pipeline_step_overrides_working_directory_to_repo_root` | :104 | working-directory |
| `test_changes_job_exposes_corpus_output` | :116 | `changes` 잡의 output 노출 |

**어느 것도 스텝 조건과 부모 잡 조건이 동시에 참일 수 있는지 보지 않는다.** 나아가 :117
도크스트링은 이렇게 적혀 있다 —

> *"`changes` 잡이 `corpus` output을 노출해야 `data-pipeline` 잡의 `if` 조건이 유효하다."*

부모 잡의 `if`는 `corpus`가 아니라 `data_pipeline`이다(`ci.yml:114`). **오해가 그것을 막으려고
만든 테스트 안에 박제되어 있다.**

> **왜 이것이 규범 위반인가**: CLAUDE.md는 *"검증 장치를 만들고 배선 확인 없이 완료 선언 금지 —
> 「저장소에 존재함」과 「돌아감」은 다르다. 이 부류는 이 프로젝트에서 **반복 발생**했다"*를 금기로
> 등재하고 선례 3회(`tests/infra` 199건 미실행·브랜치 보호 `enforcement_level=off`·`tests/infra`
> lint 잡 부재)를 나열한다. **이것이 4회차이며, 가장 순수한 형태다** — 결함이 그것을 막으려고
> 만든 테스트 *안에서* 발생했다. 실수 관리 규범상 재발방지대책 등재는 **의무**다.

**r1 정정**: r1 §3-D2는 *"`qa_pipeline`은 코퍼스 변경 트리거라 원장 행이 드물게 쌓여 추세는
당분간 통계적으로 무의미하다"*를 전제로 목적을 좁혔다. 실측상 코퍼스 PR에서는 **한 행도 쌓이지
않는다**(main push 시에만 발화한다 — `changes` 잡이 비-PR 이벤트에서 전 플래그를 true로 두기
때문, `ci.yml:57-65`). D2의 전제 자체가 정정 대상이며, **D2보다 A1이 선행**한다. 판정을
보존하기 전에 판정이 일어나야 한다.

#### A2 — 코퍼스를 읽는 검사기가 코퍼스 PR에서 돌지 않는다 🔴

| 검사기 | 실행 스텝 | 소속 잡 | 발화 조건 | 실제로 읽는 것 |
|---|---|---|---|---|
| `l3/notation_coverage.py` | `ci.yml:290` | `backend` | `src/backend/` 변경(`ci.yml:203`) | `data/corpus/problem_bank_*/problems.jsonl` **전수**(`:556-557`) |
| `ops/provenance_audit.py` | `ci.yml:296` | `backend` | 〃 | `data/corpus/<코퍼스>/_provenance.json`(`:14`) |

**대상과 트리거의 축이 어긋나 있다.** 코퍼스를 검사하는 도구가 백엔드 소스 변경에 매여 있다.
`notation_coverage`는 코퍼스가 0건이면 *"전수 측정이 공허하게 통과할 수 없으므로 명시 실패한다"*
(`:271-272`)고 할 만큼 자기 입력에 엄격한데, 정작 그 입력이 바뀌는 PR에서 실행되지 않는다.

**r1 정정**: r1 부록은 이들을 *"(상시)"*로 기록했다. 상시가 아니라 `backend` 플래그 종속이다.
(`backend` 잡은 doc-only PR 비용 절감 목적의 `if`를 갖는다 — 의도 자체는 타당하나, 코퍼스 자산
검사기를 그 잡에 둔 배치가 부작용을 낳았다.)

#### A3 — `__main__` CLI를 갖췄으나 워크플로 호출 0건 ⚠️

`harness/problem_bank_coverage.py` · `harness/visualization_reach_report.py` · `ops/cost_report.py`
— 셋 다 CLI 진입점을 갖추고 있으나 `.github/workflows/` 전체에서 호출 0건이다.
`harness/agreement_gate*.py`(3변형)·`harness/pedagogical_rubric.py`도 동일(후자는 라이브러리로
`prompt_asset_audit.py:25`가 import하므로 CLI 부재가 정상).

**r1 정정(부분)**: r1은 85④ "누락 데이터 탐지 ✅"의 근거로 `provenance_audit`·
`problem_bank_coverage`·`notation_coverage`·`visualization_reach_report` 4종을 들었다. 그중 **2종은
아예 안 돌고**, 나머지 2종은 A2 상태다. 근거 4종 중 **상시 판정에 기여하는 것은 0종**이다.

> **다만 신규 등재하지 않는다** — `problem_bank_coverage`는 `ARCH-18`이, `visualization_reach_report`는
> `VIZ-04`가 이미 소유한다(중복 등재 금지). `OPS-19`가 **가시화만** 한다.

### B. 계약이 강제되지 않는다 (강제 진실성)

#### B1 — 이벤트 페이로드 계약은 규율이지 불변식이 아니다 ⚠️

r1은 84①을 *"생산자(`api/coach.py`·`api/interactions.py`)가 반드시 경유"* ✅로 판정했다.
재검증 결과 **현재 준수는 사실, 강제는 0**이다.

| 사실 | 근거 |
|---|---|
| 생산자 3종 전부 `build_event_data` 경유 | `api/coach.py:922`·`:977`, `api/interactions.py:75` |
| **우회를 금지하는 테스트 0건** | `tests/backend/schema/test_event_data_contract.py` 5건은 계약 *내부* 정합성만 검사 |
| 무방비 우회문이 열려 있다 | `db/models/activity.py:268` `AttemptEvent.from_schema()` — 계약을 전혀 참조하지 않는다(현재 호출자 0). `schema.AttemptEvent.event_data`는 `dict[str,Any]` 자유형 |
| DB 층 방어도 없다 | `event_data`는 평문 `JSONB(none_as_null=True)` — `db/models/activity.py:266`, CHECK 제약 0 |
| 계약의 진실 원천이 사람이다 | `_PRODUCED`(테스트 :30-32)는 **손으로 적은 리터럴**이며, 주석이 *"탐사(producer 전수 grep)로 확정한 3종"*이라고 **자인**한다 |
| 그 grep 자체가 취약하다 | 생산자 3종 중 2종은 ORM을 **별칭으로 import**해 쓴다 — `api/coach.py:62` `AttemptEvent as AttemptEventORM` → `:922`·`:977`이 `AttemptEventORM(`. `api/interactions.py:75`만 `AttemptEvent(`. **`grep "AttemptEvent("`는 3종 중 1종만 잡는다**(이 문서 작성 중 실측) |

**귀결**: 다음 커밋에서 `AttemptEvent(event_data={"typo": 1})`을 직접 쓰면 **전 테스트가 green으로
통과한다.** 계약을 지키는 것은 테스트가 아니라 사람이다.

> **별칭 문제는 R3 설계의 제약이기도 하다** — 신설할 정적 테스트가 문자열 `AttemptEvent(`만
> 찾으면 **지금 이 순간에도 3종 중 2종을 놓친다**. 소스 스캔은 import 별칭을 해석해야 하며
> (`ast` 모듈로 `ImportFrom`의 `asname`을 따라가는 것이 최소 요건), 이 요구를 acceptance에
> 명시해 두지 않으면 신설 테스트가 A1과 같은 "통과하지만 안 보는" 장치가 된다.

이 저장소에는 소스를 `read_text()`로 스캔하는 정적 거버넌스 테스트 패턴이 **이미 있다** —
`tests/backend/harness/test_gate3_student_verification_governance.py:111`이 `api/coach.py` 소스를
읽어 금지 참조를 검사한다. **패턴은 있는데 이 seam에만 적용되지 않았다.**

### C. 선언이 실재와 다르다 (선언 진실성)

#### C1 — 개인정보 삭제·반출 매니페스트가 **양방향으로** 틀렸다 🔴 (의사결정 우선순위 2위 축)

`privacy/erasure.py:123-150`·`export.py:135-159`가 "RDB 밖이라 못 지운/못 반출한 외부 store"로
3종을 선언한다. 각 store의 실재를 전수 실측했다.

| store | 의존 선언 | 클라이언트 코드 | compose 서비스 | config 키 | 판정 |
|---|---|---|---|---|---|
| **ClickHouse** | 0 | 0 | 0 | 0 | **미도입 — 없는 store를 선언** |
| **S3/MinIO** | 0 (boto3·minio·s3fs 전무) | 0 | 0 | 0 | **미도입 — 없는 store를 선언** |
| **Redis** | ✅ `pyproject.toml:22` | ✅ | ✅ `docker-compose.prod.yml:118` | ✅ `config.py:85` | 실재하나 **locator가 실재하지 않음**(아래) |

**Redis locator의 부정확**: 매니페스트는 `user_id={uid} 연관 세션·캐시 키`(`erasure.py:147`)라
서술하나, `user_id`를 키 네임스페이스에 넣는 경로는 둘뿐이고 **배포 기본값에서 전부 비활성**이다
— coach rate limit(`coach_rate_limit_backend` 기본 `"memory"`, `config.py:864`) · device count
캐시(`device_store_mode` 기본 `"none"`, `config.py:672`). 두 환경변수 모두 prod compose env 목록
(`docker-compose.prod.yml:47-68`)에 없다. 반대로 **실제로 학생 유래 데이터가 들어가는 경로**(LLM
응답 캐시 — 키는 프롬프트 해시라 `user_id`로 조회·삭제 불가, `l3/router.py:329`·`:335-346`;
Celery payload — `l3/queue/celery_job_queue.py:185`)는 **서술되지 않았다**.

**그리고 누락이 더 중대하다 — Langfuse가 매니페스트에 없다.**

| 사실 | 근거 |
|---|---|
| `student_id_hash`를 외부 SaaS로 **실제 전송**한다 | `l3/trace/langfuse_sink.py:126` |
| 전송 호출부 | `l3/router.py:371`·`:417`, `l3/pipeline.py:137`·`:220`·`:264` |
| 기본 주입(옵션 아님) | `app.py:499` |
| 프로덕션 실배포 | `docker-compose.prod.yml:63-65`(env 3종), `config.py:315-325` |

> **미성년자 데이터의 실재하는 유일한 외부 반출처가 삭제·반출 매니페스트에 등재되어 있지 않다.**
> 매니페스트는 **없는 store 2개를 선언하고, 있는 store 1개를 누락**했다. 허위 선언보다 누락이
> 중대하다 — 전자는 과잉 보고이고 후자는 미보고다.

**이 틀린 집합을 회귀 테스트 6건이 동결한다**: `test_erasure.py:156`(집합 고정)·`:178`(개수 3),
`test_export.py:233`(집합 고정), `test_me_erasure.py:140-142`, `test_me_export.py:249`.
코드에서 지우면 테스트가 깨지는 구조다.

> **r1 정정**: r1 §4는 이를 *"존재하지 않는 store를 「못 지웠다」고 삭제 요청 학생에게 보고하는
> 셈이다"*라고 기술했다. 실측상 **`pending_external`은 API 응답에 실리지 않고 ops 로그로만
> 나간다** — `DELETE /v1/me`의 응답 모델 `AccountErasureResponse`는 `user_id`·`total_rows_deleted`
> 2필드뿐이고(`api/me.py:2275-2281`), store명은 로그 경로에만 있다(`:2321-2327`·`:2362-2369`).
> 학생이 보는 문구(`export.py:111-115`)는 store명을 명시하지 않는다. **수신자는 학생이 아니라
> 운영자와 코드 독자다.** 과장을 걷어내도 Langfuse 누락은 남으며, 그쪽이 실질 위험이다.

#### C2 — 데이터 플랫폼 축 런타임 의존 6종의 사용처가 0이다 ⚠️

`src/backend/pyproject.toml` 런타임 의존 **26종 전수** 스캔(`src/`·`tests/`·`scripts/`):

| 의존 | 줄 | import | 비고 |
|---|---|---|---|
| `opentelemetry-api` | :45 | **0** | CLAUDE.md 스택 표가 *"모니터링 = Langfuse + **OpenTelemetry**"*로 확정 선언 |
| `opentelemetry-sdk` | :46 | **0** | 〃 |
| `structlog` | :47 | **0** | |
| `pandas` | :50 | **0** | |
| `polars` | :51 | **0** | |
| `great-expectations` | :52 | **0** | `data_pipeline/ncic/validate.py:3`이 *"great_expectations 미사용(대형 의존성). 자체 validator로 동일 invariant 검증"*이라고 **코드가 스스로 자인** |

**6종 전부가 데이터 플랫폼 축이다** — 관측성(OTel·structlog)·분석(pandas·polars)·데이터 품질
(great-expectations). 우연이 아니라 구조적 결과다: 이 축은 "나중에 제대로 할 것"으로 **선언만**
되고, 실제로는 자체 경량 구현(`validate.py` 11종·`ServiceMetrics`·`qa_pipeline`)으로 대체돼 왔다.
**r1은 그 경량 실재가 옳다고 판정했다**(§2-① 6번째 store 회피·과공학 방지). 그 판정이 옳다면
**선언을 실재에 맞춰 내려야 한다.** 지금 상태는 무거운 선언만 남아 세 가지 비용을 낸다 —
설치·빌드 시간, CVE 표면, 그리고 **미래 세션의 오판 근거**("OTel이 이미 있으니 그걸 쓰자").

> **정상 예외**: `uvicorn`(CLI 실행체)·`asyncpg`/`psycopg`(SQLAlchemy DSN 드라이버)도 import 0이나
> 각각 정당한 사유가 있다. 게이트 설계 시 근거와 함께 예외 목록에 넣는다.

**대비가 증거다**: 이 파일은 의존마다 근거 주석을 다는 방식으로 **적극 관리된다** — SEC-07의
passlib 제거 기록, embedding extra 분리 사유, langfuse `<5` pin 상한의 실측 근거. 그 한가운데
"관측성·데이터" 블록 6종만 근거 없이 남아 있다. 그리고 **`MOB-08`이 하루 전 만든 선언↔사용
거버넌스 게이트(`src/mobile/test/pubspec_dependency_usage_governance_test.dart`, 발견분 5종을
`MOB-09`로 처분)는 Flutter 전용이라 Python 축에 대응물이 없다.**

#### C3 — (부수 발견) 태스크 ID 번호 충돌 가드가 타 브랜치 선점을 못 본다 ⚠️

이 문서를 위해 태스크를 등재하다 발견했다. **`OPS-17`과 `OPS-18`이 각각 두 태스크에 이중
배정되어 있다**:

| 번호 | main | 브랜치 `claude/whymath-data-platform-design-8ceaf5` |
|---|---|---|
| OPS-17 | `client-version-contract-gate`(#677 `a2bfa85c`, 2026-08-03 13:00 UTC) | `supply-demand-reach-audit`(`f3d312f0`, 같은 날 **07:03 UTC**) |
| OPS-18 | `cloud-escalation-reach-observability`(〃) | `qa-verdict-retention`(〃) |

브랜치가 6시간 **먼저** 등재했는데 main 쪽 세션이 그것을 보지 못했다. 원인은 가드의 관측
표면이다 — `backlog.py:718-743`의 `_taken_id_numbers`는 **로컬 백로그 + 원격 *claim* 대장**만
본다. claim은 `in_progress`만 기록하므로 **"등재만 되고 미착수"인 번호는 구조적으로 안 보인다**.
게다가 이 환경은 `refs/claims/*` push가 프록시 403으로 **상시** 실패해(`HARN-07`) claim 경로가
fail-open 상태라 2선 방어도 없었다.

**이것은 `HARN-10`(ARCH-13·OPS-15 2회 실측 후 등재)의 3회차이며, A1과 정확히 같은 형태의
결함이다** — 가드는 실재하나 그것이 보는 표면이 실제 위험 표면과 다르다. 슬러그가 달라
`validate`는 통과하므로(실측: 이 문서의 태스크 5건 추가 후에도 `✔ 백로그 무결성 green`),
깨지는 것은 **사람·문서·커밋의 번호 참조**뿐이다.

---

## §3. 설계 R1~R5 (등재된 태스크)

우선순위: **R1(게이트가 아예 안 돎) → R2(법적·윤리 축) → R3·R4·R5**.

R1이 1순위인 이유 — 다른 넷은 "관측·강제가 없다"이고 R1만 **"가장 비싼 게이트가 무효 상태로
며칠째 방치되어 있고, 그 사실을 아무도 모른다"**이다. 2026-07-16 Langfuse v2 8일 무증상 전멸과
같은 구조다.

### R1. `OPS-19-ci-gate-reachability-contract` — priority 2 · S3 · infra

**설계**: `tests/infra/`에 신설한다. **새 잡을 만들지 않는다** — `infra-contracts` 잡은 `if` 가드
없이 항상 실행되고(`ci.yml:646`), ci.yml을 파싱하는 선례가 이미 둘 있다
(`test_provenance_audit_wiring.py`·`test_qa_pipeline_wiring.py`).

**계약**: 게이트성 스텝마다 **(부모 잡 `if` ∧ 스텝 `if`)를 동시에 참으로 만드는 변경 파일 집합이
존재해야 한다.** `changes` 잡의 path 정규식을 파싱해 플래그별 대표 경로를 도출하고, 각 게이트의
조건 조합에 대해 만족 가능성을 정적 판정한다. 불가능하면 exit 1.

- **동반 수정**: `qa_pipeline`을 실제 도달 가능하게. **권장 = `data-pipeline` 잡 `if`에 corpus
  플래그 추가** — 잡 신설보다 diff가 작고, 스텝의 `working-directory: .` 오버라이드가 이미 있어
  그대로 동작한다. A2(`notation_coverage`·`provenance_audit`)의 축 정렬도 함께. 단 `backend` 잡
  전체는 35분(`ci.yml:199` timeout)이라 **통째 트리거는 금지** — 경량 경로 선택은 구현 시 판정.
- **오인 기술 정정**: `test_qa_pipeline_wiring.py:117` 도크스트링.
- **가시화(게이트 아님)**: `__main__`을 갖췄으나 워크플로 호출 0인 CLI 목록 보고 — 소유 태스크가
  있으면 그 id 병기(`visualization_reach_report.py:1-30`의 *"100% 도달은 목표가 아니다"* 관례
  답습).
- **변별력 검증 의무**(CLAUDE.md *변별력 없는 검증 스텝 금지*): `data-pipeline` 잡 `if`를 원복하면
  신설 테스트가 **실패**해야 하고, 고친 상태에서는 **통과**해야 한다. 갈리지 않으면 위장이다.

### R2. `SEC-13-external-store-manifest-truthfulness` — priority 2 · S3 · backend

- **Langfuse 등재가 본체**(누락 해소). `student_id_hash` 전송 실측을 locator로 기술.
- ClickHouse·S3 제거 또는 "미도입" 사유 병기 — 선례: `CLAUDE.md:82`(Wolfram Alpha)·`:77`(GPT-5/
  Gemini)·`00_overview.md:165`(Neo4j 2026-08-03 정정).
- Redis locator를 실재 경로로 정정하거나 조건부 표기.
- **회귀 테스트 6건을 하드코딩 집합에서 계약으로 전환** — *"선언된 store는 config 키 또는 compose
  서비스로 실재가 확인돼야 한다"*. 다음 store 추가 시 자동 방어된다.
- **범위 밖**: 실제 외부 삭제 실행(Langfuse API 연동)은 별건 — 매니페스트 진실성까지.

### R3. `OPS-20-event-payload-contract-enforcement` — priority 3 · S3 · backend

- 소스 스캔 정적 테스트로 `AttemptEvent(...)` 생성 전량의 seam 경유를 강제(기존 패턴 재사용).
- `_PRODUCED` 손베낌 리터럴을 스캔 산출로 대체.
- `AttemptEvent.from_schema` 우회문 처분.
- **변별력 검증**: 우회 생성 1줄을 넣으면 red, 빼면 green.
- **`S3-16`과의 경계**: S3-16은 휴면 EventType의 **신규 생산자 신설**, R3은 기존 3종 생산 경로의
  **강제력**. 층위가 다르다.

### R4. `OPS-21-python-dependency-usage-governance` — priority 3 · S4 · backend

- `MOB-08`의 Flutter 게이트 대응물을 `tests/infra/`에 신설(grandfather 목록 + 열린 task id 요구 —
  `MOB-09` 규약 답습).
- 예외 목록을 **근거와 함께** 명시(`uvicorn`·`asyncpg`·`psycopg`). 근거 없는 예외 추가 금지.
- 미사용 6종 처분. OpenTelemetry 제거 시 **CLAUDE.md 스택 표·`00_overview.md`에 "미배선" 병기**.

### R5. `HARN-15-id-collision-cross-branch-scan` — priority 3 · S3 · infra

- `backlog.py add`의 번호 충돌 검사에 **원격 브랜치 `backlog/tasks/` 파일명 스캔** 추가.
- 네트워크 비용 가드 — 캐시된 remote-tracking ref만 읽고 fetch하지 않는다(`cmd_next`의
  `scan_remote_done` 선례·실측 12ms). 조회 실패 시 **예외 타입명을 경고에 포함**(기존 `:728` 관례).
- **변별력 검증**: 타 브랜치에만 있는 번호로 add하면 거부 + 다음 빈 번호 제안, 그 브랜치를 지운
  상태에서는 통과.
- 이미 발생한 이중 배정 2쌍(OPS-17·OPS-18)의 **재배번 대상·시점은 Kiki 판정**.

---

## §4. 정직한 공백 — 지금 하지 않는 것

| 공백 | 사유 | 해소 시점 |
|---|---|---|
| **원격 브랜치 보호의 실재성** | 저장소 *안에서* 검증 불가 — `branch-protection-setup.md:150-156`이 실제 GitHub 설정이 `enforcement_level=off`·`checks=[]`였다고 자인한다. 문서·테스트는 코드로 지킬 수 있으나 원격 설정은 아니다 | Kiki의 수동 확인(`OPS-08` 소관) |
| `ServiceMetrics` 영속화·경로 차원 | `OPS-01` done 상태의 기지 한계(인메모리·전역 창 1개·다중 워커 부분 관측). `incident_response_slo.md:51`이 S5를 미측정으로 정직 표기 중 | 외부 스크레이퍼 도입 시 |
| `CacheDegradationCounter`의 `/health/ready` 노출 | `redis_cache.py:216` 도크스트링이 "배선은 후속"이라 명시 — 수집은 되나 운영자가 볼 표면이 없다 | OPS 후속 |
| 알림 채널 · 서비스 지표 영속화 · 외부 업타임 프로브 | **r1 §4 승계** — 온콜 0명, `SEC-12`가 스케줄 진입점 소유 | r1 §4 트리거 |
| 문항 중복 실쌍의 *해소* · ClickHouse/Event Bus | **r1 §4·§5 승계** | 〃 |
| A3의 미배선 CLI 3종 *배선* | `ARCH-18`·`VIZ-04`가 2종을 소유. `ops/cost_report`는 소유자 없으나 단독 등재할 만큼 독립적이지 않다 | R1의 가시화 리포트가 드러낸 뒤 판정 |

---

## §5. 중복 등재 금지 대장

이 r2가 **건드리지 않는** 기존 추적:

**r1(미머지)의 설계** — D1 `OPS-17-supply-demand-reach-audit`(공급↔소비 **런타임/구조** 도달 대장:
서버 라우트 ↔ 클라 호출) · D2 `OPS-18-qa-verdict-retention`(판정 **보존**) · D3
`QUAL-01-problem-duplication-audit`(문항 중복).

> **R1과 D1·D2의 경계**: D1은 *서버 write-path 라우트 ↔ 클라이언트 호출*의 도달을, D2는 *판정
> 결과의 시간축 보존*을 다룬다. R1은 *CI 스텝 조건 ↔ 부모 잡 조건*의 도달 가능성이다. 대상 표면이
> 셋 다 다르다. **순서상 R1이 D2에 선행한다** — 판정을 보존하려면 판정이 먼저 일어나야 한다.

**기존 태스크** — `S3-16`(휴면 EventType writer·`LearningSession` 영구 미신설 결정) ·
`REC-01`(추천 도달 관측, done) · `NLP-01`(OCR 축) · `NLP-02`(채점 권위, done — 단 전제인
`POST /v1/me/attempts` 호출이 0건이라 입력이 구조적으로 0) · `ARCH-18`(문제은행 커버리지 리포트) ·
`VIZ-04`(시각화 도달 리포트) · `ARCH-19`(LaTeX 파스·답 분포 게이트) · `S3-28`(canonicalize 축 결함
130건 — R1이 `continue-on-error` 제거를 강제하지 **않는다**, 그건 D2 소관) · `OPS-08`(브랜치 보호
드리프트) · `OPS-16`(프롬프트 자산 감사) · `SEC-12`(보존 파기 스케줄) · `HARN-07`(원격 claim 상시
실패) · `MOB-08`/`MOB-09`(Flutter 축 선언↔사용 — R4의 **선례이자 대응물**, 같은 축이 아니다).

**틀 항목에서 태스크를 만들지 않는 이유**: r1 §1이 84·85 전 항목을 이미 판정했고, 미채택 판정
(§2-①~⑩)은 이 r2가 재검토해 **전건 유지**했다. 이 문서의 태스크 5건은 전부 **틀 항목이 아니라
r1의 판정 근거**에서 나왔다.

---

## 부록 — 실측 근거 (2026-08-04, `origin/main` 기준)

재현 명령:

```bash
cd /home/user/WhyMath

# A1 — 스텝 if(corpus)와 부모 잡 if(data_pipeline)의 교집합이 ci.yml뿐임
sed -n '74,75p;95,96p;114p;179p;186p' .github/workflows/ci.yml

# A1 — 배선 동결 테스트가 무엇을 보는지(도달 가능성은 없다)
grep -n "def test\|needs.changes.outputs" tests/infra/test_qa_pipeline_wiring.py

# A1 — 핵심 주장의 실증: 게이트가 도달 불가인 채로 배선 동결 테스트는 5건 전부 통과한다
python3 -m pytest tests/infra/test_qa_pipeline_wiring.py -q   # → 5 passed (2026-08-04 실측)

# A2 — 코퍼스를 읽는데 backend 잡에 있다
grep -n "problem_bank_\*/problems.jsonl" src/backend/whymath_backend/l3/notation_coverage.py
sed -n '203p;290p;296p' .github/workflows/ci.yml

# A3 — __main__은 있는데 워크플로 호출 0
grep -rn "problem_bank_coverage\|visualization_reach_report\|cost_report" .github/workflows/ || echo "워크플로 호출 0건"

# B1 — AttemptEvent 생성 전량과 seam 경유 여부
#      ※ 별칭(AttemptEventORM)을 포함해야 3종이 다 잡힌다 — `AttemptEvent(`만 찾으면 1종만 나온다
grep -rnE "AttemptEvent(ORM)?\(" src/backend/whymath_backend/ | grep -v ":class "
grep -n "build_event_data(" -r src/backend/whymath_backend/
grep -n "_PRODUCED" tests/backend/schema/test_event_data_contract.py

# C1 — 선언된 3종의 실재 / 누락된 Langfuse의 실재
grep -rn 'store="' src/backend/whymath_backend/privacy/erasure.py
grep -rniE "clickhouse-driver|clickhouse-connect|boto3|minio|s3fs" src/backend/pyproject.toml || echo "ClickHouse·S3 의존 0건"
grep -n "student_id_hash" src/backend/whymath_backend/l3/trace/langfuse_sink.py

# C2 — 런타임 의존 26종 중 import 0인 것 전수
python3 - <<'PY'
import re, pathlib, subprocess
p = pathlib.Path('src/backend/pyproject.toml').read_text(encoding='utf-8')
deps = re.findall(r'"([^"]+)"', re.search(r'^dependencies\s*=\s*\[(.*?)^\]', p, re.S | re.M).group(1))
alias = {'opentelemetry-api': 'opentelemetry', 'opentelemetry-sdk': 'opentelemetry',
         'great-expectations': 'great_expectations', 'pyyaml': 'yaml',
         'python-jose': 'jose', 'pydantic-settings': 'pydantic_settings'}
for d in deps:
    n = re.split(r'[<>=\[!~ ]', d)[0]
    m = alias.get(n, n.replace('-', '_'))
    r = subprocess.run(['grep', '-rl', '-E', rf'^\s*(import|from)\s+{re.escape(m)}\b',
                        'src/', 'tests/', 'scripts/'], capture_output=True, text=True)
    if not r.stdout.split():
        print('MISSING', n)
PY
# 기대 출력: uvicorn·asyncpg·psycopg(정상 예외) + opentelemetry-api·opentelemetry-sdk·
#           structlog·pandas·polars·great-expectations(C2 대상)

# C3 — OPS-17/18 이중 배정
for b in origin/main origin/claude/whymath-data-platform-design-8ceaf5; do
  echo "[$b]"; git ls-tree -r "$b" --name-only backlog/tasks/ | grep -E 'OPS-1[78]'
done
```

핵심 수치:

- **워크플로 파일 2개**(`ci.yml` 1055줄 · `deploy.yml` 235줄), 잡 14+2개, `schedule:` cron 1건
  (`ci.yml:17-18` `0 18 * * *` → `e2e-nightly`만).
- **`continue-on-error: true` 2건** — `ci.yml:186`(qa_pipeline·게이트) · `:859`(shellcheck·의도적).
- **강제 배선된 게이트 5종**(전부 `backend` 잡): `defect_detection_eval`(:269) ·
  `coach_prose_leak_eval`(:275) · `pedagogy_pack_fidelity_eval`(:283) · `notation_coverage`(:290) ·
  `provenance_audit`(:296). **단 `backend` 플래그 종속이라 코퍼스 PR에서는 전부 skip**(A2).
- **`upload-artifact` 2건** — 둘 다 `coverage.xml` 전용(`:166`·`:300`). `qa_report.json` 업로드·커밋
  경로 0건(워크플로 전체 `git commit` 0건).
- **EventType 11종 중 휴면 8종**(73%) — `schema/enums.py:845-852`. `힌트요청`(학생 demand)은 휴면,
  `힌트제공`(AI supply)만 활성이라 **"학생이 힌트를 요청했다"는 신호는 DB에 한 행도 없다**.
- **`ProblemAttempt` 생성 좌석 1개**(`api/me.py:677`) · **Flutter 호출 0건** — 클라 엔드포인트
  13종에 `/v1/me/attempts` 부재(대조군: `/v1/interactions`는 `interaction_logger.dart:50`에서
  실호출 — 이벤트 좌석 중 **시각화조작만 end-to-end가 살아 있다**).
- **런타임 의존 26종 중 import 0이 9종** — 정상 예외 3종(`uvicorn`·`asyncpg`·`psycopg`) +
  **C2 대상 6종**.
- **`docker-compose*.yml` 정의 서비스 전수**: prod(`app`·`db`·`redis`·`retention-purge`) ·
  demo(`demo-db`) · pilot(`pilot-db`). **ClickHouse·MinIO 0건**, `infra/`에 compose 0건.
