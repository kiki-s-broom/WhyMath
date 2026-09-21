// L4 교수학 코치 API 데이터 모델 — 백엔드 `POST /v1/coach` 계약을 *구조 그대로* 옮긴다.
//
// 정본: `src/backend/whymath_backend/api/coach.py`(`CoachRequest`·`CoachResponse`) +
// 중첩 모델(`PedagogyDecision`·`CoachingTrigger`·`SolutionCoaching`·`MisconceptionMatch`·
// `InterventionDecision`·`LthcAdaptation`·`SolutionVerificationResult`).
//
// **경계(CLAUDE.md)**: 이 클래스들은 *수신 컨테이너*일 뿐이다 — 검증·진단·결정 *로직*은
// 전부 서버(L1-L4)에 있고, 클라는 결정된 신호를 구조 그대로 받아 렌더링만 한다(표현≠의미).
// 정답·검증 사유 같은 누출 위험 필드는 백엔드가 애초에 응답에 싣지 않는다(coach.py 계약).
//
// **enum 표현 방침**: 백엔드 문자열 enum(focus·socratic_category·intervention pattern 등)은
// 대부분 `String`으로 유지한다(과확장 회피·백엔드 값 그대로 보존·codegen 리스크 최소화).
// 라벨·표기는 백엔드가 한국어 문자열(rationale·prompt)로 내려주므로 클라가 enum을 해석할
// 필요가 적다. 향후 UI 분기에서 필요하면 @JsonValue enum으로 좁힌다.
import 'package:freezed_annotation/freezed_annotation.dart';

part 'coach_models.freezed.dart';
part 'coach_models.g.dart';

// ─────────────────────────────────────────────────────────────────────────
// 요청 — CoachRequest (coach.py L112)
// ─────────────────────────────────────────────────────────────────────────

/// `POST /v1/coach` 요청 본문 — 학생 발화·현재 Polya 상태·옵션 신호.
///
/// 백엔드는 `extra="forbid"`라 정의되지 않은 필드를 거부한다 — JSON 키를 정확히 맞춘다.
/// 대부분 옵셔널(첫 진입·스테이트리스 호출 지원). 수학 결정은 서버가 내린다.
@freezed
abstract class CoachRequest with _$CoachRequest {
  const factory CoachRequest({
    /// 학생 발화(자연어). 빈 문자열 허용(첫 진입).
    @JsonKey(name: 'student_input') required String studentInput,

    /// 학생의 *풀이/작업* 텍스트(L5 OCR 산출물 등) — 발화와 분리. 검산 검증 대상.
    @JsonKey(name: 'student_solution') String? studentSolution,

    /// 세션의 현재 Polya 상태(미지정 시 백엔드 기본=이해 진입).
    @JsonKey(name: 'polya_state', includeIfNull: false) PolyaState? polyaState,

    /// 학생 숙달도 라벨("초보"·"발전 중"·"숙달") — 있을 때만 LTHC 조정안 반환.
    @JsonKey(name: 'mastery_level') String? masteryLevel,

    /// L2 BKT 숙달도(0~1). masteryLevel 미지정 시 라벨로 환산.
    @JsonKey(name: 'bkt_mastery') double? bktMastery,

    /// L2 진단이 권한 코칭 포커스(verify·consolidate 등) — 진입 소크라테스 카테고리 시드.
    @JsonKey(name: 'coaching_focus') String? coachingFocus,

    /// L5가 분해한 풀이 단계 시퀀스(표현식 리스트). 제공 시 단계별 검증 수행.
    @JsonKey(name: 'solution_steps') List<String>? solutionSteps,

    /// 전이별 단계 유형(조건해석/케이스분류/그래프스케치/계산/검산 등).
    @JsonKey(name: 'solution_step_types') List<String>? solutionStepTypes,

    /// L5 OCR 인식 신뢰도(0~1). 제공+<0.8이면 백엔드가 match_low_quality 표시.
    @JsonKey(name: 'ocr_confidence') double? ocrConfidence,
  }) = _CoachRequest;

  factory CoachRequest.fromJson(Map<String, dynamic> json) =>
      _$CoachRequestFromJson(json);
}

/// 세션의 현재 Polya 상태(coach.py / l4/models.py `PolyaState`).
///
/// current_stage 값은 백엔드 enum("understand"·"plan"·"execute"·"review") 문자열.
@freezed
abstract class PolyaState with _$PolyaState {
  const factory PolyaState({
    /// 현재 단계("understand"·"plan"·"execute"·"review").
    @JsonKey(name: 'current_stage') @Default('understand') String currentStage,

    /// 단계 전이 이력(전이 직전 단계 문자열 리스트).
    @JsonKey(name: 'history') @Default(<String>[]) List<String> history,

    /// 현재 단계서 누적 턴 수(전이 시 0 리셋).
    @JsonKey(name: 'turn_count') @Default(0) int turnCount,

    /// 직전 응답의 답 미루기 단계(1~4·None이면 첫 결정).
    @JsonKey(name: 'prev_hint_level') int? prevHintLevel,
  }) = _PolyaState;

  factory PolyaState.fromJson(Map<String, dynamic> json) =>
      _$PolyaStateFromJson(json);
}

// ─────────────────────────────────────────────────────────────────────────
// 응답 — CoachResponse (coach.py L189) + 중첩
// ─────────────────────────────────────────────────────────────────────────

/// `POST /v1/coach` 응답 — 통합 교수학 결정.
///
/// `decision`은 항상 채워지고 나머지는 조건부(null 가능). 이 세션 신호(WH-1 1단계)
/// 전부 표현 가능: solution_coaching(verification·ocr_gated)·match_low_quality·
/// no_confident_match·misconceptions.
@freezed
abstract class CoachResponse with _$CoachResponse {
  const factory CoachResponse({
    /// Polya 단계 전이·프롬프트·hint_level·socratic_category 등 핵심 결정(항상 존재).
    @JsonKey(name: 'decision') required PedagogyDecision decision,

    /// 오개념 후보 top-3(없으면 빈 리스트·confidence 내림차순).
    @JsonKey(name: 'misconceptions')
    @Default(<MisconceptionMatch>[]) List<MisconceptionMatch> misconceptions,

    /// top-1 오개념 신뢰도 0.5+면 개입 결정·미만이면 null(진단 보류).
    @JsonKey(name: 'intervention') InterventionDecision? intervention,

    /// 요청에 mastery_level이 있을 때만 LTHC 조정안·없으면 null.
    @JsonKey(name: 'lthc') LthcAdaptation? lthc,

    /// 요청에 coaching_focus가 있을 때만 — 진입 소크라테스 카테고리 문자열.
    @JsonKey(name: 'entry_socratic_category') String? entrySocraticCategory,

    /// 학생 풀이의 거짓 수치 관계(계산 슬립)가 검출되면 검산 코칭 + 신호·없으면 null.
    @JsonKey(name: 'solution_coaching') SolutionCoaching? solutionCoaching,

    /// 이 문제 개념의 막힌 선수가 있으면 "선수 복습 먼저" 코칭·없으면 null.
    @JsonKey(name: 'prerequisite_coaching') CoachingTrigger? prerequisiteCoaching,

    /// §3.3 게이트 ② — ocr_confidence<0.8이면 true(재확인 유도 신호·매칭은 유지).
    @JsonKey(name: 'match_low_quality') @Default(false) bool matchLowQuality,

    /// §3.3 게이트 ① — top-1<0.65라 후보를 비웠는지(억지 매칭 금지·true면 misconceptions 빔).
    @JsonKey(name: 'no_confident_match') @Default(false) bool noConfidentMatch,
  }) = _CoachResponse;

  factory CoachResponse.fromJson(Map<String, dynamic> json) =>
      _$CoachResponseFromJson(json);
}

/// L4 핵심 결정(l4/models.py `PedagogyDecision`).
@freezed
abstract class PedagogyDecision with _$PedagogyDecision {
  const factory PedagogyDecision({
    /// 다음 단계 전이("stay"·"next"·"previous").
    @JsonKey(name: 'polya_stage_to_advance') required String polyaStageToAdvance,

    /// 답 미루기 단계(1=가장 은근/방향, 4=전체 풀이/마지막 수단).
    @JsonKey(name: 'hint_level') @Default(1) int hintLevel,

    /// 소크라테스 6카테고리 라벨(기본 빈 문자열).
    @JsonKey(name: 'socratic_category') @Default('') String socraticCategory,

    /// 사용자 프롬프트(학생에게 던질 발화 본문).
    @JsonKey(name: 'prompt') required String prompt,

    /// 시스템 프롬프트(역할·금기·톤 지시).
    @JsonKey(name: 'system') required String system,

    /// 권장 비용 티어("local"·"cloud_mid"·"cloud_high").
    @JsonKey(name: 'recommended_cost_tier')
    @Default('local') String recommendedCostTier,

    /// 단계 보조 행동 라벨(UI 표시·내부 트리거 후보).
    @JsonKey(name: 'suggested_actions')
    @Default(<String>[]) List<String> suggestedActions,

    /// 노출량 라벨(hint_level 파생·기본 빈 문자열).
    @JsonKey(name: 'reveals') @Default('') String reveals,
  }) = _PedagogyDecision;

  factory PedagogyDecision.fromJson(Map<String, dynamic> json) =>
      _$PedagogyDecisionFromJson(json);
}

/// 오개념 진단 1건(l4/misconception/models.py `MisconceptionMatch`).
@freezed
abstract class MisconceptionMatch with _$MisconceptionMatch {
  const factory MisconceptionMatch({
    /// 진단된 오개념 카탈로그 항목.
    @JsonKey(name: 'misconception') required Misconception misconception,

    /// 신뢰도(0~1).
    @JsonKey(name: 'confidence') required double confidence,

    /// 실제 매칭된 substring signals 부분집합(디버그·UI).
    @JsonKey(name: 'matched_signals')
    @Default(<String>[]) List<String> matchedSignals,

    /// 실제 매치된 regex_signals 부분집합(디버그·UI).
    @JsonKey(name: 'matched_regex_signals')
    @Default(<String>[]) List<String> matchedRegexSignals,

    /// 의미(임베딩) 매칭 경로의 코사인 유사도·substring/regex 경로는 null.
    @JsonKey(name: 'semantic_similarity') double? semanticSimilarity,
  }) = _MisconceptionMatch;

  factory MisconceptionMatch.fromJson(Map<String, dynamic> json) =>
      _$MisconceptionMatchFromJson(json);
}

/// 오개념 카탈로그 단위(l4/misconception/models.py `Misconception`).
///
/// 누출 안전: canonical_statement·counterexample은 *오개념 가정/반례 입력*이지 문제 정답이
/// 아니다(카탈로그는 공개 교수학 자산).
@freezed
abstract class Misconception with _$Misconception {
  const factory Misconception({
    /// 정본 ID — kebab-case(예: 'distribution-over-power').
    @JsonKey(name: 'id') required String id,

    /// 짧은 한국어 라벨(예: '제곱 분배').
    @JsonKey(name: 'name_kr') required String nameKr,

    /// 카탈로그 영역("대수"·"기하"·"함수" 등).
    @JsonKey(name: 'domain') required String domain,

    /// 학생이 암묵적으로 가정한 잘못된 진술.
    @JsonKey(name: 'canonical_statement') required String canonicalStatement,

    /// 반례 입력(예: 'a=1, b=1').
    @JsonKey(name: 'counterexample') required String counterexample,

    /// 공출현해야 매칭되는 substring 토큰(AND).
    @JsonKey(name: 'signals') @Default(<String>[]) List<String> signals,

    /// v1.2 보조 탐지 — 정규식(OR).
    @JsonKey(name: 'regex_signals')
    @Default(<String>[]) List<String> regexSignals,
  }) = _Misconception;

  factory Misconception.fromJson(Map<String, dynamic> json) =>
      _$MisconceptionFromJson(json);
}

/// 오개념 개입 결정(l4/misconception/models.py `InterventionDecision`).
@freezed
abstract class InterventionDecision with _$InterventionDecision {
  const factory InterventionDecision({
    /// 개입 패턴("counterexample"·"concrete_case"·"visualization"·"reverse_reasoning").
    @JsonKey(name: 'pattern') required String pattern,

    /// 학생에게 노출할 어셈블된 발화(자각 유도형).
    @JsonKey(name: 'prompt') required String prompt,

    /// 진단된 misconception.id(텔레메트리).
    @JsonKey(name: 'misconception_id') required String misconceptionId,
  }) = _InterventionDecision;

  factory InterventionDecision.fromJson(Map<String, dynamic> json) =>
      _$InterventionDecisionFromJson(json);
}

/// LTHC 조정안(l4/lthc/models.py `LthcAdaptation`).
@freezed
abstract class LthcAdaptation with _$LthcAdaptation {
  const factory LthcAdaptation({
    /// 이 조정안이 겨냥한 숙달도 라벨("초보"·"발전 중"·"숙달").
    @JsonKey(name: 'mastery_level') required String masteryLevel,

    /// 낮은 진입 후보(작은 사례·시각화·유사 회상).
    @JsonKey(name: 'entry_suggestions')
    @Default(<String>[]) List<String> entrySuggestions,

    /// 높은 천장 후보(일반화·변형·증명·다른 풀이).
    @JsonKey(name: 'extensions') @Default(<String>[]) List<String> extensions,

    /// 비계(막힘 시 보조 발화).
    @JsonKey(name: 'scaffolds') @Default(<String>[]) List<String> scaffolds,
  }) = _LthcAdaptation;

  factory LthcAdaptation.fromJson(Map<String, dynamic> json) =>
      _$LthcAdaptationFromJson(json);
}

/// 메타인지 코칭 트리거(l4/metacognitive_trigger.py `CoachingTrigger`).
///
/// SolutionCoaching.trigger·CoachResponse.prerequisite_coaching 양쪽에서 쓰인다.
@freezed
abstract class CoachingTrigger with _$CoachingTrigger {
  const factory CoachingTrigger({
    /// 코칭 포커스("verify"·"consolidate"·"retrieval"·"foundation"·"advance" 등).
    @JsonKey(name: 'focus') required String focus,

    /// 결정 근거(교사/학생 노출 가능 한국어).
    @JsonKey(name: 'rationale') required String rationale,

    /// 학생에게 보일 수 있는 메타인지 유도 발화(답 미제공).
    @JsonKey(name: 'prompt') required String prompt,

    /// 대화 진입 소크라테스 카테고리 문자열.
    @JsonKey(name: 'socratic_category') required String socraticCategory,

    /// verify 포커스가 가리키는 첫 incorrect 전이 인덱스(0-based)·없으면 null.
    @JsonKey(name: 'focus_step_index') int? focusStepIndex,
  }) = _CoachingTrigger;

  factory CoachingTrigger.fromJson(Map<String, dynamic> json) =>
      _$CoachingTriggerFromJson(json);
}

/// 학생 풀이 기반 코칭 결정(l4/solution_coaching.py `SolutionCoaching`).
///
/// WH-1 1단계 신호 일체를 담는다: solution_verification(단계별 검증)·verification_ocr_gated.
@freezed
abstract class SolutionCoaching with _$SolutionCoaching {
  const factory SolutionCoaching({
    /// L4 메타인지 코칭 결정(focus·근거·발화)·항상 존재.
    @JsonKey(name: 'trigger') required CoachingTrigger trigger,

    /// 학생 풀이에서 거짓 수치 관계가 결정론으로 검출됐는가.
    @JsonKey(name: 'arithmetic_error') required bool arithmeticError,

    /// 검출된 거짓 관계 사유(L3 검증기 출력)·없으면 null.
    @JsonKey(name: 'validation_signal') String? validationSignal,

    /// 검출된 슬립 종류("arithmetic"·"inequality"·"not_equal"·"solution"·"other")·없으면 null.
    @JsonKey(name: 'error_kind') String? errorKind,

    /// 틀린 관계의 학생 풀이 원문 내 위치 [start, end)·없으면 null.
    /// 백엔드는 JSON 배열 2-튜플로 직렬화 → `List<int>`로 수신.
    @JsonKey(name: 'error_span') List<int>? errorSpan,

    /// L5가 분해한 단계 시퀀스의 연쇄 검증 결과·단계 미제공 시 null.
    @JsonKey(name: 'solution_verification')
    SolutionVerificationResult? solutionVerification,

    /// verify_solution이 step-incorrect를 냈으나 저신뢰 OCR(<0.8)로 코칭 결정에서 보류했는지.
    @JsonKey(name: 'verification_ocr_gated')
    @Default(false) bool verificationOcrGated,
  }) = _SolutionCoaching;

  factory SolutionCoaching.fromJson(Map<String, dynamic> json) =>
      _$SolutionCoachingFromJson(json);
}

/// 풀이 단계 연쇄 검증 결과(l3/verify_solution.py `SolutionVerificationResult`).
///
/// 노출 계약: 검증 결과(상태·카운트·비율·폐쇄 사유 코드)뿐 — 정답/본문 누출 없음(reason은
/// 검증 사유). 단계별 verify_step 결과(`steps`)는 이번 슬라이스에서도 파싱하지 않는다 —
/// MATH-03이 보류 *사유 분포*를 `unverifiable_by_reason` 카운트로 따로 실어 주므로 학생 문구
/// 3분기에 steps 전체가 필요 없다(카운트로 충분·백엔드 노출 계약 유지).
@freezed
abstract class SolutionVerificationResult with _$SolutionVerificationResult {
  const factory SolutionVerificationResult({
    /// correct 전이 개수.
    @JsonKey(name: 'n_correct') required int nCorrect,

    /// incorrect 전이 개수.
    @JsonKey(name: 'n_incorrect') required int nIncorrect,

    /// unverifiable 전이 개수(검증 불가).
    @JsonKey(name: 'n_unverifiable') required int nUnverifiable,

    /// 확인 보류(unverifiable) 전이의 *사유 코드별* 카운트(MATH-03·값 합 = nUnverifiable).
    /// 키는 백엔드 폐쇄 enum(VerifyStepReasonCode) 문자열 — parse_error·undecidable·
    /// non_algebraic_step·empty_input·heterogeneous_form·subset_ambiguous·variable_mismatch.
    /// 구판 서버(키 부재)는 빈 맵 — 카드가 기존 '확인 보류 일부' 한 문구로 폴백한다.
    @JsonKey(name: 'unverifiable_by_reason')
    @Default(<String, int>{}) Map<String, int> unverifiableByReason,

    /// 총 전이 개수 = max(0, len(steps)-1)·세 카운트의 합과 같다.
    @JsonKey(name: 'n_transitions') required int nTransitions,

    /// 검증 불가 비율 = n_unverifiable/n_transitions·전이 0이면 0.0.
    @JsonKey(name: 'unverified_ratio') required double unverifiedRatio,

    /// 첫 incorrect 전이 인덱스 i(steps[i]→steps[i+1])·없으면 null.
    @JsonKey(name: 'first_incorrect_index') int? firstIncorrectIndex,

    /// incorrect 전이가 하나라도 있으면 true.
    @JsonKey(name: 'has_incorrect') required bool hasIncorrect,
  }) = _SolutionVerificationResult;

  factory SolutionVerificationResult.fromJson(Map<String, dynamic> json) =>
      _$SolutionVerificationResultFromJson(json);
}

// ─────────────────────────────────────────────────────────────────────────
// 영속 세션 — POST /v1/coach/sessions(+/turns), GET /v1/coach/sessions/{id}
// ─────────────────────────────────────────────────────────────────────────

/// 세션 생성/턴 추가 결과 — 렌더 가능한 [CoachResponse] + 영속 식별자.
///
/// 백엔드 `SessionCreateResponse`/`TurnAppendResponse`는 `CoachResponse`에 dialogue/turn ID·
/// wh1_turn_index 등을 *덧붙인* 상위 스키마다. Dart는 상속을 코드젠하지 못하므로 CoachResponse를
/// *같은 JSON에서 재파싱*(미선언 키 무시)하고 영속 필드만 별도 추출하는 얇은 합성 홀더로 둔다.
/// 재모델링 없이 기존 렌더 경로([CoachResponse])를 그대로 재사용한다.
class CoachTurnResult {
  const CoachTurnResult({
    required this.dialogueId,
    required this.response,
    required this.wh1TurnIndex,
    this.problemComplete = false,
    this.awaitingReflection = false,
    this.completedAttemptId,
  });

  /// 이 대화 세션 PK(UUID 문자열) — 이후 턴 추가·세션 조회에 재사용.
  final String dialogueId;

  /// 렌더 가능한 교수학 결정(decision·solution_coaching·misconceptions 등).
  final CoachResponse response;

  /// 이 교환의 WH-1 턴 번호(1-기반·세션 누적). 생성=1·턴마다 증가.
  final int wh1TurnIndex;

  /// 이 턴에 문제가 *완료*됐는지(서버 `problem_complete`·기본 false).
  ///
  /// 서버가 내리는 **권위값**이다 — 클라는 정오·완료를 판정하지 않고 이 값만 본다.
  /// true면 서버가 ProblemAttempt를 이미 적재하고 숙달을 전파했으므로 클라는 별도로
  /// `POST /v1/me/attempts`를 부르지 않는다(중복 적재 금지·api/coach.py 계약 명문).
  final bool problemComplete;

  /// 정답 도달 후 *돌아보기(메타인지) 1턴*을 대기 중인지(서버 `awaiting_reflection`·기본 false).
  ///
  /// true면 이번 턴은 완료가 아니며([problemComplete]=false) 학생의 근거 응답 다음 턴에 완료된다.
  final bool awaitingReflection;

  /// 완료 시 서버가 적재한 ProblemAttempt PK(UUID 문자열)·완료가 아니면 null.
  final String? completedAttemptId;

  /// 세션 생성/턴 추가 응답 JSON에서 파싱한다. [dialogueId]는 생성 응답이면 본문에서,
  /// 턴 추가 응답이면 URL에서 주입된다(TurnAppendResponse엔 dialogue_id가 없음).
  ///
  /// 완료 신호 3필드는 서버 기본값과 정합하게 폴백한다 — bool 둘은 부재 시 false,
  /// `completed_attempt_id`는 부재 시 null(구판 서버 호환·조용한 추정 없음).
  factory CoachTurnResult.fromJson(
    Map<String, dynamic> json, {
    required String dialogueId,
  }) {
    return CoachTurnResult(
      dialogueId: dialogueId,
      response: CoachResponse.fromJson(json),
      wh1TurnIndex: (json['wh1_turn_index'] as num?)?.toInt() ?? 1,
      problemComplete: json['problem_complete'] as bool? ?? false,
      awaitingReflection: json['awaiting_reflection'] as bool? ?? false,
      completedAttemptId: json['completed_attempt_id'] as String?,
    );
  }
}

/// 대화 턴 1건(백엔드 `DialogueTurn` 최소 미러 — 세션 조회 검증용).
@freezed
abstract class CoachTurn with _$CoachTurn {
  const factory CoachTurn({
    /// 턴 순서(1부터·UNIQUE(dialogue_id, turn_order)).
    @JsonKey(name: 'turn_order') required int turnOrder,

    /// 발화 주체('student'·'assistant'·'system' 등)·없으면 null.
    @JsonKey(name: 'role') String? role,

    /// 대화 본문(PII 가능)·없으면 null.
    @JsonKey(name: 'content') String? content,
  }) = _CoachTurn;

  factory CoachTurn.fromJson(Map<String, dynamic> json) =>
      _$CoachTurnFromJson(json);
}

/// 세션 스냅샷(GET /v1/coach/sessions/{id}) — 턴 영속 확인용 최소 표현.
///
/// 백엔드 `SessionGetResponse`는 `{dialogue: {...}, turns: [...]}` 중첩 구조라 flat json_serializable
/// fromJson과 맞지 않는다 — [ProblemsApi]가 아니라 `CoachApi.getSession`이 중첩을 풀어 생성한다.
@freezed
abstract class CoachSessionSnapshot with _$CoachSessionSnapshot {
  const factory CoachSessionSnapshot({
    /// 세션 PK(UUID 문자열).
    required String dialogueId,

    /// 누적 턴 수(system 포함)·없으면 null.
    int? totalTurns,

    /// 턴 목록(turn_order ASC).
    @Default(<CoachTurn>[]) List<CoachTurn> turns,
  }) = _CoachSessionSnapshot;
}
