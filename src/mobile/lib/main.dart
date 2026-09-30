// 앱 진입점 — Riverpod 컨테이너를 만들고 인증 세션·온보딩 상태를 복원한 뒤 [WhyMathApp]을 실행한다.
//
// 시작 시 보안 저장소의 토큰으로 세션을 복원(OAuth-c2b)하고 온보딩 "봤음" 플래그를 복원(MOB-11)한
// *후* 첫 프레임을 그린다 — 그래야 라우터 redirect 가드가 첫 평가에서 두 상태를 즉시 보고 복원된
// 세션·이미 온보딩을 마친 기기를 채팅으로 보낸다(로딩 프레임·refreshListenable 없이 결정론적).
// 마지막 대화 이어하기(MOB-11)는 네트워크 호출(`GET /v1/coach/sessions/{id}`)이라 앱 시작을
// 막지 않는다 — 백그라운드로 진행하고, 완료되면 채팅 화면이 상태 갱신으로 메시지를 채운다.
// 컨테이너는 앱 수명 동안 소유하므로 dispose하지 않고 [UncontrolledProviderScope]로 트리에 넘긴다.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'features/auth/application/auth_controller.dart';
import 'features/chat/application/chat_controller.dart';
import 'features/onboarding/application/onboarding_seen_controller.dart';

Future<void> main() async {
  // 플러그인(보안 저장소·shared_preferences) 사용 전 바인딩 초기화 — runApp 전 비동기 작업의 전제.
  WidgetsFlutterBinding.ensureInitialized();
  final container = ProviderContainer();
  // 저장된 토큰이 있으면 인증 상태로 복원(없거나 오류면 미인증 — graceful).
  await container.read(authControllerProvider.notifier).restore();
  // 온보딩을 이미 마친 기기면 redirect가 온보딩을 건너뛰도록 상태를 복원(MOB-11).
  await container.read(onboardingSeenControllerProvider.notifier).restore();
  // 마지막 대화 이어하기 — 네트워크 호출이라 첫 프레임을 막지 않고 백그라운드로 넘긴다.
  // 인증 복원 뒤에 시작해야 인터셉터가 Bearer를 붙인다(미인증이면 서버 401 → 조용히 빈 대화).
  unawaited(container.read(chatControllerProvider.notifier).restoreLastDialogue());
  runApp(
    UncontrolledProviderScope(container: container, child: const WhyMathApp()),
  );
}
