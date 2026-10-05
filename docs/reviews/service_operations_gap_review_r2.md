# 서비스 운영(Service Operations) 모듈 — 외부 EOS 틀 대조 **2차 재점검(r2)** (2026-08-11)


> ## ⚠️ 회수 착지본 — 2026-10-05 (`OPS-40`) · 읽기 전에 이 블록부터
>
> **성격**: 이 문서는 고립 브랜치 `origin/claude/whymath-service-operations-review-5t5lmv`(head `dd3e9475`,
> 이 문서의 최종 커밋 `7052c34a`)에서 **회수**한 2026-08-11 점검 기록이다. 본문은 *그 시점의 기록*이라
> 보존했고, 본문의 `파일:줄` 인용은 2026-08-11 번호다. 아래는 main(`d0ba970c`, 2026-10-05) 현행과 대조한 정정이다.
> 대조는 읽기 전용 에이전트 3개가 `origin/main`에 대해 수행했고 핵심(`MGMT-02`·ARCH-64·`CACHE-01`·신고 API 경로·
> `flutter_tts` 제거 사실)은 이 세션이 직접 재확인했다. **인용한 줄 번호를 쓰기 전에 다시 재라.**
>
> **① 소유 태스크 번호 매핑** — 고립 브랜치가 쓴 번호가 main에서는 다른 태스크라 새 번호로 승계했다.
>
> | 본문(2026-08-11) | main 현행 소유 | main에서 그 옛 번호의 정체 |
> |---|---|---|
> | G1·D6 `OPS-34-removed-dependency-canon-sync-gate` | **`OPS-113-removed-dependency-canon-sync-gate`** | `OPS-34` = 오프라인 리포트 수취인 계약(별건) |
> | G2·D7 `OPS-35-client-version-gate-observability` | **`OPS-112-client-version-gate-observability`** | `OPS-35` = 감사기 멤버십 소비 탐지(별건) |
> | G3·D8 `A11Y-02-accessibility-coverage-drift-gate` | **`A11Y-02-accessibility-coverage-drift-gate`**(번호 그대로) | main에 없던 번호 |
>
> 본문에서 소유자를 지정하는 줄은 새 번호로 고쳤다. **§4-④·§8의 번호 충돌 서술(`OPS-33`→`OPS-34` 배정)과 부록 명령
> 출력은 당시 일어난 일의 기록이라 옛 번호 그대로 둔다.**
>
> **② 현행 델타 — 본문 판정은 그대로 성립한다(G1~G3 모두 main에서 여전히 열려 있음).**
> D1~D5 5건은 모두 `done`. G1(정정 6곳 미집행)은 이번 회수가 7개 파일을 상환했다(아래 ③). G2(426이 요청 회계 이전에
> early-return · 미상 카운터 프로덕션 리더 0 · 클라 426 분기 1곳 · 기본 `0.0.0`·상향 트리거 서술 없음)와 G3(a11y
> 게이트 대상 5개 · chat·problem·신고 다이얼로그 게이트 밖 · 드리프트 가드 0)는 **그대로 열려 있다.** 바뀐 사실:
> `MGMT-02`는 `blocked`가 아니라 `todo` + 게이트(본문 3곳 정정) · 백로그 258건→986건 · `presentation/` 위젯 파일
> 16개→17개(커버리지 31%→약 29%) · MOB-09가 걷은 5종 중 `flutter_math_fork`는 S3-39로 재도입(`pubspec.yaml`).
>
> **③ 이번 회수(`OPS-40`)가 한 일 · 하지 않은 일**
>
> | 항목 | 처분 | 사유 |
> |---|---|---|
> | `api/speech.py`·`schema/speech.py` `flutter_tts` 서술 | **이식** | stale 전제 현존·패치 충돌 0·pytest로 계약 확인 |
> | `05_interaction.md`·`system_deep_dive.md`·`visualization_module_gap_review.md`·`ui/01`·`ui/02` 정정 | **이식** | 동일. `05`의 44dp 부분은 main이 이미 정정(48dp 정본) — 패치 대상 아님 |
> | `service_operations_gap_review.md`(v1) 배너 + API 경로 오기(`/v1/defect-reports`→`/v1/reports/defects`) | **이식** | 오기 현존·실제 경로 `api/reports.py:34,55`로 확인 |
> | `06_design_system.md` §7 TTS 행 발화 트리거 + 후속 항목 소유자 병기 | **이식** | 소유자는 새 `A11Y-02` 등재로 실재 |
> | `service_ops_mgmt_gap_review_2026-07.md:43`("학생 경로가 구조적으로 LOCAL 고정이라 비용 사고 위험 0") | **기각** | **전제가 낡았다.** ARCH-64로 학생 대면 서빙도 `build_cloud_provider()`의 클라우드 좌석을 쓴다(`CLAUDE.md` 스택 표·`app.py:966`). 재판정이 필요하며 이 회수 범위 밖 |
> | `CLAUDE.md` 스택 표 클라우드 LLM 행 정정(§정정 6) | **기각(main 우세)** | 그 행은 `CLAUDE.md:86`으로 이동했고 ARCH-64 기준으로 전면 재작성됐다. 본문의 "원문→실측" 서술은 더 이상 성립하지 않는다 |
> | `CLAUDE.md` 프로세스 금기 1건 신설(§7 "문서 §정정의 소유자 위임을 집행으로 착각 금지") | **기각** | **2026-09-20 "새 산문 규칙 등재 동결"(Kiki 지정)과 충돌.** 허용되는 변경은 기존 규칙의 정정·삭제·집행 코드 참조 병기뿐이다. 이 교훈의 집행은 `OPS-113`(제거↔정본 동기 게이트)이 코드로 맡는다. 규칙 문구 자체를 원하면 Kiki가 동결 예외를 판정할 일 |
> | `OPS-35` 구현(백엔드 `app.py`·`config.py` + 모바일 컨트롤러 7곳) | **미이식 → `OPS-112`** | Flutter 없이 모바일 검증 불가 · `config.py`·컨트롤러 일부는 이후 main이 우세(이식 금지 목록은 `OPS-112` notes) |
> | `A11Y-02` 구현(모바일 테스트 2파일 + `06` §7) | **미이식 → `A11Y-02`** | Flutter 없이 검증 불가 |
> | `OPS-34` 설계 YAML | **승계 → `OPS-113`** | main에 동등 테스트 0건 |
> | `events.ndjson` 44줄·`MEMORY.md`의 OPS-35·A11Y-02 완료 서술 | **이식 금지** | 번호 충돌 · 그 구현이 main에 없어 "완료"가 거짓이 된다 |
>
> 회수가 끝나기 전에는 고립 브랜치 `5t5lmv`를 **삭제하지 않는다**(`OPS-112`·`A11Y-02`의 참조 구현이 거기 있다).


> **범위**: v1(`service_operations_gap_review.md`, 2026-08-03)과 **동일한 외부 참고 문서**
> (『22. 서비스 운영』 모듈 91 결제·구독·환불 · 92 접근성(Accessibility) · 93 푸시 알림
> 인프라 · 94 고객지원(CS)·오류 신고 · 95 앱 배포·업데이트 관리 — **WhyMath 전용이 아닌
> 일반적 EOS 틀**, Kiki 제공)을 **v1 이후 착지분이 만든 새 지형**과 다시 대조한 기록.
> **성격**: 처음부터의 재대조가 아니라 **델타 재점검**이다. v1의 판정 — 특히 §2 의도적
> 미채택 13건 — 은 전건 유효하므로 **승계하고 재판정하지 않는다**. 다루는 것은 ⑴ v1 설계가
> 구현된 뒤 **남은 실공백**과 ⑵ v1 이후 변화로 **stale해진 칸**뿐이다.
> **v1 이후 상태**: v1이 설계한 **D1~D5 5건이 전부 착지**했다 — `RPT-01`(#690) ·
> `A11Y-01`(#692) · `OPS-18`(#693) · `MOB-08`(#694) · `OPS-17`. 그 사이 `MOB-09`(#695)가
> 모바일 의존 5종을 더 걷었고, 운영 EOS r3(#775)가 `RPT-02`·`OPS-29~32`를 등재했다.
>
> **결론 4줄**:
> 1. **최대 갭 = v1이 스스로 적은 §정정 9곳 중 6곳이 8일간 미집행.** v1 §정정은 소유자를
>    지정했으나("1~5·8은 D2에서, 6·7은 D3 notes로"), 그 파일들이 `A11Y-01`·`OPS-18`의
>    **acceptance·paths에 내려가지 않아** 집행되지 않았다. CLAUDE.md "정본화를 집행으로
>    착각한 완료 선언 금지"의 **문서 평면 변형** → **G1**, 이번 세션이 직접 상환 + `OPS-113`.
> 2. **버전 계약(`OPS-17`)이 반쪽 집행** — 게이트는 정확히 도는데 **작동한 비율이 안 보인다**.
>    426 차단이 계측 *이전에* early-return돼 요청 회계에서 사라지고, "미상" 카운터는
>    프로덕션 리더가 0이며, 클라 426 분기는 7개 컨트롤러 중 1개뿐이다 → **G2 / `OPS-112`**.
> 3. **접근성 커버리지가 AA 선언 직후 고정** — `06_design_system.md` §7이 후속 3종을 정직히
>    적어 뒀는데 **추적하는 열린 태스크 0건**이고, 화면 16개 중 게이트 대상은 5개, 주 학습
>    화면(chat·problem)과 `RPT-01`이 새로 만든 신고 다이얼로그가 전부 밖이다 → **G3 /
>    `A11Y-02`**. 운영 r3 D9의 **접근성 평면 재발**.
> 4. **v1 stale 정정 + 범위 확대** — v1이 44dp 이중 진실원천을 2곳으로 봤으나 실측 **5곳**
>    이었다(UI 설계 정본 2건 추가 발견). v1 본문의 API 경로 오기 1건도 정정.

관련 정본: [`service_operations_gap_review.md`](../architecture/service_operations_gap_review.md)(v1 — 이
문서의 모체, 판정 근거의 원본·소급 수정 금지) ·
[`operations_module_gap_review_r3.md`](../architecture/operations_module_gap_review_r3.md)(2026-08-11,
모듈 42~50 3차 — `RPT-02`·`OPS-29~32` 소유자, 중복 등재 회피 대상) ·
[`gamification_module_gap_review_r2.md`](../architecture/gamification_module_gap_review_r2.md)(동일 문서
재제출 → r2 전환 선례·골격 답습) · `docs/design/ui/06_design_system.md` §7(접근성 현황
정본) · `MEMORY.md` 결정 로그(2026-08-03 v1 · 2026-08-11 본 문서).

---

## §0. 재점검 사유 — 왜 v1을 덮어쓰지 않고 r2를 새로 쓰는가

### ① 동일 문서 재제출임을 수치로 확정한다 (추론 아님)

제출 문서와 v1 §범위가 기술한 구성이 **모듈 번호·명칭·세부 항목 구성까지 일치**한다:

| 모듈 | 제출 문서 구성 | v1 §범위 기록 |
|---|---|---|
| 91 결제·구독·환불 | 결제 6 · 구독 7 · 환불 5 · 운영 5 | 동일 |
| 92 접근성 | 시각 6 · 청각 3 · 운동 4 · 인지 5 · 표준 3 | 동일 |
| 93 푸시 알림 | 학습 6 · 운영 5 · 채널 5 · 시스템 5 | 동일 |
| 94 CS·오류신고 | 접수 5 · 오류 6 · 처리 5 · 분석 4 | 동일 |
| 95 배포·업데이트 | 배포 5 · 버전 5 · 운영 5 · 모니터링 5 | 동일 |

제출본 말미의 "서비스 운영 아키텍처" 도식과 "WhyMath에서의 역할" 5줄 요약, "운영
플랫폼(86~90)과 함께 상용 SaaS로 완성" 문장까지 v1 대조 대상과 같다. **즉 새 요구사항이
추가된 재제출이 아니라 같은 틀의 재제출**이다.

### ② v1을 in-place 수정하지 않는 이유

v1은 완료된 태스크 5건(`RPT-01`·`OPS-17`·`A11Y-01`·`OPS-18`·`MOB-08`)의 **acceptance가
가리키는 판정 근거 원본**이다. 본문을 고치면 "그 태스크가 왜 그 범위였는지"의 근거가
사라진다(v1→r2 선례: `operations_module_gap_review` v1→r2, `gamification` v1→r2). v1에는
**배너 1줄 + 오기 1건 정정**만 얹었다.

### ③ 승계 선언 — 재판정하지 않는 것

- **v1 §2 의도적 미채택 13건 전건 유효**. 재심 근거를 실측으로 확인했다:
  `MGMT-02` 여전히 선행 미충족(⑫⑬ 그대로 — 당시 `blocked`, 2026-10-05 현재는 `todo` + 게이트 `G-external-counsel-restart-after-internal-completion`) · 결제 코드 0(ROADMAP Phase 2 M2.3) ·
  `consecutive_active_days` writer·reader **여전히 0**(§2-③ 스트릭 영구 미채택 유지) ·
  `accessibility_needs` writer 0(§2-⑧) · 알림 발송 채널 0(§2-④) · CS 티켓 0(§2-⑤ 1인
  capacity) · mobile CI는 여전히 analyze·test만(§2-⑬).
- **v1 §4 정직한 공백 13종·§5 발화 트리거 10건**도 승계한다. r2가 갱신하는 것은 §5에
  **트리거 2건 추가**뿐(아래 §5).

---

## §1. v1 판정의 변경분 — 바뀐 칸만

| v1 판정 | r2 판정 | 근거 |
|---|---|---|
| **91**: 최대 갭 = 승급 사슬 도달 0 (D3) | ✅ **상환(관측 축)** | `OPS-18` done — `l3/escalation_defaults.py` 단일 좌석(6곳 리터럴 0) + `cost_probe`가 "0건 통과"가 아니라 **"미도달"**로 렌더(`:537,544`). *실배선은 여전히 결제 하류*(의도된 유예) |
| **92**: 목표 미선언 + 배율 무방비 (D2) | ✅ **상환** → ⚠️ **새 갭(커버리지 고정)** | WCAG 2.1 AA 선언(`06_design_system.md:82`)·배율축 1.0/1.3/2.0×(`accessibility_test.dart:160`)·`Semantics(label: caption)`(`scene_renderer.dart:181`) 전부 착지. 그러나 커버리지가 5개에 고정 → **G3** |
| **93**: 선언-only 의존 (D5) | ✅ **상환·초과** | `MOB-08` firebase 2종 제거 + 거버넌스 테스트 + CI `--enforce-lockfile`(`ci.yml:572`). `MOB-09`가 5종 더 제거 |
| **94**: 최대 갭 = 학생 결함 신고 경로 0 (D1) | ✅ **상환** → ⏸ 읽기 축은 `RPT-02` 소유 | `DefectReport`(user_id 부재 동결 테스트) + `POST /v1/reports/defects` + Flutter 버튼 + `qa_pipeline` 축 9. **읽기 경로 0은 운영 r3 D11이 이미 등재** — 재등재 금지 |
| **95**: 클라 버전 미상 (D4) | △ **부분 상환** → ⚠️ **G2** | 게이트 자체는 정확히 착지(426·`min_app_version`·드리프트 게이트). 그러나 **차단·미상이 관측 불가** |
| **§정정 9곳** | 🔴 **6곳 미집행 → G1** | 실제 반영은 5번 1건, 4번은 부분(3곳 중 2곳). 나머지 6건 미착지 |

### v1 설계 5건 착지 실측 (전건 done — 상태와 실물이 일치)

| 설계 | 태스크 | 실물 근거 |
|---|---|---|
| D1 | `RPT-01` | `db/models/audit.py:154` `DefectReport` · `api/reports.py:34,55` · `defect_report_button.dart`(유일 호출부 `chat_screen.dart:250`) · `qa_pipeline.py:639-641` 축 9 · alembic `db8ae6d2d91c`(체인 정상·고아 아님) |
| D2 | `A11Y-01` | `06_design_system.md:82` AA 선언 · `accessibility_test.dart:57,160` 배율축 · `scene_renderer.dart:181` Semantics |
| D3 | `OPS-18` | `l3/escalation_defaults.py` · `ops/cost_probe.py:226-256,322,334,528-547` |
| D4 | `OPS-17` | `api_client.dart:25` · `app.py:181,785-830` · `config.py:1176` · `tests/infra/test_app_version_pubspec_sync.py`(CI 상시 실행 잡) |
| D5 | `MOB-08` | `pubspec.yaml:50-52` · `pubspec_dependency_usage_governance_test.dart` · `ci.yml:572` |

**즉 v1의 설계 축은 상환됐다.** 남은 것은 v1이 스스로 적어 둔 정정의 미집행과, 착지한
계약들의 **관측·커버리지 반쪽**이다.

---

## §2. 잔여 갭 — 실측

### G1 — v1 §정정 9곳 중 **6곳 미집행**. 정정 위임이 acceptance로 내려가지 않았다 (최대 갭)

v1 §정정(`service_operations_gap_review.md` 말미)은 stale 정본 9곳을 실측하고 **소유자를
명시**했다 — *"1~5·8은 D2(`A11Y-`) 범위에서 처리한다(같은 파일군을 다루는 태스크가 정정의
자연스러운 소유자). 6·7은 `CLAUDE.md`·다른 세션 정본이라 이 문서가 직접 고치지 않고 D3
(`OPS-`) notes로 연결한다."*

실측 결과 **위임은 선언됐지만 집행되지 않았다**:

| # | 위치 | v1 위임처 | 8일 뒤 상태 |
|---|---|---|---|
| 1 | `schema/speech.py:4,151,171` · `api/speech.py:7` | D2 | ③ 미착지 |
| 2 | `05_interaction.md:48` · `system_deep_dive.md:101` | D2 | ③ 미착지 |
| 3 | `visualization_module_gap_review.md:135` | D2 | ③ 미착지 |
| 4 | 탭영역 44 vs 48dp | D2 | ② 부분 — 05·06은 통일, `system_deep_dive.md:103` 잔존 |
| 5 | `coding_flutter.md:76` "접근성 100%" | D2 | ① **착지(유일)** |
| 6 | `CLAUDE.md:77` 클라우드 LLM 행 | D3 notes | ③ 미착지 |
| 7 | `service_ops_mgmt_gap_review_2026-07.md:43` | D3 notes | ③ 미착지 |
| 8 | `06_design_system.md:95` TTS 🔴 행 | D2 | ③ 미착지 |

**구조적 원인(실측)**: `A11Y-01`의 acceptance 4항에는 **4·5만** 들어갔고 1·2·3·8이 없다.
`paths`에도 `schema/speech.py`·`system_deep_dive.md`가 없다. `OPS-18`은 `notes`에 §정정 6을
언급만 하고 `acceptance`·`paths` 어디에도 `CLAUDE.md`가 없다. **즉 위임은 산문에만
있었고 태스크의 기계 판정면(acceptance·paths)에는 존재하지 않았다** — 두 태스크 모두
acceptance를 문자 그대로 충족하고 정당하게 done이 됐다.

**왜 최대 갭인가**: v1 §6이 **9회차 반복 실수**로 지목한 위험 — *"다음 세션이 '클라만 붙이면
된다'고 읽고 이미 실패로 판명난 Gradle 경로를 다시 시도할 위험"* — 이 **지목만 되고 그대로
살아 있었다**. 갭을 발견하고 이름까지 붙였는데 처분이 증발한 형태다.

**성격 규정**: CLAUDE.md **"정본화를 집행으로 착각한 완료 선언 금지"** 의 *문서 평면 변형*.
그 규칙이 **"계약을 서빙 코드가 실제로 부르는가"** 를 묻는다면, 이번 건은
**"정정 위임이 소유 태스크의 acceptance·paths로 내려갔는가"** 를 묻는다. 2회차이므로
CLAUDE.md 실수 관리 규약상 **재발방지 등재 의무 대상**(→ §7).

### G2 — 버전 계약(`OPS-17`)이 반쪽 집행. 임계를 올릴 판정 재료가 구조적으로 없다

`OPS-17`은 게이트 자체를 정확히 착지시켰다 — 신규 미들웨어를 만들지 않고 기존 좌석에
얹었고, 426은 401/404/422와 구분되며, Settings 오구성 시 fail-open까지 갖췄고, 양방향
변별력 테스트도 있다. **문제는 게이트가 아니라 게이트의 관측면**이다.

| 축 | 실측 | 함의 |
|---|---|---|
| **426 차단이 계측 밖** | `app.py:823-827`이 `started = time.monotonic()`(`:831`)·`_observe_request`(`:837`) **이전에 early-return** | 차단된 요청은 요청 수·에러율·p95 **어디에도 없다**. 임계를 올려 학생 N명이 끊겨도 서비스 지표는 아무 변화가 없다 |
| **"미상" 카운터가 write-only** | `app.state.app_version_unknown_count`(`app.py:182,766-781`). 리더는 **테스트 어서션 2건뿐**(`tests/backend/test_app.py:687,690`), 프로덕션 리더 0 | `/health/ready` body가 `ocr`·`solution_segmentation`·growth_evidence 카운터를 노출하는데 **이 축만 없다** — 좌석 관용구가 있는데 안 쓴 것 |
| **클라 426 분기가 1/7** | `diagnosis_controller.dart:22,69-73`만 전용 문구. chat·auth·ocr·onboarding·me_tab·account_security 6개 컨트롤러는 generic `catch` | 차단이 "일반 실패"로 위장된다 — 2026-07-20 인증 누락 사고(단일 실패 문구가 원인을 덮음)와 **같은 구조**, 그 사고를 막으려 만든 계약이 같은 형태를 남겼다 |
| **임계가 영구 무력** | `min_app_version` 기본 `"0.0.0"`(`config.py:1177`) = 모든 버전 통과 | 기본값 자체는 옳다(기존 클라 보호·fail-open). 문제는 **언제·누가 올리는지 트리거·소유자가 0**이라는 것 |

**성격 규정**: CLAUDE.md **"작동 신호 없는 알고리즘 부착 금지 — 작동한 비율"** 정면 해당.
그리고 **`RPT-02`(신고가 접수만 되고 아무도 못 읽음)와 같은 형태의 다른 평면**이다 —
`RPT-02`는 *입력*이 판독되지 않는 문제, G2는 *집행 결과*가 판독되지 않는 문제.

**"안 고치면 무엇이 조용히 틀리는가"**: 지금은 게이트가 무력(0.0.0)이라 아무 일도 없다.
그러나 파일럿 중 API 계약이 깨져 임계를 올리는 순간, ⑴ 몇 명이 끊겼는지 사후에도 알 수 없고
⑵ 끊긴 학생 중 문제 화면 밖에 있던 사람은 "앱을 업데이트하세요"가 아니라 정체불명의 실패
문구를 본다. **임계를 올리는 그 순간에만 드러나는 결함**이라 지금 닫는 것이 옳다.

### G3 — 접근성 자인 후속의 백로그 추적 0건 + 커버리지 드리프트 가드 0

`06_design_system.md` §7은 정직하다 — 🟡 표기로 "chat·ocr *전체 화면 상태*는 미검증",
"Semantics 전면 감사는 후속"을 스스로 적어 뒀다. **그런데 그 후속을 추적하는 열린 태스크가
0건**이다(`A11Y-01`은 done, 백로그 258건(2026-08-11 기준 · 2026-10-05 현재 986건) 중 접근성을 다루는 태스크는 그것뿐).

실측 커버리지:

| 축 | 수치 |
|---|---|
| a11y 게이트 대상 | **5개** — `ExploreScreen`·`HomeScreen`·`MeScreen`·`SceneRenderer`·`CoachSignalCard` |
| `lib/features/*/presentation/` 실제 위젯 파일 | **16개**(그중 `*_screen.dart` 10개 · 2026-10-05 현재 17개) |
| 게이트 밖 주요 화면 | `chat_screen`(주 학습 화면)·`problem_screen`·`ocr_capture_screen`·`mathlive_input_screen`·`login_screen`·`onboarding_screen`·`account_security_screen` |
| 게이트 밖 신규 산출물 | **`defect_report_button.dart`** — `RPT-01`(v1 설계 D1)이 이번에 만든 신고 다이얼로그가 **접근성 게이트 밖으로 태어났다** |
| 커버리지 드리프트 가드 | **0** — 새 화면이 늘어도 아무 검사도 반응하지 않는다 |

**성격 규정**: 운영 r3 D9가 명명한 *"정직 표기는 침묵 통과는 막지만 영구 미상환은 막지
못한다"* 의 **접근성 평면 재발**. AA를 목표로 선언한 것(A11Y-01의 성과)이 오히려
"목표가 있으니 됐다"로 읽힐 수 있는 상태다 — 목표는 있고 커버리지는 31%(5/16 · 2026-10-05 현재 약 29%, 5/17)에 고정.

**왜 "전부 검증"이 답이 아닌가**: 16개 전부를 지금 게이트에 넣는 것은 과도하다(로그인·
온보딩은 노출 빈도가 낮고, WebView 계열은 위젯 테스트 대상이 아니다). 필요한 것은
**"어디까지 검증했는지가 기계로 고정되고, 새 화면이 조용히 늘지 않는 것"** 이다.

---

## §3. 정직한 공백 — 지금 하지 않는 것 (사유 명시)

| # | 공백 | 왜 지금 아닌가 |
|---|---|---|
| ① | `min_app_version` 실제 상향 | 상향은 **관측이 선행**해야 한다(G2 ②가 착지해 미상 비율을 볼 수 있을 때). 순서를 뒤집으면 몇 명이 끊겼는지 모른 채 끊는다 |
| ② | 강제 업데이트 유도 UI·스토어 링크 | 스토어 배포 자체가 `MGMT-02`(당시 blocked · 현재 todo+게이트) 하류(v1 §2-⑬) — 링크를 걸 대상이 없다 |
| ③ | 접근성 16개 화면 전수 편입 | 위 G3 마지막 문단. WebView 2종(`mathlive_input_webview`·`graphing_calculator_webview`)은 위젯 테스트로 내부 접근성을 볼 수 없다 |
| ④ | Semantics 라벨 **전면** 감사 | 화면 집합이 아직 늘어나는 중(`RPT-01`이 이번에 하나 더 추가). 전면 감사는 집합이 안정된 뒤가 옳다 |
| ⑤ | ocr *인식 후 cue* 상태 검증 | OCR 실기기 경로가 파일럿에서 실사용되기 전 — 만들어도 실제 상태를 재현하지 못한다 |
| ⑥ | `defect_report` 판독·집계 | **`RPT-02` 소유**(운영 r3 D11) — 재등재 금지 |
| ⑦ | `qa_pipeline` 축 9 CI 상시 error | **`ARCH-23` 소유**(운영 r3가 acceptance 보강) — 재등재 금지 |
| ⑧ | 결제·구독 실배선·tier별 quota | v1 §5-① 트리거(결제 도입 결정) 승계. `OPS-18`이 관측 좌석만 열어 뒀다 |
| ⑨ | 44dp 표기가 남은 **코드 주석 2곳** | `account_security_screen.dart:28`("44dp 이상 요구 — A11Y 가드는 48dp로 검사")·`chat_screen.dart:531,559`("48dp(44dp+)")는 **48을 실제로 강제하면서 44를 하한으로 언급**할 뿐이라 모순이 아니다. 정본 문서(값을 정하는 자리)만 정정했다 |

---

## §4. 정정 — v1 stale (v1 본문을 수정하지 않고 여기 기록·이번 세션이 실집행)

### ① v1 §정정 6곳 — **이번 세션이 직접 상환**

태스크로 다시 미루지 않은 이유: **이번 r2의 최대 발견이 "정정을 태스크에 위임했더니
8일간 집행되지 않았다"** 이다. 같은 처리를 반복하면 발견 자체가 무의미해진다. 정정 *본문*은
이 세션이 상환하고, **재유입을 막는 기계**만 태스크(`OPS-113`)가 소유하는 분할로 갔다.

| 대상 | 처리 |
|---|---|
| `schema/speech.py:4,155,175` · `api/speech.py:7` | "`flutter_tts`로 합성만 한다" 단정 → **"클라 합성 경로 현재 0"** 실측 병기(제거 사유·재도입 선행조건 포함) |
| `05_interaction.md` §5 TTS 불릿 | 동일 + 트리거 포인터 |
| `system_deep_dive.md:101` | 동일 |
| `visualization_module_gap_review.md:135,159` | "음성 표면 실재" → **"서버 표면 실재·클라 합성 0"** 로 정밀화 |
| `06_design_system.md` §7 TTS 행 | 🔴 후속 → **트리거 ⓐⓑⓒ 병기**("곧"이 아니라 트리거 대기임을 명시) |
| `CLAUDE.md:77` 클라우드 LLM 행 | **"배선됨 ≠ 학생 트래픽 도달"** 실측 병기 + 도달 계상 위치(`ops/cost_probe.py`) 명시 |
| `service_ops_mgmt_gap_review_2026-07.md:43` | "CACHE-01 계열에서 후속" → **승계처 소멸** 명시 + 현행 판정(비용 fail-closed·결제 하류 유예) |

### ② v1이 놓친 확대 — 44dp 이중 진실원천은 **2곳이 아니라 5곳**이었다

v1 §정정 4는 `05_interaction.md`·`system_deep_dive.md` 2곳만 지목했다. 실측 결과 **UI 설계
정본 2건이 더** 44dp를 표준으로 말하고 있었다:

| 위치 | v1 인지 | 처리 |
|---|---|---|
| `05_interaction.md:46` | ✅ | A11Y-01이 48dp로 통일(착지) |
| `system_deep_dive.md:103` | ✅ | **이번 세션 정정** |
| `docs/design/ui/02_student_ui_master_plan.md:39` "≥44dp+" | ❌ 미인지 | **이번 세션 정정** |
| `docs/design/ui/02_student_ui_master_plan.md:46` "탭 44dp" | ❌ 미인지 | **이번 세션 정정** |
| `docs/design/ui/01_student_pipeline_to_menus.md:105` "44dp 탭 영역" | ❌ 미인지 | **이번 세션 정정** |

**교훈**: v1의 정정 목록 자체가 전수가 아니었다. 정정을 *목록*으로 관리하면 목록의
완전성이 다시 문제가 된다 — 그래서 `OPS-113`가 **목록이 아니라 게이트**를 만든다.

### ③ v1 본문 오기 1건

v1 `:177` 착지 정정 블록이 API 경로를 `POST /v1/defect-reports`로 적었으나 **실제는
`POST /v1/reports/defects`**(`api/reports.py` prefix `/v1/reports` + `@router.post("/defects")`).
v1 상단 배너에 정정 기록.

### ④ 백로그 이벤트 로그 2건 (정직 기록 — 감사 로그는 편집하지 않는다)

**ⓐ 회수된 `add` 이벤트**: 이번 세션이 `backlog.py add`로
`DOC-01-removed-dependency-canon-sync-gate`를 등재한 뒤 접두어를 `OPS-`로 바꾸기로 하여
**파일을 즉시 회수**했다. `events.ndjson`에는 그 `add` 이벤트가 남아 있다(append-only
감사 로그이므로 편집하지 않는다 — 실제로 일어난 일이다). `validate` green(258건).
최종 등재 ID는 `OPS-34`.

**ⓑ `policy_warn` 3건 (adhoc_edit)**: 이 세션이 `schema/speech.py`·`api/speech.py`의
docstring을 정정할 때 하네스가 *"claim한 태스크 없이 코드 파일 편집"* 경고를 남겼다
(`mode: warn` — **deny가 아니다**). 우회하지 않고 여기 기록한다:
- **왜 그대로 진행했나**: 두 편집은 **docstring·Field description 문자열만**이고 동작
  변경 0이다(`ruff`·`black` exit 0, `tests/infra` 298 passed). 그리고 이 정정을 다시
  태스크로 미루는 것이 바로 **G1이 발견한 실패 형태**다 — 8일 전 v1이 같은 판단을 했고
  그 결과가 이 문서의 최대 갭이다.
- **경고가 옳게 지적하는 것**: 점검 세션이 코드 파일을 만지는 것 자체는 예외 경로다.
  일반화하면 — *정정이 코드 파일에 걸칠 때는 점검 세션이 직접 상환하되 그 사실을 문서에
  남긴다*(이 항목이 그 실행). 동작 변경을 동반하는 수정이었다면 claim이 옳았다.

---

## §5. 발화 트리거 (v1 §5 갱신 — 추가분만)

v1 §5 10건은 전건 승계. 아래 2건을 추가한다(기계로 관측 가능한 형태로).

| # | 유보 항목 | 발화 트리거 |
|---|---|---|
| ⑪ | `min_app_version` 실제 상향(§3-①) | `OPS-112` ②가 착지해 `/health/ready`가 미상 비율을 내고, 그 비율이 충분히 낮음이 관측된 뒤 **Kiki가 올린다**. 트리거의 기계적 정의 = "unknown 카운트를 읽을 수 있는 상태" |
| ⑫ | 접근성 화면 전수 편입·Semantics 전면 감사(§3-③④) | `A11Y-02`의 드리프트 가드가 착지해 **허용목록이 명시적으로 쌓인 뒤**, 그 목록 길이가 화면 집합 안정화 신호가 된다. 또는 시각약자 학생의 파일럿 참여(v1 §5-④ 승계) |

---

## §6. 잔여 갭 설계 (D6~D8 — v1 D1~D5에 번호 연속)

우선순위: **D7(버전 계약 관측) → D8(접근성 커버리지) → D6(정정 재유입 게이트)**.
D7이 앞선 이유는 파일럿(S3-01) 중 임계를 올려야 하는 상황이 실제로 올 수 있고, 그 순간에만
결함이 드러나기 때문이다.

### D6 — 제거↔정본 동기 게이트 → **`OPS-113-removed-dependency-canon-sync-gate`** (S3 · p3)

**갭**: G1. 정정 본문은 이 세션이 상환했으므로, 태스크가 소유하는 것은 **재유입 방지 기계**다.

**설계**:
- `tests/infra/test_removed_dependency_canon_sync.py` — `pubspec.yaml`의 *제거 사유 주석
  블록*에서 의존명을 **파싱해** 추출한다(하드코딩 목록 금지 — 주석이 단일 진실원천).
  그 이름이 `src/backend/**/*.py`·`docs/architecture|standards/**/*.md`에 **허용목록 밖**
  으로 등장하면 exit 1.
- 허용목록에는 "제거 이력·사고 경위를 서술하는 위치"만 **사유 주석과 함께** 등재
  (`pubspec_dependency_usage_governance_test.dart:114-122` 관용구 답습 — 근거 없는 포괄
  허용 금지).
- **`MOB-08`의 반대 방향 짝**: MOB-08은 *선언↔사용*(선언했는데 안 쓴다)을, 이것은
  *제거↔정본*(제거했는데 정본이 아직 쓴다고 말한다)을 잡는다.
- CI 배선 확인까지가 완료 조건("저장소에 존재함"과 "돌아감"은 다르다).
- **범위 밖**: TTS·STT·firebase 재도입 일체.

**변별력**: 정정한 문장 하나를 stale 표현으로 되돌리면 red, 다시 고치면 green(양방향).

### D7 — 버전 계약 관측·집행 완결 → **`OPS-112-client-version-gate-observability`** (S3 · p2)

**갭**: G2. 기존 계약을 바꾸지 않고 **관측면만** 채운다.

**설계**:
- **426 차단을 요청 회계 안으로** — early-return이 계측을 건너뛰는 현 구조를 고쳐, 차단도
  집계 대상이 되게 한다(전용 blocked 카운터 신설 또는 `_observe_request` 경유 — 착수
  세션이 택일하되 *"차단이 사라지지 않는다"* 가 계약).
- **3상태를 읽을 수 있게** — `/health/ready` body에 `client_version` 블록 추가. 기존
  `_ocr_reach_body`·`_segmentation_body` 좌석 관용구 답습(**새 엔드포인트 금지**).
  정상 / 미달(blocked) / 미상(unknown)이 **서로 다른 값**으로 나와야 한다.
- **클라 426 판정을 단일 좌석으로** — `api_client.dart`의 Dio 인터셉터 1곳
  (`auth_refresh_interceptor` 선례)에서 판정해 앱 전역이 같은 문구를 낸다. 7개 컨트롤러
  개별 수정이 아니다. `diagnosis_controller`의 기존 분기는 유지·정합(중복 처리 금지).
- **임계 상향 트리거 명문화** — 기본 `0.0.0`은 **유지**한다(fail-open이 옳다). 대신
  "언제·누가 올리는가"를 적는다(§5-⑪).
- **범위 밖**: 강제 업데이트 UI·스토어 링크·자동 업데이트·릴리스노트·롤백·Canary/
  Blue-Green·Crash 수집·서명·스토어 업로드.

**변별력(3상태 분리)**: 헤더 없는 요청 → unknown +1 / 임계 상향 후 구버전 요청 → blocked +1 /
임계 하향 → 정상 복귀. **세 값이 서로 다른 값**이어야 하며 같으면 검증 실패다.

### D8 — 접근성 커버리지 드리프트 가드 + 주 학습 화면 축 → **`A11Y-02-accessibility-coverage-drift-gate`** (S3 · p3)

**갭**: G3.

**설계**:
- **드리프트 가드** — `accessibility_test.dart`가 실제로 순회하는 대상 목록 ↔
  `lib/features/*/presentation/`의 화면 목록을 대조. 게이트에 없는 화면은 **사유 주석이
  붙은 허용목록**에 등재해야 통과. 목적은 *"지금 전부 검증"* 이 아니라
  **"새 화면이 조용히 늘지 않는다"**.
- **주 학습 화면 편입** — `chat_screen`·`problem_screen`. 06 §7이 지목한 *컨트롤러
  override 하네스*를 써서 **활성 문제·메시지가 있는 상태**를 만든다 — 빈 초기 상태만
  렌더하면 검증이 위장된다(변별력 없는 검증 스텝 금지).
- **`defect_report_button` 다이얼로그 축 추가** — v1 설계의 산출물이 게이트 밖으로 태어난
  것을 닫는다.
- **06 §7 표 갱신** — 남는 후속은 트리거 또는 태스크 중 하나를 갖게 한다(이번 세션이 표에
  이미 반영).
- **범위 밖**: Semantics 전면 감사·TTS·런타임 고대비/색약 토글·`accessibility_needs`
  분기·AAA. 목표 레벨은 `A11Y-01`의 **WCAG 2.1 AA** 승계.

**변별력**: 새 `*_screen.dart`를 추가하고 허용목록에 안 넣으면 red. 편입된 화면에서 고정
height 위젯을 배율 대상에 두면 red.

---

## §7. 반복 실수 — **11회차** (재발방지 등재)

v1 §6이 9회차까지, 운영 r3 §7이 10회차까지 확장한 표를 11회차로 잇는다.

| 회차 | 사례 | 형태 |
|---|---|---|
| 1~9 | (v1 §6 참조) | 만들고 미배선/미적재/미배포/미점화 · 선언만 · 기본값이 정책으로 · 정본이 현재로 |
| 10 | 런북 자인 공백 25종의 백로그 추적 0건(운영 r3 D9) | **정직 표기가 판정을 통과시키는 근거로 쓰임** |
| **11** | v1 §정정 9곳의 소유자 위임이 산문에만 있고 `acceptance`·`paths`에 없어 **6곳이 8일간 미집행**(G1) | **위임이 집행으로 읽힘** — 소유자를 *지정*하는 것과 그 태스크가 *판정면에 싣는* 것은 다르다. 두 태스크(`A11Y-01`·`OPS-18`) 모두 acceptance를 문자 그대로 충족했으므로 **정당하게 done**이었다 — 즉 사람의 부주의가 아니라 **인수인계 형식의 결함**이다 |

**공통 구조 갱신**: 10회차가 *"정직 표기 → 통과 근거"*, 11회차는 *"위임 선언 → 집행
증거"* 다. 둘 다 **문서가 스스로 적어 둔 미완성이 처분으로 이어지지 않는** 같은 계열이며,
공통 해법도 같다 — **미완성 항목은 반드시 ⑴ 소유 태스크의 기계 판정면(acceptance·paths)
또는 ⑵ 관측 가능한 발화 트리거 중 하나를 갖는다.** 이번 문서는 그것을 §3(공백마다 사유)·
§5(트리거)·§6(태스크)로 삼분해 적었고, `OPS-113`가 그중 문서 축을 기계화한다.

### CLAUDE.md 등재 (2회차이므로 규약상 의무) — **[2026-10-05 회수: main에 이식하지 않음 — 맨 위 회수 블록 ③]**

프로세스 금기에 1줄 추가 + 사고 경위 병기. 본문 규칙 변경이므로 **버전·수정일 표기도
함께 갱신**(0.2.1 → 0.2.2).

---

## §8. 실행 — 백로그 등재 · 중복 회피 대장

### 신규 등재 (ID는 `backlog.py add`가 배정 — 번호 추론 금지·HARN-10)

| 설계 | 태스크 | stage/prio |
|---|---|---|
| **D7** | `OPS-112-client-version-gate-observability` | S3 / 2 |
| **D8** | `A11Y-02-accessibility-coverage-drift-gate` | S3 / 3 |
| **D6** | `OPS-113-removed-dependency-canon-sync-gate` | S3 / 3 |

> **번호 가드 실동작 기록**: 최초 `OPS-33`으로 등재 시도 → CLI가 **원격 브랜치
> `claude/whymath-knowledge-design-4rxrax`의 `OPS-33-yaml-spec-unwired-audit-axis`와 충돌**을
> 잡고 `OPS-34`를 제안해 그대로 따랐다(HARN-15 교차 브랜치 스캔이 병렬 세션의 인플라이트
> 번호를 막은 2번째 기록 — 운영 r3에 이어).

### 이번 세션이 직접 집행한 것 (태스크 아님)

정정 9곳 — v1 §정정 6곳 + v1이 놓친 44dp 확대 3곳. 파일: `schema/speech.py` ·
`api/speech.py` · `05_interaction.md` · `system_deep_dive.md`(2곳) ·
`visualization_module_gap_review.md`(2곳) · `06_design_system.md`(TTS 행 + 후속 목록) ·
`CLAUDE.md:77` · `service_ops_mgmt_gap_review_2026-07.md:43` ·
`02_student_ui_master_plan.md`(2곳) · `01_student_pipeline_to_menus.md`.

### 중복 등재 금지 대장 (이번에 등재하지 **않는** 것과 그 소유자)

| 주제 | 기존 추적 |
|---|---|
| 결함 신고 **판독** 경로 | `RPT-02`(운영 r3 D11, todo) |
| `qa_pipeline` 축 9 상시 error | `ARCH-23`(운영 r3가 acceptance 보강) |
| backend 의존 선언↔사용 게이트 | `OPS-32` |
| 알림 마지막 1홉·백업 암호화 | `OPS-30`·`OPS-31` |
| CI 강제 상태 계약 | `OPS-29` |
| 결제·구독 실배선·tier quota | v1 §5-① 트리거 — **미등재가 의도** |
| CS 티켓·SLA·admin 콘솔 | v1 §2-⑤ + 운영 r3 §2-④ 트리거 대기 |
| 스토어·서명·iOS·Crash SaaS | `MGMT-02`(당시 blocked · 현재 todo+게이트) 선행 |
| 푸시 채널 전체 | v1 §5-③ Phase 3 M3.2 승계 |

### 재판정 트리거

91~95 전체의 재판정 시점 = **S3-01 파일럿 종료**(운영 공백의 실측 재평가) 또는 **결제 도입
결정**(v1 §5-①) 또는 **`MGMT-02` 해제**(v1 §5-⑥⑦) 중 먼저 오는 것. v1과 동일하다.

---

## 부록 — 실측 근거 (2026-08-11 · 브랜치 `claude/whymath-service-operations-review-5t5lmv` · 기반 HEAD `d088ae77`)

| 주장 | 확인 명령·위치 |
|---|---|
| v1 설계 5건 전건 done | `grep -H "^status:" backlog/tasks/{RPT-01,OPS-17,A11Y-01,OPS-18,MOB-08}-*.yaml` → 전부 `done` |
| 착지 커밋 실재 | `1d5c0df2`(RPT-01 #690) · `551f8e2e`(A11Y-01 #692) · `8810bc8b`(OPS-18 #693) · `b0ad24a6`(MOB-08 #694) |
| 신고 API 실제 경로 | `api/reports.py:34` prefix `/v1/reports` + `:55-56` `@router.post("/defects")` (v1 `:177`의 `/v1/defect-reports`는 오기) |
| qa_pipeline 9축 | `grep -n "def _axis_" harness/qa_pipeline.py` → 9건, 축 9 = `_axis_defect_report_intake:547` |
| **426이 계측 이전 early-return** | `app.py:823-827`(JSONResponse 반환) vs `:831` `started = time.monotonic()` · `:837` `_observe_request` |
| **미상 카운터 프로덕션 리더 0** | `grep -rn "app_version_unknown_count\|_VERSION_UNKNOWN_COUNT_KEY" src/ tests/ scripts/` → src는 정의·증가만(`app.py:182,718,776-777`), 읽기는 `tests/backend/test_app.py:687,690`뿐 |
| `/health/ready`에 유사 좌석 존재 | `app.py` `_ocr_reach_body`·`_segmentation_body`·`get_growth_evidence_counters` 소비(`:874-908`) — 버전 축만 없음 |
| 클라 426 분기 1/7 | `grep -rn "426" src/mobile/lib/` → `diagnosis_controller.dart:20,22,70` 3히트뿐. 다른 6 컨트롤러는 generic `catch`(예: `chat_controller.dart:231,276`) |
| 임계 영구 무력 | `config.py:1177` `default="0.0.0"` |
| a11y 대상 5개 vs 화면 16개 | `grep -oE "[A-Z][A-Za-z]+Screen\|[A-Z][A-Za-z]+Card\|SceneRenderer" src/mobile/test/accessibility_test.dart \| sort -u` → 5 / `ls src/mobile/lib/features/*/presentation/*.dart \| wc -l` → 16 (`*_screen.dart`만 10) |
| 접근성 추적 태스크 0건 | `grep -rln "접근성\|accessibility" backlog/tasks/` → `A11Y-01`(done)·`MATH-05`(무관) 2건뿐 |
| 06 §7 자인 후속 | `docs/design/ui/06_design_system.md` §7 표 아래 "→ **후속**" 줄(이번 세션이 소유자·트리거 병기로 개정) |
| §정정 미집행 6곳 | 정정 전 `grep -rn "flutter_tts" src/ docs/ \| grep -v pubspec` → 6히트(전부 "합성만 한다" 단정형) · `grep -rn "44×44" docs/` → `system_deep_dive.md:103` |
| **44dp 확대 3곳(v1 미인지)** | `grep -rn "44dp" docs/design/ui/` → `02_student_ui_master_plan.md:39,46` · `01_student_pipeline_to_menus.md:105` |
| 스트릭 여전히 미채택 | `grep -rn "consecutive_active_days" src/` → `schema/user.py:461`·`db/models/user.py:324`·alembic 1건 — writer·reader 0 |
| 알림 채널 여전히 0 | `grep -rlni "notification\|push_token\|device_token" src/backend/whymath_backend/ --include=*.py` → 0건 |
| `MGMT-02` blocked | `grep "^status:" backlog/tasks/MGMT-02-*.yaml` → `blocked` |
| firebase 제거 확인 | `grep -n "firebase" src/mobile/pubspec.yaml` → `:50-52` 제거 사유 주석만(선언 0) |
| 번호 충돌 가드 실동작 | `backlog.py add --id OPS-33-...` → `❌ 태스크 ID 번호 충돌: 'OPS-33' … 다음 빈 번호 제안: OPS-34` |
| 등재 후 대장 무결성 | `python3 scripts/harness/backlog.py validate; echo "EXIT=$?"` → `태스크 258건, 게이트 10건` · `EXIT=0` |
| 회귀 없음(전체 스위트) | `src/backend`에서 **bare** `python3.12 -m pytest`(CI와 동일 invocation) → **9412 passed · 304 skipped · `EXIT=0`**. lint는 CI 동일 명령·동일 대상 — `ruff check . ../../tests/backend`(`EXIT=0`) · `black --check --line-length 100 . ../../tests/backend`(`EXIT=0`). `tests/infra` 298 passed(`EXIT=0`) |

### 검증 과정에서 겪은 실행 함정 2건 (다음 세션용 기록 — 결과가 아니라 *도구 사용*의 문제였다)

| 함정 | 증상 | 원인·해법 |
|---|---|---|
| **명시 경로 invocation → asyncio strict 폴백** | `pytest ../../tests/backend`로 돌리자 **635 failed**. 실패 메시지는 *"async def functions are not natively supported"* | `src/backend/pyproject.toml:205` `asyncio_mode = "auto"`가 **명시 테스트 경로 인자**에서 적용되지 않는 알려진 형태(같은 파일 `:97-100`이 ARCH-22 재검증 때 이미 기록해 둔 현상). CI는 **bare `pytest`**(testpaths 사용)라 영향 없다. **해법 = 대상 경로를 인자로 주지 말 것**. 이 635건은 코드 결함이 아니라 **내 호출 방식의 결함**이었다 — CLAUDE.md "CI가 실제로 쓰는 명령을 그대로 재현한다"의 실사례 |
| **sibling 패키지 미설치 → collection error** | bare 재실행 시 `7 errors during collection` · `ModuleNotFoundError: No module named 'data_pipeline'` | 이 컨테이너는 `src/backend`만 설치돼 있었다. CI는 backend·data-pipeline 둘 다 설치한다 → `pip install -e src/data-pipeline` 후 green. 부수 사항: 컨테이너 기본 `python3`은 **3.11**인데 프로젝트는 `>=3.12` 요구라 `python3.12`로 설치·실행해야 한다 |

**두 함정의 공통점**: 둘 다 **"실패처럼 보이는 환경 아티팩트"** 였고, 둘 다 *추정하지 않고 원인을 실측해* 판별했다(전자는 실패 메시지 전문 확인, 후자는 의존 설치 후 재판정). 만약 첫 결과를 그대로 "회귀 발생"으로 보고했다면 존재하지 않는 결함을 8시간 추적했을 것이다.

---

**버전**: 1.0 | **작성**: 2026-08-11 | **교차링크**:
[v1](../architecture/service_operations_gap_review.md) · [운영 EOS r3](../architecture/operations_module_gap_review_r3.md) ·
[운영 플랫폼](../architecture/operations_platform_gap_review.md) · [게임화 r2](../architecture/gamification_module_gap_review_r2.md) ·
`../design/ui/06_design_system.md` · `../standards/coding_flutter.md` ·
`../reviews/service_ops_mgmt_gap_review_2026-07.md`
