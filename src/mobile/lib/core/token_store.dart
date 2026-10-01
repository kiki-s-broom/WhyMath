// 액세스 토큰 영속 — flutter_secure_storage 래퍼(OS 보안 저장소) + 액세스 토큰 메모리 캐시. OAuth-b · MOB-24.
//
// 경계(CLAUDE.md): 미성년자 민감정보·토큰은 평문 저장 금지 — OS 보안 저장소(iOS Keychain·
// Android EncryptedSharedPreferences)에 둔다. 토큰은 클라가 *운반*만 하고 발급·검증은 서버(L5).
// 테스트 가능성을 위해 추상 인터페이스(TokenStore)로 감싸고, 플랫폼 채널을 타는 실 구현
// (SecureTokenStore)은 통합/수동 검증·소비자(인터셉터 등)는 fake TokenStore로 단위 테스트한다.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// 액세스 토큰 저장소 경계 — 읽기·쓰기·삭제(로그아웃).
abstract interface class TokenStore {
  /// 저장된 액세스 토큰(없으면 null).
  Future<String?> readAccessToken();

  /// 액세스 토큰 저장(로그인 성공 시).
  Future<void> saveAccessToken(String token);

  /// 토큰 삭제(로그아웃·만료).
  Future<void> clear();
}

/// 리프레시 토큰 저장소 경계 — 액세스 토큰 만료 시 무중단 갱신(MOB-12)에 쓰인다.
///
/// **[TokenStore]와 별도 인터페이스인 이유**: 액세스 토큰만 다루던 기존 계약에 메서드를 더하면
/// 이미 `implements TokenStore`로 선언된 테스트 fake 7종이 전부 깨진다. 리프레시 토큰은 수명·
/// 용도(갱신 전용·서버 allowlist 대상)가 다른 별개 자산이므로 계약도 분리해 둔다 — 실 구현
/// ([SecureTokenStore])은 두 계약을 함께 만족하고, 액세스 토큰만 필요한 소비자(인터셉터의 헤더
/// 첨부 등)는 기존 계약만 알면 된다(인터페이스 분리 원칙).
///
/// 경계(CLAUDE.md): 리프레시 토큰도 *운반*만 한다 — 회전·재사용 탐지·취소 판정은 전부 서버(L5)다.
abstract interface class RefreshTokenStore {
  /// 저장된 리프레시 토큰(없으면 null).
  Future<String?> readRefreshToken();

  /// 리프레시 토큰 저장(로그인·회전 성공 시).
  Future<void> saveRefreshToken(String token);

  /// 리프레시 토큰 삭제(로그아웃·재사용 탐지로 서버가 거부했을 때).
  Future<void> clearRefreshToken();
}

/// flutter_secure_storage 기반 실 구현 — OS 보안 저장소에 토큰을 두고, **액세스 토큰만** 메모리에 캐시한다.
///
/// 플랫폼 채널이라 `flutter test`에서 직접 검증 불가(통합/수동) — 소비자는 [TokenStore] fake로
/// 단위 테스트한다. 다만 캐시 로직은 [FlutterSecureStorage]를 가짜로 갈아 끼워
/// (`secureTokenStoreProvider` override) 플랫폼 채널 없이 그대로 검증한다. 액세스·리프레시 두 토큰을
/// *다른 키*로 저장한다(용도·수명이 다르므로 한쪽만 지우는 조작이 가능해야 한다 — 예: 갱신 실패 시
/// 액세스만 버리고 재로그인 유도).
///
/// ### 왜 캐시하는가 (MOB-24 ②)
/// `AuthInterceptor`는 **모든 요청마다** [readAccessToken]을 부른다. 캐시가 없으면 요청 하나마다
/// 플랫폼 채널 왕복(Keystore/Keychain 복호화)이 하나씩 붙어, 화면 하나가 요청을 여러 개 쏘면 그만큼
/// 지연이 쌓인다.
///
/// ### 캐시가 낡은 토큰을 내면 — 그래서 무효화가 핵심이다
/// 토큰은 로그인·갱신 회전·로그아웃·401 정리로 바뀐다. 캐시가 그 변화를 놓치면 로그아웃한 기기가 옛
/// 토큰을 계속 실어 보내거나, 갱신 뒤에도 옛 토큰으로 401을 반복해 갱신을 또 태운다(리프레시 토큰은
/// 1회용이라 회전이 어긋나면 서버가 재사용 탐지로 **전체 세션을 취소**한다). 그래서 캐시는 이 클래스
/// 안에서 **write-through**로만 존재하고, 저장소를 바꾸는 모든 경로(로그인 저장·갱신 회전 저장·
/// 로그아웃 삭제·401 정리 삭제)가 이 클래스의 [saveAccessToken]·[clear]를 지난다:
///  - [saveAccessToken] — 저장소 쓰기가 *성공한 뒤에만* 캐시를 새 토큰으로 채운다(실패하면 비운 채).
///  - [clear] — 성공·실패와 무관하게 캐시를 비운다(다음 읽기가 저장소 진실을 다시 읽는다).
///  - 저장소 읽기 실패(예외)는 캐시하지 않는다(다음 읽기가 다시 시도한다).
///  - 변경(저장·삭제)이 *시작되는 즉시* 캐시를 비우고, 변경 도중·이전에 시작된 읽기가 뒤늦게 돌아와
///    캐시를 덮어쓰지 못하게 **세대(epoch)** 로 막는다 — 로그아웃 직후 옛 토큰이 되살아나거나 로그인
///    직후 "토큰 없음"이 캐시에 남는 경합을 차단한다.
///
/// **인스턴스는 앱 전체에서 하나여야 한다** — 캐시가 인스턴스 안에 있어 둘이면 서로의 쓰기를 못 본다.
/// 그래서 이 클래스를 만드는 곳은 [secureTokenStoreProvider] 하나뿐이고, 액세스·리프레시 두 계약
/// provider는 그 인스턴스를 공유한다(`test/token_store_cache_test.dart`가 동일 인스턴스를 고정한다).
///
/// 리프레시 토큰은 캐시하지 않는다 — 갱신 때만(드물게) 읽고, 1회용이라 낡은 값이 나가면 곧바로 세션
/// 취소로 이어지므로 매번 저장소 진실을 읽는다.
class SecureTokenStore implements TokenStore, RefreshTokenStore {
  SecureTokenStore(this._storage);

  final FlutterSecureStorage _storage;

  static const _key = 'access_token';
  static const _refreshKey = 'refresh_token';

  // ── 액세스 토큰 메모리 캐시 상태(MOB-24 ②) ───────────────────────────────

  /// 캐시가 저장소 진실을 반영하는가. false면 "모른다"이고 다음 읽기가 저장소를 읽는다.
  bool _cacheValid = false;

  /// 캐시 값 — [_cacheValid]가 true일 때만 의미가 있다(null = 저장소에 토큰이 없음을 확인한 상태).
  String? _cachedToken;

  /// 변경(저장·삭제)이 시작되거나 끝날 때마다 올린다 — 읽기가 시작된 뒤 변경이 끼어들었는지 가리는 표식.
  int _epoch = 0;

  /// 지금 진행 중인 변경(저장·삭제) 수.
  int _mutations = 0;

  /// 진행 중인 저장소 읽기 1건 — 캐시가 빈 동안 동시에 온 읽기를 저장소 왕복 한 번으로 묶는다.
  Future<String?>? _pendingRead;

  @override
  Future<String?> readAccessToken() {
    if (_cacheValid) {
      return Future<String?>.value(_cachedToken);
    }
    return _pendingRead ??= _readFromStorage();
  }

  /// 저장소에서 읽고, *그 사이 변경이 끼어들지 않았을 때만* 캐시에 반영한다.
  Future<String?> _readFromStorage() {
    final startEpoch = _epoch;
    // 변경이 진행 중일 때 시작한 읽기는 결과가 변경 전·후 어느 쪽인지 알 수 없어 캐시하지 않는다.
    final cacheable = _mutations == 0;
    // `Future.sync`: 저장소가 동기 예외(`FlutterSecureStorage.read`는 async가 아니라 미지원 플랫폼에서
    // 예외가 Future 밖으로 곧장 나온다)를 던져도 Future 오류로 수렴시킨다. 진행 표식 해제를 async 함수의
    // `finally`에 두면 동기 예외 때 호출자가 표식을 대입하기 *전에* 해제가 먼저 돌아 실패한 Future가
    // 표식으로 영구히 남는다(이후 모든 읽기가 저장소를 부르지도 않고 같은 실패를 재방송한다). 아래
    // `then`·`whenComplete` 콜백은 항상 호출자의 표식 대입 *이후*에 비동기로 돈다.
    return Future<String?>.sync(() => _storage.read(key: _key))
        .then<String?>((value) {
          if (cacheable && startEpoch == _epoch) {
            _cachedToken = value;
            _cacheValid = true;
          }
          return value;
        })
        .whenComplete(() {
          // 같은 세대의 읽기일 때만 진행 표식을 치운다 — 그 사이 변경이 이미 표식을 폐기했고 더 새로운 읽기가
          // 새 표식을 달았다면 그것을 건드리지 않는다. (읽기 예외는 여기서 삼키지 않고 호출자로 전파한다.)
          if (startEpoch == _epoch) {
            _pendingRead = null;
          }
        });
  }

  @override
  Future<void> saveAccessToken(String token) => _mutateAccessToken(
    () => _storage.write(key: _key, value: token),
    cacheResult: true,
    resultToken: token,
  );

  @override
  Future<void> clear() => _mutateAccessToken(
    () => _storage.delete(key: _key),
    cacheResult: false,
  );

  /// 액세스 토큰 키를 바꾸는 작업(저장·삭제)의 공통 골격.
  ///
  /// ① 시작하자마자 캐시를 비운다(쓰기 도중에 낡은 값이 나가지 않게 — 이후 읽기는 저장소를 읽는다).
  /// ② 저장소 작업이 **성공한 뒤에만**, 그리고 나 혼자 진행했을 때만 [resultToken]으로 캐시를 채운다
  ///    (겹친 변경은 저장소에 어느 쪽이 나중에 닿았는지 알 수 없어 채우지 않는다 — 다음 읽기가 진실을 읽는다).
  /// ③ 끝나면(성공·실패 모두) 세대를 올려, 이 작업 도중에 시작된 읽기가 뒤늦게 캐시를 채우지 못하게 한다.
  Future<void> _mutateAccessToken(
    Future<void> Function() writeToStorage, {
    required bool cacheResult,
    String? resultToken,
  }) async {
    _invalidateCache();
    _mutations++;
    final epochAtStart = _epoch;
    try {
      await writeToStorage();
      if (cacheResult && _mutations == 1 && epochAtStart == _epoch) {
        _cachedToken = resultToken;
        _cacheValid = true;
      }
    } finally {
      _mutations--;
      _epoch++;
      _pendingRead = null;
    }
  }

  /// 캐시를 "모른다"로 되돌린다 — 토큰 문자열 참조도 함께 놓는다(메모리에 낡은 토큰을 남기지 않는다).
  void _invalidateCache() {
    _epoch++;
    _cacheValid = false;
    _cachedToken = null;
    _pendingRead = null;
  }

  @override
  Future<String?> readRefreshToken() => _storage.read(key: _refreshKey);

  @override
  Future<void> saveRefreshToken(String token) => _storage.write(key: _refreshKey, value: token);

  @override
  Future<void> clearRefreshToken() => _storage.delete(key: _refreshKey);
}

/// 앱 전역 단일 [SecureTokenStore] — 액세스 토큰 메모리 캐시의 **유일한 주인**(MOB-24 ②).
///
/// 이 클래스를 만드는 곳은 여기 하나여야 한다 — 인스턴스가 둘이면 한쪽의 저장·삭제를 다른 쪽 캐시가
/// 못 봐서 낡은 토큰을 낸다. 아래 두 계약 provider([tokenStoreProvider]·[refreshTokenStoreProvider])는
/// 이것을 그대로 공유한다. 테스트는 이 provider를 override해 플랫폼 채널 없는 fake 저장소 위에서 실
/// 캐시 로직과 실 인터셉터·로그인·로그아웃 배선을 함께 검증한다.
final secureTokenStoreProvider = Provider<SecureTokenStore>(
  (ref) => SecureTokenStore(const FlutterSecureStorage()),
);

/// 앱 전역 토큰 저장소 provider — [secureTokenStoreProvider]의 액세스 토큰 계약 면.
final tokenStoreProvider = Provider<TokenStore>(
  (ref) => ref.watch(secureTokenStoreProvider),
);

/// 앱 전역 리프레시 토큰 저장소 provider — 같은 [SecureTokenStore] 인스턴스의 다른 계약 면(MOB-12).
///
/// [tokenStoreProvider]와 **같은 인스턴스**다(MOB-24 — 예전에는 `const` 생성자가 우연히 하나로 합쳐
/// 줬지만, 이제 캐시 상태가 인스턴스에 있어 명시적으로 공유한다). 테스트는 이 provider만 override해
/// 갱신 경로를 검증하고, 액세스 토큰만 쓰는 기존 테스트는 [tokenStoreProvider]만 override하던 방식을
/// 그대로 유지한다.
final refreshTokenStoreProvider = Provider<RefreshTokenStore>(
  (ref) => ref.watch(secureTokenStoreProvider),
);
