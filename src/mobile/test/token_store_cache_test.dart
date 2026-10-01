// 액세스 토큰 메모리 캐시 테스트 — **무효화가 핵심이다**(MOB-24 ②).
//
// 배경: `AuthInterceptor`가 모든 요청마다 보안 저장소(플랫폼 채널)에서 토큰을 읽었다. 그래서
// `SecureTokenStore` 안에 write-through 캐시를 뒀는데, 캐시는 *낡은 토큰을 내는 순간* 결함이 된다:
//  - 로그아웃했는데 옛 토큰이 계속 실려 나간다(정리 실패·다음 학생에게 이전 학생 토큰).
//  - 갱신(회전) 뒤에도 옛 액세스 토큰으로 401을 반복해 갱신을 또 태운다. 리프레시 토큰은 1회용이라
//    회전이 어긋나면 서버 재사용 탐지가 **전체 세션을 취소**한다(학생이 갑자기 로그아웃되는 사고).
// 그래서 이 파일은 "캐시가 빠르다"가 아니라 "캐시가 저장소와 어긋나지 않는다"를 고정한다.
//
// 구성:
//  1) 단위 — 계측 fake 저장소 위에서 실제 `SecureTokenStore`를 직접 검증(왕복 수·저장/삭제/실패·경합).
//  2) 실배선 — 실제 `dioProvider`(AuthInterceptor)·`AuthController`·`SecureTokenStore`를 가짜 서버
//     (토큰을 실제로 검사하고 리프레시를 1회용으로 회전하는 어댑터) 위에서 돌려 4개 경로(로그인·갱신
//     회전·로그아웃·401)마다 "다음 요청에 실린 토큰"과 "저장소 진실"이 같음을 단언한다.
// 플랫폼 채널은 쓰지 않는다 — `FlutterSecureStorage`를 상속한 인메모리 fake를 `secureTokenStoreProvider`
// override로 갈아 끼운다.
import 'dart:async';
import 'dart:collection';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/core/api_client.dart';
import 'package:korean_math_app/core/token_refresh_api.dart';
import 'package:korean_math_app/core/token_store.dart';
import 'package:korean_math_app/features/auth/application/auth_controller.dart';
import 'package:korean_math_app/features/auth/data/auth_api.dart';
import 'package:korean_math_app/features/chat/data/dialogue_store.dart';

// 저장소 키 — `SecureTokenStore`의 비공개 상수와 같은 값이어야 한다(달라지면 시드 읽기가 null이 돼
// 이 파일의 테스트가 요란하게 깨진다 — 조용히 통과하지 않는다).
const String _accessKey = 'access_token';
const String _refreshKey = 'refresh_token';

/// 플랫폼 채널 없이 flutter_secure_storage를 흉내 내는 인메모리 저장소 — 왕복 횟수를 세고, 실패·지연을
/// 주입할 수 있다.
///
/// [readGates]·[writeGates]·[deleteGates]는 *호출 순서대로* 하나씩 소비된다. 읽기는 값을 **호출 시점에
/// 잡아 둔 뒤** 게이트가 열릴 때까지 도착만 늦춘다 — "읽기가 시작된 뒤 변경이 끼어들고, 읽기 결과가
/// 뒤늦게 돌아오는" 경합을 결정적으로 재현한다. 쓰기·삭제는 게이트가 열린 *뒤에* 저장소에 반영한다
/// ("쓰기가 진행 중인 동안 저장소는 아직 옛 값"을 재현).
class _ScriptedSecureStorage extends FlutterSecureStorage {
  _ScriptedSecureStorage() : super();

  /// 저장소 진실(키 → 값) — 테스트가 직접 읽어 캐시와 대조한다.
  final Map<String, String> data = <String, String>{};

  int accessReads = 0;
  int accessWrites = 0;
  int accessDeletes = 0;
  int refreshReads = 0;

  final Queue<Completer<void>> readGates = Queue<Completer<void>>();
  final Queue<Completer<void>> writeGates = Queue<Completer<void>>();
  final Queue<Completer<void>> deleteGates = Queue<Completer<void>>();

  /// 다음 액세스 토큰 읽기·쓰기·삭제를 실패시킨다(한 번 쓰고 꺼진다).
  bool failNextAccessRead = false;
  bool failNextAccessWrite = false;
  bool failNextAccessDelete = false;

  /// true면 실패시키는 쓰기·삭제가 저장소에는 **반영된 채** 예외로 끝난다(부분 성공) — 캐시가 "실패했으니
  /// 저장소는 그대로"라고 믿으면 낡은 값이 남는다.
  bool failAfterApplying = false;

  /// true면 쓰기·삭제를 호출 시점에 **먼저 반영**하고, 게이트는 *완료 통지*만 늦춘다 — 저장소에 닿은
  /// 순서와 완료가 통지되는 순서가 다른 경우(먼저 닿은 쪽이 나중에 완료)를 재현한다(이 모드에선
  /// [failNextAccessWrite]·[failNextAccessDelete]를 쓰지 않는다).
  bool applyWritesImmediately = false;

  void _apply(String key, String? value) {
    if (value == null) {
      data.remove(key);
    } else {
      data[key] = value;
    }
  }

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (key != _accessKey) {
      refreshReads++;
      return data[key];
    }
    accessReads++;
    if (failNextAccessRead) {
      failNextAccessRead = false;
      throw PlatformException(code: 'read_failed');
    }
    final String? snapshot = data[key]; // 읽은 시점의 진실을 잡아 둔다.
    if (readGates.isNotEmpty) {
      await readGates.removeFirst().future; // 결과 도착만 늦춘다.
    }
    return snapshot;
  }

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (key != _accessKey) {
      _apply(key, value);
      return;
    }
    accessWrites++;
    if (applyWritesImmediately) {
      _apply(key, value); // 저장소엔 지금 닿는다 — 완료 통지만 게이트로 늦춘다.
    }
    if (writeGates.isNotEmpty) {
      await writeGates.removeFirst().future;
    }
    if (applyWritesImmediately) {
      return;
    }
    if (failNextAccessWrite) {
      failNextAccessWrite = false;
      if (failAfterApplying) {
        _apply(key, value);
      }
      throw PlatformException(code: 'write_failed');
    }
    _apply(key, value);
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (key != _accessKey) {
      data.remove(key);
      return;
    }
    accessDeletes++;
    if (applyWritesImmediately) {
      data.remove(key); // 저장소엔 지금 닿는다 — 완료 통지만 게이트로 늦춘다.
    }
    if (deleteGates.isNotEmpty) {
      await deleteGates.removeFirst().future;
    }
    if (applyWritesImmediately) {
      return;
    }
    if (failNextAccessDelete) {
      failNextAccessDelete = false;
      if (failAfterApplying) {
        data.remove(key);
      }
      throw PlatformException(code: 'delete_failed');
    }
    data.remove(key);
  }
}

/// `read`가 **동기 예외**를 던지는 저장소 — 실제 `FlutterSecureStorage.read`는 `async`가 아니라서
/// 미지원 플랫폼에서 `_selectOptions`의 `UnsupportedError`가 Future 밖으로 곧장 나온다.
class _SyncThrowingSecureStorage extends FlutterSecureStorage {
  _SyncThrowingSecureStorage() : super();

  int reads = 0;

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) {
    reads++;
    throw UnsupportedError('unsupported_platform(테스트)');
  }
}

// ── 실배선용 가짜 서버 ─────────────────────────────────────────────────────

/// 서버 상태 — 어떤 액세스 토큰이 유효한지, 어떤 리프레시 토큰이 *유일하게* 유효한지(1회용 회전).
class _FakeServer {
  /// 지금 서버가 인정하는 액세스 토큰(null이면 인정할 토큰이 없다 = 만료).
  String? validAccess;

  /// 서버가 인정하는 유일한 리프레시 토큰 — 회전하면 옛 것은 죽는다.
  String? currentRefresh;

  /// 옛 리프레시 토큰이 재제출되면 켜진다 — 재사용 탐지로 **전체 세션이 취소**된 상태.
  bool sessionRevoked = false;

  int _serial = 0;

  /// 서버가 받은 Authorization 헤더(요청 시도마다 1건 — 재시도도 별도로 센다). 헤더가 없으면 null.
  final List<String?> seenAuth = <String?>[];

  /// 갱신 호출에 실려 온 리프레시 토큰들.
  final List<String> refreshInputs = <String>[];

  /// 새 토큰 쌍을 발급한다(A1/R1, A2/R2 …) — 이전 쌍은 무효가 된다.
  AuthTokens issue() {
    _serial++;
    validAccess = 'A$_serial';
    currentRefresh = 'R$_serial';
    return AuthTokens(accessToken: 'A$_serial', refreshToken: 'R$_serial');
  }

  /// 액세스 토큰만 만료시킨다(리프레시 세션은 살아 있다).
  void expireAccess() => validAccess = null;
}

/// `/v1/public/*`은 헤더와 무관하게 200, 그 밖은 서버가 인정하는 Bearer일 때만 200(아니면 401).
class _ServerAdapter implements HttpClientAdapter {
  _ServerAdapter(this.server);

  final _FakeServer server;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final String? auth = options.headers['Authorization'] as String?;
    server.seenAuth.add(auth);
    final bool isPublic = options.path.startsWith('/v1/public');
    final String? valid = server.validAccess;
    final bool ok = isPublic || (auth != null && valid != null && auth == 'Bearer $valid');
    return ResponseBody.fromString(
      '{}',
      ok ? 200 : 401,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// 리프레시·로그아웃 fake — 서버의 1회용 회전 규칙을 그대로 흉내 낸다.
///
/// [gate]를 주면 갱신이 그 Completer가 완료될 때까지 멈춘다(두 요청의 갱신 구간을 확실히 겹치게 한다).
class _FakeTokenRefreshApi extends TokenRefreshApi {
  _FakeTokenRefreshApi(this.server, {this.gate}) : super(Dio());

  final _FakeServer server;
  final Completer<void>? gate;
  int calls = 0;
  final List<String> loggedOut = <String>[];

  @override
  Future<AuthTokens> refresh(String refreshToken) async {
    calls++;
    server.refreshInputs.add(refreshToken);
    if (gate != null) {
      await gate!.future;
    }
    if (server.sessionRevoked || refreshToken != server.currentRefresh) {
      // 옛 리프레시 토큰 재제출 = 재사용 탐지 → 전체 세션 취소(서버 규칙 미러).
      server.sessionRevoked = true;
      throw DioException(
        requestOptions: RequestOptions(path: '/v1/auth/refresh'),
        response: Response<dynamic>(
          requestOptions: RequestOptions(path: '/v1/auth/refresh'),
          statusCode: 401,
        ),
      );
    }
    return server.issue();
  }

  @override
  Future<void> logout(String refreshToken) async => loggedOut.add(refreshToken);
}

/// 로그인 fake — 서버가 새 토큰 쌍을 발급한다.
class _FakeAuthApi extends AuthApi {
  _FakeAuthApi(this.server) : super(Dio());

  final _FakeServer server;

  @override
  Future<AuthTokens> login({
    required String provider,
    required String code,
    required String redirectUri,
  }) async => server.issue();
}

class _FakeDialogueStore implements DialogueStore {
  String? id;

  @override
  Future<String?> readDialogueId() async => id;

  @override
  Future<void> saveDialogueId(String dialogueId) async => id = dialogueId;

  @override
  Future<void> clearDialogueId() async => id = null;
}

/// 실배선 한 벌 — 실제 dioProvider·AuthInterceptor·AuthController·SecureTokenStore + fake 저장소·서버.
class _Stack {
  _Stack({
    required this.storage,
    required this.server,
    required this.refreshApi,
    required this.container,
    required this.dio,
  });

  final _ScriptedSecureStorage storage;
  final _FakeServer server;
  final _FakeTokenRefreshApi refreshApi;
  final ProviderContainer container;
  final Dio dio;

  AuthController get auth => container.read(authControllerProvider.notifier);
  bool get isAuthenticated => container.read(authControllerProvider).isAuthenticated;

  /// 이 요청에 서버가 받은 첫 시도의 Authorization(직전 시도 기준).
  String? get lastAuth => server.seenAuth.last;
}

_Stack _buildStack({Completer<void>? refreshGate}) {
  final storage = _ScriptedSecureStorage();
  final server = _FakeServer();
  final adapter = _ServerAdapter(server);
  final refreshApi = _FakeTokenRefreshApi(server, gate: refreshGate);
  // 재시도용 Dio — 인증 인터셉터가 없는 인스턴스가 같은 서버 어댑터에 물린다(dioProvider 조립과 동형).
  final retryDio = Dio(BaseOptions(baseUrl: 'http://x'))..httpClientAdapter = adapter;
  final container = ProviderContainer(
    overrides: [
      secureTokenStoreProvider.overrideWithValue(SecureTokenStore(storage)),
      authApiProvider.overrideWithValue(_FakeAuthApi(server)),
      tokenRefreshApiProvider.overrideWithValue(refreshApi),
      authFreeDioProvider.overrideWithValue(retryDio),
      dialogueStoreProvider.overrideWithValue(_FakeDialogueStore()),
    ],
  );
  addTearDown(container.dispose);
  // AuthController는 autoDispose — await 중 폐기되지 않게 리스너로 붙잡는다(e2e 테스트와 동일 사유).
  container.listen(authControllerProvider, (_, __) {}, fireImmediately: true);
  final dio = container.read(dioProvider)..httpClientAdapter = adapter;
  return _Stack(
    storage: storage,
    server: server,
    refreshApi: refreshApi,
    container: container,
    dio: dio,
  );
}

/// GET 하나를 보내고 최종 상태코드를 돌려준다(401 등 실패는 예외 대신 코드로).
Future<int?> _status(Dio dio, String path) async {
  try {
    final Response<dynamic> response = await dio.get<dynamic>(path);
    return response.statusCode;
  } on DioException catch (e) {
    return e.response?.statusCode;
  }
}

void main() {
  group('SecureTokenStore 캐시 — 저장소 왕복 수 (MOB-24)', () {
    test('연속 읽기는 저장소를 1번만 읽는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);

      for (var i = 0; i < 5; i++) {
        expect(await store.readAccessToken(), 'A');
      }

      expect(storage.accessReads, 1, reason: '캐시가 없으면 요청 수만큼(5번) 플랫폼 채널 왕복이 붙는다');
    });

    test('캐시가 빈 채 동시에 들어온 읽기는 저장소 왕복 1번으로 묶인다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final gate = Completer<void>();
      storage.readGates.add(gate);
      final store = SecureTokenStore(storage);

      final List<Future<String?>> reads = List<Future<String?>>.generate(
        5,
        (_) => store.readAccessToken(),
      );
      // 첫 요청 다발이 한꺼번에 나가는 콜드 스타트 — 저장소 읽기는 하나만 시작돼 있어야 한다.
      expect(storage.accessReads, 1);
      gate.complete();

      expect(await Future.wait(reads), everyElement('A'));
      expect(storage.accessReads, 1);
      // 이후는 캐시.
      expect(await store.readAccessToken(), 'A');
      expect(storage.accessReads, 1);
    });

    test('토큰이 없다는 사실(null)도 캐시한다 — 미인증 요청마다 저장소를 읽지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage();
      final store = SecureTokenStore(storage);

      expect(await store.readAccessToken(), isNull);
      expect(await store.readAccessToken(), isNull);
      expect(await store.readAccessToken(), isNull);

      expect(storage.accessReads, 1);
    });

    test('읽기 실패는 캐시하지 않는다 — 다음 읽기가 다시 시도한다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()
        ..data[_accessKey] = 'A'
        ..failNextAccessRead = true;
      final store = SecureTokenStore(storage);

      await expectLater(store.readAccessToken(), throwsA(isA<PlatformException>()));
      // 실패를 "토큰 없음"으로 캐시하면 여기서 null이 나오고 앱은 멀쩡한 토큰을 두고 미인증으로 동작한다.
      expect(await store.readAccessToken(), 'A');
      expect(storage.accessReads, 2);
      // 성공한 값부터는 캐시된다.
      expect(await store.readAccessToken(), 'A');
      expect(storage.accessReads, 2);
    });

    test('저장소가 동기 예외를 던져도 Future 오류로 수렴하고 진행 표식이 남지 않는다 (MOB-24)', () async {
      final storage = _SyncThrowingSecureStorage();
      final store = SecureTokenStore(storage);

      // 동기 예외가 Future 밖으로 새면 이 expect 호출 자체가 던져 테스트가 깨진다.
      await expectLater(store.readAccessToken(), throwsA(isA<UnsupportedError>()));
      // 실패한 읽기가 "진행 중" 표식으로 남아 있으면 두 번째 호출은 저장소를 부르지도 않고 같은 실패를 재방송한다.
      await expectLater(store.readAccessToken(), throwsA(isA<UnsupportedError>()));
      expect(storage.reads, 2);
    });

    test('리프레시 토큰은 캐시하지 않는다 — 매번 저장소 진실을 읽는다 (MOB-24)', () async {
      // 1회용 리프레시 토큰이 낡은 값으로 나가면 곧바로 서버 재사용 탐지(전체 세션 취소)다.
      final storage = _ScriptedSecureStorage()..data[_refreshKey] = 'R1';
      final store = SecureTokenStore(storage);

      expect(await store.readRefreshToken(), 'R1');
      storage.data[_refreshKey] = 'R9'; // 저장소 진실이 바뀌면
      expect(await store.readRefreshToken(), 'R9'); // 곧바로 보인다.
      expect(storage.refreshReads, 2);
    });
  });

  group('SecureTokenStore 캐시 — 무효화 (MOB-24)', () {
    test('저장(write-through) 뒤 읽기는 새 토큰을 내고 저장소를 다시 읽지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'OLD';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'OLD'); // 캐시에 OLD가 올라간다.

      await store.saveAccessToken('NEW');

      expect(await store.readAccessToken(), 'NEW', reason: '갱신 회전 뒤에도 옛 토큰이 나가면 401→재갱신이 반복된다');
      expect(storage.data[_accessKey], 'NEW');
      expect(storage.accessReads, 1, reason: 'write-through라 저장 뒤에도 저장소를 다시 읽을 필요가 없다');
    });

    test('저장 실패는 캐시를 새 값으로 채우지 않는다 — 다음 읽기가 저장소 진실을 읽는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'A');

      storage.failNextAccessWrite = true; // 쓰기가 반영 없이 실패.
      await expectLater(store.saveAccessToken('B'), throwsA(isA<PlatformException>()));

      expect(await store.readAccessToken(), 'A', reason: '저장소에는 A가 그대로다 — 캐시가 B를 내면 안 된다');
      expect(storage.accessReads, 2, reason: '캐시를 믿지 않고 저장소를 다시 읽었어야 한다');
    });

    test('저장이 반영된 채 예외로 끝나도(부분 성공) 옛 캐시를 남기지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'A');

      storage
        ..failNextAccessWrite = true
        ..failAfterApplying = true; // 저장소엔 B가 들어갔는데 예외로 끝난다.
      await expectLater(store.saveAccessToken('B'), throwsA(isA<PlatformException>()));

      // "실패했으니 그대로 A"라고 믿는 캐시는 여기서 A를 내 저장소 진실(B)과 어긋난다.
      expect(await store.readAccessToken(), 'B');
    });

    test('삭제(clear) 뒤 읽기는 저장소 진실(없음)을 읽는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'A');

      await store.clear();

      expect(await store.readAccessToken(), isNull, reason: '로그아웃 뒤에도 옛 토큰이 나가면 정리가 실패한 것이다');
      expect(storage.accessReads, 2);
    });

    test('삭제가 실패해도 캐시는 비운다 — 저장소 진실을 다시 읽는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'A');

      storage.failNextAccessDelete = true; // 삭제가 반영 없이 실패 — 저장소에는 A가 그대로.
      await expectLater(store.clear(), throwsA(isA<PlatformException>()));

      expect(await store.readAccessToken(), 'A');
      expect(storage.accessReads, 2, reason: 'clear는 성공·실패와 무관하게 캐시를 비워 진실을 다시 읽게 해야 한다');
    });

    test('삭제가 반영된 채 예외로 끝나도(부분 성공) 옛 토큰을 되살리지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final store = SecureTokenStore(storage);
      expect(await store.readAccessToken(), 'A');

      storage
        ..failNextAccessDelete = true
        ..failAfterApplying = true; // 실제로는 지워졌는데 예외로 끝난다.
      await expectLater(store.clear(), throwsA(isA<PlatformException>()));

      // 실패했으니 캐시를 그대로 둔다는 구현은 여기서 A를 내 — 이미 지운 토큰이 유령으로 남는다.
      expect(await store.readAccessToken(), isNull);
    });
  });

  group('SecureTokenStore 캐시 — 경합 (MOB-24)', () {
    test('읽는 도중 로그아웃(clear)이 끼어들면 그 읽기의 옛 토큰이 캐시에 남지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final gate = Completer<void>();
      storage.readGates.add(gate);
      final store = SecureTokenStore(storage);

      final Future<String?> inFlight = store.readAccessToken(); // 저장소에서 A를 잡고 도착을 기다린다.
      await store.clear(); // 그 사이 로그아웃이 끝난다.
      // 삭제가 끝난 뒤의 새 읽기 — 아직 게이트에 걸려 있는 옛 읽기(A)에 합류하면 옛 토큰을 받는다.
      final Future<String?> after = store.readAccessToken();
      gate.complete();

      // 옛 읽기는 삭제 *전에* 시작했으므로 옛 값을 받는 것까지는 허용된다.
      expect(await inFlight, 'A');
      expect(await after, isNull, reason: '로그아웃이 끝난 뒤 시작한 읽기가 옛 토큰을 받으면 정리가 실패한 것이다');
      // 그리고 그 옛 값이 캐시에 남으면 로그아웃한 기기가 옛 토큰을 계속 실어 보낸다.
      expect(await store.readAccessToken(), isNull);
      expect(storage.accessReads, 2);
    });

    test('읽는 도중 로그인(save)이 끼어들면 그 읽기의 옛 값이 새 토큰을 덮지 못한다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage(); // 아직 토큰 없음.
      final gate = Completer<void>();
      storage.readGates.add(gate);
      final store = SecureTokenStore(storage);

      final Future<String?> inFlight = store.readAccessToken(); // 저장소에서 "없음"을 잡고 도착을 기다린다.
      await store.saveAccessToken('NEW'); // 그 사이 로그인이 끝난다.
      gate.complete();

      expect(await inFlight, isNull);
      // 뒤늦게 도착한 "없음"이 캐시를 덮으면 로그인한 학생이 계속 미인증으로 요청한다.
      expect(await store.readAccessToken(), 'NEW');
      expect(storage.accessReads, 1, reason: '캐시(write-through)가 새 토큰을 들고 있어 저장소를 다시 읽을 필요가 없다');
    });

    test('쓰기 도중 시작한 읽기는 캐시를 채우지 못한다 — 쓰기가 반영된 채 예외로 끝나도 낡은 값이 안 남는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final writeGate = Completer<void>();
      storage.writeGates.add(writeGate);
      storage
        ..failNextAccessWrite = true
        ..failAfterApplying = true;
      final store = SecureTokenStore(storage);

      final Future<void> saving = store.saveAccessToken('B'); // 쓰기 진행 중(아직 미반영).
      final Future<void> savingOutcome = expectLater(saving, throwsA(isA<PlatformException>()));
      // 쓰기 도중에 시작·완료된 읽기 — 저장소는 아직 A다.
      expect(await store.readAccessToken(), 'A');
      writeGate.complete(); // 이제 B가 반영되고 예외로 끝난다.
      await savingOutcome;

      // 쓰기 도중 읽은 A가 캐시에 올라가 있었다면 여기서 A가 나와 저장소 진실(B)과 어긋난다.
      expect(await store.readAccessToken(), 'B');
    });

    test('겹친 저장 — 저장소에 먼저 닿은 쪽이 나중에 완료 통지돼도 캐시를 확정하지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..applyWritesImmediately = true;
      final firstGate = Completer<void>();
      final secondGate = Completer<void>();
      storage.writeGates
        ..add(firstGate)
        ..add(secondGate);
      final store = SecureTokenStore(storage);

      final Future<void> first = store.saveAccessToken('B'); // 저장소에 먼저 닿는다(B).
      final Future<void> second = store.saveAccessToken('C'); // 그다음 닿는다 → 저장소 최종값은 C.
      secondGate.complete(); // 완료 통지는 뒤늦게 닿은 쪽이 먼저,
      await second;
      firstGate.complete(); // 먼저 닿은 쪽이 나중에 온다.
      await first;

      expect(storage.data[_accessKey], 'C');
      // 마지막에 완료 통지된 저장(B)이 "내가 마지막"이라 믿고 B를 캐시했다면 여기서 B가 나와 저장소(C)와 어긋난다.
      expect(await store.readAccessToken(), 'C');
    });

    test('쓰기 도중 시작한 읽기가 아직 안 끝났어도, 쓰기가 끝난 뒤의 새 읽기는 그 읽기에 합류하지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final writeGate = Completer<void>();
      final readGate = Completer<void>();
      storage.writeGates.add(writeGate);
      storage.readGates.add(readGate); // 첫 읽기(쓰기 도중에 시작하는 것)만 도착을 늦춘다.
      storage
        ..failNextAccessWrite = true
        ..failAfterApplying = true; // 저장소엔 B가 들어가고 예외로 끝난다.
      final store = SecureTokenStore(storage);

      final Future<void> saving = store.saveAccessToken('B');
      final Future<void> savingOutcome = expectLater(saving, throwsA(isA<PlatformException>()));
      // 쓰기 도중에 시작한 읽기 — 저장소 스냅샷은 아직 A이고 도착은 게이트로 늦춘다.
      final Future<String?> during = store.readAccessToken();
      writeGate.complete(); // 쓰기가 B를 반영하고 예외로 끝난다.
      await savingOutcome;

      // 쓰기가 끝난 뒤의 새 읽기 — 위 지연된 읽기(A)에 합류하면 저장소 진실(B)과 어긋난 A를 받는다.
      final Future<String?> after = store.readAccessToken();
      readGate.complete();
      expect(await after, 'B');
      expect(await during, 'A'); // 지연됐던 읽기 자신은 쓰기 전 값을 받는다(허용).
      // 늦게 도착한 그 읽기가 캐시를 오염시키지도 않는다.
      expect(await store.readAccessToken(), 'B');
    });

    test('삭제가 저장소에 닿은 뒤 시작한 읽기는 삭제 전에 시작된 읽기(옛 스냅샷)에 합류하지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()
        ..data[_accessKey] = 'A'
        ..applyWritesImmediately = true;
      final readGate = Completer<void>();
      final deleteGate = Completer<void>();
      storage.readGates.add(readGate); // 첫 읽기(삭제 전에 시작하는 것)만 도착을 늦춘다.
      storage.deleteGates.add(deleteGate);
      final store = SecureTokenStore(storage);

      final Future<String?> before = store.readAccessToken(); // 삭제 전에 시작 — 스냅샷 A, 도착 지연.
      final Future<void> clearing = store.clear(); // 삭제는 저장소에 닿았고 완료 통지만 지연된다.
      final Future<String?> during = store.readAccessToken(); // 삭제가 닿은 뒤 시작한 읽기.
      readGate.complete(); // 지연됐던 옛 읽기가 도착한다.

      // 옛 스냅샷(A)에 합류하면 로그아웃이 진행되는 동안에도 옛 토큰을 받는다.
      expect(await during, isNull, reason: '삭제가 닿은 뒤 시작한 읽기는 저장소를 새로 읽어야 한다');
      deleteGate.complete();
      await clearing;
      expect(await before, 'A'); // 삭제 전에 시작한 읽기 자신은 옛 값을 받는다(허용).
      expect(await store.readAccessToken(), isNull);
    });

    test('변경 도중 시작해 늦게 끝난 읽기가, 변경이 끝난 뒤 시작한 읽기의 진행 표식을 지우지 않는다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage()..data[_accessKey] = 'A';
      final deleteGate = Completer<void>();
      final duringGate = Completer<void>();
      final afterGate = Completer<void>();
      storage.deleteGates.add(deleteGate);
      storage.readGates
        ..add(duringGate) // 변경 도중 시작하는 읽기
        ..add(afterGate); // 변경이 끝난 뒤 시작하는 읽기
      final store = SecureTokenStore(storage);

      final Future<void> clearing = store.clear(); // 삭제 진행 중.
      final Future<String?> during = store.readAccessToken(); // 변경 도중 시작(도착 지연).
      deleteGate.complete();
      await clearing; // 삭제 끝.
      final Future<String?> after = store.readAccessToken(); // 변경이 끝난 뒤 시작(도착 지연).
      duringGate.complete(); // 늦게 끝난 '변경 도중' 읽기가 도착한다.
      // 이 읽기는 삭제가 저장소에 닿기 전에 스냅샷을 잡았으므로 옛 값(A)을 받는 것이 정당하다 — 캐시엔 오르지 않는다.
      expect(await during, 'A');
      // 위 읽기가 after의 진행 표식을 지웠다면, 지금 들어온 읽기는 합류하지 않고 저장소를 또 읽는다.
      final Future<String?> joiner = store.readAccessToken();
      expect(storage.accessReads, 2, reason: 'during·after 두 번만 읽어야 한다 — 표식이 지워지면 3번이 된다');
      afterGate.complete();
      expect(await after, isNull);
      expect(await joiner, isNull);
    });

    test('겹친 저장 두 건은 캐시를 확정하지 않는다 — 마지막에 저장소에 닿은 값이 정답이다 (MOB-24)', () async {
      final storage = _ScriptedSecureStorage();
      final firstGate = Completer<void>();
      final secondGate = Completer<void>();
      storage.writeGates
        ..add(firstGate)
        ..add(secondGate);
      final store = SecureTokenStore(storage);

      final Future<void> first = store.saveAccessToken('B'); // 먼저 시작했지만
      final Future<void> second = store.saveAccessToken('C'); // 나중 것이
      secondGate.complete(); // 저장소에 먼저 닿고(C)
      await second;
      firstGate.complete(); // 먼저 시작한 것이 나중에 닿는다(B) → 저장소 최종값은 B.
      await first;

      expect(storage.data[_accessKey], 'B');
      // 나중에 시작한 저장이 "내가 마지막"이라고 믿고 C를 캐시했다면 여기서 C가 나와 어긋난다.
      expect(await store.readAccessToken(), 'B');
    });
  });

  group('토큰 저장소 인스턴스 (MOB-24)', () {
    test('액세스·리프레시 계약 provider는 같은 SecureTokenStore 인스턴스를 공유한다 (MOB-24)', () {
      // 캐시가 인스턴스 안에 있으므로, 인스턴스가 둘이면 한쪽의 저장·삭제를 다른 쪽 캐시가 못 본다.
      final container = ProviderContainer();
      addTearDown(container.dispose);

      final TokenStore access = container.read(tokenStoreProvider);
      final RefreshTokenStore refresh = container.read(refreshTokenStoreProvider);
      final SecureTokenStore single = container.read(secureTokenStoreProvider);

      expect(identical(access, single), isTrue);
      expect(identical(refresh, single), isTrue);
    });
  });

  group('실배선 — 로그인·갱신 회전·로그아웃·401마다 캐시가 저장소와 같다 (MOB-24)', () {
    test('연속 요청 5건은 매번 같은 토큰을 싣고 저장소는 1번만 읽는다 (MOB-24)', () async {
      final s = _buildStack();
      s.storage.data[_accessKey] = 'A0';
      s.server.validAccess = 'A0';

      for (var i = 0; i < 5; i++) {
        expect(await _status(s.dio, '/v1/me/x$i'), 200);
      }

      expect(s.server.seenAuth, everyElement('Bearer A0'));
      expect(s.storage.accessReads, 1, reason: '요청 5건에 플랫폼 채널 왕복이 5번 붙던 낭비가 1번으로 줄어야 한다');
    });

    test('동시에 나간 요청 5건도 저장소 왕복 1번으로 묶인다 (MOB-24)', () async {
      final s = _buildStack();
      s.storage.data[_accessKey] = 'A0';
      s.server.validAccess = 'A0';

      final List<int?> statuses = await Future.wait(
        List<Future<int?>>.generate(5, (i) => _status(s.dio, '/v1/me/c$i')),
      );

      expect(statuses, everyElement(200));
      expect(s.storage.accessReads, 1);
    });

    test('앱 시작 복원(restore)이 읽은 토큰을 첫 요청이 다시 읽지 않는다 (MOB-24)', () async {
      final s = _buildStack();
      s.storage.data[_accessKey] = 'A0';
      s.server.validAccess = 'A0';

      await s.auth.restore(); // 시작 시 토큰 존재 확인(저장소 1번)
      expect(s.isAuthenticated, isTrue);
      expect(await _status(s.dio, '/v1/me/first'), 200); // 첫 요청은 그 캐시를 쓴다.

      expect(s.storage.accessReads, 1);
      expect(s.lastAuth, 'Bearer A0');
    });

    test('로그인 ⓑ: 미인증 때 캐시된 "토큰 없음"이 로그인 뒤 첫 요청에 남지 않는다 (MOB-24)', () async {
      final s = _buildStack();
      // 로그인 전 — 미인증 요청이 캐시에 "토큰 없음"을 올린다(공개 경로라 401·로그아웃 정리를 부르지 않는다).
      expect(await _status(s.dio, '/v1/public/ping'), 200);
      expect(s.lastAuth, isNull);

      await s.auth.completeLogin(provider: 'kakao', code: 'c', redirectUri: 'r');
      expect(s.isAuthenticated, isTrue);

      // "없음"이 캐시에 남았다면 여기서 헤더 없이 나가 401이다.
      expect(await _status(s.dio, '/v1/me/x'), 200);
      expect(s.lastAuth, 'Bearer A1');
      expect(s.storage.data[_accessKey], 'A1');
    });

    test('로그인 ⓑ: 이미 토큰이 캐시된 기기에서 다시 로그인하면 새 토큰이 실린다 (MOB-24)', () async {
      final s = _buildStack();
      s.storage.data[_accessKey] = 'A0';
      s.server.validAccess = 'A0';
      expect(await _status(s.dio, '/v1/me/x'), 200); // 캐시에 A0.

      await s.auth.completeLogin(provider: 'kakao', code: 'c', redirectUri: 'r'); // 서버가 A1 발급.

      expect(await _status(s.dio, '/v1/me/y'), 200);
      expect(s.lastAuth, 'Bearer A1', reason: '캐시가 옛 A0를 내면 다른 계정 토큰으로 요청이 나간다');
    });

    test('갱신 회전 ⓒ: 회전 뒤 요청은 새 토큰을 싣고 갱신을 또 태우지 않는다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue(); // 서버: A1/R1
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      expect(await _status(s.dio, '/v1/me/x'), 200); // 캐시에 A1.

      s.server.expireAccess(); // 액세스 토큰 만료(리프레시는 유효).
      expect(await _status(s.dio, '/v1/me/x'), 200); // 401 → 갱신(R1→R2) → A2로 재시도 성공.
      expect(s.refreshApi.calls, 1);
      expect(s.storage.data[_accessKey], 'A2');
      expect(s.storage.data[_refreshKey], 'R2');

      final int before = s.server.seenAuth.length;
      expect(await _status(s.dio, '/v1/me/y'), 200);

      // 캐시가 옛 A1을 냈다면 이 요청은 A1로 나가 401 → 갱신이 한 번 더 돌고(회전 어긋남 위험) 시도가 2건이 된다.
      expect(s.server.seenAuth.length - before, 1, reason: '회전 뒤 첫 요청이 401 없이 1시도로 끝나야 한다');
      expect(s.lastAuth, 'Bearer A2');
      expect(s.refreshApi.calls, 1);
      expect(s.server.sessionRevoked, isFalse);
      // 캐시가 내는 값 == 저장소 진실.
      expect(await s.container.read(tokenStoreProvider).readAccessToken(), s.storage.data[_accessKey]);
    });

    test('갱신 회전 ⓒ: 연속 두 번 회전해도 재사용 탐지에 걸리지 않고 매번 최신 토큰이 실린다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue(); // A1/R1
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';

      s.server.expireAccess();
      expect(await _status(s.dio, '/v1/me/a'), 200); // A2/R2
      s.server.expireAccess();
      expect(await _status(s.dio, '/v1/me/b'), 200); // A3/R3
      expect(await _status(s.dio, '/v1/me/c'), 200);

      expect(s.server.refreshInputs, <String>['R1', 'R2'], reason: '두 번째 갱신은 회전된 R2로 나가야 한다(옛 R1 재제출 = 세션 취소)');
      expect(s.server.sessionRevoked, isFalse);
      expect(s.lastAuth, 'Bearer A3');
      expect(s.storage.data[_accessKey], 'A3');
    });

    test('갱신 회전 ⓒ: 동시 401 두 건은 갱신 1번을 공유하고 캐시는 새 토큰이다 (MOB-24)', () async {
      final gate = Completer<void>(); // 갱신을 붙잡아 두 요청의 갱신 구간을 확실히 겹치게 한다.
      final s = _buildStack(refreshGate: gate);
      s.server.issue();
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      expect(await _status(s.dio, '/v1/me/warm'), 200); // 캐시에 A1.
      s.server.expireAccess();

      final Future<List<int?>> both = Future.wait(<Future<int?>>[
        _status(s.dio, '/v1/me/a'),
        _status(s.dio, '/v1/me/b'),
      ]);
      // 갱신 구간 진입까지 기다린다(요청→401→인터셉터 체인은 여러 마이크로태스크가 걸린다).
      for (var i = 0; i < 200 && s.refreshApi.calls == 0; i++) {
        await Future<void>.delayed(Duration.zero);
      }
      for (var i = 0; i < 50; i++) {
        await Future<void>.delayed(Duration.zero); // 두 번째 401도 갱신 대기에 도달할 여유.
      }
      expect(s.refreshApi.calls, 1, reason: '겹친 갱신은 하나의 비행으로 묶여야 한다');
      gate.complete();

      expect(await both, everyElement(200));
      expect(s.refreshApi.calls, 1);
      expect(s.server.sessionRevoked, isFalse);
      expect(await _status(s.dio, '/v1/me/after'), 200);
      expect(s.lastAuth, 'Bearer A2');
    });

    test('갱신 회전 ⓒ: 회전 저장 도중 보안 저장소 쓰기가 실패하면 낡은 토큰이 남지 않고 로그아웃으로 수렴한다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue();
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      await s.auth.restore(); // 인증 상태 + 캐시 A1.
      expect(s.isAuthenticated, isTrue);
      s.server.expireAccess();
      s.storage.failNextAccessWrite = true; // 갱신은 성공하는데 새 액세스 토큰 저장이 실패한다.

      expect(await _status(s.dio, '/v1/me/x'), 401);

      // 세션은 최종 무효로 정리됐다 — 앱 상태·저장소·캐시가 모두 미인증이다.
      expect(s.isAuthenticated, isFalse);
      expect(s.storage.data.containsKey(_accessKey), isFalse);
      expect(s.storage.data.containsKey(_refreshKey), isFalse);
      expect(await _status(s.dio, '/v1/public/ping'), 200);
      expect(s.lastAuth, isNull, reason: '실패한 회전 뒤에 옛 A1이 캐시에 남아 실려 나가면 안 된다');
    });

    test('로그아웃 ⓓ: 로그아웃 뒤 요청은 토큰 없이 나간다 — 캐시가 옛 토큰을 내지 않는다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue();
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      await s.auth.restore();
      expect(await _status(s.dio, '/v1/me/x'), 200); // 캐시에 A1.
      expect(s.lastAuth, 'Bearer A1');

      await s.auth.logout();

      expect(s.isAuthenticated, isFalse);
      expect(s.storage.data.containsKey(_accessKey), isFalse);
      expect(s.refreshApi.loggedOut, <String>['R1'], reason: '서버 세션도 취소됐어야 한다(MOB-12)');
      expect(await _status(s.dio, '/v1/public/ping'), 200);
      expect(s.lastAuth, isNull, reason: '로그아웃한 기기가 옛 토큰을 계속 실어 보내면 정리가 실패한 것이다');
    });

    test('로그아웃 ⓓ: 같은 기기에서 다음 학생이 로그인하면 이전 학생 토큰이 아닌 새 토큰이 실린다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue(); // 이전 학생: A1/R1
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      await s.auth.restore();
      expect(await _status(s.dio, '/v1/me/x'), 200);
      await s.auth.logout();

      await s.auth.completeLogin(provider: 'kakao', code: 'c', redirectUri: 'r'); // 다음 학생: A2/R2

      expect(await _status(s.dio, '/v1/me/y'), 200);
      expect(s.lastAuth, 'Bearer A2');
    });

    test('401 ⓔ: 갱신할 리프레시 토큰이 없으면 전역 로그아웃으로 수렴하고 옛 토큰은 캐시에 남지 않는다 (MOB-24)', () async {
      final s = _buildStack();
      s.storage.data[_accessKey] = 'A1'; // 리프레시 토큰은 없다.
      s.server.validAccess = null; // 서버에서 이미 만료.
      await s.auth.restore();
      expect(s.isAuthenticated, isTrue);

      expect(await _status(s.dio, '/v1/me/x'), 401);

      expect(s.isAuthenticated, isFalse, reason: '갱신 불가 401은 앱 전역 로그아웃으로 이어져야 한다(MOB-15)');
      expect(s.storage.data.containsKey(_accessKey), isFalse);
      expect(await _status(s.dio, '/v1/public/ping'), 200);
      expect(s.lastAuth, isNull, reason: '401로 정리된 뒤에도 옛 토큰이 캐시에서 나가면 안 된다');
    });

    test('401 ⓔ: 서버가 리프레시 세션을 취소했으면(갱신 거절) 저장분을 폐기하고 로그아웃으로 수렴한다 (MOB-24)', () async {
      final s = _buildStack();
      s.server.issue();
      s.storage.data[_accessKey] = 'A1';
      s.storage.data[_refreshKey] = 'R1';
      await s.auth.restore();
      expect(await _status(s.dio, '/v1/me/x'), 200); // 캐시에 A1.
      s.server.expireAccess();
      s.server.sessionRevoked = true; // 갱신이 거절된다.

      expect(await _status(s.dio, '/v1/me/y'), 401);

      expect(s.isAuthenticated, isFalse);
      expect(s.storage.data.containsKey(_accessKey), isFalse);
      expect(s.storage.data.containsKey(_refreshKey), isFalse);
      expect(await _status(s.dio, '/v1/public/ping'), 200);
      expect(s.lastAuth, isNull);
    });
  });
}
