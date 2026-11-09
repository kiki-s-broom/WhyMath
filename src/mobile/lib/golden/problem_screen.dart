// GP-2~GP-4 문제 화면 — 위: 문제 본문 / 가운데: 대화 말풍선 / 아래: 입력창 + 보내기(S6).
// (S7) 맨 위에 "LF-07 · 7/30"과 현재 숙련도(서버 값)를 작게 표시한다.
//
// 문제 본문의 `$...$` 구간만 flutter_math_fork(`Math.tex`)로 그리고, 나머지는 일반 텍스트다.
// 채점은 하지 않는다 — 입력을 서버로 보내고, 서버가 준 튜터 문장·판정 줄을 쌓기만 한다.

import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden_api.dart';
import 'golden_state.dart';

class ProblemScreen extends ConsumerStatefulWidget {
  const ProblemScreen({super.key});

  @override
  ConsumerState<ProblemScreen> createState() => _ProblemScreenState();
}

class _ProblemScreenState extends ConsumerState<ProblemScreen> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _send() {
    final String text = _controller.text;
    if (text.trim().isEmpty) return;
    _controller.clear();
    ref.read(goldenProvider.notifier).send(text);
  }

  @override
  Widget build(BuildContext context) {
    final GoldenState s = ref.watch(goldenProvider);
    final GoldenProblem? problem = s.problem;
    final bool canSend = !s.loading && !s.problemFinished;

    return Scaffold(
      appBar: AppBar(title: const Text('문제')),
      body: Column(
        children: <Widget>[
          // 맨 위 작은 줄: 문항 ID · 몇 번째/전체 + 현재 숙련도(서버 값 그대로)
          if (problem != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Row(
                children: <Widget>[
                  Text(
                    '${problem.id} · ${problem.index}/${problem.total}',
                    key: const Key('golden_problem_position'),
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
                  const Spacer(),
                  Text(
                    '숙련도 ${s.mastery.toStringAsFixed(2)}',
                    key: const Key('golden_mastery_label'),
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
                ],
              ),
            ),
          // 위: 문제 본문
          if (problem != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: StemText(problem.stem, key: const Key('golden_stem')),
            ),
          const Divider(height: 1),
          // 가운데: 대화 말풍선(최신이 아래)
          Expanded(
            child: ListView.builder(
              key: const Key('golden_chat_list'),
              reverse: true,
              padding: const EdgeInsets.all(12),
              itemCount: s.chat.length,
              itemBuilder: (BuildContext context, int i) {
                final (String who, String text) = s.chat[s.chat.length - 1 - i];
                return ChatBubble(who: who, text: text);
              },
            ),
          ),
          if (s.loading) const LinearProgressIndicator(),
          // 아래: 입력창 + 보내기
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: TextField(
                      key: const Key('golden_answer_field'),
                      controller: _controller,
                      enabled: canSend,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: InputDecoration(
                        hintText: s.problemFinished
                            ? '이 문제는 끝났어요'
                            : '답이나 생각을 적어 보세요',
                        border: const OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    key: const Key('golden_send_button'),
                    onPressed: canSend ? _send : null,
                    child: const Text('보내기'),
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

/// 문제 본문 — `$...$` 구간은 수식(Math.tex), 나머지는 일반 텍스트로 한 문단에 섞어 그린다.
///
/// 수식이 파싱되지 않으면 그 구간은 원문 텍스트로 대신 보여준다(앱이 깨지지 않게).
class StemText extends StatelessWidget {
  const StemText(this.stem, {super.key});

  final String stem;

  /// `$`로 감싼 구간. `$` 짝이 안 맞으면 남은 부분은 그냥 텍스트가 된다.
  static final RegExp _inlineMath = RegExp(r'\$([^$]+)\$');

  @override
  Widget build(BuildContext context) {
    final TextStyle style =
        Theme.of(context).textTheme.titleMedium ?? const TextStyle(fontSize: 16);
    final List<InlineSpan> spans = <InlineSpan>[];
    int last = 0;
    for (final RegExpMatch m in _inlineMath.allMatches(stem)) {
      if (m.start > last) {
        spans.add(TextSpan(text: stem.substring(last, m.start)));
      }
      final String tex = m.group(1)!;
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: Math.tex(
            tex,
            mathStyle: MathStyle.text,
            textStyle: style,
            onErrorFallback: (FlutterMathException _) => Text(tex, style: style),
          ),
        ),
      );
      last = m.end;
    }
    if (last < stem.length) {
      spans.add(TextSpan(text: stem.substring(last)));
    }
    return Text.rich(TextSpan(style: style, children: spans));
  }
}

/// 대화 말풍선 — 학생은 오른쪽, 튜터는 왼쪽, 판정 줄은 가운데.
class ChatBubble extends StatelessWidget {
  const ChatBubble({super.key, required this.who, required this.text});

  final String who;
  final String text;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    if (who == kWhoVerdict) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Text(
            text,
            key: const Key('golden_verdict_line'),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
      );
    }
    final bool isStudent = who == kWhoStudent;
    return Align(
      alignment: isStudent ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        key: Key(isStudent ? 'golden_bubble_student' : 'golden_bubble_tutor'),
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        constraints: const BoxConstraints(maxWidth: 480),
        decoration: BoxDecoration(
          color: isStudent ? colors.primaryContainer : colors.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(who, style: Theme.of(context).textTheme.labelSmall),
            const SizedBox(height: 2),
            Text(text),
          ],
        ),
      ),
    );
  }
}
