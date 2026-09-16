"""ORM 모델 패키지 — 모든 테이블을 import해 `Base.metadata`에 등록한다.

alembic autogenerate(env.py의 `target_metadata = Base.metadata`)가 테이블을 인식하려면
모델 클래스가 *import되어 메타데이터에 등록*되어 있어야 한다. env.py가
`import whymath_backend.db.models`만 하면 이 `__init__`이 아래 모델들을 끌어와 등록한다.

수록 도메인:
  - 도메인1 Problem (§3.1·§3.2): Problem·ProblemStep·ProblemRelation.
  - 도메인2 Concept (§4.2): Concept·ConceptEdge·ProblemConcept·ConceptFusion.
  - 도메인8 Provenance (§10.1): ContentProvenance·GenerationLog.
  - 도메인3 User (§5.1·§5.2): UserProfile·UserTrackHistory·UserPersonaHistory·UserStateSnapshot.
  - 도메인4 Activity (§6.1): LearningSession·ProblemAttempt·AttemptEvent.
  - EOS-32 AnswerSubmission (attempt 내 다회 제출 시퀀스 정규화 — 32_learning_history §4).
  - EOS-45 HintUsage (힌트 횟수·레벨·열람시간 1급 데이터화 — used_hint 병행·32 §4).
  - EOS-46 StudentSolutionStep (학생 풀이 step 정규 기록 — ADR-002·WH-S SolutionNode와 무관).
  - 도메인5 Dialogue (§7.1): Dialogue·DialogueTurn.
  - 도메인6 Assessment (§8.1): Assessment·ConceptMasteryHistory.
  - 도메인7 TimeSeries (§9.1): DailyLearningMetrics·ProblemSolveTimeDistribution·
    UserBehaviorMetrics.
  - v1.1 CurriculumEntry (다국 커리큘럼 매트릭스 셀).
  - v1.1 TextbookMapping·TextbookUnit (교과서 매핑 — 중첩 → 관계형 2테이블).
  - EOS-49 ConceptVersion (개념 버전 테이블 — `concept.current_published_version_id`의 FK
    타깃. 이 등록이 빠지면 autogenerate가 실재하는 테이블을 **삭제 대상으로 본다**).
  - 슬105 MisconceptionEmbedding (L4 오개념 의미 매칭 pgvector 영속 — `vector` 컬럼 소유).
  - 슬3(개념그래프 아크) ConceptEmbedding (L1 개념 의미검색 pgvector 영속 — UC 키·`vector` 컬럼).
  - 개념그래프 소비 슬1 ConceptNode (L1 개념 메타 PG 프로젝션 — UC 키·검색 enrichment 백킹).
  - 원자 Phase 2b AtomEmbedding (L1 원자 의미검색 pgvector 영속 — code 키·`vector` 컬럼).
  - S2-c ProblemEmbedding (자체생성 동등문제 dedup pgvector 백킹 — AtomEmbedding의 문제 짝).
  - P1-2 AchievementStandard·ConceptStandardLink (NCIC 성취기준 영속 + 개념↔성취기준 N:M 링크).
  - CUR-07 AchievementLevelUnit (단원 단위 성취수준 등급 커버리지 — FK 없음·독립 테이블).
  - PIPA §22-2 ParentalConsent (14세 미만 법정대리인 동의 GRANT 감사 — user_profile FK).
  - SEC-09 PrivacyAudit (개인정보 감사 4종 — 반출·동의변경·관리자접근·역할변경·user_id FK 아님).
  - RPT-01 DefectReport (학생 결함 신고 — 카테고리+problem_id만, user_id 컬럼 자체 없음).
모든 테이블이 한 `Base.metadata`에 모여 문자열 FK 타깃(`problem.problem_id`·
`concept.concept_id`·`user_profile.user_id`·`learning_session.session_id`·
`problem_attempt.attempt_id`·`dialogue.dialogue_id`·`textbook_mapping.isbn` 등)이 해소된다.

도메인4~7의 hypertable 5종(attempt_event·concept_mastery_history·daily_learning_metrics·
problem_solve_time_distribution·user_behavior_metrics)은 ORM에선 *일반 테이블*이다
(create_hypertable 변환은 마이그레이션 레벨 — 메인 처리). §6~§9 DDL이 REFERENCES를 명시하지
않은 컬럼(target_concept_id·stuck_at_concept_id·attempt_event/시계열 FK들)은 FK가 아니다.
"""

from __future__ import annotations

from whymath_backend.db.models.achievement_level_unit import AchievementLevelUnit
from whymath_backend.db.models.achievement_standard import AchievementStandard
from whymath_backend.db.models.activity import (
    AttemptEvent,
    LearningSession,
    ProblemAttempt,
)
from whymath_backend.db.models.answer_submission import AnswerSubmission
from whymath_backend.db.models.assessment import (
    Assessment,
    ConceptMasteryHistory,
)
from whymath_backend.db.models.atom_embedding import AtomEmbedding
from whymath_backend.db.models.atom_node import (
    ATOM_REVIEW_STATUS_AI_ESTIMATED,
    AtomNode,
)
from whymath_backend.db.models.atom_probe import (
    ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED,
    AtomProbe,
)
from whymath_backend.db.models.audit import DefectReport, DeletionAudit, PrivacyAudit
from whymath_backend.db.models.concept import (
    Concept,
    ConceptEdge,
    ConceptFusion,
    ProblemConcept,
)
from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
    ConceptContent,
)
from whymath_backend.db.models.concept_embedding import ConceptEmbedding
from whymath_backend.db.models.concept_node import ConceptNode
from whymath_backend.db.models.concept_standard_link import ConceptStandardLink
from whymath_backend.db.models.concept_version import ConceptVersion
from whymath_backend.db.models.concept_visual_style import ConceptVisualStyle
from whymath_backend.db.models.concept_visualization import ConceptVisualization
from whymath_backend.db.models.curriculum_entry import CurriculumEntry
from whymath_backend.db.models.curriculum_framework import CurriculumFramework
from whymath_backend.db.models.curriculum_version import CurriculumVersion
from whymath_backend.db.models.dead_end_log import DeadEndLog
from whymath_backend.db.models.device import DeviceCredential
from whymath_backend.db.models.dialogue import (
    Dialogue,
    DialogueTurn,
)
from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.db.models.evidence_link import EvidenceLink
from whymath_backend.db.models.formula_node import (
    FORMULA_REVIEW_STATUS_DEFAULT,
    FormulaNode,
)
from whymath_backend.db.models.hint_usage import HintUsage
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.models.learner_state import LearnerStateRecord
from whymath_backend.db.models.misconception_catalog import MisconceptionCatalog
from whymath_backend.db.models.misconception_crosslink import MisconceptionCrosslink
from whymath_backend.db.models.misconception_embedding import MisconceptionEmbedding
from whymath_backend.db.models.misconception_hypothesis import (
    MisconceptionHypothesisRecord,
)
from whymath_backend.db.models.misconception_relation import MisconceptionRelation
from whymath_backend.db.models.parental_consent import ParentalConsent
from whymath_backend.db.models.pedagogy_dsl import (
    CONTENT_SLOT_STATUS_DEFAULT,
    UNIT_SPEC_STATUS_DEFAULT,
    LearningObjective,
    PedagogyContentSlot,
    PedagogyPack,
    UnitSpec,
)
from whymath_backend.db.models.problem import (
    Problem,
    ProblemRelation,
    ProblemStep,
)
from whymath_backend.db.models.problem_embedding import ProblemEmbedding
from whymath_backend.db.models.problem_type_node import (
    PROBLEM_TYPE_REVIEW_STATUS_DEFAULT,
    ProblemTypeNode,
)
from whymath_backend.db.models.provenance import (
    ContentProvenance,
    GenerationLog,
)
from whymath_backend.db.models.refresh_token_session import RefreshTokenSession
from whymath_backend.db.models.review_timer_event import ReviewTimerEvent
from whymath_backend.db.models.rights import (
    ContentRightsLink,
    ContentSourceLink,
    DerivationEdge,
    RightsEntity,
    RightsHolderEntity,
    SourceEntity,
)
from whymath_backend.db.models.skill_node import (
    SKILL_REVIEW_STATUS_DEFAULT,
    SkillNode,
)
from whymath_backend.db.models.solution_node import (
    NodeVerifyStatus,
    SolutionNode,
)
from whymath_backend.db.models.solution_path import SolutionPath
from whymath_backend.db.models.strategy_node import (
    STRATEGY_REVIEW_STATUS_DEFAULT,
    StrategyNode,
)
from whymath_backend.db.models.student_solution_step import StudentSolutionStep
from whymath_backend.db.models.textbook_mapping import (
    TextbookMapping,
    TextbookUnit,
)
from whymath_backend.db.models.timeseries import (
    DailyLearningMetrics,
    ProblemSolveTimeDistribution,
    UserBehaviorMetrics,
)
from whymath_backend.db.models.user import (
    UserPersonaHistory,
    UserProfile,
    UserStateSnapshot,
    UserTrackHistory,
)
from whymath_backend.db.models.verified_lemma import VerifiedLemma
from whymath_backend.db.models.verified_solution import (
    VerifiedSolution,
    WhsSolutionGrade,
)

__all__ = [
    # 도메인1 Problem
    "Problem",
    "ProblemStep",
    "ProblemRelation",
    # 도메인2 Concept
    "Concept",
    "ConceptEdge",
    "ProblemConcept",
    "ConceptFusion",
    # 도메인8 Provenance
    "ContentProvenance",
    "GenerationLog",
    # 도메인3 User
    "UserProfile",
    "UserTrackHistory",
    "UserPersonaHistory",
    "UserStateSnapshot",
    # 도메인4 Activity
    "LearningSession",
    "ProblemAttempt",
    "AttemptEvent",
    # EOS-32: AnswerSubmission (attempt 내 다회 제출 시퀀스 정규화 — evidence_links 1급 입력)
    "AnswerSubmission",
    # EOS-45: HintUsage (힌트 횟수·레벨·열람시간 1급 데이터화 — used_hint 병행·hint_rate 원천)
    "HintUsage",
    # EOS-46: StudentSolutionStep (학생 풀이 step 정규 기록 — ADR-002·WH-S SolutionNode와 무관)
    "StudentSolutionStep",
    # EOS-54: ReviewTimerEvent (HIT 검수 타이머 이벤트 — 검수자 텔레메트리·학생 축 없음)
    "ReviewTimerEvent",
    # 도메인5 Dialogue
    "Dialogue",
    "DialogueTurn",
    # 도메인6 Assessment
    "Assessment",
    "ConceptMasteryHistory",
    # 도메인7 TimeSeries
    "DailyLearningMetrics",
    "ProblemSolveTimeDistribution",
    "UserBehaviorMetrics",
    # v1.1 CurriculumEntry
    "CurriculumEntry",
    # CUR-10: CurriculumFramework/CurriculumVersion (EOS Curriculum Semantic Backbone)
    "CurriculumFramework",
    "CurriculumVersion",
    # v1.1 TextbookMapping
    "TextbookMapping",
    "TextbookUnit",
    # 슬라이스 23: DeviceCredential
    "DeviceCredential",
    # 슬라이스 57: DeletionAudit
    "DeletionAudit",
    # SEC-09: PrivacyAudit (개인정보 감사 4종 — 반출·동의변경·관리자접근·역할변경)
    "PrivacyAudit",
    # RPT-01: DefectReport (학생 결함 신고 — user_id 컬럼 없음, append-only)
    "DefectReport",
    # Phase B.2: MisconceptionCatalog (M-id 오개념 콘텐츠 카탈로그·mis_id PK·기존 kebab 체계와 별개)
    "MisconceptionCatalog",
    # 오개념 정체성 통합 골격: MisconceptionCrosslink (kebab-id ↔ M-id N:M 매핑·read-time 해석)
    "MisconceptionCrosslink",
    # 슬라이스 105: MisconceptionEmbedding (pgvector 영속)
    "MisconceptionEmbedding",
    # WH-1 2단계: MisconceptionHypothesisRecord (활성 오개념 가설 per-student 영속·§8.4)
    "MisconceptionHypothesisRecord",
    # MISC-04: MisconceptionRelation (오개념 전용 관계셋 — caused_by·variant_of·개념그래프 격리)
    "MisconceptionRelation",
    # WH-1 2단계 §2.3: EvidenceLink (학습 증거 그래프·삭제권 FK CASCADE·polarity CHECK)
    "EvidenceLink",
    # 교수법 DSL(L2): EvidenceEvent (학습목표별 유형 달성 증거 하이퍼테이블·B1 봉투 암호화)
    "EvidenceEvent",
    # 교수법 DSL(L3): UnitSpec·PedagogyPack·LearningObjective·PedagogyContentSlot
    #   (7유형→팩→증거·knowledge_type native enum·provenance FK 위임·M1 fail-closed)
    "UnitSpec",
    "PedagogyPack",
    "LearningObjective",
    "PedagogyContentSlot",
    "UNIT_SPEC_STATUS_DEFAULT",
    "CONTENT_SLOT_STATUS_DEFAULT",
    # 슬라이스 3(개념그래프 아크): ConceptEmbedding (L1 개념 의미검색 pgvector 영속·UC 키)
    "ConceptEmbedding",
    # 개념그래프 소비 슬1: ConceptNode (L1 개념 메타 PG 프로젝션·UC 키·검색 enrichment 백킹)
    "ConceptNode",
    # 원자 Phase 3 Slice 1: ConceptContent (콘텐츠 4종 PG 프로젝션·code 키·K-12/대학·additive)
    "ConceptContent",
    "ConceptVisualization",
    # ARCH-14 ③: ConceptVisualStyle (권장 시각화 양식 Overlay·code 키·슬88 컬럼 이관·Concept Purity)
    "ConceptVersion",
    "ConceptVisualStyle",
    "CONTENT_REVIEW_STATUS_AI_ESTIMATED",
    "CONTENT_SCOPE_K12",
    "CONTENT_SCOPE_UNIVERSITY",
    # 원자 마이그레이션 Phase 2a: AtomNode (L1 원자 메타 PG 프로젝션·code 키·검색 enrichment 백킹)
    "AtomNode",
    "ATOM_REVIEW_STATUS_AI_ESTIMATED",
    # 원자 Phase 3 Slice 3: AtomProbe (②진단문항·③소크라테스 PG 프로젝션·code 키·additive)
    "AtomProbe",
    "ATOM_PROBE_REVIEW_STATUS_AI_ESTIMATED",
    # 원자 마이그레이션 Phase 2b: AtomEmbedding (L1 원자 의미검색 pgvector 영속·code 키·vector 컬럼)
    "AtomEmbedding",
    "ProblemEmbedding",
    # WH-S S1: SolutionNode (풀이 경로 트리 노드·§2.1·오프라인 솔버 상태) + 검증 상태 enum
    "SolutionNode",
    "NodeVerifyStatus",
    # WH-S S1 §2.3: DeadEndLog (실패 접근 로그·멱등 (problem,state,action) UNIQUE)
    "DeadEndLog",
    # WH-S S1 §2.4: VerifiedSolution (검증 풀이 저장소·다중 풀이) + 등급 enum(verified/unverified)
    "VerifiedSolution",
    "WhsSolutionGrade",
    # WH-S S1 §2.2: VerifiedLemma (검증 중간 결과 저장소·재사용·멱등 (problem,key) UNIQUE)
    "VerifiedLemma",
    # S4-09(D1): SolutionPath (풀이 경로 헤더·solution_paths·단계는 problem_step additive 컬럼)
    "SolutionPath",
    # OAuth-a3b: RefreshTokenSession (리프레시 토큰 서버측 취소 allowlist·PK=jti)
    "RefreshTokenSession",
    # LIC-01: Rights & Provenance Infrastructure
    "SourceEntity",
    "RightsHolderEntity",
    "RightsEntity",
    "ContentSourceLink",
    "ContentRightsLink",
    "DerivationEdge",
    # Part 2 Phase 2a: SkillNode (L1 스킬 메타 PG 프로젝션·skill_id 키·behavior_area native enum)
    "SkillNode",
    "SKILL_REVIEW_STATUS_DEFAULT",
    # Part 2 Phase 3: ProblemTypeNode (L1 문제유형 메타 PG 프로젝션·problem_type_id 키·enum 없음)
    "ProblemTypeNode",
    "PROBLEM_TYPE_REVIEW_STATUS_DEFAULT",
    # Part 2 Phase 5a: FormulaNode (L1 canonical 수식 메타 PG 프로젝션·formula_id 키·enum 없음)
    "FormulaNode",
    "FORMULA_REVIEW_STATUS_DEFAULT",
    # Part 2 Phase 6a: StrategyNode (L1 문제공략 전략 메타 PG 프로젝션·strategy_id 키·enum 없음)
    "StrategyNode",
    "STRATEGY_REVIEW_STATUS_DEFAULT",
    # PIPA §22-2: ParentalConsent (14세 미만 법정대리인 동의 GRANT 감사·surrogate UUID PK)
    "ParentalConsent",
    # P1-2: AchievementStandard (NCIC 성취기준 영속·norm_id PK·official_code 비유일)
    "AchievementStandard",
    # P1-2: ConceptStandardLink (개념↔성취기준 N:M 연결·norm_id 실 FK·link_id UUID PK)
    "ConceptStandardLink",
    # CUR-07: AchievementLevelUnit (단원 단위 성취수준 등급 커버리지·자연키(school_level,subject,
    # unit)·FK 없음 — 개별 성취기준 연결은 실측 근거 부족으로 범위 밖)
    "AchievementLevelUnit",
    # SEC-27: JobOwnership (비동기 QUALITY 작업 소유권·job_id(String) PK = Celery 태스크 id)
    "JobOwnership",
    # EOS-103: LearnerStateRecord (학습자 현재 상태 1행 — LearnerState 좌석 2번째 테이블.
    # 숙련·오개념 맵은 담지 않는다(각자 정본 보유) — 생산자가 없던 curriculum/objective 축과
    # 생성 시점만 영속한다).
    "LearnerStateRecord",
    # EOS-49: ConceptVersion (Concept 좌석 4번째 테이블 — concept.current_published_version_id
    # 의 FK 타깃이라 여기 없으면 좁은 선택에서 FK가 해소되지 않는다 · ARCH-09)
    "ConceptVersion",
    # S2-c: ProblemEmbedding (L1 자체생성 동등문제 dedup pgvector 백킹·problem_id PK·
    # 하드 FK 없음 — 여기 없으면 autogenerate가 실재 테이블을 drop 제안한다 · ARCH-09)
    "ProblemEmbedding",
]
