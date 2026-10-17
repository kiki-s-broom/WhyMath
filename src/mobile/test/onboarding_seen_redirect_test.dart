// 온보딩 1회 노출 영속 — 라우터 redirect 가드 위젯 테스트(MOB-11).
//
// route_guard_test.dart(OAuth-c2b)와 동형 패턴: fake OnboardingStore를 주입한
// ProviderContainer를 만들고 runApp 전처럼 `restore()`를 먼저 호출한 뒤
// UncontrolledProviderScope로 실 앱(WhyMathApp)을 띄운다. 양방향(레드→그린) 검증 —
// ① 온보딩을 이미 마친 상태를 재현하면 재실행 시 온보딩이 건너뛰어진다.
// ② 저장소가 비어 있으면(최초 실행) 온보딩이 여전히 뜬다.
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/app.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';
import 'package:korean_math_app/features/onboarding/application/onboarding_seen_controller.dart';
import 'package:korean_math_app/features/onboarding/data/onboarding_store.dart';
import 'package:korean_math_app/features/onboarding/presentation/onboarding_screen.dart';

/// 메모리 OnboardingStore — 주입한 값을 그대로 돌려준다(플랫폼 채널 회피).
class _FakeOnboardingStore implements OnboardingStore {
  _FakeOnboardingStore({bool seen = false}) : _seen = seen;

  bool _seen;

  @override
  Future<bool> hasSeenOnboarding() async => _seen;

  @override
  Future<void> markOnboardingSeen() async => _seen = true;
}

/// 호출되지 않는 fake — 채팅 화면이 네트워크 없이 빌드만 되도록 둔다.
class _FakeCoachApi extends CoachApi {
  _FakeCoachApi() : super(Dio());

  @override
  Future<CoachResponse> coach(CoachRequest request) async {
    throw UnimplementedError('redirect 테스트는 coach를 호출하지 않습니다.');
  }
}

ProviderContainer _container({required bool seenAtStart}) {
  final container = ProviderContainer(
    overrides: [
      onboardingStoreProvider.overrideWithValue(
        _FakeOnboardingStore(seen: seenAtStart),
      ),
      coachApiProvider.overrideWithValue(_FakeCoachApi()),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  testWidgets('온보딩을 이미 마친 상태 재현 → 재실행 시 온보딩을 건너뛰고 채팅으로 간다', (tester) async {
    final container = _container(seenAtStart: true);
    // runApp 전처럼 복원을 먼저 끝내 첫 redirect 평가가 최신 값을 보게 한다(main.dart 순서 재현).
    await container.read(onboardingSeenControllerProvider.notifier).restore();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const WhyMathApp()),
    );
    await tester.pumpAndSettle();

    expect(find.byType(ChatScreen), findsOneWidget);
    expect(find.byType(OnboardingScreen), findsNothing);
  });

  testWidgets('저장소가 비어 있으면(최초 실행) 온보딩이 여전히 뜬다', (tester) async {
    final container = _container(seenAtStart: false);
    await container.read(onboardingSeenControllerProvider.notifier).restore();

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const WhyMathApp()),
    );
    await tester.pumpAndSettle();

    expect(find.byType(OnboardingScreen), findsOneWidget);
    expect(find.text('답이 아닌, 이유를 묻습니다'), findsOneWidget);
    expect(find.byType(ChatScreen), findsNothing);
  });
}
