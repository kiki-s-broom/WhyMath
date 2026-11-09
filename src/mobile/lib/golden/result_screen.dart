// GP-5·GP-6 결과 화면 — 판정(맞음/틀림)·숙련도·피드백·튜터 턴 수 + "다음 문제" 버튼(S7).
//
// 서버가 준 값만 보여준다. 숙련도 계산(+0.10/−0.05·잘라내기)은 서버 몫이고, 여기서 보여주는
// "바뀐 양"은 판정 직전 서버 값과 판정 뒤 서버 값의 차이일 뿐이다.
// 게임화(배지·연속 정답·통계)는 넣지 않는다. 오답 문구는 비난 표현 없이 담담하게 쓴다.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden_api.dart';
import 'golden_state.dart';

class ResultScreen extends ConsumerWidget {
  const ResultScreen({super.key});

  /// 숙련도 변화량을 부호와 함께 소수 둘째 자리로 쓴다(예: "+0.10", "−0.05", "±0.00").
  ///
  /// 부동소수 오차(0.15 − 0.10 = 0.04999…)는 둘째 자리 반올림으로 흡수한다.
  static String formatDelta(double delta) {
    final String abs = delta.abs().toStringAsFixed(2);
    if (abs == '0.00') return '±0.00';
    return delta > 0 ? '+$abs' : '−$abs';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final GoldenState s = ref.watch(goldenProvider);
    final Graded? result = s.result;
    // 결과 없이 이 화면이 그려질 일은 없지만(앱이 result 유무로 화면을 고른다) 안전하게 비운다.
    if (result == null) return const Scaffold(body: SizedBox.shrink());

    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    // 맞음 = 초록·체크, 틀림 = 주황·전구(다시 생각해 볼 거리) — 빨간 X는 쓰지 않는다.
    final Color tone = result.correct ? Colors.green.shade700 : Colors.orange.shade800;
    final IconData icon =
        result.correct ? Icons.check_circle_outline : Icons.lightbulb_outline;
    final String label = result.correct ? '맞음' : '틀림';
    final double previous = s.previousMastery ?? s.mastery;
    final String problemId = s.problem?.id ?? '';

    return Scaffold(
      appBar: AppBar(title: const Text('결과')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: <Widget>[
            // 판정 — 색과 아이콘
            Icon(icon, key: const Key('golden_result_icon'), size: 72, color: tone),
            const SizedBox(height: 8),
            Text(
              label,
              key: const Key('golden_result_label'),
              textAlign: TextAlign.center,
              style: text.headlineMedium?.copyWith(color: tone, fontWeight: FontWeight.bold),
            ),
            if (problemId.isNotEmpty)
              Text(problemId, textAlign: TextAlign.center, style: text.labelMedium),
            const SizedBox(height: 24),
            // 숙련도 — 서버 값(둘째 자리) + 직전 값에서 바뀐 양
            Text(
              '숙련도 ${result.mastery.toStringAsFixed(2)}',
              key: const Key('golden_result_mastery'),
              textAlign: TextAlign.center,
              style: text.titleLarge,
            ),
            Text(
              '(${formatDelta(result.mastery - previous)})',
              key: const Key('golden_result_delta'),
              textAlign: TextAlign.center,
              style: text.titleMedium,
            ),
            const SizedBox(height: 24),
            // 서버의 한 줄 피드백
            Text(
              result.feedback,
              key: const Key('golden_result_feedback'),
              textAlign: TextAlign.center,
              style: text.bodyLarge,
            ),
            const SizedBox(height: 12),
            Text(
              '튜터와 주고받은 횟수: ${result.turnsUsed}번',
              key: const Key('golden_result_turns'),
              textAlign: TextAlign.center,
              style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
            ),
            const SizedBox(height: 32),
            if (s.loading) const LinearProgressIndicator(),
            const SizedBox(height: 8),
            FilledButton(
              key: const Key('golden_next_button'),
              onPressed: s.loading ? null : () => ref.read(goldenProvider.notifier).nextProblem(),
              child: const Text('다음 문제'),
            ),
          ],
        ),
      ),
    );
  }
}
