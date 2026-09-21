# 48. EOS 보안·접근 통제(Security & Access Control) 설계

> **범위**: 인가(Authorization)·암호화·키/시크릿 관리·세션 보안·AI/데이터 접근 통제·감사 연동을 아우르는 EOS 공통 보안 기반 계층(Control Plane).
> **상태**: 목표 아키텍처 수용(2026-08-25). 제2부 현행 매핑은 2026-08-25 코드 실측 기준. 미결 항목은 제3부 결정표.
> **관련**: `docs/architecture/44_eos_version_management.md`(버전 관리 — 정책 버저닝 연결), `docs/standards/eos_identity_layer_011_1_decision.md`(Entity ID), `docs/standards/security_privacy.md`, `docs/legal/pipa_data_matrix.md`, `data/access_matrix.json`, 백로그 `SEC-01~24`·`ADMIN-01~09`

---

## 0. 이 문서를 읽는 법

- **제1부 — EOS 목표 아키텍처**: EOS(Education OS) 완성형의 보안 모델. 전부 지금 구현한다는 뜻이 아니다.
- **제2부 — 현행 WhyMath 매핑**: 제1부 각 영역이 오늘 코드베이스에 얼마나 있는지 실측. 신규 과제와 기존 자산을 혼동하지 않기 위해 작성했다.
- **제3부 — 결정표**: 확정 결정과 미결(TBD) 항목. 카탈로그가 아니라 결정이 필요한 지점만 모았다.
- **제4부 — 착지 순서**: 46(인증)·47(동의)·90(감사) 문서가 아직 없으므로 선행 의존을 명시한다.

**식별자 규칙**: 이 문서의 요구사항 ID는 `EOS-SEC-*` 접두사다. 백로그 태스크 번호(`SEC-01~24`, `ADMIN-*`)와 구분하기 위함이다.

**법령 인용 검증 상태**: 「개인정보의 안전성 확보조치 기준」(개인정보보호위원회고시 제2026-9호, 2026-07-01 시행)은 2026-08-25 [law.go.kr](https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000281400&chrClsCd=010201) 원문 대조로 확인했다. 접속기록 보관기간 등 세부 수치는 고시 별표의 최신 원문을 기준으로 하며 이 문서에 수치를 박아 넣지 않는다(개정 시 문서가 틀어지지 않도록).

---

# 제1부. EOS 목표 아키텍처

## 1. 위치와 책임

48_보안은 개별 기능 모듈이 아니라 모든 EOS 서비스가 의존하는 공통 기반 계층이다. 내부 명칭은 **EOS Security Control Plane**.

| 모듈 | 질문 | 주요 책임 |
|---|---|---|
| 46 회원가입·로그인·인증 | 누구인가? | Identity 증명, 토큰 발급, MFA/Passkey 지원 |
| **48 보안·접근 통제** | 무엇을 할 수 있는가? + 데이터를 어떻게 보호하는가? | 인가 판정, 접근 통제, 암호화, 키/시크릿, 세션 보호, AI/데이터 보안 |
| 47 개인정보·보호자 동의 | 어떤 개인정보를 어떤 근거로 처리할 수 있는가? | 법적 동의, 보호자 관계 검증, 데이터 처리 근거 |
| 90 감사로그 | 누가 언제 무엇을 했는가? | 변조 방지 감사, 보안 이벤트 영속, Policy 버전 고정 |

48번 핵심 흐름:

```
Authentication(46) → Identity → Authorization(RBAC/ABAC/ReBAC) → Policy Decision → Policy Enforcement → Application/API/AI/Data → Encryption/KMS → Audit(90)
```

## 2. 설계 원칙

1. **Deny by Default**: 명시적 ALLOW가 없으면 DENY.
2. **최소권한 + 필요 최소화**: 학생, 특히 미성년자 계정은 보수적 기본값(프로필 비공개, 검색 불가, 외부 메시지 불가, 학습데이터 외부공유 불가).
3. **Consent ≠ Authorization**: 동의가 있어도 인가가 없으면 DENY. 둘 다 충족해야 접근 가능.
4. **Actor 통일 모델**: 사람(USER), 서비스(SERVICE), 에이전트(AGENT), 작업(JOB), 기기(DEVICE), 플러그인(PLUGIN) 모두 Identity + Policy로 다룬다.
5. **Defense in Depth**: API 인가 + DB RLS + 테넌트 격리 + 암호화. 한 층만 의존하지 않는다.
6. **가명 기본**: 학습 데이터에는 실명이 아닌 opaque ID(ULID/UUID)만 사용. PII Store와 Education Data Store를 논리적으로 분리.
7. **Zero Trust 실질 요구**: "내부망이므로 신뢰"가 아니라 모든 요청을 인증·인가. 서비스 간에도 mTLS + 단기 자격증명 + 스코프.
8. **AI 출력도 인가 대상**: LLM이 호출하는 tool은 서버측에서 다시 인가. RAG retrieval에도 tenant/scope/grade 필터.

## 3. 인가 모델: RBAC + ABAC + ReBAC + Context

RBAC만으로는 "TEACHER가 어느 학교·어느 학급 학생을 볼 수 있는가"에 답할 수 없다. 따라서 EOS는 세 모델을 조합한다.

| 모델 | 판단 근거 | EOS 예시 |
|---|---|---|
| RBAC | 역할 | `STUDENT`, `TEACHER`, `CONTENT_ADMIN`, `SECURITY_ADMIN` |
| ABAC | 속성 | `subject.school_id == resource.school_id`, `resource.class_id in subject.assigned_class_ids` |
| ReBAC | 관계 | `parent --guardian_of--> student`, `teacher --teaches--> class --contains--> student` |
| Context | 요청 맥락 | `MFA verified`, `risk_score < threshold`, `trusted_device`, `time` |

Permission namespace: `{domain}.{resource}.{action}`

```
learning.progress.read
learning.progress.update
assessment.exam.publish
content.problem.edit
privacy.pii.export
security.role.manage
audit.event.read
```

관계 모델은 별도 테이블에 영속:

```
relationships(subject_type, subject_id, relation, object_type, object_id, valid_from, valid_until, status)
```

예: `TEACHER_123 —TEACHES→ CLASS_456`, `PARENT_9 —GUARDIAN_OF→ STUDENT_44`.

정책은 버전 관리(44번 모듈 연계). 각 보안 결정은 정책 버전(`policy_version`)과 이유(`reason`)를 남긴다.

```python
# EOS 목표 API
await authorize({
    actor: req.user,
    action: "learning.progress.read",
    resource: { type: "StudentProgress", studentId, tenantId }
})
```

## 4. 권한 계층과 멀티테넌시

```
Platform
 └── Tenant
      └── Institution
           └── School
                └── Class
                     └── User
```

`tenant_id`는 1급 보안 속성. 모든 리소스 조회에는 tenant 필터가 있어야 한다.

```sql
-- PostgreSQL RLS 예시(가이드용)
ALTER TABLE students ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON students
USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

RLS 구현 시 유의사항:
- SQLAlchemy async + 커넥션 풀에서는 **트랜잭션 시작 시** `SET LOCAL app.tenant_id = ...`를 호출해야 한다. 커넥션 반납 시 설정이 풀린다.
- 애플리케이션 DB 계정은 `BYPASSRLS` 권한이 없어야 한다. 슈퍼유저로 접속하면 RLS가 무력화된다.
- **테이블 소유자(owner)는 기본적으로 RLS를 우회**할 수 있다. 마이그레션 계정과 애플리케이션 계정을 분리하거나, 소유자에게도 RLS를 강제하는 `FORCE ROW LEVEL SECURITY`를 사용해야 한다. 인가 테스트에 이 케이스를 포함해야 한다.
- 현재 WhyMath는 테넌시 개념이 없으므로 이는 EOS 단계 요구사항이다.

## 5. 객체 수준·필드 수준 인가

API 경로의 ID를 바꾸어 다른 객체를 조회할 수 있어서는 안 된다. 모든 API는 다음 순서를 거친다.

```
Authentication → tenant check → object ownership/relationship check → action permission → field filtering
```

필드 수준 인가 예시:

| 필드 | 학생 | 보호자 | 담당 교사 | 지원 상담원 | 관리자 |
|---|---|---|---|---|---|
| 이름 | 자기 | 자녀 | 담당학생 | 제한 | 필요 시 |
| 학습진도 | O | 자녀 O | 담당학생 O | 제한 | 제한 |
| 오개념 프로필 | O | 자녀 O | 담당학생 O | X | 제한 |
| 보호자 전화 | X | O | 필요 시 | 마스킹 | 제한 |
| 인증정보 | X | X | X | X | X |

현재 `data/access_matrix.json`이 PIPA 데이터 권한 매트릭스의 기계 판독 사본으로 존재한다. EOS에서는 이 매트릭스를 런타임 필드 인가 정책의 씨앗으로 사용할 것을 권장한다.

## 6. 주체별 접근 정책

### 6.1 학생(미성년자 우선)

- 프로필 공개 기본값 `false`
- 검색 가능 기본값 `false`
- 외부 메시지 기본값 `false`
- 위치수집 기본값 `false`
- 학습데이터 외부공유 기본값 `false`

### 6.2 보호자

단순히 `PARENT → CHILD DATA`가 아니라 검증된 관계(`guardian_relationship.status == VERIFIED`)가 있어야 한다.

```json
{
  "guardian_id": "usr_p001",
  "student_id": "usr_s001",
  "relationship": "LEGAL_GUARDIAN",
  "status": "VERIFIED",
  "valid_from": "2026-01-01",
  "valid_until": null
}
```

### 6.3 교사

`teacher → institution → class assignment → subject → student` 범위로 계산.

```
교사 A
학교 X
1학년 3반 수학 담당
→ 학교 X + 1학년 3반 + 수학 관련 학습데이터만
```

### 6.4 관리자 권한 분리

`ADMIN` 하나로 통합하지 않는다.

```
CONTENT_ADMIN
USER_ADMIN
SCHOOL_ADMIN
PRIVACY_ADMIN
SECURITY_ADMIN
BILLING_ADMIN
SYSTEM_ADMIN
SUPER_ADMIN
```

특히 사용자관리·콘텐츠관리·개인정보관리·보안관리·운영관리는 서로 분리.

### 6.5 Super Admin

상시 사용 계정이 아니라 **JIT(Just-In-Time)**.

```
일반 운영 → Privileged Access Request → 승인 → 임시 권한 → 작업 → 자동 만료
```

### 6.6 Step-Up Authentication

고위험 작업에는 최근 MFA 인증 이력(예: 5분 이내) 또는 Passkey/WebAuthn 같은 phishing-resistant 인증을 요구.

```
학생 개인정보 다운로드
MFA 해제
관리자 권한 변경
데이터 삭제 / 대량 export
API key 생성
암호키 rotation
```

## 7. 암호화

### 7.1 3층 암호화

- **Transit**: Client↔API, API↔API, API↔DB/Vector DB/Object Storage/LLM — TLS 1.3 우선, 1.2 호환 범위에 한해.
- **At-Rest**: PostgreSQL, Redis, Object Storage, Vector DB, backups, snapshots, analytics warehouse, log storage.
- **Application/Field-Level**: 고위험 필드(guardian_phone, email, real_name, external_identity, sensitive_profile)는 AES-256-GCM 필드 수준 암호화. EOS 목표는 §7.2의 KEK/DEK 봉투 암호화를 적용하는 것이다.

> ⚠️ Disk/TDE 암호화만으로는 부족. 애플리케이션 서버 자체가 탈취된 경우를 대비해 필드 수준 암호화를 병행.

### 7.2 Envelope Encryption

```
Master Key → KEK → DEK → Data
```

데이터 하나하나를 KMS 마스터 키로 직접 암호화하지 않는다. 데이터는 DEK로, DEK는 KEK로 암호화.

### 7.3 현행 WhyMath 암호화 패턴

`src/backend/whymath_backend/api/_crypto.py`가 이미 다음을 구현해 두었다.

- AES-256-GCM(96-bit nonce, AEAD) 필드 수준 암호화
- `MultiKeyCipher`: primary + fallback 다중 키 + 버전 기반 복호화
- 자산별 키 소스 분리: device secret, dialogue content, evidence payload
- device secret·dialogue content 모두 prod 추정 환경에서 암호화 키 미설정 시 부팅 거부(fail-closed) — 판정은 `config.is_production_like` 단일 좌석

현재 구현은 **자산별 마스터 키를 직접 사용하는 필드 암호화**이며, §7.2에서 정의한 KEK/DEK 봉투 암호화나 KMS는 아직 도입되지 않았다. EOS는 이를 P0 암호화 기반선으로 삼고, KEK/DEK/KMS로의 이행은 P1/P2에서 `TBD-48-02`로 결정한다.

> **[SEC-28 해소·2026-08-30]** 위 갭(`WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY` 미설정 시 device
> secret 평문 폴백)은 닫혔다. `require_device_secret_cipher`가 prod 추정 환경에서 키가 없으면
> `RuntimeError`로 **부팅을 거부**하고(집행 지점 = `_device_store.build_device_store_from_settings`),
> `encrypt_secret_for_storage`는 `allow_plaintext_fallback=True`를 명시받지 않으면 평문 저장을
> 거부한다. 개발/CI에서만 그 플래그가 켜지며, 그 값은 `cipher is None and not
> settings.production_like`로 계산된다 — 즉 **prod-like에서는 켤 수 없다**.
>
> 하위 호환: 기존 평문 행의 읽기(`resolve_stored_secret` dual-read)는 그대로다 — 이 변경은
> *새 secret의 저장*만 막는다. 기존 평문 행의 재암호화 배치는 여전히 후속이다(슬라이스 73 한계 ①).
>
> 변별력 실측: prod-like 거부 가드와 부팅 배선을 각각 무력화하는 뮤테이션에서 테스트 4건이 red로
> 전환됨을 확인했다(`TestRequireDeviceSecretCipher`·`TestBuildDeviceStoreFromSettings`).

### 7.4 Key Lifecycle

```
GENERATED → ACTIVE → ROTATING → RETIRED → DESTROYED
```

키 회전 시 전체 DB를 한 번에 재암호화하지 않는다. 데이터에 `key_version`을 기록해 점진 재암호화.

```json
{
  "key_id": "kek-user-pii-007",
  "purpose": "USER_PII",
  "version": 7,
  "status": "ACTIVE",
  "created_at": "...",
  "activated_at": "...",
  "retired_at": null
}
```

### 7.5 Secret Management

다음을 소스코드·이미지·커밋된 env 파일에 영구 저장하지 않는다.

```
DB 자격증명
JWT 서명 키
클라우드 LLM/API 키
SMTP 자격증명
OAuth 클라이언트 시크릿
웹훅 시크릿
암호화 키
```

대신 Secret Manager / Vault / Cloud secret service를 사용. 이미지 계약은 "런타임 env 주입만"이 기본.

### 7.6 비밀번호 저장

현재 WhyMath는 OAuth 전용이며 비밀번호 인증을 채택하지 않았다(백로그 SEC-07 D1). 비밀번호 인증을 도입할 경우:

- AES 등 가역 암호화가 아닌 일방향 해싱.
- Argon2id 우선. 환경에 따라 scrypt/PBKDF2.
- 알고리즘, memory_cost, time_cost, parallelism, version까지 기록.

## 8. 토큰·세션

### 8.1 JWT 설계

최소 클레임:

```json
{
  "sub": "usr_123",
  "tenant_id": "tenant_01",
  "roles": ["TEACHER"],
  "scope": ["student:read", "assessment:create"],
  "iat": 1780000000,
  "exp": 1780000900
}
```

JWT payload에 다음은 넣지 않는다: email, phone, address, student details, guardian data. JWT는 서명되지 **암호화된 것은 아니기 때문**.

### 8.2 토큰 수명

- Access Token: 짧게(수분~수십 분).
- Refresh Token: 더 긴 수명 + 회전(rotation) + 재사용 탐지.

현재 WhyMath는 액세스 토큰이 stateless라서 이미 발급된 토큰은 만료까지 유효하다. 이 한계를 문서에 명시한다.

### 8.3 세션 취소

다음 상황에서 세션/권한을 종료할 수 있어야 한다.

```
password reset (도입 시)
MFA reset
account compromise
role change
staff termination
student withdrawal
guardian relationship revoked
```

### 8.4 클라이언트 세션

- iOS: Keychain
- Android: Keystore
- 웹 쿠키: Secure; HttpOnly; SameSite=Lax 또는 Strict
- cookie 기반 인증 시 CSRF token + SameSite + Origin/Referer 검증

## 9. 데이터 보호

### 9.1 PII와 학습 데이터 논리적 분리

```
Identity / PII Store ──internal opaque ID──> Education Data Store
```

학습 DB에는 실명·연락처가 직접 없어야 한다.

### 9.2 가명 ID

```
learner_id: 01JYFG4M9RWPT...
```

금지: 주민번호, 전화번호, 이메일을 식별자로 사용.

### 9.3 데이터 분류

공통 enum:

```
PUBLIC
INTERNAL
CONFIDENTIAL
RESTRICTED
```

| 데이터 | 분류 |
|---|---|
| 개념 정의 | PUBLIC |
| 공개 교육과정 | PUBLIC |
| 내부 콘텐츠 초안 | INTERNAL |
| 문항 원본 | CONFIDENTIAL |
| 학생 학습기록 | CONFIDENTIAL |
| 학생 오개념 프로필 | CONFIDENTIAL |
| 이메일·전화번호 | RESTRICTED |
| 인증정보 | RESTRICTED |

### 9.4 Knowledge Graph 접근 통제

| 그래프 영역 | 분류 |
|---|---|
| Concept Graph | PUBLIC/INTERNAL |
| Problem Bank | LICENSED |
| Student Mastery | CONFIDENTIAL |
| Misconception Profile | CONFIDENTIAL |
| PII | RESTRICTED |

### 9.5 스토리지 보호

- Object Storage: private bucket + short-lived signed URL. public bucket 금지.
- CDN(저작권·유료 콘텐츠): signed URL/cookie + expiry. 42_저작권 모듈과 연결.
- Backup: 운영 DB뿐만 아니라 snapshot, replica, archive까지 암호화. backup.read/restore/delete 권한 분리.
- 개발/스테이징: 운영 PII를 복사하지 않는다. synthetic data 또는 de-identification/masking.

## 10. AI·그래프 보안

### 10.1 RAG 접근 통제

나쁜 구조:

```
AI Tutor → Vector DB 전체 검색
```

좋은 구조:

```
AI Tutor → Authorization Context → Retrieval Policy → Filtered Retrieval → LLM
```

Vector query에도 `tenant_id`, `user_scope`, `content_license`, `security_classification`, `grade`, `role` 필터.

### 10.2 LLM에 개인정보 최소화

```text
학생 김철수(010-....)는 이차함수를...   ← 금지

learner_123:
이차함수 개념 숙련도 0.47
최근 오류 유형 ...                   ← 권장
```

### 10.3 Prompt Injection도 접근통제 문제

Retrieved Content ≠ System Authorization. LLM이 tool을 호출하더라도 다음 구조.

```
LLM → Tool Gateway → Authorization Policy → Actual Tool
```

### 10.4 LLM Tool Authorization

```json
{
  "tool": "get_student_progress",
  "actor": "teacher_123",
  "arguments": { "student_id": "student_456" }
}
```

LLM이 호출했다고 곧바로 실행하지 않고, `teacher_123`이 `student_456`의 담당교사인지 서버에서 확인.

### 10.5 Machine Identity

장기 EOS에서는 사람만 Identity가 아니다.

```
USER, SERVICE, AGENT, JOB, DEVICE, PLUGIN
```

예: `agent.problem_generator`, `agent.content_validator`, `service.analytics`.

## 11. API·서비스 보안

### 11.1 Service-to-Service

"내부 API이므로 신뢰"하지 않는다. Service Identity + TLS + short-lived credentials + scope.

### 11.2 API Scope

AI Tutor 서비스는 `progress:read`, `problem:read`, `hint:create`만 있고 `user:delete`, `admin:create`는 없어야 한다.

### 11.3 Export·Bulk 권한 분리

- `student.read` ≠ `student.export`
- `student.read.one`, `student.read.class`, `student.read.school`, `student.export.school` 분리

### 11.4 Rate Limiting

권한이 있어도 무제한 호출을 허용하지 않는다. 키 조합:

```
IP, user, tenant, API key, endpoint
```

예: 학생 조회 `teacher 100/min`, `admin 500/min`, `service 5000/min`. AI/LLM 엔드포인트에는 비용 기반 DoW(Denial of Wallet) 제한도 추가.

### 11.5 이상 접근 탐지

```
한 교사가 2분 동안 학생 10,000명 조회
```

권한이 있더라도 비정상. Authorization + Behavior Monitoring 조합.

### 11.6 리스크 기반 Access Control(P2)

```
risk = f(user, device, IP, geo, behavior, action, resource)
```

하지만 AI 모델이 단독으로 계정을 영구 차단하지 않고 deterministic security policy와 결합.

### 11.7 AppSec 기반

- **CSRF**: cookie 인증 시 CSRF token + SameSite + Origin/Referer 검증.
- **XSS**: CSP, output escaping, HTML sanitization. XSS가 발생하면 access control도 무력화될 수 있다.
- **SQL Injection**: 프로젝트 규칙은 "ORM/쿼리 빌더만, 원시 SQL 최소화". 파라미터화된 쿼리를 사용. 예:
  ```python
  # 나쁜 예
  session.execute(text(f"SELECT * FROM users WHERE id = '{user_id}'"))

  # 좋은 예
  session.execute(select(User).where(User.id == user_id))
  ```
- **GraphQL**: authorization, query depth/complexity, pagination, field-level controls, introspection policy. GraphQL 도입이 결정된 후 적용.
- **파일 업로드**: 확장자·MIME·magic byte, 파일명 재생성, 크기 제한, 악성파일 검사, 격리 저장, executable path 배치 금지.

## 12. 감사·보안 이벤트

### 12.1 204 교육 이벤트와 분리

```
Educational Event   (problem.attempted, hint.requested, concept.mastered)
Security Event      (login.failed, access.denied, token.reuse.detected)
Audit Event         (admin.role.changed, pii.exported, account.deleted)
```

### 12.2 보안 이벤트 예시

```json
{
  "event_id": "sec_evt_123",
  "event_type": "ACCESS_DENIED",
  "actor_id": "usr_001",
  "resource_type": "student_profile",
  "resource_id": "stu_009",
  "policy_id": "policy.student.v14",
  "reason_code": "NOT_ASSIGNED_TEACHER",
  "risk_score": 62,
  "timestamp": "2026-08-20T01:00:00Z"
}
```

### 12.3 Audit Trail

48번의 모든 보안 결정은 90번으로 전달. 거부 이유도 내부 감사에 기록.

외부 사용자: `403 Forbidden`
내부 감사: `TENANT_MISMATCH`, `CLASS_SCOPE_MISMATCH`, `MISSING_PERMISSION`, `MFA_REQUIRED`

### 12.4 감사로그 변조 방지

append-only, restricted write/delete, retention policy, integrity verification.

### 12.5 Policy Versioning

"2026년 8월 1일에 이 사용자가 왜 접근 가능했는가?"를 재현해야 하므로 모든 보안정책은 버전을 갖는다.

## 13. 운영·개발 보안

### 13.1 환경 격리

dev/test/staging/production의 권한·키·DB 분리. 금지:

```
same DB password
same JWT private key
same API key
```

### 13.2 Production 접근

개발자가 production DB에 상시 직접 접근하지 않는다.

```
Developer → Approved Tool / Bastion → JIT Access → Production
```

모든 접근은 감사.

### 13.3 CI/CD 권한 분리

```
CI_READ, CI_BUILD, CI_DEPLOY_STAGING, CI_DEPLOY_PROD
```

CI가 DB superuser credential을 가지고 있으면 안 된다.

### 13.4 Supply Chain

```
dependency scanning, SAST, DAST, secret scanning, container scanning, SBOM, signed artifacts
```

### 13.5 Security Gate

배포 전:

```
Unit / Integration / Security Tests
Dependency Scan / Secret Scan / SAST
Authorization Test
```

### 13.6 Authorization Test 자동화

pytest 계약 테스트 + CI gate:

```
STUDENT A → STUDENT B record       → DENY
TEACHER classA → student classA      → ALLOW
TEACHER classA → student classB      → DENY
PARENT A → own child                 → ALLOW
PARENT A → unrelated child           → DENY
```

### 13.7 Security Regression Test

새 기능 추가 시 권한이 넓어지지 않았는지 자동 검증.

```
v10: teacher → class students
v11: teacher → all students          → 자동 경고
```

### 13.8 Threat Modeling

각 핵심 서비스마다 Asset, Actor, Trust Boundary, Threat, Control, Residual Risk 정의.

## 14. 법규·표준 매핑

### 14.1 한국 법규

개인정보 보호법 시행령 제30조(안전성 확보조치) 요구를 EOS에 매핑.

| 규제 요구 | EOS |
|---|---|
| 접근권한 부여·변경·말소 | IAM / Authorization |
| 인증수단 | 46 Identity |
| 침입 탐지·차단 | Security Monitoring |
| 비밀번호 일방향 암호화 | Credential Store (도입 시) |
| 개인정보 저장 암호화 | Data Encryption |
| 개인정보 전송 암호화 | TLS |
| 접속기록 | 90 Audit |
| 접속기록 안전보관 | Immutable Audit |
| 악성프로그램 대응 | Endpoint/Workload Security |
| 내부관리계획 | Security Governance |

「개인정보의 안전성 확보조치 기준」(개인정보보호위원회고시 제2026-9호, 2026-07-01 시행)은 위 세부 기준의 출처.

### 14.2 OWASP ASVS 5.0 / NIST

- OWASP ASVS 5.0 Level 2를 baseline. 고위험 관리자·개인정보 처리에는 개별 control 추가.
- NIST SP 800-63B-4: 인증 보증 수준(AAL). 고위험 관리자 계정은 phishing-resistant(Passkey/WebAuthn) 권장.

## 15. 데이터 모델·메타데이터

### 15.1 보안 Entity(예시)

```
users, roles, permissions, user_roles, role_permissions
tenants, organizations, memberships
relationships, resource_permissions
security_policies, policy_versions
access_grants, access_requests
encryption_keys_metadata, secret_metadata
security_events
```

### 15.2 Permission namespace

```
learning.progress.read      learning.progress.update
assessment.exam.create      assessment.exam.publish
content.problem.read        content.problem.edit
privacy.pii.read            privacy.pii.export
security.role.manage        security.policy.manage
audit.event.read
```

### 15.3 Policy를 EOS 1급 Entity로

`Policy`를 Entity Registry에 추가해 버전·감사·릴리즈(44)와 통합.

### 15.4 205 공통 메타데이터·206 리소스 레지스트리 연결

```json
{
  "security": {
    "classification": "CONFIDENTIAL",
    "tenant_scope": "tenant_123",
    "contains_pii": true,
    "encryption_required": true,
    "audit_required": true
  }
}
```

Educational Resource Registry(206):

```json
{
  "resource_id": "...",
  "license": "SCHOOL_ONLY",
  "security_classification": "CONFIDENTIAL",
  "allowed_audiences": ["TEACHER", "STUDENT"]
}
```

보안은 사용자만 통제하는 것이 아니라 Identity ↔ Policy ↔ Resource 관계.

## 16. 요구사항 ID

이 문서에서 사용하는 요구사항 ID는 `EOS-SEC-*` 접두사다(백로그 `SEC-*` 태스크와 구분).

```
EOS-SEC-AUTHZ-001  모든 보호 자원은 명시적 ALLOW가 없는 경우 접근을 거부한다.
EOS-SEC-AUTHZ-002  모든 학생 데이터 접근은 tenant 및 relationship 검증을 수행한다.
EOS-SEC-AUTHZ-003  API 호출마다 객체 소유권/관계를 다시 검증한다(IDOR/BOLA 방지).
EOS-SEC-ENC-001    민감정보 전송은 승인된 TLS 설정을 사용한다.
EOS-SEC-ENC-002    고위험 개인정보는 저장 시 봉투 암호화한다.
EOS-SEC-KEY-001    암호키는 애플리케이션 데이터 저장소와 분리한다.
EOS-SEC-SECRET-001 시크릿은 런타임 env 주입만 사용하고 소스/이미지에 저장하지 않는다.
EOS-SEC-AI-001     LLM 또는 Agent가 호출한 모든 privileged tool은 서버측 authorization을 수행한다.
EOS-SEC-AUDIT-001  모든 보안 거부 결정은 감사 이벤트로 남긴다.
EOS-SEC-TEST-001   새 기능은 인가 회귀 테스트를 통과해야 한다.
```

## 17. Security Definition of Done

기능별 DoD에 다음을 추가:

- [ ] Authentication 필요한가?
- [ ] Authorization policy가 정의되었는가?
- [ ] Tenant isolation이 적용됐는가?
- [ ] Object-level authorization이 있는가?
- [ ] Field-level authorization이 필요한가?
- [ ] PII가 포함되는가?
- [ ] Encryption 적용 여부를 검토했는가?
- [ ] Audit event가 정의됐는가?
- [ ] Security event가 정의됐는가?
- [ ] Abuse/rate limit을 검토했는가?
- [ ] Secret이 추가되었는가?
- [ ] Threat model이 갱신됐는가?
- [ ] Authorization 테스트가 있는가?

## 18. 단계별 범위(P0/P1/P2)

### P0 — 현행 WhyMath를 강화하는 EOS 초기 필수

| 영역 | EOS 요구 | 현행 WhyMath 상태 |
|---|---|---|
| Identity 연계 | 46과 연계 | ✅ OAuth + JWT (`security.py`, `api/auth.py`) |
| RBAC | 역할 기반 인가 | 🟡 2역할(STUDENT/CONTENT_ADMIN)만 |
| Tenant Isolation | tenant_id 1급 | ⬜ 테넌시 개념 없음 |
| Object-level Authorization | IDOR/BOLA 방지 | 🟡 본인 조회 게이트, 일부 미착지(job 소유권 등) |
| Deny by Default | 명시적 ALLOW | 🟡 `require_role` 적용 표면 한정 |
| TLS | 전송 구간 암호화 | 인프라 단계 |
| Password hashing | 비밀번호 해싱 | N/A (OAuth 전용) |
| DB/backups 암호화 | 저장 암호화 | 🟡 필드 수준만, 디스크/TDE 인프라 |
| Secret Manager | 시크릿 관리 | 🟡 env 주입, Vault 미도입 |
| PII 최소화 | pseudonym | ✅ email 해시, opaque learner_id |
| Security Audit | 감사 | 🟡 3테이블, admin access 감사 미배선 |
| Admin MFA | 관리자 재인증 | ⬜ 미구현 |
| Rate Limiting | 요청 제한 | ✅ (`api/_rate_limit.py`) |
| Authorization Integration Test | 인가 테스트 | 🟡 매트릭스 테스트 있음, 런타임 소비는 0 |

### P1 — EOS 전환기

- ABAC
- Guardian/Teacher ReBAC
- Field-Level Authorization → `data/access_matrix.json` 런타임 소비
- Field-Level Encryption → 현행 `_crypto.py` 일반화
- KMS
- Key Rotation
- JIT Admin Access
- Anomaly Detection
- Security Event Pipeline

### P2 — 고급

- Policy-as-Code / Central PDP
- Agent Identity / Service Identity
- Advanced Zero Trust(mTLS·단기 자격증명)
- 리스크 기반 Authorization
- Automated Access Review

## 19. 설계 안티패턴

아래는 의도적으로 피해야 할 설계다.

```
❌ ADMIN 하나에 모든 권한
❌ 프론트엔드에서만 권한 검사
❌ RBAC만 사용
❌ tenant_id 검사 누락
❌ URL ID만 바꾸면 다른 학생 조회 가능
❌ 개발자가 production DB 상시 접근
❌ API Key 소스코드 저장
❌ JWT에 개인정보 저장
❌ 비밀번호 AES 암호화 저장
❌ 암호키를 DB와 같은 위치에 저장
❌ LLM이 DB Tool 직접 호출
❌ Vector DB 전체를 AI에게 검색 허용
❌ 미성년 학생 데이터와 일반 콘텐츠 동일 정책
❌ 관리자 대량 Export 무감사
❌ 보안로그에 PII/비밀번호 기록
❌ 백업 암호화 누락
❌ 운영 데이터를 dev에 복사
❌ 모든 microservice가 DB superuser
```

---

# 제2부. 현행 WhyMath 매핑 (2026-08-25 최초 실측 · 2026-09-11 SEC-26/27/29 반영 갱신)

| EOS 영역 | WhyMath 현행 | 파일/자산 | 판정 |
|---|---|---|---|
| JWT 발급/검증 | jose 기반, access/refresh 구분, fail-fast | `security.py` | ✅ 충족 |
| OAuth + refresh 회전/재사용 탐지 | 카카오·네이버 OAuth, rotation, reuse detection, 전체 로그아웃 | `api/auth.py`, `refresh_token_session.py` | ✅ 충족 |
| Role enum | STUDENT, CONTENT_ADMIN 2종뿐 | `schema/enums.py:1473` | 🟡 부분 |
| 동의·미성년 검사 | `is_minor` 파생, 보호자 동의 부여/철회/만료 | `api/_auth.py:get_consented_user` | 🟡 부분 (expires_at writer 없음) |
| 필드 수준 암호화 | AES-256-GCM, 3개 자산별 키, MultiKeyCipher 회전, dialogue content만 prod fail-closed; device secret 평문 폴백 갭 있음 | `api/_crypto.py` | 🟡 부분 |
| Log PII 스크러버 | 시크릿/이메일/전화번호/학생 발화 마스킹, 예외 타입명 보존 | `ops/log_scrubber.py` | ✅ 충족 |
| 감사 테이블 | DeletionAudit, PrivacyAudit, DefectReport | `db/models/audit.py` | ✅ 구조 충족 |
| 관리자 접근 감사 | `record_admin_access_audit`(관리자→학생 개인정보 열람) 호출부 여전히 0곳(ADMIN-06 콘솔 선행 대기) — 콘텐츠 CUD(개념·문항)는 신설 5번째 event_kind `content_mutation`으로 별도 배선(SEC-29, `api/concepts.py`·`api/problems.py` 6라우터) | `privacy/audit.py`, `api/concepts.py`, `api/problems.py` | 🟡 부분(콘텐츠축 충족·개인정보열람축 미착지) |
| Rate Limiting | 슬라이딩 윈도우, 메모리/Redis, 카테고리별 | `api/_rate_limit.py` | ✅ 충족 |
| CORS/보안 헤더 미들웨어 | TrustedHost→CORS→보안헤더 순 상시 등록, allowlist 비면 deny-by-default(네이티브 앱 무영향), prod에서 HSTS/CSP 추가(SEC-26) | `app.py::create_app`, `config.py` | ✅ 충족 |
| 테넌시/RLS | 없음 | — | ⬜ 미착지(EOS 단계) |
| Service-to-Service 인증 | 내부망 신뢰 가정 | — | ⬜ 미착지(EOS 단계) |
| Job 소유권 검사 | `/v1/jobs/{id}` job↔user 매핑 적재·대조(`JobOwnership`, SEC-27) — 매핑 부재·타인 소유 둘 다 404로 통일 | `db/models/job_ownership.py`, `app.py` | ✅ 충족 |
| access_matrix 런타임 소비 | `data/access_matrix.json`은 계약 테스트만 읽음 | `tests/backend/schema/test_access_matrix.py` | 🟡 부분 |
| 비밀번호 인증 | 미채택(OAuth 전용), passlib 제거 | `pyproject.toml:38` | N/A |
| Secret 관리 | env 주입, 이미지 시크릿 0 | `Dockerfile`, CI | 🟡 부분 |

---

# 제3부. 결정표

## 확정 결정(이 문서에서 닫음)

| ID | 결정 | 근거 |
|---|---|---|
| DEC-48-01 | 요구사항 ID는 `EOS-SEC-*` 접두사 사용 | 백로그 `SEC-01~24`와 충돌 방지 |
| DEC-48-02 | 비밀번호 인증은 현행과 같이 미채택, 비밀번호 해싱 절은 "도입 시" 조걶로 한정 | OAuth 전용 결정(SEC-07 D1) |
| DEC-48-03 | 필드 수준 AES-256-GCM + 자산별 키 분리 + MultiKeyCipher 회전은 EOS P0 암호화 기반선; KEK/DEK/KMS 봉투 암호화는 P1/P2(`TBD-48-02`)로 이행 | 현행 `_crypto.py`가 P0 기반선, 완전 봉투 미도입 |
| DEC-48-04 | 액세스 토큰은 stateless JWT + 짧은 TTL + refresh 회전을 유지, 즉시 취소 한계를 문서화 | 현행 설계 유지 |
| DEC-48-05 | 멀티테넌시·RLS·12개 역할은 EOS 단계로 분리, 현행은 2역할 유지 | "좌석 없는 역할 안 만든다" 원칙, 테넌시 부재 |
| DEC-48-06 | 보안 이벤트는 204 교육 이벤트와 분리 | 감사/보안/교육 3종 구분 |
| DEC-48-07 | AI tool 호출은 서버측 재인가 필수 | LLM 프롬프트 인젝션 위험 |

## 미결 결정(추후 별도 결정/의존 모듈 필요)

| ID | 미결 항목 | 의존 | 시기 |
|---|---|---|---|
| TBD-48-01 | 정책 엔진: OPA / 자체 DSL / 중앙 Python authorize | 47, 90 | ReBAC 도입기 |
| TBD-48-02 | KMS/HSM 선택(cloud KMS vs Vault) | infra | 키 종류 5+ 또는 B2B 테넌트 |
| TBD-48-03 | relationship 테이블 설계(47 보호자 관계 정규화 이후) | 47 | ReBAC 도입기 |
| TBD-48-04 | 리스크 기반 Access Control 모델 | — | P2 |
| TBD-48-05 | GraphQL 도입 여부(도입 시 보안 규칙 적용) | — | 별도 아키텍처 결정 |
| TBD-48-06 | 고위험 작업 step-up: Passkey/WebAuthn vs TOTP vs 재인증 TTL | 46 | 관리자 콘솔 착지기 |
| TBD-48-07 | 감사로그 무결성 메커니즘(해시 체인 vs WORM) | 90 | 90 문서 선행 |
| TBD-48-08 | 데이터 보존·파기 기한 세부 정책 | 47 | 47 문서 선행 |

---

# 제4부. 착지 순서(46/47/90 의존)

48번은 다음 선행 모듈에 의존한다. 현재 저장소에는 44, 011_1 문서만 착지돼 있고 46/47/90 문서는 없다.

```
46 Authentication (인증·Identity)
   ↓
47 Privacy & Consent (동의·보호자 관계·법적 근거)
   ↓
48 Security & Access Control (이 문서) — P0는 현행 강화, P1은 46/47이 먼저
   ↓
90 Audit (보안 이벤트·감사 변조 방지·정책 버전 재현)
```

권장 착지 단계:

1. **48-P0 잔여**(독립 가능): `access_matrix.json` 런타임 소비, expires_at writer, `record_admin_access_audit`(관리자→학생 개인정보 열람 — ADMIN-06 콘솔 선행 대기). CORS/보안 헤더(SEC-26)·job 소유권 검사(SEC-27)·콘텐츠 CUD 감사(SEC-29)는 착지 완료.
2. **46 먼저**: 인증·역할·MFA/Passkey 결정.
3. **47 먼저**: 동의·보호자 관계·데이터 처리 근거·보존기간.
4. **48-P1 EOS 확장**: ReBAC/ABAC, tenant_id, RLS, 관리자 콘솔.
5. **90 먼저/동시**: 보안 이벤트 영속·변조 방지·정책 버전 재현.
6. **48-P2 고급**: Central PDP, Agent Identity, 리스크 기반.

---

# 부록 A. EOS 주요 Threat Catalog

```
Account takeover
Credential stuffing
Privilege escalation
IDOR/BOLA
Cross-tenant access
Mass data export
Insider threat
Token theft
Session hijacking
API key leakage
Secret leakage
Database exfiltration
Backup leakage
Ransomware
Supply-chain compromise
Prompt injection
RAG data leakage
AI tool privilege escalation
Graph data leakage
Misconfigured cloud storage
```

---

# 부록 B. 참조

- 「개인정보 보호법」시행령 제30조(개인정보의 안전성 확보조치)
- 「개인정보의 안전성 확보조치 기준」(개인정보보호위원회고시 제2026-9호, 2026-07-01 시행) — [law.go.kr](https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000281400&chrClsCd=010201)
- NIST SP 800-63B-4 Digital Identity Guidelines
- OWASP ASVS 5.0
- OWASP Cheat Sheet Series(Transport Layer Protection, Cryptographic Storage, Authentication, Authorization, JWT, Password Storage, CSRF, XSS, SQL Injection, GraphQL)
- `docs/standards/superhuman_verification_standard.md`
- `docs/standards/security_privacy.md`
- `docs/legal/pipa_data_matrix.md`
