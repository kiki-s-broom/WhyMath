// OnboardingSeenController + SharedPreferencesOnboardingStore 단위 테스트(MOB-11).
//
// shared_preferences 공식 테스트 경로(`setMockInitialValues`)로 실제 저장소 왕복을
// 검증한다(플랫폼 채널을 타지 않는 인메모리 구현으로 전환됨 — 패키지 공식 테스트 지원).
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/onboarding/application/onboarding_seen_controller.dart';
import 'package:korean_math_app/features/onboarding/data/onboarding_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

ProviderContainer _container() {
  final container = ProviderContainer();
  addTearDown(container.dispose);
  return container;
}

void main() {
  setUp(() {
    // 매 테스트 빈 저장소로 시작(테스트 간 격리).
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  group('SharedPreferencesOnboardingStore', () {
    test('처음엔 false, markOnboardingSeen 후엔 true를 읽는다(왕복)', () async {
      const store = SharedPreferencesOnboardingStore();
      expect(await store.hasSeenOnboarding(), isFalse);

      await store.markOnboardingSeen();

      expect(await store.hasSeenOnboarding(), isTrue);
    });
  });

  group('OnboardingSeenController', () {
    test('build() 기본값은 false(온보딩 노출)', () {
      final container = _container();
      expect(container.read(onboardingSeenControllerProvider), isFalse);
    });

    test('restore()는 저장된 플래그(true)를 상태로 올린다', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        'onboarding_seen': true,
      });
      final container = _container();

      await container.read(onboardingSeenControllerProvider.notifier).restore();

      expect(container.read(onboardingSeenControllerProvider), isTrue);
    });

    test('restore()는 저장소가 비어 있으면 false를 유지한다(최초 실행)', () async {
      final container = _container();

      await container.read(onboardingSeenControllerProvider.notifier).restore();

      expect(container.read(onboardingSeenControllerProvider), isFalse);
    });

    test('markSeen()은 상태를 즉시 true로 올리고 영속한다', () async {
      final container = _container();
      final notifier = container.read(onboardingSeenControllerProvider.notifier);

      await notifier.markSeen();

      expect(container.read(onboardingSeenControllerProvider), isTrue);

      // 새 컨테이너(=재실행 재현)에서 restore()가 영속된 값을 다시 읽는다.
      final restarted = _container();
      await restarted
          .read(onboardingSeenControllerProvider.notifier)
          .restore();
      expect(restarted.read(onboardingSeenControllerProvider), isTrue);
    });
  });
}
