# WhyMath 기능·보안 점검 감사 (2026-08-08)

> 정본. 백엔드(FastAPI)·모바일(Flutter)·웹(그래핑 계산기) 대상 기능 결함·오류·취약점 점검.
> 3개 탐색 축(백엔드/모바일/기지이슈) 병렬 + 상위 16개 후보를 **적대적 검증**(실제 코드 재독으로 확정/반증)한 결과.
> 후보를 그대로 나열하지 않고 **검증으로 확정된 것만**, 완화요인·전제와 함께 기록한다(CLAUDE.md 검증 권위: "무엇이 측정으로 증명됐는가").
>
> 등재 태스크: SEC-13·SEC-14·SEC-15·SEC-16·SEC-17·SEC-18·ARCH-27·OPS-23·MOB-12·MOB-13·MGMT-03 (본 문서를 정본으로 인용).
> severity 축 = CLAUDE.md 의사결정 우선순위(①학생안전 ②법적·미성년 ③교수학 ④학습효과 ⑤UX ⑥비용).

---

## 요약표

| ID | 심각도 | 판정 | 위치 | 결함 | 태스크 |
|---|---|---|---|---|---|
| H1 | HIGH | CONFIRMED | `api/me.py:2755-2817` | `/harness-metrics`가 노출 계약 우회 — GAMING_SUSPECT 낙인·INTERNAL_ONLY 학생 노출 | SEC-13 |
| H2 | HIGH | PARTIAL | `api/_rate_limit.py:938-956` | XFF 무조건 신뢰 → 감사 IP 위조 + rate limit 우회 | SEC-14 |
| H3 | HIGH | CONFIRMED | `GraphingCalculator.jsx:1871` + `assets/graphing_calculator/assets/index-*.js` | QuizMode 수학 판정 로직 학생 실기기 도달(슬89 위반) | ARCH-27 |
| H4 | HIGH | PARTIAL | `oauth_providers.py:85,147` + `_auth.py:88` | 실 OAuth 신규 가입자 전원 is_minor=None → PIPA 게이트 미집행 | MGMT-03 |
| M1 | MEDIUM | CONFIRMED | `api/problems.py:81,127` | 정답·풀이단계·distractor_map 무인증 공개 | SEC-15 |
| M2 | MEDIUM | PARTIAL | `api/study.py:253` + `l2/pedagogy_evidence.py:127` | `/outcome` 쓰기 소유권 검사 0 → 효과측정 오염 | SEC-16 |
| M3 | MEDIUM | CONFIRMED | `harness/wh1_llm_policy.py:196` | 학생 대면 튜터 폴백 침묵 강등(예외 타입명 0) | OPS-23 |
| M4 | MEDIUM | CONFIRMED | `api/ocr.py:60,93` | OCR 업로드 크기·MIME 검증 0 → 인증 DoS | SEC-17 |
| M5 | MEDIUM | CONFIRMED | `active_problem.dart:13` | activeProblem 영구 stale → 신고·세션 오귀속 | MOB-12 |
| M6 | MEDIUM | PARTIAL | `app.py:905` | `/v1/jobs/{job_id}` 무인증·무소유권 | SEC-15 |
| M7 | MEDIUM | PARTIAL | `config.py:1298` | is_production_like 단일 신호에 3중 안전장치 결박 | MGMT-03 |
| L1 | LOW | CONFIRMED | `app.py:550` | `/docs`·`/openapi.json` 프로덕션 무인증 노출 | SEC-18 |
| L2 | LOW | PARTIAL | `android/app/build.gradle:35-39` | release 빌드 debug 키 서명 | MOB-13 |
| L3 | LOW | PARTIAL | `auth_interceptor.dart:16`·`api_client.dart:21` | 401 미처리 + sendTimeout 부재 | MOB-13 |
| L4 | LOW | PARTIAL | `api/gating.py` | 게이팅 6종 무인증 + persona 자유지정 | SEC-18(notes) |
| — | — | REFUTED | `onboarding_controller.dart:60-67` | isSubmitted=true-on-failure는 게이트 미제어(오탐) | — |

---

## HIGH

### H1. `/v1/me/harness-metrics`가 노출 계약을 우회 (CONFIRMED) — SEC-13
`api/me.py:2755-2817`. 학생 토큰(`ConsentedUser`, admin 게이트 없음)만으로 원시 `SurrogateMetrics`를 그대로 반환한다.
포함 항목: INTERNAL_ONLY 지표(`diagnosis_agreement_rate`·`tokens_per_turn` — `growth_evidence_exposure.py:65-78 _STATIC_TIER`),
원 `calibration_brier` 스칼라(역방향 지표 오독 소지), `help_reduction_validated.verdict`(=`R15Verdict.GAMING_SUSPECT` 가능).
성장증거 노출 계약(`classify_metric_exposure`)은 스스로 "유일한 노출 판정 경로"라 선언(`growth_evidence_exposure.py:121-129`)했으나
이 라우트가 우회한다 — `me.py:2811-2817` 자백 주석("원시 SurrogateMetrics를 그대로 반환 — 계약을 우회").
- **왜 중요**: CLAUDE.md 금기 "부정 피드백 정서 강화 금지"(GAMING_SUSPECT 낙인) + 계약 위반. PED-08(#726 done)이 안전 라우트
  `/growth-evidence`를 병설했을 뿐 원시 라우트를 학생 접근에서 닫지 않음 — CLAUDE.md "정본화를 집행으로 착각한 완료 선언" 재발형.
- **완화**: 공식 Flutter 클라는 이 엔드포인트 미호출(dart 참조 0). 앱 정상 경로로는 학생이 만나지 않으며 유효 토큰 직접 HTTP 호출 시에만 노출. 본인 집계(교차 유출 아님). → critical 아닌 high.

### H2. `X-Forwarded-For` 무조건 신뢰 → 감사 IP 위조 + rate limit 우회 (PARTIAL) — SEC-14
`api/_rate_limit.py:938-956`. `_client_ip`가 XFF 좌측 첫 값을 신뢰 프록시 검증 없이 채택.
위조 시 미인증 표면(auth 콜백/리프레시·`/v1/reports/defects`)의 IP 레이트리밋이 전면 우회되고,
`privacy/audit.hash_client_ip`가 기록하는 **미성년 동의변경·개인정보 반출 감사 IP도 위조**된다(`api/me.py:2733`·`api/users.py:255`).
- **완화**: 기본 prod는 `127.0.0.1` 바인딩이라 현재는 잠재 상태(런북 §8이 공개 노출 전 프록시·TLS·방화벽 선행 게이트). 단 `APP_BIND_ADDR=0.0.0.0`(실기기 데모 토글)이나 공개 배포 시 즉시 라이브.
- **정정**: 초기 점검이 지목한 `--proxy-headers`/`--forwarded-allow-ips`는 이 함수를 못 고침 — `_client_ip`가 raw 헤더를 직접 판독해 uvicorn scope['client'] 재작성을 우회한다. 실제 방어 = XFF를 append가 아닌 **overwrite**하는 신뢰 프록시 + 우측-신뢰값 채택. nginx 기본(append)만으론 `split[0]`이 위조값을 집어 방어 안 됨.

### H3. 그래핑 계산기 번들에 수학 판정 로직이 학생 실기기 도달 (CONFIRMED) — ARCH-27
`src/web/graphing-calculator/src/GraphingCalculator.jsx:1871`의 무조건 렌더 "문제" 버튼이 QuizMode를 연다:
클라 채점(`sameGraph` `:566-594`)·오개념 진단(`diagnose` `:539-563`, "당신의 답: N" 노출)·정답 공개(`giveUp` `:597-608`)·점수 누적(`HISTORY_KEY="quiz_history"` `:344`).
이 번들이 `src/mobile/assets/graphing_calculator/assets/index-*.js`로 출하되고, Flutter `GraphingCalculatorWebView`가
chat_screen→`SceneRenderer`(대화형 그래프/곡면/시뮬 장면) 경로로 로드한다 → **학생 실기기 도달. CLAUDE.md 슬89 무-수학판정 불변식·L1-L4 독립 코어 원칙 위반.**
- **핵심**: 웹 거버넌스 테스트(`no_math_judgement_governance.test.js:11-16`)가 이 위반을 ARCH-12 "데모 전용·학생 노출 0·Flutter 도달 경로 0" 예외로 화이트리스트 존치했는데,
  **그 전제가 실측으로 반증됨**(대화형 그래프는 앱 핵심 기능·코드·자산·테스트 전부 배선). 테스트는 green이나 근거가 거짓 — 테스트가 명시한 강제 재설계 트리거("판정 로직 학생 노출 경로 진입 시 백엔드 verify 리팩터 강제")가 이미 충족.
- **거버넌스 사각**: Dart 게이트(`no_math_logic_governance_test.dart`)=`lib/**.dart`만, 웹 게이트=`src/web/**/src/**`만 → **출하 자산(`assets/*.js`) 검사 게이트 0건.** 두 게이트 사이 틈으로 통과.
- **완화**: 도달 실현은 코치가 대화형 viz 장면을 내보내는 빈도에 좌우(정적 스칼라 spec만 주입하는 임베드는 안전). 그러나 "도달 0" 전제는 구조적으로 성립 불가.

### H4. 실 OAuth 신규 가입자 전원 `is_minor=None` → PIPA 미성년 게이트 미집행 (PARTIAL) — MGMT-03
`oauth_providers.py:85,147`가 `OAuthIdentity(provider, subject, email)`만 넘기고 birth_year 미전달 →
`api/auth.py:163-169` 신규 가입자가 `is_minor=None`. 동의 게이트 `api/_auth.py:88`은 `if user.is_minor and user.parent_consent_at is None`으로
**"알려진 미성년"만 차단** → 연령 미신고 실제 미성년은 통과.
- **완화**: 우발 버그 아닌 **의도된 정책 경계**("모르면 모른다" — `consent.py:20-23`·모델 docstring 3회 명시, 가입 시 birth_year 필수화는 변호사 자문 후속 = MGMT-02 blocked). is_minor 서버 재파생(`users.py:146-150`)은 정직 신고자 게이트·`is_minor=false` 위조 차단은 작동. 데모 provider는 birth_year 전달(`demo_auth.py:50`), 실 로그인 클라는 스텁(OAuth-c3 미구현).
- **단 실 OAuth 배선 + 카카오/네이버 birthyear 스코프 파싱 미추가 시 즉시 라이브 법적 노출.** "무효화"는 다소 과장 — 정확히는 "연령 강제 수집 부재" 공백.

---

## MEDIUM

### M1. 정답·풀이단계 무인증 공개 (CONFIRMED) — SEC-15
`api/problems.py:81-104`(`GET /v1/problems/{id}`)·`:127-149`(`/steps`)·목록이 인증 의존성 없이 자체생성 문항의
`answer`(`schema/problem.py:307`)·`answer_explanation`(:311)·`distractor_map`(:324)·`expected_answer`(:684)를 그대로 직렬화.
- **완화**: SEC-07 D1의 의도적 "공개 카탈로그(GET 무인증)" 결정(`problems.py:15-18`). 평가원/EBS/교과서 저작권 본문은 validator(`schema/problem.py:602-649`)가 강제-비움.
- **단**: `answer`는 그 강제-비움 목록에서 **빠짐** + `is_published`/`is_premium` 필터 없음(미게시·프리미엄 열람) + 목록 GET이 정답 포함 전량 반환(UUID 열거 불필요) → 교수학 무결성("막혔을 때 바로 정답 제공 금지" 절대금기) 위험. `ProblemSchema`를 학생용/관리용 구분 없이 단일 응답모델로 쓰는 설계 차원. (gating.py도 동일 ProblemSchema 반환).

### M2. `/outcome` 쓰기 소유권 검사 0 → 효과측정 데이터 오염 (PARTIAL) — SEC-16
`api/study.py:253-282`. `user:ConsentedUser`로 인증하나 핸들러가 주입 user를 안 쓰고, `session_id`를 클라 body(`OutcomeRequest`)로 받아
소유권 검증 없이 `record_pedagogy_outcome`(`l2/pedagogy_evidence.py:127`) → `EvidenceEvent` insert. 모델에 `user_id` 컬럼 부재(`evidence_event.py:54-115`).
- **완화**: 인증 필요(무인증 아님). 성적/숙달 갱신 아님(그건 `record_problem_attempt_mastery`가 user_id에 묶여 별도). session_id=랜덤 UUID4(122비트, 열거·목록 노출 엔드포인트 없음). 세션 불일치 행은 집계 제외.
- **위험**: 인증 학생이 임의/자기 session_id로 미검증 outcome을 무제한 주입 → L4 적응형 교수법 효과측정 집계 오염(write-authorization 공백). user_id 부재는 가명화(우선순위 #2) 의도 설계와 본질적 긴장 — 소유권 검증을 가명화와 양립하게 설계해야.

### M3. wh1 튜터 정책 침묵 강등 — 예외 타입명 미기록 (CONFIRMED) — OPS-23
`harness/wh1_llm_policy.py:196` `except Exception: return self._safe_fallback(state)`. LLM 장애를 타입명 로그 없이 폴백.
`wh1_primary_enabled=True`(기본·GA) 하에 학생 대면 coach 세션/턴 엔드포인트에 **실배선**.
- **CLAUDE.md 1급 금기(침묵 실패) 라이브 위반** — 2026-07-16 langfuse 8일 무증상 사고와 동형. `config.py:180`이 스스로 "폴백은 예외 타입명 로그·침묵 실패 금지" 계약을 명시하나 이 폴백이 미이행(문서-코드 불일치). 같은 코드베이스 `judge.py:171`은 동일 상황 `exc_info=True` 로그 — 처우 비일관.
- **완화**: 폴백 자체는 안전 강등(verify 의무 시 verify_step, 아니면 격려 end_turn — 정답 억제 백스톱 통과, 학생에 오답·크래시 없음). 위험 본질 = 관측성 결손(provider 지속 장애를 "정상"으로 오인).
- **동반 대상**(같은 무타입 흡수): `l4/step_shadow.py:136`, `l4/misconception/shadow.py:107·244`, `l4/misconception/crosslink_shadow.py:145·169`, `harness/wh1_shadow.py:289`, `l5/ocr/verify.py:126`(antlr 미설치=영구 열화와 일시 파싱실패를 같은 pass로 흡수).

### M4. OCR 업로드 크기·MIME 검증 0 → 인증 DoS (CONFIRMED) — SEC-17
`api/ocr.py:60`(`await image.read()`)·`:93`(20장 리스트 컴프리헨션). 페이지 **수**만 20 캡, 바이트 크기·content-type 검증 없음. 앱 계층 body 상한 없음.
- **완화**: `ConsentedUser` 게이트(무인증 아님·인증된 남용/탈취 계정). Starlette `SpooledTemporaryFile`이 파싱 중 일부 디스크 스풀하나 `.read()`가 단일 bytes로 RAM 복귀 → 고갈 벡터 성립. `/pages`는 20배 동시 적재 증폭. 프로덕션 ingress body 상한 가능성 있으나 리포 내 근거 없음.

### M5. `activeProblemProvider` 영구 stale → 결함 신고·세션 오귀속 (CONFIRMED) — MOB-12
`src/mobile/lib/features/problems/application/active_problem.dart:13` `StateProvider<Problem?>`(非autoDispose).
프로덕션 write는 세팅 1곳(`problem_screen.dart:83`)뿐, **null 리셋 0건**(전수 grep 확인). 앱 재시작 전까지 영구 활성.
- **영향**: 결함 신고(`chat_screen.dart:211`)가 엉뚱한 problem_id로 접수, 새 코치 세션(`chat_controller.dart:188`)이 낡은 문제에 묶임, 로그아웃(`auth_controller.dart:88`)해도 잔존(다음 학생에 이전 문제 배너).

### M6. `/v1/jobs/{job_id}` 무인증·무소유권 (PARTIAL) — SEC-15
`app.py:905-906`. 인증·소유권 검사 없이 비동기 생성 결과(검증 전 원시 LLM 출력) 반환. 바로 위 `POST /v1/generate`(`:836`)는 `CurrentUser`로 봉인.
- **완화**: job_id=Celery async_result.id=클라 생성 UUID4(추측·열거 불가) → 타 채널(로그·네트워크)로 UUID 선행 유출 필요. 노출은 학생 PII 아닌 L3 생성 수학 텍스트. 부수적 무제한 폴링(경미 DoS·enumeration). docstring(app.py:28)이 "SEC-07 범위 밖" 자백하나 backlog 추적 태스크 부재(미추적 공백).

### M7. `is_production_like` 단일 신호에 3중 안전장치 결박 (PARTIAL) — MGMT-03
`config.py:1298-1321`. OAuth(kakao/naver) 구성 여부 하나로 ①대화 콘텐츠 암호화 fail-closed(`require_dialogue_content_cipher`) ②PII IP salt fail-closed ③데모 가짜 provider 이중 방어가 동시 판정.
- **완화**: 동일 신호가 미성년 로그인 경로(유일 토큰 발급구)도 차단 → OAuth 없는 prod엔 저장할 미성년 대화 자체가 없어 현행 평문 위해는 도달 불가(SEC-01 설계 근거·테스트 동결). 코드 사실 3건은 참이나 위해 도달성 결핍.
- **단**: 향후 device/email 등 OAuth 외 로그인 경로 추가 시 is_production_like가 False로 남은 채 미성년 진입 → 이 결박이 침묵 실패가 됨. 폭발반경 격리 원칙(키 분리는 잘 지킴)과 모순되는 신호 결박.

---

## LOW (배포 전 승격 필요)

- **L1. `/docs`·`/redoc`·`/openapi.json` 프로덕션 무인증 노출 (CONFIRMED) — SEC-18** · `app.py:550`. docs_url 등 미지정·기본 활성·prod 분기 부재. 정보 공개(스키마 광고·정찰 조력)이지 접근 우회 아님(보호 라우트는 인증 유지). GCP/AWS WAF 차단 여지 있으나 리포 근거 없음.
- **L2. Android release 빌드 debug 키 서명 (PARTIAL) — MOB-13** · `build.gradle:35-39`. 배포 CI·keystore·스토어 등록 전무(사전 릴리스, applicationId "잠정"). Google Play가 debug 인증서 거부하므로 게시-후-위조도 부분 차단. **스토어 배포 착수 시 HIGH 승격 필수 선행.**
- **L3. AuthInterceptor 401 미처리 + sendTimeout 부재 (PARTIAL) — MOB-13** · `auth_interceptor.dart:16`·`api_client.dart:21`. 문서화된 후속 슬라이스 유예. graceful 실패. 권고: onError 401→`token_store.clear()`+재로그인 유도, `sendTimeout` 추가.
- **L4. 게이팅 6종 무인증 + persona 자유지정 (PARTIAL) — SEC-18 notes** · `api/gating.py`. SEC-07 D1 공개 카탈로그(이미 `/v1/problems`로 익명 공개되는 동일 데이터의 persona 필터 부분집합). persona는 인가 경계 아닌 콘텐츠 버킷 선택자. 저작권 차단은 L6 `is_exposable`이 persona 무관 집행(스푸핑 우회 불가). **향후 학생별 진단·약점 개념 등 개인 컨텍스트 반환 확장 시 인증/persona 바인딩 필수 — 그때 재검토.**

## 반증 (오탐)
- **`onboarding_controller.dart:60-67` isSubmitted=true-on-failure (REFUTED)**. 사실이나 이 플래그가 앱 진입/게이트를 제어하지 않음(화면 무조건 이동·서버 `ConsentedUser`가 모든 보호 엔드포인트에서 독립 집행). 진짜 잔여 리스크는 H4의 birth_year 정책. 부수적으로 catch(e) 타입 미로깅은 작은 관측성 갭(OPS-23 범위에서 함께 처리 가능).

---

## 백로그 미등재 신규 관찰 3건 (별도 처리)
1. **`G-s4-14-variant-identity` 게이트 부재** — 문서(`problem_bank_gap_review_r2`)상 등재 선언됐으나 `backlog/gates.yaml`에 없음(HARN-18 notes 손편집분 미착지). `gates` CLI에 `add` 동사 부재 → HARN-18 선행. Kiki 안내.
2. **ADMIN-03 백로그 상태 드리프트(미머지 done 비가시성 · HARN-11 유형)** — 코드는 main에 머지(7dbf40c5 / PR #716, retention.py + security_privacy.md + 동결 테스트 test_audit_retention_exclusion.py)됐으나 main의 `backlog/tasks/ADMIN-03*.yaml`은 status=todo. done-status는 미머지 브랜치 `claude/admin-03-audit-retention-policy`의 백로그 사본에만 존재 → 코드는 왔는데 status 갱신이 동기화 안 됨. `backlog.py start`가 "이미 완료(미머지)"로 거부(중복 구현 방지) → **직접 done 전이 불가**. harness 백로그 동기화(그 브랜치의 status 반영) 사안 — 본 세션에서 우회하지 않음(CLAUDE.md '거부 우회 금지'). Kiki/harness 정정 항목.
3. **HARN-15 부재 → S3-26/27/28 3중 번호충돌 재채번 정지** — main에 HARN-15 없어 소유자 없는 정지 상태. Kiki 결정(추론 재채번 금지).

## CI·테스트 배선 실태 (건전 — 참고)
테스트 디렉터리 전건 CI 배선(`test_test_suite_wiring.py` 4계약 동결), 커버리지 70% 실강제(backend/data_pipeline/web ≥70·계층별 l4=90·Flutter ≥60).
알려진 약점: QA 파이프라인 게이트 상시 fail-open(`ci.yml:186 continue-on-error` → ARCH-23 todo), 야간 전수 재검증 3/7 코퍼스(PB-02), 경로필터 skip=required 충족.
