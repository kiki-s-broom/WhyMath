// 골든 패스 앱 껍데기 — 기본 Material 앱 + 화면 위 오류 한 줄(S6).
//
// 옛 `app.dart`·`core/router.dart`는 쓰지 않는다(진입점 분리). 화면 전환은 라우터 없이
// 상태로 정한다: 세션이 없으면 닉네임 화면, 있으면 문제 화면.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden_state.dart';
import 'nickname_screen.dart';
import 'problem_screen.dart';

class GoldenApp extends StatelessWidget {
  const GoldenApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'WhyMath Golden',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
      // 모든 화면 위에 오류 한 줄을 얹는다(서버 꺼짐·타임아웃이어도 앱은 그대로).
      builder: (BuildContext context, Widget? child) =>
          _ErrorBannerFrame(child: child ?? const SizedBox.shrink()),
      home: const _GoldenHome(),
    );
  }
}

/// 세션 유무로 화면을 고른다.
class _GoldenHome extends ConsumerWidget {
  const _GoldenHome();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool started =
        ref.watch(goldenProvider.select((GoldenState s) => s.sessionId != null));
    return started ? const ProblemScreen() : const NicknameScreen();
  }
}

/// 오류 문구가 있으면 화면 맨 위에 한 줄로 보여준다.
class _ErrorBannerFrame extends ConsumerWidget {
  const _ErrorBannerFrame({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final String? error =
        ref.watch(goldenProvider.select((GoldenState s) => s.error));
    if (error == null) return child;
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Column(
      children: <Widget>[
        Material(
          color: colors.errorContainer,
          child: SafeArea(
            bottom: false,
            child: SizedBox(
              width: double.infinity,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Text(
                  error,
                  key: const Key('golden_error_banner'),
                  style: TextStyle(color: colors.onErrorContainer),
                ),
              ),
            ),
          ),
        ),
        // 배너가 상태 표시줄 여백을 이미 썼으므로 아래 화면에서는 위 여백을 뺀다.
        Expanded(
          child: MediaQuery.removePadding(
            context: context,
            removeTop: true,
            child: child,
          ),
        ),
      ],
    );
  }
}
