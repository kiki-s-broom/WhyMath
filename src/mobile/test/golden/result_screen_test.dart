// 골든 패스 결과 화면 위젯 테스트(S7) — 가짜 API를 Provider로 주입해 서버 없이 돌린다.
//
// ① graded(correct=true) → 결과 화면에 "맞음"과 숙련도(+ 바뀐 양)
// ② "다음 문제" 탭 → 문제 화면 복귀 + 대화 비움 + 다른 문제
// ③ correct=false → 비난 표현 없음("틀렸"·"못" 문자열 부재)
// (+) 같은 닉네임으로 다시 시작하면 서버가 준 숙련도를 그대로 보인다(재시작 유지)

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/golden/golden_api.dart';
import 'package:korean_math_app/golden/golden_app.dart';
import 'package:korean_math_app/golden/golden_state.dart';
import 'package:korean_math_app/golden/problem_screen.dart';
import 'package:korean_math_app/golden/result_screen.dart';

/// 가짜 API — 문제는 LF-07, LF-08 … 순서로, 답 응답은 정해 둔 순서로 돌려준다.
class _FakeGoldenApi implements GoldenApi {
  _FakeGoldenApi({
    this.answers = const <AnswerResult>[],
    this.sessionMastery = 0.0,
  });

  final List<AnswerResult> answers;

  /// 세션 시작 때 서버가 돌려줄 숙련도(같은 닉네임 재시작 흉내).
  final double sessionMastery;
  int _nextAnswer = 0;
  int nextCalls = 0;

  static const List<GoldenProblem> problems = <GoldenProblem>[
    GoldenProblem(
      id: 'LF-07',
      stem: r'일차함수 $f(x) = 2x + 7$에 대하여 $f(2)$를 구하시오.',
      index: 7,
      total: 30,
    ),
    GoldenProblem(
      id: 'LF-08',
      stem: r'일차함수 $f(x) = -x + 4$에 대하여 $f(3)$을 구하시오.',
      index: 8,
      total: 30,
    ),
  ];

  @override
  Future<GoldenSession> createSession(String nickname) async =>
      GoldenSession(sessionId: 'sid-1', nickname: nickname, mastery: sessionMastery);

  @override
  Future<GoldenProblem> nextProblem(String sessionId) async =>
      problems[nextCalls++ % problems.length];

  @override
  Future<AnswerResult> answer(String sessionId, String problemId, String text) async =>
      answers[_nextAnswer++];
}

Future<void> _openProblem(WidgetTester tester, _FakeGoldenApi api) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [goldenApiProvider.overrideWithValue(api)],
      child: const GoldenApp(),
    ),
  );
  await tester.enterText(find.byKey(const Key('golden_nickname_field')), '테스트학생');
  await tester.tap(find.byKey(const Key('golden_start_button')));
  await tester.pumpAndSettle();
}

Future<void> _sendAnswer(WidgetTester tester, String text) async {
  await tester.enterText(find.byKey(const Key('golden_answer_field')), text);
  await tester.tap(find.byKey(const Key('golden_send_button')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('① graded(correct=true) → 결과 화면에 "맞음"과 숙련도·바뀐 양·피드백·턴 수',
      (WidgetTester tester) async {
    final _FakeGoldenApi api = _FakeGoldenApi(
      sessionMastery: 0.20,
      answers: const <AnswerResult>[
        TutorTurn(message: '2를 넣으면 어떻게 될까?', turn: 1),
        Graded(
          correct: true,
          mastery: 0.30,
          turnsUsed: 1,
          feedback: '맞았어요. 다음 문제로 가 볼까요?',
        ),
      ],
    );
    await _openProblem(tester, api);
    await _sendAnswer(tester, '모르겠어요');
    await _sendAnswer(tester, '11');

    expect(find.byType(ResultScreen), findsOneWidget);
    expect(find.byType(ProblemScreen), findsNothing);
    expect(find.text('맞음'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
    // 숙련도는 서버 값 그대로(둘째 자리), 바뀐 양은 직전 서버 값 0.20과의 차이
    expect(find.text('숙련도 0.30'), findsOneWidget);
    expect(find.text('(+0.10)'), findsOneWidget);
    expect(find.text('맞았어요. 다음 문제로 가 볼까요?'), findsOneWidget);
    expect(find.text('튜터와 주고받은 횟수: 1번'), findsOneWidget);
    expect(find.byKey(const Key('golden_next_button')), findsOneWidget);
  });

  testWidgets('② "다음 문제" 탭 → 문제 화면으로 돌아오고 대화가 비며 다른 문제가 보인다',
      (WidgetTester tester) async {
    final _FakeGoldenApi api = _FakeGoldenApi(
      answers: const <AnswerResult>[
        TutorTurn(message: '2를 넣으면 어떻게 될까?', turn: 1),
        Graded(
          correct: true,
          mastery: 0.10,
          turnsUsed: 1,
          feedback: '맞았어요. 다음 문제로 가 볼까요?',
        ),
      ],
    );
    await _openProblem(tester, api);
    expect(find.text('LF-07 · 7/30'), findsOneWidget);
    await _sendAnswer(tester, '모르겠어요');
    await _sendAnswer(tester, '11');
    expect(find.byType(ResultScreen), findsOneWidget);

    await tester.tap(find.byKey(const Key('golden_next_button')));
    await tester.pumpAndSettle();

    // 문제 화면 복귀 — 다음 문제(LF-08)를 서버에서 다시 받았다
    expect(api.nextCalls, 2);
    expect(find.byType(ProblemScreen), findsOneWidget);
    expect(find.byType(ResultScreen), findsNothing);
    expect(find.text('LF-08 · 8/30'), findsOneWidget);
    expect(find.textContaining('을 구하시오.', findRichText: true), findsOneWidget);
    // 숙련도는 판정 때 서버가 준 값을 그대로 이어서 보인다
    expect(find.text('숙련도 0.10'), findsOneWidget);
    // 대화 목록이 비었고, 새 문제에는 다시 답을 보낼 수 있다
    expect(find.byType(ChatBubble), findsNothing);
    final ElevatedButton send =
        tester.widget<ElevatedButton>(find.byKey(const Key('golden_send_button')));
    expect(send.onPressed, isNotNull);
  });

  testWidgets('③ correct=false → 비난 표현("틀렸"·"못")이 화면 어디에도 없다', (WidgetTester tester) async {
    final _FakeGoldenApi api = _FakeGoldenApi(
      sessionMastery: 0.10,
      answers: const <AnswerResult>[
        TutorTurn(message: '2를 넣으면 어떻게 될까?', turn: 1),
        TutorTurn(message: '2 곱하기 2는 얼마일까?', turn: 2),
        TutorTurn(message: '거기에 7을 더하면?', turn: 3),
        // 서버(S5) 오답 피드백 문구 그대로
        Graded(
          correct: false,
          mastery: 0.05,
          turnsUsed: 3,
          feedback: '이번 문제의 답은 11였어요. 다음 문제에서 다시 해 봐요.',
        ),
      ],
    );
    await _openProblem(tester, api);
    for (final String t in <String>['몰라요', '4', '9', '10']) {
      await _sendAnswer(tester, t);
    }

    expect(find.byType(ResultScreen), findsOneWidget);
    expect(find.text('틀림'), findsOneWidget);
    expect(find.byIcon(Icons.lightbulb_outline), findsOneWidget);
    expect(find.text('숙련도 0.05'), findsOneWidget);
    expect(find.text('(−0.05)'), findsOneWidget);
    expect(find.text('튜터와 주고받은 횟수: 3번'), findsOneWidget);
    // 비난 표현 부재 — 일반 Text와 RichText를 모두 훑는다
    expect(find.textContaining('틀렸', findRichText: true), findsNothing);
    expect(find.textContaining('못', findRichText: true), findsNothing);
  });

  testWidgets('같은 닉네임으로 다시 시작하면 서버가 준 숙련도를 그대로 보인다', (WidgetTester tester) async {
    // 앱 재시작 = 새 ProviderScope(상태 없음). 서버는 같은 닉네임의 숙련도 0.35를 돌려준다.
    await _openProblem(tester, _FakeGoldenApi(sessionMastery: 0.35));

    expect(find.text('숙련도 0.35'), findsOneWidget);
  });

  test('바뀐 양 표기 — 부호·둘째 자리·부동소수 오차 흡수', () {
    expect(ResultScreen.formatDelta(0.10), '+0.10');
    expect(ResultScreen.formatDelta(-0.05), '−0.05');
    expect(ResultScreen.formatDelta(0.15 - 0.10), '+0.05');
    expect(ResultScreen.formatDelta(0.0), '±0.00');
  });
}
