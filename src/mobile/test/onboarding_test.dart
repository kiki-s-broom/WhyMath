// 온보딩·라우터 위젯 테스트 — go_router 셸의 첫 진입(온보딩)·목표 입력 폼·학습 루프 전이 검증.
//
// 앱 첫 진입은 온보딩이다(initialLocation='/onboarding'). 안내 3페이지 뒤에 목표 입력 폼
// 페이지가 붙고(S1-c), "시작하기"로 입력을 전송한 뒤 학습 루프(진단→문제 `/problem`)로 도달한다.
// 문제 화면은 problemsApiProvider를, 폼은 userApiProvider를 읽으므로 네트워크 없이 빌드되도록
// fake로 override한다(이 테스트는 실제 네트워크 호출을 하지 않는다).
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/app.dart';
import 'package:korean_math_app/features/onboarding/data/onboarding_store.dart';
import 'package:korean_math_app/features/onboarding/data/user_api.dart';
import 'package:korean_math_app/features/problems/data/problem_models.dart';
import 'package:korean_math_app/features/problems/data/problems_api.dart';
import 'package:korean_math_app/features/problems/presentation/problem_screen.dart';

/// 결정론 fake — 온보딩 완료 후 진입하는 문제 화면이 네트워크 없이 문제를 제시하도록 한다.
class _FakeProblemsApi extends ProblemsApi {
  _FakeProblemsApi() : super(Dio());

  @override
  Future<NextProblemResponse> getNextProblem({
    bool prioritizeWeakConcepts = false,
  }) async {
    return const NextProblemResponse(
      problemId: '11111111-1111-1111-1111-111111111111',
      theta: 0.0,
      measurementSufficient: false,
    );
  }

  @override
  Future<Problem> getProblem(String problemId) async {
    return Problem(
      problemId: problemId,
      sourceType: '자체생성',
      subject: '미적분',
      subunit: '합성함수의 미분',
      unitCodes: const <String>['CAL-DIFF-COMP'],
      questionText: '다음 함수를 미분하시오.',
    );
  }

  @override
  Future<List<ConceptDiagnosisItem>> getDiagnosisConcepts({int? limit}) async {
    return const <ConceptDiagnosisItem>[];
  }
}

/// 전송 여부만 기록하는 fake — 빈 폼이면 patchMe가 호출되지 않는다(선택 입력).
class _FakeUserApi extends UserApi {
  _FakeUserApi() : super(Dio());

  int callCount = 0;

  @override
  Future<void> patchMe(Map<String, dynamic> body) async {
    callCount++;
  }
}

/// 메모리 OnboardingStore — 완료 지점이 "봤음"을 영속하는지(MOB-11) 기록한다.
class _FakeOnboardingStore implements OnboardingStore {
  bool seen = false;

  @override
  Future<bool> hasSeenOnboarding() async => seen;

  @override
  Future<void> markOnboardingSeen() async => seen = true;
}

Widget _app({OnboardingStore? onboardingStore}) {
  return ProviderScope(
    overrides: [
      problemsApiProvider.overrideWithValue(_FakeProblemsApi()),
      userApiProvider.overrideWithValue(_FakeUserApi()),
      onboardingStoreProvider.overrideWithValue(onboardingStore ?? _FakeOnboardingStore()),
    ],
    child: const WhyMathApp(),
  );
}

/// 안내 페이지(3개)를 모두 지나 목표 입력 폼 페이지까지 "다음"으로 넘긴다.
Future<void> _advanceToForm(WidgetTester tester) async {
  for (var i = 0; i < 3; i++) {
    await tester.tap(find.widgetWithText(FilledButton, '다음'));
    await tester.pumpAndSettle();
  }
}

void main() {
  testWidgets('첫 진입은 온보딩 — 메타인지 안내가 보인다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    // 첫 페이지(브랜드·답 미루기 안내)와 진행 버튼이 보인다. 아직 문제 화면은 아니다.
    expect(find.text('답이 아닌, 이유를 묻습니다'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '다음'), findsOneWidget);
    expect(find.byType(ProblemScreen), findsNothing);
  });

  testWidgets('안내 3페이지 뒤 목표 입력 폼과 "시작하기"가 나온다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    // 페이지 1 → 2.
    await tester.tap(find.widgetWithText(FilledButton, '다음'));
    await tester.pumpAndSettle();
    expect(find.text('막혀도 괜찮아요'), findsOneWidget);

    // 페이지 2 → 3(안내 마지막). 아직 폼이 아니라 "다음"이 유지된다.
    await tester.tap(find.widgetWithText(FilledButton, '다음'));
    await tester.pumpAndSettle();
    expect(find.text('풀이를 함께 검산해요'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '다음'), findsOneWidget);

    // 페이지 3 → 폼(마지막). 목표 입력 필드와 "시작하기"가 나온다.
    await tester.tap(find.widgetWithText(FilledButton, '다음'));
    await tester.pumpAndSettle();
    expect(find.text('목표를 알려 주세요'), findsOneWidget);
    expect(find.text('목표 등급'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '시작하기'), findsOneWidget);
  });

  testWidgets('"시작하기"를 누르면 학습 루프(문제 화면)로 전이한다(빈 폼도 진행)', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    await _advanceToForm(tester);

    // 폼을 비운 채 "시작하기" → 문제 화면(`/problem`)으로 이동(선택 입력이라 전송 없이 진행).
    await tester.tap(find.widgetWithText(FilledButton, '시작하기'));
    await tester.pumpAndSettle();

    expect(find.byType(ProblemScreen), findsOneWidget);
    // CAT 추천 문제가 제시된다(전이 성공 + 로드 확인).
    expect(find.text('다음 함수를 미분하시오.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '풀이 시작'), findsOneWidget);
  });

  testWidgets('"건너뛰기"를 누르면 바로 학습 루프(문제 화면)로 전이한다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    // 첫 페이지의 "건너뛰기" → 문제 화면으로 이동.
    await tester.tap(find.text('건너뛰기'));
    await tester.pumpAndSettle();

    expect(find.byType(ProblemScreen), findsOneWidget);
  });

  testWidgets('좁은 세로 제약(키보드 노출 상당)에서도 안내 페이지가 넘치지 않는다', (tester) async {
    // 실기기 회귀 가드: 키보드가 올라와 세로가 좁아진 상황(실측 h≈200)에서
    // _OnboardingPageView Column이 RenderFlex overflow를 내던 결함(35px 줄무늬가
    // 시연 녹화에 찍힘). 스크롤 강등으로 예외가 없어야 한다 — overflow가 나면
    // 테스트 프레임워크가 예외로 실패시킨다.
    tester.view.physicalSize = const Size(1080, 500);
    tester.view.devicePixelRatio = 2.5; // 논리 432x200 — 실측 제약 재현.
    addTearDown(tester.view.reset);

    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    // 예외 없이 렌더되고 첫 페이지 콘텐츠가 존재한다(스크롤 안쪽).
    expect(tester.takeException(), isNull);
    expect(find.text('답이 아닌, 이유를 묻습니다'), findsOneWidget);
  });

  testWidgets('"건너뛰기" 완료 지점은 온보딩 "봤음"을 영속한다(MOB-11 — 다음 실행부터 재노출 안 함)', (tester) async {
    final store = _FakeOnboardingStore();
    await tester.pumpWidget(_app(onboardingStore: store));
    await tester.pumpAndSettle();
    expect(store.seen, isFalse);

    await tester.tap(find.text('건너뛰기'));
    await tester.pumpAndSettle();

    expect(store.seen, isTrue);
  });

  testWidgets('"시작하기" 완료 지점도 온보딩 "봤음"을 영속한다(MOB-11)', (tester) async {
    final store = _FakeOnboardingStore();
    await tester.pumpWidget(_app(onboardingStore: store));
    await tester.pumpAndSettle();
    await _advanceToForm(tester);

    await tester.tap(find.widgetWithText(FilledButton, '시작하기'));
    await tester.pumpAndSettle();

    expect(store.seen, isTrue);
    expect(find.byType(ProblemScreen), findsOneWidget);
  });
}
