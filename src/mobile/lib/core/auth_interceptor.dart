// dio 인증 인터셉터 — 액세스 토큰 Bearer 첨부 + 만료 시 자동 갱신·재시도. OAuth-b · MOB-12.
//
// 경계(CLAUDE.md): 클라는 토큰을 *운반*만 한다(발급·검증·회전 판정은 서버 L5). 토큰이 없으면
// 헤더를 붙이지 않는다(미인증 요청은 서버가 401로 처리).
//
// MOB-12에서 더한 것 — **401 → 갱신 → 원요청 재시도**:
// 액세스 토큰은 짧게 만료되는데 갱신 배선이 없어서, 만료 순간 학생은 아무 예고 없이 모든 화면이
// 실패하는 상태였다(`POST /v1/auth/refresh` 서버 좌석은 완비·모바일 호출 0건 — OPS-22 실측).
// 이제 401을 받으면 저장된 리프레시 토큰으로 한 번 갱신하고 원요청을 재시도한다. 학생 눈에는
// 아무 일도 일어나지 않는다(무중단) — 이것이 이 배선의 실효다.
//
// 만료 여부를 클라가 *판정하지 않는다*는 점이 중요하다 — JWT exp를 파싱해 선제 갱신하지 않고,
// 서버가 401을 줄 때만 반응한다(판정 권위는 서버 단일).
//
// MOB-15에서 더한 것 — **세션 최종 무효 시 앱 전역 정리 콜백(`onUnauthorized`)**:
// 갱신까지 실패해 원래 401을 올리는 순간(또는 갱신 의존이 아예 없는데 401), 인터셉터는 저장 토큰을
// 지우지만 *앱 상태*(isAuthenticated·라우터)는 여전히 로그인 상태로 남는다 — 학생은 "아무것도 안
// 되는" 화면에 갇힌다. 이 콜백으로 상위(dioProvider)가 로그아웃 전체 정리를 태우게 한다.
// 갱신 성공·재시도 경로에서는 부르지 않는다(무중단이 MOB-12의 실효다).
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'token_refresh_api.dart';
import 'token_store.dart';

/// 재시도 1회 표식 — 갱신 후 재시도한 요청이 다시 401이면 더는 갱신하지 않는다(무한 루프 차단).
const String _retriedFlag = 'whymath_auth_retried';

/// 저장된 액세스 토큰을 요청 헤더(Authorization: Bearer)에 첨부하고, 401 시 갱신·재시도하는 인터셉터.
///
/// 갱신 관련 의존 3종은 **선택**이다 — 주지 않으면 기존 동작(헤더 첨부만) 그대로다. 액세스 토큰만
/// 다루던 기존 테스트 fake들이 그대로 유효하도록 생성자를 후방호환으로 유지한다.
class AuthInterceptor extends Interceptor {
  AuthInterceptor(
    this._store, {
    TokenRefreshApi? refreshApi,
    RefreshTokenStore? refreshStore,
    Dio? retryDio,
    Future<void> Function()? onUnauthorized,
  }) : _refreshApi = refreshApi,
       _refreshStore = refreshStore,
       _retryDio = retryDio,
       _onUnauthorized = onUnauthorized;

  final TokenStore _store;

  /// 갱신 호출 래퍼 — **AuthInterceptor가 없는 Dio**로 만들어져야 한다(재귀 차단).
  final TokenRefreshApi? _refreshApi;
  final RefreshTokenStore? _refreshStore;

  /// 재시도용 Dio — 인증 인터셉터가 없는 인스턴스. 재시도가 다시 이 인터셉터를 타지 않게 한다.
  final Dio? _retryDio;

  /// 세션 최종 무효 시 호출되는 앱 전역 정리 콜백(선택·MOB-15).
  ///
  /// nullable + 기본 null — 토큰 저장소만 넘겨 만드는 기존 테스트 관례를 깨지 않는다(후방호환).
  /// Riverpod `Ref`를 이 낮은 계층에 넣지 않고 콜백으로 받아 프레임워크 결합을 최소화한다.
  final Future<void> Function()? _onUnauthorized;

  /// 진행 중인 최종 무효 정리 1건 — 동시에 여러 요청이 최종 401을 받아도 정리는 1회로 묶는다.
  Future<void>? _inFlightUnauthorized;

  /// 진행 중인 갱신 1건 — 동시에 401을 받은 여러 요청이 갱신을 중복 발사하지 않게 묶는다
  /// (리프레시 토큰은 1회용이라 동시 회전은 재사용 탐지에 걸려 전체 세션이 취소된다).
  Future<String?>? _inFlightRefresh;

  @override
  Future<void> onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await _store.readAccessToken();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    if (!_shouldAttemptRefresh(err)) {
      // 여기 도달한 401은 둘 중 하나다: ① 갱신 의존이 미주입 — 이 인터셉터로는 세션을 되살릴
      // 길이 없다 → 최종 무효로 정리한다. ② 재시도 표식이 붙은 요청 — 정리하지 않는다(방금 갱신에
      // 성공한 세션을 로그아웃으로 서버 취소까지 하는 것은 과잉이다. 재시도는 인터셉터 없는 Dio로
      // 나가므로 정상 흐름에선 이 경로로 되돌아오지 않고, 무한 루프도 없다).
      if (_isUnauthorized(err) && !_isRetried(err)) {
        await _notifyUnauthorized();
      }
      handler.next(err);
      return;
    }
    final newToken = await _refreshOnce();
    if (newToken == null) {
      // 갱신 실패 = 리프레시 토큰도 만료·취소됨. 저장분을 버리고 원래 401을 그대로 올린다
      // (조용히 삼키지 않는다 — 호출자가 재로그인으로 유도할 수 있어야 한다).
      // MOB-15: 앱 상태도 미인증으로 맞춘다(콜백 — 로그아웃 전체 정리).
      await _notifyUnauthorized();
      handler.next(err);
      return;
    }
    try {
      final retried = await _retry(err.requestOptions, newToken);
      handler.resolve(retried);
    } on DioException catch (retryError) {
      handler.next(retryError);
    } on Object {
      handler.next(err);
    }
  }

  /// 갱신을 시도할 상황인가 — 401이고, 의존이 주입됐고, 아직 재시도한 적 없는 요청일 때만.
  bool _shouldAttemptRefresh(DioException err) {
    if (!_isUnauthorized(err)) {
      return false;
    }
    if (!_hasRefreshDeps) {
      return false;
    }
    return !_isRetried(err);
  }

  bool _isUnauthorized(DioException err) => err.response?.statusCode == 401;

  bool get _hasRefreshDeps => _refreshApi != null && _refreshStore != null && _retryDio != null;

  bool _isRetried(DioException err) => err.requestOptions.extra[_retriedFlag] == true;

  /// 최종 무효 정리 콜백 호출(동시 호출은 1건으로 묶음) — 콜백 실패가 원 에러 전파를 막지 않게 한다.
  ///
  /// 콜백 예외는 삼키되 **예외 타입명을 로그에 남긴다**(CLAUDE.md 침묵 실패 금지 — 필드값 제외).
  Future<void> _notifyUnauthorized() {
    final callback = _onUnauthorized;
    if (callback == null) {
      return Future<void>.value();
    }
    return _inFlightUnauthorized ??= () async {
      try {
        await callback();
      } on Object catch (e) {
        debugPrint('세션 무효 정리 콜백 실패(${e.runtimeType}) — 원 401은 그대로 전파한다.');
      }
    }().whenComplete(() {
      _inFlightUnauthorized = null;
    });
  }

  /// 갱신 1회(동시 요청은 같은 Future를 공유) — 성공 시 새 액세스 토큰, 실패 시 null.
  Future<String?> _refreshOnce() {
    return _inFlightRefresh ??= _doRefresh().whenComplete(() {
      _inFlightRefresh = null;
    });
  }

  Future<String?> _doRefresh() async {
    final store = _refreshStore!;
    try {
      final refreshToken = await store.readRefreshToken();
      if (refreshToken == null || refreshToken.isEmpty) {
        return null;
      }
      final tokens = await _refreshApi!.refresh(refreshToken);
      // 회전 결과는 **둘 다** 저장한다 — 서버가 옛 리프레시 세션을 취소했으므로 옛 토큰을
      // 남겨두면 다음 갱신이 재사용 탐지에 걸려 전체 세션이 날아간다.
      await _store.saveAccessToken(tokens.accessToken);
      await store.saveRefreshToken(tokens.refreshToken);
      return tokens.accessToken;
    } on Object {
      // 갱신 실패 → 저장분 폐기(다음 요청이 헛된 갱신을 반복하지 않게).
      await _safeClear();
      return null;
    }
  }

  Future<void> _safeClear() async {
    try {
      await _store.clear();
      await _refreshStore!.clearRefreshToken();
    } on Object {
      // 보안 저장소 오류로 앱이 죽지 않게 한다(미인증 취급으로 수렴).
    }
  }

  /// 원요청을 새 토큰으로 1회 재시도 — 재시도 표식을 실어 재귀를 차단한다.
  Future<Response<dynamic>> _retry(RequestOptions options, String token) {
    return _retryDio!.fetch<dynamic>(
      options.copyWith(
        headers: <String, dynamic>{...options.headers, 'Authorization': 'Bearer $token'},
        extra: <String, dynamic>{...options.extra, _retriedFlag: true},
      ),
    );
  }
}
