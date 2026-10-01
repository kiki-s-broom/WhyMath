// 채팅 버블 재빌드 범위 — 키보드가 오르내리는 동안 버블이 다시 빌드되지 않는다(MOB-24 ④).
//
// 재빌드 원인은 **두 가지이고 서로 다르다**(2026-09-30 실측·이 테스트가 둘 다 고정한다):
//  ① 목록이 `LayoutBuilder` 안에 있었다 — 키보드로 body 높이가 줄 때마다 `LayoutBuilder`가 목록을 새로
//     만들고(`SliverChildBuilderDelegate.shouldRebuild`는 항상 true) 보이는 버블을 전부 강제 재빌드한다.
//     **키보드 프레임마다** 일어난다. 실측(버블 6개·신호 카드 3개·키보드 5프레임): 원본 `_MessageBubble` 30회·
//     `CoachSignalCard` 15회. 이 원인은 버블의 MediaQuery 구독과 무관하다 — `MediaQuery.sizeOf`만 적용해도
//     30·15회 그대로였다(Scaffold가 body 하위 MediaQuery에서 키보드 `viewInsets`를 제거하기 때문이다).
//  ② 버블·카드가 폭만 읽으면서 `MediaQuery.of(context)`로 MediaQuery *전체*를 구독했다 — 하단 시스템 인셋
//     (홈 인디케이터·제스처 바)이 있는 폰에서는 키보드가 오르내리는 **첫·끝 프레임**에 body MediaQuery의
//     `padding.bottom`이 바뀌어(`max(0, viewPadding − viewInsets)`) 모든 버블·카드가 다시 빌드된다. 하단 인셋이
//     없는 창에서는 재현되지 않으므로, 이 테스트는 34dp 시스템 인셋을 재현한다.
// 두 조치(목록을 LayoutBuilder 밖으로 + `sizeOf`)가 모두 있어야 0회다. 뮤테이션 실측(12프레임): 목록을
// LayoutBuilder 안에서 만들면 버블 83회, 버블이 `MediaQuery.of`면 14회, 카드가 `MediaQuery.of`면 7회.
//
// 판정은 벽시계가 아니라 **재빌드 횟수**(결정론적 대리지표)로 한다. 프로덕션 코드에는 카운터를 넣지
// 않는다 — Flutter가 제공하는 `debugOnRebuildDirtyWidget` 훅으로 테스트가 밖에서 센다.
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';
import 'package:korean_math_app/features/chat/presentation/coach_emphasis_text.dart';
import 'package:korean_math_app/features/chat/presentation/coach_signal_card.dart';

/// 신호 카드가 붙는 코치 응답을 돌려주는 fake — 코치 버블마다 [CoachSignalCard]가 그려진다.
class _SignalCoachApi extends CoachApi {
  _SignalCoachApi({this.prompt = '먼저 무엇이 주어졌는지 정리해 볼까요?'}) : super(Dio());

  final String prompt;

  CoachTurnResult _result(String dialogueId) => CoachTurnResult(
    dialogueId: dialogueId,
    response: CoachResponse(
      decision: PedagogyDecision(
        polyaStageToAdvance: 'stay',
        prompt: prompt,
        system: '시스템(테스트)',
        socraticCategory: '조건확인',
      ),
      solutionCoaching: const SolutionCoaching(
        // trigger.prompt는 비워 추가 코치 버블을 만들지 않는다(카드만 붙인다).
        trigger: CoachingTrigger(
          focus: 'verify',
          rationale: '근거(테스트)',
          prompt: '',
          socraticCategory: '검증',
        ),
        arithmeticError: true,
        errorKind: 'arithmetic',
      ),
    ),
    wh1TurnIndex: 1,
  );

  @override
  Future<CoachTurnResult> createSession(CoachRequest request, {String? problemId}) async =>
      _result('dialogue-1');

  @override
  Future<CoachTurnResult> addTurn(String dialogueId, CoachRequest request) async =>
      _result(dialogueId);
}

/// 위젯 타입별 재빌드 횟수 프로브 — 프레임워크 훅만 쓴다(프로덕션 코드 무변경).
///
/// **이미 살아 있던 요소([tracked])가 다시 빌드된 횟수만** 센다. 키보드가 내려올 때 목록이 다시 길어지면
/// 화면 밖에서 폐기됐던 버블이 *새로* 만들어져 첫 빌드가 일어나는데, 그것은 낭비된 재빌드가 아니라 리스트
/// 가상화의 정상 동작이다 — 새 요소는 tracked에 없으므로 제외된다(레이아웃이 바뀌어도 오탐이 나지 않는다).
class _RebuildProbe {
  final Map<String, int> _counts = <String, int>{};
  Set<Element> _tracked = <Element>{};

  void start(Iterable<Element> tracked) {
    _tracked = tracked.toSet();
    debugOnRebuildDirtyWidget = (Element e, bool builtOnce) {
      if (!_tracked.contains(e)) {
        return;
      }
      final String name = e.widget.runtimeType.toString();
      _counts[name] = (_counts[name] ?? 0) + 1;
    };
  }

  void stop() => debugOnRebuildDirtyWidget = null;

  void reset() => _counts.clear();

  int of(String typeName) => _counts[typeName] ?? 0;
}

/// 대화 버블 위젯의 타입 이름 — 비공개 클래스라 이름으로 센다. 이름이 바뀌면 양성 대조군(새 메시지를 보내면
/// 0보다 커야 한다)이 실패해 "측정 장치가 죽었다"를 알리므로, 조용히 통과하지 않는다.
const String _bubbleType = '_MessageBubble';

/// 지금 화면에 있는 버블·신호 카드·코치 본문 요소 전체(오프스테이지 포함 — 캐시 구간의 것도 살아 있는 요소다).
Iterable<Element> _bubbleElements(WidgetTester tester) => tester.elementList(
  find.byWidgetPredicate(
    (Widget w) => w.runtimeType.toString() == _bubbleType || w is CoachSignalCard || w is CoachEmphasisText,
    skipOffstage: false,
  ),
);

Widget _wrap(CoachApi api) => ProviderScope(
  overrides: [coachApiProvider.overrideWithValue(api)],
  child: const MaterialApp(home: ChatScreen()),
);

/// 하단 시스템 인셋(홈 인디케이터·제스처 바) 높이(dp) — 요즘 폰은 거의 다 가진다(iPhone 34·안드로이드 제스처 내비 ~24).
const double _systemBottomInset = 34;

/// 폰급 논리 크기(411×756·dpr 1.0)로 창을 잡는다(MOB-02 오버플로 테스트와 같은 창) — 하단 시스템 인셋 포함.
void _phoneWindow(WidgetTester tester) {
  tester.view.physicalSize = const Size(411, 756);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  _setKeyboardInset(tester, 0);
}

/// 키보드 높이 [bottom]에 맞춰 창의 inset을 **엔진 의미론대로** 바꾼다.
///
/// `viewPadding`은 시스템 UI 전체 높이(키보드와 무관·고정), `viewInsets`는 키보드가 가리는 높이, `padding`은
/// 그 둘을 뺀 실제 안전영역이라 키보드가 시스템 인셋 위로 올라오면 그만큼 줄어든다(`max(0, viewPadding − viewInsets)`).
/// `viewInsets`만 바꾸는 테스트는 이 변화를 재현하지 못해 실제 폰의 첫·끝 프레임(padding이 바뀌는 프레임)을 놓친다.
void _setKeyboardInset(WidgetTester tester, double bottom) {
  tester.view.viewPadding = const FakeViewPadding(bottom: _systemBottomInset);
  tester.view.viewInsets = FakeViewPadding(bottom: bottom);
  tester.view.padding = FakeViewPadding(bottom: math.max(0, _systemBottomInset - bottom));
}

Future<void> _sendMessage(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.tap(find.byIcon(Icons.send));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('키보드 inset이 바뀌는 프레임에도 대화 버블·신호 카드는 다시 빌드되지 않는다 (MOB-24)', (tester) async {
    _phoneWindow(tester);
    final probe = _RebuildProbe();
    addTearDown(probe.stop);
    await tester.pumpWidget(_wrap(_SignalCoachApi()));
    for (final String t in <String>['첫째 발화', '둘째 발화', '셋째 발화']) {
      await _sendMessage(tester, t);
    }
    // 대조군 — 버블 6개(학생 3+코치 3)·신호 카드 3개가 실제로 그려져 있다.
    expect(find.byType(CoachSignalCard), findsNWidgets(3));
    expect(find.byType(CoachEmphasisText), findsNWidgets(3));

    // 양성 대조군 — 프로브가 *이미 있던* 버블의 재빌드를 실제로 센다(훅이 죽었거나 위젯 이름이 바뀌면 여기서
    // 실패한다). 새 메시지가 붙으면 대화 상태가 바뀌어 기존 버블도 다시 빌드되는 것이 정상이다.
    probe.start(_bubbleElements(tester));
    await _sendMessage(tester, '넷째 발화');
    expect(probe.of(_bubbleType), greaterThan(0), reason: '새 메시지가 붙으면 기존 버블이 다시 빌드돼야 한다 — 프로브가 죽었다');
    expect(probe.of((CoachSignalCard).toString()), greaterThan(0));
    expect(probe.of((CoachEmphasisText).toString()), greaterThan(0));
    probe.stop();
    probe.reset();

    // 키보드가 올라오는 프레임들(0→300px)과 내려가는 프레임들 — 창 크기(size)는 그대로, viewInsets만 바뀐다.
    // 이 시점에 살아 있는 요소만 추적한다(가상화로 새로 만들어지는 요소는 재빌드가 아니다).
    probe.start(_bubbleElements(tester));
    final double heightIdle = tester.getSize(find.byType(ListView)).height;
    for (var b = 50; b <= 300; b += 50) {
      _setKeyboardInset(tester, b.toDouble());
      await tester.pump();
    }
    final double heightWithKeyboard = tester.getSize(find.byType(ListView)).height;
    for (var b = 250; b >= 0; b -= 50) {
      _setKeyboardInset(tester, b.toDouble());
      await tester.pump();
    }
    probe.stop();

    // 대조군 — 그 프레임들이 실제로 화면 레이아웃에 닿았다(목록 높이가 키보드만큼 줄었다가 돌아온다).
    expect(heightWithKeyboard, lessThan(heightIdle), reason: 'inset 프레임이 body에 닿지 않았다 — 테스트가 공허하다');
    expect(tester.getSize(find.byType(ListView)).height, heightIdle);

    // 핵심 — 그 12프레임 동안 버블·카드·코치 본문은 한 번도 다시 빌드되지 않았다.
    expect(probe.of(_bubbleType), 0, reason: '키보드 프레임마다 버블이 재빌드되면 대화가 길수록 입력이 버벅인다');
    expect(probe.of((CoachSignalCard).toString()), 0);
    expect(probe.of((CoachEmphasisText).toString()), 0);
  });

  testWidgets('말풍선 최대 폭은 여전히 화면 폭의 78%다 — sizeOf 전환이 폭 계산을 바꾸지 않는다 (MOB-24)', (tester) async {
    _phoneWindow(tester);
    // 한 줄에 다 안 들어가는 긴 코치 발화 — 폭이 상한에 닿는다.
    final String longPrompt = List<String>.filled(30, '주어진 조건을 하나씩 정리해 볼까요?').join(' ');
    await tester.pumpWidget(_wrap(_SignalCoachApi(prompt: longPrompt)));
    await _sendMessage(tester, '시작');

    final Finder coachBubble = find.ancestor(
      of: find.byType(CoachEmphasisText),
      matching: find.byType(Container),
    );
    final double width = tester.getSize(coachBubble.first).width;
    const double maxWidth = 411 * 0.78;
    expect(width, lessThanOrEqualTo(maxWidth + 0.01));
    // 상한에 실제로 닿았는지(짧은 글이라 공허하게 통과하지 않도록) — 긴 글은 상한 근처까지 찬다.
    expect(width, greaterThan(maxWidth * 0.9));
  });
}
