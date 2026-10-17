// DiagnosisController 테스트 — CAT 추천→문제 로드·후보없음·에러·중복호출 가드 검증. S1.
//
// 네트워크를 타지 않는다 — problemsApiProvider를 미리 짠 응답(또는 throw)을 돌려주는 fake로
// override한다(ocr_controller_test 답습). 컨트롤러는 순수 상태 전이라 결과를 직접 검증한다.
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/problems/application/diagnosis_controller.dart';
import 'package:korean_math_app/features/problems/data/problem_models.dart';
import 'package:korean_math_app/features/problems/data/problems_api.dart';

/// 미리 짠 결과를 돌려주는 fake — next-problem·problem·diagnosis 각각을 제어한다.
class _FakeProblemsApi extends ProblemsApi {
  _FakeProblemsApi({
    required this.next,
    this.problem,
    this.diagnoses = const <ConceptDiagnosisItem>[],
    this.problemThrows = false,
    this.diagnosisThrows = false,
  }) : super(Dio());

  final NextProblemResponse next;
  final Problem? problem;
  final List<ConceptDiagnosisItem> diagnoses;
  final bool problemThrows;
  final bool diagnosisThrows;

  int nextCalls = 0;

  /// getProblem 호출 횟수·마지막 인자(MOB-24 — 왕복 수를 단언으로 고정한다).
  int problemCalls = 0;
  String? lastProblemId;

  /// getDiagnosisConcepts 호출 횟수(MOB-24 — 문제 화면이 안 쓰는 진단 왕복이 되살아나면 1 이상).
  int diagnosisCalls = 0;

  @override
  Future<NextProblemResponse> getNextProblem({
    bool prioritizeWeakConcepts = false,
  }) async {
    nextCalls++;
    return next;
  }

  @override
  Future<Problem> getProblem(String problemId) async {
    problemCalls++;
    lastProblemId = problemId;
    if (problemThrows) {
      throw DioException(requestOptions: RequestOptions(path: '/x'));
    }
    return problem!;
  }

  @override
  Future<List<ConceptDiagnosisItem>> getDiagnosisConcepts({int? limit}) async {
    diagnosisCalls++;
    if (diagnosisThrows) {
      throw DioException(requestOptions: RequestOptions(path: '/x'));
    }
    return diagnoses;
  }
}

Problem _problem() => const Problem(
      problemId: 'p1',
      sourceType: '자체생성',
      subject: '미적분',
      unitCodes: <String>['CAL'],
      questionText: '문제',
    );

ConceptDiagnosisItem _diag() => const ConceptDiagnosisItem(
      conceptId: 'c1',
      coaching: DiagnosisCoaching(
        focus: 'verify',
        rationale: 'r',
        prompt: 'p',
      ),
    );

ProviderContainer _containerWith(ProblemsApi api) {
  final container = ProviderContainer(
    overrides: [problemsApiProvider.overrideWithValue(api)],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  test('추천 문제 있음: next→problem 2단만 로드하고 왕복 수를 고정한다 (MOB-24)', () async {
    // 진단 목록이 서버에 있어도(픽스처에 1건) 문제 제시 흐름은 그것을 기다리지 않는다.
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problem: _problem(),
      diagnoses: <ConceptDiagnosisItem>[_diag()],
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    final s = container.read(diagnosisControllerProvider);
    expect(s.isLoading, isFalse);
    expect(s.noCandidate, isFalse);
    expect(s.problem?.problemId, 'p1');
    expect(s.nextProblem?.problemId, 'p1');
    expect(s.error, isNull);
    // 왕복 수 — 이 숫자가 곧 학생이 문제가 뜨기까지 기다리는 직렬 왕복 수다.
    expect(api.nextCalls, 1);
    expect(api.problemCalls, 1);
    expect(api.lastProblemId, 'p1', reason: 'getProblem은 next-problem이 준 id로 불려야 한다');
    expect(
      api.diagnosisCalls,
      0,
      reason: '문제 화면이 표시하지 않는 진단 목록 왕복(MOB-24 ①)이 되살아나면 문제 제시가 그만큼 늦어진다',
    );
  });

  test('추천 후보 없음(problem_id null): noCandidate로 종료하고 문제를 로드하지 않는다', () async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: null),
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    final s = container.read(diagnosisControllerProvider);
    expect(s.noCandidate, isTrue);
    expect(s.problem, isNull);
    expect(s.error, isNull);
  });

  test('진단 목록 엔드포인트가 죽어 있어도 문제 제시는 영향받지 않는다 — 부르지도 않는다 (MOB-24)', () async {
    // 예전에는 진단 실패를 삼켜서(graceful) 문제 제시를 살렸다. 이제는 그 엔드포인트를 아예 부르지
    // 않으므로 죽어 있어도 문제 제시와 무관하다 — 이 테스트가 그 성질을 고정한다.
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problem: _problem(),
      diagnosisThrows: true,
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    final s = container.read(diagnosisControllerProvider);
    expect(s.problem?.problemId, 'p1');
    expect(s.error, isNull);
    expect(api.diagnosisCalls, 0);
  });

  test('추천 후보 없음이면 문제 상세도 진단 목록도 부르지 않는다 — next-problem 1회뿐 (MOB-24)', () async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: null),
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    expect(api.nextCalls, 1);
    expect(api.problemCalls, 0);
    expect(api.diagnosisCalls, 0);
  });

  test('문제 로드 실패에서도 진단 목록 왕복은 없다 — 실패 시 낭비 호출이 더 늘지 않는다 (MOB-24)', () async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problemThrows: true,
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    expect(api.nextCalls, 1);
    expect(api.problemCalls, 1);
    expect(api.diagnosisCalls, 0);
    expect(container.read(diagnosisControllerProvider).error, isNotNull);
  });

  test('문제 로드 실패: 에러만 남기고 앱을 막지 않는다', () async {
    final api = _FakeProblemsApi(
      next: const NextProblemResponse(problemId: 'p1'),
      problemThrows: true,
    );
    final container = _containerWith(api);

    await container.read(diagnosisControllerProvider.notifier).load();

    final s = container.read(diagnosisControllerProvider);
    expect(s.error, isNotNull);
    expect(s.problem, isNull);
    expect(s.isLoading, isFalse);
  });
}
