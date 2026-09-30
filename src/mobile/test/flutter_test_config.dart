// 전역 테스트 설정 — `flutter test`가 test/ 트리 전체 실행 전에 자동으로 이 훅을 태운다.
//
// 왜 필요한가(MOB-11): `shared_preferences`는 실 플랫폼 채널이 없는 `flutter test` 환경에서
// mock을 설정하지 않으면 *예외를 던지지 않고 영영 완료되지 않는다*(flutter_secure_storage와
// 달리 MissingPluginException으로 빠르게 실패하지 않음 — 실측: pumpAndSettle이 무한 대기하며
// 타임아웃). `onboardingStoreProvider`·`dialogueStoreProvider`를 override하지 않는 기존 위젯
// 테스트(chat_screen_test.dart 등)가 전부 이 문제에 걸리므로, 개별 테스트를 고치는 대신
// 공식 지원 경로(`SharedPreferences.setMockInitialValues`)로 스위트 전체에 인메모리 구현을
// 깐다 — 빈 값이라 "저장된 게 없다"는 기존 동작(온보딩 노출·복원할 대화 없음)과 그대로 합치한다.
// 특정 테스트가 다른 초기값이 필요하면 그 테스트의 setUp에서 다시 호출해 덮어쓰면 된다
// (마지막 호출이 우선 — `onboarding_seen_controller_test.dart` 참고).
import 'dart:async';

import 'package:shared_preferences/shared_preferences.dart';

Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  await testMain();
}
