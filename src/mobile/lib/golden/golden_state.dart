// 골든 패스 화면 상태 — Riverpod Notifier 하나(S6).
//
// 상태 = 세션 ID·닉네임·숙련도·현재 문제·대화 목록·로딩·오류 문구.
// 수학 로직은 넣지 않는다 — 맞음/틀림·숙련도는 서버가 준 값을 그대로 담기만 한다.

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden_api.dart';

/// 대화 목록 한 줄의 말한 쪽 — 학생 / 튜터 / 판정(서버 판정 결과 한 줄).
const String kWhoStudent = '학생';
const String kWhoTutor = '튜터';
const String kWhoVerdict = '판정';

/// 화면 상태(불변). 바꿀 때는 [copyWith]로 새 값을 만든다.
class GoldenState {
  const GoldenState({
    this.sessionId,
    this.nickname,
    this.mastery = 0.0,
    this.problem,
    this.chat = const <(String, String)>[],
    this.loading = false,
    this.error,
  });

  final String? sessionId;
  final String? nickname;
  final double mastery;

  /// 지금 풀고 있는 문제(세션 시작 전에는 null).
  final GoldenProblem? problem;

  /// 대화 목록 — (말한 쪽, 내용).
  final List<(String who, String text)> chat;

  /// 서버 요청 중인지.
  final bool loading;

  /// 화면 위에 보여줄 오류 문구(없으면 null).
  final String? error;

  /// 이 문제의 판정이 이미 나왔는지 — 대화 마지막 줄이 판정 줄이면 참.
  /// (같은 문제에 답을 다시 보내 숙련도가 두 번 바뀌는 것을 막는 용도. 다음 문제로 넘어가기는 S7)
  bool get problemFinished => chat.isNotEmpty && chat.last.$1 == kWhoVerdict;

  GoldenState copyWith({
    String? sessionId,
    String? nickname,
    double? mastery,
    GoldenProblem? problem,
    List<(String, String)>? chat,
    bool? loading,
    String? error,
    bool clearError = false,
  }) {
    return GoldenState(
      sessionId: sessionId ?? this.sessionId,
      nickname: nickname ?? this.nickname,
      mastery: mastery ?? this.mastery,
      problem: problem ?? this.problem,
      chat: chat ?? this.chat,
      loading: loading ?? this.loading,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

/// API 클라이언트 — 테스트는 `goldenApiProvider.overrideWithValue(가짜)`로 바꿔 끼운다.
final Provider<GoldenApi> goldenApiProvider =
    Provider<GoldenApi>((Ref ref) => GoldenApi());

/// 화면 상태 Provider.
final NotifierProvider<GoldenNotifier, GoldenState> goldenProvider =
    NotifierProvider<GoldenNotifier, GoldenState>(GoldenNotifier.new);

class GoldenNotifier extends Notifier<GoldenState> {
  @override
  GoldenState build() => const GoldenState();

  GoldenApi get _api => ref.read(goldenApiProvider);

  /// GP-1 → GP-2: 닉네임으로 세션을 열고 첫 문제를 받는다.
  Future<void> start(String nickname) async {
    final String name = nickname.trim();
    if (name.isEmpty || state.loading) return;
    state = state.copyWith(loading: true, clearError: true);
    try {
      final GoldenSession session = await _api.createSession(name);
      final GoldenProblem problem = await _api.nextProblem(session.sessionId);
      state = state.copyWith(
        sessionId: session.sessionId,
        nickname: session.nickname,
        mastery: session.mastery,
        problem: problem,
        chat: const <(String, String)>[],
        loading: false,
      );
    } on GoldenApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    } on FormatException {
      // 응답 모양이 계약과 다름 — 앱은 죽지 않고 문구만 보인다.
      state = state.copyWith(loading: false, error: '서버 응답을 읽지 못했어요.');
    }
  }

  /// GP-3 → GP-4/GP-5: 학생 입력을 보내고, 튜터 되묻기 또는 판정 한 줄을 대화에 쌓는다.
  Future<void> send(String text) async {
    final String body = text.trim();
    final String? sessionId = state.sessionId;
    final GoldenProblem? problem = state.problem;
    if (body.isEmpty ||
        sessionId == null ||
        problem == null ||
        state.loading ||
        state.problemFinished) {
      return;
    }
    // 학생 말풍선은 보내는 즉시 보인다.
    state = state.copyWith(
      chat: <(String, String)>[...state.chat, (kWhoStudent, body)],
      loading: true,
      clearError: true,
    );
    try {
      final AnswerResult result = await _api.answer(sessionId, problem.id, body);
      switch (result) {
        case TutorTurn(:final String message):
          state = state.copyWith(
            chat: <(String, String)>[...state.chat, (kWhoTutor, message)],
            loading: false,
          );
        case Graded(:final bool correct, :final double mastery):
          // S6은 판정 한 줄만 추가한다(결과 화면은 S7).
          final String verdict =
              '판정: ${correct ? '맞음' : '틀림'} · 숙련도 ${mastery.toStringAsFixed(2)}';
          state = state.copyWith(
            chat: <(String, String)>[...state.chat, (kWhoVerdict, verdict)],
            mastery: mastery,
            loading: false,
          );
      }
    } on GoldenApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    } on FormatException {
      state = state.copyWith(loading: false, error: '서버 응답을 읽지 못했어요.');
    }
  }
}
