// 채팅 화면 — 학생 발화·코치 발화 버블·소크라테스 배지·입력/로딩/에러를 렌더한다.
//
// 경계(CLAUDE.md): 화면은 서버(L4)가 내린 결정을 *그대로 표시*만 한다(표현≠의미).
// 답을 강조하지 않는 톤 — 코치 발화(`decision.prompt`)는 메타인지 유도 발문이라
// 그 문장 자체를 버블로 보여줄 뿐, 정답·정오 강조 UI를 두지 않는다(절대 금기 준수).
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router.dart';
import '../../../theme/spacing.dart';
import '../../ocr/data/ocr_models.dart';
import '../../problems/application/active_problem.dart';
import '../../problems/data/problem_models.dart';
import '../../reports/presentation/defect_report_button.dart';
import '../application/chat_controller.dart';
import '../application/completion_signal.dart';
import '../domain/chat_message.dart';
import '../domain/latex_to_plain.dart';
import '../domain/solution_steps.dart';
import 'coach_emphasis_text.dart';
import 'coach_signal_card.dart';
import 'scene_renderer.dart';

/// 슬로건 — 앱바 부제로 노출(브랜드 정체성·답이 아닌 이유).
const String _slogan = '답이 아닌, 이유를 묻는 수학';

// ── MOB-02 오버플로 방지 상한 ─────────────────────────────────────────────
// 근본 원인(실기기 실측 2026-07-19 M2007J20CG·125px 오버플로): body Column의
// 비신축 자식(문제 배너·입력 영역)의 고정 높이 합이, 키보드(IME)로
// resizeToAvoidBottomInset이 줄인 body 가용 높이를 넘으면 Expanded(메시지 리스트)가
// 0까지 줄어도 RenderFlex가 넘친다. 특히 배너는 발문·선택지 길이에 비례해 *상한 없이*
// 커지는 유일한 자식이라 대화 모드에서도 넘쳤다. 고정 px 상한 대신 *가용 높이 대비
// 비율* 상한을 걸어 어떤 화면·키보드 높이에서도 비신축 합이 body를 다 먹지 않게 한다.
// (resizeToAvoidBottomInset을 끄는 우회는 금지 — 입력이 키보드에 가려지면 안 된다.)

/// 문제 배너 최대 높이 — body 가용 높이 대비 비율. 초과분은 배너 내부 스크롤.
const double _bannerMaxHeightFraction = 0.3;

/// 풀이 단계 영역이 차지할 수 있는 body 가용 높이 비율 상한.
const double _stepAreaMaxHeightFraction = 0.25;

/// 단계 영역 절대 상한(px) — S3-05 값 유지(행 ~54px 3개 분량). 공간이 넉넉하면 이
/// 값이 걸리고, 키보드로 좁아지면 위 비율 상한이 먼저 걸린다(둘 중 작은 쪽).
const double _stepAreaMaxHeight = 162;

/// 객관식 선택지 목록 영역이 차지할 수 있는 body 가용 높이 비율 상한(S3-17).
const double _choiceAreaMaxHeightFraction = 0.25;

/// 선택지 목록 영역 절대 상한(px) — 행 ~48px 3개 분량. 공간이 넉넉하면 이 값이 걸리고,
/// 키보드로 좁아지면 위 비율 상한이 먼저 걸린다(둘 중 작은 쪽·단계 영역과 동일 규칙).
const double _choiceAreaMaxHeight = 160;

/// 빈 단계 필드 예시 힌트 (MOB-05) — 학생에게 *앱이 알아듣는 입력 형태*를 스스로 안내한다.
/// 등식 한 줄·근 나열 등 백엔드 verify가 결정하는 자연 표기(MOB-06·S3-06)라, 그대로 따라 쓰면
/// 검증 결정 구간에 들어간다. 왼쪽 번호 라벨과 중복되던 "단계 N"을 대체. 정오 강조·부정 표현 없음.
/// 필드가 늘어도 `index % length`로 순환한다.
const List<String> _stepHintExamples = <String>[
  '예: 2x+3=7',
  '예: x=2',
  '예: (x-2)(x-3)=0',
];

/// 활성 문항이 객관식인지 판정한다(S3-12→S3-17 — 섀도 브랜치 회수).
///
/// 규칙: `questionFormat == '객관식'`이거나 `choices`가 비어있지 않으면 객관식으로 취급한다
/// (둘 중 하나면 MC). 단, 실제 *목록 렌더*는 보수적으로 [_renderableChoices]가 결정한다 —
/// 탭할 선택지(choices)가 없으면 어포던스를 만들 수 없기 때문이다.
bool _isMultipleChoice(Problem problem) {
  if (problem.questionFormat == '객관식') {
    return true;
  }
  final choices = problem.choices;
  return choices != null && choices.isNotEmpty;
}

/// 렌더 가능한 선택지 목록(객관식이고 choices 보유)·아니면 null(주관식·선택지 없음).
///
/// 이 함수가 null을 돌려주면 선택지 목록을 아예 그리지 않는다 — 주관식 문항엔 영향이 0이다.
List<String>? _renderableChoices(Problem? problem) {
  if (problem == null || !_isMultipleChoice(problem)) {
    return null;
  }
  final choices = problem.choices;
  if (choices == null || choices.isEmpty) {
    return null; // MC지만 탭할 선택지가 없으면 목록을 만들 수 없다(보수적).
  }
  return choices;
}

/// 입력 모드 — 대화(단일 라인) 또는 풀이 단계(단계 리스트 편집기·묶음 제출).
enum _InputMode {
  /// 자유 대화(기존 동작) — `send`로 학생 발화만 전송.
  conversation,

  /// 풀이 단계 입력 — 단계 리스트 편집기로 여러 단계를 *한 메시지로 묶어*
  /// `sendSolution`으로 전송(`'\n'` 조인 → 컨트롤러가 다시 줄 분해).
  solution,
}

/// 메인 대화 화면.
///
/// 본문은 메시지 ListView(학생/코치 버블 구분)·하단 입력 행(TextField + 전송)으로 구성된다.
/// 라우팅(go_router)·인증·세션 영속은 후속 슬라이스다 — 이번엔 단일 화면 채팅 플로우만.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _inputController = TextEditingController();

  /// 풀이 단계 편집기 상태 핸들 — MathLive "완료"가 입력 수식을 이 편집기의 단계 필드에
  /// 채우기 위해 쓴다(MOB-07). 편집기는 풀이 단계 모드에서만 트리에 있으므로 currentState는
  /// 그때만 유효하다(아니면 폴백).
  final GlobalKey<_SolutionStepsEditorState> _stepsEditorKey =
      GlobalKey<_SolutionStepsEditorState>();

  /// 현재 입력 모드(기본=대화). 토글로 풀이 단계 모드와 전환한다.
  _InputMode _mode = _InputMode.conversation;

  @override
  void dispose() {
    _inputController.dispose();
    super.dispose();
  }

  /// 입력 모드를 대화↔풀이 단계로 토글한다(입력 내용은 유지하지 않고 비운다).
  void _toggleMode() {
    setState(() {
      _mode = _mode == _InputMode.conversation
          ? _InputMode.solution
          : _InputMode.conversation;
      _inputController.clear();
    });
  }

  /// 대화 입력을 `send`(학생 발화)로 보내고 입력 필드를 비운다.
  ///
  /// 이 메서드는 *대화 모드 전용* — 풀이 단계 제출은 [_onSendSolutionSteps]가 담당한다
  /// (단계 리스트 편집기가 합친 원문을 받는다).
  /// 선택지 행 탭 → 그 항목의 *값*을 기존 `send`(`student_input`) 경로로 제출한다(S3-17).
  /// 번호→값 매핑은 화면 표현일 뿐 정답 판정·완료는 서버 권위다(클라는 값 제출만·표현≠의미).
  Future<void> _onChoiceSelected(String choice) async {
    await ref.read(chatControllerProvider.notifier).send(choice);
  }

  Future<void> _onSend() async {
    final text = _inputController.text;
    if (text.trim().isEmpty) {
      return;
    }
    _inputController.clear();
    await ref.read(chatControllerProvider.notifier).send(text);
  }

  /// 단계 리스트 편집기가 합친 풀이 원문(`'\n'` 조인)을 `sendSolution`으로 보낸다.
  ///
  /// 조인은 편집기(UI)가, 줄 분해는 컨트롤러(`_splitSteps`)가 한다 — 기존 L5 계약
  /// (`sendSolution(String)` 시그니처·줄 분해 로직)은 완전 무변경이다. 실기기 실측
  /// (2026-07-19): verify는 *인접 두 단계의 전이*를 판정하므로 여러 단계를 한 메시지로
  /// 묶어야만 correct/incorrect가 결정된다 — 이 묶음 제출이 편집기의 존재 이유다.
  Future<void> _onSendSolutionSteps(String joined) async {
    if (joined.trim().isEmpty) {
      return;
    }
    await ref.read(chatControllerProvider.notifier).sendSolution(joined);
  }

  /// 약점개념 학습 장면을 요청한다(서버 L2 진단→L4 장면·S5a 엔드포인트). 결과는 장면
  /// 메시지로 대화에 끼워져 [SceneRenderer]로 렌더된다(컨트롤러가 상태 전이·에러 처리).
  Future<void> _onRequestScene() async {
    await ref.read(chatControllerProvider.notifier).requestScene();
  }

  /// 풀이 사진 OCR 화면(`/ocr`)으로 진입하고, 돌아온 인식 결과를 코치에게 넘긴다(S1-d).
  ///
  /// OCR 화면은 채팅을 알지 못한 채 `context.pop(result)`로 [OcrResult]만 돌려준다(단방향
  /// chat→ocr 의존). 여기서 결과를 받아 `sendOcrSolution`으로 매핑·전송한다 — 사용자가 그냥
  /// 뒤로 가면(null) 아무 일도 하지 않는다.
  Future<void> _onCaptureSolution() async {
    final result = await context.push<OcrResult>(AppRoutes.ocrPath);
    if (result != null && mounted) {
      await ref.read(chatControllerProvider.notifier).sendOcrSolution(result);
    }
  }

  /// 수식(MathLive) 입력 화면(`/math-input`)으로 진입하고, 돌아온 LaTeX를 풀이로 넘긴다(S1).
  ///
  /// 입력 화면은 채팅을 알지 못한 채 `context.pop(latex)`로 LaTeX만 돌려준다(OCR과 동형·단방향
  /// chat→math-input 의존). 받은 LaTeX를 평문 수식(표기 매핑·MOB-06)으로 바꿔 **풀이 단계 편집기
  /// 필드에 채운다**(MOB-07) — 학생이 숨은 줄바꿈(⊕) 제스처 없이 눈에 보이는 단계 필드로 다단계를
  /// 쌓고 "풀이 제출"하게 한다. 여러 줄(⊕로 만든 `\displaylines`)이면 여러 필드에 분배된다. 편집기가
  /// 없거나(모드 전환 등) 채울 게 없으면 기존 즉시 제출 경로로 폴백한다(방어). 취소(null)·빈 입력이면
  /// 아무 일도 하지 않는다(변환·줄 분해·검증은 컨트롤러·백엔드가 한다).
  Future<void> _onMathInput() async {
    final latex = await context.push<String>(AppRoutes.mathInputPath);
    if (latex == null || latex.trim().isEmpty || !mounted) {
      return; // 취소·빈 입력.
    }
    final plain = latexToPlainSolution(latex);
    final filled =
        _stepsEditorKey.currentState?.fillFromMathInput(plain) ?? false;
    if (!filled) {
      // 편집기 미마운트(모드 전환 등)·빈 변환 → 기존 즉시 제출 경로 폴백(계약 유지).
      await ref
          .read(chatControllerProvider.notifier)
          .sendMathLiveSolution(latex);
    }
  }

  /// 완료 후 '다음 문항으로' — 소비한 완료 신호를 비우고 문제 화면으로 넘긴다(MOB-20).
  ///
  /// 여기서 어떤 제출도 하지 않는다 — attempt 적재·숙달 전파는 서버가 완료 턴에서 이미 끝냈다
  /// (중복 적재 금지 계약). 다음 문항 *선정*도 서버(L2 CAT)가 `/v1/me/next-problem`에서 하고,
  /// 문제 화면이 진입 시 그것을 부른다. 신호를 먼저 비우는 이유: 돌아왔을 때 낡은 완료 패널이
  /// 남아 있으면 이미 끝난 문항의 완료를 새 문항의 완료로 오독하게 된다.
  void _onNextProblem() {
    ref.read(coachCompletionSignalProvider.notifier).state =
        CoachCompletionSignal.none;
    context.go(AppRoutes.problemPath);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatControllerProvider);
    // 서버가 내린 완료 신호(MOB-20) — 클라는 판정하지 않고 이 권위값만 보고 어포던스를 바꾼다.
    //
    // **활성 문제에 스코프한다**: 이 provider는 autoDispose가 아니고 하단 탭이 상태를 보존하므로,
    // 학생이 홈에서 다른 문제를 열면(problem_screen이 activeProblemProvider만 교체) 이전 완료
    // 신호가 살아남아 *새 문제*의 선택지를 감추고 *이전* attempt의 완료 패널을 띄운다 — 새로 고른
    // 문제를 건너뛰게 만든다. 신호의 problemId가 지금 문제와 다르면 신호가 없는 것으로 다룬다
    // (리스너가 아니라 렌더 시점 대조라 경합이 없다).
    final CoachCompletionSignal rawCompletion =
        ref.watch(coachCompletionSignalProvider);
    final CoachCompletionSignal completion =
        rawCompletion.appliesTo(ref.watch(activeProblemProvider)?.problemId)
            ? rawCompletion
            : CoachCompletionSignal.none;

    // 에러가 생기면 SnackBar로 알리고(가용성·앱은 죽지 않음) 상태를 지운다.
    ref.listen<String?>(
      chatControllerProvider.select((s) => s.error),
      (previous, next) {
        if (next != null && context.mounted) {
          ScaffoldMessenger.of(context)
            ..hideCurrentSnackBar()
            ..showSnackBar(SnackBar(content: Text(next)));
          ref.read(chatControllerProvider.notifier).clearError();
        }
      },
    );

    return Scaffold(
      appBar: AppBar(
        title: const Text('WhyMath'),
        actions: [
          // 풀이 사진 보내기 — OCR 화면으로 진입(전송 중엔 비활성·중복 진입 방지).
          // 완료 중에도 비활성: `sendOcrSolution`도 `_dispatch`를 타 턴을 만든다(입력바와 동일 사유).
          IconButton(
            icon: const Icon(Icons.camera_alt_outlined),
            tooltip: '풀이 사진 보내기',
            onPressed: state.isSending || completion.problemComplete
                ? null
                : _onCaptureSolution,
          ),
          // 약점개념 학습 장면 요청 — 전송 중엔 비활성(중복 요청 방지).
          IconButton(
            icon: const Icon(Icons.auto_awesome_outlined),
            tooltip: '약점 개념 장면 보기',
            onPressed: state.isSending ? null : _onRequestScene,
          ),
          // 결함 신고(RPT-01) — 문항·AI응답·수식 오류를 학생이 알릴 유일한 경로.
          // 활성 문제가 있으면 대상 참조로 함께 실어 보낸다(자유 대화면 problemId=null).
          DefectReportButton(
            problemId: ref.watch(activeProblemProvider)?.problemId,
          ),
        ],
        // 슬로건을 부제로 — 답이 아닌 이유를 묻는다는 정체성을 항상 노출.
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(20),
          child: Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs6),
            child: Text(_slogan, style: Theme.of(context).textTheme.bodySmall),
          ),
        ),
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          // 키보드(IME)가 올라오면 Scaffold(resizeToAvoidBottomInset 기본 true)가
          // body를 그만큼 줄인다. 그 *줄어든 실제 가용 높이*를 기준으로 비신축 자식
          // (배너·단계 영역)의 상한을 계산한다 — 입력은 키보드 위에 남고(리사이즈 유지)
          // Column은 넘치지 않는 근본 수정(MOB-02).
          final double bodyHeight = constraints.maxHeight;
          final double bannerMaxHeight = bodyHeight * _bannerMaxHeightFraction;
          final double stepAreaMaxHeight = math.min(
            _stepAreaMaxHeight,
            bodyHeight * _stepAreaMaxHeightFraction,
          );
          final double choiceAreaMaxHeight = math.min(
            _choiceAreaMaxHeight,
            bodyHeight * _choiceAreaMaxHeightFraction,
          );
          return Column(
            children: [
              // 풀이 중인 문제를 채팅 위에 상시 노출(접기 가능) — 실기기 시연 피드백:
              // "문제가 한 화면에 같이 안 나옴". 학생이 문제를 다시 보러 화면을 떠나지 않게 한다.
              _ActiveProblemBanner(maxHeight: bannerMaxHeight),
              Expanded(
                child: state.messages.isEmpty
                    ? const _EmptyHint()
                    : ListView.builder(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        itemCount: state.messages.length,
                        itemBuilder: (context, index) =>
                            _MessageBubble(message: state.messages[index]),
                      ),
              ),
              // 코치 응답 대기 중 선형 인디케이터(은근한 로딩·도파민 카운트다운 아님).
              if (state.isSending) const LinearProgressIndicator(minHeight: 2),
              // 객관식 선택지 세로 번호 목록(S3-12→S3-17 — 섀도 브랜치 회수) — 활성 문항이
              // 객관식일 때 보기를 "N. [값]" 세로 목록으로 노출하고, 학생은 *번호 행을 탭*해
              // 그 값을 제출한다(입력 영역 바로 위·주 어포던스).
              //  · *대화 모드에서만* 렌더한다 — 풀이 단계 모드는 학생이 다단계 풀이를 *직접
              //    구성*하는 별도 어포던스이고, 그 편집기가 이미 좁은 세로 공간을 쓰므로
              //    선택지 목록을 겹쳐 넣지 않는다(MOB-02 오버플로 불변식 보존).
              //  · 완료(problemComplete)·돌아보기 대기(awaitingReflection) 중에도 감춘다
              //    (MOB-20에서 배선 완료 — 서버 완료 신호 3필드가 클라에 도착한다). 완료 후에는
              //    같은 문항의 보기를 다시 고를 이유가 없고, 돌아보기 턴은 *번호 선택*이 아니라
              //    학생의 근거 서술을 받아야 하므로 진행을 보류한다(서버 docstring 요구 UX).
              // 주관식 문항엔 위젯이 스스로 빈 자리를 반환해 영향이 0이다(주관식 흐름 무변경).
              if (_mode == _InputMode.conversation &&
                  !completion.problemComplete &&
                  !completion.awaitingReflection)
                _ChoiceButtons(
                  enabled: !state.isSending,
                  maxHeight: choiceAreaMaxHeight,
                  onSelected: _onChoiceSelected,
                ),
              // 돌아보기 대기 안내 — 정답 도달 후 "왜 그렇게 됐는지" 한 턴을 받는 구간임을
              // 학생에게 알린다(정오 강조·정답 노출 없음·재촉 없음).
              if (completion.awaitingReflection) const _ReflectionNotice(),
              // 완료 → '다음 문항으로 진행' 어포던스. 서버가 attempt를 이미 적재했으므로
              // 여기서 어떤 제출도 하지 않는다(재적재 금지) — 다음 문제 화면으로 넘길 뿐이다.
              if (completion.problemComplete)
                _CompletionPanel(
                  attemptId: completion.completedAttemptId,
                  onNext: _onNextProblem,
                ),
              _InputBar(
                controller: _inputController,
                stepsEditorKey: _stepsEditorKey,
                // 완료는 *종단 상태*다 — 여기서 한 턴을 더 보내면 서버가 already_completed로
                // no-op 처리해 problem_complete=false를 돌려주고(coach.py:2630·l4/completion.py),
                // 그러면 유일한 '다음 문항으로'가 사라진 채 끝난 세션에 묶인다. 그래서 완료 중에는
                // 턴을 만드는 입력을 막는다(진행 경로는 '다음 문항으로' 하나만 남긴다).
                enabled: !state.isSending && !completion.problemComplete,
                mode: _mode,
                stepAreaMaxHeight: stepAreaMaxHeight,
                onSend: _onSend,
                onSendSolution: _onSendSolutionSteps,
                onToggleMode: _toggleMode,
                onMathInput: _onMathInput,
              ),
            ],
          );
        },
      ),
    );
  }
}

/// 풀이 중인 문제 배너 — 활성 문제(발문·과목)를 채팅 상단에 접이식으로 상시 노출한다.
///
/// 활성 문제가 없으면(자유 대화 진입) 아무것도 그리지 않는다. 발문이 길면 접어서 채팅
/// 공간을 확보한다(기본 펼침 — 시연·풀이 맥락 우선). 정답·힌트는 어떤 형태로도 싣지
/// 않는다(서버가 답을 안 주는 계약과 동일·표현≠의미).
class _ActiveProblemBanner extends ConsumerStatefulWidget {
  const _ActiveProblemBanner({required this.maxHeight});

  /// 배너 최대 높이 — 화면(LayoutBuilder)이 body 가용 높이의 비율로 계산해 내려준다.
  /// 발문·선택지가 아무리 길어도 이 상한을 넘지 않고 초과분은 내부 스크롤로 가둔다
  /// (MOB-02 — 배너는 키보드 표시 시 Column을 넘치게 하던 유일한 *비유계* 자식이었다).
  final double maxHeight;

  @override
  ConsumerState<_ActiveProblemBanner> createState() =>
      _ActiveProblemBannerState();
}

class _ActiveProblemBannerState extends ConsumerState<_ActiveProblemBanner> {
  /// 펼침 상태(기본 펼침) — 학생이 접으면 발문을 숨기고 한 줄 요약만 남긴다.
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    final Problem? problem = ref.watch(activeProblemProvider);
    if (problem == null) {
      return const SizedBox.shrink();
    }
    final theme = Theme.of(context);
    final question = problem.questionText ?? problem.questionTextMd;

    return Material(
      color: theme.colorScheme.surfaceContainerHighest,
      // 접근성(MOB-13): 탭 노드에 라벨·button 역할·펼침 상태를 부여한다. InkWell은
      // excludeFromSemantics로 중복 시맨틱 노드를 없애고 시각 리플·탭만 담당하며,
      // 스크린리더 라벨·활성화 액션은 이 Semantics가 제공한다(펼침 내용은 하위 텍스트로 읽힘).
      child: Semantics(
        button: true,
        label: _expanded ? '풀이 중인 문제, 접기' : '풀이 중인 문제, 펼치기',
        onTap: () => setState(() => _expanded = !_expanded),
        child: InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          excludeFromSemantics: true,
        // 상한 초과분은 내부 스크롤 — 키보드가 올라와도 발문 전체를 볼 수 있는 경로는
        // 유지하면서(스크롤) 배너가 채팅·입력 영역을 밀어내지 않게 한다(MOB-02).
        child: ConstrainedBox(
          // 접근성(MOB-14): 접힌 배너도 최소 48dp 탭 타깃. minHeight를 maxHeight로 clamp해
          // (math.min) MOB-02의 fraction 상한을 절대 넘지 않으면서 min>max assert도 피한다.
          constraints: BoxConstraints(
            minHeight: math.min(48, widget.maxHeight),
            maxHeight: widget.maxHeight,
          ),
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, AppSpacing.sm10, AppSpacing.md, AppSpacing.sm10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        Icons.menu_book_outlined,
                        size: 18,
                        color: theme.colorScheme.primary,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          '풀이 중인 문제 · ${problem.subject}'
                          '${problem.subunit != null ? ' · ${problem.subunit}' : ''}',
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      Icon(
                        _expanded ? Icons.expand_less : Icons.expand_more,
                        size: 20,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ],
                  ),
                  if (_expanded && question != null) ...[
                    const SizedBox(height: AppSpacing.xs6),
                    Text(question, style: theme.textTheme.bodyMedium),
                    if (problem.choices != null &&
                        problem.choices!.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xs),
                      for (var i = 0; i < problem.choices!.length; i++)
                        Text(
                          '${i + 1}. ${problem.choices![i]}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                    ],
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
      ),
    );
  }
}

/// 객관식 선택지 세로 번호 목록 — 활성 문항이 객관식일 때 보기를 "N. [값]" 세로 목록으로
/// 렌더하고, 각 행을 탭하면 그 항목의 *값*을 제출한다(S3-17 — S3-12 가로 칩에서 리팩터).
///
/// 배경(Kiki UX·실기기 실측 2026-07-22): ① 서버 `verify_final_answer`는 *정확한 선택지 값*("2")만
/// correct로 판정하고 자연 표현("답은 2"·"2개요")·근 나열은 unverifiable로 떨어져 완료가 안 됐다.
/// ② S3-12는 값을 가로 칩에 통째로 넣어, 값이 길어 여러 줄이 되면 어색했다. 그래서 값이 아니라
/// *번호*를 고르는 게 자연스럽다는 방향으로, 각 보기를 "N. [값]" 세로 행으로 렌더한다(번호는 문항
/// 배너의 1-기반 "N." 표기와 시각 일치·값은 길면 줄바꿈).
///
/// 탭 → *값 제출*(서버 계약 무변경): 번호를 *타이핑*하면 "2"가 2번인지 값 2인지 모호해(서버 거짓
/// correct 위험) 학생은 번호 행을 *탭*만 하고, 클라가 `choices[i]`(값)를 기존 `send`(`student_input`)
/// 경로로 제출한다 — 모호성 0·서버는 정확한 값으로 correct→돌아보기→완료(주관식과 동일 흐름·S3-10).
/// 번호→값 매핑은 화면 표현일 뿐이고 정답 판정·완료는 서버 권위다(클라는 값 제출만·정답 미보유·표현≠의미).
///
/// 경계(CLAUDE.md): WhyMath는 객관식 양산 앱이 아니다 — 객관식은 부차이고 이 목록은 *우아한 완료*만
/// 보장한다. 정오·정답률·빨강 카운트다운 등 부정 강화 UI는 두지 않는다(정서 안전·표현≠의미).
/// 주관식·선택지 없음이면 스스로 빈 자리(SizedBox.shrink)를 반환해 주관식 흐름엔 영향이 0이다.
class _ChoiceButtons extends ConsumerWidget {
  const _ChoiceButtons({
    required this.enabled,
    required this.maxHeight,
    required this.onSelected,
  });

  /// 행 활성 여부(전송 중엔 비활성 — 기존 입력 행과 동일 규칙·중복 제출 방지).
  final bool enabled;

  /// 선택지 목록 영역 최대 높이 — 화면(LayoutBuilder)이 키보드로 줄어든 body 가용 높이에
  /// 맞춰 계산해 내려준다(MOB-02). 보기가 많거나 값이 길어 초과하면 내부 스크롤로 가둔다(Column 안 넘침).
  final double maxHeight;

  /// 선택지 행 탭 콜백 — 그 항목의 *값*을 그대로(`student_input`) 코치 턴으로 제출한다.
  final Future<void> Function(String choice) onSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final choices = _renderableChoices(ref.watch(activeProblemProvider));
    if (choices == null) {
      return const SizedBox.shrink(); // 주관식·선택지 없음 → 아무것도 그리지 않는다.
    }
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 은근한 안내 — 답을 재촉·정오 강조하지 않는 톤(정서 안전). 번호 선택임을 명시한다.
          Text(
            '보기 번호를 골라 보세요',
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 6),
          // 세로 번호 목록 — 각 행 "N. [값]"(번호 앞 고정·값은 길면 줄바꿈). 탭하면 그 항목의
          // *값*(choices[i])을 서버 verify가 받는 정확한 형태로 제출한다(자유 타이핑 브리틀함 우회).
          // 높이를 가둬(내부 스크롤) 보기가 많거나 값이 길어도 화면(입력 영역)을 밀어내지 않는다(MOB-02).
          ConstrainedBox(
            constraints: BoxConstraints(maxHeight: maxHeight),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var i = 0; i < choices.length; i++)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: _ChoiceRow(
                        // 1-기반 번호 — 문항 배너("N. [값]")와 표기 일치(혼동 방지).
                        number: i + 1,
                        value: choices[i],
                        enabled: enabled,
                        onTap: () => onSelected(choices[i]),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 돌아보기(메타인지) 대기 안내 — 서버 `awaiting_reflection`이 참인 동안만 그린다(MOB-20).
///
/// 정답에 도착했다는 사실 자체를 축하·강조하지 않는다(도파민 설계 금지·정답 노출 금지). 지금은
/// "왜 그렇게 됐는지"를 한 턴 말하는 구간임을 알리는 *안내*일 뿐이며, 이 구간 동안 선택지 목록은
/// 감춰져 번호 선택으로 흘려보낼 수 없다(진행 보류). 판정은 하지 않는다 — 서버 값의 표시뿐이다.
class _ReflectionNotice extends StatelessWidget {
  const _ReflectionNotice();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.md, AppSpacing.xs6, AppSpacing.md, 0),
      child: Semantics(
        // 스크린리더에 한 덩어리로 읽힌다(아이콘은 장식이라 시맨틱에서 제외).
        container: true,
        label: '돌아보기 차례입니다. 어떻게 그렇게 됐는지 한 번만 이야기해 주세요.',
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ExcludeSemantics(
              child: Icon(
                Icons.chat_bubble_outline,
                size: 18,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: ExcludeSemantics(
                child: Text(
                  '돌아보기 차례예요 — 어떻게 그렇게 됐는지 한 번만 이야기해 볼까요?',
                  style: theme.textTheme.bodyMedium,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 완료 패널 — 서버 `problem_complete`가 참인 동안만 그린다(MOB-20 · '다음 문항으로 진행' 신호).
///
/// [attemptId]는 서버가 적재한 ProblemAttempt PK다. **학생에게 표시하지 않는다**(UUID는 학습
/// 정보가 아니다) — 완료 1건과 패널 1개를 묶는 *동일성 키*로만 쓴다: 연속 완료에서 위젯이
/// 재사용되지 않고 새로 만들어져, 이전 문항의 패널이 그대로 남아 보이는 상태를 구조적으로 막는다.
/// 정답·점수·정답률은 어떤 형태로도 싣지 않는다(절대 금기).
class _CompletionPanel extends StatelessWidget {
  _CompletionPanel({required this.attemptId, required this.onNext})
      // 완료 attempt 1건 = 패널 1개. 서버 계약상 완료면 id가 오지만, 오지 않은 경우를 'none'
      // 으로 *조용히 같게* 만들지 않고 그대로 구분되게 둔다(추정 금지·부재는 부재로).
      : super(key: ValueKey<String>('completion-panel-${attemptId ?? 'none'}'));

  /// 서버가 적재한 ProblemAttempt PK(완료 아니면 이 위젯 자체가 그려지지 않는다)·없으면 null.
  final String? attemptId;

  /// '다음 문항으로' 탭 콜백 — 신호를 비우고 문제 화면으로 넘긴다(클라 제출 없음).
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.md, AppSpacing.xs6, AppSpacing.md, 0),
      child: Row(
        children: [
          Expanded(
            child: Text(
              '이 문제는 여기까지예요. 다음 문항으로 가 볼까요?',
              style: theme.textTheme.bodyMedium,
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          // 접근성(MOB-14): 최소 48dp 탭 타깃.
          ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
            child: FilledButton.tonal(
              onPressed: onNext,
              child: const Text('다음 문항으로'),
            ),
          ),
        ],
      ),
    );
  }
}

/// 선택지 한 행 — 앞에 1-기반 번호("N.")·뒤에 값(길면 줄바꿈)을 담은 탭 가능한 전폭 행.
///
/// 배너의 "N. [값]" 표기와 번호 스타일을 맞춰 시각 일관을 유지하고, 값이 길어 여러 줄이 돼도
/// 번호는 앞(위)에 고정된다(멀티라인 수용). 탭하면 [onTap]이 그 항목의 값을 제출한다. 접근성:
/// 최소 높이 48dp(44dp+)·번호+값이 하나의 시맨틱 버튼으로 읽힌다.
class _ChoiceRow extends StatelessWidget {
  const _ChoiceRow({
    required this.number,
    required this.value,
    required this.enabled,
    required this.onTap,
  });

  /// 1-기반 보기 번호(배너 표기와 일치).
  final int number;

  /// 보기 값 — 서버 verify가 받는 정확한 형태 그대로(길면 줄바꿈).
  final String value;

  /// 활성 여부(전송 중엔 비활성).
  final bool enabled;

  /// 행 탭 콜백 — 이 항목의 값을 제출한다.
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return OutlinedButton(
      onPressed: enabled ? onTap : null,
      style: OutlinedButton.styleFrom(
        alignment: Alignment.centerLeft, // 값이 짧아도 번호가 왼쪽에 고정.
        minimumSize: const Size.fromHeight(48), // 접근성 44dp+ 탭 타겟.
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start, // 멀티라인 값 첫 줄에 번호 정렬.
        children: [
          // 번호 라벨 — 배너와 같은 "N." 표기(1-기반). 어포던스라 primary 색으로 도드라지게.
          Text(
            '$number.',
            style: theme.textTheme.titleMedium?.copyWith(
              color: theme.colorScheme.primary,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 10),
          // 값 — 길면 자연스럽게 줄바꿈(멀티라인)·짧으면 한 줄. 번호는 앞에 고정된다.
          Expanded(
            child: Text(value, softWrap: true),
          ),
        ],
      ),
    );
  }
}

/// 메시지가 없을 때 보여줄 안내 — 답을 재촉하지 않는 톤.
class _EmptyHint extends StatelessWidget {
  const _EmptyHint();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: Text(
          '어떤 문제를 함께 생각해 볼까요?',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
      ),
    );
  }
}

/// 대화 한 줄 버블 — 학생은 오른쪽·코치는 왼쪽 정렬로 구분한다.
class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    // 장면 메시지면 SceneRenderer로만 렌더한다(빈 텍스트 버블 없이·S5e).
    final scene = message.scene;
    if (scene != null) {
      return SceneRenderer(scene: scene);
    }

    final theme = Theme.of(context);
    final isCoach = message.isCoach;
    final alignment = isCoach ? Alignment.centerLeft : Alignment.centerRight;
    final bubbleColor = isCoach
        ? theme.colorScheme.surfaceContainerHighest
        : theme.colorScheme.primaryContainer;
    final category = message.socraticCategory;
    final showBadge = isCoach && category != null && category.isNotEmpty;

    final bubble = Align(
      alignment: alignment,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md14, vertical: AppSpacing.sm10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        decoration: BoxDecoration(
          color: bubbleColor,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // 소크라테스 카테고리 배지(있을 때만) — 어떤 발문 전략인지 메타 표시.
            if (showBadge) _SocraticBadge(category: category),
            if (showBadge) const SizedBox(height: AppSpacing.xs6),
            // 코치 발화만 템플릿 `*...*` 강조를 굵게 렌더한다(MOB-04·표현≠의미).
            // 학생 버블은 원문 그대로 — 학생 입력의 별표는 곱셈 기호(`3*4`)일 수
            // 있어 어떤 해석도 하지 않는다.
            if (isCoach)
              CoachEmphasisText(message.text)
            else
              // 접근성(MOB-13): primaryContainer 위 텍스트는 onPrimaryContainer 롤로
              // (기본 onSurface는 다크에서 대비 부족). 기본 스타일에 색만 병합한다.
              Text(
                message.text,
                style: TextStyle(color: theme.colorScheme.onPrimaryContainer),
              ),
          ],
        ),
      ),
    );

    // 코치 발화에 원본 응답이 있으면 버블 아래에 verify 신호 카드를 덧붙인다.
    // (학생 버블엔 response가 없어 카드가 붙지 않는다. 카드는 신호가 없으면 스스로
    //  빈 위젯을 반환하므로 여기선 단순히 존재 여부만 보고 끼워 넣는다.)
    final response = message.response;
    if (isCoach && response != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          bubble,
          CoachSignalCard(response: response),
        ],
      );
    }

    return bubble;
  }
}

/// 소크라테스 카테고리 배지 — 코치 발화의 발문 전략 라벨.
class _SocraticBadge extends StatelessWidget {
  const _SocraticBadge({required this.category});

  final String category;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.hairline),
      decoration: BoxDecoration(
        color: theme.colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        category,
        style: theme.textTheme.labelSmall?.copyWith(
          color: theme.colorScheme.onSecondaryContainer,
        ),
      ),
    );
  }
}

/// 하단 입력 행 — 대화 모드는 단일 입력+전송, 풀이 모드는 단계 리스트 편집기.
///
/// 풀이 단계 모드는 [_SolutionStepsEditor]가 담당한다: 채팅 습관(한 메시지 한 줄)대로
/// 보내면 매 턴이 외톨이 단계(전이 0)라 verify가 전부 unverifiable이 되므로(실기기 실측),
/// 여러 단계를 한 메시지로 *묶는* 제출을 UI 구조로 유도한다(단계 구조의 시각화 =
/// 사고 구조화·메타인지 정합). 대화 모드는 기존 동작(Enter 전송)을 그대로 유지한다.
class _InputBar extends StatelessWidget {
  const _InputBar({
    required this.controller,
    required this.stepsEditorKey,
    required this.enabled,
    required this.mode,
    required this.stepAreaMaxHeight,
    required this.onSend,
    required this.onSendSolution,
    required this.onToggleMode,
    required this.onMathInput,
  });

  /// 대화 모드 입력 컨트롤러(풀이 모드는 편집기가 자체 컨트롤러를 쓴다).
  final TextEditingController controller;

  /// 풀이 단계 편집기 상태 핸들 — MathLive 입력을 단계 필드에 채우는 데 쓴다(MOB-07).
  final GlobalKey<_SolutionStepsEditorState> stepsEditorKey;

  final bool enabled;
  final _InputMode mode;

  /// 풀이 단계 영역 최대 높이 — 화면(LayoutBuilder)이 키보드로 줄어든 body 가용
  /// 높이에 맞춰 계산해 내려준다(MOB-02 — 좁은 화면에서 입력 영역이 넘치지 않게).
  final double stepAreaMaxHeight;

  /// 대화 모드 전송(학생 발화 `send`).
  final Future<void> Function() onSend;

  /// 풀이 모드 제출 — 편집기가 합친 원문(`'\n'` 조인)을 받아 `sendSolution`으로 보낸다.
  final Future<void> Function(String joined) onSendSolution;

  final VoidCallback onToggleMode;
  final Future<void> Function() onMathInput;

  @override
  Widget build(BuildContext context) {
    final isSolution = mode == _InputMode.solution;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 모드 토글 행 — 대화↔풀이 단계 전환(은근한 라벨·답 강조 없음).
            Row(
              children: [
                IconButton(
                  icon: Icon(
                    isSolution
                        ? Icons.chat_bubble_outline
                        : Icons.format_list_numbered,
                  ),
                  tooltip: isSolution ? '대화로 전환' : '풀이 단계로 전환',
                  onPressed: enabled ? onToggleMode : null,
                ),
                Text(
                  isSolution ? '풀이 단계' : '대화',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                // 풀이 모드에서만 — MathLive 수식 입력기로 진입(로드맵 S1 "MathLive 우선").
                // 텍스트 입력과 병행(OCR·plain 텍스트도 그대로 지원).
                if (isSolution) ...[
                  const Spacer(),
                  TextButton.icon(
                    icon: const Icon(Icons.functions, size: 18),
                    label: const Text('수식으로 입력'),
                    onPressed: enabled ? onMathInput : null,
                  ),
                ],
              ],
            ),
            if (isSolution)
              // 풀이 단계 모드 — 단계 리스트 편집기. 토글로 모드를 나가면 편집기가
              // 트리에서 제거돼 상태가 초기화된다(기존 "토글 시 입력 비움"과 동형).
              // GlobalKey로 MathLive 입력을 이 편집기 필드에 채운다(MOB-07).
              _SolutionStepsEditor(
                key: stepsEditorKey,
                enabled: enabled,
                stepAreaMaxHeight: stepAreaMaxHeight,
                onSubmit: onSendSolution,
              )
            else
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: controller,
                      enabled: enabled,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: enabled ? (_) => onSend() : null,
                      decoration: const InputDecoration(
                        hintText: '생각을 적어 보세요',
                        border: OutlineInputBorder(),
                        isDense: true,
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  IconButton(
                    icon: const Icon(Icons.send),
                    tooltip: '보내기',
                    onPressed: enabled ? onSend : null,
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// 풀이 단계 리스트 편집기 — 번호 매겨진 단계 필드·추가/삭제·"N단계 제출" 버튼.
///
/// 실기기 실측(2026-07-19·MEMORY): verify는 *인접 두 단계의 전이*를 판정하므로 단계를
/// 한 메시지로 묶어 보내야만 correct/incorrect가 결정된다(외톨이 단계=전부 unverifiable).
/// 이 편집기는 "여러 단계를 한 번에"가 기본 모양임을 UI 구조로 유도한다 — 초기 2개 필드·
/// 단계 번호·"N단계 제출" 미리보기. 1단계 제출도 막지 않는다(부드러운 안내만 — 백엔드가
/// 전이 0을 안전 처리·질책 표현 금지).
///
/// 경계: 편집기는 비어있지 않은 단계를 `'\n'`로 합쳐 [onSubmit]에 넘길 뿐이다 — 줄 분해는
/// 컨트롤러(`sendSolution`), 검증은 백엔드가 한다(표현≠의미·수학 로직 클라 미구현).
class _SolutionStepsEditor extends StatefulWidget {
  const _SolutionStepsEditor({
    super.key,
    required this.enabled,
    required this.stepAreaMaxHeight,
    required this.onSubmit,
  });

  /// 입력·버튼 활성 여부(전송 중엔 비활성 — 기존 입력 행과 동일 규칙).
  final bool enabled;

  /// 단계 필드 리스트 영역 최대 높이 — 넉넉하면 절대 상한(162px·행 3개 분량), 키보드로
  /// 좁아지면 body 가용 높이 비율로 줄어든 값이 내려온다(MOB-02). 초과분은 내부 스크롤.
  final double stepAreaMaxHeight;

  /// 제출 콜백 — 비어있지 않은 단계들을 `'\n'`로 합친 원문을 받는다.
  final Future<void> Function(String joined) onSubmit;

  @override
  State<_SolutionStepsEditor> createState() => _SolutionStepsEditorState();
}

class _SolutionStepsEditorState extends State<_SolutionStepsEditor> {
  /// 초기 단계 필드 수 — 묶음 제출이 기본 모양임을 시각적으로 유도한다(1개가 아님).
  /// 2개인 이유: ①2단계 = 검증 가능한 최소 모양(인접 전이 1개) — verify가 판정할 전이가
  /// 생기는 최소 단위라 "묶음이 기본" 유도는 유지된다 ②3개 대비 행 1개(~54px)만큼 풀이
  /// 모드 초기 높이를 줄여 기존 키보드 오버플로(MOB-02) 악화를 완화한다.
  static const int _initialStepCount = 2;

  final List<TextEditingController> _controllers = <TextEditingController>[];
  final List<FocusNode> _focusNodes = <FocusNode>[];
  final ScrollController _scrollController = ScrollController();

  /// 비어있지 않은 단계 수 — "N단계 제출" 라벨·묶음 안내 텍스트에 실시간 반영한다.
  int _filledCount = 0;

  @override
  void initState() {
    super.initState();
    for (var i = 0; i < _initialStepCount; i++) {
      _appendField();
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers) {
      controller.dispose();
    }
    for (final node in _focusNodes) {
      node.dispose();
    }
    _scrollController.dispose();
    super.dispose();
  }

  /// 새 단계 필드(컨트롤러+포커스 노드)를 리스트 끝에 만든다(카운터 리스너 부착).
  void _appendField() {
    final controller = TextEditingController();
    controller.addListener(_recount);
    _controllers.add(controller);
    _focusNodes.add(FocusNode());
  }

  /// 비어있지 않은 단계 수를 다시 세어 달라졌으면 라벨을 갱신한다(실시간 반영).
  void _recount() {
    final n = _controllers.where((c) => c.text.trim().isNotEmpty).length;
    if (n != _filledCount) {
      setState(() => _filledCount = n);
    }
  }

  /// "+ 단계 추가" — 필드를 하나 늘리고(요청 시) 새 필드로 포커스·스크롤을 옮긴다.
  void _addStep({bool focus = false}) {
    setState(_appendField);
    // 새 필드는 다음 프레임에야 트리에 붙으므로 포커스·스크롤을 프레임 뒤로 미룬다.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      if (focus && _focusNodes.isNotEmpty) {
        _focusNodes.last.requestFocus();
      }
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
  }

  /// MathLive "완료"로 받은 평문 수식(`'\n'` 여러 줄 가능)을 단계 필드에 채운다(MOB-07).
  ///
  /// [mergeStepTexts] 규칙으로 **빈 필드부터 채우고 남으면 필드를 추가**한다 — 학생이 숨은
  /// 줄바꿈(⊕) 제스처 없이도 눈에 보이는 단계 필드로 다단계를 쌓게 한다. 채운 줄이 하나라도
  /// 있으면 true를 돌려준다(호출부가 폴백 여부 판정). 구조 변경(필드 추가)만 setState로 감싸고,
  /// 텍스트는 컨트롤러 세팅으로 반영한다(TextField가 컨트롤러로 갱신·리스너가 카운트 라벨 갱신).
  /// 표기 배치만 한다 — 수학 판정·검증은 백엔드 몫(표현≠의미).
  bool fillFromMathInput(String plainText) {
    final lines = plainText
        .split('\n')
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();
    if (lines.isEmpty) {
      return false; // 채울 게 없다(빈/공백 입력) — 호출부가 폴백한다.
    }
    final merged =
        mergeStepTexts(_controllers.map((c) => c.text).toList(), lines);
    // 늘어난 만큼 새 필드 추가(구조 변경이라 setState).
    final extra = merged.length - _controllers.length;
    if (extra > 0) {
      setState(() {
        for (var i = 0; i < extra; i++) {
          _appendField();
        }
      });
    }
    // 각 필드 텍스트 반영(달라진 것만 — 불필요한 커서 리셋·알림 방지).
    for (var i = 0; i < merged.length; i++) {
      if (_controllers[i].text != merged[i]) {
        _controllers[i].text = merged[i];
      }
    }
    _recount();
    // 채운 마지막 필드가 보이도록 스크롤한다(다음 프레임).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
    return true;
  }

  /// 단계 삭제 — 마지막 1개는 남긴다(빈 편집기 방지). dispose는 프레임 뒤로 미룬다
  /// (제거되는 TextField가 이번 프레임까지 이전 컨트롤러·노드를 참조하기 때문).
  void _removeStep(int index) {
    if (_controllers.length <= 1) {
      return;
    }
    final controller = _controllers[index];
    final node = _focusNodes[index];
    setState(() {
      _controllers.removeAt(index);
      _focusNodes.removeAt(index);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      controller.dispose();
      node.dispose();
    });
    _recount();
  }

  /// 단계 필드 Enter(next) — 다음 단계로 이동, 마지막 필드면 새 단계를 추가한다.
  void _handleStepSubmitted(int index) {
    if (index + 1 < _focusNodes.length) {
      _focusNodes[index + 1].requestFocus();
    } else {
      _addStep(focus: true);
    }
  }

  /// 비어있지 않은 단계들을 `'\n'`로 합쳐 제출하고 편집기를 초기 상태로 되돌린다.
  ///
  /// 합치기만 UI가 한다 — 컨트롤러 `sendSolution`이 다시 줄 분해하므로 왕복 무손실이다
  /// (컨트롤러/L5 계약 완전 무변경). 빈 단계(공백뿐)는 제출에서 제외한다.
  Future<void> _submit() async {
    final joined = _controllers
        .map((c) => c.text.trim())
        .where((t) => t.isNotEmpty)
        .join('\n');
    if (joined.isEmpty) {
      return;
    }
    _resetFields(); // 기존 입력 행과 동형 — 전송 전에 입력을 비운다.
    await widget.onSubmit(joined);
  }

  /// 필드들을 초기 개수의 빈 필드로 되돌린다(이전 컨트롤러·노드는 프레임 뒤 dispose).
  void _resetFields() {
    final oldControllers = List<TextEditingController>.of(_controllers);
    final oldNodes = List<FocusNode>.of(_focusNodes);
    setState(() {
      _controllers.clear();
      _focusNodes.clear();
      for (var i = 0; i < _initialStepCount; i++) {
        _appendField();
      }
      _filledCount = 0;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      for (final controller in oldControllers) {
        controller.dispose();
      }
      for (final node in oldNodes) {
        node.dispose();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 단계 필드 리스트 — 높이를 가둬 내부 스크롤(단계가 늘어도 화면을 안 밀어낸다).
        // 상한은 화면이 body 가용 높이에 맞춰 내려준 값(키보드 표시 시 축소·MOB-02).
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: widget.stepAreaMaxHeight),
          child: SingleChildScrollView(
            controller: _scrollController,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (var i = 0; i < _controllers.length; i++) _buildStepRow(i),
              ],
            ),
          ),
        ),
        // 한 단계뿐일 때 — 묶음 제출을 부드럽게 안내한다(질책 아님·제출은 막지 않음).
        if (_filledCount == 1)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.hairline, bottom: AppSpacing.xs),
            child: Text(
              '단계를 나눠 적으면 풀이를 확인해 드릴 수 있어요',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        Row(
          children: [
            TextButton.icon(
              icon: const Icon(Icons.add, size: 18),
              label: const Text('단계 추가'),
              onPressed: widget.enabled ? () => _addStep(focus: true) : null,
            ),
            const Spacer(),
            // "N단계 제출" — 제출 미리보기(몇 단계가 실제 전송되는지 상시 표시).
            // 비어있으면 보낼 게 없으므로 비활성(1단계 제출은 허용 — 백엔드 안전 처리).
            FilledButton(
              onPressed: (widget.enabled && _filledCount > 0) ? _submit : null,
              child: Text(
                _filledCount > 0 ? '$_filledCount단계 제출' : '풀이 제출',
              ),
            ),
          ],
        ),
      ],
    );
  }

  /// 단계 한 행 — 번호 라벨 + 단일라인 필드(Enter=다음 단계) + 삭제 버튼.
  Widget _buildStepRow(int index) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs6),
      child: Row(
        children: [
          // 번호 라벨 — 필드가 채워져도 단계 구조가 계속 보인다(사고 구조의 시각화).
          SizedBox(
            width: 24,
            child: Text(
              '${index + 1}',
              textAlign: TextAlign.center,
              style: theme.textTheme.labelLarge?.copyWith(
                color: theme.colorScheme.primary,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: TextField(
              controller: _controllers[index],
              focusNode: _focusNodes[index],
              enabled: widget.enabled,
              maxLines: 1,
              // Enter=다음 단계(마지막이면 추가) — 줄바꿈이 아니라 단계 이동이 자연 흐름.
              textInputAction: TextInputAction.next,
              onSubmitted: (_) => _handleStepSubmitted(index),
              decoration: InputDecoration(
                // 번호는 왼쪽 라벨에 있으므로 힌트는 *입력 형태 예시*로 안내한다(MOB-05).
                hintText: _stepHintExamples[index % _stepHintExamples.length],
                border: const OutlineInputBorder(),
                isDense: true,
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.remove_circle_outline, size: 20),
            tooltip: '단계 삭제',
            onPressed: (widget.enabled && _controllers.length > 1)
                ? () => _removeStep(index)
                : null,
          ),
        ],
      ),
    );
  }
}
