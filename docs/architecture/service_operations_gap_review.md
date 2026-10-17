# 서비스 운영(Service Operations) 모듈 — 외부 EOS 틀 대조 갭 점검·설계 (2026-08-03)

> **⚠️ 후속 문서 있음 — 이 문서는 v1(2026-08-03)이며 본문은 소급 수정하지 않는다**
> (완료 태스크 `RPT-01`·`OPS-17`·`A11Y-01`·`OPS-18`·`MOB-08`의 판정 근거 원본이기 때문).
> 현행 판정은 **[`service_operations_gap_review_r2.md`](../reviews/service_operations_gap_review_r2.md)**
> (2026-08-11, 2차 델타 재점검)를 읽는다 — v1 설계 D1~D5는 **전건 착지 확인**됐고, r2는
> ⑴ v1 §정정 9곳 중 **6곳이 미집행**이라는 사실 ⑵ 버전 계약(OPS-17)의 관측 반쪽
> ⑶ 접근성 커버리지 드리프트를 다룬다.
>
> **본문 오기 1건 정정(r2 실측)**: 아래 §3 D1 착지 정정 블록(`:177` 부근)이 API 경로를
> `POST /v1/defect-reports`로 적었으나 **실제 착지 경로는 `POST /v1/reports/defects`**
> (`api/reports.py` prefix `/v1/reports` + `@router.post("/defects")`)다.

> **범위**: 외부 참고 문서 『22. 서비스 운영』(핵심 모듈 91~95: 결제·구독·환불 · 접근성
> (Accessibility) · 푸시 알림 인프라 · 고객지원(CS)·오류 신고 · 앱 배포·업데이트 관리 —
> **WhyMath 전용이 아닌 일반적 EOS 틀**, Kiki 제공)을 현 코드베이스와 대조해 빠진 부분을
> 점검하고, 진짜 갭을 WhyMath 불변식(1인 capacity 가드·소비처 없는 설계 금지·교수학 금기
> [게임화·중독성 설계 금지]·검증 권위 서열·법령 유래 절차의 기계 대체 금지·dead code 금기·
> 이중 진실원천 금지) 안에서 설계한 기록.
> **형식**: `operations_module_gap_review.md`(모듈 42~50, 2026-07-29)·`ai_recommendation_
> module_gap_review.md`(기능 80~83, 2026-08-01, 최신 판정기호 규약) 답습 — 같은 외부 EOS
> 틀 대조 시리즈(모듈 6~10 → 18~22 → 23~27 → 37~41 → 42~50 → 46~53 → 58~68 → 62~65 →
> 66~69 → 80~83)의 **11번째** 자매편.
> **결론**: 91(결제)·93(푸시 채널)·CS 도구는 `service_ops_mgmt_gap_review_2026-07.md`가
> 이미 "의도된 지연·백로그 오염 방지 미등재"로 판정했고 이번 대조로 재확인했다 — 단,
> **91의 진짜 갭은 결제가 아니라 클라우드 승급 사슬의 학생 도달 관측 부재(D3)**이고, **93의
> firebase 의존 2종은 선언만 있고 아무 층도 없어 제거 대상(D5)**이다. 이 검토가 다루지
> 않은 두 축이 이번 대조의 핵심이다 — **94의 학생 오류신고 경로가 완전히 부재**(최대 갭,
> D1)하고, **95의 클라이언트(Flutter) 축은 자기 버전을 서버에 알리지 않는다**(D4). 92는
> Flutter 접근성 회귀 게이트가 이미 도는데 **목표 레벨 선언·배율 축·시각화 라벨**이 빠졌다
> (D2). 의도적 미채택 13건·정직한 공백 13종·발화 트리거 10건·반복 실수 3회차 신규(7~9회차).

관련 정본: `docs/reviews/service_ops_mgmt_gap_review_2026-07.md`(2026-07-26, 서비스·운영·
관리 3축 검토 — `OPS-01~04`·`MGMT-01/02` 등재, 이번 문서가 그 후속·재확인) ·
`docs/architecture/operations_module_gap_review.md`(모듈 42~50, `ARCH-20`·`ARCH-21`) ·
`docs/architecture/account_security_gap_review.md`(계정·보안, `SEC-07~12`) ·
`docs/architecture/ai_recommendation_module_gap_review.md`(§6 반복 실수 1~6회차 — 이 문서가
7~9회차로 확장) · `ROADMAP.md`(Phase 배치) · `MEMORY.md` 결정 로그(2026-08-03).

---

## §0. 선결 — 실측 정정 3건 + 확대 2건

착수 전 조사(Explore 2건 병렬 + Plan 설계 1건, 전건 grep·파일:줄 spot-check 재검증)에서
초기 가설이 부정확했던 지점을 먼저 고정한다. 틀린 전제 위에 D를 세우면 다음 세션이 없는
것을 만든다.

| # | 초기 가설 | 실측 결과 | 스코프 영향 |
|---|---|---|---|
| 정정① | "시각화 대체텍스트(alt text) 필드 자체가 없다" | **`caption: str \| None`이 이미 있다**(`schema/visualization.py:176`) — Flutter도 소비 중(`src/mobile/lib/features/chat/presentation/scene_renderer.dart:163-164`, 폴백 `'인터랙티브 시각화'`). 진짜 문제는 부재가 아니라 ⑴ `Optional`이라 강제되지 않음 ⑵ 프롬프트가 요청만 하고 스키마가 강제 안 함(`l3/visualization.py:88`) ⑶ `Semantics` 위젯에 부착 안 됨 | "필드 신설"에서 "부착·보장"으로 스코프가 1/10로 축소(D2) |
| 정정② | "MOB-13/14 접근성 패스로 이미 착지" | MOB-13/14는 **백로그 태스크가 아니다** — `backlog/tasks/`엔 MOB-01~07만 있고, 13/14는 `MEMORY.md:1689,1697`의 Kiki 지시 즉시작업 기록(코드는 실재, 태스크 추적만 없음) | 신규 `A11Y-` 태스크가 기존 태스크와 중복되지 않음 확정 |
| 정정③ | "Flutter 런타임 접근성 대응이 전무하다" | 토글은 0이 맞다. 그러나 `fontSize:` 리터럴·고정 `TextScaler` 오버라이드가 코드 전수에 무일치 — 즉 앱은 **OS 글자크기 확대를 구조적으로 이미 존중**한다. 없는 것은 "대응"이 아니라 **그 대응이 깨지지 않는다는 회귀 증거** | "토글 신설"(YAGNI)이 아니라 "배율 회귀 게이트"로 D2 성격이 바뀜 |
| 확대① | "91: `student_subscription` 하드코딩 → 라우팅 가드 단절" | **가드는 4겹이고 구독은 그중 둘째다.** ⑴ `budget_krw` 기본 `0.0`, 학생 경로 생산자 0(`ops/cost_probe.py`·`ops/live_preflight.py` 2개 CLI뿐) → `l3/router.py:536`의 **규칙1이 구독 규칙(:539)보다 먼저** LOCAL 강등 ⑵ 구독 하드코딩(6곳 전부 `"free"`) ⑶ `next_tier()`(`:443`) 프로덕션 호출자 0 ⑷ 코치가 `difficulty="medium"` 고정(`harness/wh1_llm_policy.py:148`)이라 규칙3(killer→CLOUD_HIGH)의 발동 조건 자체가 미성립 | 구독만 배선하면 before/after가 **바이트 동일** — D의 대상이 "구독 배선"에서 "승급 사슬 도달 관측"으로 이동(D3) |
| 확대② | "94: 신고 경로 0" | 맞다. 더해 **결함 큐 자산은 이미 있다** — `harness/needs_review_worklist.py`("근거만 모으고 판정하지 않는다" 계약), `harness/qa_pipeline.py`(ARCH-21, 기존 7축 조립 — corpus_audit·equivalence_canonicalize·concept_graph_reachability·misconception_crosslink_demotion·coach_prose_leak·content_provenance·defect_injection_demotion) | 신규 채널 하나가 **기존 7축과 별개로** 합류하는 8번째 입력이 됨(D1 스코프 확정) |

---

## §1. 모듈 91~95 ↔ WhyMath crosswalk 판정

판정 기호: ✅ 충족·초과 / △ 부분(부품은 있는데 배선·목표·정본이 없음) / ⚠️ 진짜 갭 → D /
⏸ 기존 태스크·선행 판정 승계(중복 등재 금지) / 🚫 의도적 미채택 → §2.

### 모듈 91. 결제·구독·환불 — **결제 자체는 선행 지연, 진짜 갭은 라우팅 가드 도달 0**

| 문서 항목 | WhyMath 현행 | 판정 |
|---|---|---|
| 결제(카드·간편결제·계좌이체·법인·해외·세금계산서) | 라우터·PG 연동·정산 코드 전수 무일치. `scripts/setup.sh:85-87`에 `TOSS_CLIENT_KEY`/`TOSS_SECRET_KEY` 자리표시자만(대응 `config.py` Settings 필드 없음) | 🚫 §2-① |
| 구독 관리(무료·개인프리미엄·가족·학교·학원·교육청·기업) | `SubscriptionTier`(free/basic/premium, `schema/enums.py:784-789`) + `UserProfile.subscription_tier/_started_at/_renewed_at`(`schema/user.py:259-271`) + `Problem.is_premium`(`schema/problem.py:571`) 필드 실재, DDL 반영. **다층 플랜(가족·학교·학원·교육청·기업)은 조직 테넌시 모델 자체가 0** | △ (필드만) → 🚫 §2-② (다층화) |
| 환불·쿠폰·프로모션·추천인·매출Dashboard·정산리포트 | 전수 grep(`refund\|환불\|coupon\|쿠폰\|toss\|정산\|settlement`) 무일치, DDL 28테이블 중 결제 관련 테이블 0건, 백로그 153건 무일치 | 🚫 §2-① |
| **구독 등급의 실제 소비처(클라우드 LLM 라우팅 가드)** | `l3/router.py:294-307`(`guard_cloud`)·`:530-548`(승급 규칙 1~6)가 `RoutingRequest.student_subscription`·`budget_krw`로 **실제 판정을 집행**한다. 그런데 호출부 6곳(`api/visualization.py:55`·`api/scene.py:54`·`l4/misconception/judge_seam.py:47,55`·`l3/cross_verify.py:375`·`l3/equivalent/{llm_generator,rephrase}.py`)이 전부 `"free"` 리터럴 — **DB의 `subscription_tier`를 읽는 런타임 코드 0건.** `next_tier()`(:443)도 프로덕션 호출자 0 | 🔴 **최대 갭 → D3** |
| 사용량 제한(요금제별 quota) | `api/_rate_limit.py`는 성숙(sliding window·Redis·Lua 원자성)하나 키가 user/IP/device뿐 — **tier 무관**. `ops/cost_probe.py`는 사후 측정만(런타임 상한 강제 없음, 이미 `service_ops_mgmt_gap_review_2026-07.md:26`가 판정) | 🚫 §4-③ (결제 하류) |

**91 종합**: 문서가 기대하는 "결제 시스템"은 애초 이 단계의 과제가 아니다(선행 판정 승계).
그러나 결제와 무관하게 **이미 배선된 비용·품질 가드가 학생 트래픽에 한 번도 도달하지
않는다는 사실 자체가 안 보인다** — 이것이 진짜 갭이다.

### 모듈 92. 접근성 (Accessibility) — **회귀 게이트는 도는데 목표·배율·시각화 라벨이 없다**

| 문서 항목 | WhyMath 현행 | 판정 |
|---|---|---|
| 시각 접근성(스크린리더·대체텍스트·고대비·글자크기·색약·확대) | 대비 4.5:1·탭영역 48dp guideline 테스트(`src/mobile/test/accessibility_test.dart`, explore/home/me + `SceneRenderer`/`CoachSignalCard` 라이트·다크) 실재·통과 중. 색만으로 정보 전달 금지 🟢(`CoachEmphasisText`). **글자크기 배율 축·고대비 토글·색약 팔레트는 런타임 대응 0**(`textScale\|TextScaler\|highContrast\|colorblind` 전수 무일치) | △ (대비·탭만) → 배율은 **D2**, 토글은 🚫 §2-⑧ |
| 청각 접근성(자막·음성안내·수어) | 백엔드 `SpeechSpec`(`api/speech.py POST /v1/speech/latex`·`l3/speech.py`·결정론 규칙엔진·70테스트) **완비**. 클라 소비 0 — 유일 경로였던 `flutter_tts`가 Gradle 비호환 실측으로 **의도적 제거**됨(`src/mobile/pubspec.yaml:42-45`) | ⏸ (도달 유보 — §정정 필요) |
| 운동 접근성(키보드전용·포커스·터치확대·음성입력) | 터치영역 48dp는 시각 항목과 동일 게이트로 겸함. 키보드전용·포커스이동·음성입력(STT)은 자산 0 | 🚫 §2-⑩ |
| 인지 접근성(쉬운언어·집중모드·애니메이션감소·단계별안내·개인맞춤UI) | `accessibility_needs: list[Accessibility]`(5종: 시각약자·색약·큰글씨·음성안내·시간연장, `schema/user.py:289`) 필드 실재·`api/users.py:81` PATCH 화이트리스트 등재. **그러나 Flutter 온보딩이 이 필드를 수집·전송하지 않는다**(writer 0) — 소비 분기를 만들어도 항상 빈 배열 위에서 돈다 | 🚫 §2-⑧ |
| 표준 준수(WCAG 2.2·모바일접근성·교육기관기준) | **목표 레벨을 선언한 문서가 없다.** `docs/standards/coding_flutter.md:76`이 "접근성 100%"라 쓰지만 측정 근거 없음. `05_interaction.md:46`(44dp)과 `06_design_system.md` §7(48dp, 실 게이트 값)이 **서로 다른 값**을 말함(이중 진실원천) | ⚠️ **D2** |

**92 종합**: 시리즈 문서 대부분과 달리 이 모듈은 "부품이 없다"가 아니라 **"부품은 도는데
기준선이 선언된 적이 없다"**. 문서가 요구하는 것 중 실제로 지금 정당한 것은 배율·라벨·
목표 선언 3종뿐이고, 나머지는 소비처(writer) 자체가 없거나 자산 밖이다.

### 모듈 93. 푸시 알림 인프라 — **채널은 선례대로 지연, 의존 선언은 제거 대상, 스트릭은 영구 금지**

| 문서 항목 | WhyMath 현행 | 판정 |
|---|---|---|
| 학습 알림(복습·과제·시험일정·학습목표) | 채널 자체가 0 | ⏸ 선행 판정 승계(Phase 3 M3.2) |
| **학습 알림 — Streak 유지** | `consecutive_active_days`(`schema/user.py:461`) 필드 존재하나 **writer·reader 0**. 알림으로 배달되면 CLAUDE.md·`system_deep_dive.md:103`·`06_design_system.md` §6이 3중으로 금지하는 **게이미피케이션(스트릭)**의 가장 중독적인 형태(앱 밖 손실회피 자극) | 🚫 **§2-③ 영구 미채택** (지연이 아님) |
| 학습 알림 — AI추천 | 추천 엔진 자체가 콜드스타트(θ=0, `ai_recommendation_module_gap_review.md` D1)라 추천할 것이 없는 상태에서 알림은 거짓 신호 | ⏸ §5-② (REC-01 도달 관측 후) |
| 운영 알림(공지·이벤트·점검·라이선스만료·결제완료) | 결제·라이선스 자체가 미도입 | ⏸ 승계 |
| 알림 채널(앱Push·이메일·SMS·웹·카카오알림톡) | `firebase_messaging ^15.0.0`·`firebase_core ^3.0.0`이 `pubspec.yaml:48-50`에 **선언만** — Dart/Kotlin 사용처 0, `google-services.json` 0, gradle 플러그인 미적용, **`ios/` 디렉터리 자체 부재**. 이메일/SMS/알림톡 코드 0(`email_hash`만 보유, 평문 연락처 미수집) | ⚠️ **D5 (제거)** |
| 시스템 기능(예약발송·대상그룹·개인화·통계·재시도) | 채널이 없어 대상 없음 | 🚫 §2-④ |

**93 종합**: "만들었는데 켜지 않음"이 아니라 **"아무 층도 없는데 의존성 목록만 켜져
있다"** — 이 시리즈 §6의 뒤집힌 형태(7회차, 아래 §6).

### 모듈 94. 고객지원(CS)·오류 신고 — **최대 갭. 학생 결함 신고 경로가 전 층에서 0**

| 문서 항목 | WhyMath 현행 | 판정 |
|---|---|---|
| 문의 접수(1:1·FAQ·AI챗봇·분류·첨부) | 전무 | 🚫 §2-⑤⑥ |
| **오류 신고(앱·콘텐츠·AI응답·수식·오답·UI)** | 라우터 16종·DDL 28테이블 전수 확인 — report/feedback/inquiry 표면 **0건**. `api/interactions.py`(`/v1/interactions`)는 시각화 조작 이벤트 수집일 뿐 오류 신고와 무관. `schema/problem.py:494` `feedback_id`는 외부 카탈로그 느슨참조(학생 신고와 무관) | 🔴 **최대 갭 → D1** |
| 처리 관리(티켓·배정·우선순위·SLA·이력) | 전무 | 🚫 §2-⑤ |
| 분석 기능(유형통계·반복오류·만족도·CS Dashboard) | 관측 인프라 자체는 성숙(`ops/service_health.py` 5xx·p95 breach 알림, `ops/log_scrubber.py` PII 스크러버, Langfuse) — 그러나 **입력이 학생 결함이 아니라 인프라 지표**. OpenTelemetry는 `pyproject.toml` 의존 선언만(계측 0). 모바일 Sentry는 `env.dart:16` `sentryDsn` 상수 선언만(패키지 미포함·초기화 0) | △ (인프라 관측만) → 🚫 §4-⑥⑦ |

**94 종합**: CLAUDE.md "❌ 환각 발견 시 조용히 넘어가지 말고 로그·수정"과 초인간 검증
기준("인간 검수도 하나의 검출기다")은 **실사용 중 발견분을 받는 채널**을 전제한다. 그
채널이 0이면 이 원칙은 생성 시점에만 집행되고 사용 시점엔 집행 불가능하다.

### 모듈 95. 앱 배포·업데이트 관리 — **백엔드는 초과 충족, 클라 축은 자기 버전을 말하지 않는다**

| 문서 항목 | WhyMath 현행 | 판정 |
|---|---|---|
| 배포 관리(웹·Android·iOS·Desktop·내부테스트) | 백엔드: `.github/workflows/deploy.yml`(수동승인·`preflight`가 `latest` 태그 거부·환경 승인 게이트·배포 후 `/health/ready` 검증)·`deployment_cd_runbook.md`(25KB, 롤백 3단계)·CI 14잡 — 틀보다 엄격(OPS-03 done). **앱**: `mobile` 잡은 `analyze`·`test`만(빌드 산출물 0), `signingConfig = signingConfigs.debug`, **`ios/` 자체 부재** | ✅ (백엔드) / ⚠️ **D4 여지** (앱) |
| 버전 관리(이력·릴리스노트·자동/강제 업데이트·롤백) | 백엔드 롤백=이전 `image_tag` 재배포(성숙). **클라 최소버전 체크·강제 업데이트 API 전수 무일치**(`force.?update\|min.?version` grep). `pubspec.yaml:4` `version: 0.1.0+1` 수동, `applicationId` "잠정"(build.gradle 주석 명기) | 🔴 **최대 갭(클라 축) → D4** |
| 운영 기능(Canary·Blue-Green·A/B·FeatureFlag·롤링) | 전용 프레임워크 없이 `config.py` Settings 불리언 18종(`wh1_primary_enabled` 등) + shadow→canary→full 규율로 **이미 다른 형태로 실현** | ✅ (대체 실현) → 🚫 §2-⑪ |
| 모니터링(Crash분석·업데이트성공률·버전별오류율·채택률·배포Dashboard) | 백엔드 서비스 헬스는 성숙(OPS-01). **Crash 수집(Sentry/Crashlytics) 0**, 버전별 오류율·채택률 계상 0(애초 클라 버전이 서버에 안 옴) | 🚫 §2-⑫ / D4의 부속 |

**95 종합**: 서버는 CD로 매 커밋 갱신되는데, 파일럿 태블릿에 사이드로드된 앱은 그 갱신과
무관하게 고정된다. API 계약이 바뀌어도 구버전 앱은 이를 감지하지 못하고 단일 실패
문구(`diagnosis_controller.dart:66` `'문제를 불러오지 못했어요...'`)로 위장한다 —
2026-07-20 인증 누락 사고와 **동일한 구조**의 위험이다.

### 판정 분포 요약

| 모듈 | ✅ | △ | ⚠️→D | ⏸ | 🚫 | 최대 갭 |
|---|---|---|---|---|---|---|
| 91 결제·구독·환불 | 0 | 3 | **1 (D3)** | 0 | 다수 | 승급 사슬 도달 0 |
| 92 접근성 | 3 | 2 | **1 (D2)** | 1 | 다수 | 목표 미선언 + 배율 무방비 |
| 93 푸시 알림 | 0 | 0 | **1 (D5)** | 3 | 다수(**스트릭 영구**) | 선언-only 의존 |
| 94 CS·오류신고 | 0 | 1 | **1 (D1)** | 0 | 다수 | **학생 결함 신고 경로 0** |
| 95 배포·업데이트 | 2(백엔드) | 0 | **1 (D4)** | 0 | 다수 | 클라 버전 미상 |

**한 줄 결론**: 백엔드 운영(CD·백업·SLO·관측)은 틀을 초과 충족한다. 비어 있는 것은 전부
**클라이언트 쪽 운영 축**과 **학생→시스템 역방향 채널**이다 — 앱은 자기 버전을 말하지
않고, 학생은 결함을 말할 곳이 없으며, 접근성 목표는 선언된 적이 없다. 그리고 91·93은
"없다"가 아니라 **"있다고 읽히는데 도달이 0"**이라는 이 시리즈의 반복 형태다(§6).

---

## §2. 의도적 미채택 판정 (협상 불가 근거)

| # | 틀 제안 | 불채택 근거 |
|---|---|---|
| ① | 결제·PG·환불·쿠폰·정산 일체(91) | **선행 판정 승계** — `docs/reviews/service_ops_mgmt_gap_review_2026-07.md:25,76`("의도된 지연 Phase 2 M2.3"·**백로그 오염 방지로 의식적 미등재**) + `ROADMAP.md:119`("❌ 결제 시스템 = Phase 1.5 또는 2"). 재설계·재등재 금지 |
| ② | 플랜 다층화(가족·학교·학원·교육청·기업)(91) | 조직(학교·학원·반) 테넌시 모델 0 — `account_security_gap_review.md`가 Phase 3~4로 기판정. 요금제가 제품 정체성보다 앞설 수 없다(1인 capacity 가드) |
| ③ | Streak 유지 푸시·랭킹·보상 알림(93) | **영구 미채택.** `CLAUDE.md`"❌ 무자비한 게임화·중독성 설계"·"❌ 학습 시간·정답률만으로 우열을 매기는 게임화 금지" + `docs/architecture/system_deep_dive.md:103`("게이미피케이션[정답률 랭킹·**스트릭**]을 금지") + `docs/design/ui/06_design_system.md` §6(게이미피케이션 금지 — 랭킹·스트릭·카운트다운·보상 연출 없음) 3정본 독립 금지. `consecutive_active_days`는 writer·reader 0인 좌석일 뿐(§2-⑧과 동형: 컬럼이 있다는 것이 채워야 한다는 뜻은 아니다) |
| ④ | SMS·카카오알림톡·이메일 발송 채널(93) | 현행은 `email_hash`만 보유(평문 연락처 0, `api/users.py:62` `_PII_EXCLUDE`). 발송 채널은 새 미성년 PII 수집을 강제한다 — 개인정보 최소화 역행 |
| ⑤ | CS 티켓·배정·우선순위·SLA·상담 이력(94) | **1인 capacity 가드** — `operations_module_gap_review.md` §2-④ 승계("운영자 1인·β 소규모는 DB 직접 조회로 감내"). 티켓 시스템은 응대 인력이 존재할 때의 도구 |
| ⑥ | AI 챗봇 상담(94) | `CLAUDE.md` "❌ LLM 응답을 검증 없이 학생에게 제공 금지 — PRM 또는 도구 검증 필수". 수학 코칭(WH-1)은 PRM·도구검증을 통과하는데 CS 챗봇엔 그 축이 없다 — 검증된 발화와 미검증 발화를 같은 앱에서 섞지 않는다 |
| ⑦ | 만족도·NPS 조사(94) | 정서 라벨 수집 — `ai_recommendation_module_gap_review.md` §2("측정 근거 없이 정서·피로 라벨을 붙이는 설계는 열지 않는다")와 인접 논리 승계 |
| ⑧ | `accessibility_needs` 기반 개인맞춤 UI 분기(92) | **소비처 없는 설계 금지의 역방향** — 필드는 있으나 **writer가 0**이다(Flutter 온보딩이 수집·전송 안 함). 분기를 만들면 항상 빈 배열 위에서 도는 dead 경로. 먼저 필요한 건 분기가 아니라 OS 접근성 설정 존중(D2) |
| ⑨ | WCAG 2.2 AAA·전면 준수 선언(92) | 목표는 **AA**다(현행 게이트 대비 4.5:1이 이미 AA 값). 수식·그래프가 많은 콘텐츠는 AAA 달성 불가 구간이 있어 선언 자체가 거짓이 된다 — `docs/standards/coding_flutter.md:76` "접근성 100%"가 이미 그 형태(§정정 5) |
| ⑩ | 수어·음성입력(STT)·집중모드(92) | 수어는 촬영·코퍼스 자산 전제(capacity 밖). STT는 `speech_to_text` 제거 사유(Gradle 비호환 실측, `pubspec.yaml:42-45`) 승계 |
| ⑪ | Canary·Blue-Green·A/B·롤링 인프라(95) | **다른 형태로 이미 실현** — 트래픽 분할 장치 없이 `config.py` Settings 불리언 18종 + shadow→canary→full 규율로 운영 중. 대상 인스턴스가 1개인데 트래픽 분할 인프라를 넣는 것은 truth source 이중화 |
| ⑫ | Crash 수집 SaaS(Sentry/Crashlytics)(95) | 미성년 앱에 제3자 SDK 추가는 `MGMT-02`(약관·개인정보처리방침 문안) 사실관계를 바꾼다 — 문안 확정 전 도입 금지 |
| ⑬ | 스토어 배포·서명·심사·iOS(95) | **미채택이 아니라 법적 선행 미충족.** 스토어 심사는 이용약관·개인정보처리방침 URL이 필수 제출물인데 `MGMT-02`가 **blocked**다. "법령 유래 절차의 기계 대체 금지" — 순서를 뒤집을 수 없다 → §5-⑥ |

---

## §3. 설계 D1~D5 (진짜 갭의 WhyMath 정합 설계)

우선순위: **D1(학생 결함 신고) → D4(클라 버전 계약) → D2(접근성 목표) → D3(승급 관측) →
D5(firebase 제거)**. D1·D4는 파일럿(S3-01, 학생 5~10명) 전 안전망이라 stage S3·priority 2.

### D1. 학생 결함 신고 채널 (신규 `RPT-` 접두어)

**갭**: 학생이 문항·AI응답·수식 오류를 신고할 경로가 스키마·API·UI 어디에도 없다(§1 모듈
94). 파일럿에서 실학생이 만나는 결함은 기계 게이트(생성 시점 40여 종)가 구조적으로 볼 수
없는 표본이고, 그 신호를 받을 채널이 없으면 CLAUDE.md "환각 발견 시 조용히 넘어가지 말고
로그·수정"은 사용 시점에 집행 불가능하다. 희소한 파일럿 코호트가 만든 결함 신호를 못
받으면 파일럿의 최대 산출물이 증발한다.

**dead code인가?** 아니다 — 기준은 "지금 데이터가 있는가"가 아니라 "입력이 도착할 때
받을 좌석이 있는가"다(OPS-01/02도 착수 시점엔 데이터가 없었다). 소비처도 이미 존재한다:
`harness/needs_review_worklist.py`("근거만 모으고 판정하지 않는다" 계약)·`harness/
qa_pipeline.py`(ARCH-21, 기존 축과 별개로 합류하는 추가 입력).

> **착지 정정(2026-08-04)**: D1은 `RPT-01`로 구현돼 착지했다(append-only `defect_report`
> 테이블 + `POST /v1/defect-reports` + Flutter 신고 버튼 + qa_pipeline 축). 이 문서가
> 집필 시점에 "기존 7축 → 8번째 입력"이라 적었으나, **같은 날 ARCH-24가 `banned_words_pii`
> 를 축 8로 먼저 착지시켜** 실제 슬롯은 **축 9(`defect_report_intake`)**가 됐다. 두 축은
> 판정 로직이 서로 독립이라 양쪽 모두 유지하고 번호만 재배정했다 — 현재 qa_pipeline은
> **9개 축**을 조립한다. 축 9는 코퍼스 파일이 아니라 DB를 읽는 유일한 축이며,
> "수집 경로 미배선"(테이블 없음 → `no_snapshot`)·"0건 접수"(`ok`+count=0)·"DB 미도달"
> (`error`+예외 타입명)을 서로 다른 값으로 낸다(이중 회계).

**일반 CS와의 경계(판별 기준 한 줄: "학생에게 답을 돌려주는가?")**:

| 만드는 것(결함 수집) | 만들지 않는 것(CS 운영) |
|---|---|
| 카테고리 enum(≤6, 콘텐츠오류/AI응답오류/수식오류/오답의심/UI문제/기타) + 대상 참조 1건 | 자유서술·첨부 이미지·1:1 문의 스레드 |
| append-only 1행 | 티켓 상태전이·배정·우선순위·SLA·상담 이력 |
| CLI 리포트(유형별 집계, `qa_pipeline` 합류) | CS Dashboard·만족도/NPS·회신 이메일 |
| — | AI 챗봇 상담 |

**설계**:
- **저장 위치**: `db/models/audit.py`의 `DeletionAudit`/`PrivacyAudit` append-only 패턴
  답습(plain UUID·`String(32)` 태그·UPDATE/DELETE 라우터 없음). `attempt_event`는
  **재사용하지 않는다** — `privacy/retention.py:50`이 이를 보존 파기 대상(3년)에 넣어
  두었는데, 결함 대장은 학생 기록이 아니라 콘텐츠 기록이므로 학생 데이터 파기와 함께
  사라지면 안 된다. `EventType`은 PG 네이티브 enum이라 값 추가에 alembic이 필요해지는
  것도 회피 사유.
- **`user_id`를 저장하지 않는다** — 결함 대장에 필요한 건 "누가"가 아니라 "무엇이"다.
  이렇게 하면 ⑴ 미성년 PII 미저촉 ⑵ 보존 파기 대상 아님 ⑶ 반출·삭제권 대상 아님 ⑷ 회신
  유혹이 구조적으로 차단(CS로 새지 않음). 남용 방어는 기존 `api/_rate_limit.py`(SEC-08
  선례)가 저장 없이 담당.
- **v0는 카테고리만, 자유서술 0** — 미성년 자유서술은 PII이고 SEC-01 암호화 좌석을 끌어온다.
  카테고리 + `problem_id`만으로도 QA 파이프라인을 특정 문항에 겨눌 수 있어 충분히 행동
  가능하다.
- **클라 배선 필수 포함** — 이 태스크는 REC-01/NLP-01과 달리 상류 원인이 따로 없다.
  클라 버튼이 유일한 생산자이므로 **버튼 1개를 반드시 같은 태스크 범위에 포함**한다(빠지면
  §6의 7번째 재발).
- **명시적 미포함**: 자유서술·첨부·티켓·배정·SLA·챗봇·만족도·회신.

**변별력 검증**: ⑴ 앱 버튼 1회 → 1행 적재, 되돌리면 0행(양방향 실측) ⑵ 리포트가 "수집
경로 미배선"과 "0건 접수"를 **다른 값**으로 표시(이중 회계, OPS-01 정본 답습). 같은 값이면
검증 실패.

### D2. 접근성 목표 선언 + 배율 회귀 + 시각화 라벨 (신규 `A11Y-` 접두어)

**갭**: `test/accessibility_test.dart`가 대비·탭영역 회귀를 이미 잡는데(MOB-13/14, 백로그
미등재), ⑴ 글자크기 배율 축이 없다 ⑵ 목표 레벨(WCAG/KWCAG 등급)이 선언된 적이 없고 두
정본이 탭영역 값(44dp vs 48dp)에서 이미 서로 다르다 ⑶ 시각화 seed의 기존 `caption`이
스크린리더에 노출되지 않는다.

**설계**:
- **목표 레벨 선언**: WCAG/KWCAG **AA**를 정본 목표로 선언(AAA는 §2-⑨로 미채택, "100%"
  표현은 §정정으로 폐기). `05_interaction.md:46`(44dp)을 `06_design_system.md`의 48dp(실
  게이트 값)로 **통일** — 이중 진실원천 해소.
- **배율 회귀**: 기존 하네스(`accessibility_test.dart`)에 배율 축(1.3×·2.0×) 추가 — 새
  테스트 파일이 아니라 기존 라이트/다크 매트릭스에 축 하나 추가.
- **시각화 라벨**: `scene_renderer.dart:163-164`가 이미 `caption`을 읽고 있으므로,
  `Semantics(label: caption)`으로 감싸는 1줄만 추가.
- **명시적 미포함**: 런타임 토글(고대비·색약 팔레트 전환)·`accessibility_needs` 소비
  분기·TTS 재도입·AAA.
- **법적 축**: 장애인차별금지법 §20-21(정당한 편의)·지능정보화기본법 §46(웹접근성, 문언상
  웹사이트 중심이며 WhyMath 학생 클라이언트는 네이티브 앱)은 **법률 판단 사항**이라 이
  문서가 결론 내지 않는다. `MGMT-02`(약관·개인정보처리방침 변호사 자문) 항목에 "접근성
  준수 수준"을 1줄 추가하는 것만 제안한다 — 법령 유래 절차의 기계 대체 금지.

**변별력 검증**: 고정 height 위젯을 배율 대상 범위에 두면 테스트가 실패해야 하고,
`Semantics` 라벨을 제거하면 시각화 테스트가 실패해야 한다(성공/실패가 다른 값을 내야
검증이 유효).

### D3. 클라우드 승급 사슬 도달 관측 (신규 `OPS-` 후속, 배선 아님)

**갭**: `l3/router.py`가 구독·예산·킬러문항 3축으로 클라우드 승급을 판정하도록 이미
설계돼 있는데, 학생 경로 6곳이 전부 `budget_krw=0.0`·`subscription="free"` 리터럴이라
**규칙1(예산)이 규칙2(구독)보다 먼저 발동**해 클라우드 도달이 항상 0이다. 응답은 완전히
정상적으로 생성되므로(LOCAL 응답도 유효) 이 미도달은 겉으로 드러나지 않는다.

**"지금 고치면 무엇이 달라지는가"**: 구독만 고치면 **아무것도 달라지지 않는다** — 예산
가드가 먼저 막는다(성공/실패가 같은 값을 내는 변경은 그 자체로 CLAUDE.md "변별력 없는
검증 스텝 금지" 위반). **"안 고치면 무엇이 조용히 틀리는가"**: ⑴ 킬러·증명 문항이 학생
경로에서 CLOUD_HIGH로 승급하는 코드 경로가 한 번도 실행되지 않는다(`problem_bank_
killer_v0` 코퍼스가 실재하므로 가정이 아니다) ⑵ 신뢰도 미달 에스컬레이션(`next_tier()`)이
존재하지 않는다 ⑶ CLAUDE.md 스택 표가 클라우드 2모델을 "실제 배선"으로 적어 정본이 도달을
보증하는 것처럼 읽힌다.

**비용·안전 관점**: 현 상태는 비용에 대해 **fail-closed**(항상 최저가 로컬)라 비용 사고
위험은 0이다 — 이것이 이 갭의 우선순위를 낮추는 정당한 근거(stage S4). 반대로 **품질에
대해서는 fail-open을 위장**한다(승급 사슬이 도는 것처럼 읽히지만 미도달).

**설계**:
- 학생 경로 6곳의 라우팅 신호 리터럴을 **단일 정책 함수**로 모으되 **반환값 불변**(회귀
  0·바이트 동일 동결) — 값이 아니라 "이 값이 어디서 오는가"만 1곳으로.
- `ops/cost_probe.py`의 이중 회계 좌석에 **승급 도달 계상**을 추가: 요청 수 / LOCAL 강등
  사유별(예산0·free·규칙6) / CLOUD 도달 건수 / `next_tier` 호출 0건. "0건 통과"가 아니라
  **"미도달"**로 표시.
- **명시적 미포함**: DB `subscription_tier` 읽기·결제·`budget_krw` 실제 배정·`is_premium`
  게이팅·tier별 rate limit·`next_tier` 트리거 구현.

**변별력 검증**: `budget_krw=1000, subscription="premium", difficulty="killer"` 요청을
1건 주입하면 리포트의 "CLOUD 도달"이 0→1로 바뀌고, 되돌리면 다시 "미도달"이 나와야 한다.

### D4. 클라 버전 계약 게이트 (신규 `OPS-` 후속)

**갭**: 백엔드는 `deploy.yml`로 매 커밋 갱신되는데(불변 태그·승인게이트·`/health/ready`
검증), 파일럿 태블릿에 사이드로드된 앱은 그 갱신과 무관하다. mobile CI 잡은 `analyze`·
`test`만 돌고 빌드 산출물이 없다 — CI의 계약 방어는 "다음에 빌드할 앱"만 지키고 "이미
태블릿에 깔린 앱"은 못 지킨다. API 계약이 파손되면 `diagnosis_controller.dart:66`의 단일
실패 문구(`'문제를 불러오지 못했어요...'`)가 401/422/계약파손을 전부 같은 모양으로
덮는다 — 2026-07-20 인증 누락 사고(CLAUDE.md에 규칙으로 등재됨)와 **동일한 구조**다.

**설계**:
- **클라 버전 식별**: `api_client.dart:26`의 기존 단일 헤더 좌석에 `X-App-Version` 추가.
  새 패키지 의존 0 — `lib/core/app_version.dart`에 상수 1개 + `tests/infra/`에 그 상수와
  `pubspec.yaml`의 `version:`이 일치하는지 검사하는 드리프트 게이트.
- **서버측 판정**: 새 미들웨어를 만들지 않는다 — `app.py:544`의 기존
  `_service_metrics_middleware`(OPS-01) 좌석에 최소버전 판정을 얹는다. 임계는 `config.py`
  Settings(기존 플래그 18종과 동거). 미달 시 401/404/422와 **반드시 다른** 전용 사유코드.
- **클라 문구**: `diagnosis_controller.dart:66`의 단일 문자열 분기에 "앱 업데이트가
  필요합니다" 케이스를 하나 더 추가.
- **버전 미상(헤더 없음)은 "미달"과 별도로 "미상"으로 계상** — OPS-01의 "미구성 ≠ 도달
  실패" 회계 정본 답습.
- **명시적 미포함**: 강제 업데이트 유도 UI·스토어 링크·자동 업데이트·릴리스노트·롤백·
  Canary/Blue-Green·Crash 수집·서명·스토어 업로드.

**변별력 검증**: 최소버전을 현재 버전보다 위로 올리면 클라가 전용 문구를 내고, 되돌리면
정상 동작해야 한다. 헤더를 제거하면 "미상"으로 계상돼야 한다(3상태가 서로 다른 값).

**앱 빌드·서명·스토어는 왜 D가 아닌가**: §2-⑬ — 법적 선행(`MGMT-02`) 미충족이라 순서를
뒤집을 수 없다.

### D5. 미사용 의존 제거 + 선언↔사용 거버넌스 게이트 (기존 `MOB-` 접두어 재사용)

**갭**: `firebase_messaging`/`firebase_core`가 `pubspec.yaml:48-50`에 선언만 되고
Dart/Kotlin 사용처·`google-services.json`·gradle 플러그인·`ios/` 디렉터리 전부 0이다 —
같은 pubspec에서 `flutter_tts`/`speech_to_text`를 이미 같은 사유(사용처 0)로 제거한
선례(`:42-45`)가 있다.

**제거 근거**: ⑴ 선례 동형(같은 파일·같은 상태·같은 처분이 일관성) ⑵ 미성년 앱에 미사용
Google SDK 잔존은 `MGMT-02`(개인정보처리방침 "제3자 처리위탁·국외이전" 사실관계)를
오염시킨다 ⑶ "선언 = 도입"으로 다음 세션이 오독할 위험(§6 7회차) ⑷ 부수적으로 빌드 표면
축소.

**설계**:
- `pubspec.yaml`에서 2종 제거 + 제거 사유 주석(`:42-45` 형식 답습).
- **lock 정합**: CI `flutter pub get`에 `--enforce-lockfile` 적용을 시도한다(mobile CI
  잡은 flutter 3.41.9를 실제로 설치하므로 가능성 있음). 이 환경엔 flutter가 없어 실행
  검증이 불가능하므로, 안 되면 `tests/infra/`에 pubspec.yaml 의존 목록↔pubspec.lock
  최상위 항목 일치를 검사하는 Python 게이트로 대체 — **착수 세션이 CI 1회전으로 확정**.
- **선언↔사용 거버넌스 테스트 신설**: `pubspec.yaml` 의존 중 `lib/`·`test/`·`android/`
  사용처 0인 것을 검출(허용목록 명시). 이게 없으면 3회차 재발이 온다.
- **명시적 미포함**: 푸시 구현 일체·FCM 설정·디바이스토큰 테이블·`ios/` 신설.

**변별력 검증**: 미사용 의존을 하나 되돌리면 거버넌스 테스트가 red가 돼야 하고, stale
lock 상태에서 CI가 red가 돼야 한다.

---

## §4. 정직한 공백 — 지금 하지 않는 것 (사유 명시)

| # | 공백 | 실측 근거 | 왜 지금 아닌가 |
|---|---|---|---|
| ① | `subscription_tier` DB reader 0·`budget_krw` 학생 경로 생산자 0·`next_tier` 호출자 0 | `l3/router.py:443,536,539` · `ops/{cost_probe,live_preflight}.py`(유일 생산자) | 배선하면 비용 사고 위험이 즉시 생긴다. D3는 관측만 — 활성화는 결제 결정의 하류 |
| ② | `Problem.is_premium` reader 0 | `schema/problem.py:571` · `db/models/problem.py:244`(소비처 0) | 프리미엄 게이팅은 결제의 하류. 소비처 없는 게이트는 dead code |
| ③ | rate limit이 tier 무관 | `api/_rate_limit.py`(키=user/ip/device) | tier가 없으므로 tier별 한도는 정의 불가 |
| ④ | 시각화 alt text 보장(필수화) 0 | `schema/visualization.py:176`(Optional·게이트 없음) · `l3/visualization.py:88`(프롬프트가 요청만) | D2는 `Semantics` 부착까지만. `caption` 필수화는 회귀 위험이고 클라가 아직 seed 렌더 단계(05a §6)라 실 WebView 완성 후가 옳다 |
| ⑤ | SpeechSpec 클라 도달 0 | `api/speech.py`·`l3/speech.py`(완비) vs `pubspec.yaml:42-45`(의존 제거) | 재도입은 MOB-01이 고정한 툴체인 재교란. 파일럿 코호트에 시각약자 없음 |
| ⑥ | OpenTelemetry 의존 선언만·계측 0 | `pyproject.toml:45-46` vs import 0건 | Langfuse + `ops/service_health.py` 인프로세스 이중 회계로 판정치는 이미 산출됨. 소비처(수집기) 부재 |
| ⑦ | `env.dart:16 sentryDsn` 상수 선언만·소비 0 | 참조처 0 | §2-⑫와 동일 논리. D5의 제거 대상은 pubspec 의존 2종뿐 — dart-define 상수는 SDK가 아니라 무해 |
| ⑧ | `consecutive_active_days` writer·reader 0 | `schema/user.py:461` · `db/models/user.py:324` | §2-③. 좌석은 유지하되 채우지 않는다 |
| ⑨ | 앱 빌드 산출물 CI 0·서명 debug·applicationId 잠정·version 수동 | `ci.yml`(analyze·test만) · `build.gradle:26,39` | §2-⑬(MGMT-02 선행 미충족) |
| ⑩ | `ios/` 디렉터리 자체 부재 | `ls src/mobile/` — android만 | Apple 계정·심사·연 등록비는 사업 결정. Phase 2+ |
| ⑪ | 신고의 자유서술·첨부 이미지 | — | 미성년 PII·SEC-01 암호화 좌석을 끌어온다. v0는 카테고리만 |
| ⑫ | Crash·ANR 수집 0 | pubspec에 crash SDK 0 | §2-⑫ |
| ⑬ | `google-services.json` 0·gradle 플러그인 미적용 | `find` 무일치 | 푸시가 어느 층에도 없다는 증거. D5의 근거이자 §2-③의 뒷받침 |

---

## §5. 유보 항목의 발화 조건 (지금 안 만들되, 언제 만드는지)

| # | 유보 항목 | 발화 트리거 |
|---|---|---|
| ① | 구독·예산 실배선(§4-①②③) | 결제 도입 결정(Phase 2 M2.3) 시. 그 세션의 최초 서브태스크로 D3 리포트를 먼저 읽어 "4겹 차단" 사실을 확인한다 — 구독만 고치면 변별력 0이라는 것이 이 문서의 핵심 실측 |
| ② | AI추천 푸시 | `REC-01` 도달 리포트가 실측 θ 기반 추천을 관측한 뒤. 콜드스타트 위에서 추천 푸시를 보내면 거짓 신호다 |
| ③ | 푸시 채널 전체(93) | Phase 3 M3.2 승계. 발송 채널이 요구하는 새 PII 수집(§2-④)의 동의 범위 갱신이 선행 |
| ④ | 접근성 개인맞춤·TTS·수어(§2-⑧⑩·§4-⑤) | 셋 중 하나: ⓐ 온보딩이 `accessibility_needs`를 실제로 수집하기 시작(writer 발생) ⓑ 시각·청각 약자 학생이 파일럿에 참여 ⓒ 교육기관 납품 결정. TTS는 추가로 실기기 Gradle 호환 재검증 필수 |
| ⑤ | WCAG 법적 준수 수준 상향(§1 법적 축) | `MGMT-02` 변호사 자문 시 접근성 준수 수준을 자문 항목에 포함 → 회신 내용으로 판정 |
| ⑥ | 스토어 배포·서명·iOS(§2-⑬) | `MGMT-02` blocked 해제(약관·개인정보처리방침 문안 확정) — 순서 역전 금지 |
| ⑦ | 신고 자유서술·첨부(§4-⑪) | `MGMT-02` 문안 확정 + SEC-01 암호화 좌석 재사용 판정. 둘 다 필요 |
| ⑧ | CS 티켓·SLA·admin 콘솔(§2-⑤) | `operations_module_gap_review.md` §5 트리거 승계 — 결제 도입 또는 운영자 2인 이상 또는 CS 문의 유입 개시. D1 신고 리포트가 월 N건 이상을 관측하는 것이 "유입 개시"의 기계적 정의가 된다 |
| ⑨ | Crash 수집·OTel 계측(§4-⑥⑫) | 파일럿 중 원인 불명 앱 종료가 실측되고, `MGMT-02` 문안이 제3자 처리위탁을 커버할 때 |
| ⑩ | Canary·Blue-Green·롤링 인프라(§2-⑪) | 백엔드 인스턴스가 2개 이상이 될 때. 단일 인스턴스에서는 플래그 규율이 정본 |

---

## §6. 반복 실수 — 7~9회차 (재발방지 등재)

`ai_recommendation_module_gap_review.md` §6의 6회차 표를 9회차로 확장. 기존 6개는 전부
"만들고 X 안 함" 방향이고, 이번 3개는 **그 뒤집힌 방향**이다.

| 회차 | 사례 | 형태 |
|---|---|---|
| 1~6 | (기존 — `ai_recommendation_module_gap_review.md` §6 참조) | 만들고 CI 미배선/미적재/미배포/미접속/미점화/미공급 |
| **7** | `firebase_messaging`·`firebase_core` pubspec 선언 · Dart/Kotlin 사용 0 · `google-services.json` 0 · gradle 플러그인 미적용 · `ios/` 부재(D5) | **만들지 않고 선언만** — TTS/STT 제거에 이은 2회차 |
| **8** | `budget_krw=0.0` 기본 + `student_subscription="free"` 하드코딩 + `next_tier` 호출자 0 → 클라우드 승급 사슬 학생 도달 0(D3) | **가드를 만들고 입력을 상시 기본값으로 막음** — 6회차("공급원을 잇지 않음")와 달리 공급원이 없는 게 아니라 **기본값 자체가 차단 신호**. 코드는 완전히 정상 동작하고 LOCAL 응답은 완전히 유효한 응답이라 부분 수정이 "고쳤다"는 착각을 만든다(차단이 3겹이라 하나만 고치면 아무 일도 안 일어남) |
| **9** | `api/speech.py:7`·`schema/speech.py` 등 4곳이 클라 소비를 "`flutter_tts`로 합성"이라 단정하는데 그 의존은 이미 제거됨(§정정) | **코드의 후퇴 결정을 정본이 흡수하지 못함** — 다음 세션이 "클라만 붙이면 된다"고 읽고 이미 실패로 판명난 Gradle 경로를 다시 시도할 위험 |

**공통 구조 갱신**: 1~6회차는 "소비측이 완비돼 있어서 존재함이 돌아감으로 읽힌다"였다.
7~9회차는 그 뒤집힌 짝이다 — 7=**선언이 구현으로 읽힌다**, 8=**기본값이 정책으로
읽힌다**, 9=**정본이 현재로 읽힌다**(문서=코드). 판정 기준을 "무엇이 존재하는가"에서
"무엇이 실제로 통과했는가"로 옮겨야 잡힌다 — D3의 도달 계상·D5의 거버넌스 테스트·
아래 §정정이 각각 그 기계화다.

---

## §정정 — stale 정본 9곳 (이번 대조에서 실측으로 발견)

| # | 위치 | 현재 기술 | 실측 |
|---|---|---|---|
| 1 | `src/backend/whymath_backend/api/speech.py:7` · `schema/speech.py:4,151,171` | "클라(L5 Flutter)는 이 명세를 받아 `flutter_tts`로 합성만 한다" | `flutter_tts`는 `pubspec.yaml:42-45`에서 Gradle 비호환 실측으로 제거됨 — 소비 경로가 존재하지 않는다 |
| 2 | `docs/architecture/05_interaction.md:47` · `system_deep_dive.md:101` | 동일 단정 | 동일 |
| 3 | `docs/architecture/visualization_module_gap_review.md:126` | "`/v1/speech` → `SpeechSpec` → `flutter_tts`" | 동일(자매편 stale — 시리즈 내부 전파) |
| 4 | `05_interaction.md:46` "최소 탭 영역 44×44dp" · `system_deep_dive.md:103` "탭 영역 44×44dp" | vs `06_design_system.md` §7 "48dp" + 실 게이트 `androidTapTargetGuideline`(=48dp) | 이중 진실원천. 실행 중인 게이트가 48이므로 44 서술이 stale |
| 5 | `docs/standards/coding_flutter.md:76` | "접근성 100% (Semantics·대비·탭 영역)" | 측정 없는 100% 주장. 실제 커버리지는 explore/home/me + 조밀 위젯 2종·라이트/다크뿐(`06_design_system.md` §7이 정직하게 🟡 표기 중) |
| 6 | `CLAUDE.md` 기술 스택 표 클라우드 LLM 행 | "실제 배선(2026-07 코드): `claude-sonnet-4-6`(CLOUD_MID)·`claude-opus-4-7`(CLOUD_HIGH)만" | 배선 서술은 참이나 학생 트래픽 도달은 0이다(`budget_krw=0.0` 기본이 규칙1로 선차단). "배선됨"이 "돌아감"으로 읽히는 전형 |
| 7 | `docs/reviews/service_ops_mgmt_gap_review_2026-07.md:42` | "LLM 비용 통제 — 런타임 per-user 예산 상한 강제 없음 → CACHE-01 계열에서 후속" | `CACHE-01`은 done인데 예산 상한은 여전히 미배선 — 승계처가 소멸한 stale |
| 8 | `06_design_system.md` §7 TTS 행 "🔴 후속" | 후속의 선행조건(클라 의존 재도입 + 실기기 Gradle 호환 검증)이 표에 없어 "곧 할 것"으로 읽힌다 | §5-④ 트리거를 표에 병기 필요 |
| 9 | `docs/reviews/service_ops_mgmt_gap_review_2026-07.md:21` "14개 라우터" | 실측 `APIRouter(prefix=...)` 16종(`speech`·`study`·`gating` 포함) | 사소 — 참고 기록만 |

**소스·YAML 반영 원칙(선례 승계)**: 1~5·8은 D2(`A11Y-`) 범위에서 처리한다(같은 파일군을
다루는 태스크가 정정의 자연스러운 소유자). 6·7은 `CLAUDE.md`·다른 세션 정본이라 이 문서가
직접 고치지 않고 D3(`OPS-`) notes로 연결한다(거부의 우회 금지 — 정정 사실은 여기 남기고
소유 태스크가 처리). 9는 사소해 정정 없이 기록만.

---

## §7. 실행 — 이번 세션 백로그 등재 (실제 ID는 `backlog.py add`가 배정)

- **`RPT-01-student-defect-report-channel`** — D1. stage S3 · priority 2 · track infra-debt ·
  layer backend.
- **`OPS-17-client-version-contract-gate`** — D4. stage S3 · priority 2 · track infra-debt ·
  layer backend.
- **`A11Y-01-text-scale-and-wcag-target`** — D2. stage S3 · priority 3 · track infra-debt ·
  layer mobile.
- **`OPS-18-cloud-escalation-reach-observability`** — D3. stage S4 · priority 3 · track
  infra-debt · layer backend.
- **`MOB-08-unused-dependency-purge-gate`** — D5. stage S4 · priority 4 · track infra-debt ·
  layer mobile.

### 재판정 트리거 (등재하지 않는 것) — §5 표 참조

가장 우선순위 높은 트리거만 재강조: **91·92·93·94·95 전체의 재판정 시점은 S3-01 파일럿
종료(운영 공백의 실측 재평가) 또는 결제 도입 결정(Phase 2, §5-① 트리거) 또는 `MGMT-02`
해제(§5-⑥⑦) 중 먼저 오는 것**이다.
