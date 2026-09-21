// MathliveInputScreen — 수식 입력 화면(채팅에서 push해 진입, 완료 시 LaTeX를 pop 결과로 반환).
//
// 경계(CLAUDE.md): 화면은 학생이 입력한 LaTeX를 *수집·반환*만 한다 — 수학 판정·검증은 서버(L3)가
// 한다. OCR 화면(ocr_capture_screen)과 동형으로 채팅을 알지 못한 채 `context.pop(latex)`로 결과만
// 돌려주고, 채팅이 `sendSolution`으로 매핑·전송한다(단방향 chat→math-input 의존).
//
// 레이아웃(MOB-03 실기기 실측 교훈): MathLive 가상 키보드는 *WebView 자체 뷰포트*의 하단에
// 도킹한다(index.html 주석 참조). 고정 140px 스트립에 넣으면 키보드(자연 높이 약 300 CSS px)가
// 스트립을 덮으며 상단 행이 잘리고 필드가 가려진다 — 그래서 WebView를 Expanded(잔여 전체 높이)로
// 배치한다. 목표: 필드 상단 가시 + 키보드 WebView 하단 도킹 + 잘림 0.
//
// 정서 안전(절대 금기): 정오 강조·정답·빨강 경고·게임화 없음. 입력을 격려하는 중립 톤만.
// visibleForTesting·ValueChanged는 material 경유 재수출(framework.dart 실측) — foundation
// 직접 import는 unnecessary_import 경고라 쓰지 않는다.
import 'package:flutter/material.dart';

import '../../../theme/spacing.dart';
import '../domain/latex_to_plain.dart';
import 'mathlive_input_webview.dart';

/// 수식(LaTeX) 입력 화면 — MathLive WebView로 입력받아 "완료"로 반환한다.
class MathliveInputScreen extends StatefulWidget {
  const MathliveInputScreen({super.key, this.inputBuilder});

  /// 테스트 전용 입력 위젯 대체자 — WebView(플랫폼 뷰)는 헤드리스 flutter test에서 렌더
  /// 불가하므로, 화면 계약(pop(latex)·완료 활성화·Expanded 배치) 테스트가 이 자리로
  /// fake를 주입한다. null이면 실제 [MathliveInputWebView]를 쓴다(프로덕션 경로).
  @visibleForTesting
  final Widget Function(ValueChanged<String> onChanged)? inputBuilder;

  @override
  State<MathliveInputScreen> createState() => _MathliveInputScreenState();
}

class _MathliveInputScreenState extends State<MathliveInputScreen> {
  /// WebView 입력 상태 핸들(전송/취소 시 비우기).
  final GlobalKey<MathliveInputWebViewState> _inputKey =
      GlobalKey<MathliveInputWebViewState>();

  /// 웹에서 흘러온 현재 LaTeX(미리보기·완료 활성화 판정).
  String _latex = '';

  bool get _canSubmit => _latex.trim().isNotEmpty;

  /// 미리보기용 평문 표기(MATH-05) — 표시 전용이며 pop 반환값에는 쓰지 않는다.
  ///
  /// 변환 결과가 빈 문자열이면(간격 매크로만 입력한 경우 등) 미리보기를 아예 그리지 않는다 —
  /// 전송 가능 판정(`_canSubmit`)은 원문 기준 그대로라 여기 결과에 영향받지 않는다.
  String get _preview => latexToPlainSolution(_latex);

  /// 웹(또는 테스트 fake)이 흘린 LaTeX 변경을 화면 상태로 반영한다.
  void _onLatexChanged(String latex) => setState(() => _latex = latex);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('수식으로 풀이 입력'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: '취소',
          // 취소는 아무것도 반환하지 않는다(null) — 채팅은 그대로 유지된다.
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '풀이 수식을 입력해 주세요. 정답 여부는 함께 확인해요.',
                style: theme.textTheme.bodyMedium,
              ),
              const SizedBox(height: AppSpacing.md),
              // WebView는 잔여 높이를 전부 차지한다 — 필드는 웹 문서 상단에 그려지고,
              // 가상 키보드는 WebView 뷰포트 하단(= 이 영역 하단, 버튼 행 바로 위)에
              // 도킹한다. 고정 높이 금지(키보드 잘림 재발 — 파일 상단 주석 참조).
              Expanded(
                child: widget.inputBuilder != null
                    ? widget.inputBuilder!(_onLatexChanged)
                    : MathliveInputWebView(
                        key: _inputKey,
                        onChanged: _onLatexChanged,
                        // 이 화면은 수식 입력 전용이라 "진입 = 지금 입력하려는 것"이다 —
                        // 필드를 한 번 더 탭해야 하는 마찰을 없앤다(S3-37). 인라인 임베드는
                        // 기본값(false)을 그대로 쓴다(webview 쪽 autofocus 주석 참조).
                        autofocus: true,
                      ),
              ),
              const SizedBox(height: AppSpacing.md),
              // 입력 미리보기 — 학생이 읽을 *평문 표기*로 되돌려 보여준다(MATH-05).
              //
              // 이전엔 `Text(_latex)`로 MathLive LaTeX 원문(`\frac{1}{2}` 등 백슬래시 매크로)을
              // 그대로 노출했다. 채팅 버블(chat_screen.dart)은 MOB-06에서 이미 같은 변환을
              // 거치는데 이 표면만 빠져 있던 것 — 없던 기능을 만드는 게 아니라 *이미 정본인*
              // 표기 변환(latexToPlainSolution)이 미적용이던 표면을 닫는다. 수식 조판
              // 엔진(flutter_math_fork)은 여전히 미도입이다(pubspec.yaml 주석 유지) — 이건
              // 조판이 아니라 표기 매핑이고, 렌더러를 코어에 넣지 않는다(Renderer=Plugin).
              //
              // ⚠️ 표시만 변환하고 *데이터 흐름은 원문 그대로*다 — '완료'가 pop으로 돌려주는
              // 값은 아래에서 `_latex.trim()`(원문 LaTeX)이며, 호출측
              // chat_controller.sendMathliveLatex가 자기 쪽에서 latexToPlainSolution을
              // 적용한다. 여기서 pop 값까지 변환하면 이중 변환이 된다.
              if (_preview.isNotEmpty) ...[
                Text(
                  _preview,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
                const SizedBox(height: AppSpacing.md),
              ],
              Row(
                children: [
                  TextButton(
                    onPressed: () {
                      _inputKey.currentState?.clear();
                    },
                    child: const Text('지우기'),
                  ),
                  const Spacer(),
                  FilledButton(
                    // 빈 입력은 보낼 게 없으므로 비활성(전송 무의미).
                    onPressed: _canSubmit
                        ? () => Navigator.of(context).pop(_latex.trim())
                        : null,
                    child: const Text('완료'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
