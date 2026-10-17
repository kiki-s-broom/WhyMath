// 온보딩 "봤음" 플래그 영속 — shared_preferences 래퍼. 복귀 지원 최소 착지(MOB-11).
//
// 경계(CLAUDE.md): 이 플래그는 토큰·PII가 아니라 "이 기기에서 온보딩 안내를 이미 봤다"는
// 단순 UI 상태다 — [TokenStore](OS 보안 저장소)와 달리 민감정보가 아니므로 shared_preferences로
// 충분하다(과보안 회피). 값 자체는 학생을 식별하지 않는다(기기 단위 플래그).
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 온보딩 노출 여부 저장소 경계 — 읽기·쓰기.
abstract interface class OnboardingStore {
  /// 이 기기에서 온보딩을 이미 마쳤는지(건너뛰기·시작하기 공통 완료 지점 기준).
  Future<bool> hasSeenOnboarding();

  /// 온보딩을 마쳤음을 영속 기록한다(다음 실행부터 재노출하지 않는다).
  Future<void> markOnboardingSeen();
}

/// shared_preferences 기반 실 구현.
///
/// `SharedPreferences.getInstance()`는 내부적으로 캐시되므로 매 호출마다 새로 얻어도
/// 비용이 낮다(인스턴스를 provider 생성 시점에 미리 묶어둘 필요가 없다 — 플랫폼 채널
/// 준비 전 이른 초기화를 피한다).
class SharedPreferencesOnboardingStore implements OnboardingStore {
  const SharedPreferencesOnboardingStore();

  static const _key = 'onboarding_seen';

  @override
  Future<bool> hasSeenOnboarding() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_key) ?? false;
  }

  @override
  Future<void> markOnboardingSeen() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_key, true);
  }
}

/// 앱 전역 온보딩 저장소 provider — 실 구현([SharedPreferencesOnboardingStore]) 주입.
final onboardingStoreProvider = Provider<OnboardingStore>(
  (ref) => const SharedPreferencesOnboardingStore(),
);
