// 온보딩 "봤음" 상태 컨트롤러 — 영속 플래그를 읽어 라우터 redirect가 참조할 in-memory
// 상태로 올린다. 복귀 지원 최소 착지(MOB-11).
//
// 경계(CLAUDE.md): `AuthController.restore()`와 동형 패턴이다 — 앱 시작 시 저장소를 한 번
// 읽어 상태를 올리고(`restore`), 온보딩 완료 지점에서 상태를 즉시 반영한 뒤 영속 저장을
// 시도한다(`markSeen`). 저장소 오류(테스트의 MissingPluginException 포함)는 삼켜 앱이
// 죽지 않게 한다 — 최악의 경우도 "온보딩이 한 번 더 보이는" 수준의 graceful 열화일 뿐이다.
import 'package:flutter/foundation.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../data/onboarding_store.dart';

part 'onboarding_seen_controller.g.dart';

/// 온보딩 노출 여부를 관리하는 Riverpod Notifier.
@riverpod
class OnboardingSeenController extends _$OnboardingSeenController {
  @override
  bool build() => false; // 기본값=미확인 → 온보딩 노출(안전 기본값·신규 설치와 동일하게 취급).

  /// 앱 시작 시 저장된 플래그를 읽어 상태에 반영한다(라우터 redirect가 이 상태를 읽는다).
  ///
  /// `main()`에서 `runApp` 전에 한 번 호출한다(`AuthController.restore()`와 같은 타이밍
  /// 계약) — 그래야 첫 redirect 평가가 복귀 여부를 즉시 안다(로딩 프레임 없이 결정론적).
  Future<void> restore() async {
    try {
      final seen = await ref.read(onboardingStoreProvider).hasSeenOnboarding();
      state = seen;
    } on Object catch (e) {
      // 저장소 미가용·오류 → 미확인(기본값=false) 유지, 온보딩이 그대로 보인다(앱 안 죽음).
      // 침묵 실패 금지(CLAUDE.md) — 예외 타입명만 남긴다.
      debugPrint('온보딩 플래그 복원 실패(${e.runtimeType}) — 온보딩을 다시 보여준다.');
    }
  }

  /// 온보딩 완료 지점(건너뛰기·시작하기 공통)에서 호출한다.
  ///
  /// 상태를 *먼저* true로 올려(동기) 곧바로 이어지는 `context.go` 재평가가 즉시 반영되게
  /// 하고, 영속 저장은 그 뒤 시도한다 — 저장 실패해도 이번 세션 이동은 막지 않는다(이번
  /// 실행은 이미 seen이므로 재노출 없음, 다음 설치·저장소 초기화 시에만 다시 보일 수 있음).
  Future<void> markSeen() async {
    state = true;
    try {
      await ref.read(onboardingStoreProvider).markOnboardingSeen();
    } on Object catch (e) {
      // 저장 실패 — graceful(다음 재실행에서만 영향, 이번 세션은 이미 seen).
      debugPrint('온보딩 플래그 저장 실패(${e.runtimeType}) — 다음 실행에 온보딩이 다시 보일 수 있다.');
    }
  }
}
