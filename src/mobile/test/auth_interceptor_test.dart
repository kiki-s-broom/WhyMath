// dio AuthInterceptor 단위테스트 — 저장 토큰의 Bearer 첨부 + 세션 최종 무효 콜백(MOB-15). OAuth-b.
//
// 플랫폼 채널 없이: fake TokenStore + capture HttpClientAdapter로 요청 헤더를 검증한다
// (SecureTokenStore 실 구현은 채널이라 통합/수동). 토큰 운반만 검증 — 발급·검증은 서버.
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/core/api_client.dart';
import 'package:korean_math_app/core/auth_interceptor.dart';
import 'package:korean_math_app/core/token_refresh_api.dart';
import 'package:korean_math_app/core/token_store.dart';

/// 인메모리 TokenStore — 플랫폼 채널 없이 인터셉터 로직을 검증한다.
class _FakeTokenStore implements TokenStore {
  _FakeTokenStore([this._token]);

  String? _token;

  @override
  Future<String?> readAccessToken() async => _token;

  @override
  Future<void> saveAccessToken(String token) async => _token = token;

  @override
  Future<void> clear() async => _token = null;
}

/// 요청을 가로채 RequestOptions를 캡처하는 가짜 어댑터(네트워크 없음).
class _CaptureAdapter implements HttpClientAdapter {
  RequestOptions? captured;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    captured = options;
    return ResponseBody.fromString(
      '{}',
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Dio _dioWith(TokenStore store, _CaptureAdapter adapter) {
  final dio = Dio()..httpClientAdapter = adapter;
  dio.interceptors.add(AuthInterceptor(store));
  return dio;
}

/// 인메모리 리프레시 토큰 저장소(MOB-15 콜백 테스트용).
class _FakeRefreshStore implements RefreshTokenStore {
  _FakeRefreshStore([this.token]);

  String? token;

  @override
  Future<String?> readRefreshToken() async => token;

  @override
  Future<void> saveRefreshToken(String value) async => token = value;

  @override
  Future<void> clearRefreshToken() async => token = null;
}

/// 회전 토큰을 돌려주거나(성공) 예외를 던지는(실패) 갱신 fake.
class _FakeRefreshApi extends TokenRefreshApi {
  _FakeRefreshApi({this.shouldThrow = false}) : super(Dio());

  final bool shouldThrow;
  int calls = 0;

  @override
  Future<AuthTokens> refresh(String refreshToken) async {
    calls++;
    if (shouldThrow) {
      throw DioException(requestOptions: RequestOptions(path: '/v1/auth/refresh'));
    }
    return const AuthTokens(accessToken: 'new-access', refreshToken: 'new-refresh');
  }
}

/// 상태코드 시퀀스대로 응답하는 어댑터 — 마지막 코드는 이후 요청에 반복된다.
class _SequenceAdapter implements HttpClientAdapter {
  _SequenceAdapter(this.codes);

  final List<int> codes;
  int requests = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final code = codes[requests < codes.length ? requests : codes.length - 1];
    requests++;
    return ResponseBody.fromString(
      '{}',
      code,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// 갱신 의존까지 주입한 인터셉터 Dio(재시도 Dio는 인터셉터 없이 같은 어댑터 공유).
Dio _refreshingDio(
  _SequenceAdapter adapter, {
  required TokenRefreshApi refreshApi,
  required RefreshTokenStore refreshStore,
  Future<void> Function()? onUnauthorized,
}) {
  final retryDio = Dio()..httpClientAdapter = adapter;
  return Dio()
    ..httpClientAdapter = adapter
    ..interceptors.add(
      AuthInterceptor(
        _FakeTokenStore('old-access'),
        refreshApi: refreshApi,
        refreshStore: refreshStore,
        retryDio: retryDio,
        onUnauthorized: onUnauthorized,
      ),
    );
}

void main() {
  test('토큰이 있으면 Authorization: Bearer 헤더를 첨부한다', () async {
    final adapter = _CaptureAdapter();
    final dio = _dioWith(_FakeTokenStore('abc123'), adapter);
    await dio.get<dynamic>('http://x/y');
    expect(adapter.captured!.headers['Authorization'], 'Bearer abc123');
  });

  test('토큰이 없으면 Authorization 헤더를 붙이지 않는다(미인증 → 서버 401)', () async {
    final adapter = _CaptureAdapter();
    final dio = _dioWith(_FakeTokenStore(), adapter);
    await dio.get<dynamic>('http://x/y');
    expect(adapter.captured!.headers.containsKey('Authorization'), isFalse);
  });

  test('tokenStoreProvider는 TokenStore(SecureTokenStore)를 제공한다', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final store = container.read(tokenStoreProvider);
    expect(store, isA<TokenStore>());
    expect(store, isA<SecureTokenStore>());
  });

  group('세션 최종 무효 콜백(MOB-15) — 갱신 흐름(MOB-12)과 공존', () {
    test('갱신 성공 → 재시도 성공이면 onUnauthorized를 호출하지 않는다(무중단)', () async {
      var calls = 0;
      final adapter = _SequenceAdapter([401, 200]);
      final refreshApi = _FakeRefreshApi();
      final dio = _refreshingDio(
        adapter,
        refreshApi: refreshApi,
        refreshStore: _FakeRefreshStore('old-refresh'),
        onUnauthorized: () async => calls++,
      );

      final response = await dio.get<dynamic>('http://x/y');

      expect(response.statusCode, 200);
      expect(refreshApi.calls, 1);
      expect(calls, 0, reason: '갱신으로 살아난 세션을 로그아웃시키면 MOB-12 무중단이 깨진다');
    });

    test('갱신 실패면 원 401을 올리고 onUnauthorized를 정확히 1회 호출한다', () async {
      var calls = 0;
      final dio = _refreshingDio(
        _SequenceAdapter([401]),
        refreshApi: _FakeRefreshApi(shouldThrow: true),
        refreshStore: _FakeRefreshStore('old-refresh'),
        onUnauthorized: () async => calls++,
      );

      await expectLater(
        dio.get<dynamic>('http://x/y'),
        throwsA(isA<DioException>().having((e) => e.response?.statusCode, 'status', 401)),
      );
      expect(calls, 1, reason: '최종 무효면 앱 상태도 미인증으로 맞춰야 한다(중복·누락 둘 다 결함)');
    });

    test('리프레시 토큰이 없어 갱신 불가여도 최종 무효로 1회 호출한다', () async {
      var calls = 0;
      final refreshApi = _FakeRefreshApi();
      final dio = _refreshingDio(
        _SequenceAdapter([401]),
        refreshApi: refreshApi,
        refreshStore: _FakeRefreshStore(),
        onUnauthorized: () async => calls++,
      );

      await expectLater(dio.get<dynamic>('http://x/y'), throwsA(isA<DioException>()));
      expect(refreshApi.calls, 0);
      expect(calls, 1);
    });

    test('동시 최종 401 여러 건이어도 정리 콜백은 1회로 묶인다', () async {
      var calls = 0;
      final dio = _refreshingDio(
        _SequenceAdapter([401]),
        refreshApi: _FakeRefreshApi(shouldThrow: true),
        refreshStore: _FakeRefreshStore('old-refresh'),
        onUnauthorized: () async {
          calls++;
          await Future<void>.delayed(const Duration(milliseconds: 10));
        },
      );

      await Future.wait([
        dio.get<dynamic>('http://x/a').then<Object?>((r) => r, onError: (Object e) => e),
        dio.get<dynamic>('http://x/b').then<Object?>((r) => r, onError: (Object e) => e),
      ]);
      expect(calls, 1);
    });

    test('재시도가 다시 401이면(갱신은 성공) 콜백을 부르지 않고 무한 루프 없이 끝난다', () async {
      var calls = 0;
      final adapter = _SequenceAdapter([401, 401]);
      final refreshApi = _FakeRefreshApi();
      final dio = _refreshingDio(
        adapter,
        refreshApi: refreshApi,
        refreshStore: _FakeRefreshStore('old-refresh'),
        onUnauthorized: () async => calls++,
      );

      await expectLater(dio.get<dynamic>('http://x/y'), throwsA(isA<DioException>()));
      expect(refreshApi.calls, 1);
      expect(adapter.requests, 2, reason: '원요청 1 + 재시도 1 — 그 이상이면 루프');
      expect(calls, 0, reason: '방금 갱신에 성공한 세션은 서버상 유효 — 로그아웃(서버 취소)은 과잉');
    });

    test('재시도 표식이 붙은 요청의 401은 갱신 의존이 있어도 정리 콜백을 부르지 않는다', () async {
      // 정상 흐름에서 재시도는 인터셉터 없는 Dio로 나가 이 경로에 오지 않는다 — 표식 달린 요청이
      // 어떤 이유로 인터셉터 달린 Dio를 다시 타더라도 재갱신·로그아웃 없이 원 에러만 올린다.
      var calls = 0;
      final refreshApi = _FakeRefreshApi();
      final dio = _refreshingDio(
        _SequenceAdapter([401]),
        refreshApi: refreshApi,
        refreshStore: _FakeRefreshStore('old-refresh'),
        onUnauthorized: () async => calls++,
      );

      await expectLater(
        dio.get<dynamic>(
          'http://x/y',
          options: Options(extra: <String, dynamic>{'whymath_auth_retried': true}),
        ),
        throwsA(isA<DioException>()),
      );
      expect(refreshApi.calls, 0);
      expect(calls, 0);
    });

    test('갱신 의존 미주입인데 401이면 onUnauthorized를 1회 호출한다', () async {
      var calls = 0;
      final dio = Dio()..httpClientAdapter = _SequenceAdapter([401]);
      dio.interceptors.add(
        AuthInterceptor(_FakeTokenStore('expired'), onUnauthorized: () async => calls++),
      );

      await expectLater(dio.get<dynamic>('http://x/y'), throwsA(isA<DioException>()));
      expect(calls, 1);
    });

    test('401이 아닌 에러(500)·403에서는 호출하지 않는다', () async {
      for (final code in [500, 403]) {
        var calls = 0;
        final refreshApi = _FakeRefreshApi();
        final dio = _refreshingDio(
          _SequenceAdapter([code]),
          refreshApi: refreshApi,
          refreshStore: _FakeRefreshStore('old-refresh'),
          onUnauthorized: () async => calls++,
        );

        await expectLater(dio.get<dynamic>('http://x/y'), throwsA(isA<DioException>()));
        expect(calls, 0, reason: '$code는 토큰 문제가 아니다 — 정상 세션을 부당하게 끊으면 안 된다');
        expect(refreshApi.calls, 0);
      }
    });

    test('콜백이 예외를 던져도 원 401은 그대로 전파된다(정리 실패가 에러를 삼키지 않음)', () async {
      final dio = Dio()..httpClientAdapter = _SequenceAdapter([401]);
      dio.interceptors.add(
        AuthInterceptor(_FakeTokenStore('expired'), onUnauthorized: () async => throw StateError('x')),
      );

      await expectLater(
        dio.get<dynamic>('http://x/y'),
        throwsA(isA<DioException>().having((e) => e.response?.statusCode, 'status', 401)),
      );
    });
  });

  test('dioProvider의 BaseOptions에 sendTimeout 30초가 설정돼 있다(MOB-15 — 업로드 무한대기 방지)', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    expect(dio.options.sendTimeout, const Duration(seconds: 30));
    // 갱신·재시도 전용 Dio도 같은 옵션을 공유한다(원요청과 다른 실패 양상 방지).
    expect(container.read(authFreeDioProvider).options.sendTimeout, const Duration(seconds: 30));
  });
}
