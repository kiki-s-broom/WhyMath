// 골든 패스 튜터 말풍선 수식 표시 테스트(S10) — 로그 원문을 그대로 넣어 재현한다.
//
// 근거 로그(줄 번호 = turns CSV 줄, 머리줄 1행):
// - S9 3행: 튜터 문장에 `$f(x)=-3x+3$`가 들어 있었다(말풍선이 Text(text)라 원문이 보이는 경로).
// - S11 sim_no-setup 2행: `$f(x)=-3x+3$`·`$x$` — `$` 구간 2개.
// - S11 sim_no-setup 39행·sim_slope-blind_r2 18행: `\(...\)` 표기 — 같은 수식이 다른 기호로 온다.
// 기대: 튜터 말풍선의 수식 구간은 Math 위젯으로 그려지고, `$`·`\(` 기호가 화면 글자로 남지 않는다.

import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/golden/golden_state.dart';
import 'package:korean_math_app/golden/problem_screen.dart';

/// 말풍선 하나만 그려 본다(서버·Provider 불필요).
Future<void> _pumpBubble(WidgetTester tester, String who, String text) async {
  await tester.pumpWidget(
    MaterialApp(home: Scaffold(body: ChatBubble(who: who, text: text))),
  );
}

/// 화면에 보이는 글자(RichText의 평문)를 모두 이어 붙인다 — 수식 위젯 안 글자는 포함하지 않는다.
String _visiblePlainText(WidgetTester tester) {
  return tester
      .widgetList<RichText>(find.byType(RichText))
      .map((RichText r) => r.text.toPlainText(includePlaceholders: false))
      .join('\n');
}

void main() {
  testWidgets(r'S11 no-setup 2행 — 튜터 말풍선의 $...$ 구간 2개는 Math 위젯', (WidgetTester tester) async {
    await _pumpBubble(
      tester,
      kWhoTutor,
      r'5라고 생각했구나. 그럼 $f(x)=-3x+3$에서 $x$ 자리에 5를 넣으면 오른쪽 식이 어떻게 되는지 말해 볼래?',
    );
    expect(find.byType(Math), findsNWidgets(2));
    expect(_visiblePlainText(tester), isNot(contains(r'$')));
    expect(_visiblePlainText(tester), contains('5라고 생각했구나'));
  });

  testWidgets(r'S11 no-setup 39행 — 튜터 말풍선의 \(...\) 구간 3개도 Math 위젯', (WidgetTester tester) async {
    await _pumpBubble(
      tester,
      kWhoTutor,
      r'x 자리에 -2를 넣는 것이라고 생각한 거구나. 그럼 \(f(x)=5x-1\)에서 \(x\)가 있던 자리에 '
      r'\(-2\)를 그대로 넣으면 오른쪽 식이 어떻게 되는지 말해 볼래?',
    );
    expect(find.byType(Math), findsNWidgets(3));
    expect(_visiblePlainText(tester), isNot(contains(r'\(')));
  });

  testWidgets('학생 말풍선은 입력한 글자 그대로 보인다(수식 변환 없음)', (WidgetTester tester) async {
    // 학생이 친 글자는 고치지 않는다 — 학생이 `$`를 쳤다면 그대로 보여야 한다.
    await _pumpBubble(tester, kWhoStudent, r'$x$에 5 넣어요?');
    expect(find.byType(Math), findsNothing);
    expect(_visiblePlainText(tester), contains(r'$x$에 5 넣어요?'));
  });
}
