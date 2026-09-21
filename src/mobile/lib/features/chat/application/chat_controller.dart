// 채팅 컨트롤러 — 학생 발화 전송·코치 응답 수신·Polya 단계 전이를 관장한다.
//
// 경계(CLAUDE.md): 수학·교수학 결정은 전부 서버(L4 `POST /v1/coach`)가 내린다. 이 컨트롤러는
// (1) 학생 입력을 요청으로 옮기고 (2) 받은 [CoachResponse]를 화면 메시지로 *렌더*하며
// (3) 서버가 내린 단계 전이 결정을 그대로 적용할 뿐이다(표현≠의미·수학 로직 클라 미구현).
// 부수효과는 [CoachApi] 호출 하나뿐 — 나머지는 순수 상태 전이다.
import 'package:flutter/foundation.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../ocr/data/ocr_models.dart';
import '../../problems/application/active_problem.dart';
import '../data/coach_api.dart';
import '../data/coach_models.dart';
import '../data/scene_api.dart';
import '../domain/chat_message.dart';
import '../domain/latex_to_plain.dart';
import 'chat_state.dart';
import 'completion_signal.dart';

part 'chat_controller.g.dart';

/// Polya 4단계 순서("understand"→"plan"→"execute"→"review").
///
/// 서버 결정 `decision.polyaStageToAdvance`는 *전이*("stay"·"next"·"previous")라
/// 현재 단계에 적용해 다음 단계 문자열을 얻는다. 자동 후퇴는 서버만 지시한다(클라 판단 없음).
const List<String> _polyaOrder = <String>[
  'understand',
  'plan',
  'execute',
  'review',
];

/// 현재 단계에 서버 전이 결정을 적용해 다음 단계 문자열을 계산한다.
///
/// 알 수 없는 전이·범위를 벗어난 이동은 현재 단계를 유지한다(보수적·앱 안정성).
String _applyTransition(String current, String transition) {
  final idx = _polyaOrder.indexOf(current);
  if (idx < 0) {
    return current; // 알 수 없는 단계는 그대로 둔다.
  }
  switch (transition) {
    case 'next':
      final next = idx + 1;
      return next < _polyaOrder.length ? _polyaOrder[next] : current;
    case 'previous':
      final prev = idx - 1;
      return prev >= 0 ? _polyaOrder[prev] : current;
    case 'stay':
    default:
      return current;
  }
}

/// 채팅 화면 상태를 관리하는 Riverpod Notifier.
@riverpod
class ChatController extends _$ChatController {
  @override
  ChatState build() => const ChatState();

  /// 학생 발화(대화 모드)를 보내고 코치 응답으로 상태를 갱신한다.
  ///
  /// 흐름: ① 학생 메시지 append·전송중 표시·에러 클리어 → ② 서버 호출 →
  /// ③ 성공 시 코치 발화 append·단계 전이 반영·검산 코칭 추가 발화 →
  /// ④ 실패 시 에러만 기록(앱은 죽지 않는다·가용성).
  ///
  /// 이 메서드는 *대화 모드* 전용 — 풀이 단계 전송은 [sendSolution]을 쓴다.
  Future<void> send(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || state.isSending) {
      return; // 빈 입력·전송 중 재진입 방지.
    }

    // 대화 모드는 단계 신호 없이 학생 발화만 보낸다(solutionSteps 미전송).
    await _dispatch(
      studentMessage: ChatMessage.student(trimmed),
      request: CoachRequest(
        studentInput: trimmed,
        polyaState: PolyaState(currentStage: state.polyaState),
      ),
    );
  }

  /// 풀이 단계 모드 — 학생이 *한 줄에 한 단계씩* 적은 풀이를 보낸다.
  ///
  /// 줄 분해(수동 세그먼트)만 L5가 한다(CLAUDE.md): [rawSolution]을 줄(`\n`)로 나눠
  /// 각 줄을 trim하고 빈 줄을 버린 `steps`를 만들어 `solution_steps`로 전송한다.
  /// *수학 검증·단계 의미 추론은 절대 하지 않는다* — 백엔드 `verify_solution`이 단계별
  /// 검증을 수행하고, 응답의 `solution_verification`·`focus_step_index`가 채워지면
  /// 기존 코치 발화·신호 카드가 그대로 동작한다.
  ///
  /// 단계 수 가드: 전이가 0개(steps가 1개 이하)여도 *그대로 전송*한다 — 백엔드가 빈
  /// 검증 결과(n_transitions=0)를 안전하게 처리한다. 단, 유효한 줄이 하나도 없으면
  /// (전부 공백) 보낼 게 없으므로 무시한다.
  Future<void> sendSolution(String rawSolution) async {
    if (state.isSending) {
      return; // 전송 중 재진입 방지.
    }
    final steps = _splitSteps(rawSolution);
    if (steps.isEmpty) {
      return; // 유효한 줄이 하나도 없으면 보낼 게 없다.
    }

    // 학생 메시지는 원문 그대로 표시하되 풀이임을 구분 가능하게 표시한다(isSolution).
    final raw = rawSolution.trim();
    await _dispatch(
      studentMessage: ChatMessage.student(raw, isSolution: true),
      request: CoachRequest(
        studentInput: raw,
        solutionSteps: steps,
        polyaState: PolyaState(currentStage: state.polyaState),
      ),
    );
  }

  /// MathLive 수식 입력(LaTeX)을 평문 수식 줄로 변환해 풀이로 전송한다(MOB-06).
  ///
  /// MathLive는 여러 줄 수식을 `\displaylines{... \\ ...}` LaTeX로 직렬화한다 — 그 원문을 그대로
  /// [sendSolution]에 넘기면 (1) 학생 버블에 LaTeX가 노출되고 (2) 행 구분자 `\\`는 `_splitSteps`의
  /// `'\n'` 분해에 걸리지 않아 단일 0-전이 스텝이 되어 verify가 미결정한다(2026-07-20 실기기 실측).
  /// 여기서 [latexToPlainSolution](순수·표기 매핑)으로 백엔드 verify 계약이 받는 평문 수식 줄
  /// (`'\n'` 구분)로 되돌린 뒤 기존 [sendSolution]에 위임한다 — 버블엔 평문, steps는 인접 전이로
  /// 분해된다. 수학 판정은 서버가 한다(표현≠의미·클라는 표기 변환만·검증 미구현).
  Future<void> sendMathLiveSolution(String latex) =>
      sendSolution(latexToPlainSolution(latex));

  /// OCR로 인식한 풀이를 코치에게 넘긴다(사진 풀이 핸드오프·S1-d).
  ///
  /// 매핑은 백엔드 *정전(canonical) 구현*(`api/ocr_handoff.py`
  /// `ocr_result_to_coach_request`)을 **정확히 미러링**한다 — 착지점마다 빈 값이면 null로
  /// 낮춘다. 특히 [OcrResult.overallConfidence]는 *영역이 하나라도 있을 때만* 넘긴다
  /// (regions 가드): 영역이 0이면 overall_confidence가 0.0인데 그대로 넘기면 0<0.8로
  /// `match_low_quality`가 *거짓 발동*하므로, OCR이 없을 땐 null(dormant)이 옳다.
  ///
  /// [studentInput]은 OCR 산출이 아니라 학생의 *대화 발화*다(호출자 제공·기본 빈 문자열).
  /// 이후 기존 [_dispatch]를 재사용해 코치 발화·단계 전이·검산 코칭이 그대로 동작한다.
  /// 수학·검증 로직은 서버(L3/L4)가 하고 L5는 매핑·전송만 한다(표현≠의미·클라 미구현).
  Future<void> sendOcrSolution(
    OcrResult result, {
    String studentInput = '',
  }) async {
    if (state.isSending) {
      return; // 전송 중 재진입 방지.
    }
    // 학생 버블은 인식한 풀이 원문을 보여준다(없으면 사진을 보냈다는 부드러운 안내).
    final display = result.plainLatex.isEmpty
        ? '(사진에서 읽은 내용이 없어요)'
        : result.plainLatex;
    await _dispatch(
      studentMessage: ChatMessage.student(display, isSolution: true),
      request: CoachRequest(
        studentInput: studentInput,
        // 매핑 표(정전 미러): 빈 값이면 null(발화/dormant 폴백).
        studentSolution: result.plainLatex.isEmpty ? null : result.plainLatex,
        // regions 가드 — 영역 0이면 null(게이트 거짓 발동 방지), 있으면 전체 신뢰도.
        ocrConfidence: result.regions.isEmpty ? null : result.overallConfidence,
        solutionSteps:
            result.solutionSteps.isEmpty ? null : result.solutionSteps,
        solutionStepTypes: result.solutionStepTypes.isEmpty
            ? null
            : result.solutionStepTypes,
        polyaState: PolyaState(currentStage: state.polyaState),
      ),
    );
  }

  /// 학생 메시지를 반영하고 [request]를 서버로 보낸 뒤 응답을 상태에 적용하는 공통 흐름.
  ///
  /// [send]·[sendSolution]이 공유한다 — 성공 시 코치 발화·단계 전이·검산 코칭 추가
  /// 발화, 실패 시 graceful 에러 처리를 *한 곳*에서 한다(중복 구현 금지).
  Future<void> _dispatch({
    required ChatMessage studentMessage,
    required CoachRequest request,
  }) async {
    // ① 학생 메시지를 즉시 반영하고 로딩 상태로 전환한다.
    state = state.copyWith(
      messages: [...state.messages, studentMessage],
      isSending: true,
      error: null,
    );
    // 이전 턴의 완료 신호는 이 턴에 대해 더 이상 참이 아니다 — 새 응답이 오기 전까지 비운다
    // (실패해 응답이 없으면 신호도 없는 상태로 남는다: 낡은 완료 패널을 계속 보이지 않는다).
    ref.read(coachCompletionSignalProvider.notifier).state =
        CoachCompletionSignal.none;

    try {
      // ② 서버 호출 — 영속 세션 경로(WH-1 턴·가설 누적·백엔드 E2E 앵커 정합).
      //    첫 발화면 세션을 생성(활성 문제에 묶음)하고 dialogue_id를 확보하며, 이후 발화는
      //    같은 세션에 턴으로 잇는다. 스테이트리스 `coach()`는 자유 대화 fallback으로 남는다.
      final api = ref.read(coachApiProvider);
      String? dialogueId = state.dialogueId;
      // 이 턴이 *어느 문제*에 대한 것인지 — 완료 신호를 그 문제에 스코프하는 데 쓴다.
      // (세션 생성 경로에서만 읽으면 turns 경로의 신호가 문제 없이 남아 낡은 완료로 오독된다.)
      final String? activeProblemId = ref.read(activeProblemProvider)?.problemId;
      final CoachTurnResult result;
      if (dialogueId == null) {
        // 진단→문제제시에서 넘어온 활성 문제(있으면)에 세션을 묶는다(problem_id 영속).
        result = await api.createSession(request, problemId: activeProblemId);
        dialogueId = result.dialogueId;
      } else {
        result = await api.addTurn(dialogueId, request);
      }
      final CoachResponse response = result.response;

      // ③ 코치 발화를 만든다 — `decision.prompt`(메타인지 유도 발화)를 그대로 표시한다.
      final decision = response.decision;
      final newMessages = <ChatMessage>[
        ...state.messages,
        ChatMessage.coach(
          decision.prompt,
          socraticCategory: decision.socraticCategory,
          response: response,
        ),
      ];

      // 검산 코칭(solution_coaching.trigger.prompt)이 있으면 *추가* 코치 발화로 잇는다.
      final coaching = response.solutionCoaching;
      if (coaching != null && coaching.trigger.prompt.isNotEmpty) {
        newMessages.add(
          ChatMessage.coach(
            coaching.trigger.prompt,
            socraticCategory: coaching.trigger.socraticCategory,
          ),
        );
      }

      // 서버가 내린 단계 전이를 그대로 적용한다(클라 교수학 판단 없음).
      final nextStage = _applyTransition(
        state.polyaState,
        decision.polyaStageToAdvance,
      );

      state = state.copyWith(
        messages: newMessages,
        polyaState: nextStage,
        dialogueId: dialogueId,
        isSending: false,
      );

      // 서버가 내린 완료 신호를 *그대로* 옮긴다(MOB-20 · S3-32 클라 절반). 클라는 완료 여부를
      // 판정하지 않고, attempt 재적재도 하지 않는다(서버가 이미 적재 — 중복 적재 금지 계약).
      ref.read(coachCompletionSignalProvider.notifier).state =
          CoachCompletionSignal(
        problemComplete: result.problemComplete,
        awaitingReflection: result.awaitingReflection,
        completedAttemptId: result.completedAttemptId,
        problemId: activeProblemId,
      );
    } catch (e) {
      // ④ 실패는 graceful — 에러만 기록하고 입력 상태를 복구한다(앱 안 죽음).
      // 침묵 실패 금지(CLAUDE.md): 학생 화면 문구는 부드럽게 두되 예외 *타입명*은 남긴다
      // (본문·PII는 남기지 않는다 — 학생 발화가 요청에 실려 있다).
      debugPrint('코치 턴 실패(${e.runtimeType}) — 대화는 유지하고 재시도를 연다.');
      state = state.copyWith(
        isSending: false,
        error: '코치와 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
      );
    }
  }

  /// 풀이 원문을 줄 단위 단계 리스트로 분해하는 *순수* 함수(부수효과 없음).
  ///
  /// 줄바꿈(`\n`)으로 나눠 각 줄을 trim하고 빈 줄을 제외한다 — 수학 의미 추론·세그먼트
  /// 추정은 하지 않는다(CLAUDE.md: 줄 분해만·검증은 백엔드). `\r\n`도 안전하게 처리한다.
  static List<String> _splitSteps(String rawSolution) {
    return rawSolution
        .split('\n')
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();
  }

  /// 표시된 에러를 지운다(SnackBar 닫힘 등에서 호출).
  void clearError() {
    if (state.error != null) {
      state = state.copyWith(error: null);
    }
  }

  /// 약점개념 학습 장면을 서버에서 받아 대화에 끼운다(L2 진단→L4 장면·S5a 엔드포인트).
  ///
  /// 흐름: ① 전송중 표시·에러 클리어 → ② `POST /v1/scenes/weak-concept`(SceneApi) →
  /// ③ 성공 시 장면 메시지 append(`SceneRenderer`가 렌더) → ④ 실패 시 graceful 에러만
  /// 기록(앱은 죽지 않는다). 장면 생성·검증은 전부 서버(L4)가 하고 클라는 렌더만 한다
  /// (표현≠의미·수학 로직 클라 미구현). 부수효과는 [SceneApi] 호출 하나뿐.
  Future<void> requestScene() async {
    if (state.isSending) {
      return; // 전송 중 재진입 방지.
    }
    state = state.copyWith(isSending: true, error: null);
    try {
      final scene = await ref.read(sceneApiProvider).fetchWeakConceptScene();
      state = state.copyWith(
        messages: [...state.messages, ChatMessage.scene(scene)],
        isSending: false,
      );
    } catch (e) {
      state = state.copyWith(
        isSending: false,
        error: '학습 장면을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.',
      );
    }
  }
}
