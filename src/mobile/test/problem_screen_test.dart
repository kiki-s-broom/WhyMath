// ProblemScreen 위젯 테스트 — 문제 렌더·후보없음 안내·"풀이 시작" 전이·answer 미노출 검증. S1.
//
// problemsApiProvider를 fake로 override해 네트워크 없이 화면 동작을 확인한다(ocr_capture_screen_test
// 답습). go_router 전이가 필요하므로 최소 라우터(/problem·/)로 감싼다. 정서 안전·절대금기 가드로
// 정답·정오 강조가 렌더 텍스트에 없음을 단언한다.
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:korean_math_app/core/router.dart';
import 'package:korean_math_app/features/problems/application/active_problem.dart';
import 'package:korean_math_app/features/problems/data/problem_models.dart';
import 'package:korean_math_app/features/problems/data/problems_api.dart';
import 'package:korean_math_app/features/problems/presentation/problem_screen.dart';

/// 미리 짠 next-problem·problem을 돌려주는 fake.
class _FakeProblemsApi extends ProblemsApi {
  _FakeProblemsApi({required this.next, this.problem}) : super(Dio());

  final NextProblemResponse next;
  final Problem? problem;

  @override
  Future<NextProblemResponse> getNextProblem({
    bool prioritizeWeakConcepts = false,
  }) async =>
      next;

  @override
  Future<Problem> getProblem(String problemId) async => problem!;

  @override
  Future<List<ConceptDiagnosisItem>> getDiagnosisConcepts({int? limit}) async =>
      const <ConceptDiagnosisItem>[];
}

/// ProblemScreen을 최소 라우터(/problem 진입·/ 채팅 placeholder)로 감싼다.
Widget _wrap(ProblemsApi api) {
  final router = GoRouter(
    initialLocation: AppRoutes.problemPath,
    routes: [
      GoRoute(
        path: AppRoutes.problemPath,
        builder: (_, __) => const ProblemScreen(),
      ),
      GoRoute(
        path: AppRoutes.chatPath,
        builder: (_, __) => const Scaffold(body: Text('채팅 화면')),
      ),
    ],
  );
  return ProviderScope(
    overrides: [problemsApiProvider.overrideWithValue(api)],
    child: MaterialApp.router(routerConfig: router),
  );
}

void main() {
  testWidgets('추천 문제를 로드해 발문·맥락·"풀이 시작"을 렌더한다', (tester) async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problem: const Problem(
        problemId: 'p1',
        sourceType: '자체생성',
        subject: '미적분',
        subunit: '합성함수의 미분',
        unitCodes: <String>['CAL'],
        questionText: '다음 함수를 미분하시오.',
      ),
    );
    await tester.pumpWidget(_wrap(api));
    await tester.pumpAndSettle();

    expect(find.text('다음 함수를 미분하시오.'), findsOneWidget);
    expect(find.text('미적분'), findsOneWidget);
    expect(find.text('합성함수의 미분'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '풀이 시작'), findsOneWidget);
  });

  testWidgets('추천 후보 없음이면 코치 대화 안내로 graceful 처리한다', (tester) async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: null),
    );
    await tester.pumpWidget(_wrap(api));
    await tester.pumpAndSettle();

    expect(find.textContaining('추천할 문제가 없어요'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '코치와 대화하기'), findsOneWidget);
  });

  testWidgets('"풀이 시작"은 활성 문제를 세팅하고 코치로 전이한다', (tester) async {
    final container = ProviderContainer(
      overrides: [
        problemsApiProvider.overrideWithValue(
          _FakeProblemsApi(
            next: const NextProblemResponse(problemId: 'p1'),
            problem: const Problem(
              problemId: 'p1',
              sourceType: '자체생성',
              subject: '미적분',
              unitCodes: <String>['CAL'],
              questionText: '문제',
            ),
          ),
        ),
      ],
    );
    addTearDown(container.dispose);

    final router = GoRouter(
      initialLocation: AppRoutes.problemPath,
      routes: [
        GoRoute(
          path: AppRoutes.problemPath,
          builder: (_, __) => const ProblemScreen(),
        ),
        GoRoute(
          path: AppRoutes.chatPath,
          builder: (_, __) => const Scaffold(body: Text('채팅 화면')),
        ),
      ],
    );
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp.router(routerConfig: router),
      ),
    );
    await tester.pumpAndSettle();

    // 진입 시점엔 활성 문제가 비어 있다.
    expect(container.read(activeProblemProvider), isNull);

    await tester.tap(find.widgetWithText(FilledButton, '풀이 시작'));
    await tester.pumpAndSettle();

    // 활성 문제가 세팅되고 채팅 화면으로 전이한다.
    expect(container.read(activeProblemProvider)?.problemId, 'p1');
    expect(find.text('채팅 화면'), findsOneWidget);
  });

  testWidgets('안전: 문제 화면에 정답 문자열이 렌더되지 않는다', (tester) async {
    // Problem 모델은 answer를 담지 않으므로 화면이 정답을 그릴 방법이 없다(구조적 차단 확인).
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problem: const Problem(
        problemId: 'p1',
        sourceType: '자체생성',
        subject: '미적분',
        unitCodes: <String>['CAL'],
        questionText: '문제 발문',
      ),
    );
    await tester.pumpWidget(_wrap(api));
    await tester.pumpAndSettle();

    // 정오 강조·정답 문구가 없다(절대 금기).
    expect(find.textContaining('정답'), findsNothing);
    expect(find.textContaining('틀렸'), findsNothing);
  });

  // ── S3-35: 객관식 보기 = 세로 번호목록 동결 ──────────────────────────────
  //
  // 이 UI는 이미 main에 구현돼 있었으나(_ProblemView의 choices 루프 + _circledNumber)
  // 어떤 테스트도 동결하지 않아 조용히 회귀할 수 있었다 — 예컨대 누가 Wrap/Row로 바꿔
  // 가로 배치가 되거나, 번호 라벨을 떼거나, 정오 색을 입혀도 스위트는 green이었다.
  // 아래 4건이 그 세 축(번호·세로·중립)을 각각 잡는다.
  group('객관식 보기 렌더 (S3-35)', () {
    /// 보기 [choices]를 가진 객관식 문제 화면을 띄운다.
    Future<void> pumpWithChoices(
      WidgetTester tester,
      List<String> choices,
    ) async {
      final api = _FakeProblemsApi(
        next: const NextProblemResponse(problemId: 'p1'),
        problem: Problem(
          problemId: 'p1',
          sourceType: '자체생성',
          subject: '수학I',
          unitCodes: const <String>['ALG'],
          questionText: '다음 중 옳은 것은?',
          choices: choices,
        ),
      );
      await tester.pumpWidget(_wrap(api));
      await tester.pumpAndSettle();
    }

    testWidgets('보기는 ①②③ 번호가 붙어 렌더된다', (tester) async {
      await pumpWithChoices(tester, <String>['둘', '넷', '여섯']);

      expect(find.text('① 둘'), findsOneWidget);
      expect(find.text('② 넷'), findsOneWidget);
      expect(find.text('③ 여섯'), findsOneWidget);
    });

    testWidgets('보기는 가로가 아니라 세로로 쌓인다', (tester) async {
      await pumpWithChoices(tester, <String>['둘', '넷', '여섯']);

      // Wrap/Row로 바뀌면 y가 같고 x가 증가한다 — 이 단언이 그 회귀를 잡는다.
      final double y1 = tester.getTopLeft(find.text('① 둘')).dy;
      final double y2 = tester.getTopLeft(find.text('② 넷')).dy;
      final double y3 = tester.getTopLeft(find.text('③ 여섯')).dy;
      expect(y2, greaterThan(y1), reason: '②는 ① 아래에 놓여야 한다(세로 목록)');
      expect(y3, greaterThan(y2), reason: '③은 ② 아래에 놓여야 한다(세로 목록)');
    });

    testWidgets('보기가 없는 문제(주관식)에는 번호 라벨이 없다 — 변별력', (tester) async {
      // 번호 단언이 "항상 통과"가 아님을 반대 사례로 보인다.
      final api = _FakeProblemsApi(
        next: const NextProblemResponse(problemId: 'p1'),
        problem: const Problem(
          problemId: 'p1',
          sourceType: '자체생성',
          subject: '수학I',
          unitCodes: <String>['ALG'],
          questionText: '값을 구하시오.',
        ),
      );
      await tester.pumpWidget(_wrap(api));
      await tester.pumpAndSettle();

      expect(find.textContaining('①'), findsNothing);
    });

    testWidgets('보기끼리 색이 달라지지 않는다 — 정오 강조 금기(절대 금기)', (tester) async {
      await pumpWithChoices(tester, <String>['둘', '넷', '여섯']);

      // "정오 강조 없음"의 실질은 *보기마다 색이 갈리지 않는 것*이다(M3 bodyLarge는
      // 기본 onSurface 색을 이미 갖고 있으므로 color==null 단언은 성립하지 않는다 — 실측).
      // 정답 초록·오답 빨강 같은 차등 강조가 들어오면 아래 집합의 크기가 1을 넘는다.
      final Set<Color?> colors = <Color?>{
        for (final String label in <String>['① 둘', '② 넷', '③ 여섯'])
          tester.widget<Text>(find.text(label)).style?.color,
      };
      expect(
        colors,
        hasLength(1),
        reason: '보기마다 색이 다르다 — 정오 차등 강조로 읽힌다(정서 안전 금기 위반)',
      );

      // 그 단일 색이 error 롤(경고색)이어서도 안 된다 — 보기는 경고 대상이 아니다.
      final ThemeData theme = Theme.of(tester.element(find.text('① 둘')));
      expect(
        colors.single,
        isNot(theme.colorScheme.error),
        reason: '보기 전체를 error 롤로 칠하는 것도 부정 피드백 강화다',
      );
    });
  });
}
