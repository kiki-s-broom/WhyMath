// 채팅 입력창 — 응답 대기 중에도 입력은 열려 있고, 잠기는 것은 *전송 동작*뿐이다(MOB-24 ③).
//
// 배경: 예전에는 코치 응답을 기다리는 동안(`isSending`) 입력창 자체가 잠겼다. 그러면 키보드가 내려가고
// 학생은 응답이 올 때까지 다음 생각을 적어 둘 수 없다. 이제 글쓰기·모드 전환·단계 편집은 대기 중에도 열고,
// 보내기 버튼·키보드 '보내기'(Enter)·풀이 제출만 잠근다.
//
// 이 파일이 고정하는 것(잠금을 좁히면 생기는 위험 3가지):
//  1) 입력이 정말 열려 있다(대기 중 글쓰기·단계 편집·단계 추가).
//  2) 대기 중 전송 시도가 **중복 요청을 만들지 않고**, 써 둔 글도 지우지 않는다 — `_onSend`는 예전에
//     "입력창을 비운 뒤 send를 부르는" 순서라서, 잠금 없이 입력을 열기만 하면 컨트롤러가 재진입을 막아 줘도
//     글이 지워진 채 전송이 무시된다.
//  3) 응답이 와도 써 둔 글이 남고, 그 글이 한 번만 나간다.
// 컨트롤러가 재진입을 스스로 막는다는 사실(방어 2겹 중 안쪽)도 별도 테스트로 고정한다.
import 'dart:async';
import 'dart:collection';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/chat/application/chat_controller.dart';
import 'package:korean_math_app/features/chat/application/completion_signal.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';

/// 응답을 게이트로 붙잡아 "응답 대기 중" 상태를 결정적으로 만드는 fake.
///
/// [gates]는 호출 순서대로 하나씩 소비된다 — 게이트가 있는 호출은 그 Completer가 끝날 때까지 응답하지 않는다.
class _GatedCoachApi extends CoachApi {
  _GatedCoachApi({this.completes = false}) : super(Dio());

  /// true면 응답이 서버의 '문항 완료' 신호(problem_complete)를 싣는다(종단 상태 상호작용 검증용).
  final bool completes;

  final Queue<Completer<void>> gates = Queue<Completer<void>>();
  final List<CoachRequest> requests = <CoachRequest>[];
  int createCalls = 0;
  int turnCalls = 0;

  /// 서버로 나간 요청 총수 — 이 숫자가 곧 "중복 요청이 있었는가"다.
  int get calls => createCalls + turnCalls;

  CoachTurnResult _result(String dialogueId) => CoachTurnResult(
    dialogueId: dialogueId,
    response: const CoachResponse(
      decision: PedagogyDecision(
        polyaStageToAdvance: 'stay',
        prompt: '먼저 무엇이 주어졌는지 정리해 볼까요?',
        system: '시스템(테스트)',
        socraticCategory: '조건확인',
      ),
    ),
    wh1TurnIndex: 1,
    problemComplete: completes,
    completedAttemptId: completes ? 'att-1' : null,
  );

  @override
  Future<CoachTurnResult> createSession(CoachRequest request, {String? problemId}) async {
    createCalls++;
    requests.add(request);
    if (gates.isNotEmpty) {
      await gates.removeFirst().future;
    }
    return _result('dialogue-1');
  }

  @override
  Future<CoachTurnResult> addTurn(String dialogueId, CoachRequest request) async {
    turnCalls++;
    requests.add(request);
    if (gates.isNotEmpty) {
      await gates.removeFirst().future;
    }
    return _result(dialogueId);
  }
}

Widget _wrap(CoachApi api) => ProviderScope(
  overrides: [coachApiProvider.overrideWithValue(api)],
  child: const MaterialApp(home: ChatScreen()),
);

/// 대화 모드 입력창의 컨트롤러 텍스트 — 화면에 그려진 글이 아니라 실제 입력 상태를 읽는다.
String _typed(WidgetTester tester) =>
    tester.widget<TextField>(find.byType(TextField)).controller!.text;

/// 대화 모드에서 첫 발화를 보내고 응답이 게이트에 걸린 상태(전송 중)로 만든다.
Future<Completer<void>> _startFirstSend(WidgetTester tester, _GatedCoachApi api) async {
  final gate = Completer<void>();
  api.gates.add(gate);
  await tester.pumpWidget(_wrap(api));
  await tester.enterText(find.byType(TextField), '첫 생각');
  await tester.tap(find.byIcon(Icons.send));
  await tester.pump(); // 전송이 시작돼 화면이 대기 상태로 다시 그려진다(응답은 게이트에 걸려 있다).
  return gate;
}

bool _isFocusedInsideTextField() {
  final BuildContext? focused = FocusManager.instance.primaryFocus?.context;
  return focused != null && focused.findAncestorWidgetOfExactType<TextField>() != null;
}

void main() {
  group('대화 모드 — 응답 대기 중 입력·전송 (MOB-24)', () {
    testWidgets('응답 대기 중에도 입력창은 열려 있고 다음 생각을 적을 수 있다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await _startFirstSend(tester, api);

      // 대조군 — 정말 대기 중이다(선형 인디케이터·요청 1건 진행).
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      expect(api.calls, 1);

      // 입력창은 잠기지 않는다. (TextField.enabled는 bool? — null도 '활성'이라 == true로 확정해서 본다.)
      expect(tester.widget<TextField>(find.byType(TextField)).enabled, isTrue);
      await tester.enterText(find.byType(TextField), '대기 중에 쓰는 다음 생각');
      expect(_typed(tester), '대기 중에 쓰는 다음 생각');

      gate.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('대기 중 보내기 버튼은 잠기고, 눌러도 요청이 늘지 않으며 써 둔 글도 그대로다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await _startFirstSend(tester, api);
      await tester.enterText(find.byType(TextField), '대기 중 다음 생각');

      final IconButton sendButton = tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.send));
      expect(sendButton.onPressed, isNull, reason: '전송 동작은 대기 중 잠겨야 한다');
      // 변별력: 실제로 눌러 본다. 잠금이 풀려 있으면 여기서 요청이 늘거나(컨트롤러 가드가 없다면) 글이 지워진다.
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump();

      expect(api.calls, 1, reason: '대기 중 전송 시도가 중복 요청을 만들면 안 된다');
      expect(_typed(tester), '대기 중 다음 생각', reason: '보내지 못한 글이 지워지면 학생이 써 둔 생각이 사라진다');

      gate.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('대기 중 키보드 보내기(Enter)로도 중복 요청이 나가지 않고, 글과 키보드 포커스가 유지된다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await _startFirstSend(tester, api);
      await tester.enterText(find.byType(TextField), '대기 중 다음 생각');
      expect(_isFocusedInsideTextField(), isTrue); // 대조군 — 입력창에 포커스가 있다.

      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pump();

      expect(api.calls, 1, reason: 'Enter도 전송 동작이다 — 대기 중엔 나가면 안 된다');
      expect(_typed(tester), '대기 중 다음 생각');
      // '보내기' 키의 기본 동작은 포커스를 내려놓는(키보드를 내리는) 것이다 — 전송이 막힌 동안엔 이어 쓸 수
      // 있게 유지해야 한다.
      expect(_isFocusedInsideTextField(), isTrue, reason: '막힌 전송이 키보드를 내리면 학생이 다시 눌러야 한다');

      gate.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('전송 직후 다음 프레임 전에 Enter가 들어와도(잠금이 아직 낡은 창) 글이 지워지지 않고 요청도 1건이다 (MOB-24)', (tester) async {
      // 보내기를 누른 순간 컨트롤러의 isSending은 곧바로 true지만, 화면의 잠금 플래그는 *다음 프레임에야*
      // 바뀐다. 그 사이에 들어온 Enter는 낡은 플래그(전송 가능)를 본다 — `_onSend`가 살아 있는 상태를 직접
      // 확인하지 않으면 입력창만 비워지고 전송은 컨트롤러 가드에 막혀 글이 사라진다.
      final api = _GatedCoachApi();
      final gate = Completer<void>();
      api.gates.add(gate);
      await tester.pumpWidget(_wrap(api));
      await tester.enterText(find.byType(TextField), '첫 생각');
      await tester.tap(find.byIcon(Icons.send)); // 전송 시작 — 아직 pump하지 않는다(화면은 낡은 상태).

      // 주의: `tester.enterText`는 내부에서 pump()를 한 번 돌려 화면을 '전송 중'으로 다시 그려 버린다 — 그러면
      // 잠금 플래그가 낡지 않아 이 창을 재현하지 못한다(실측: 그 방식은 `_onSend`의 가드를 지워도 통과했다).
      // 그래서 컨트롤러 텍스트를 직접 바꾸고, pump 없이 IME의 '보내기' 동작만 전달한다.
      tester.widget<TextField>(find.byType(TextField)).controller!.text = '곧바로 쓴 다음 생각';
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pump();

      expect(api.calls, 1);
      expect(_typed(tester), '곧바로 쓴 다음 생각', reason: '전송이 무시되는데 글까지 지워지면 안 된다');

      gate.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('응답이 도착해도 대기 중 쓴 글은 지워지지 않고, 그 글이 이제 정확히 한 번 전송된다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await _startFirstSend(tester, api);
      await tester.enterText(find.byType(TextField), '대기 중 쓴 다음 생각');

      gate.complete();
      await tester.pumpAndSettle();

      // 응답 도착만으로는 새 요청이 나가지 않고, 써 둔 글도 그대로다.
      expect(api.calls, 1);
      expect(_typed(tester), '대기 중 쓴 다음 생각');
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.send)).onPressed, isNotNull);

      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(api.calls, 2);
      expect(api.requests.last.studentInput, '대기 중 쓴 다음 생각');
      expect(_typed(tester), isEmpty);
    });

    testWidgets('응답이 도착한 뒤 Enter는 다시 전송으로 동작한다 — 잠금이 영구히 남지 않는다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await _startFirstSend(tester, api);
      gate.complete();
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), '응답 뒤 다음 생각');
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pumpAndSettle();

      expect(api.calls, 2);
      expect(api.requests.last.studentInput, '응답 뒤 다음 생각');
    });
  });

  group('풀이 단계 모드 — 응답 대기 중 입력·제출 (MOB-24)', () {
    /// 풀이 단계 모드로 전환해 두 단계를 제출하고 응답이 게이트에 걸린 상태로 만든다.
    Future<Completer<void>> startSolutionSend(WidgetTester tester, _GatedCoachApi api) async {
      final gate = Completer<void>();
      api.gates.add(gate);
      await tester.pumpWidget(_wrap(api));
      await tester.tap(find.byIcon(Icons.format_list_numbered)); // 풀이 단계 모드.
      await tester.pump();
      await tester.enterText(find.byType(TextField).at(0), 'a');
      await tester.enterText(find.byType(TextField).at(1), 'b');
      await tester.pump();
      await tester.tap(find.text('2단계 제출'));
      await tester.pump();
      return gate;
    }

    testWidgets('대기 중에도 단계를 적고 추가할 수 있고, 제출만 잠긴다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await startSolutionSend(tester, api);
      expect(api.calls, 1);
      expect(find.byType(LinearProgressIndicator), findsOneWidget); // 대조군 — 대기 중.

      // 단계 필드는 모두 열려 있다(전건 검사 — 일부만 열려 있어도 통과하는 위장을 막는다).
      final Iterable<TextField> fields = tester.widgetList<TextField>(find.byType(TextField));
      expect(fields, isNotEmpty);
      expect(fields.every((TextField f) => f.enabled == true), isTrue);
      await tester.enterText(find.byType(TextField).at(0), 'x=1');
      await tester.enterText(find.byType(TextField).at(1), 'x=2');
      await tester.pump();

      // "단계 추가"는 입력 구조 편집이라 대기 중에도 동작한다. (대기 구간에는 끝나지 않는 로딩 애니메이션이
      // 있어 pumpAndSettle이 영원히 안 끝난다 — 프레임을 직접 몇 번만 돌린다.)
      await tester.tap(find.text('단계 추가'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.byType(TextField), findsNWidgets(3));

      // 제출은 잠겨 있고, 눌러도 요청이 늘지 않으며 써 둔 단계도 그대로다.
      final Finder submit = find.widgetWithText(FilledButton, '2단계 제출');
      expect(tester.widget<FilledButton>(submit).onPressed, isNull, reason: '대기 중 제출은 잠겨야 한다');
      await tester.tap(submit);
      await tester.pump();
      expect(api.calls, 1);
      expect(tester.widget<TextField>(find.byType(TextField).at(0)).controller!.text, 'x=1');
      expect(tester.widget<TextField>(find.byType(TextField).at(1)).controller!.text, 'x=2');

      gate.complete();
      await tester.pumpAndSettle();
    });

    testWidgets('응답이 도착하면 대기 중 적은 단계가 그대로 남아 있고 정확히 한 번 제출된다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi();
      final gate = await startSolutionSend(tester, api);
      await tester.enterText(find.byType(TextField).at(0), 'x=1');
      await tester.enterText(find.byType(TextField).at(1), 'x=2');
      await tester.pump();

      gate.complete();
      await tester.pumpAndSettle();

      expect(api.calls, 1);
      final Finder submit = find.widgetWithText(FilledButton, '2단계 제출');
      expect(tester.widget<FilledButton>(submit).onPressed, isNotNull);
      await tester.tap(submit);
      await tester.pumpAndSettle();

      expect(api.calls, 2);
      expect(api.requests.last.solutionSteps, <String>['x=1', 'x=2']);
    });
  });

  group('완료(종단 상태)와의 상호작용 (MOB-24)', () {
    // 입력을 대기 중에도 열면서 새로 생긴 조합이다: 학생이 대기 중에 글을 써 뒀는데 응답이 '문항 완료'다.
    // 종단 상태에서는 한 턴을 더 보내면 서버가 no-op 처리해 유일한 '다음 문항으로'가 사라지므로(MOB-20),
    // 써 둔 글이 있어도 입력·전송은 다시 잠겨야 한다.

    testWidgets('대화 모드 — 대기 중 써 둔 글이 있어도 응답이 문항 완료면 입력·전송이 잠긴다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi(completes: true);
      final gate = await _startFirstSend(tester, api);
      await tester.enterText(find.byType(TextField), '대기 중 쓴 글');

      gate.complete();
      await tester.pumpAndSettle();

      expect(find.text('다음 문항으로'), findsOneWidget); // 대조군 — 완료 패널이 떴다.
      expect(tester.widget<TextField>(find.byType(TextField)).enabled, isFalse);
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.send)).onPressed, isNull);
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
      expect(api.calls, 1, reason: '끝난 세션에 턴을 더 붙이면 서버 no-op으로 유일한 진행 경로가 사라진다');
    });

    testWidgets('문항 완료 응답이 막 도착했지만 화면이 아직 안 바뀐 창에서 Enter가 와도 끝난 세션에 턴이 붙지 않는다 (MOB-24)', (tester) async {
      // 응답 처리(상태 갱신)는 끝났지만 프레임이 아직 안 그려져, 화면의 전송 잠금은 '전송 중'(막힘)으로 낡아 있다.
      // 이때 살아 있는 isSending만 보면 "대기가 끝났다"고 판단해 끝난 세션에 턴을 보낸다(서버는 no-op으로 처리해
      // 유일한 '다음 문항으로'를 없앤다 — MOB-20). 낡은 '막힘'을 존중하는 화면 쪽 가드가 이 창을 닫는다.
      final api = _GatedCoachApi(completes: true);
      final gate = await _startFirstSend(tester, api);
      await tester.enterText(find.byType(TextField), '대기 중 쓴 글'); // 이 안의 pump로 '전송 중' 화면이 확정된다.

      gate.complete();
      await tester.idle(); // 응답 처리만 돌리고 프레임은 그리지 않는다.
      final ProviderContainer container = ProviderScope.containerOf(tester.element(find.byType(ChatScreen)));
      // 대조군 — 창이 실제로 열려 있다: 상태는 이미 '대기 끝·문항 완료'인데 화면은 아직 안 바뀌었다.
      expect(container.read(chatControllerProvider).isSending, isFalse);
      expect(container.read(coachCompletionSignalProvider).problemComplete, isTrue);
      expect(find.text('다음 문항으로'), findsNothing);

      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pump();

      expect(api.calls, 1, reason: '끝난 세션에 턴을 붙이면 서버 no-op으로 유일한 진행 경로가 사라진다');
      await tester.pumpAndSettle();
      expect(find.text('다음 문항으로'), findsOneWidget);
    });

    testWidgets('풀이 단계 모드 — 대기 중 적어 둔 단계가 있어도 응답이 문항 완료면 필드·제출이 잠긴다 (MOB-24)', (tester) async {
      final api = _GatedCoachApi(completes: true);
      final gate = Completer<void>();
      api.gates.add(gate);
      await tester.pumpWidget(_wrap(api));
      await tester.tap(find.byIcon(Icons.format_list_numbered));
      await tester.pump();
      await tester.enterText(find.byType(TextField).at(0), 'a');
      await tester.enterText(find.byType(TextField).at(1), 'b');
      await tester.pump();
      await tester.tap(find.text('2단계 제출'));
      await tester.pump();
      await tester.enterText(find.byType(TextField).at(0), 'x=1'); // 대기 중 적어 둔 단계.
      await tester.enterText(find.byType(TextField).at(1), 'x=2');
      await tester.pump();

      gate.complete();
      await tester.pumpAndSettle();

      expect(find.text('다음 문항으로'), findsOneWidget);
      final Iterable<TextField> fields = tester.widgetList<TextField>(find.byType(TextField));
      expect(fields, isNotEmpty);
      expect(fields.every((TextField f) => f.enabled == false), isTrue, reason: '완료 뒤엔 단계 필드가 하나도 열려 있으면 안 된다');
      final Finder submit = find.widgetWithText(FilledButton, '2단계 제출');
      expect(tester.widget<FilledButton>(submit).onPressed, isNull, reason: '써 둔 단계가 있어도 종단 상태에선 제출이 잠겨야 한다');
      expect(api.calls, 1);
    });
  });

  group('컨트롤러 재진입 방어 (MOB-24)', () {
    ProviderContainer containerWith(_GatedCoachApi api) {
      final container = ProviderContainer(overrides: [coachApiProvider.overrideWithValue(api)]);
      addTearDown(container.dispose);
      // ChatController는 autoDispose — await 중 폐기되지 않게 리스너로 붙잡는다.
      container.listen(chatControllerProvider, (_, __) {}, fireImmediately: true);
      return container;
    }

    test('응답 대기 중 들어온 send·sendSolution은 요청을 만들지 않는다 (MOB-24)', () async {
      final api = _GatedCoachApi();
      final gate = Completer<void>();
      api.gates.add(gate);
      final container = containerWith(api);
      final ChatController notifier = container.read(chatControllerProvider.notifier);

      final Future<void> first = notifier.send('첫 발화'); // 진행 중(응답은 게이트에 걸려 있다).
      expect(container.read(chatControllerProvider).isSending, isTrue);

      await notifier.send('둘째 발화'); // 즉시 반환 — 요청 없음.
      await notifier.sendSolution('a\nb'); // 즉시 반환 — 요청 없음.
      expect(api.calls, 1, reason: '재진입이 요청을 만들면 학생 발화가 서버에 중복 적재된다');
      // 대기 중 들어온 발화는 대화 목록에도 남지 않는다(첫 발화 1건뿐).
      expect(container.read(chatControllerProvider).messages, hasLength(1));

      gate.complete();
      await first;
      expect(api.calls, 1);
      expect(container.read(chatControllerProvider).isSending, isFalse);
      expect(container.read(chatControllerProvider).messages, hasLength(2)); // 학생 + 코치.
    });
  });
}
