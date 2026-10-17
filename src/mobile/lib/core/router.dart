// 앱 라우팅 셸 — go_router 설정과 라우트 상수.
//
// 단일 화면(MaterialApp.home)에서 go_router 기반 셸로 전환한다. 첫 진입은 온보딩
// (메타인지 철학 안내·기대 관리)이고, "시작하기"로 채팅 화면에 진입한다.
//
// 하단 탭 네비게이션(홈/학습/탐구/나)은 `StatefulShellRoute.indexedStack`으로 추가했다(MOB-08).
// 채팅(학습)은 `/`에 그대로 두어 기존 흐름을 보존하고, 온보딩·로그인·OCR·문제·수식 입력은 셸 밖
// 최상위 라우트로 유지한다(탭 바 없이 전체 화면).
//
// 정직(범위): 세션 복원(OAuth-c2b)으로 *복원된 인증* 세션은 가드가 채팅으로 보낸다. 단 실 로그인은
// code 획득 webview(c3) 전엔 작동하지 않으므로 가드는 미인증을 강제하지 않는다 — 미인증은 여전히
// 온보딩→채팅 흐름을 그대로 탄다(앱 유지). 온보딩을 이미 마친 기기는 같은 가드가 채팅으로 보낸다
// (`onboardingSeenControllerProvider`·복귀 지원 최소 착지 MOB-11). 미인증→로그인 강제·로그아웃
// 반영·딥링크는 *후속 슬라이스*다.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/application/auth_controller.dart';
import '../features/auth/presentation/account_security_screen.dart';
import '../features/auth/presentation/login_screen.dart';
import '../features/chat/presentation/chat_screen.dart';
import '../features/chat/presentation/mathlive_input_screen.dart';
import '../features/explore/presentation/explore_screen.dart';
import '../features/home/presentation/home_screen.dart';
import '../features/ocr/presentation/ocr_capture_screen.dart';
import '../features/onboarding/application/onboarding_seen_controller.dart';
import '../features/onboarding/presentation/onboarding_screen.dart';
import '../features/problems/presentation/problem_screen.dart';
import '../features/profile/presentation/me_screen.dart';
import 'shell/app_shell.dart';

/// 앱 라우트 경로·이름 상수.
///
/// 문자열 리터럴 분산을 막아 라우트 정의·네비게이션 호출이 같은 상수를 참조하게 한다.
abstract final class AppRoutes {
  /// 온보딩(첫 진입) 경로.
  static const String onboardingPath = '/onboarding';

  /// 온보딩 라우트 이름.
  static const String onboardingName = 'onboarding';

  /// 채팅(메인) 경로.
  static const String chatPath = '/';

  /// 채팅 라우트 이름.
  static const String chatName = 'chat';

  /// 홈(하단 탭) 경로 — 셸의 첫 탭. 교과서 좌표(준비 중)·학습 진입.
  static const String homePath = '/home';

  /// 홈 라우트 이름.
  static const String homeName = 'home';

  /// 탐구(하단 탭) 경로 — 사고력·시각화·갤러리(준비 중).
  static const String explorePath = '/explore';

  /// 탐구 라우트 이름.
  static const String exploreName = 'explore';

  /// 나(하단 탭) 경로 — 학습 경로·진단·설정(준비 중)·로그아웃.
  static const String mePath = '/me';

  /// 나 라우트 이름.
  static const String meName = 'me';

  /// 로그인(소셜) 경로 — OAuth-c2. 등록만 하고 기본 흐름은 강제하지 않는다.
  static const String loginPath = '/login';

  /// 로그인 라우트 이름.
  static const String loginName = 'login';

  /// 계정 보안(내 기기 관리) 경로 — "나" 탭에서 push해 진입한다(MOB-12).
  static const String accountSecurityPath = '/account-security';

  /// 계정 보안 라우트 이름.
  static const String accountSecurityName = 'account-security';

  /// 풀이 사진 OCR 경로 — 채팅에서 push해 진입하고, 인식 결과를 pop 결과로 돌려준다(S1-d).
  static const String ocrPath = '/ocr';

  /// OCR 라우트 이름.
  static const String ocrName = 'ocr';

  /// 진단→문제제시 경로 — 온보딩 완료 후 진입한다. CAT 추천 문제를 제시하고 코치로 넘긴다(S1).
  static const String problemPath = '/problem';

  /// 문제 라우트 이름.
  static const String problemName = 'problem';

  /// 수식(MathLive) 입력 경로 — 채팅 풀이 모드에서 push해 진입하고, LaTeX를 pop 결과로 돌려준다.
  static const String mathInputPath = '/math-input';

  /// 수식 입력 라우트 이름.
  static const String mathInputName = 'math-input';
}

/// 앱 전역 [GoRouter] provider.
///
/// `initialLocation`은 항상 온보딩 경로 상수다 — 실제 첫 화면(온보딩을 볼지·바로 채팅으로
/// 갈지)은 `redirect`가 결정한다(아래). 라우터 인스턴스는 앱 수명 동안 1개만 유지되도록 plain
/// [Provider]로 둔다(코드 생성 의존 없이 기존 provider 패턴과 일치). `redirect`는 *복원된 인증*
/// 세션과 *온보딩을 이미 마친* 기기를 채팅으로 보내는 비파괴 가드다(c2b + MOB-11) — 미인증 강제
/// redirect는 후속 슬라이스다(기본 흐름은 온보딩→채팅 유지).
final goRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: AppRoutes.onboardingPath,
    // 비파괴 가드: ① OAuth-c2b — *복원된 인증* 세션이 온보딩/로그인에 있으면 채팅으로 보낸다.
    // ② MOB-11 — 온보딩을 이미 마친 기기(`onboardingSeenControllerProvider`)가 온보딩에 있으면
    // 채팅으로 보낸다(복귀 학생이 매번 온보딩부터 다시 보지 않게 — "돌아오기 쉽다"). 로그인 경로는
    // ②의 대상이 아니다(온보딩만 봤다고 로그인 화면을 막지 않는다).
    // 미인증은 강제 redirect하지 않는다 — 로그인은 실 webview(c3) 전엔 작동하지 않으므로
    // 미인증→로그인 강제는 앱을 막는다(미인증은 현 온보딩→채팅 흐름 유지). redirect는 완전
    // 동기라 context를 쓰지 않는다. refreshListenable 생략(c2b): 두 상태 모두 복원은 runApp 전 완료되고
    // 로그인은 명시적 네비게이션이라 런타임 재평가가 불필요하다 — 로그아웃·강제 가드는 c3.
    redirect: (context, state) {
      final authenticated = ref.read(authControllerProvider).isAuthenticated;
      final onboardingSeen = ref.read(onboardingSeenControllerProvider);
      final location = state.matchedLocation;
      if (location == AppRoutes.onboardingPath && (authenticated || onboardingSeen)) {
        return AppRoutes.chatPath;
      }
      if (authenticated && location == AppRoutes.loginPath) {
        return AppRoutes.chatPath;
      }
      return null;
    },
    routes: [
      GoRoute(
        path: AppRoutes.onboardingPath,
        name: AppRoutes.onboardingName,
        builder: (context, state) => const OnboardingScreen(),
      ),
      // 하단 탭 네비게이션 셸(MOB-08) — 홈/학습/탐구/나 4탭을 각 브랜치로 감싸 상태를 보존하며
      // 전환한다(`StatefulShellRoute.indexedStack`). 채팅(학습)은 `/`에 그대로 두어 기존 redirect·
      // errorBuilder·`context.go(chatPath)` 호출이 변경 없이 학습 탭으로 도달한다. 온보딩·로그인·
      // OCR·문제·수식 입력은 셸 *밖* 최상위 라우트라 탭 바 없이 전체 화면으로 뜬다(플로우·모달성).
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) => AppShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.homePath,
                name: AppRoutes.homeName,
                builder: (context, state) => const HomeScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.chatPath,
                name: AppRoutes.chatName,
                builder: (context, state) => const ChatScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.explorePath,
                name: AppRoutes.exploreName,
                builder: (context, state) => const ExploreScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.mePath,
                name: AppRoutes.meName,
                builder: (context, state) => const MeScreen(),
              ),
            ],
          ),
        ],
      ),
      // 소셜 로그인(OAuth-c2) — 라우트로 등록만 한다. 실 code 획득(c3) 전엔 작동하지 않으므로
      // initialLocation·온보딩 흐름은 건드리지 않는다(흐름 강제·세션 복원은 c2b).
      GoRoute(
        path: AppRoutes.loginPath,
        name: AppRoutes.loginName,
        builder: (context, state) => const LoginScreen(),
      ),
      // 계정 보안 — 내 기기 관리(MOB-12). "나" 탭에서 push로 진입한다. 셸 밖 최상위 라우트라
      // 탭 바 없이 전체 화면으로 뜬다(설정성 화면·로그인/OCR과 동형).
      GoRoute(
        path: AppRoutes.accountSecurityPath,
        name: AppRoutes.accountSecurityName,
        builder: (context, state) => const AccountSecurityScreen(),
      ),
      // 풀이 사진 OCR(S1-d) — 채팅에서 push로 진입한다. 인식 결과를 코치에게 넘길 땐
      // `context.pop(result)`로 `OcrResult`를 호출자(채팅)에게 돌려주고, 채팅이
      // `chat_controller.sendOcrSolution`으로 매핑·전송한다(OCR 화면은 채팅을 알지 못한다·
      // 단방향 chat→ocr 의존 유지).
      GoRoute(
        path: AppRoutes.ocrPath,
        name: AppRoutes.ocrName,
        builder: (context, state) => const OcrCaptureScreen(),
      ),
      // 진단→문제제시(S1) — 온보딩 완료 후 진입한다. CAT 추천 문제를 로드해 제시하고,
      // "풀이 시작"으로 활성 문제를 세팅한 뒤 채팅(코치)으로 넘긴다(세션 묶기는 코치가 소비).
      GoRoute(
        path: AppRoutes.problemPath,
        name: AppRoutes.problemName,
        builder: (context, state) => const ProblemScreen(),
      ),
      // 수식(MathLive) 입력 — 채팅 풀이 모드에서 push로 진입한다. 완료 시 `context.pop(latex)`로
      // LaTeX를 호출자(채팅)에게 돌려주고, 채팅이 `sendSolution`으로 매핑·전송한다(OCR과 동형·
      // 단방향 chat→math-input 의존·수식 입력기는 채팅을 알지 못한다).
      GoRoute(
        path: AppRoutes.mathInputPath,
        name: AppRoutes.mathInputName,
        builder: (context, state) => const MathliveInputScreen(),
      ),
    ],
    // 미정의 경로 안전 처리 — 잘못된 딥링크/오타로 앱이 죽지 않게 채팅으로 안내한다.
    errorBuilder: (context, state) => const ChatScreen(),
  );
});
