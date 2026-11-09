// GP-1 닉네임 화면 — 텍스트 필드 1개 + 시작 버튼(S6).
//
// 학생 식별자는 닉네임 문자열뿐이다. 실명·학교·학년은 묻지 않는다.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'golden_state.dart';

/// 닉네임 길이 상한 — 서버 계약(1~20자)과 같다.
const int kNicknameMaxLength = 20;

class NicknameScreen extends ConsumerStatefulWidget {
  const NicknameScreen({super.key});

  @override
  ConsumerState<NicknameScreen> createState() => _NicknameScreenState();
}

class _NicknameScreenState extends ConsumerState<NicknameScreen> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _start() {
    ref.read(goldenProvider.notifier).start(_controller.text);
  }

  @override
  Widget build(BuildContext context) {
    final bool loading =
        ref.watch(goldenProvider.select((GoldenState s) => s.loading));
    return Scaffold(
      appBar: AppBar(title: const Text('와이매스 — 시작하기')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const Text('닉네임만 입력하면 바로 시작해요.'),
            const SizedBox(height: 16),
            TextField(
              key: const Key('golden_nickname_field'),
              controller: _controller,
              maxLength: kNicknameMaxLength,
              textInputAction: TextInputAction.go,
              onSubmitted: (_) => _start(),
              decoration: const InputDecoration(
                labelText: '닉네임',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            ElevatedButton(
              key: const Key('golden_start_button'),
              onPressed: loading ? null : _start,
              child: Text(loading ? '여는 중…' : '시작'),
            ),
          ],
        ),
      ),
    );
  }
}
