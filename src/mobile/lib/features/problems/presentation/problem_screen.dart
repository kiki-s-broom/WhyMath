// 진단→문제제시 화면 — CAT 추천 문제를 로드해 발문·맥락·보기를 보이고 코치로 진입시킨다.
//
// 경계(CLAUDE.md): 화면은 서버가 내려준 문제 구조를 *그대로 표시*만 한다(표현≠의미). 정답·정오
// 강조·게임화 없음(절대 금기). 발문·보기의 캐럿/평문 수식은 MathText가 교과서 조판으로 렌더한다
// (S3-39 회수) — 조판은 *표기* 변환일 뿐 의미·정오 판정이 아니며, 파싱 불가는 원문 폴백이다.
//
// ⚠️ 안전(절대 원칙 #1): [Problem] 모델은 answer를 담지 않으므로 이 화면이 정답을 노출할 방법이
// 구조적으로 없다(problem_models.dart 안전 주석). 정오 판단은 코치/verify 신호로만 이뤄진다.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router.dart';
import '../../../shared/widgets/math_text.dart';
import '../../../theme/spacing.dart';
import '../application/active_problem.dart';
import '../application/diagnosis_controller.dart';
import '../application/diagnosis_state.dart';
import '../data/problem_models.dart';

/// 진단(CAT)으로 확보한 문제를 제시하는 화면.
///
/// 진입 시 [DiagnosisController.load]를 1회 트리거하고, 로딩·후보없음·에러·문제 상태를 렌더한다.
/// "풀이 시작"으로 활성 문제를 세팅한 뒤 코치 화면으로 이동한다(세션 묶기는 Slice 2 코치가 소비).
class ProblemScreen extends ConsumerStatefulWidget {
  const ProblemScreen({super.key});

  @override
  ConsumerState<ProblemScreen> createState() => _ProblemScreenState();
}

class _ProblemScreenState extends ConsumerState<ProblemScreen> {
  @override
  void initState() {
    super.initState();
    // 첫 프레임 이후 로드를 트리거한다(build 중 provider 변경 회피).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(diagnosisControllerProvider.notifier).load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(diagnosisControllerProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('오늘의 문제'),
        actions: [
          TextButton(
            onPressed: () => context.go(AppRoutes.chatPath),
            child: const Text('건너뛰기'),
          ),
        ],
      ),
      body: SafeArea(
        child: _buildBody(context, state),
      ),
    );
  }

  Widget _buildBody(BuildContext context, DiagnosisState state) {
    if (state.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (state.error != null) {
      return _MessagePane(
        message: state.error!,
        actionLabel: '다시 시도',
        onAction: () => ref.read(diagnosisControllerProvider.notifier).load(),
      );
    }
    if (state.noCandidate || state.problem == null) {
      // 추천 후보 없음 — 코치와 자유 대화로 진행할 수 있게 안내한다(가용성).
      return _MessagePane(
        message: '지금 추천할 문제가 없어요. 코치와 먼저 이야기해 볼까요?',
        actionLabel: '코치와 대화하기',
        onAction: () => context.go(AppRoutes.chatPath),
      );
    }
    return _ProblemView(
      problem: state.problem!,
      onStart: () {
        // 활성 문제를 세팅해 코치 세션이 problem_id에 묶이게 한다(Slice 2 소비).
        ref.read(activeProblemProvider.notifier).state = state.problem;
        context.go(AppRoutes.chatPath);
      },
    );
  }
}

/// 로딩 실패·후보 없음 등 안내 + 단일 액션 버튼 패널.
class _MessagePane extends StatelessWidget {
  const _MessagePane({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: AppSpacing.xl),
            FilledButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}

/// 문제 본문·맥락·보기 렌더.
class _ProblemView extends StatelessWidget {
  const _ProblemView({required this.problem, required this.onStart});

  final Problem problem;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // 발문은 마크다운 우선·없으면 원문·둘 다 없으면(메타 전용 레코드) 부드러운 안내.
    final questionBody = problem.questionTextMd ??
        problem.questionText ??
        '(이 문제의 발문은 준비 중이에요)';

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.xl),
      children: [
        // 맥락 칩(과목·소단원) — 정오 강조 없는 중립 표시.
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _ContextChip(label: problem.subject),
            if (problem.subunit != null) _ContextChip(label: problem.subunit!),
            if (problem.questionFormat != null)
              _ContextChip(label: problem.questionFormat!),
          ],
        ),
        const SizedBox(height: AppSpacing.xl),
        // 발문 — 프로즈+수식 혼합을 교과서 조판으로 렌더한다(캐럿/평문 수식만·표현≠의미·S3-39).
        MathText(questionBody, style: theme.textTheme.titleMedium),
        if (problem.choices != null && problem.choices!.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.xl),
          for (var i = 0; i < problem.choices!.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              // 원 번호 접두사는 평문·값만 수식 조판(번호가 값 수식에 섞이지 않게).
              //
              // 스타일은 루트 TextSpan이 아니라 Text.rich의 `style` 인자로 준다 — 보기끼리
              // 색이 갈리지 않음을 `tester.widget<Text>(...).style?.color`로 동결한 S3-35
              // 게이트가 그래야 변별력을 유지한다(루트 스팬에 넣으면 Text.style이 항상 null이
              // 돼 정오 차등 강조가 들어와도 통과하는 위장 검사가 된다).
              child: Text.rich(
                TextSpan(
                  children: <InlineSpan>[
                    TextSpan(text: '${_circledNumber(i + 1)} '),
                    ...mathInlineSpansFor(
                      problem.choices![i],
                      theme.textTheme.bodyLarge ??
                          DefaultTextStyle.of(context).style,
                    ),
                  ],
                ),
                style: theme.textTheme.bodyLarge,
              ),
            ),
        ],
        const SizedBox(height: AppSpacing.xxxl),
        FilledButton(
          onPressed: onStart,
          child: const Text('풀이 시작'),
        ),
      ],
    );
  }

  /// 1~9를 원 숫자(①~⑨)로, 그 밖은 괄호 숫자로 표시한다(객관식 보기 라벨).
  String _circledNumber(int n) {
    if (n >= 1 && n <= 9) {
      return String.fromCharCode(0x2460 + n - 1); // ①=U+2460
    }
    return '($n)';
  }
}

/// 맥락 칩(과목·소단원 등) — 중립 톤.
class _ContextChip extends StatelessWidget {
  const _ContextChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text(label),
      visualDensity: VisualDensity.compact,
    );
  }
}
