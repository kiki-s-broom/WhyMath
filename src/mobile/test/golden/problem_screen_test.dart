// 골든 패스 문제 화면 위젯 테스트(S6) — 가짜 API를 Provider로 주입해 서버 없이 돌린다.
//
// ① 문제가 렌더된다(LaTeX 구간은 Math 위젯)
// ② "모르겠어요" 전송 후 튜터 말풍선 1개 추가
// ③ graded 응답 후 결과 화면으로 바뀐다(S6에서는 판정 줄이었고, S7에서 결과 화면으로 바뀜)
// (+) 서버 꺼짐이면 오류 한 줄이 보이고 앱은 그대로

import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/golden/golden_api.dart';
import 'package:korean_math_app/golden/golden_app.dart';
import 'package:korean_math_app/golden/golden_state.dart';
import 'package:korean_math_app/golden/problem_screen.dart';

/// 가짜 API — 정해 둔 응답을 차례로 돌려주고, 받은 요청을 기록한다.
class _FakeGoldenApi implements GoldenApi {
  _FakeGoldenApi({this.answers = const <AnswerResult>[], this.failSession = false});

  final List<AnswerResult> answers;
  final bool failSession;
  final List<String> sentTexts = <String>[];
  int _next = 0;

  static const GoldenProblem problem = GoldenProblem(
    id: 'LF-07',
    stem: r'일차함수 $f(x) = 2x + 7$에 대하여 $f(2)$를 구하시오.',
    index: 7,
    total: 30,
  );

  @override
  Future<GoldenSession> createSession(String nickname) async {
    if (failSession) {
      throw const GoldenApiException(kServerUnreachableMessage);
    }
    return GoldenSession(sessionId: 'sid-1', nickname: nickname, mastery: 0.0);
  }

  @override
  Future<GoldenProblem> nextProblem(String sessionId) async => problem;

  @override
  Future<AnswerResult> answer(String sessionId, String problemId, String text) async {
    sentTexts.add(text);
    return answers[_next++];
  }
}

/// 가짜 API를 끼운 앱을 띄우고 닉네임으로 시작해 문제 화면까지 간다.
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
  testWidgets('① 문제가 렌더된다 — 본문 텍스트 + LaTeX 구간 2개는 Math 위젯', (WidgetTester tester) async {
    await _openProblem(tester, _FakeGoldenApi());

    expect(find.byKey(const Key('golden_stem')), findsOneWidget);
    // 한국어 본문은 텍스트로 보인다
    expect(find.textContaining('일차함수', findRichText: true), findsOneWidget);
    expect(find.textContaining('를 구하시오.', findRichText: true), findsOneWidget);
    // $...$ 구간 2개($f(x) = 2x + 7$, $f(2)$)는 Math.tex로 그려진다
    expect(find.byType(Math), findsNWidgets(2));
    // 상단에 문제 위치와 숙련도(S7에서 "LF-07 · 7/30" 작은 줄로 바뀜)
    expect(find.text('LF-07 · 7/30'), findsOneWidget);
    expect(find.text('숙련도 0.00'), findsOneWidget);
    // 대화는 아직 비어 있다
    expect(find.byType(ChatBubble), findsNothing);
  });

  testWidgets('② "모르겠어요" 전송 후 튜터 말풍선 1개가 추가된다', (WidgetTester tester) async {
    final _FakeGoldenApi api = _FakeGoldenApi(
      answers: const <AnswerResult>[
        TutorTurn(message: '어느 부분이 막히는지 한 가지만 말해 줄래?', turn: 1),
      ],
    );
    await _openProblem(tester, api);

    await _sendAnswer(tester, '모르겠어요');

    expect(api.sentTexts, <String>['모르겠어요']);
    expect(find.byKey(const Key('golden_bubble_student')), findsOneWidget);
    expect(find.byKey(const Key('golden_bubble_tutor')), findsOneWidget);
    expect(find.text('어느 부분이 막히는지 한 가지만 말해 줄래?'), findsOneWidget);
    expect(find.byKey(const Key('golden_verdict_line')), findsNothing);
  });

  testWidgets('③ graded 응답 후 문제 화면이 결과 화면으로 바뀐다', (WidgetTester tester) async {
    final _FakeGoldenApi api = _FakeGoldenApi(
      answers: const <AnswerResult>[
        TutorTurn(message: '2를 넣으면 어떻게 될까?', turn: 1),
        Graded(correct: true, mastery: 0.10, turnsUsed: 1, feedback: '맞았어요.'),
      ],
    );
    await _openProblem(tester, api);

    await _sendAnswer(tester, '모르겠어요');
    await _sendAnswer(tester, '11');

    // 결과 화면이 보이고, 문제 화면(입력창)은 사라진다 — 판정이 난 문제에는 다시 보낼 수 없다
    expect(find.byKey(const Key('golden_result_label')), findsOneWidget);
    expect(find.byKey(const Key('golden_answer_field')), findsNothing);
    expect(find.byKey(const Key('golden_send_button')), findsNothing);
  });

  testWidgets('서버 꺼짐이면 화면 위에 오류 한 줄이 보이고 앱은 닉네임 화면에 남는다',
      (WidgetTester tester) async {
    await _openProblem(tester, _FakeGoldenApi(failSession: true));

    expect(find.byKey(const Key('golden_error_banner')), findsOneWidget);
    expect(find.text(kServerUnreachableMessage), findsOneWidget);
    expect(find.byKey(const Key('golden_nickname_field')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
