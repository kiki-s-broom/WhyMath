// OCR→코치 핸드오프 네비게이션 위젯 테스트 — 채팅 카메라 진입·인식·풀이 전달 왕복. S1-d.
//
// 최소 GoRouter(채팅 '/'·OCR '/ocr')에 coachApi·ocrApi·imageSourceService를 fake로 주입해
// 네트워크·플랫폼 채널 없이 흐름을 확인한다. OCR 화면은 채팅을 알지 못한 채 `pop(result)`로
// OcrResult만 돌려주고(단방향 chat→ocr), 채팅이 sendOcrSolution으로 매핑·전송한다.
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:korean_math_app/core/router.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';
import 'package:korean_math_app/features/ocr/data/image_source_service.dart';
import 'package:korean_math_app/features/ocr/data/ocr_api.dart';
import 'package:korean_math_app/features/ocr/data/ocr_models.dart';
import 'package:korean_math_app/features/ocr/presentation/ocr_capture_screen.dart';

/// 인식 결과를 코치에게 넘기면 응답 프롬프트를 돌려주는 fake — 요청을 캡처한다.
class _FakeCoachApi extends CoachApi {
  _FakeCoachApi() : super(Dio());

  CoachRequest? lastRequest;

  CoachResponse _canned() => CoachResponse(
        decision: PedagogyDecision(
          polyaStageToAdvance: 'stay',
          prompt: '어느 단계부터 함께 볼까요?',
          system: '시스템(테스트)',
          socraticCategory: '단계분해',
        ),
      );

  @override
  Future<CoachTurnResult> createSession(
    CoachRequest request, {
    String? problemId,
  }) async {
    lastRequest = request;
    return CoachTurnResult(
      dialogueId: 'test-dialogue',
      response: _canned(),
      wh1TurnIndex: 1,
    );
  }
}

/// 미리 짠 인식 결과를 돌려주는 fake OcrApi.
class _FakeOcrApi extends OcrApi {
  _FakeOcrApi() : super(Dio());

  @override
  Future<OcrResult> recognize(MultipartFile image) async => OcrResult(
        regions: [
          OcrRegion(
            bbox: const BBox(x: 0, y: 0, width: 10, height: 10),
            contentType: '수식',
            latex: r'D = b^2 - 4ac',
            confidence: 0.9,
          ),
        ],
        plainLatex: r'D = b^2 - 4ac',
        overallConfidence: 0.9,
        minConfidence: 0.9,
      );
}

/// 항상 한 장을 돌려주는 fake 선택 서비스(취소 없음).
class _FakeImageSourceService implements ImageSourceService {
  @override
  Future<PickedImage?> pick(OcrImageSource source) async => PickedImage(
        bytes: Uint8List.fromList(<int>[1, 2, 3]),
        path: '/tmp/s.jpg',
        fileName: 's.jpg',
      );
}

Widget _app(_FakeCoachApi coach) {
  final router = GoRouter(
    initialLocation: AppRoutes.chatPath,
    routes: [
      GoRoute(
        path: AppRoutes.chatPath,
        builder: (context, state) => const ChatScreen(),
      ),
      GoRoute(
        path: AppRoutes.ocrPath,
        builder: (context, state) => const OcrCaptureScreen(),
      ),
    ],
  );
  return ProviderScope(
    overrides: [
      coachApiProvider.overrideWithValue(coach),
      ocrApiProvider.overrideWithValue(_FakeOcrApi()),
      imageSourceServiceProvider.overrideWithValue(_FakeImageSourceService()),
    ],
    child: MaterialApp.router(routerConfig: router),
  );
}

void main() {
  testWidgets('채팅 카메라 → OCR 인식 → "이 풀이로 코치에게" → 채팅에서 코치 응답', (tester) async {
    final coach = _FakeCoachApi();
    await tester.pumpWidget(_app(coach));
    await tester.pumpAndSettle();

    // 채팅에서 카메라(풀이 사진 보내기)로 OCR 화면에 진입.
    await tester.tap(find.byTooltip('풀이 사진 보내기'));
    await tester.pumpAndSettle();
    expect(find.byType(OcrCaptureScreen), findsOneWidget);

    // 사진 찍기 → 인식 결과·핸드오프 버튼 렌더.
    await tester.tap(find.text('사진 찍기'));
    await tester.pumpAndSettle();
    expect(find.text('이 풀이로 코치에게'), findsOneWidget);

    // 코치에게 넘기면 채팅으로 복귀하고 인식 풀이 전달 + 코치 응답이 보인다.
    await tester.tap(find.text('이 풀이로 코치에게'));
    await tester.pumpAndSettle();

    expect(find.byType(ChatScreen), findsOneWidget);
    expect(find.byType(OcrCaptureScreen), findsNothing);
    // 학생 버블(인식 풀이) — 캐럿 수식(b^2)은 raw가 아니라 Math로 조판된다(S3-39).
    expect(find.byType(Math), findsWidgets);
    expect(find.text(r'D = b^2 - 4ac'), findsNothing);
    // 코치 응답 프롬프트(순수 프로즈)는 평문으로 그대로 보인다.
    expect(find.text('어느 단계부터 함께 볼까요?'), findsOneWidget);

    // 정전 매핑이 코치 요청에 반영됐다(regions 있으니 신뢰도 전달).
    expect(coach.lastRequest!.studentSolution, r'D = b^2 - 4ac');
    expect(coach.lastRequest!.ocrConfidence, 0.9);
  });
}
