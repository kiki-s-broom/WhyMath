# WhyMath × EOS Privacy & Consent Platform 갭 분석

> **작성일**: 2026-08-25  
> **대상**: WhyMath 백엔드(`src/backend/whymath_backend`) 및 관련 문서  
> **기준**: EOS(Education Operating System) 지향 교육앱 47_개인정보·보호자 동의 검토(134항), 2026년 8월 기준  
> **성격**: 설계·기술 갭 분석(법률 자문 아님)

---

## 1. 개요

### 1.1 목표
EOS 검토서가 제시한 Privacy & Consent Platform 아키텍처(Consent를 독립 도메인으로, AI inference/training 분리, Data Category/Processing Purpose/Retention Registry, 삭제 오케스트레이션 등)와 WhyMath의 현재 구현을 대조하여, **구현된 부분 / 부분 구현 / 미구현 / 설계 갭**을 파일·모델·API 수준에서 식별하고, 우선순위와 후속 태스크를 도출한다.

### 1.2 범위
- **포함**: Age Policy, Guardian/보호자, Consent, Processing Purpose, Data Category, AI 개인정보, Retention/Deletion, Privacy Request, Audit, Access Control, Privacy-as-Code, 문서 거버넌스
- **제외**: 법률 자문 판단(변호사 검토 필요 항목은 명시), B2B 학교 계약 세부 설계(Phase 3+), 해외 클라우드 DPA 실체 검증(계약 문서 부재)

### 1.3 방법론
1. EOS 검토 134항을 12개 주제로 그룹화
2. 각 주제별로 "현재 구현 / EOS 요구 / 갭 / 위험도 / 관련 파일" 정리
3. P0~P3 우선순위와 법적·기술적 위험도를 교차해 최종 우선순위 매트릭스 도출
4. 후속 태스크를 `backlog` 등재 가능한 형태로 분해

### 1.4 면책
- 본 문서는 **제품 설계·기술 구현 갭 분석**이며, 법률 자문이 아니다.
- 14세 미만 동의 절차, 민감정보 분류, 국외 이전, 보존 연한 등은 변호사·개인정보 전문가 검토가 필요하다.
- EOS 검토서 원문은 저장소 외부 문서이며, 본 분석은 사용자가 제공한 134항 텍스트와 WhyMath 저장소 내 코드/문서를 기준으로 매핑했다.

---

## 2. WhyMath 현재 구현 요약

### 2.1 이미 구현된 부분

| 영역 | 핵심 내용 | 위치 |
|---|---|---|
| 연령 파생 | `birth_year`만 수집, 서버에서 `is_minor` 파생(클라이언트 입력 무시) | `schema/user.py:119-125`, `db/models/user.py:85`, `consent.py:43-60` |
| 보호자 동의 기록 | `parental_consent` 테이블, `guardian_email_hash`, `verification_method`, `consent_scope`, `consent_signed_at`, `expires_at`, `revoked_at` | `db/models/parental_consent.py:51-89`, `schema/parental_consent.py:33-105` |
| 동의 게이트 | 미성년 + 동의 없음 시 403, `revoked_at`/`expires_at` reader | `api/_auth.py:92-133` |
| 동의 GRANT/REVOKE | `POST /v1/users/me/parental-consent`, `DELETE /v1/users/me/parental-consent` | `api/users.py:183-280`, `api/users.py:283-358` |
| 대화 암호화 | `dialogue_turn.content` AES-256-GCM 봉투 암호화 | `db/models/dialogue.py:175-184`, `api/_crypto.py` |
| 삭제권 | `_ERASURE_PLAN`에 따라 18개 테이블 단일 트랜잭션 삭제, `DeletionAudit` 증빙 | `privacy/erasure.py:92-111`, `db/models/audit.py:48` |
| 반출 | `_EXPORT_PLAN` 기반 JSON 반출, 학생 대면 예측 필드 제외 | `privacy/export.py:98-172` |
| 보존 파기 | `_RETENTION_PLAN` 기반 3년 PII 시계열 파기 | `privacy/retention.py:66-84` |
| 감사 | `PrivacyAudit` 4종(반출·동의변경·관리자접근·역할변경), IP 해싱 | `privacy/audit.py:85-194`, `db/models/audit.py:88-138` |
| LLM 라우터 | 무료 사용자는 클라우드 금지, local 우선, `student_id_hash`만 Langfuse에 기록 | `l3/router.py:309`, `l3/router.py:424` |
| 로그 마스킹 | `PiiSecretScrubberFilter`로 API 키·JWT·이메일·전화번호 등 마스킹 | `ops/log_scrubber.py:77-232`, `app.py:669` |
| 이벤트 PII 차단 | `_FORBIDDEN_PAYLOAD_KEYS`로 analytics 이벤트 payload 일부 금지 | `schema/analytics_event.py:39-62` |

### 2.2 핵심 갭 한눈에 보기

| # | 갭 | 위험도 | EOS 검토서 항목 |
|---|---|---|---|
| 1 | **Consent를 독립 도메인이 아닌 `UserProfile`/`ParentalConsent` 단일 테이블로 취급** — ConsentPolicy/Version/Record/Evidence 미구현 | 높음 | §13~§17, §124 |
| 2 | **보호자 독립 계정/인증 모델 없음** — `parent_email_hash` 단일 컬럼, N:M 관계 없음 | 높음 | §10~§13, §32~§39 |
| 3 | **처리 목적/데이터 카테고리 Registry 부재** — `service_core` 단일 scope, ProcessingPurpose/DataCategory 미구현 | 높음 | §18~§23, §71~§74 |
| 4 | **AI inference vs training 동의 분리** — `ConsentScope.ai_training` 기반 PEP 및 `/v1/generate` trace 배선 구현. 성인은 별도 동의 UI 부재로 기본 거부(privacy-by-default) | 높음 | §5, §48 |
| 5 | **LLM 입력 PII redaction 없음** — 학생 발화/학교명/실명이 provider로 그대로 전송 가능 | 높음 | §45~§47 |
| 6 | **Vector DB(임베딩) 삭제 전파 없음** — `erase_user`가 4개 임베딩 테이블 삭제 안 함 | 높음 | §59 |
| 7 | **Privacy Request 워크플로우 부재** — 삭제/반출/정정 요청을 추적하는 상태기계 없음 | 중간~높음 | §40~§43 |
| 8 | **계정 상태 머신 부재** — ACTIVE/SUSPENDED/DEACTIVATED/DELETION_PENDING/DELETED/ANONYMIZED 분리 없음 | 중간 | §42 |
| 9 | **관리자 접근 감사 배선 안 됨** — `record_admin_access_audit` 호출부 0 | 중간~높음 | §63~§66 |
| 10 | **Processor Registry 부재** — 외부 LLM/OCR/embedding/observability 가공자 등록부 없음 | 중간 | §68~§69 |
| 11 | **Privacy-as-Code/CI Privacy Gate 부재** — 스키마 변경 시 privacy metadata 검사 없음 | 중간 | §71~§74 |
| 12 | **개발/QA 데이터 비식별화 파이프라인 부재** | 중간 | §104~§105 |

---

## 3. 주제별 갭 분석

### 3.1 연령 확인(Age Policy) — EOS §6~§9

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| 연령을 `AgeStatus` 독립 모델로 관리(UNKNOWN, UNDER_MINIMUM, MINOR_GUARDIAN_REQUIRED, MINOR_SELF_CONSENT_ALLOWED, ADULT) | `UserProfile.is_minor` boolean/nullable, 서버에서 `birth_year`로 파생 | 연령대 분류 없음, 단일 boolean | 낮음~중간 | `db/models/user.py:149`, `consent.py:43-60` |
| 생년월일 최소수집, 원본 삭제 후 검증 결과만 보관 | `birth_year`(연 단위)만 수집, 월일 미수집 | 정확한 만나이 계산 불가, 보수적 연나이 사용 | 중간 | `schema/user.py:119-125`, `db/models/user.py:85` |
| 국가별 연령 정책 확장 | `Settings.minor_consent_age` 기본 14 | 국가별 AgePolicyEngine 부재 | 낮음 | `config.py:522-532` |
| `AGE_THRESHOLD_CROSSED` 이벤트, 성년 전환 처리 | 없음 | 연령 임계 도달 시 ConsentMigrationPolicy/이벤트 부재 | 낮음(Phase 3+) | — |

**핵심 갭**: WhyMath는 데이터 최소화 관점에서 `birth_year`만 수집하는 것이 강점이나, 이로 인해 **정확한 만나이 게이팅**이 불가하고 연나이 기준 보수적 판정을 사용 중. EOS 검토서의 `AgeStatus` 독립 모델과 `AgePolicyEngine`은 미구현. 또한 `is_minor=None`(생년 미제공) 상태에서 게이트가 통과되는 문제(`api/_auth.py:115`)가 남아 있다.

---

### 3.2 보호자 도메인(Guardian) — EOS §10~§13, §32~§39

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| Guardian을 `parent`가 아닌 독립 개체로, 별도 계정/프로필 | `UserProfile`에 `parent_email_hash`, `parent_consent_at` 단일 컬럼만 존재 | `GuardianProfile`/`GuardianRelationship` 테이블 없음 | 높음 | `db/models/user.py:149-151`, `schema/user.py:278-286` |
| Guardian-학생 N:M 관계, 관계 유형/검증/유효기간/철회 | `parental_consent` 테이블이 동의 이력만 기록 | GuardianRelationship 모델(`PENDING`/`VERIFIED`/`REVOKED` 등) 부재 | 높음 | `db/models/parental_consent.py:51-89` |
| 보호자 본인확인(휴대폰·이메일 OTP·신분증 등) | `GuardianVerifier` Protocol + `StubGuardianVerifier` seam | 실 본인확인 미구현, prod 안전장치로 기능 기본 off | 높음 | `consent_grant.py:87-117`, `config.py:533-544` |
| 보호자 변경/이혼/후견인 변경/성년 전환 대응 | 없음 | `valid_from`/`valid_until`/`revoked_at` 기반 관계 생애주기 부재 | 중간 | — |
| 교사 ≠ Guardian 분리 | `Role` 2값뿐, 교사/부모 역할 미도입 | `TEACHER`, `PARENT`, `SCHOOL_ADMIN` 역할 부재 | 중간 | `schema/enums.py:1473-1505` |

**핵심 갭**: WhyMath는 보호자를 **단일 컬럼**(`parent_email_hash`)으로 취급. EOS가 요구하는 `GuardianRelationship`의 N:M 구조, 관계 검증 상태, 관계 생애주기는 전무. 보호자 본인확인도 `stub` 상태(`verification_method="stub"`)이며, prod에서는 `parental_consent_grant_enabled=False`로 동의 시스템 자체가 꺼져 있어 **법정대리인 동의 플로우가 완성되지 않음**.

---

### 3.3 동의 도메인(Consent) — EOS §13~§21, §114~§116

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| Consent = Event + State 방식, 상태 머신(REQUIRED→PENDING→GRANTED→WITHDRAWN/EXPIRED/REJECTED/SUPERSEDED/INVALIDATED) | `ParentalConsent` 단일 테이블, `revoked_at`/`expires_at` nullable로 암묵적 상태 판단 | 명시적 `ConsentStatus` 상태 머신 부재 | 중간 | `db/models/parental_consent.py:51-89` |
| ConsentPolicy/ConsentPolicyVersion/ConsentRecord/ConsentEvidence 분리 | `ParentalConsent` 테이블 1개 | 독립 도메인 모델 부재 | 높음 | `db/models/parental_consent.py` |
| 동의 문안/버전 추적, document snapshot/hash | `consent_scope`만 기록 | `policy_version`, `document_sha256`, `presentation_id` 부재 | 높음 | `schema/parental_consent.py:119-129` |
| 동의 목적(Purpose) Registry화 | `ConsentScope.service_core` 단일 값 | `ProcessingPurposeRegistry` 부재, AI_INFERENCE/AI_TRAINING/RESEARCH 등 구분 없음 | 높음 | `schema/enums.py:1454-1470` |
| Bundle Consent 회피(필수/선택 분리) | 없음 | 동의 항목 분리 UI/API 부재 | 중간 | — |
| Consent Impact Engine(약관 변경 시 NO_ACTION/NOTICE_ONLY/RECONSENT_REQUIRED) | 없음 | Policy diff → 재동의 판단 자동화 부재 | 낮음(Phase 2+) | — |

**핵심 갭**: WhyMath의 `ParentalConsent`는 **동의 "이력" 테이블** 수준에 머물러 있음. EOS가 요구하는 `ConsentRecord`, `ConsentPolicyVersion`, `ConsentEvidence`의 분리, 상태 머신, 동의 문안 버전 추적은 미구현. 특히 AI 서비스/학습/연구/마케팅 등 **목적별 동의 분리**가 없어 CLAUDE.md "동의 없이 학습 사용 금지" 원칙을 코드 수준에서 완전히 집행하기 어려움.

---

### 3.4 처리 목적·데이터 카테고리·처리 매트릭스 — EOS §18~§23

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| ProcessingPurposeRegistry(서비스 제공/AI 응답/품질/학습/연구 등) | `ConsentScope.service_core` 단일 값, `PermissionAction` enum에 AI_TRAINING/AI_CONTEXT 등 값은 있으나 연결 안 됨 | 목적별 처리 레지스트리 부재 | 높음 | `schema/enums.py:554`, `schema/enums.py:1454-1470` |
| DataCategory Registry(IDENTITY, CONTACT, LEARNING_ACTIVITY, AI_CONVERSATION, SECURITY_LOG 등) | `_ERASURE_PLAN`/`_EXPORT_PLAN`/`_RETENTION_PLAN`으로 실질적 분류는 있음 | 중앙 DataCategory Registry 부재, 메타데이터 기반 분류 아님 | 중간 | `privacy/erasure.py:92-111`, `privacy/export.py:98-172`, `privacy/retention.py:66-84` |
| Processing Activity Catalog(데이터×목적×주체×AI×보유×삭제) | 없음 | 처리 활동 중앙 카탈로그 부재 | 중간 | — |
| Data Processing Matrix(CMS 관리) | 없음 | 매트릭스 관리 UI/스키마 부재 | 낮음(Phase 2+) | — |

**핵심 갭**: WhyMath는 **플랜 튜플**(`_ERASURE_PLAN`, `_EXPORT_PLAN`, `_RETENTION_PLAN`)로 데이터 처리 범위를 관리. 이는 삭제/반출/보존에 유효하나, EOS가 요구하는 **목적 중심의 중앙 Registry**는 아님. 따라서 "이 데이터를 이 목적으로 처리할 수 있는가?"를 코드에서 일괄 판단하는 `Policy Enforcement Point`가 없음.

---

### 3.5 AI 개인정보 — EOS §45~§53

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| LLM 입력 PII redaction(Privacy Filter → Context Minimizer → PII Redaction) | 없음 | `l3/pipeline.py`가 원시 `prompt`/`system`을 provider에 그대로 전달 | 높음 | `l3/pipeline.py:127-140,235-237`, `l3/models.py` |
| AI inference vs AI training 동의 분리 | `get_consented_user`가 단일 동의 게이트 | LLM 파이프라인에서 동의 종류 구분 불가 | 높음 | `api/_auth.py:92-133`, `api/coach.py:2006,2049` |
| Processor Registry(LLM provider별 allow_child_data/training_use/region) | `LOCAL_MODEL_MATRIX`, `QUALITY_MODEL_ID`만 존재 | 가공자/목적/데이터 카테고리/보호 조치 등록부 부재 | 중간 | `l3/router.py:LOCAL_MODEL_MATRIX` |
| Prompt Privacy Classification(PUBLIC/INTERNAL/PERSONAL/CHILD_PERSONAL/SENSITIVE/RESTRICTED) | `analytics_event.py`의 `_FORBIDDEN_PAYLOAD_KEYS` 정도만 존재 | LLM prompt/이벤트 민감도 분류체계 부재 | 높음 | `schema/analytics_event.py:39-62` |
| Raw AI conversation 최소 보관, learning signals 분리 저장 | `DialogueTurn` 봉투 암호화로 원문 저장은 가능 | 외부 provider/Langfuse로 원문 유출 가능성, 학습 신호 장기 저장 분리 미구현 | 높음 | `db/models/dialogue.py:175-184`, `l3/trace/langfuse_sink.py:119-137` |
| Vector DB 삭제 전파 | `erase_user`에 4개 임베딩 테이블 누락 | `source_record_id`/`subject_id` 메타데이터 부재, 삭제 전파 미구현 | 높음 | `privacy/erasure.py:92-111`, `db/models/concept_embedding.py:82-99` |

**핵심 갭**: WhyMath는 **저장 시 암호화**와 **local-우선 라우팅**으로 일부 AI 개인정보 위험을 줄였으나, **LLM provider로 전송되는 prompt 자체의 PII redaction**과 **AI training 동의 분리**가 없음. 이는 EOS 검토서가 가장 강조한 "학습데이터 ≠ AI 학습데이터" 원칙과 직접 충돌.

---

### 3.6 데이터 최소화·가명화·ID 분리 — EOS §50~§54, §89~§90

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| User ID vs Learner ID vs Analytics ID 분리 | `UserProfile.user_id`가 모든 학습/분석/대화 테이블에 직접 연결 | 독립 식별자 공간 부재 | 중간 | `db/models/user.py`, `db/models/dialogue.py:163-166` |
| Concept Graph ≠ Learner Graph | 개념 임베딩과 학습자 숙련도 이력이 논리적으로 분리 | 동일 `concept_id`/`user_id` 축, 접근 통제가 명시적으로 분리되지 않음 | 중간 | `db/models/concept_embedding.py:82-99`, `db/models/assessment.py:157-179` |
| Analytics 데이터 분리(이름/이메일/전화 제거) | `analytics_event`에 `_FORBIDDEN_PAYLOAD_KEYS`, `session_id` 사용 | Analytics 전용 식별자 부재, `privacy_classification` 필드 부재 | 중간 | `schema/analytics_event.py:39-62,98` |
| 가명정보 Layer(Raw → Pseudonymized → Education Data → Aggregate) | 없음 | 체계적 pseudonymization pipeline 부재 | 중간 | — |

**핵심 갭**: WhyMath는 이메일 해시(`email_hash`) 등으로 PII 노출을 줄였으나, **서비스 식별자와 학습/분석 식별자가 물리적으로 통합**되어 있어 단일 계정 해킹 시 전체 학습 프로파일이 노출될 수 있음.

---

### 3.7 보존·삭제·삭제 전파 — EOS §55~§60, §111

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| RetentionPolicy Registry(데이터별 보존 기간) | `pii_retention_years`(기본 3년), `evidence_retention_years`(기본 3년) | 데이터 카테고리별 보존 정책 레지스트리 부재 | 중간 | `config.py:644,654`, `privacy/retention.py:66-84` |
| Retention Engine(Scheduler → Engine → Data Catalog → Delete/Anonymize/Archive) | `purge_expired_records` 함수 + docker-compose 24h 루프 | 카탈로그 기반 보존 엔진 부재 | 낮음~중간 | `privacy/retention_purge_cli.py`, `docker-compose.prod.yml:156-166` |
| 삭제 전파(Deletion Orchestrator): PostgreSQL, Redis, Vector DB, Object Storage, Analytics, LLM logs, Backup | `external_erasure_targets()`로 Redis/Langfuse 매니페스트만 남김 | 실제 외부 store 삭제 집행 미구현, Vector DB(pgvector) 삭제 누락 | 높음 | `privacy/erasure.py` |
| 계정 상태 분리(ACTIVE/SUSPENDED/DEACTIVATED/DELETION_PENDING/DELETED/ANONYMIZED) | `is_active`/`is_deleted` boolean + `deleted_at` | 상태 머신 부재, 탈퇴 유예기/복구/익명화 경로 부재 | 중간 | `db/models/user.py:172-173` |

**핵심 갭**: WhyMath의 삭제권은 **PostgreSQL 내에서는 견고**하나, **Vector DB(임베딩)와 외부 store의 실제 삭제 집행**이 매니페스트 수준에 머물러 있음. EOS가 강조한 "삭제 후 Vector DB에 embedding이 남으면 불완전한 삭제"를 아직 해결하지 못함.

> **정정(2026-09-07·SEC-32)**: 이 절의 초판(2026-08-25)은 매니페스트가 선언한 **ClickHouse·S3**를 실재 store로 전제해 "ClickHouse/S3/Redis 삭제 연동"을 후속 과제로 적었다. 실측 결과 두 store는 이 저장소에 **도입된 적이 없고**(설정 키 0·compose 서비스 0·SDK 0), 반대로 학생 유래 데이터가 실제로 나가는 **Langfuse**(L3 라우팅 트레이스·외부 SaaS)가 매니페스트에서 누락돼 있었다. 매니페스트는 Redis·Langfuse 2종으로 정정됐고, 선언↔실재 대조는 `tests/backend/_external_store_evidence.py` 계약이 강제한다. 아래 P1 항목의 대상 store도 그에 맞춰 읽어야 한다.

---

### 3.8 Privacy Request·Dashboard·자동화된 결정 — EOS §40~§44, §112~§113

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| PrivacyRequest 모델/워크플로우(ACCESS/RECTIFICATION/DELETION/RESTRICTION/EXPORT/CONSENT_WITHDRAWAL) | 엔드포인트 단위로 직접 구현(`export_my_data`, `erase_my_account`, 동의 REVOKE) | 요청 추적 상태기계 부재 | 중간~높음 | `api/me.py:3053`, `api/me.py:3100`, `api/users.py:283-358` |
| 법정대리인 대리 요청 경로 | 없음 | 보호자가 자녀 데이터에 대해 직접 요청/관리하는 별도 인증 흐름 부재 | 높음 | — |
| 보호자/학생 Privacy Dashboard | 없음 | 개인정보 이용 현황·동의 관리·데이터 다운로드·삭제 UI 대시보드 부재 | 중간 | — |
| 자동화된 결정 추적(DecisionTrace) | 없음 | 학습 경로/추천/숙련도 추정 등 자동화 결정의 입력·모델·결과·설명가능성 기록 부재 | 낮음~중간(Phase 2+) | — |

**핵심 갭**: WhyMath는 권리 행사를 **개별 API 호출**로 처리하지만, EOS가 요구하는 **PrivacyRequest라는 일관된 워크플로우**와 **보호자 대시보드**는 없음. 특히 보호자가 자녀 데이터를 직접 요청/관리할 경로가 없음.

---

### 3.9 감사 로그 — EOS §63~§64, §90~§95

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| 보호자 동의/철회/버전 변경/데이터 접근/반출/삭제/관계 변경 감사 | `PrivacyAudit` 4종 writer 구현(반출·동의변경·관리자접근·역할변경) | 관리자접근(`admin_access`) 호출부 0 | 중간~높음 | `privacy/audit.py:130-158` |
| 감사 로그 보존 연한 | `_RETENTION_PLAN`/`_ERASURE_PLAN`에서 감사 2테이블 의도적 제외 | 보존 연한 미확정, 자동 파기 경로 미배선 | 중간 | `privacy/retention.py:20-34`, `db/models/audit.py:88-138` |
| 감사 로그에 PII 과다 기록 금지 | `ip_hash`만 저장, 콘텐츠 미저장 | 일부 이벤트에서 콘텐츠 해시 외 추가 메타데이터 필요 가능 | 낮음 | `privacy/audit.py:85-103` |
| PrivacyService → AuditService 연결 | 직접 writer 호출 | 이벤트 기반 감사 통합 부재 | 낮음 | — |

**핵심 갭**: 감사 기록 메커니즘은 있으나, **관리자 접근 감사가 배선되지 않음**. 관리자 콘솔이 없기 때문. 또한 감사 로그 보존 연한이 법률 검토 대기 중이라 무기한 보존 상태.

---

### 3.10 보안·접근통제·역할 — EOS §66~§69, §88

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| 역할 세분화: STUDENT/PARENT/TEACHER/SCHOOL_ADMIN/PRIVACY_ADMIN/SECURITY_ADMIN/SUPPORT_AGENT/SUPER_ADMIN | `Role` 2값: `STUDENT`, `CONTENT_ADMIN` | 교사/부모/학교관리자/Privacy Admin 등 역할 부재 | 중간 | `schema/enums.py:1473-1505` |
| 보호자 권한 세분화(VIEW_PROGRESS, VIEW_ASSESSMENT, VIEW_AI_CHAT, MANAGE_CONSENT, REQUEST_EXPORT, REQUEST_DELETION) | 없음 | 보호자 RBAC 부재 | 높음 | — |
| 관리자라도 최소 권한, 개인정보 접근 제한 | `CONTENT_ADMIN`만 존재 | Privacy Admin 역할/권한 매트릭스 부재 | 중간 | `api/_auth.py:136-163` |
| Break-glass(Emergency Privacy Access) | 없음 | 긴급 접근 절차, 임시 권한, 자동 만료 부재 | 낮음~중간 | — |
| MFA/step-up 인증/관리자 IP 허용목록 | 없음 | 관리자 보안 강화 부재 | 낮음~중간 | `docs/architecture/account_security_gap_review_r2.md:328-337` |

**핵심 갭**: WhyMath의 역할 모델은 **학생 vs 콘텐츠 관리자** 2값에 머물러 있음. EOS가 요구하는 보호자/교사/학교 관리자/Privacy Admin 등 다양한 역할과 권한 세분화는 미구현.

---

### 3.11 Privacy-as-Code·CI Privacy Gate — EOS §71~§74

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| 처리 목적/데이터/보존/처리자 등을 코드로 기술(Privacy-as-Code) | 없음 | YAML/코드 기반 privacy metadata 부재 | 중간 | — |
| Privacy Policy Compiler(Registry → Check) | 없음 | 자동화된 개인정보 처리방침 생성/검증 부재 | 낮음(Phase 2+) | — |
| CI Privacy Gate: 새 PII 필드 → privacy metadata required | `policy-guard`가 시크릿/저작권 패턴 차단 | privacy 전용 CI 게이트 부재 | 중간 | `.github/workflows/ci.yml:1038-1081` |
| Schema diff → privacy classification/retention/purpose required | 없음 | 스키마 변경 시 privacy impact 자동 검사 부재 | 중간 | — |

**핵심 갭**: WhyMath는 `policy-guard`로 시크릿/저작권을 차단하지만, **새로운 PII 필드 추가 시 privacy metadata(분류·목적·보존)를 요구하는 CI 게이트**는 없음.

---

### 3.12 문서 거버넌스·개발환경 데이터 — EOS §70, §97~§98, §104~§107

| EOS 요구사항 | 현재 구현 | 갭 | 위험도 | 관련 파일 |
|---|---|---|---|---|
| Privacy Notice/ConsentPolicy/DocumentVersion 분리 관리 | 없음 | 개인정보 처리방침/동의 문안 버전 관리 시스템 부재 | 중간 | `docs/legal/pipa_data_matrix.md:136-145` |
| Processing Registry → 개인정보 처리방침 자동 생성 | 없음 | Privacy Policy Compiler 부재 | 낮음(Phase 2+) | — |
| 개발/QA/LLM eval용 production dump 비식별화 | 없음 | de-identification/synthetic/pseudonymous pipeline 부재 | 중간 | — |
| AI 평가 데이터 ≠ Production Learner Conversations | 없음 | LLM eval corpus용 별도 비식별화 자산 파이프라인 부재 | 중간 | — |

**핵심 갭**: 개발·평가 환경에서 production 데이터를 그대로 사용하지 않도록 하는 **비식별화/합성 데이터 파이프라인**이 없음.

---

## 4. 우선순위 매트릭스

| 우선순위 | 항목 | 위험도 | EOS 항목 | 후속 태스크 성격 |
|---|---|---|---|---|
| **P0 (즉시)** | 1. 보호자 본인확인 실 구현(`GuardianVerifier`) | 높음 | §6, §10~§13 | `MGMT-01` 법적 검토 후 구현, prod on 전 필수 |
| **P0** | 2. 동의 범위 확장(AI 학습/연구/마케팅 분리) + ConsentPolicyVersion/ConsentEvidence | 높음 | §5, §13~§17, §48 | `MGMT-02` 문안 확정 후 스키마 확장 |
| **P0** | 3. LLM 입력 PII redaction + Prompt Privacy Classification | 높음 | §45~§47 | 기술 구현, 변호사 검토 병행 |
| **P0** | 4. AI inference vs training 동의 분리 집행 | 높음 | §5, §48, §50 | `ConsentScope.ai_training`/`ai_inference` 추가, `has_scope_consent`, `privacy/authorize.py` PEP, `/v1/generate` trace 배선. 성인 동의 UI는 미구현으로 `ai_training` 기본 거부 |
| **P1 (Phase 1.5~2 초반)** | 5. Vector DB 삭제 전파 | 높음 | §59 | `erase_user` 확장 + embedding metadata 추가 |
| **P1** | 6. 외부 store 삭제/반출 집행 오케스트레이션 | 높음 | §58, §111 | Redis 무효화 + Langfuse 삭제 API 연동(SEC-32 정정 — ClickHouse·S3는 미도입) |
| **P1** | 7. `GuardianRelationship` + 보호자 독립 계정 모델 | 높음 | §10~§13, §32~§39 | 스키마 재설계, `MGMT-01` 선행 |
| **P1** | 8. `PrivacyRequest` 모델/워크플로우 | 중간~높음 | §40~§43 | 상태기계 + API + dashboard |
| **P1** | 9. 관리자 접근 감사 배선 + `admin_access` 호출부 연결 | 중간~높음 | §63~§66 | 관리자 콘솔/엔드포인트 착지 시 |
| **P2 (Phase 2 중반)** | 10. ProcessingPurpose/DataCategory/RetentionPolicy Registry | 높음 | §18~§23, §71~§74 | 중앙 레지스트리 설계 |
| **P2** | 11. 역할 세분화(TEACHER/PARENT/SCHOOL_ADMIN/PRIVACY_ADMIN) | 중간 | §66~§69 | 스키마 + 인가 게이트 |
| **P2** | 12. 보호자 권한 RBAC + 대시보드 | 중간~높음 | §34, §112 | 권한 매트릭스 코드 집행 |
| **P2** | 13. 개발/QA/평가 데이터 비식별화 파이프라인 | 중간 | §104~§105 | 합성 데이터 생성 |
| **P3 (Phase 2 후반~3)** | 14. Privacy-as-Code/CI Privacy Gate | 중간 | §71~§74 | CI 게이트 + 메타데이터 스키마 |
| **P3** | 15. Privacy Policy Compiler | 낮음~중간 | §70, §106~§107 | Registry 기반 자동 생성 |
| **P3** | 16. DecisionTrace/자동화된 결정 추적 | 낮음~중간 | §44 | 추천/학습경로 결정 기록 |
| **P3** | 17. Multijurisdiction Policy(국가별 연령/동의) | 낮음 | §7, §68 | 해상 확장 시 |

---

## 5. 후속 태스크 제안

아래 태스크는 `backlog.py add` 등재 후보다. 실제 등재는 `backlog.py` CLI를 통해 확정해야 한다(AGENTS.md "태스크 ID 추론 배정 금지").

### P0 (즉시 착수 권장)

1. **법정대리인 본인확인 구현** — `GuardianVerifier` Protocol의 실 구현체(이메일 OTP/휴대폰 본인인증/신분증 확인 중 법적 적정 방식)를 도입하고, `parental_consent_grant_enabled`를 prod에서 켤 수 있도록 만든다.
2. **동의 범위 및 버전 관리 스키마 확장** — `ConsentScope`를 `service_core` 외 `ai_inference`, `ai_training`, `research`, `marketing` 등으로 확장하고, `ConsentPolicyVersion`/`ConsentEvidence` 테이블을 신설한다.
3. **LLM Prompt PII Redaction Layer** — `l3/pipeline.py`의 `generate()` 호출 전에 PII 탐지/마스킹/최소화 계층을 추가하고, `RoutingRequest`에 `privacy_classification`을 도입한다.
4. **AI Training 동의 게이트** — ✅ 2026-08-25 구현 완료. `ConsentScope.ai_training`/`ai_inference`/`research`/`marketing` 추가, `has_scope_consent()`/`require_consent()`/`authorize_processing()` PEP 도입, `/v1/generate`에서 `training_allowed`를 `pipeline.generate(..., training_allowed=...)`로 전달해 Langfuse trace 메타데이터에 기록. 성인은 별도 성인 동의 저장소 부재로 `ai_training` 기본 거부(privacy-by-default); 성인 동의 UI/스키마는 후속.

### P1 (Phase 1.5~2 초반)

5. **Vector DB 삭제 전파** — `erase_user`에 4개 임베딩 테이블 삭제 로직을 추가하거나, 임베딩 테이블에 `source_record_id`/`subject_id`/`source_record_type` 메타데이터를 추가해 삭제 전파가 가능하게 한다.
6. **외부 Store 삭제/반출 집행** — `external_erasure_targets`/`external_export_pending` 매니페스트를 실제 클라이언트 작업으로 완결한다. 대상은 **Redis**(응답 캐시·큐 payload)와 **Langfuse**(라우팅 트레이스 SaaS) 2종이다(SEC-32 정정 — ClickHouse·S3는 미도입이라 제외). 다만 두 store 모두 **현재 user 단위 키가 없다** — Redis 캐시 키는 프롬프트 해시이고 Langfuse의 `student_id_hash`는 서빙 경로에서 채워지지 않는다. 따라서 이 과제는 삭제 API 호출 이전에 *user 축을 만들 것인가*(추적 가능성 ↑ vs 삭제 가능성 ↑)를 먼저 판정해야 한다.
7. **GuardianRelationship 도메인 모델** — `GuardianProfile`, `GuardianRelationship` 테이블을 신설하고, 학생-보호자 N:M 관계, 관계 유형/검증/유효기간/철회를 관리한다.
8. **PrivacyRequest 워크플로우** — 요청 접수→검증→처리→완료/거부 상태기계를 구현하고, 법정대리인 대리 요청 경로를 만든다.
9. **관리자 접근 감사 배선** — 관리자 콘솔/엔드포인트가 생기는 시점에 `record_admin_access_audit` 호출부를 연결하고, 관리자 조회 이력을 학생 본인도 확인할 수 있게 한다.

### P2~P3 (Phase 2 중반~3)

10. **ProcessingPurpose/DataCategory/RetentionPolicy Registry** — 중앙 레지스트리를 설계하고, 기존 `_ERASURE_PLAN`/`_EXPORT_PLAN`/`_RETENTION_PLAN`을 registry 기반으로 전환한다.
11. **역할 확장 및 보호자 권한 RBAC** — `TEACHER`/`PARENT`/`SCHOOL_ADMIN`/`PRIVACY_ADMIN` 역할을 도입하고, PIPA 데이터 권한 매트릭스를 코드로 집행한다.
12. **개발/QA/평가 데이터 비식별화** — production dump → de-identification/synthetic 데이터 생성 파이프라인을 만든다.
13. **Privacy-as-Code/CI Privacy Gate** — 새로운 PII 필드 추가 시 privacy metadata(분류·목적·보존)를 요구하는 CI 검사를 추가한다.
14. **Privacy Policy Compiler/DecisionTrace** — 중장기적으로 registry 기반 처리방침 생성과 자동화된 결정 추적을 구현한다.

---

## 6. 결론

WhyMath는 **PostgreSQL 중심의 개인정보 보호 기반**(동의 기록, 삭제권, 반출, 보존 파기, 감사, 대화 암호화, local-우선 LLM 라우팅)을 이미 상당 수준 갖추었다. 특히 `is_minor` 서버 파생, `parental_consent` append-only 테이블, 단일 트랜잭션 `erase_user`, IP 해싱 감사 등은 EOS 검토서의 핵심 원칙과 방향이 일치한다.

그러나 **Consent를 독립 도메인으로 보는 관점**, **AI 개인정보 통제**, **Vector DB/외부 store 삭제 전파**, **보호자 독립 계정/인증**, **처리 목적 중앙 Registry** 5개 영역에서 구조적 갭이 크다. 특히 LLM 입력 PII redaction과 AI training 동의 분리는 WhyMath가 "생성형 AI 수학 튜터"를 핵심 기능으로 하는 서비스인 만큼 **P0로 즉시 다뤄야 한다**.

가장 현실적인 접근은:
1. **P0 4개 항목**(보호자 본인확인, 동의 범위/버전, LLM PII redaction, AI training 동의)을 먼저 설계/구현
2. **P1 삭제 전파**(Vector DB, 외부 store)를 병행
3. **P2 Registry/RBAC**로 아키텍처를 확장 가능하게 정리
4. **P3 Privacy-as-Code/Compiler**는 중장기 로드맵으로 유지

---

## 부록 A. EOS 검토서 항목 매핑

| 본 분석 주제 | EOS 검토서 항목(§) |
|---|---|
| 3.1 연령 확인 | §6~§9 |
| 3.2 보호자 도메인 | §10~§13, §32~§39 |
| 3.3 동의 도메인 | §13~§21, §114~§116 |
| 3.4 처리 목적·데이터 카테고리 | §18~§23 |
| 3.5 AI 개인정보 | §45~§53 |
| 3.6 데이터 최소화·가명화 | §50~§54, §89~§90 |
| 3.7 보존·삭제 | §55~§60, §111 |
| 3.8 Privacy Request·Dashboard | §40~§44, §112~§113 |
| 3.9 감사 로그 | §63~§64, §90~§95 |
| 3.10 보안·접근통제 | §66~§69, §88 |
| 3.11 Privacy-as-Code·CI Gate | §71~§74 |
| 3.12 문서 거버넌스·개발환경 | §70, §97~§98, §104~§107 |

## 부록 B. 법적 면책

- 본 문서는 제품 설계 기준과 기술 구현 현황을 대조한 것이며, **법률 자문을 대체하지 않는다**.
- 14세 미만 법정대리인 동의 방식, 민감정보 분류, 보존/파기 기한, 국외 이전, 자동화된 결정에 대한 권리 등은 상용화 직전 변호사·개인정보 전문가 검토가 필요하다.
- WhyMath의 현재 설계가 PIPA, GDPR-K, COPPA 등 다양한 법역에 대응할 수 있도록 확장 가능한 구조를 제안하는 것이 목적이지, 특정 법역의 준수 여부를 판단하는 것은 아니다.
