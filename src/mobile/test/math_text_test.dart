// 수식 렌더 테스트 (S3-21) — 한국 수학교과서 표기 렌더의 정규화·세그먼트·위젯 fail-closed.
//
// 실측 증상(2026-07-22 실기기): 문항("삼차함수 f(x) = x^3 …")·코치 발화·풀이 수식이 raw
// 캐럿(x^2)·평문 LaTeX(\lbrack·f^(\prime))로 노출됐다. 목표는 그 수식들을 조판된 수학 표기로
// 렌더하는 것(위첨자·프라임·분수·근호·괄호). 표현≠의미(CLAUDE.md): 렌더만·의미추론/검증 없음.
//
// 검증 축: ①표기 정규화 순수함수(캐럿/아래첨자 그룹·분수·근호·곱셈) ②프로즈+수식 세그먼트
// (한글 경계 분해·신호 없는 값은 평문) ③위젯 — 수식은 Math(flutter_math)로 렌더되고 raw
// 문자열은 안 보임·파싱 불가는 raw 폴백(크래시 0)·순수 프로즈는 평문 Text(무회귀).
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/shared/math/math_notation.dart';
import 'package:korean_math_app/shared/widgets/math_text.dart';

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  group('plainMathToLatex — 표기 정규화(순수)', () {
    test('캐럿 숫자런을 그룹으로 감싼다(x^2 → x^{2})', () {
      expect(plainMathToLatex('x^2'), 'x^{2}');
      expect(plainMathToLatex('3x^2+6x-144'), '3x^{2}+6x-144');
      expect(plainMathToLatex('x^23'), 'x^{23}'); // 다중 자리 지수 보존.
    });

    test('캐럿 괄호 그룹을 중괄호 그룹으로(핵심 수정: f^(\\prime) → f^{\\prime})', () {
      // latex_to_plain이 중괄호를 괄호로 바꿔 깨진 지수를 되돌린다(^가 그룹 전체에 붙게).
      expect(plainMathToLatex(r'f^(\prime)(x)'), r'f^{\prime}(x)');
      expect(plainMathToLatex('x^(2)'), 'x^{2}');
    });

    test('아래첨자도 캐럿과 대칭으로 그룹화한다(a_(1) → a_{1})', () {
      expect(plainMathToLatex('a_(1)'), 'a_{1}');
      expect(plainMathToLatex('a_1'), 'a_{1}');
    });

    test('분수·근호 산출형을 되돌린다', () {
      expect(plainMathToLatex('((1)/(2))'), r'\frac{1}{2}');
      expect(plainMathToLatex('((3x)/(2))'), r'\frac{3x}{2}');
      expect(plainMathToLatex('sqrt((x))'), r'\sqrt{x}');
    });

    test('곱셈 별표를 \\cdot으로(양옆 공백으로 토큰 접합 방지)', () {
      expect(plainMathToLatex('3*4'), r'3 \cdot 4');
      expect(plainMathToLatex('2*x'), r'2 \cdot x');
    });

    test('이미 유효한 LaTeX는 캐럿/아래첨자 그룹을 건드리지 않는다', () {
      expect(plainMathToLatex(r'f^{\prime}(x)'), r'f^{\prime}(x)');
      expect(plainMathToLatex(r'x^{2}+1'), r'x^{2}+1');
    });
  });

  group('segmentMathText — 프로즈+수식 세그먼트(순수·무손실)', () {
    test('한국어 문항을 한글 경계에서 프로즈/수식으로 자른다', () {
      const q = '삼차함수 f(x) = x^3 + 3x^2 - 144x에서 극소가 되는 x의 값을 구하시오';
      final segs = segmentMathText(q);
      // 조각을 이으면 원문과 정확히 같다(무손실).
      expect(segs.map((s) => s.text).join(), q);
      // 수식 조각은 캐럿을 포함한 그 식 하나뿐(외톨이 'x'는 신호 없어 프로즈로 흡수).
      final math = segs.where((s) => s.isMath).toList();
      expect(math.length, 1);
      expect(math.single.text, 'f(x) = x^3 + 3x^2 - 144x');
      // 프로즈 조각들은 한글 맥락을 담는다.
      expect(segs.first.text, '삼차함수 ');
      expect(segs.any((s) => !s.isMath && s.text.contains('극소가 되는')), isTrue);
    });

    test('한글 없는 풀이 수식은 한 덩어리(수식) 조각이다', () {
      const sol = r'f^(\prime)(x)=3x^2+6x-144=3\lbrack x+8\rbrack(x-6)';
      final segs = segmentMathText(sol);
      expect(segs.length, 1);
      expect(segs.single.isMath, isTrue);
      expect(segs.single.text, sol);
    });

    test('순수 한국어는 프로즈 한 조각(수식 조각 0)', () {
      final segs = segmentMathText('안녕하세요 반갑습니다');
      expect(segs.every((s) => !s.isMath), isTrue);
      expect(segs.map((s) => s.text).join(), '안녕하세요 반갑습니다');
    });

    test('신호만 있고 피연산자가 없으면 수식이 아니다(구두점 안전)', () {
      // '*미완'·'**'는 강조/구두점 폴백 — 수식으로 오인하지 않는다.
      expect(segmentMathText('*미완').every((s) => !s.isMath), isTrue);
      expect(segmentMathText('**').every((s) => !s.isMath), isTrue);
    });

    test('신호 없는 단순 값은 평문으로 남는다(선택지 0·2·x=2·k<-1)', () {
      for (final v in <String>['0', '2', 'x=2', 'k<-1', 'ㄱ']) {
        expect(
          segmentMathText(v).every((s) => !s.isMath),
          isTrue,
          reason: '"$v"는 수식 신호가 없어 평문이어야 한다',
        );
      }
    });

    test('곱셈 별표는 수식 신호다(3*4 → 수식)', () {
      final segs = segmentMathText('3*4');
      expect(segs.length, 1);
      expect(segs.single.isMath, isTrue);
    });
  });

  group('MathText 위젯 — 렌더/폴백', () {
    testWidgets('캐럿 수식(x^2)은 Math로 렌더되고 raw 문자열은 안 보인다', (tester) async {
      await tester.pumpWidget(_wrap(const MathText('x^2')));
      // 조판된 수식 위젯이 존재한다.
      expect(find.byType(Math), findsOneWidget);
      // 변별력: 렌더 실패였다면 raw 'x^2'가 평문 Text로 남아 아래 단언이 실패한다.
      expect(find.text('x^2'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('LaTeX 수식(\\prime·\\lbrack)도 Math로 렌더된다', (tester) async {
      await tester.pumpWidget(
        _wrap(const MathText(r'f^(\prime)(x)=3\lbrack x+8\rbrack(x-6)')),
      );
      expect(find.byType(Math), findsOneWidget);
      // raw LaTeX가 그대로 안 보인다(성공 렌더 = 폴백 아님).
      expect(find.text(r'f^(\prime)(x)=3\lbrack x+8\rbrack(x-6)'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('파싱 불가 문자열은 raw 평문으로 폴백한다(크래시 0)', (tester) async {
      await tester.pumpWidget(_wrap(const MathText(r'\nonexistentmacro')));
      // fail-closed: 원문이 그대로 평문으로 보인다(앱은 죽지 않는다).
      expect(find.text(r'\nonexistentmacro'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('순수 프로즈는 평문 Text로 렌더된다(무회귀·find.text 호환)', (tester) async {
      await tester.pumpWidget(_wrap(const MathText('안녕하세요 반갑습니다')));
      expect(find.text('안녕하세요 반갑습니다'), findsOneWidget);
      expect(find.byType(Math), findsNothing);
    });

    testWidgets('혼합 문항 — 프로즈는 보이고 수식만 Math로 조판된다', (tester) async {
      await tester.pumpWidget(
        _wrap(
          const MathText(
            '삼차함수 f(x) = x^3 + 3x^2 - 144x에서 극소가 되는 x의 값을 구하시오',
          ),
        ),
      );
      // 수식 런은 한 개만 Math로(외톨이 x는 프로즈).
      expect(find.byType(Math), findsOneWidget);
      // 한국어 프로즈는 그대로 노출된다(WidgetSpan 혼합이라 textContaining으로 확인).
      expect(find.textContaining('삼차함수'), findsOneWidget);
      expect(find.textContaining('극소가 되는'), findsOneWidget);
      // raw 캐럿 조각은 평문으로 보이지 않는다.
      expect(find.textContaining('x^3'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });
}
