// AuthController 단위테스트 — code 교환→토큰 저장→상태·로그아웃. OAuth-c1.
//
// 네트워크·플랫폼 채널 없이: fake AuthApi + fake TokenStore를 provider override로 주입한다
// (chat_controller_test 패턴). 토큰 발급·저장의 *배선*만 검증 — 수학·인증 결정은 서버.
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/core/api_client.dart';
import 'package:korean_math_app/core/token_refresh_api.dart';
import 'package:korean_math_app/core/token_store.dart';
import 'package:korean_math_app/features/auth/application/auth_controller.dart';
import 'package:korean_math_app/features/auth/data/auth_api.dart';
import 'package:korean_math_app/features/chat/application/chat_controller.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/data/dialogue_store.dart';
import 'package:korean_math_app/features/problems/application/active_problem.dart';
import 'package:korean_math_app/features/problems/data/problem_models.dart';

class _FakeAuthApi extends AuthApi {
  _FakeAuthApi({this.token, this.shouldThrow = false}) : super(Dio());

  final String? token;
  final bool shouldThrow;

  @override
  Future<AuthTokens> login({
    required String provider,
    required String code,
    required String redirectUri,
  }) async {
    if (shouldThrow) {
      throw DioException(
        requestOptions: RequestOptions(path: '/v1/auth/$provider/callback'),
        error: '네트워크 실패(테스트)',
      );
    }
    // MOB-12: 서버는 액세스+리프레시 두 토큰을 함께 준다.
    return AuthTokens(accessToken: token!, refreshToken: 'refresh-$token');
  }
}

/// 인메모리 리프레시 토큰 저장소(MOB-12) — 플랫폼 채널 회피.
class _FakeRefreshTokenStore implements RefreshTokenStore {
  String? saved;
  bool cleared = false;

  @override
  Future<String?> readRefreshToken() async => saved;

  @override
  Future<void> saveRefreshToken(String token) async => saved = token;

  @override
  Future<void> clearRefreshToken() async {
    saved = null;
    cleared = true;
  }
}

/// 서버 로그아웃 호출을 캡처하는 fake — 실제 HTTP 없이 배선만 검증한다.
class _FakeTokenRefreshApi extends TokenRefreshApi {
  _FakeTokenRefreshApi() : super(Dio());

  final List<String> loggedOut = <String>[];

  @override
  Future<void> logout(String refreshToken) async => loggedOut.add(refreshToken);
}

/// 서버 로그아웃이 실패하는 fake — 오프라인 상황의 로컬 정리 보장을 검증한다.
class _ThrowingTokenRefreshApi extends TokenRefreshApi {
  _ThrowingTokenRefreshApi() : super(Dio());

  @override
  Future<void> logout(String refreshToken) async =>
      throw DioException(requestOptions: RequestOptions(path: '/v1/auth/logout'));
}

class _FakeTokenStore implements TokenStore {
  String? saved;
  bool cleared = false;

  @override
  Future<String?> readAccessToken() async => saved;

  @override
  Future<void> saveAccessToken(String token) async => saved = token;

  @override
  Future<void> clear() async {
    saved = null;
    cleared = true;
  }
}

/// 읽기에서 오류를 던지는 TokenStore — restore()의 방어적 처리(앱 안 죽음)를 검증한다.
class _ThrowingTokenStore implements TokenStore {
  @override
  Future<String?> readAccessToken() async => throw Exception('보안 저장소 오류(테스트)');

  @override
  Future<void> saveAccessToken(String token) async {}

  @override
  Future<void> clear() async {}
}

/// 인메모리 대화 세션 참조 저장소(MOB-11) — 로그아웃 정리 검증용.
class _FakeDialogueStore implements DialogueStore {
  _FakeDialogueStore([this.dialogueId]);

  String? dialogueId;

  @override
  Future<String?> readDialogueId() async => dialogueId;

  @override
  Future<void> saveDialogueId(String value) async => dialogueId = value;

  @override
  Future<void> clearDialogueId() async => dialogueId = null;
}

/// 세션 잔여 재현용 fake(MOB-23) — 코치 응답 1개를 그대로 돌려준다(chat_controller_test 패턴 축약).
class _FakeCoachApi extends CoachApi {
  _FakeCoachApi() : super(Dio());

  @override
  Future<CoachTurnResult> createSession(
    CoachRequest request, {
    String? problemId,
  }) async {
    return CoachTurnResult(
      dialogueId: 'prev-student-dialogue',
      response: CoachResponse(
        decision: PedagogyDecision(
          polyaStageToAdvance: 'stay',
          prompt: '이전 학생 발화에 대한 응답(테스트)',
          system: '시스템(테스트)',
          socraticCategory: '',
        ),
      ),
      wh1TurnIndex: 1,
    );
  }

  @override
  Future<CoachTurnResult> addTurn(String dialogueId, CoachRequest request) {
    throw UnimplementedError('이 테스트는 첫 턴만 쓴다');
  }
}

/// 모든 요청에 401을 돌려주는 어댑터 — dioProvider의 세션 무효 배선(MOB-15)을 네트워크 없이 검증.
class _UnauthorizedAdapter implements HttpClientAdapter {
  int requests = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests++;
    return ResponseBody.fromString('{}', 401, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    });
  }

  @override
  void close({bool force = false}) {}
}

ProviderContainer _container(
  AuthApi api,
  TokenStore store, {
  RefreshTokenStore? refreshStore,
  TokenRefreshApi? refreshApi,
  DialogueStore? dialogueStore,
  CoachApi? coachApi,
}) {
  final container = ProviderContainer(
    overrides: [
      authApiProvider.overrideWithValue(api),
      tokenStoreProvider.overrideWithValue(store),
      // MOB-12: 리프레시 토큰 저장·서버 로그아웃 호출도 fake로 — 실 구현은 플랫폼 채널/HTTP다.
      refreshTokenStoreProvider.overrideWithValue(refreshStore ?? _FakeRefreshTokenStore()),
      tokenRefreshApiProvider.overrideWithValue(refreshApi ?? _FakeTokenRefreshApi()),
      dialogueStoreProvider.overrideWithValue(dialogueStore ?? _FakeDialogueStore()),
      // MOB-23: 이전 학생의 코치 대화 잔여를 재현하는 테스트만 주입한다(기본은 실 구현 — 미사용).
      if (coachApi != null) coachApiProvider.overrideWithValue(coachApi),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  test('completeLogin 성공 → 액세스+리프레시 저장 + isAuthenticated', () async {
    final store = _FakeTokenStore();
    final refreshStore = _FakeRefreshTokenStore();
    final container = _container(_FakeAuthApi(token: 'tok'), store, refreshStore: refreshStore);
    await container
        .read(authControllerProvider.notifier)
        .completeLogin(provider: 'kakao', code: 'c', redirectUri: 'r');
    final state = container.read(authControllerProvider);
    expect(store.saved, 'tok');
    // MOB-12: 리프레시 토큰을 버리지 않고 저장해야 이후 무중단 갱신이 가능하다.
    expect(refreshStore.saved, 'refresh-tok');
    expect(state.isAuthenticated, isTrue);
    expect(state.isSubmitting, isFalse);
    expect(state.error, isNull);
  });

  test('completeLogin 실패 → error·미저장·미인증(앱 안 죽음)', () async {
    final store = _FakeTokenStore();
    final container = _container(_FakeAuthApi(shouldThrow: true), store);
    await container
        .read(authControllerProvider.notifier)
        .completeLogin(provider: 'kakao', code: 'c', redirectUri: 'r');
    final state = container.read(authControllerProvider);
    expect(store.saved, isNull);
    expect(state.error, isNotNull);
    expect(state.isAuthenticated, isFalse);
    expect(state.isSubmitting, isFalse);
  });

  test('logout → 서버 세션 취소 + 두 저장소 정리 + isAuthenticated=false', () async {
    final store = _FakeTokenStore()..saved = 'tok';
    final refreshStore = _FakeRefreshTokenStore()..saved = 'refresh-tok';
    final refreshApi = _FakeTokenRefreshApi();
    final container = _container(
      _FakeAuthApi(token: 'tok'),
      store,
      refreshStore: refreshStore,
      refreshApi: refreshApi,
    );
    await container.read(authControllerProvider.notifier).logout();
    // MOB-12: 로컬만 지우면 서버 리프레시 세션이 살아남아 재발급이 가능했다 — 서버도 끊는다.
    expect(refreshApi.loggedOut, ['refresh-tok']);
    expect(store.cleared, isTrue);
    expect(refreshStore.cleared, isTrue);
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
  });

  test('logout은 마지막 대화 세션 참조도 지운다(MOB-11 — 다음 학생이 물려받지 않게)', () async {
    final dialogueStore = _FakeDialogueStore('prev-student-dialogue');
    final container = _container(
      _FakeAuthApi(token: 'tok'),
      _FakeTokenStore()..saved = 'tok',
      dialogueStore: dialogueStore,
    );
    await container.read(authControllerProvider.notifier).logout();
    expect(dialogueStore.dialogueId, isNull);
  });

  test(
      'logout → activeProblemProvider·코치 대화(dialogueId·메시지)도 함께 초기화된다'
      '(다음 학생에게 잔여 노출 방지·MOB-23)', () async {
    final container = _container(
      _FakeAuthApi(token: 'tok'),
      _FakeTokenStore()..saved = 'tok',
      coachApi: _FakeCoachApi(),
    );

    // 이전 학생이 풀던 문제가 남아 있는 상태를 재현한다. `overrideWith`로 초기값을 고정하면
    // `invalidate`가 그 고정값으로 되돌아가 버려 리셋을 검증할 수 없으므로(실제 프로덕션
    // 빌더는 `(ref) => null`), 실제 빌더를 그대로 두고 세팅만 직접 한다(problem_screen.onStart와
    // 동형 — `.notifier.state =`).
    container.read(activeProblemProvider.notifier).state = const Problem(
      problemId: 'p-prev-student',
      sourceType: '자체생성',
      subject: '공통',
      unitCodes: <String>['ALG'],
    );

    // 이전 학생의 코치 대화 잔여(dialogueId·메시지)를 재현한다.
    await container.read(chatControllerProvider.notifier).send('이전 학생 발화');
    expect(container.read(chatControllerProvider).dialogueId, isNotNull);
    expect(container.read(chatControllerProvider).messages, isNotEmpty);
    expect(container.read(activeProblemProvider), isNotNull);

    await container.read(authControllerProvider.notifier).logout();

    // 다음 학생이 같은 기기로 로그인해도 이전 학생의 문제·대화가 보이지 않아야 한다.
    expect(container.read(activeProblemProvider), isNull);
    final chatState = container.read(chatControllerProvider);
    expect(chatState.dialogueId, isNull);
    expect(chatState.messages, isEmpty);
  });

  test('dioProvider 배선(MOB-15): 갱신 불가 401이면 앱 전역 로그아웃으로 미인증이 된다', () async {
    final store = _FakeTokenStore()..saved = 'expired';
    final refreshStore = _FakeRefreshTokenStore(); // 리프레시 토큰 없음 → 갱신 불가(네트워크 미호출)
    final dialogueStore = _FakeDialogueStore('d-1');
    final container = _container(
      _FakeAuthApi(token: 'tok'),
      store,
      refreshStore: refreshStore,
      dialogueStore: dialogueStore,
    );
    await container.read(authControllerProvider.notifier).restore();
    expect(container.read(authControllerProvider).isAuthenticated, isTrue);

    final adapter = _UnauthorizedAdapter();
    final dio = container.read(dioProvider)..httpClientAdapter = adapter;
    await expectLater(dio.get<dynamic>('/v1/me/sessions'), throwsA(isA<DioException>()));

    // 부분 정리(토큰만 삭제)가 아니라 로그아웃 전체 정리 — 앱 상태까지 미인증으로 맞는다.
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
    expect(store.saved, isNull);
    expect(dialogueStore.dialogueId, isNull);
    expect(adapter.requests, 1, reason: '401→정리 경로가 요청을 재발사하면 안 된다(재귀·루프 없음)');
  });

  test('logout: 서버 호출 실패해도 로컬 정리·미인증은 반드시 수행된다', () async {
    // 오프라인 등으로 서버 취소가 실패해도 "로그아웃 눌렀는데 로그인 상태"가 되면 안 된다.
    final store = _FakeTokenStore()..saved = 'tok';
    final refreshStore = _FakeRefreshTokenStore()..saved = 'refresh-tok';
    final container = _container(
      _FakeAuthApi(token: 'tok'),
      store,
      refreshStore: refreshStore,
      refreshApi: _ThrowingTokenRefreshApi(),
    );
    await container.read(authControllerProvider.notifier).logout();
    expect(store.cleared, isTrue);
    expect(refreshStore.cleared, isTrue);
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
  });

  test('restore: 저장된 토큰 있으면 → isAuthenticated', () async {
    final store = _FakeTokenStore()..saved = 'tok';
    final container = _container(_FakeAuthApi(token: 'tok'), store);
    await container.read(authControllerProvider.notifier).restore();
    expect(container.read(authControllerProvider).isAuthenticated, isTrue);
  });

  test('restore: 토큰 없으면(null) → 미인증', () async {
    final container = _container(_FakeAuthApi(token: 'tok'), _FakeTokenStore());
    await container.read(authControllerProvider.notifier).restore();
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
  });

  test('restore: 빈 문자열 토큰 → 미인증', () async {
    final store = _FakeTokenStore()..saved = '';
    final container = _container(_FakeAuthApi(token: 'tok'), store);
    await container.read(authControllerProvider.notifier).restore();
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
  });

  test('restore: 저장소 오류 → 미인증·예외 없음(앱 안 죽음)', () async {
    final container = _container(_FakeAuthApi(token: 'tok'), _ThrowingTokenStore());
    await container.read(authControllerProvider.notifier).restore();
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
  });
}
