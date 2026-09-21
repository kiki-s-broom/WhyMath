// 코치 완료 신호 — 서버 권위값 3필드의 클라 미러(problem_complete·awaiting_reflection·
// completed_attempt_id). S3-32의 *클라 절반*(MOB-20).
//
// 경계(CLAUDE.md · L5 = View Layer): 이 파일은 **어떤 판정도 하지 않는다.** "문제가 끝났는가",
// "돌아보기를 받아야 하는가"는 전부 서버(L4 코치)가 턴 응답에 실어 내려주는 값이고, 클라는 그
// 값을 *그대로* 보관해 화면 어포던스를 바꿀 뿐이다(점수 비교·정오 판정식 클라 금지).
//
// ⚠️ 재적재 금지: `problemComplete == true`면 서버가 이미 ProblemAttempt를 적재하고 숙달을
// 전파한 뒤다(api/coach.py `_complete_problem`). 그러므로 클라는 `POST /v1/me/attempts`를
// **부르지 않는다** — 부르면 attempt·숙달 이중 적재가 된다(계약 명문: api/coach.py
// `_PROBLEM_COMPLETE_DESC` "클라는 별도로 POST /v1/me/attempts를 부르지 않는다").
//
// 학습 세션(session_id) 축 — **미기록**(조용히 메우지 않는다):
//   `ProblemAttempt.session_id`(FK→learning_session)는 이 코치 완료 경로에서 *채워지지 않는다*.
//   서버 `_complete_problem`이 attempt를 적재할 때 session_id를 세팅하지 않고, 클라도 여기서
//   아무것도 제출하지 않으므로 실을 자리 자체가 없다. 코치 세션 식별자(`dialogue_id`)는
//   LearningSession PK가 *아니라* Dialogue PK이므로 그 자리에 대신 넣지 않는다 — 넣으면
//   존재하지 않는 세션을 가리키는 가짜 참조가 된다. 즉 "해당 없음"이 아니라 **알려진 미기록**이며,
//   메우는 일은 LearningSession writer가 생기는 시점의 *서버* 과제다(클라 우회 금지).
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';

/// 코치 턴 1회가 남긴 완료 신호(서버 권위값 미러·불변).
///
/// - [problemComplete] : 이 턴에 문제가 완료됐는지 — *다음 문항으로 진행* 어포던스의 유일한 근거.
/// - [awaitingReflection] : 정답 도달 후 Polya 돌아보기(메타인지) 1턴을 대기 중인지 — 진행 보류 UX.
/// - [completedAttemptId] : 완료 시 서버가 적재한 ProblemAttempt PK(완료가 아니면 null).
///   학생에게 표시하지 않는다(UUID는 학습 정보가 아니다) — 완료 패널의 *동일성 키*로만 쓴다.
@immutable
class CoachCompletionSignal {
  const CoachCompletionSignal({
    this.problemComplete = false,
    this.awaitingReflection = false,
    this.completedAttemptId,
    this.problemId,
  });

  /// 신호 없음(초기값·턴 전송 시작 시 되돌아가는 상태).
  static const CoachCompletionSignal none = CoachCompletionSignal();

  /// 이 턴에 문제가 완료됐는지(서버 `problem_complete`·부재 시 false).
  final bool problemComplete;

  /// 돌아보기(메타인지) 응답 대기 중인지(서버 `awaiting_reflection`·부재 시 false).
  final bool awaitingReflection;

  /// 서버가 적재한 ProblemAttempt PK(서버 `completed_attempt_id`·완료 아니면 null).
  final String? completedAttemptId;

  /// 이 신호가 *어느 문제*에 대한 것인지(신호를 만든 턴의 활성 문제 id·없으면 null).
  ///
  /// 이 provider는 autoDispose가 아니고 하단 탭이 `StatefulShellRoute.indexedStack`으로 상태를
  /// 보존하므로, 학생이 홈 → '오늘의 문제 풀기'로 **다른 문제를 열어도** 이전 완료 신호가 그대로
  /// 살아 있다(`problem_screen.dart`가 `activeProblemProvider`만 교체한다). 그 상태로 채팅에
  /// 돌아오면 *새 문제*의 선택지가 감춰지고 *이전* attempt의 완료 패널이 뜬다 — 새로 고른 문제를
  /// 건너뛰게 만드는 실결함이다. 그래서 신호를 문제에 **스코프**하고, 화면은 [appliesTo]가 참일
  /// 때만 신호를 인정한다(버튼 탭에만 의존하는 리셋은 이 경로를 못 막는다).
  final String? problemId;

  /// 이 신호가 [currentProblemId]에 대한 것인가 — 아니면 화면은 신호가 *없는* 것으로 다룬다.
  ///
  /// 자유 대화(활성 문제 없음)는 양쪽 다 null이라 성립한다. 문제가 바뀌면 즉시 불일치가 되므로
  /// 리스너·타이밍에 의존하지 않는다(경합 없음).
  bool appliesTo(String? currentProblemId) => problemId == currentProblemId;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is CoachCompletionSignal &&
          other.problemComplete == problemComplete &&
          other.awaitingReflection == awaitingReflection &&
          other.completedAttemptId == completedAttemptId &&
          other.problemId == problemId;

  @override
  int get hashCode => Object.hash(
      problemComplete, awaitingReflection, completedAttemptId, problemId);

  @override
  String toString() => 'CoachCompletionSignal(problemComplete: $problemComplete, '
      'awaitingReflection: $awaitingReflection, '
      'completedAttemptId: $completedAttemptId, '
      'problemId: $problemId)';
}

/// 마지막 코치 턴의 완료 신호 — 컨트롤러가 쓰고 채팅 화면이 읽는다.
///
/// `ChatState`(freezed)에 필드를 더하지 않고 별도 provider로 두는 이유: 이 값은 *서버 턴 응답의
/// 파생 신호*라 대화 누적(messages·polyaState)과 수명이 다르고, 활성 문제 전달과 같은 단방향
/// 표현 상태 1건이라 기존 `activeProblemProvider`와 같은 형태를 따른다(소비처가 늘면 Notifier 승격).
final coachCompletionSignalProvider = StateProvider<CoachCompletionSignal>(
  (ref) => CoachCompletionSignal.none,
);
