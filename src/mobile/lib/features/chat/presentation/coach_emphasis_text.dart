// 코치 발화 경량 강조 렌더 (MOB-04) — L4 결정론 템플릿의 `*...*` 표기를 굵게 표시한다.
//
// 실측 증상(2026-07-19 실기기): 코치 버블에 Polya 템플릿의 마크다운 강조가 원문
// 그대로 노출 — "좋아, 이제 *어떻게 풀지* 계획을 세워보자."의 별표가 평문으로 보였다.
//
// 경계(CLAUDE.md 표현≠의미): `*...*`는 템플릿(L4)이 담은 *의미*(강조)이고, 그것을
// 어떻게 보일지는 표현 계층(L5)의 몫이다 — 서버 템플릿은 무변경, 렌더만 여기서 한다.
// 전체 마크다운 엔진은 도입하지 않는다(pubspec 무접촉) — 코치 템플릿이 쓰는 표기는
// `*...*` 한 가지뿐이라 초소형 파서로 충분하고, 그 이상은 과설계다.
//
// 이 *강조* 렌더는 코치 버블 전용이다. 학생 버블에는 절대 적용하지 않는다 — 학생 입력의
// 별표는 곱셈 기호(`3*4`)일 수 있어 강조로 해석하면 안 된다. 학생 버블은 대신 MathText로
// 곧장 간다(S3-39): 별표가 강조가 아니라 곱셈 `\cdot`으로 조판될 뿐이라 강조 오해가 없고,
// 글자를 잃지도 않는다(조판 실패 시 원문 폴백). "강조 해석 0" 불변식은 그대로다.
import 'package:flutter/material.dart';

import '../../../shared/widgets/math_text.dart';

/// 강조 파싱 결과 한 조각 — 부분 문자열과 강조 여부.
///
/// 파서는 텍스트를 이 조각들의 리스트로 자르기만 한다(스타일 결정은 위젯 몫).
/// 강조 조각의 [text]에는 여닫는 별표가 포함되지 않고, 비강조 조각은 원문 그대로다.
@immutable
class EmphasisSegment {
  const EmphasisSegment(this.text, {required this.emphasized});

  /// 조각 본문(강조 조각이면 별표 제거 후 내용, 아니면 원문 부분 문자열).
  final String text;

  /// 굵게 표시할 조각인지.
  final bool emphasized;

  @override
  bool operator ==(Object other) =>
      other is EmphasisSegment &&
      other.text == text &&
      other.emphasized == emphasized;

  @override
  int get hashCode => Object.hash(text, emphasized);

  @override
  String toString() => emphasized ? '강조($text)' : '평문($text)';
}

/// `*...*` 초소형 파서 — 코치 발화 전용.
///
/// 규칙(안전 폴백 우선 — 판정이 애매하면 항상 원문 그대로):
/// - `*내용*` 쌍은 내용이 ①비어 있지 않고 ②양끝이 공백이 아니며 ③줄바꿈을 포함하지
///   않을 때만 강조로 인정한다.
/// - 인정되지 않는 별표(짝 없음 `*미완`·빈 강조 `**`·닫는 별표가 없는 `3*4`)는 문자
///   그대로 남긴다 — 어떤 입력에서도 글자를 잃지 않는다(무손실).
/// - 곱셈 기호 오탐 방어: `3*4를 곱하고 *다시* 보자`에서 첫 별표는 닫는 후보까지의
///   내용("4를 곱하고 ")이 공백으로 끝나 쌍 인정이 거부되고 문자 그대로 남는다.
///   그 뒤 `*다시*`만 강조된다(왼쪽부터 한 번 훑는 결정론 파서·O(n)).
List<EmphasisSegment> parseCoachEmphasis(String text) {
  final List<EmphasisSegment> segments = <EmphasisSegment>[];
  final StringBuffer plain = StringBuffer();

  // 쌓인 평문 버퍼를 조각으로 내보낸다(강조 조각 사이의 접착부).
  void flushPlain() {
    if (plain.isNotEmpty) {
      segments.add(EmphasisSegment(plain.toString(), emphasized: false));
      plain.clear();
    }
  }

  int i = 0;
  while (i < text.length) {
    if (text[i] != '*') {
      plain.write(text[i]);
      i += 1;
      continue;
    }
    // 여는 별표 후보 — 다음 별표까지를 내용 후보로 본다.
    final int close = text.indexOf('*', i + 1);
    if (close == -1) {
      // 짝 없는 별표 — 원문 그대로(안전 폴백).
      plain.write('*');
      i += 1;
      continue;
    }
    final String content = text.substring(i + 1, close);
    final bool valid = content.isNotEmpty &&
        !content.contains('\n') &&
        content.trim().length == content.length; // 양끝 공백 없음.
    if (!valid) {
      // 빈 강조(`**`)·공백 경계 내용 — 이 별표는 문자로 두고 한 칸만 전진한다
      // (닫는 후보였던 별표는 다음 회차에 새 여는 후보로 재평가된다).
      plain.write('*');
      i += 1;
      continue;
    }
    flushPlain();
    segments.add(EmphasisSegment(content, emphasized: true));
    i = close + 1;
  }
  flushPlain();
  return segments;
}

/// 코치 버블 본문 텍스트 — `*...*` 강조는 굵게, 수식은 교과서 조판으로 렌더하는 Text 대체 위젯.
///
/// 강조(w700)는 색 없이 굵기로만 표현한다 — 색맹 친화 원칙(색만으로 정보 전달 금지)·테마 무관.
/// 강조가 하나도 없으면 [MathText]에 위임한다(순수 프로즈면 그 안에서 평문 [Text]로 폴백 —
/// 기존 렌더와 바이트 단위 동일·무회귀). 강조가 있으면 비강조 조각만 프로즈+수식으로 조판하고
/// (코치 발화의 `3x^2` 등), 강조 조각은 굵은 평문으로 둔다 — 코치 강조는 한국어 구절 대상이라
/// 강조 안 수식 렌더는 하지 않는다(단순·안전·원문 무손실). 수학 판정은 없다(표현≠의미).
class CoachEmphasisText extends StatelessWidget {
  const CoachEmphasisText(this.text, {super.key});

  /// 코치 발화 원문(템플릿 `*...*` 표기·수식 포함 가능).
  final String text;

  @override
  Widget build(BuildContext context) {
    final List<EmphasisSegment> segments = parseCoachEmphasis(text);
    final bool hasEmphasis = segments.any((s) => s.emphasized);
    if (!hasEmphasis) {
      // 강조가 없으면 수식 렌더만 — MathText가 순수 프로즈면 평문 Text로 폴백한다(무회귀).
      return MathText(text);
    }
    final TextStyle baseStyle = DefaultTextStyle.of(context).style;
    final List<InlineSpan> children = <InlineSpan>[];
    for (final EmphasisSegment segment in segments) {
      if (segment.emphasized) {
        children.add(
          TextSpan(
            text: segment.text,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        );
      } else {
        children.addAll(mathInlineSpansFor(segment.text, baseStyle));
      }
    }
    return Text.rich(TextSpan(style: baseStyle, children: children));
  }
}
