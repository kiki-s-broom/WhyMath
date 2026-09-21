// S1 E2E 학습 루프 *앱 계층 관통* 플로우 테스트 — 온보딩→진단→문제→코치(세션)→turn→verify
// →정답 제출→돌아보기→완료 소비→다음 추천 변화(EOS-81 뒷반쪽 연장).
//
// 백엔드 `tests/backend/api/test_e2e_vertical_slice_integration.py`의 호출 순서·불변식을 *앱 측에서
// 미러*한다. fake가 아니라 **실 api 클라이언트·실 컨트롤러·실 화면**을 하나의 라우팅 Dio 어댑터
// (경로별 canned 응답)에 물려, 실제 직렬화·경로·모델 매핑·UI 어포던스를 한 번에 관통 검증한다
// (라이브 키 전의 회귀 앵커).
//
// 검증 불변식(백엔드 앵커와 동형):
//  ① answer 비노출 — GET problem이 answer를 보내도 클라 Problem/코치 응답에 진입하지 않는다.
//  ② verify 신호 정합 — 코치 solution_verification.first_incorrect_index == 독립 verify와 일치.
//  ③ 턴 영속 — 세션 생성(2턴)+turn(2턴)=… getSession이 누적 턴을 돌려준다.
//  ④ 세션 problem_id 배선 — 활성 문제가 createSession 본문 problem_id로 실린다.
//  ⑤ is_minor 서버파생 — 온보딩 PATCH 본문에 is_minor를 싣지 않는다(서버가 birth_year에서 파생).
//  ⑥ 완료 신호 소비(MOB-20) — 정답 제출 턴은 돌아보기 대기, 돌아보기 응답 턴은 완료를 내리고
//     클라 상태·화면이 그대로 따라간다. 완료여도 클라는 `POST /v1/me/attempts`를 부르지 않는다
//     (중복 적재 금지 — api/coach.py 계약).
//  ⑦ 폐쇄루프 — 완료 후 다시 받은 CAT 추천이 *실제로 달라진다*(EOS-81 완료조건 (라)).
//
// ── EOS-81 완료조건 4가지의 클라 관측 가능 범위(정직 표기) ─────────────────────────────
//  (가) "코치 완료 경로가 attempt를 적재하고 클라가 그 완료 신호를 소비한다" → **관측 가능**.
//       클라가 볼 수 있는 적재 증거는 완료 턴이 돌려준 `completed_attempt_id`(서버 권위값)뿐이며,
//       이 파일은 그 값이 상태(provider)·화면(완료 패널)까지 전파되는 지점을 단언한다.
//  (나) "attempt가 영속 저장된다" → **클라에서 관측 불가**(DB 행 수는 서버 축). 백엔드 앵커가 센다.
//  (다) "개념·스킬 mastery가 변경된다" → **클라에서 관측 불가**(mastery 델타는 서버 축).
//       클라가 볼 수 있는 것은 그 변화의 *하류 결과*인 추천 변화((라))뿐이다.
//  (라) "후속 추천이 갱신을 반영한다" → **관측 가능**. 완료 전후로 `GET /v1/me/next-problem`이
//       내려주는 문항이 *달라지는 것*으로 단언한다("200 OK"는 완료 조건이 아니다).
//
// 변별력(CLAUDE.md 2026-09-01): 이 파일의 fake는 **상태 있는(stateful)** 서버 대역이다 —
// 완료 턴이 오기 전에는 몇 번을 물어도 같은 문항(prob-1)을 돌려주고, 완료 턴 뒤에만 다른
// 문항(prob-2)을 돌려준다. 호출 횟수로 회전하는 fake라면 (라)는 아무것도 증명하지 못한다.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:korean_math_app/core/router.dart';
import 'package:korean_math_app/features/chat/application/chat_controller.dart';
import 'package:korean_math_app/features/chat/application/completion_signal.dart';
import 'package:korean_math_app/features/chat/data/coach_api.dart';
import 'package:korean_math_app/features/chat/presentation/chat_screen.dart';
import 'package:korean_math_app/features/onboarding/data/user_api.dart';
import 'package:korean_math_app/features/problems/application/active_problem.dart';
import 'package:korean_math_app/features/problems/application/diagnosis_controller.dart';
import 'package:korean_math_app/features/problems/data/problems_api.dart';
import 'package:korean_math_app/features/verify/data/verify_api.dart';

const String _answerSentinel = '정답은-42-절대노출금지';

/// 서버가 완료 턴에서 적재한 ProblemAttempt PK(클라가 볼 수 있는 유일한 적재 증거).
const String _attemptId = 'att-e2e-1';

/// 경로·메서드로 canned 응답을 라우팅하는 **상태 있는** 어댑터 — 요청도 경로별로 캡처한다.
///
/// 상태를 갖는 이유(변별력): 폐쇄루프의 핵심 주장은 "완료가 다음 추천을 바꾼다"이다. 응답이
/// 고정이면 그 주장은 검사 없이 통과하고, 호출 횟수로 회전시키면 *완료와 무관하게* 바뀐다.
/// 그래서 추천 응답은 오직 [attemptRecorded](완료 턴이 만든 서버 상태의 미러)에만 의존한다.
class _RoutingAdapter implements HttpClientAdapter {
  /// 경로별 *마지막* 요청(본문·쿼리 단언용).
  final Map<String, RequestOptions> captured = <String, RequestOptions>{};

  /// 나간 요청 전건('METHOD path' 순서·횟수) — 마지막만 남는 [captured]로는 셀 수 없다.
  final List<String> calls = <String>[];

  /// 세션에 이어붙인 턴 호출 횟수 — 턴마다 서버 응답이 달라지므로 상태로 센다.
  int coachTurnCalls = 0;

  /// 서버가 완료 턴에서 attempt를 적재하고 숙달을 전파했는가(서버 상태의 클라측 미러).
  ///
  /// 이 플래그가 참이 된 *뒤에야* CAT 추천이 달라진다 — 조회 횟수로는 절대 바뀌지 않는다.
  bool attemptRecorded = false;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final path = options.path;
    final method = options.method;
    captured['$method $path'] = options;
    calls.add('$method $path');
    return _json(_bodyFor(method, path));
  }

  @override
  void close({bool force = false}) {}

  /// 어떤 경로가 몇 번 불렸는지(부분 문자열 일치) — 호출 0건·중복 호출 단언에 쓴다.
  int callCount(String needle) => calls.where((c) => c.contains(needle)).length;

  Map<String, dynamic> _bodyFor(String method, String path) {
    if (method == 'PATCH' && path == '/v1/users/me') {
      return <String, dynamic>{};
    }
    if (path == '/v1/me/next-problem') {
      // ⑦ CAT 추천 — 완료(=attempt 적재+숙달 전파) *전후*로만 달라진다.
      //    서버 미러: 완료 전에는 몇 번을 물어도 같은 문항(측정이 그대로라 추천도 그대로),
      //    완료 뒤에는 갱신된 숙달을 반영해 다른 문항·다른 θ를 내려준다.
      return attemptRecorded
          ? <String, dynamic>{
              'problem_id': 'prob-2',
              'theta': 0.62,
              'difficulty': 3.5,
              'measurement_sufficient': false,
            }
          : <String, dynamic>{
              'problem_id': 'prob-1',
              'theta': 0.3,
              'difficulty': 2.5,
              'measurement_sufficient': false,
            };
    }
    if (path == '/v1/me/diagnosis/concepts') {
      return <String, dynamic>{'__list__': <dynamic>[]};
    }
    if (path == '/v1/problems/prob-1') {
      // ① 백엔드는 answer를 그대로 반환한다 — 클라 모델이 걸러야 한다.
      return _problemBody('prob-1', '다음 함수를 미분하시오.');
    }
    if (path == '/v1/problems/prob-2') {
      // 완료 후 새로 추천된 문항 — 같은 answer 불변식이 여기서도 성립해야 한다.
      return _problemBody('prob-2', '다음 극한값을 구하시오.');
    }
    if (path == '/v1/coach/sessions') {
      // 세션 생성 — 코치 결정 + 영속 식별자 + verify 신호(answer는 결코 싣지 않는다).
      // 첫 풀이는 오답 단계라 완료 신호가 없다(백엔드 앵커의 _BAD_STEPS 구간과 동형).
      return _coachBody(dialogueId: 'dlg-1', wh1: 1);
    }
    if (path == '/v1/coach/sessions/dlg-1/turns') {
      coachTurnCalls++;
      switch (coachTurnCalls) {
        case 1:
          // 다턴 — 아직 코칭 중(완료 신호 없음·대조군).
          return _coachBody(wh1: 2);
        case 2:
          // 정답 풀이 제출 턴 — 서버가 correct로 판정하고 Polya 돌아보기 1턴을 요청한다.
          // (정오 판정은 전적으로 서버 권위값이다 — 클라는 판정하지 않는다.)
          return _coachBody(wh1: 3, awaitingReflection: true);
        default:
          // 학생의 돌아보기 응답 턴에서 완료된다 — 서버가 attempt를 적재하고 숙달을 전파한 뒤
          // id를 돌려준다. 이 시점부터 추천이 갱신된 숙달을 반영한다(폐쇄루프 닫힘).
          attemptRecorded = true;
          return _coachBody(
            wh1: 4,
            problemComplete: true,
            completedAttemptId: _attemptId,
          );
      }
    }
    if (method == 'GET' && path == '/v1/coach/sessions/dlg-1') {
      // ③ 생성 2턴 + turn마다 2턴이 누적 영속된다(호출 시점의 실제 누적을 돌려준다).
      final int total = 2 + 2 * coachTurnCalls;
      return <String, dynamic>{
        'dialogue': <String, dynamic>{
          'dialogue_id': 'dlg-1',
          'total_turns': total,
        },
        'turns': <dynamic>[
          for (int i = 1; i <= total; i++)
            <String, dynamic>{
              'turn_order': i,
              'role': i.isOdd ? 'student' : 'assistant',
              'content': 't$i',
            },
        ],
      };
    }
    if (path == '/v1/verify-solution') {
      // ② 코치 solution_verification과 동일 위치(first_incorrect_index=1)를 가리킨다.
      return _verifyBody();
    }
    return <String, dynamic>{};
  }

  /// 문제 단건 응답 — answer·해설에 sentinel을 심는다(클라 모델이 거르는지 보기 위함).
  Map<String, dynamic> _problemBody(String problemId, String questionText) =>
      <String, dynamic>{
        'problem_id': problemId,
        'source_type': '자체생성',
        'subject': '미적분',
        'subunit': '합성함수의 미분',
        'unit_codes': <String>['CAL-DIFF-COMP'],
        'question_text': questionText,
        'answer': _answerSentinel,
        'answer_explanation': '풀이 설명 $_answerSentinel',
      };

  /// 코치 응답(세션/turn 공통) — decision + solution_verification + 영속 필드. answer 없음.
  Map<String, dynamic> _coachBody({
    String? dialogueId,
    required int wh1,
    bool problemComplete = false,
    bool awaitingReflection = false,
    String? completedAttemptId,
  }) {
    return <String, dynamic>{
      'decision': <String, dynamic>{
        'polya_stage_to_advance': 'stay',
        'prompt': '세 번째 줄의 계산을 다시 살펴볼까요?',
        'system': 's',
        'socratic_category': '단계분해',
      },
      'solution_coaching': <String, dynamic>{
        'trigger': <String, dynamic>{
          'focus': 'verify',
          'rationale': '단계 검증 결과',
          'prompt': '',
          'socratic_category': '검증',
        },
        'arithmetic_error': true,
        'solution_verification': _verifyBody(),
      },
      if (dialogueId != null) 'dialogue_id': dialogueId,
      'student_turn_id': 's-$wh1',
      'assistant_turn_id': 'a-$wh1',
      'wh1_turn_index': wh1,
      'wh1_exploration_turn': false,
      // S3-32 완료 신호 3필드(MOB-20 클라 소비 대상).
      'problem_complete': problemComplete,
      'awaiting_reflection': awaitingReflection,
      'completed_attempt_id': completedAttemptId,
    };
  }

  Map<String, dynamic> _verifyBody() => <String, dynamic>{
        'n_transitions': 2,
        'n_correct': 1,
        'n_incorrect': 1,
        'n_unverifiable': 0,
        'unverified_ratio': 0.0,
        'first_incorrect_index': 1,
        'has_incorrect': true,
      };

  ResponseBody _json(Map<String, dynamic> body) => ResponseBody.fromString(
        jsonEncode(body['__list__'] ?? body),
        200,
        headers: {
          Headers.contentTypeHeader: [Headers.jsonContentType],
        },
      );
}

/// 채팅 화면 + 실제 라우터(문제 화면은 표식만 있는 대역)로 감싼다.
///
/// 완료 신호가 *화면까지* 전파되는지 보려면 실제 위젯 트리가 필요하다 — provider 값만 확인하면
/// 어포던스가 죽어 있어도 초록이 된다(변별력 없는 검증 금지·`coach_completion_signal_test.dart`
/// 의 `_wrap`과 동형).
Widget _wrap(ProviderContainer container) {
  final router = GoRouter(
    initialLocation: AppRoutes.chatPath,
    routes: [
      GoRoute(path: AppRoutes.chatPath, builder: (_, __) => const ChatScreen()),
      GoRoute(
        path: AppRoutes.problemPath,
        builder: (_, __) => const Scaffold(body: Text('문제 화면(대역)')),
      ),
    ],
  );
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp.router(routerConfig: router),
  );
}

void main() {
  testWidgets(
      '온보딩→진단→문제→코치→다턴→verify→정답 제출→돌아보기→완료 소비→다음 추천 변화를 '
      '앱 계층에서 관통한다', (tester) async {
    final adapter = _RoutingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://x'))
      ..httpClientAdapter = adapter;

    final container = ProviderContainer(
      overrides: [
        problemsApiProvider.overrideWithValue(ProblemsApi(dio)),
        coachApiProvider.overrideWithValue(CoachApi(dio)),
      ],
    );
    addTearDown(container.dispose);

    // autoDispose 컨트롤러가 await 중 폐기되지 않도록 리스너로 살려 둔다(실제 앱에선 화면이
    // watch로 구독을 유지하는 것과 동형). 구독 없이 read만 하면 await 사이에 폐기돼 상태가 리셋된다.
    container.listen(diagnosisControllerProvider, (_, __) {}, fireImmediately: true);
    container.listen(chatControllerProvider, (_, __) {}, fireImmediately: true);

    // ⑦ 대조군 기준점 — 완료 *전*의 추천 문항·θ(폐쇄루프 구간에서 달라짐을 잰다).
    late final String recommendedBefore;
    late final double thetaBefore;

    // ── 네트워크 구간(1~10)은 tester.runAsync로 *실* async 존에서 돌린다 ──────────
    // testWidgets의 FakeAsync 존에서는 dio의 Future가 진행하지 않아 첫 await에서 그대로 멈춘다
    // (2026-09-04 실측: 직접 await는 타임아웃, runAsync는 통과). 화면 검증(pump 계열)은
    // runAsync 안에서 할 수 없으므로 네트워크 구간과 렌더 구간을 블록으로 나눈다.
    await tester.runAsync(() async {
      // ── 1) 온보딩: PATCH /v1/users/me (⑤ is_minor 미포함) ────────────────────
      await UserApi(dio).patchMe(<String, dynamic>{
        'birth_year': 2008,
        'target_grade': 2,
      });
      final patchBody =
          adapter.captured['PATCH /v1/users/me']!.data as Map<String, dynamic>;
      expect(patchBody.containsKey('is_minor'), isFalse); // ⑤ 서버 파생.

      // ── 2) 진단(CAT)→문제 로드: DiagnosisController ─────────────────────────
      await container.read(diagnosisControllerProvider.notifier).load();
      final diag = container.read(diagnosisControllerProvider);
      expect(diag.problem, isNotNull);
      expect(diag.problem!.problemId, 'prob-1');
      // ① answer 비노출 — 문제 모델 재직렬화에 정답 sentinel이 없다.
      final problemJson = jsonEncode(diag.problem!.toJson());
      expect(problemJson.contains(_answerSentinel), isFalse);
      expect(diag.problem!.questionText, '다음 함수를 미분하시오.');
      recommendedBefore = diag.problem!.problemId;
      thetaBefore = diag.nextProblem!.theta;

      // ── 3) 활성 문제 세팅(진단→코치 핸드오프) ───────────────────────────────
      container.read(activeProblemProvider.notifier).state = diag.problem;

      // ── 4) 코치: 첫 풀이 전송 → 세션 생성(problem_id 배선·verify 신호) ────────
      final chat = container.read(chatControllerProvider.notifier);
      await chat.sendSolution('a\nb\nc');
      final afterCreate = container.read(chatControllerProvider);
      expect(afterCreate.dialogueId, 'dlg-1'); // 세션 생성됨.
      // ④ 세션이 활성 문제에 묶였다.
      final coachBody = adapter.captured['POST /v1/coach/sessions']!.data
          as Map<String, dynamic>;
      expect(coachBody['problem_id'], 'prob-1');
      // 코치 응답에 정답 sentinel이 없다(answer 비노출).
      final coachMsg =
          afterCreate.messages.firstWhere((m) => m.response != null);
      final coachFirstIncorrect = coachMsg
          .response!.solutionCoaching!.solutionVerification!.firstIncorrectIndex;
      expect(coachFirstIncorrect, 1);
      expect(jsonEncode(coachMsg.text).contains(_answerSentinel), isFalse);
      // ⑥ 오답 단계 구간이라 완료 신호가 아직 없다(대조군 — 신호가 항상 켜져 있는 게 아니다).
      final afterCreateSignal = container.read(coachCompletionSignalProvider);
      expect(afterCreateSignal.problemComplete, isFalse);
      expect(afterCreateSignal.awaitingReflection, isFalse);
      expect(afterCreateSignal.completedAttemptId, isNull);

      // ── 5) 다음 발화 → 같은 세션에 turn 추가 ────────────────────────────────
      await chat.send('이 부분이 맞나요?');
      expect(
        adapter.captured.containsKey('POST /v1/coach/sessions/dlg-1/turns'),
        isTrue,
      );
      expect(container.read(chatControllerProvider).dialogueId, 'dlg-1');
      // 여전히 코칭 중 — 완료도 돌아보기도 아니다(신호는 이 문제에 스코프된 '없음' 상태다:
      // problemId만 실리고 3필드는 서버 기본값 그대로다).
      final afterTurnSignal = container.read(coachCompletionSignalProvider);
      expect(afterTurnSignal.problemComplete, isFalse);
      expect(afterTurnSignal.awaitingReflection, isFalse);
      expect(afterTurnSignal.completedAttemptId, isNull);
      expect(afterTurnSignal.problemId, 'prob-1');

      // ── 6) 세션 조회: ③ 턴 영속 확인 ────────────────────────────────────────
      final snapshot = await CoachApi(dio).getSession('dlg-1');
      expect(snapshot.turns, hasLength(4)); // 생성 2턴 + turn 2턴.
      expect(snapshot.totalTurns, 4);

      // ── 7) 독립 verify: ② 코치 신호와 first_incorrect_index 정합 ────────────
      final verdict = await VerifyApi(dio)
          .verifySolution(<String>['x^2-4=0', '2x+3', 'x=2']);
      expect(verdict.hasIncorrect, isTrue);
      expect(verdict.firstIncorrectIndex, coachFirstIncorrect); // ② 정합.

      // ══ 이하 EOS-81 연장 — 폐쇄루프 뒷반쪽(정답 제출→돌아보기→완료→추천 변화) ══

      // ── 8) 대조군: 완료 *전*에는 몇 번을 물어도 추천이 그대로다 ─────────────
      // 이 확인이 없으면 뒤의 "추천이 달라졌다"가 *완료 때문인지* 그냥 두 번째 조회여서인지
      // 구분되지 않는다(호출 횟수로 회전하는 fake는 아무것도 증명하지 못한다).
      final probeBefore =
          await container.read(problemsApiProvider).getNextProblem();
      expect(probeBefore.problemId, recommendedBefore);
      expect(probeBefore.theta, thetaBefore);

      // ── 9) 정답 풀이 제출 → 서버가 correct 판정·돌아보기 1턴 요청 ────────────
      // 클라는 정오를 판정하지 않는다 — 제출한 단계를 그대로 올리고 서버 권위값을 받는다.
      await chat.sendSolution('x^2-4=0\n(x-2)(x+2)=0\nx=2 또는 x=-2');
      // 산출물 자체 단언 — "200 OK"가 아니라 *무엇을 보냈는가*를 본다(단계 3줄이 실렸다).
      final solutionBody = adapter
          .captured['POST /v1/coach/sessions/dlg-1/turns']!
          .data as Map<String, dynamic>;
      expect(solutionBody['solution_steps'], <String>[
        'x^2-4=0',
        '(x-2)(x+2)=0',
        'x=2 또는 x=-2',
      ]);
      // 돌아보기 대기 — 아직 완료가 아니다(서버 계약 순서 그대로).
      final reflectSignal = container.read(coachCompletionSignalProvider);
      expect(reflectSignal.awaitingReflection, isTrue);
      expect(reflectSignal.problemComplete, isFalse);
      expect(reflectSignal.completedAttemptId, isNull);
      // 돌아보기 대기 중에도 추천은 그대로다(완료가 아니면 숙달도 안 바뀐다).
      expect(
        (await container.read(problemsApiProvider).getNextProblem()).problemId,
        recommendedBefore,
      );

      // ── 10) 돌아보기 응답 → 완료: (가) 서버 적재 신호를 클라가 소비한다 ───────
      await chat.send('두 근의 곱이 -4라서 인수분해로 찾았어요.');
      final reflectionBody = adapter
          .captured['POST /v1/coach/sessions/dlg-1/turns']!
          .data as Map<String, dynamic>;
      expect(reflectionBody['student_input'], '두 근의 곱이 -4라서 인수분해로 찾았어요.');
      // 완료 신호 3필드가 그대로 상태에 실린다 — completed_attempt_id가 클라가 볼 수 있는
      // 유일한 "서버가 attempt를 적재했다" 증거다((나) 행 수·(다) mastery 델타는 서버 축).
      final doneSignal = container.read(coachCompletionSignalProvider);
      expect(doneSignal.problemComplete, isTrue);
      expect(doneSignal.awaitingReflection, isFalse);
      expect(doneSignal.completedAttemptId, _attemptId);
      // 신호는 *그 문제*에 스코프된다(다른 문제로 승계되지 않는다).
      expect(doneSignal.problemId, 'prob-1');
      expect(doneSignal.appliesTo('prob-1'), isTrue);
      // ⑥ 완료여도 클라는 attempt를 재적재하지 않는다 — 이 경로로 나간 요청이 0건이어야 한다.
      expect(adapter.callCount('/v1/me/attempts'), 0);
      // 턴 영속도 완료 턴까지 이어진다(생성 2턴 + turn 3회×2턴 = 8턴).
      final afterDone = await CoachApi(dio).getSession('dlg-1');
      expect(afterDone.turns, hasLength(8));
      expect(afterDone.totalTurns, 8);
    });

    // ── 11) 화면 전파: 완료 신호가 UI 어포던스까지 도달한다 ───────────────────
    // (상태만 보면 어포던스가 죽어 있어도 초록이 된다 — 화면까지 내려가야 소비의 증명이다.)
    await tester.pumpWidget(_wrap(container));
    await tester.pumpAndSettle();
    // 완료 패널이 뜨고(서버가 준 attempt id가 패널의 동일성 키), 돌아보기 안내는 사라졌다.
    expect(find.text('다음 문항으로'), findsOneWidget);
    expect(
      find.byKey(const ValueKey<String>('completion-panel-$_attemptId')),
      findsOneWidget,
    );
    expect(find.textContaining('돌아보기 차례'), findsNothing);
    // 완료는 종단 상태 — 턴을 만드는 입력이 잠긴다(끝난 세션에 턴을 더 붙이지 않는다).
    expect(tester.widget<TextField>(find.byType(TextField)).enabled, isFalse);

    // ── 12) (라) 후속 추천이 갱신을 반영한다 — *결과가 실제로 달라진다* ────────
    await tester.runAsync(() async {
      await container.read(diagnosisControllerProvider.notifier).load();
    });
    final diag2 = container.read(diagnosisControllerProvider);
    expect(diag2.problem, isNotNull);
    expect(diag2.problem!.problemId, isNot(recommendedBefore)); // 달라짐이 핵심.
    expect(diag2.problem!.problemId, 'prob-2');
    expect(diag2.problem!.questionText, '다음 극한값을 구하시오.');
    // 능력 추정도 갱신됐다(완료 이전 스냅샷과 다른 값).
    expect(diag2.nextProblem!.theta, isNot(thetaBefore));
    // ① 새 문항에도 answer 비노출 불변식이 그대로 성립한다.
    expect(
      jsonEncode(diag2.problem!.toJson()).contains(_answerSentinel),
      isFalse,
    );
    // 추천은 총 4번 조회됐다(진단 2회 + 대조군 프로브 2회) — 그중 달라진 것은 완료 *뒤* 조회뿐.
    expect(adapter.callCount('GET /v1/me/next-problem'), 4);
    // 전 구간에서 클라가 attempt를 직접 적재한 적이 없다(중복 적재 금지 최종 확인).
    expect(adapter.callCount('/v1/me/attempts'), 0);

    // ── 13) 새 문항으로 넘어가면 이전 완료 패널은 인정되지 않는다 ─────────────
    // (완료 신호가 새 문제의 진행을 가로막지 않는지 — 폐쇄루프가 *다음 바퀴*로 이어진다.)
    container.read(activeProblemProvider.notifier).state = diag2.problem;
    await tester.pumpAndSettle();
    expect(find.text('다음 문항으로'), findsNothing);
    expect(tester.widget<TextField>(find.byType(TextField)).enabled, isTrue);
  });
}
