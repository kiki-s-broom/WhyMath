// Dio HTTP 클라이언트 — 독립 수학 코어(L1-L4) API 소비 단일 경로.
//
// 모든 백엔드 호출은 이 Dio 인스턴스를 거친다(baseUrl·타임아웃·공통 헤더 일원화).
// LLM·수학 검증은 *서버에서만* 수행되고, 클라이언트는 결과 JSON을 구조 그대로 수신한다
// (CLAUDE.md: 수학 로직을 클라에 넣지 않는다·표현≠의미).
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/auth/application/auth_controller.dart';
import 'auth_interceptor.dart';
import 'env.dart';
import 'token_refresh_api.dart';
import 'token_store.dart';

/// 공통 [BaseOptions] — 공유 Dio와 인증 없는 Dio가 **같은 baseUrl·타임아웃·헤더**를 쓰게 한다.
///
/// 갱신·재시도가 다른 설정으로 나가면(타임아웃 등) 원요청과 다른 실패 양상을 보여 진단이 흐려진다.
BaseOptions _baseOptions() => BaseOptions(
  baseUrl: Env.apiUrl,
  connectTimeout: const Duration(seconds: 10),
  receiveTimeout: const Duration(seconds: 30),
  // MOB-15: 송신 타임아웃 — OCR `/pages` multipart 이미지 업로드가 느린 네트워크에서 무한정
  // 대기하지 않도록. SEC-17이 합계 50MB 상한을 이미 걸어 뒀으므로 receiveTimeout과 대칭인 30초는
  // 일반 모바일 업로드 대역폭 기준 합리적 여유다(이 저장소에 별도 상한 근거 없음).
  sendTimeout: const Duration(seconds: 30),
  // 코어 API는 JSON in/out — 구조(AST/JSON)를 그대로 주고받는다.
  // X-App-Version(OPS-17): 서버 최소버전 계약 게이트(app.py _service_metrics_middleware)가
  // 읽는 클라 버전 신고. Env.appVersion은 컴파일타임 상수라야 이 const 맵에 들어갈 수 있다
  // (pubspec.yaml version:과의 동기화는 tests/infra/test_app_version_pubspec_sync.py가 게이트).
  headers: const {'Content-Type': 'application/json', 'X-App-Version': Env.appVersion},
);

/// 인증 인터셉터가 **없는** Dio provider — 토큰 갱신 호출·갱신 후 재시도 전용(MOB-12).
///
/// 갱신 요청이 [AuthInterceptor]를 타면 그 요청의 401이 다시 갱신을 부르는 무한 재귀가 된다.
/// 인터셉터를 아예 달지 않은 별도 인스턴스로 그 재귀를 *구조적으로* 차단한다(플래그 검사에
/// 의존하지 않는다 — 플래그는 재시도 축의 2차 방어로 따로 있다).
final authFreeDioProvider = Provider<Dio>((ref) => Dio(_baseOptions()));

/// 토큰 수명주기 API provider — 인증 없는 Dio 위에서 갱신·로그아웃을 호출한다(MOB-12).
final tokenRefreshApiProvider = Provider<TokenRefreshApi>(
  (ref) => TokenRefreshApi(ref.watch(authFreeDioProvider)),
);

/// 앱 전역에서 공유하는 Dio 인스턴스 provider.
///
/// - baseUrl: [Env.apiUrl](빌드 타임 주입·시크릿 하드코딩 금지).
/// - connect/receive/send 타임아웃: 모바일 네트워크 변동을 견디는 보수적 값(send는 MOB-15).
/// - [AuthInterceptor]: 저장된 액세스 토큰을 Bearer로 자동 첨부(OAuth-b·미인증이면 헤더 없이)
///   + 401 시 리프레시 토큰으로 갱신 후 원요청 1회 재시도(MOB-12·학생 눈에는 무중단)
///   + 갱신마저 실패한 세션 최종 무효 시 로그아웃 전체 정리(MOB-15).
/// - certificate pinning은 후속 슬라이스.
final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(_baseOptions());
  // 저장된 토큰을 모든 요청에 Bearer로 첨부(인증 플로우·OAuth-b) + 401 자동 갱신(MOB-12).
  dio.interceptors.add(
    AuthInterceptor(
      ref.read(tokenStoreProvider),
      refreshApi: ref.read(tokenRefreshApiProvider),
      refreshStore: ref.read(refreshTokenStoreProvider),
      retryDio: ref.read(authFreeDioProvider),
      // MOB-15: 세션 최종 무효(갱신 실패로 원 401을 올림) → `AuthController.logout()` 전체 정리.
      // 부분 정리(토큰만 삭제)는 앱이 로그인 상태로 남아 학생을 "아무것도 안 되는" 화면에 가둔다.
      //
      // 순환 의존 점검: 이 `ref.read`는 dioProvider build 시점이 아니라 **401 발생 시점**의 클로저
      // 안에서만 실행된다. `AuthController.build()`는 dioProvider를 읽지 않고, `logout()`은
      // `tokenRefreshApiProvider`(= 인증 인터셉터 없는 authFreeDio)만 쓰므로 이 dio로 다시 요청을
      // 보내지 않는다 — build-time 사이클도, 401→logout→401 재귀도 없다.
      onUnauthorized: () => ref.read(authControllerProvider.notifier).logout(),
    ),
  );
  return dio;
});
