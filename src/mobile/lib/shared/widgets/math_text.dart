// 수식 렌더 위젯 (S3-21·NS-02) — 프로즈+수식이 섞인 문자열을 한국 수학교과서 조판으로 그린다.
//
// 경계(CLAUDE.md 표현≠의미): 렌더(표현)만 한다 — 수학 의미·정오·동치 판정은 백엔드(L3) 몫.
// 세그먼트·표기 정규화는 math_notation.dart(순수)가, 실제 조판은 flutter_math_fork(KaTeX·순수
// Dart 렌더러·WebView 불요)가 한다. 여기서는 그 둘을 이어 위젯으로 만들 뿐이다.
//
// NS-02: 이 파일은 정규화·세그먼트·LaTeX 산출을 *직접 조합하지 않는다* — canonical 진입점
// (renderSegments·renderLatexFor)만 소비한다. 조합 순서의 단일 진실은 math_notation.dart다
// (위젯마다 재조립하며 생기던 드리프트 위험 제거·산출 바이트는 종전과 동일).
//
// fail-closed(절대 원칙·크래시 0): 수식 조각이 파싱 불가하면 그 조각만 *원문 그대로* 평문으로
// 폴백한다(Math.tex의 onErrorFallback). 앱은 어떤 입력에도 죽지 않고, 최악의 경우 오늘과 같은
// raw 표기를 보일 뿐이다(로그 없이 graceful). 순수 프로즈는 기존과 동일한 평문 Text로 그린다.
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';

import '../math/math_notation.dart';

/// 프로즈+수식 혼합 문자열을 렌더하는 위젯(기존 [Text]의 드롭인 대체).
///
/// - 수식 신호가 없는 순수 프로즈: 기존과 완전히 동일한 평문 [Text](무회귀).
/// - 수식 한 덩어리(한글 없는 풀이·수식): 가로 스크롤로 긴 식도 넘치지 않게 조판(MOB-02 정합).
/// - 혼합(문항 등): 프로즈는 흐르는 텍스트, 수식은 인라인 위젯으로 끼워 넣어 조판(교과서처럼).
class MathText extends StatelessWidget {
  const MathText(this.text, {super.key, this.style, this.textAlign});

  /// 렌더할 원문(캐럿/평문 표기 포함 가능).
  final String text;

  /// 기본 텍스트 스타일(수식 크기·색도 이 스타일에 맞춘다·null이면 컨텍스트 기본).
  final TextStyle? style;

  /// 텍스트 정렬(순수 프로즈·혼합 모두 적용).
  final TextAlign? textAlign;

  @override
  Widget build(BuildContext context) {
    // canonical 진입점(NS-02): 유니코드 정규화 → 세그먼트를 단일 조립점에 위임한다(S3-23 동작 동일).
    final segments = renderSegments(text);
    final mathCount = segments.where((s) => s.isMath).length;

    // 순수 프로즈 — 기존 렌더와 바이트 단위 동일(무회귀·find.text 호환).
    // (수식이 하나도 없으면 정규화가 아무것도 안 바꾼 것이므로 원문 [text]와 동일하다.)
    if (mathCount == 0) {
      return Text(text, style: style, textAlign: textAlign);
    }

    final baseStyle = _resolveStyle(context);

    // 수식 한 덩어리(프로즈 없음) — 가로 스크롤 박스로 그려 긴 풀이도 넘치지 않게 한다.
    if (segments.length == 1) {
      return _ScrollableMath(segment: segments.first, style: baseStyle);
    }

    // 혼합 — 프로즈 TextSpan + 수식 WidgetSpan을 흐르는 텍스트로 조판한다.
    return Text.rich(
      TextSpan(style: baseStyle, children: mathInlineSpans(segments, baseStyle)),
      textAlign: textAlign ?? TextAlign.start,
    );
  }

  /// 컨텍스트 기본 스타일에 [style]을 병합해 fontSize·color가 확정된 스타일을 만든다.
  /// (Math.tex는 fontSize 비-null을 요구하므로 컨텍스트 DefaultTextStyle을 바닥으로 깐다.)
  TextStyle _resolveStyle(BuildContext context) {
    final base = DefaultTextStyle.of(context).style;
    final merged = base.merge(style);
    // 방어: 어떤 경로로든 fontSize가 비면 Material 기본값으로 채운다(Math.tex 크래시 방지).
    return merged.fontSize == null ? merged.copyWith(fontSize: 14) : merged;
  }
}

/// [MathSegment] 리스트를 인라인 스팬으로 바꾼다(프로즈=TextSpan·수식=WidgetSpan).
///
/// 인접 프로즈는 하나의 TextSpan으로 병합한다(불필요한 스팬 방지·기존 강조 테스트 호환).
/// 수식 조각의 canonical LaTeX는 [renderLatexFor](단일 지점·NS-02)가 산출하고 [Math.tex]로
/// 그리되, 파싱 실패 시 *세그먼트 원문* 평문으로 폴백한다(fail-closed).
List<InlineSpan> mathInlineSpans(List<MathSegment> segments, TextStyle style) {
  final spans = <InlineSpan>[];
  final proseBuf = StringBuffer();
  void flushProse() {
    if (proseBuf.isNotEmpty) {
      spans.add(TextSpan(text: proseBuf.toString()));
      proseBuf.clear();
    }
  }

  for (final seg in segments) {
    if (!seg.isMath) {
      proseBuf.write(seg.text);
      continue;
    }
    flushProse();
    spans.add(
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Math.tex(
          renderLatexFor(seg),
          mathStyle: MathStyle.text,
          textStyle: style,
          onErrorFallback: (_) => Text(seg.text, style: style),
        ),
      ),
    );
  }
  flushProse();
  return spans;
}

/// 원문 문자열을 곧장 인라인 스팬으로(세그먼트 포함) — 접두사와 함께 조립할 때 쓴다.
///
/// 예: 선택지 "N. [값]"의 값 부분을 번호 접두사 TextSpan 뒤에 이어 붙일 때.
/// 세그먼트는 canonical 진입점 [renderSegments]에 위임한다(NS-02·재조립 금지).
List<InlineSpan> mathInlineSpansFor(String text, TextStyle style) =>
    mathInlineSpans(renderSegments(text), style);

/// 수식 한 덩어리를 가로 스크롤 박스로 그린다 — 긴 풀이 수식이 버블·배너 폭을 넘어도
/// 넘침(RenderFlex/클리핑) 없이 옆으로 스크롤해 전체를 볼 수 있게 한다(MOB-02 정합).
class _ScrollableMath extends StatelessWidget {
  const _ScrollableMath({required this.segment, required this.style});

  /// 렌더할 수식 조각 — canonical LaTeX는 [renderLatexFor]가 산출하고(NS-02 단일 지점),
  /// 파싱 실패 시 [MathSegment.text](정규화 전 원문)를 그대로 보인다(fail-closed 불변).
  final MathSegment segment;

  /// 조판 스타일(fontSize·color 확정).
  final TextStyle style;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Math.tex(
        renderLatexFor(segment),
        mathStyle: MathStyle.text,
        textStyle: style,
        onErrorFallback: (_) => Text(segment.text, style: style),
      ),
    );
  }
}
