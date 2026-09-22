// 채팅 화면 위젯 테스트 — 입력·전송 후 코치 버블·소크라테스 배지·로딩/에러 렌더 검증.
//
// coachApiProvider를 fake로 override해 네트워크 없이 화면 동작을 확인한다.
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/data/coach_models.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';
import 'package:korean_math_app/features/problems/application/active_problem.dart';
import 'package:korean_math_app/features/problems/data/problem_models.dart';

/// 미리 짠 응답을 돌려주는 fake(또는 throw) — 위젯 테스트용.
///
/// [lastRequest]에 마지막 요청을 기록한다 — 단계 리스트 편집기의 조인 결과가
/// 컨트롤러 계약(`student_input`·`solution_steps`) 그대로 전달되는지 검증용.
class _FakeCoachApi extends CoachApi {
  _FakeCoachApi({this.response, this.shouldThrow = false}) : super(Dio());

  final CoachResponse? response;
  final bool shouldThrow;

  /// 마지막으로 받은 요청(조인·줄 분해 왕복 검증용).
  CoachRequest? lastRequest;

  DioException _fail() => DioException(
        requestOptions: RequestOptions(path: '/v1/coach/sessions'),
        error: '네트워크 실패(테스트)',
      );

  @override
  Future<CoachTurnResult> createSession(
    CoachRequest request, {
    String? problemId,
  }) async {
    lastRequest = request;
    if (shouldThrow) {
      throw _fail();
    }
    return CoachTurnResult(
      dialogueId: 'test-dialogue',
      response: response!,
      wh1TurnIndex: 1,
    );
  }

  @override
  Future<CoachTurnResult> addTurn(
    String dialogueId,
    CoachRequest request,
  ) async {
    lastRequest = request;
    if (shouldThrow) {
      throw _fail();
    }
    return CoachTurnResult(
      dialogueId: dialogueId,
      response: response!,
      wh1TurnIndex: 2,
    );
  }
}

CoachResponse _response({
  String prompt = '먼저 무엇이 주어졌는지 정리해 볼까요?',
  String socraticCategory = '조건확인',
  SolutionCoaching? coaching,
}) {
  return CoachResponse(
    decision: PedagogyDecision(
      polyaStageToAdvance: 'stay',
      prompt: prompt,
      system: '시스템(테스트)',
      socraticCategory: socraticCategory,
    ),
    solutionCoaching: coaching,
  );
}

Widget _wrap(CoachApi fake) {
  return ProviderScope(
    overrides: [coachApiProvider.overrideWithValue(fake)],
    child: const MaterialApp(home: ChatScreen()),
  );
}

/// 활성 문제를 함께 주입해 감싸는 헬퍼(객관식 선택지 버튼 테스트용·S3-12).
Widget _wrapWithProblem(CoachApi fake, Problem problem) {
  return ProviderScope(
    overrides: [
      coachApiProvider.overrideWithValue(fake),
      activeProblemProvider.overrideWith((ref) => problem),
    ],
    child: const MaterialApp(home: ChatScreen()),
  );
}

void main() {
  testWidgets('슬로건과 빈 안내가 보인다', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    expect(find.text('WhyMath'), findsOneWidget);
    expect(find.text('답이 아닌, 이유를 묻는 수학'), findsOneWidget);
    expect(find.text('어떤 문제를 함께 생각해 볼까요?'), findsOneWidget);
  });

  testWidgets('입력·전송 후 코치 버블과 소크라테스 배지가 렌더된다', (tester) async {
    await tester.pumpWidget(
      _wrap(
        _FakeCoachApi(
          response: _response(
            prompt: '주어진 조건을 먼저 적어 볼까요?',
            socraticCategory: '조건확인',
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '판별식이 헷갈려요');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    // 학생 입력·코치 발화·배지가 모두 보인다.
    expect(find.text('판별식이 헷갈려요'), findsOneWidget);
    expect(find.text('주어진 조건을 먼저 적어 볼까요?'), findsOneWidget);
    expect(find.text('조건확인'), findsOneWidget);
  });

  testWidgets('코치 응답에 검산 신호가 있으면 채팅에 신호 카드가 노출된다', (tester) async {
    await tester.pumpWidget(
      _wrap(
        _FakeCoachApi(
          response: _response(
            prompt: '같이 한 번 더 살펴볼까요?',
            socraticCategory: '검증',
            coaching: const SolutionCoaching(
              // trigger.prompt는 비워 추가 코치 버블을 만들지 않는다(카드만 검증).
              trigger: CoachingTrigger(
                focus: 'verify',
                rationale: '근거(테스트)',
                prompt: '',
                socraticCategory: '검증',
              ),
              arithmeticError: true,
              errorKind: 'arithmetic',
            ),
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '이 계산 맞나요?');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    // 코치 버블 아래 신호 카드(검산 cue)가 채팅에 보인다.
    expect(find.textContaining('스스로 검산해볼까?'), findsOneWidget);
    // 답 미루기 — "틀렸다" 단정은 노출하지 않는다.
    expect(find.textContaining('틀렸'), findsNothing);
  });

  testWidgets('풀이 단계 모드에서 단계들을 묶어 제출하면 신호 카드가 노출된다',
      (tester) async {
    await tester.pumpWidget(
      _wrap(
        _FakeCoachApi(
          response: _response(
            prompt: '같이 한 번 더 살펴볼까요?',
            socraticCategory: '검증',
            coaching: const SolutionCoaching(
              trigger: CoachingTrigger(
                focus: 'verify',
                rationale: '근거(테스트)',
                prompt: '', // 추가 버블 없이 신호 카드만 검증.
                socraticCategory: '검증',
              ),
              arithmeticError: false,
              solutionVerification: SolutionVerificationResult(
                nCorrect: 1,
                nIncorrect: 1,
                nUnverifiable: 0,
                nTransitions: 2,
                unverifiedRatio: 0,
                firstIncorrectIndex: 1,
                hasIncorrect: true,
              ),
            ),
          ),
        ),
      ),
    );

    // 풀이 단계 모드로 토글한다(토글 아이콘 → 단계 리스트 편집기).
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 초기 2개 필드에 "단계 추가"로 하나 더한 3개 단계를 입력하고 "3단계 제출"로 묶어
    // 전송한다(실기기 실측: 묶음 제출이어야 verify 전이가 생겨 correct/incorrect가
    // 결정된다 — 3단계=전이 2개가 위 가짜 응답 nTransitions: 2와 정합).
    await tester.tap(find.text('단계 추가'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(0), 'a');
    await tester.enterText(find.byType(TextField).at(1), 'b');
    await tester.enterText(find.byType(TextField).at(2), 'c');
    await tester.pump();
    await tester.tap(find.text('3단계 제출'));
    await tester.pumpAndSettle();

    // 단계 검증 요약 신호 카드가 노출된다(전이 수 표시).
    expect(find.textContaining('단계 확인'), findsOneWidget);
    expect(find.textContaining('다시 볼 단계가 있어요'), findsOneWidget);
    // 답 미루기 — "틀렸다" 단정은 노출하지 않는다.
    expect(find.textContaining('틀렸'), findsNothing);
  });

  testWidgets('단계 리스트 편집기 — 단계 추가/삭제가 동작하고 마지막 1개는 지울 수 없다',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 초기 2개 단계 필드 — 묶음 제출(최소 전이 1개)이 기본 모양임을 시각적으로 유도한다.
    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.text('예: 2x+3=7'), findsOneWidget); // 입력 형태 예시 힌트(MOB-05).

    // "단계 추가" → 3개.
    await tester.tap(find.text('단계 추가'));
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNWidgets(3));

    // 단계 삭제 → 다시 2개. (추가 직후 단계 영역이 아래로 스크롤되므로
    // 항상 화면에 보이는 *마지막* 행의 삭제 버튼을 탭한다.)
    await tester.tap(find.byIcon(Icons.remove_circle_outline).last);
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNWidgets(2));

    // 1개까지 줄이면 — 마지막 단계의 삭제 버튼은 비활성(빈 편집기 방지).
    await tester.tap(find.byIcon(Icons.remove_circle_outline).last);
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNWidgets(1));
    final deleteButton = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.remove_circle_outline),
    );
    expect(deleteButton.onPressed, isNull);

    // 대화로 나갔다 돌아오면 편집기가 초기 상태(2개 필드)로 리셋된다(토글=입력 비움과 동형).
    await tester.tap(find.byIcon(Icons.chat_bubble_outline));
    await tester.pump();
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();
    expect(find.byType(TextField), findsNWidgets(2));
  });

  testWidgets('단계 필드 Enter(다음) — 마지막 필드에서 누르면 새 단계가 추가된다',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 마지막(2번째) 필드에 입력 후 Enter(next) → 3번째 필드가 자연스럽게 추가된다.
    await tester.enterText(find.byType(TextField).at(1), '마지막 단계');
    await tester.testTextInput.receiveAction(TextInputAction.next);
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNWidgets(3));
  });

  testWidgets('"N단계 제출" 라벨이 실시간 반영되고, 1단계뿐이면 묶음 안내가 보인다',
      (tester) async {
    const helper = '단계를 나눠 적으면 풀이를 확인해 드릴 수 있어요';
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 전부 비어 있으면 "풀이 제출"(비활성) — 보낼 단계가 없다.
    expect(find.text('풀이 제출'), findsOneWidget);
    expect(find.text(helper), findsNothing);
    final emptySubmit = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '풀이 제출'),
    );
    expect(emptySubmit.onPressed, isNull);

    // 1단계 입력 → "1단계 제출" + 부드러운 묶음 안내(질책 표현 없음·제출은 허용).
    await tester.enterText(find.byType(TextField).at(0), '판별식을 계산한다');
    await tester.pump();
    expect(find.text('1단계 제출'), findsOneWidget);
    expect(find.text(helper), findsOneWidget);
    final oneStepSubmit = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '1단계 제출'),
    );
    expect(oneStepSubmit.onPressed, isNotNull); // 1단계 제출도 막지 않는다.

    // 2단계 입력 → "2단계 제출", 안내는 사라진다.
    await tester.enterText(find.byType(TextField).at(1), 'D>0이므로 근이 두 개');
    await tester.pump();
    expect(find.text('2단계 제출'), findsOneWidget);
    expect(find.text(helper), findsNothing);

    // 지우면 → 다시 "1단계 제출"(실시간 반영).
    await tester.enterText(find.byType(TextField).at(1), '');
    await tester.pump();
    expect(find.text('1단계 제출'), findsOneWidget);
  });

  testWidgets('제출은 비어있지 않은 단계들만 줄바꿈으로 합쳐 sendSolution 경로로 보낸다',
      (tester) async {
    final fake = _FakeCoachApi(response: _response());
    await tester.pumpWidget(_wrap(fake));

    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // "단계 추가"로 3개 필드를 만든 뒤 단계 1·3만 채우고 2는 비워 둔다
    // (초기 필드는 2개) — 빈 단계는 제출에서 제외된다.
    await tester.tap(find.text('단계 추가'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(0), '식을 정리한다');
    await tester.enterText(find.byType(TextField).at(2), '근을 구한다');
    await tester.pump();
    expect(find.text('2단계 제출'), findsOneWidget);

    await tester.tap(find.text('2단계 제출'));
    await tester.pumpAndSettle();

    // 컨트롤러 계약(무변경) 검증: 편집기 조인(`'\n'`) → sendSolution 줄 분해 왕복.
    expect(fake.lastRequest?.studentInput, '식을 정리한다\n근을 구한다');
    expect(fake.lastRequest?.solutionSteps, <String>['식을 정리한다', '근을 구한다']);

    // 제출 후 편집기는 초기 상태(빈 2필드·"풀이 제출")로 돌아온다(추가한 3번째도 사라짐).
    expect(find.text('풀이 제출'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
  });

  testWidgets('대화 모드 회귀 — 단계 편집기 UI 없이 Enter(전송)로 보낸다', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    // 대화 모드엔 단일 입력 필드 하나뿐, 단계 편집기 UI는 없다.
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('단계 추가'), findsNothing);
    expect(find.text('풀이 제출'), findsNothing);
    expect(find.byIcon(Icons.send), findsOneWidget);

    // Enter(전송 액션)로 보내는 기존 동작이 유지된다.
    await tester.enterText(find.byType(TextField), '이 문제 어렵네요');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pumpAndSettle();
    expect(find.text('이 문제 어렵네요'), findsOneWidget); // 학생 버블.
    expect(find.text('먼저 무엇이 주어졌는지 정리해 볼까요?'), findsOneWidget); // 코치 응답.
  });

  testWidgets('풀이 모드에서만 "수식으로 입력"(MathLive) 진입 버튼이 보인다', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    // 대화 모드에선 수식 입력 버튼이 없다.
    expect(find.text('수식으로 입력'), findsNothing);

    // 풀이 단계 모드로 토글하면 MathLive 진입 버튼이 나타난다(탭하면 WebView 화면이라
    // 여기선 존재만 확인한다 — WebView 렌더 통합은 후속).
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();
    expect(find.text('수식으로 입력'), findsOneWidget);
  });

  testWidgets('풀이 단계 빈 필드에 입력 형태 예시 힌트가 보인다(MOB-05)', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    // 풀이 단계 모드로 토글하면 단계 편집기(초기 2필드)가 나타난다.
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 빈 필드 힌트가 "단계 N"이 아니라 입력 형태 예시로 안내된다(왼쪽 번호 라벨과 중복 제거).
    // 힌트는 빈 필드에 Text로 렌더되므로 find.text로 잡힌다(필드별 예시가 달라 각 1개).
    expect(find.text('예: 2x+3=7'), findsOneWidget);
    expect(find.text('예: x=2'), findsOneWidget);
    expect(find.textContaining('단계 1'), findsNothing);

    // 정서 안전(절대 금기): "틀렸다"류 부정 표현이 없다.
    expect(find.textContaining('틀'), findsNothing);
  });

  testWidgets('API 실패 시 SnackBar로 에러를 알린다(앱은 유지)', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(shouldThrow: true)));

    await tester.enterText(find.byType(TextField), '도와주세요');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump(); // 상태 갱신.
    await tester.pump(); // SnackBar 프레임.

    // 학생 발화는 남고 SnackBar(에러)가 뜬다.
    expect(find.text('도와주세요'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets('활성 문제가 있으면 채팅 상단 배너에 발문이 보인다(접기 가능)', (tester) async {
    // 실기기 시연 피드백 회귀 가드: "문제가 한 화면에 같이 안 나옴" — 풀이 중 문제를
    // 다시 보러 화면을 떠나지 않도록 채팅 위에 발문을 상시 노출한다.
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          coachApiProvider.overrideWithValue(_FakeCoachApi(response: _response())),
          activeProblemProvider.overrideWith(
            (ref) => const Problem(
              problemId: 'p-1',
              sourceType: '자체생성',
              subject: '공통',
              questionText: '이차방정식 x^2-5x+6=0의 두 근 중 큰 근을 구하시오.',
            ),
          ),
        ],
        child: const MaterialApp(home: ChatScreen()),
      ),
    );

    // 기본 펼침 — 발문이 보인다(수식 x^2는 조판되므로 프로즈 부분은 textContaining으로 확인·S3-39).
    expect(find.textContaining('두 근 중 큰 근을 구하시오'), findsOneWidget);
    // 캐럿 수식(x^2-5x+6=0)은 raw가 아니라 Math로 조판된다.
    expect(find.byType(Math), findsWidgets);
    expect(find.textContaining('x^2-5x+6=0'), findsNothing);

    // 배너를 탭하면 접혀 발문이 숨고 요약 행만 남는다.
    await tester.tap(find.textContaining('풀이 중인 문제'));
    await tester.pump();
    expect(find.textContaining('두 근 중 큰 근을 구하시오'), findsNothing);
    expect(find.byType(Math), findsNothing); // 접히면 수식도 사라진다.
    expect(find.textContaining('풀이 중인 문제'), findsOneWidget);
  });

  testWidgets('활성 문제가 없으면 배너가 그려지지 않는다', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));
    expect(find.textContaining('풀이 중인 문제'), findsNothing);
  });

  // ── S3-12→S3-17 객관식 선택지 세로 번호 목록 ─────────────────────────────
  // 학생은 값을 고르는 게 아니라 *번호*를 고른다: 보기를 "N. [값]" 세로 목록으로 렌더하고
  // (번호는 문항 배너의 1-기반 "N." 표기와 일치), 번호 행을 탭하면 클라가 그 항목의 *값*
  // (choices[i])을 기존 send(student_input) 경로로 제출한다(번호 타이핑 모호성 0·서버 계약 무변경).
  testWidgets('객관식 문항이면 선택지를 세로 번호 목록으로 렌더한다("N." 번호 + 값)',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-mc',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '객관식',
          questionText: '이차방정식 x^2-5x+6=0의 서로 다른 실근의 개수는?',
          choices: ['0', '1', '2', '3'],
        ),
      ),
    );

    // 선택지 4개가 각각 탭 가능한 세로 행(OutlinedButton)으로 렌더된다.
    expect(find.byType(OutlinedButton), findsNWidgets(4));
    // 각 행 앞에 1-기반 번호 "N."(배너 표기와 일치). 배너는 "N. 값"을 한 Text로 합쳐 렌더하므로
    // "1."(마침표까지)만의 정확 일치는 목록 행 번호에서만 잡힌다.
    expect(find.text('1.'), findsOneWidget);
    expect(find.text('4.'), findsOneWidget);
    // 값은 번호 뒤에 별도 Text로 렌더된다(길면 줄바꿈).
    expect(find.widgetWithText(OutlinedButton, '0'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '2'), findsOneWidget);
    // 은근한 안내(정오·정답률 강조 없음)·번호 선택임을 명시.
    expect(find.text('보기 번호를 골라 보세요'), findsOneWidget);
  });

  testWidgets('choices만 있고 question_format이 없어도 세로 번호 목록을 렌더한다',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-mc2',
          sourceType: '자체생성',
          subject: '공통',
          // question_format 미지정 — choices 보유만으로 MC로 취급.
          questionText: '다음 중 옳은 것은?',
          choices: ['ㄱ', 'ㄴ', 'ㄷ'],
        ),
      ),
    );
    expect(find.byType(OutlinedButton), findsNWidgets(3));
    expect(find.text('3.'), findsOneWidget); // 1-기반 번호가 붙는다.
  });

  testWidgets('번호 행 탭 → 그 항목의 값(choices[i])이 send(student_input) 경로로 나간다',
      (tester) async {
    final fake = _FakeCoachApi(response: _response());
    await tester.pumpWidget(
      _wrapWithProblem(
        fake,
        const Problem(
          problemId: 'p-mc',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '객관식',
          questionText: '서로 다른 실근의 개수는?',
          choices: ['0', '1', '2', '3'],
        ),
      ),
    );

    // 3번 보기(번호 "3.")를 탭한다 — 그 항목의 값은 choices[2] = "2"다(번호≠값). 탭은 번호로
    // 하고 제출은 값으로 나가는 매핑을 봉인한다(번호 타이핑 모호성 우회의 핵심).
    // 세로 목록은 상한+내부 스크롤이라 좁은 창에선 뒤 행이 뷰포트 밖일 수 있어 먼저 노출시킨다.
    final target = find.widgetWithText(OutlinedButton, '3.');
    await tester.ensureVisible(target);
    await tester.pumpAndSettle();
    await tester.tap(target);
    await tester.pumpAndSettle();

    // 타이핑과 동일한 경로 — student_input에 *번호가 아닌 값* "2"가 실려 나간다(풀이 단계 아님).
    expect(fake.lastRequest?.studentInput, '2');
    expect(fake.lastRequest?.solutionSteps, isNull);
    // 학생 버블로 선택 값이 보이고 코치 응답이 이어진다.
    expect(find.text('먼저 무엇이 주어졌는지 정리해 볼까요?'), findsOneWidget);
  });

  testWidgets('선택지 값이 길어도 세로 목록이 줄바꿈으로 렌더되고 오버플로가 없다(MOB-02)',
      (tester) async {
    // 폰급 창 + 키보드(IME 300px)로 body 가용 높이를 좁혀 최악 케이스를 만든다 —
    // 값이 길어도 목록은 상한+내부 스크롤로 가둬져 RenderFlex 오버플로가 나지 않는다.
    tester.view.physicalSize = const Size(411, 756);
    tester.view.devicePixelRatio = 1.0;
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.reset);

    const longValue = '이차함수의 그래프가 x축과 서로 다른 두 점에서 만나고 '
        '그 두 점의 x좌표의 합이 4, 곱이 3이 되도록 하는 실수 k의 값';
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-mc-long',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '객관식',
          questionText: '다음 중 옳은 것은?',
          choices: ['짧은 보기', longValue, '또 다른 보기', '마지막 보기'],
        ),
      ),
    );

    // 첫 레이아웃부터 오버플로 예외가 없어야 한다.
    expect(tester.takeException(), isNull);
    // 긴 값도 하나의 행(OutlinedButton) 안에 값 Text로 렌더된다(멀티라인 수용).
    expect(find.widgetWithText(OutlinedButton, longValue), findsOneWidget);
    expect(find.byType(OutlinedButton), findsNWidgets(4));
  });

  testWidgets('주관식 문항이면 선택지 목록을 렌더하지 않는다(주관식 흐름 영향 0)',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-sub',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '단답형',
          questionText: '이차방정식 x^2-5x+6=0의 두 근 중 큰 근을 구하시오.',
          // choices 없음(단답형) → MC 아님.
        ),
      ),
    );

    // S3-38(원 S3-20): 주관식은 '풀이 단계' 모드로 시작한다 — 대화로 전환해도(선택지 목록이
    // 뜰 수 있는 모드) 주관식엔 선택지 목록이 없다(주관식 흐름 영향 0). 대화로 전환해 최악
    // 케이스에서 확인한다.
    await tester.tap(find.byIcon(Icons.chat_bubble_outline));
    await tester.pump();

    // 선택지 목록·안내가 없고, 대화 입력(단일 필드+전송)은 그대로다.
    expect(find.byType(OutlinedButton), findsNothing);
    expect(find.text('보기 번호를 골라 보세요'), findsNothing);
    expect(find.byIcon(Icons.send), findsOneWidget);
  });

  // ── S3-38(원 S3-20) 코치 첫 화면 기본 모드 문제유형별(Kiki 결정) ─────────────
  // 객관식 → '대화' 모드(선택지 번호 목록 바로 노출)·주관식 → '풀이단계' 모드(단계 풀이 바로 시작)·
  // 자유 대화 → 기존 기본 '대화'. 학생의 수동 모드 전환은 그대로 가능(토글 UI·기존 동작 불변).
  testWidgets('S3-38: 객관식 활성 문제는 대화 모드로 시작한다(선택지 목록 바로 노출)',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-mc-start',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '객관식',
          questionText: '서로 다른 실근의 개수는?',
          choices: ['0', '1', '2', '3'],
        ),
      ),
    );

    // 대화 모드로 시작 — 모드 라벨 '대화'·선택지 번호 목록이 바로 노출된다(풀이 편집기 아님).
    expect(find.text('대화'), findsOneWidget);
    expect(find.byType(OutlinedButton), findsNWidgets(4));
    expect(find.byIcon(Icons.send), findsOneWidget);
    expect(find.text('풀이 제출'), findsNothing);
    expect(find.text('단계 추가'), findsNothing);
  });

  testWidgets('S3-38: 주관식 활성 문제는 풀이단계 모드로 시작한다(단계 풀이 바로 시작)',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-sub-start',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '서술형',
          questionText: '이차방정식 x^2-5x+6=0의 두 근 중 큰 근을 구하시오.',
          // choices 없음(주관식) → 풀이 단계 모드로 시작.
        ),
      ),
    );

    // 풀이 단계 모드로 시작 — 모드 라벨 '풀이 단계'·단계 편집기(제출/추가 버튼)가 바로 보인다.
    expect(find.text('풀이 단계'), findsOneWidget);
    expect(find.text('풀이 제출'), findsOneWidget); // 빈 필드 → "풀이 제출"(비활성).
    expect(find.text('단계 추가'), findsOneWidget);
    // 대화 모드 어포던스(단일 전송·선택지 목록)는 없다.
    expect(find.byIcon(Icons.send), findsNothing);
    expect(find.byType(OutlinedButton), findsNothing);
  });

  testWidgets('S3-38: 활성 문제가 없으면(자유 대화) 기존 기본 대화 모드로 시작한다',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));

    // 자유 대화는 기존 기본 — 대화 모드(단일 입력+전송)로 시작한다.
    expect(find.text('대화'), findsOneWidget);
    expect(find.byIcon(Icons.send), findsOneWidget);
    expect(find.text('풀이 제출'), findsNothing);
  });

  testWidgets('활성 문제가 없으면(자유 대화) 선택지 목록을 렌더하지 않는다', (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));
    expect(find.byType(OutlinedButton), findsNothing);
  });

  testWidgets('풀이 단계 모드로 전환하면 선택지 목록을 감춘다(풀이 편집기와 겹치지 않음·MOB-02 불변식)',
      (tester) async {
    await tester.pumpWidget(
      _wrapWithProblem(
        _FakeCoachApi(response: _response()),
        const Problem(
          problemId: 'p-mc',
          sourceType: '자체생성',
          subject: '공통',
          questionFormat: '객관식',
          questionText: '서로 다른 실근의 개수는?',
          choices: ['0', '1', '2', '3'],
        ),
      ),
    );

    // 대화 모드(기본) — 선택지 목록이 주 어포던스로 보인다.
    expect(find.byType(OutlinedButton), findsNWidgets(4));

    // 풀이 단계 모드로 토글 → 단계 편집기가 답 구성 어포던스를 넘겨받고 선택지 목록은 감춰진다.
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();
    expect(find.byType(OutlinedButton), findsNothing);
    expect(find.text('보기 번호를 골라 보세요'), findsNothing);

    // 대화로 돌아오면 다시 선택지 목록이 나타난다.
    await tester.tap(find.byIcon(Icons.chat_bubble_outline));
    await tester.pump();
    expect(find.byType(OutlinedButton), findsNWidgets(4));
  });

  // ── NS-01 풀이 단계 편집기 교과서 표기 렌더 프리뷰 ─────────────────────────────
  // "수식으로 입력"(MathLive)으로 넣은 수식이 단계 필드에 raw LaTeX(f^{\prime\prime}(x))로
  // 보이던 문제(실기기 2026-07-23). 편집 TextField는 raw를 유지하되, 그 아래에 같은 내용을
  // 교과서 표기로 조판한 read-only 프리뷰(MathText → Math)를 얹는다. 편집·제출 계약은 불변.
  // 변별력: _wrap은 활성 문제가 없어 배너가 없으므로 Math 위젯은 *프리뷰에서만* 나온다 —
  // 빈/프로즈 단계에서 findsNothing, 수식 단계에서 findsWidgets로 대비가 성립한다.
  testWidgets('NS-01: 단계 필드에 LaTeX 입력 시 교과서 표기 렌더 프리뷰(Math)가 노출된다',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 초기 빈 2필드 → 프리뷰 없음(빈 공간 최소화).
    expect(find.byType(Math), findsNothing);

    // MathLive가 낼 법한 raw LaTeX(이계도함수)를 단계 필드에 넣는다.
    await tester.enterText(find.byType(TextField).at(0), r'f^{\prime\prime}(x)');
    await tester.pump();

    // 교과서 표기로 조판된 프리뷰(Math)가 생긴다 — raw만 노출되지 않는다(크래시 0).
    expect(find.byType(Math), findsWidgets);
    expect(tester.takeException(), isNull);

    // 편집 필드는 raw 원문을 그대로 보유한다(편집 가능성 불변 — 필드 값 무변경).
    final field = tester.widget<TextField>(find.byType(TextField).at(0));
    expect(field.controller?.text, r'f^{\prime\prime}(x)');
  });

  testWidgets('NS-01: 단계 필드에 유니코드 수식(x³) 입력 시 렌더 프리뷰가 노출된다',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    expect(find.byType(Math), findsNothing);
    // 유니코드 상첨자(x³)는 캐럿 LaTeX로 정규화돼 조판된다(S3-23).
    await tester.enterText(find.byType(TextField).at(0), 'x³-3x');
    await tester.pump();
    expect(find.byType(Math), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('NS-01: 빈 필드·순수 프로즈 단계엔 렌더 프리뷰가 없다(빈 공간 최소화)',
      (tester) async {
    await tester.pumpWidget(_wrap(_FakeCoachApi(response: _response())));
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    // 초기 빈 2필드 → 프리뷰 없음.
    expect(find.byType(Math), findsNothing);

    // 수식 신호가 없는 순수 한국어 단계 → 프리뷰를 만들지 않는다(중복 표시 억제).
    await tester.enterText(find.byType(TextField).at(0), '식을 표준형으로 정리한다');
    await tester.pump();
    expect(find.byType(Math), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('NS-01: 프리뷰가 떠 있어도 제출은 raw 원문을 그대로 sendSolution으로 보낸다',
      (tester) async {
    final fake = _FakeCoachApi(response: _response());
    await tester.pumpWidget(_wrap(fake));
    await tester.tap(find.byIcon(Icons.format_list_numbered));
    await tester.pump();

    await tester.enterText(find.byType(TextField).at(0), r'f^{\prime}(x)=2x');
    await tester.enterText(find.byType(TextField).at(1), r'f^{\prime}(1)=2');
    await tester.pump();
    // 두 단계 모두 교과서 표기 프리뷰(Math)가 떠 있다.
    expect(find.byType(Math), findsWidgets);

    await tester.tap(find.text('2단계 제출'));
    await tester.pumpAndSettle();

    // 제출 계약 불변 — 프리뷰는 표시일 뿐, 전송 원문은 raw 그대로다(줄 분해 왕복 무손실).
    expect(
      fake.lastRequest?.studentInput,
      r'f^{\prime}(x)=2x' '\n' r'f^{\prime}(1)=2',
    );
    expect(
      fake.lastRequest?.solutionSteps,
      <String>[r'f^{\prime}(x)=2x', r'f^{\prime}(1)=2'],
    );

    // 제출 후 편집기는 초기 상태(빈 2필드)로 돌아온다 — 필드가 비어 프리뷰도 사라진다
    // (제출된 학생 버블 수식은 S3-21로 조판되어 대화에 남는 것이 정상이라 Math 총량은 검사하지 않는다).
    expect(find.byType(TextField), findsNWidgets(2));
  });
}
