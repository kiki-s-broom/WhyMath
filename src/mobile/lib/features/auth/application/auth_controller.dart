// 인증 컨트롤러 — code 교환 → 토큰 저장 → auth 상태. OAuth-c1.
//
// 경계(CLAUDE.md): 토큰 발급·검증은 서버(L5). 이 컨트롤러는 (1) provider code를 백엔드 콜백으로
// 교환하고 (2) 받은 JWT를 보안 저장소(OAuth-b `tokenStore`)에 저장하며 (3) 실패를 graceful 처리할
// 뿐이다. provider 리다이렉트(code 획득·webview/딥링크)는 *호출자*(로그인 화면·c2)가 담당하고
// 여기엔 code만 들어온다. `ChatController`(@riverpod) 패턴을 따른다.
// riverpod 3: riverpod_annotation이 수동 Provider를 재수출하지 않는다 — 명시 import.
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../core/api_client.dart';
import '../../../core/env.dart';
import '../../../core/token_store.dart';
import '../../chat/application/chat_controller.dart';
import '../../chat/data/dialogue_store.dart';
import '../../problems/application/active_problem.dart';
import '../data/auth_api.dart';
import 'auth_state.dart';

part 'auth_controller.g.dart';

/// 시연 전용 사전주입 토큰 소스(S1 실기기 시연 게이트 ①) — 기본은 컴파일 타임 [Env.demoToken].
///
/// 별도 provider로 감싸 (1) `restore()`가 시연 토큰을 *주입 가능한 seam*으로 읽게 하고
/// (2) 테스트가 dart-define 없이 override로 시연 분기를 검증하게 한다. 미주입(prod 빌드) 시
/// [Env.demoToken]은 빈 문자열이라 시연 분기는 실행되지 않는다(누출 없음).
final demoTokenProvider = Provider<String>((ref) => Env.demoToken);

/// 인증 세션을 관리하는 Riverpod Notifier.
@riverpod
class AuthController extends _$AuthController {
  @override
  AuthState build() => const AuthState();

  /// 앱 시작 시 보안 저장소(OAuth-b `tokenStore`)의 토큰으로 인증 세션을 복원한다.
  ///
  /// 재시작 후에도 로그인 세션을 유지한다 — `build()`는 항상 미인증으로 시작하므로, 시작 시
  /// 한 번 호출해 저장된 토큰이 있으면 인증 상태로 올린다(라우터 가드가 채팅으로 보냄·c2b).
  /// 토큰 *검증*은 서버(L5) — 여기선 존재만 보고 운반한다(만료 처리는 후속). 보안 저장소 오류는
  /// 미인증으로 처리해 앱이 죽지 않게 한다.
  Future<void> restore() async {
    try {
      // 시연 전용(S1 게이트 ①): DEMO_TOKEN 주입 시 저장소에 심고 인증한다 — 실 로그인 webview
      // (OAuth-c3) 미배선 상태에서 실기기 시연 루프를 인증된 채로 부팅한다. prod 빌드는 이
      // define을 넘기지 않아 빈 값 → 이 분기 미실행(누출 없음). 저장 후엔 인터셉터가 Bearer 첨부.
      final demoToken = ref.read(demoTokenProvider);
      if (demoToken.isNotEmpty) {
        await ref.read(tokenStoreProvider).saveAccessToken(demoToken);
        state = state.copyWith(isAuthenticated: true);
        return;
      }
      final token = await ref.read(tokenStoreProvider).readAccessToken();
      if (token != null && token.isNotEmpty) {
        state = state.copyWith(isAuthenticated: true);
      }
    } on Object catch (_) {
      // 보안 저장소 미가용·오류(테스트의 MissingPluginException 포함) → 미인증 취급, 앱 안 죽음.
    }
  }

  /// authorization code를 토큰으로 교환하고 보안 저장소에 저장한다(로그인 완료).
  ///
  /// 흐름: ① 전송중 표시·에러 클리어 → ② `AuthApi.login`(백엔드 콜백) → ③ `tokenStore.saveAccessToken`
  /// → 인증 상태 → ④ 실패 시 graceful 에러(앱은 죽지 않는다). 토큰 저장 후엔 dio 인터셉터(OAuth-b)가
  /// 이후 모든 요청에 Bearer로 첨부한다.
  Future<void> completeLogin({
    required String provider,
    required String code,
    required String redirectUri,
  }) async {
    if (state.isSubmitting) {
      return; // 전송 중 재진입 방지.
    }
    state = state.copyWith(isSubmitting: true, error: null);
    try {
      final tokens = await ref
          .read(authApiProvider)
          .login(provider: provider, code: code, redirectUri: redirectUri);
      await ref.read(tokenStoreProvider).saveAccessToken(tokens.accessToken);
      // MOB-12: 리프레시 토큰도 저장해야 액세스 만료 시 인터셉터가 무중단 갱신할 수 있다.
      await ref.read(refreshTokenStoreProvider).saveRefreshToken(tokens.refreshToken);
      state = state.copyWith(isSubmitting: false, isAuthenticated: true);
    } catch (e) {
      state = state.copyWith(isSubmitting: false, error: '로그인에 실패했어요. 잠시 후 다시 시도해 주세요.');
    }
  }

  /// 로그아웃 — **서버 세션을 취소**하고 저장된 토큰을 지운 뒤 미인증 상태로 되돌린다.
  ///
  /// MOB-12: 예전에는 로컬 토큰만 지웠다. 그러면 서버의 리프레시 세션은 살아 있어서, 그 토큰을
  /// 손에 넣은 쪽은 계속 액세스 토큰을 재발급받을 수 있었다(로그아웃이 기기 안에서만 일어남).
  /// 이제 `POST /v1/auth/logout`으로 서버 세션을 먼저 취소한다.
  ///
  /// 서버 호출이 실패해도(오프라인 등) **로컬 정리는 반드시 수행한다** — 학생이 로그아웃을
  /// 눌렀는데 로그인 상태로 남는 것이 더 나쁘다. 실패를 조용히 삼키지 않도록 예외 타입을 로그에
  /// 남긴다(CLAUDE.md 침묵 실패 금지).
  Future<void> logout() async {
    final refreshStore = ref.read(refreshTokenStoreProvider);
    try {
      final refreshToken = await refreshStore.readRefreshToken();
      if (refreshToken != null && refreshToken.isNotEmpty) {
        await ref.read(tokenRefreshApiProvider).logout(refreshToken);
      }
    } on Object catch (e) {
      debugPrint('로그아웃 서버 세션 취소 실패(${e.runtimeType}) — 로컬 정리는 계속한다.');
    }
    await ref.read(tokenStoreProvider).clear();
    try {
      await refreshStore.clearRefreshToken();
    } on Object catch (e) {
      debugPrint('리프레시 토큰 삭제 실패(${e.runtimeType}).');
    }
    // MOB-11: 마지막 대화 세션 참조도 지운다 — 같은 기기에서 다음 학생이 로그인했을 때 이전
    // 학생의 세션 UUID로 복원을 시도하지 않게(서버 소유권 검증이 404로 막지만 참조 자체를 남기지 않는다).
    try {
      await ref.read(dialogueStoreProvider).clearDialogueId();
    } on Object catch (e) {
      debugPrint('대화 세션 참조 삭제 실패(${e.runtimeType}).');
    }
    state = state.copyWith(isAuthenticated: false);
    // MOB-23: 토큰·대화 참조만 지우고 끝내면 이전 학생의 활성 문제·코치 대화(dialogueId·메시지 누적)가
    // provider에 그대로 남는다(非autoDispose `activeProblemProvider`·앱 수명 내내 유지되는
    // `ChatController` 상태) — 같은 기기로 다음 학생이 로그인하면 그 잔여가 그대로 보인다.
    // `invalidate`로 두 provider를 최초 빌드 상태(활성 문제 없음·빈 대화)로 되돌려 학생 간 경계를 보장한다.
    // 위 세 정리가 모두 끝난 뒤(= 로그아웃이 실제로 완료된 경우)에만 실행된다 — `tokenStore.clear()`가
    // 던지면 학생은 로그인 상태로 남으므로 잔여를 지울 이유가 없다.
    ref.invalidate(activeProblemProvider);
    ref.invalidate(chatControllerProvider);
  }
}
