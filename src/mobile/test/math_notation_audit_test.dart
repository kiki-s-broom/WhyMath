// 수식 표기 전수 감사 테스트 (S3-23) — MathLive 입력 팔레트 전 구성요소가 교과서 조판되는지.
//
// 배경(2026-07-23 실기기·Kiki #2·#3): 이계도함수 f″가 교과서 표기가 아니었다. 실측(프로브)으로
// 원인 규명 — MathLive는 ■″ 버튼을 `f^\doubleprime`로 직렬화하는데(번들 v0.110.0), flutter_math_fork
// 0.7.4에 `\doubleprime`가 없어 raw로 폴백됐다. 코퍼스는 별도로 유니코드 `f″`(U+2033)를 써 프로즈
// 글리프로 샜다. 두 경로를 모두 지원 등가물로 정규화한다(표현≠의미·의미추론/검증 없음·fail-closed).
//
// 검증 축: ①plainMathToLatex 미지원 매크로 정규화(순수) ②normalizeUnicodeMath 유니코드 조판
// 되돌림(순수) ③위젯 — 각 팔레트 구성요소가 Math(flutter_math)로 조판되고 raw가 안 남음·파싱
// 불가는 원문 폴백(크래시 0). 회귀 안전: 기존 렌더·선택지·완료 흐름 불변(math_text_test.dart와 상보).
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/shared/math/math_notation.dart';
import 'package:korean_math_app/shared/widgets/math_text.dart';

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: Center(child: child)));

/// 구성요소 [input]이 Math로 조판되고(폴백 아님) raw 원문이 평문으로 안 보이는지 확인한다.
/// [rawIfBroken]은 렌더가 깨졌을 때 폴백 Text로 노출될 문자열(세그먼트 원문) — 이게 안 보이면
/// 성공 렌더다(변별력). 크래시 0도 함께 단언한다(fail-closed).
Future<void> _expectRenders(
  WidgetTester tester,
  String input, {
  required String rawIfBroken,
}) async {
  await tester.pumpWidget(_wrap(MathText(input)));
  expect(find.byType(Math), findsWidgets, reason: '"$input"은 수식으로 라우팅돼야 한다');
  expect(
    find.text(rawIfBroken),
    findsNothing,
    reason: '"$input"이 폴백 없이 조판돼야 한다(raw "$rawIfBroken" 미노출)',
  );
  expect(tester.takeException(), isNull);
}

void main() {
  group('plainMathToLatex — 미지원 매크로 정규화(순수·S3-23)', () {
    test('더블프라임: MathLive \\doubleprime → {\\prime\\prime}(이계도함수)', () {
      // f^\doubleprime(x) → f^{\prime\prime}(x): 캐럿이 그룹 전체를 잡아 두 프라임이 위첨자로 붙는다.
      expect(plainMathToLatex(r'f^\doubleprime(x)'), r'f^{\prime\prime}(x)');
      expect(plainMathToLatex(r'f^{\doubleprime}'), r'f^{{\prime\prime}}'); // 브레이스형(중첩·무해)
      expect(plainMathToLatex(r'\dprime'), r'{\prime\prime}');
    });

    test('트리플프라임: \\trprime → {\\prime\\prime\\prime}(삼계도함수)', () {
      expect(plainMathToLatex(r'f^\trprime'), r'f^{\prime\prime\prime}');
    });

    test('미분 d·e: \\differentialD → \\mathrm{d}', () {
      expect(plainMathToLatex(r'\differentialD x'), r'\mathrm{d} x');
      expect(plainMathToLatex(r'\differentialE'), r'\mathrm{e}');
      expect(plainMathToLatex(r'\capitalDifferentialD'), r'\mathrm{D}');
    });

    test('자동 크기 괄호: \\mleft·\\mright → \\left·\\right', () {
      expect(plainMathToLatex(r'\mleft(x\mright)'), r'\left(x\right)');
    });

    test('절대값·노름: \\abs{X}·\\norm{X} → \\left|·\\right| 형', () {
      expect(plainMathToLatex(r'\abs{x}'), r'\left|x\right|');
      expect(plainMathToLatex(r'\norm{v}'), r'\left\|v\right\|');
    });

    test('자리표시자: \\placeholder{X} → X(빈 필드는 빈 문자열)', () {
      expect(plainMathToLatex(r'\placeholder{n}'), 'n');
      expect(plainMathToLatex(r'x^{\placeholder{}}'), 'x^{}');
    });

    test('괄호형 강세 복원: \\overline(AB)·\\vec(v) → 브레이스 그룹', () {
      // latex_to_plain의 {}→() 변환으로 깨진 강세 인자를 되돌린다(오버바가 AB 전체에 걸리게).
      expect(plainMathToLatex(r'\overline(AB)'), r'\overline{AB}');
      expect(plainMathToLatex(r'\vec(v)'), r'\vec{v}');
      expect(plainMathToLatex(r'\overrightarrow(AB)'), r'\overrightarrow{AB}');
      expect(plainMathToLatex(r'\bar(x)'), r'\bar{x}');
    });

    test('회귀: 이미 유효한 브레이스 강세·프라임은 불변', () {
      expect(plainMathToLatex(r'\overline{AB}'), r'\overline{AB}');
      expect(plainMathToLatex(r'f^{\prime}(x)'), r'f^{\prime}(x)');
      expect(plainMathToLatex(r'f^(\prime)(x)'), r'f^{\prime}(x)'); // 기존 괄호형 경로 유지
    });
  });

  group('normalizeUnicodeMath — 유니코드 조판 되돌림(순수·S3-23)', () {
    test('유니코드 상첨자 → 캐럿 그룹', () {
      expect(normalizeUnicodeMath('x²'), 'x^{2}');
      expect(normalizeUnicodeMath('x³'), 'x^{3}');
      expect(normalizeUnicodeMath('x⁻¹'), 'x^{-1}');
      expect(normalizeUnicodeMath('aⁿ'), 'a^{n}');
    });

    test('유니코드 프라임 → 캐럿 프라임(1·2·3계)', () {
      expect(normalizeUnicodeMath('f′'), r'f^{\prime}');
      expect(normalizeUnicodeMath('f″'), r'f^{\prime\prime}'); // 이계도함수(핵심)
      expect(normalizeUnicodeMath('f‴'), r'f^{\prime\prime\prime}');
    });

    test('회귀: 순수 한글·ASCII 캐럿은 불변', () {
      expect(normalizeUnicodeMath('안녕하세요'), '안녕하세요');
      expect(normalizeUnicodeMath('x^3'), 'x^3');
    });
  });

  group('MathText 위젯 — 팔레트 구성요소 조판(렌더/폴백·S3-23)', () {
    testWidgets('이계도함수 MathLive형 f^\\doubleprime(x) — 조판·폴백 아님', (tester) async {
      await _expectRenders(tester, r'f^\doubleprime(x)',
          rawIfBroken: r'f^\doubleprime(x)');
    });

    testWidgets('이계도함수 유니코드형 f″(x) — 프로즈 아닌 수식으로 라우팅·조판', (tester) async {
      await tester.pumpWidget(_wrap(const MathText('f″(x)')));
      // 유니코드 프라임이 캐럿으로 정규화돼 수식으로 라우팅됐다(프로즈였다면 Math가 없다).
      expect(find.byType(Math), findsOneWidget);
      // 날 유니코드 글리프가 평문으로 남지 않는다(교과서 위첨자로 조판).
      expect(find.text('f″(x)'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('고차도함수 f^{(n)}·삼계 f‴ — 조판', (tester) async {
      await _expectRenders(tester, r'f^{(n)}(x)', rawIfBroken: r'f^{(n)}(x)');
      await tester.pumpWidget(_wrap(const MathText('f‴')));
      expect(find.byType(Math), findsOneWidget);
      expect(find.text('f‴'), findsNothing);
    });

    testWidgets('편미분 ∂·분수형 편도함수 — 조판', (tester) async {
      await _expectRenders(tester, r'\partial', rawIfBroken: r'\partial');
      await _expectRenders(tester, r'\frac{\partial f}{\partial x}',
          rawIfBroken: r'\frac{\partial f}{\partial x}');
    });

    testWidgets('극한 lim·lim_{x→∞} — 조판', (tester) async {
      await _expectRenders(tester, r'\lim_{x\to\infty}',
          rawIfBroken: r'\lim_{x\to\infty}');
    });

    testWidgets('이중적분 ∬·삼중적분 ∭ — 조판', (tester) async {
      await _expectRenders(tester, r'\iint', rawIfBroken: r'\iint');
      await _expectRenders(tester, r'\iiint', rawIfBroken: r'\iiint');
    });

    testWidgets('오버바·벡터·화살표(괄호형 포함) — 조판', (tester) async {
      await _expectRenders(tester, r'\overline{AB}', rawIfBroken: r'\overline{AB}');
      await _expectRenders(tester, r'\overline(AB)', rawIfBroken: r'\overline(AB)');
      await _expectRenders(tester, r'\overrightarrow{AB}',
          rawIfBroken: r'\overrightarrow{AB}');
      await _expectRenders(tester, r'\vec(v)', rawIfBroken: r'\vec(v)');
    });

    testWidgets('n제곱근 \\sqrt[3]{x}·\\sqrt[n]{x} — 조판', (tester) async {
      await _expectRenders(tester, r'\sqrt[3]{x}', rawIfBroken: r'\sqrt[3]{x}');
      await _expectRenders(tester, r'\sqrt[n]{x}', rawIfBroken: r'\sqrt[n]{x}');
    });

    testWidgets('미분 d(\\differentialD)·자동괄호(\\mleft) — 조판', (tester) async {
      await _expectRenders(tester, r'\differentialD x',
          rawIfBroken: r'\differentialD x');
      await _expectRenders(tester, r'\mleft(x+1\mright)',
          rawIfBroken: r'\mleft(x+1\mright)');
    });

    testWidgets('절대값·노름 \\abs·\\norm — 조판', (tester) async {
      await _expectRenders(tester, r'\abs{x}', rawIfBroken: r'\abs{x}');
      await _expectRenders(tester, r'\norm{v}', rawIfBroken: r'\norm{v}');
    });

    testWidgets('로그 하첨자 \\log_{10}·역삼각 \\sin^{-1} — 조판', (tester) async {
      await _expectRenders(tester, r'\log_{10}x', rawIfBroken: r'\log_{10}x');
      await _expectRenders(tester, r'\sin^{-1}x', rawIfBroken: r'\sin^{-1}x');
    });

    testWidgets('그리스 대표(소문자·변형·대문자) — 조판', (tester) async {
      for (final g in <String>[
        r'\alpha', r'\beta', r'\theta', r'\varepsilon', r'\varkappa',
        r'\varphi', r'\omega', r'\Gamma', r'\Delta', r'\Sigma', r'\Omega',
      ]) {
        await _expectRenders(tester, g, rawIfBroken: g);
      }
    });

    testWidgets('유니코드 상첨자 x³ — 프로즈 아닌 수식 조판', (tester) async {
      await tester.pumpWidget(_wrap(const MathText('x³')));
      expect(find.byType(Math), findsOneWidget);
      expect(find.text('x³'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('fail-closed: 미지원 매크로는 raw 평문으로 폴백(크래시 0)', (tester) async {
      await tester.pumpWidget(_wrap(const MathText(r'\totallyunknownmacro')));
      expect(find.text(r'\totallyunknownmacro'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('회귀: 순수 한글 프로즈는 평문 Text·수식 없음(무회귀)', (tester) async {
      await tester.pumpWidget(_wrap(const MathText('다시 한번 볼까요')));
      expect(find.text('다시 한번 볼까요'), findsOneWidget);
      expect(find.byType(Math), findsNothing);
    });
  });
}
