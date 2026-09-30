// ChatController.restoreLastDialogue 테스트 — 마지막 대화 이어하기(MOB-11).
//
// 네트워크를 타지 않는다 — dialogueStoreProvider·coachApiProvider를 fake로 override한다.
// 신규 엔드포인트 없이 기존 getSession만 재사용하는지, 저장된 dialogueId가 없으면 아무
// 일도 하지 않는지, 이미 세션이 시작된 상태면 되돌아온 과거 세션으로 덮지 않는지 검증한다.
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/chat/application/chat_controller.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/data/dialogue_store.dart';
import 'package:korean_math_app/features/chat/domain/chat_message.dart';

/// 메모리 DialogueStore — 주입한 값을 그대로 돌려준다.
class _FakeDialogueStore implements DialogueStore {
  _FakeDialogueStore({String? dialogueId}) : _dialogueId = dialogueId;

  String? _dialogueId;

  @override
  Future<String?> readDialogueId() async => _dialogueId;

  @override
  Future<void> saveDialogueId(String dialogueId) async =>
      _dialogueId = dialogueId;

  @override
  Future<void> clearDialogueId() async => _dialogueId = null;
}

/// 저장이 항상 실패하는 DialogueStore — 영속 실패가 코치 교환을 깨지 않는지 검증용.
class _ThrowingDialogueStore implements DialogueStore {
  @override
  Future<String?> readDialogueId() async => throw StateError('저장소 미가용(테스트)');

  @override
  Future<void> saveDialogueId(String dialogueId) async =>
      throw StateError('저장소 미가용(테스트)');

  @override
  Future<void> clearDialogueId() async => throw StateError('저장소 미가용(테스트)');
}

/// getSession 호출을 기록하고 미리 짠 스냅샷(또는 예외)을 돌려주는 fake.
class _FakeCoachApi extends CoachApi {
  _FakeCoachApi({this.snapshot, this.shouldThrow = false}) : super(Dio());

  final CoachSessionSnapshot? snapshot;
  final bool shouldThrow;

  /// getSession 호출 횟수(호출 여부 검증용).
  int getSessionCalls = 0;
  String? lastRequestedId;

  @override
  Future<CoachSessionSnapshot> getSession(String dialogueId) async {
    getSessionCalls++;
    lastRequestedId = dialogueId;
    if (shouldThrow) {
      throw DioException(
        requestOptions: RequestOptions(path: '/v1/coach/sessions/$dialogueId'),
        error: '세션 조회 실패(테스트)',
      );
    }
    return snapshot!;
  }

  int createCalls = 0;
  int turnCalls = 0;

  @override
  Future<CoachTurnResult> createSession(
    CoachRequest request, {
    String? problemId,
  }) async {
    createCalls++;
    return const CoachTurnResult(
      dialogueId: 'fresh-dialogue',
      response: _response,
      wh1TurnIndex: 1,
    );
  }

  @override
  Future<CoachTurnResult> addTurn(String dialogueId, CoachRequest request) async {
    turnCalls++;
    return CoachTurnResult(
      dialogueId: dialogueId,
      response: _response,
      wh1TurnIndex: turnCalls + 1,
    );
  }
}

const CoachResponse _response = CoachResponse(
  decision: PedagogyDecision(
    polyaStageToAdvance: 'stay',
    prompt: '무엇을 구해야 할까요?',
    system: '시스템 지시(테스트)',
    socraticCategory: '',
  ),
);

ProviderContainer _container({
  required DialogueStore dialogueStore,
  required CoachApi coachApi,
}) {
  final container = ProviderContainer(
    overrides: [
      dialogueStoreProvider.overrideWithValue(dialogueStore),
      coachApiProvider.overrideWithValue(coachApi),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  group('ChatController.restoreLastDialogue', () {
    test('저장된 dialogueId가 있으면 getSession을 호출해 메시지를 복원한다', () async {
      final fakeApi = _FakeCoachApi(
        snapshot: const CoachSessionSnapshot(
          dialogueId: 'saved-dialogue',
          totalTurns: 2,
          turns: <CoachTurn>[
            CoachTurn(turnOrder: 1, role: 'student', content: '판별식이 뭔가요?'),
            CoachTurn(
              turnOrder: 2,
              role: 'assistant',
              content: '먼저 이차방정식의 형태를 살펴볼까요?',
            ),
          ],
        ),
      );
      final container = _container(
        dialogueStore: _FakeDialogueStore(dialogueId: 'saved-dialogue'),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.restoreLastDialogue();

      expect(fakeApi.getSessionCalls, 1);
      expect(fakeApi.lastRequestedId, 'saved-dialogue');

      final state = container.read(chatControllerProvider);
      expect(state.dialogueId, 'saved-dialogue');
      expect(state.messages.length, 2);
      expect(state.messages[0].role, ChatRole.student);
      expect(state.messages[0].text, '판별식이 뭔가요?');
      expect(state.messages[1].role, ChatRole.coach);
      expect(state.messages[1].text, '먼저 이차방정식의 형태를 살펴볼까요?');
    });

    test('저장된 dialogueId가 없으면 getSession을 호출하지 않는다(신규 실행)', () async {
      final fakeApi = _FakeCoachApi();
      final container = _container(
        dialogueStore: _FakeDialogueStore(),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.restoreLastDialogue();

      expect(fakeApi.getSessionCalls, 0);
      final state = container.read(chatControllerProvider);
      expect(state.dialogueId, isNull);
      expect(state.messages, isEmpty);
    });

    test('세션 조회 실패는 조용히 지나가고 빈 대화로 남는다(가용성)', () async {
      final fakeApi = _FakeCoachApi(shouldThrow: true);
      final container = _container(
        dialogueStore: _FakeDialogueStore(dialogueId: 'gone-dialogue'),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.restoreLastDialogue();

      expect(fakeApi.getSessionCalls, 1);
      final state = container.read(chatControllerProvider);
      expect(state.dialogueId, isNull);
      expect(state.messages, isEmpty);
      expect(state.error, isNull); // 조용한 실패 — 에러 배너도 띄우지 않는다.
    });

    test('system 등 student/assistant가 아닌 role은 화면에 렌더하지 않는다', () async {
      final fakeApi = _FakeCoachApi(
        snapshot: const CoachSessionSnapshot(
          dialogueId: 'saved-dialogue',
          turns: <CoachTurn>[
            CoachTurn(turnOrder: 1, role: 'system', content: '시스템 프롬프트'),
            CoachTurn(turnOrder: 2, role: 'student', content: '안녕하세요'),
          ],
        ),
      );
      final container = _container(
        dialogueStore: _FakeDialogueStore(dialogueId: 'saved-dialogue'),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.restoreLastDialogue();

      final state = container.read(chatControllerProvider);
      expect(state.messages.length, 1);
      expect(state.messages[0].text, '안녕하세요');
    });

    test('이미 이번 실행에서 세션이 시작됐으면 되돌아온 과거 세션으로 덮지 않는다', () async {
      final fakeApi = _FakeCoachApi(
        snapshot: const CoachSessionSnapshot(
          dialogueId: 'saved-dialogue',
          turns: <CoachTurn>[
            CoachTurn(turnOrder: 1, role: 'student', content: '과거 발화'),
          ],
        ),
      );
      final container = _container(
        dialogueStore: _FakeDialogueStore(dialogueId: 'saved-dialogue'),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      // send()를 직접 부르지 않고 상태를 이미 세션이 시작된 것처럼 구성 — 이 테스트는
      // 가드(state.dialogueId != null)만 검증하면 충분하다(coachApi.send 배선은 다른
      // 테스트 파일의 책임 — chat_controller_test.dart).
      container.read(chatControllerProvider.notifier).state = container
          .read(chatControllerProvider)
          .copyWith(dialogueId: 'already-active');

      await notifier.restoreLastDialogue();

      expect(fakeApi.getSessionCalls, 0);
      expect(container.read(chatControllerProvider).dialogueId, 'already-active');
    });
  
    test('첫 발화로 세션이 생성되면 세션 ID(UUID)만 저장하고, 이후 턴은 재저장하지 않는다', () async {
      final store = _FakeDialogueStore();
      final fakeApi = _FakeCoachApi();
      final container = _container(dialogueStore: store, coachApi: fakeApi);
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.send('판별식이 뭔가요?');
      expect(fakeApi.createCalls, 1);
      expect(await store.readDialogueId(), 'fresh-dialogue');

      // 두 번째 발화는 같은 세션에 턴으로 잇는다 — 저장값은 그대로(본문은 저장 대상이 아님).
      await notifier.send('두 번째 발화');
      expect(fakeApi.turnCalls, 1);
      expect(await store.readDialogueId(), 'fresh-dialogue');
    });

    test('세션 ID 저장이 실패해도 코치 교환은 정상 완료된다(가용성)', () async {
      final fakeApi = _FakeCoachApi();
      final container = _container(
        dialogueStore: _ThrowingDialogueStore(),
        coachApi: fakeApi,
      );
      final notifier = container.read(chatControllerProvider.notifier);

      await notifier.send('안녕하세요');

      final state = container.read(chatControllerProvider);
      expect(state.dialogueId, 'fresh-dialogue');
      expect(state.error, isNull);
      expect(state.messages.length, 2);
    });

    test('저장소 읽기 실패는 조용히 지나가고 getSession을 호출하지 않는다', () async {
      final fakeApi = _FakeCoachApi();
      final container = _container(
        dialogueStore: _ThrowingDialogueStore(),
        coachApi: fakeApi,
      );

      await container.read(chatControllerProvider.notifier).restoreLastDialogue();

      expect(fakeApi.getSessionCalls, 0);
      expect(container.read(chatControllerProvider).dialogueId, isNull);
    });
  });
}
