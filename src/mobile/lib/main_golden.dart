// 골든 패스 전용 진입점(S6) — 옛 `main.dart`·`app.dart`·`core/router.dart`는 건드리지 않는다.
//
// 실행: flutter run -t lib/main_golden.dart --dart-define=API_URL=http://<서버 IP>:8000

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden/golden_app.dart';

void main() {
  runApp(const ProviderScope(child: GoldenApp()));
}
