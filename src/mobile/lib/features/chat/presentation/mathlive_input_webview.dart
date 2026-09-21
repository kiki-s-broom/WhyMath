// MathliveInputWebView — vendored MathLive(assets/mathlive_input)를 WebView로 임베드한 수식 입력기.
//
// 경계(슬89 표현≠의미·국소 비상구): 학생이 입력한 수식을 LaTeX 문자열로 *그대로* Flutter에 흘릴
// 뿐, 수학 판정·검증은 하지 않는다(백엔드 L3 verify가 검증). MathLive는 수식 입력의 국소 예외
// (자족 비상구)로, Flutter는 자산 번들(assets/mathlive_input/)을 오프라인 로드한다.
//
// 통신: 웹은 `WhymathMathInput` JS 채널로 LaTeX 변경을 push하고, Flutter는 `window.whymathClear()`·
// `window.whymathSetLatex(v)`·`window.whymathFocus()`를 runJavaScript로 호출한다(단방향 상태 +
// 명령 훅). MathLive 로드 실패 시 웹이 textarea로 폴백하므로 입력 자체는 끊기지 않는다(HTML 참조).
//
// 생명주기 하드닝(MOB-19): ① onPageFinished 전까지 로딩 인디케이터로 빈 화면을 가리고, ② 주 프레임
// 로드 실패(onWebResourceError) 시 WebView를 걷어내고 "수식 입력 불가 → 평문 입력 유도" 안내로
// 강등한다. 웹 내부 3단 폴백(textarea)은 *페이지가 떴을 때*만 유효하므로, 페이지 자체가 안 뜨는
// 네이티브 측 실패는 여기서 막는다. 정서 안전: 실패를 빨강·경고로 표현하지 않는다.
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'webview_fallback.dart';

/// 웹이 보낸 LaTeX 입력 메시지를 정규화한다(순수·Flutter/WebView 무관 — 단위 테스트 대상).
///
/// 앞뒤 공백을 제거한다. 공백뿐이거나 빈 문자열이면 빈 문자열을 돌려준다(전송 판정은 호출자).
/// 수학 의미 추론·치환은 하지 않는다(LaTeX 원문 보존·검증은 백엔드).
String normalizeLatexInput(String raw) => raw.trim();

/// 웹의 포커스 훅을 부르는 JS — 자동 포커스(S3-37→S3-50) 배선의 유일한 호출 문자열.
///
/// 훅은 index.html이 MathLive 경로(`mf.focus()` + 가상 키보드 `show()`)와 textarea 폴백
/// 경로(`ta.focus()`) *양쪽*에 정의한다 — MathLive가 로드 실패해 강등돼도 자동 포커스는
/// 그대로 동작한다. 호출 시점은 `WhymathMathReady` 신호 수신 직후(훅 정의 완료가 보장됨 —
/// S3-50)지만, `&&` 존재 가드는 방어적으로 유지한다(`whymathClear` 호출과 동일 패턴).
/// 포커스는 코스메틱이라 실패해도 입력 자체는 탭 한 번으로 정상 진행된다.
const String mathliveFocusScript = 'window.whymathFocus && window.whymathFocus()';

/// MathLive 수식 입력 WebView — 입력 변경을 [onChanged]로 콜백한다.
///
/// 생명주기(MOB-19): 로드 완료 전까지 로딩 인디케이터를 얹고, 주 프레임 로드 실패 시 수식 입력 불가
/// 안내 폴백으로 강등한다(빈 화면 미노출). 플랫폼 뷰라 헤드리스 flutter test에서는 WebView 본체를
/// pump하지 않고, 강등 판정(순수 함수)·폴백 외형(공개 위젯)만 webview_fallback.dart 테스트가 문다.
class MathliveInputWebView extends StatefulWidget {
  const MathliveInputWebView({
    required this.onChanged,
    this.height,
    this.autofocus = false,
    super.key,
  });

  /// 입력된 LaTeX(정규화 후)를 흘리는 콜백. 빈 문자열도 전달한다(호출자가 전송 여부 판정).
  final ValueChanged<String> onChanged;

  /// 웹 훅 준비 완료(WhymathMathReady) 시 입력 필드에 자동으로 포커스를 줄지 (S3-37→S3-50).
  ///
  /// 수식 입력 *전용 화면*(MathliveInputScreen)처럼 "진입했다 = 지금 입력하려는 것"이 확실한
  /// 자리에서만 true로 준다 — 학생이 화면에 들어와서 필드를 한 번 더 탭해야 하는 마찰을 없앤다.
  /// 인라인 임베드(`height` 지정)에서 true면 학생이 의도하지 않은 시점에 키보드가 떠 다른
  /// 콘텐츠를 덮으므로 **기본값은 false**다(opt-in).
  final bool autofocus;

  /// 인라인 표시 높이(px). null이면 부모 제약을 그대로 채운다(전체 높이 배치용).
  ///
  /// MathLive 가상 키보드는 *WebView 자체 뷰포트*의 하단에 도킹한다(웹 번들 실측 —
  /// index.html 주석 참조). 키보드 자연 높이(약 300 CSS px)보다 낮은 고정 높이를 주면
  /// 키보드 상단이 잘리고 필드를 덮으므로, 키보드를 쓰는 화면은 null(Expanded 배치)로 쓴다.
  final double? height;

  @override
  State<MathliveInputWebView> createState() => MathliveInputWebViewState();
}

/// [MathliveInputWebView] 상태 — 외부에서 [clear]를 호출해 입력을 비울 수 있다(전송 후).
class MathliveInputWebViewState extends State<MathliveInputWebView> {
  late final WebViewController _controller;

  /// 로딩 인디케이터 표시 여부 — onPageFinished(로드 완료) 전까지만 true(MOB-19).
  bool _loading = true;

  /// 강등 여부 — 주 프레임 로드 실패 시 수식 입력 불가 안내로 내린다(빈 화면 금지).
  bool _fallBackToGuidance = false;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      // 웹이 LaTeX 변경을 push하는 인바운드 채널 — 정규화해 콜백으로 흘린다.
      ..addJavaScriptChannel(
        'WhymathMathInput',
        onMessageReceived: (JavaScriptMessage message) {
          widget.onChanged(normalizeLatexInput(message.message));
        },
      )
      // 자동 포커스(S3-50·원 S3-19) — 웹이 명령 훅 정의를 *마친 뒤* 보내는 WhymathMathReady
      // 신호에서 훅을 부른다. S3-37이 쓰던 onPageFinished는 이 자산에선 타이밍이 틀렸다:
      // index.html의 모듈 스크립트는 top-level await로 비동기 실행되므로 페이지 로드 완료
      // 시점엔 whymathFocus가 아직 미정의일 수 있고, && 가드 때문에 *무증상 no-op*이 된다
      // (헤드리스 테스트로는 못 잡는 실기기 전용 실패 — fa08081 원본 대조로 발견).
      // ready 신호는 MathLive 경로·textarea 폴백 경로 양쪽에서 온다(자산 계약 테스트가 동결).
      ..addJavaScriptChannel(
        'WhymathMathReady',
        onMessageReceived: (JavaScriptMessage message) {
          if (widget.autofocus) {
            _controller.runJavaScript(mathliveFocusScript);
          }
        },
      )
      // 생명주기 하드닝(MOB-19) — main 독자 진화분, 섀도 회수와 함께 보존한다.
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (_) {
            if (_fallBackToGuidance || !mounted) return;
            setState(() => _loading = false);
          },
          onWebResourceError: _onWebResourceError,
        ),
      )
      ..loadFlutterAsset('assets/mathlive_input/index.html');
  }

  /// 리소스 로드 실패 처리 — 주 프레임 실패만 안내 폴백으로 강등한다(판정은 공유 순수 함수).
  void _onWebResourceError(WebResourceError error) {
    if (!shouldDemoteWebViewOnError(isForMainFrame: error.isForMainFrame)) return;
    // 침묵 실패 금지 — 강등 사유를 로그로 남긴다(학생 표면은 중립 톤 유지).
    debugPrint(
      '[whymath] MathLive WebView 주 프레임 로드 실패 → 입력 안내 폴백: '
      'code=${error.errorCode} ${error.description}',
    );
    if (_fallBackToGuidance || !mounted) return;
    setState(() {
      _loading = false;
      _fallBackToGuidance = true;
    });
  }

  /// 입력을 비운다(전송 후 초기화) — 웹의 `whymathClear` 훅을 호출한다.
  Future<void> clear() async {
    await _controller.runJavaScript('window.whymathClear && window.whymathClear()');
  }

  @override
  Widget build(BuildContext context) {
    // 강등 — WebView 대신 평문 입력 유도 안내. 학생은 실패 경고가 아니라 "이렇게 입력하면 된다"는
    // 안내를 본다(정서 안전). 실제 평문 입력 필드로의 대체는 별개 축(범위 밖 — MOB-19는 안내까지).
    if (_fallBackToGuidance) {
      return WebViewFallbackTile(
        icon: Icons.edit_note_outlined,
        label: '수식 입력 도구를 불러오지 못했어요. x^2 + 3x처럼 평문으로 적어도 괜찮아요',
        height: widget.height,
      );
    }
    // height가 null이면 SizedBox는 높이 제약을 추가하지 않는다 — 부모(Expanded 등)가
    // 준 제약을 WebView가 그대로 채운다(가상 키보드 하단 도킹 공간 확보).
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: SizedBox(
        height: widget.height,
        width: double.infinity,
        child: Stack(
          children: [
            WebViewWidget(controller: _controller),
            // 로드 완료 전까지 웹뷰 위를 덮는다 — 초기 흰 프레임·빈 화면을 숨기는 인디케이터.
            if (_loading) const Positioned.fill(child: WebViewLoadingCover()),
          ],
        ),
      ),
    );
  }
}
