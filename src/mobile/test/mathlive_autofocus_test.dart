// 수식 입력 자동 포커스 배선 테스트 (S3-37 → S3-50 갱신)
//
// 무엇을 막는가: 학생이 "수식으로 풀이 입력" 화면에 들어가면 곧바로 타이핑할 수 있어야
// 하는데, 진입 후 필드를 한 번 더 탭해야 하는 마찰이 있었다. S3-37이 웹 훅(whymathFocus)을
// Dart에 배선했고, S3-50이 실기기 공백 2건을 봉합했다(원 커밋 fa08081의 S3-19 부분 대조로 발견):
//  ① 타이밍 — S3-37의 onPageFinished 호출은 이 자산에선 틀렸다: index.html의 모듈 스크립트가
//     top-level await로 비동기 실행되므로 페이지 로드 완료 시점엔 훅이 미정의일 수 있고,
//     && 가드 때문에 *무증상 no-op*이 된다(헤드리스 테스트로 못 잡는 실기기 전용 실패).
//     → 웹이 훅 정의 직후 보내는 WhymathMathReady 신호에서 호출하도록 교체.
//  ② 키보드 — mathVirtualKeyboardPolicy=manual에선 mf.focus()만으로 가상 키보드가 안 뜬다.
//     → whymathFocus가 mathVirtualKeyboard.show()까지 호출.
//
// 왜 위젯 테스트가 아니라 계약·소스 스캔인가: WebView는 플랫폼 뷰라 헤드리스 flutter test
// 에서 컨트롤러 생성조차 불가하다. 그래서 자동 포커스가 성립하기 위한 축들을 각각 동결한다 —
// ①웹이 훅·ready 신호를 제공하는가(자산 스캔) ②Dart가 ready 신호에서 훅을 부르는가(소스
// 스캔). 실기기에서의 실제 포커스·키보드 표시는 실기기 확인 몫이다.
//
// 스캔 술어는 모두 결함주입 테스트를 동반한다 — 배선이 빠진 소스에서 실제로 false를 내는지
// 확인해야 스캔이 "항상 통과하는 위장 검사"가 아님이 보장된다(CLAUDE.md 변별력 없는 검증 금지).
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/features/chat/presentation/mathlive_input_webview.dart';

/// MathLive 경로가 포커스 훅을 정의하는가 — 블록 첫 문장이 `mf.focus();`인 형태(S3-50).
bool _definesFocusHookForMathfield(String html) => RegExp(
      r'window\.whymathFocus\s*=\s*\(\)\s*=>\s*\{\s*mf\.focus\(\);',
    ).hasMatch(html);

/// textarea 폴백 경로가 포커스 훅을 정의하는가 — `window.whymathFocus = () => ta.focus()`.
///
/// MathLive 로드가 실패해 강등된 상태에서도 자동 포커스가 살아 있어야 한다(폴백은 구버전
/// WebView·자산 누락 시 실제로 타는 경로다).
bool _definesFocusHookForFallback(String html) =>
    RegExp(r'window\.whymathFocus\s*=\s*\(\)\s*=>\s*ta\.focus\(\)').hasMatch(html);

/// MathLive 경로 훅이 가상 키보드까지 띄우는가(S3-50 ②) — manual 정책에선 focus()만으로
/// 키보드가 안 뜨므로 show() 호출이 없으면 "포커스는 갔는데 키보드는 안 뜨는" 반쪽 성립이다.
bool _showsVirtualKeyboardInFocusHook(String html) =>
    html.contains('mathVirtualKeyboard.show()');

/// 웹이 훅 준비 완료를 두 경로(MathLive·폴백) *모두*에서 알리는가(S3-50 ①).
///
/// emitReady 정의(WhymathMathReady로 post)와 호출 2곳 이상을 요구한다 — 한쪽 경로만 알리면
/// 다른 쪽으로 강등됐을 때 자동 포커스가 무증상으로 죽는다.
bool _emitsReadyInBothPaths(String html) {
  final bool defined =
      RegExp(r'window\.WhymathMathReady\.postMessage').hasMatch(html);
  final int calls = 'emitReady();'.allMatches(html).length;
  return defined && calls >= 2;
}

/// `source`의 `name:` 콜백 본문(중괄호 블록)을 돌려준다 — 없으면 null.
///
/// 여는 중괄호부터 짝이 맞는 닫는 중괄호까지를 깊이 계산으로 잘라낸다. 문자열 리터럴 안의
/// 중괄호는 이 파일들에 없어(검사 대상이 위젯 배선 코드다) 단순 계수로 충분하다.
String? _callbackBodyOf(String source, String name) {
  final int at = source.indexOf('$name:');
  if (at < 0) return null;
  final int open = source.indexOf('{', at);
  if (open < 0) return null;
  int depth = 0;
  for (int i = open; i < source.length; i++) {
    if (source[i] == '{') depth++;
    if (source[i] == '}') {
      depth--;
      if (depth == 0) return source.substring(open, i + 1);
    }
  }
  return null;
}

/// Dart가 포커스를 *ready 신호에서* 부르는가(S3-50 ①) — 순서와 호출 지점까지 본다.
///
/// `WhymathMathReady` 채널 등록이 있고, 포커스 호출이 그 등록 위치 *뒤*(핸들러 내부)에
/// 있어야 한다. 그리고 포커스 호출은 **정확히 한 곳**이며 `onPageFinished` 콜백 본문 안에
/// 있으면 안 된다 — 타이밍이 틀린 구현(모듈 스크립트의 top-level await 때문에 그 시점엔
/// 훅이 미정의일 수 있어 `&&` 가드로 무증상 no-op이 된다)의 재유입을 막는 것이 이 술어의
/// 목적이다.
///
/// [S3-24 회수 시 술어 정정] 종전 판은 `setNavigationDelegate`가 소스에 *존재하기만 해도*
/// 실패시켰다. 그것은 이 가드가 작성된 2026-08-11 시점에 그 API의 유일한 용도가 포커스
/// 배선이었기 때문에 성립한 **대리 지표**였는데, 그 뒤 main에 착지한 MOB-19가 같은 API를
/// 전혀 다른 목적(로딩 인디케이터 종료·주 프레임 로드 실패 시 안내 폴백)으로 쓰면서 전제가
/// 무너졌다. 그대로 두면 이 가드는 "포커스 타이밍"이 아니라 "MOB-19 하드닝의 부재"를
/// 요구하게 되어, 회수를 위해 멀쩡한 생명주기 방어를 지워야 하는 거짓 강제가 된다.
/// 그래서 대리 지표를 버리고 **의도 자체**(포커스가 onPageFinished 안에서 불리지 않을 것)를
/// 구조로 검사한다 — 변별력은 약해지지 않는다(결함주입 4종으로 확인·아래 group 참조).
bool _wiresFocusOnReadyChannel(String source) {
  const String focusCall = 'runJavaScript(mathliveFocusScript)';
  final int channelAt = source.indexOf("'WhymathMathReady'");
  final int focusCallAt = source.indexOf(focusCall);
  if (channelAt < 0 || focusCallAt < 0) return false;
  // 포커스 호출은 단 한 곳 — 두 곳이면 한쪽이 틀린 타이밍일 수 있고, 어느 쪽이 실제로
  // 먼저 도는지 소스만 보고는 알 수 없다(모른다 ≠ 아니다).
  if (focusCall.allMatches(source).length != 1) return false;
  // onPageFinished 콜백 *본문*에 포커스 호출이 있으면 실패 — API의 존재 자체는 무해하다.
  final String? onPageFinished = _callbackBodyOf(source, 'onPageFinished');
  if (onPageFinished != null && onPageFinished.contains('mathliveFocusScript')) {
    return false;
  }
  return focusCallAt > channelAt;
}

/// 수식 입력 전용 화면이 자동 포커스를 opt-in 하는가 — `autofocus: true` 전달.
bool _optsIntoAutofocus(String source) =>
    RegExp(r'autofocus:\s*true').hasMatch(source);

void main() {
  // 테스트 실행 cwd = src/mobile (mathlive_input_asset_config_test 선례)
  final String indexHtml =
      File('assets/mathlive_input/index.html').readAsStringSync();
  final String webviewSource =
      File('lib/features/chat/presentation/mathlive_input_webview.dart')
          .readAsStringSync();
  final String screenSource =
      File('lib/features/chat/presentation/mathlive_input_screen.dart')
          .readAsStringSync();

  group('웹 계약 — index.html이 포커스 훅·ready 신호를 제공한다', () {
    test('MathLive 경로에 window.whymathFocus가 정의돼 있다(첫 문장 mf.focus)', () {
      expect(
        _definesFocusHookForMathfield(indexHtml),
        isTrue,
        reason: 'Dart의 자동 포커스 배선이 부르는 훅이다 — 사라지면 자동 포커스가 '
            '무증상으로 죽는다(JS 쪽은 `&&` 가드라 예외도 안 난다)',
      );
    });

    test('textarea 폴백 경로에도 window.whymathFocus가 정의돼 있다', () {
      expect(
        _definesFocusHookForFallback(indexHtml),
        isTrue,
        reason: 'MathLive 로드 실패로 강등된 상태(구버전 WebView·자산 누락)에서도 '
            '자동 포커스는 동작해야 한다',
      );
    });

    test('S3-50: MathLive 훅이 가상 키보드(show)까지 띄운다', () {
      expect(
        _showsVirtualKeyboardInFocusHook(indexHtml),
        isTrue,
        reason: 'manual 정책에선 focus()만으로 키보드가 안 뜬다 — show()가 빠지면 '
            '"포커스는 갔는데 키보드는 안 뜨는" 반쪽 성립(실기기 전용 실패)',
      );
    });

    test('S3-50: ready 신호(emitReady)가 두 경로 모두에서 발신된다', () {
      expect(
        _emitsReadyInBothPaths(indexHtml),
        isTrue,
        reason: '모듈 스크립트는 top-level await로 비동기라 onPageFinished 시점엔 '
            '훅이 미정의일 수 있다 — ready 신호가 자동 포커스 성립의 기준점이며, '
            '폴백 경로도 알려야 강등 시 무증상 실패가 없다',
      );
    });
  });

  group('Dart 배선 — ready 신호에서 훅을 부른다', () {
    test('포커스 스크립트는 존재 확인 가드를 포함한다', () {
      expect(mathliveFocusScript, contains('window.whymathFocus'));
      expect(
        mathliveFocusScript,
        contains('&&'),
        reason: 'ready 신호가 타이밍을 보장하지만 방어 가드는 유지한다'
            '(whymathClear 호출과 동일 패턴)',
      );
    });

    test('S3-50: WebView가 WhymathMathReady 채널에서 포커스를 부른다(onPageFinished 아님)', () {
      expect(
        _wiresFocusOnReadyChannel(webviewSource),
        isTrue,
        reason: 'onPageFinished 시점엔 훅이 미정의일 수 있어 무증상 no-op이 된다 — '
            'ready 채널 기반이어야 하고, onPageFinished 배선이 재유입되면 실패다',
      );
    });

    test('수식 입력 전용 화면이 autofocus: true로 opt-in 한다', () {
      expect(
        _optsIntoAutofocus(screenSource),
        isTrue,
        reason: 'autofocus 기본값은 false(인라인 임베드 보호)이므로, 전용 화면이 '
            '명시적으로 켜지 않으면 배선이 있어도 동작하지 않는다',
      );
    });

    test('autofocus 기본값은 false다 — 인라인 임베드가 키보드를 띄우지 않는다', () {
      // 위젯 생성만 한다(pump 금지 — 컨트롤러가 플랫폼 뷰를 요구한다).
      const MathliveInputWebView inline = MathliveInputWebView(onChanged: _noop);
      expect(
        inline.autofocus,
        isFalse,
        reason: '기본값이 true면 인라인 임베드에서 학생이 의도하지 않은 시점에 '
            '키보드가 떠 다른 콘텐츠를 덮는다(opt-in 계약)',
      );
    });
  });

  group('결함주입 — 스캔 술어가 변별력을 갖는다', () {
    test('훅이 없는 html은 검출된다(MathLive·폴백 각각)', () {
      const String noHooks = '<html><script>const mf = 1;</script></html>';
      expect(_definesFocusHookForMathfield(noHooks), isFalse);
      expect(_definesFocusHookForFallback(noHooks), isFalse);
    });

    test('S3-37 구형(키보드 없는 단일식 훅)은 MathLive 술어에서 검출된다', () {
      // 구형 `() => mf.focus()`(show 없음)가 재유입되면 블록형 술어가 잡는다.
      const String legacy = 'window.whymathFocus = () => mf.focus();';
      expect(_definesFocusHookForMathfield(legacy), isFalse);
      expect(_showsVirtualKeyboardInFocusHook(legacy), isFalse);
    });

    test('ready 신호가 한쪽 경로에만 있으면 검출된다', () {
      const String oneCall = '''
        function emitReady() { window.WhymathMathReady.postMessage("ready"); }
        emitReady();
      ''';
      expect(_emitsReadyInBothPaths(oneCall), isFalse,
          reason: '호출 1곳뿐 — 폴백 강등 시 무증상 실패를 놓친다');
    });

    test('포커스 호출이 아예 없는 소스는 검출된다', () {
      const String noCall = "addJavaScriptChannel('WhymathMathReady',)";
      expect(_wiresFocusOnReadyChannel(noCall), isFalse);
    });

    test('onPageFinished 기반 구형 배선이 재유입되면 검출된다', () {
      const String legacyWiring = '''
        ..setNavigationDelegate(NavigationDelegate(onPageFinished: (_) {
          _controller.runJavaScript(mathliveFocusScript);
        }))
        ..addJavaScriptChannel('WhymathMathReady', onMessageReceived: (_) {})
      ''';
      expect(
        _wiresFocusOnReadyChannel(legacyWiring),
        isFalse,
        reason: '타이밍이 틀린 구현(onPageFinished)이 남아 있으면 실패해야 한다',
      );
    });

    test('autofocus를 켜지 않은 화면 소스는 검출된다', () {
      const String notOptedIn = 'MathliveInputWebView(onChanged: _onLatexChanged)';
      expect(_optsIntoAutofocus(notOptedIn), isFalse);
    });

    test('autofocus: false만 있는 소스도 검출된다', () {
      const String explicitlyOff =
          'MathliveInputWebView(onChanged: _x, autofocus: false)';
      expect(_optsIntoAutofocus(explicitlyOff), isFalse);
    });
  });
}

/// 위젯 생성용 무동작 콜백(const 생성자 인자 — 톱레벨 함수여야 const가 된다).
void _noop(String _) {}
