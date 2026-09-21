// 표기 canonical 파이프라인 테스트 (NS-02) — 단일 진입점·무회귀 봉인·매니페스트/계약 정합.
//
// NS-02(notation_semantics_layer.md §8)는 *리팩터+정합 형식화*다: 흩어져 있던 조합 순서
// (normalizeUnicodeMath → segmentMathText → 조각별 plainMathToLatex)를 canonical 진입점
// (renderSegments·renderLatexFor·toRenderLatex)에 캡슐화하되 산출은 바이트 단위로 종전과
// 동일해야 한다. 이 파일이 그 무회귀를 *봉인*하고, 지원 표기 매니페스트
// (data/notation_support_manifest.json — NS-03 커버리지 게이트의 입력)·표기 계약
// (data/notation_contract.json — SymPy↔mathjs canonical)과 Dart 파이프라인의 정합을 동결한다.
//
// 경계(표현≠의미): 여기서 검증하는 것은 전부 *표기* 변환·렌더 가능성이다. 수학 의미·동치·
// 정오 판정은 백엔드 L3(SymPy) 단일 권위 — 이 테스트는 그 영역을 건드리지 않는다.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korean_math_app/shared/math/math_notation.dart';
import 'package:korean_math_app/shared/widgets/math_text.dart';

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: Center(child: child)));

// 테스트 실행 cwd = src/mobile (flutter test 규약·governance 테스트와 동일 기준) → 레포 루트의
// data/는 두 단계 위다.
final File _manifestFile = File('../../data/notation_support_manifest.json');
final File _contractFile = File('../../data/notation_contract.json');

/// *구 조합*(NS-02 이전 위젯들이 각자 재조립하던 순서)을 그대로 재현한다 — 신 진입점과의
/// 바이트 동일성을 단언하기 위한 기준 구현. 공개 순수 함수 4종만 사용한다.
String _legacyComposition(String raw) =>
    segmentMathText(normalizeUnicodeMath(raw))
        .map((s) => s.isMath ? plainMathToLatex(s.text) : s.text)
        .join();

/// 계약(notation_contract.json)의 모든 식(numeric + equivalence 양변)을 모은다.
List<String> _contractExprs(Map<String, dynamic> contract) => <String>[
      for (final c in contract['numeric_cases'] as List<dynamic>)
        (c as Map<String, dynamic>)['expr'] as String,
      for (final c in contract['equivalence_cases'] as List<dynamic>) ...[
        (c as Map<String, dynamic>)['a'] as String,
        c['b'] as String,
      ],
    ];

/// 무회귀 봉인 코퍼스 — 감사 테스트(S3-23) 입력 + 렌더 테스트(S3-21) 입력 + 한글 혼합 프로즈.
/// (계약 식은 fixture에서 로드해 별도 그룹에서 같은 봉인을 돈다 — 단일 출처 유지.)
const List<String> _sealCorpus = <String>[
  // ── math_notation_audit_test.dart(S3-23) 입력들 ──
  'f^\\doubleprime(x)', 'f^{\\doubleprime}', '\\dprime', 'f^\\trprime',
  '\\differentialD x', '\\differentialE', '\\capitalDifferentialD',
  '\\mleft(x\\mright)', '\\abs{x}', '\\norm{v}', '\\placeholder{n}',
  'x^{\\placeholder{}}', '\\overline(AB)', '\\vec(v)', '\\overrightarrow(AB)',
  '\\bar(x)', '\\overline{AB}', 'f^{\\prime}(x)', 'f^(\\prime)(x)',
  'x²', 'x³', 'x⁻¹', 'aⁿ', 'f′', 'f″', 'f‴', '안녕하세요', 'x^3',
  'f^{(n)}(x)', '\\partial', '\\frac{\\partial f}{\\partial x}',
  '\\lim_{x\\to\\infty}', '\\iint', '\\iiint', '\\sqrt[3]{x}', '\\sqrt[n]{x}',
  '\\differentialD x', '\\mleft(x+1\\mright)', '\\log_{10}x', '\\sin^{-1}x',
  '\\alpha', '\\beta', '\\theta', '\\varepsilon', '\\varphi', '\\omega',
  '\\Gamma', '\\Delta', '\\Sigma', '\\Omega', '\\totallyunknownmacro',
  // ── math_text_test.dart(S3-21) 입력들 ──
  'x^2', '3x^2+6x-144', 'x^23', 'x^(2)', 'a_(1)', 'a_1',
  '((1)/(2))', '((3x)/(2))', 'sqrt((x))', '3*4', '2*x', 'x^{2}+1',
  '삼차함수 f(x) = x^3 + 3x^2 - 144x에서 극소가 되는 x의 값을 구하시오',
  'f^(\\prime)(x)=3x^2+6x-144=3\\lbrack x+8\\rbrack(x-6)',
  '안녕하세요 반갑습니다', '*미완', '**', '0', '2', 'x=2', 'k<-1', 'ㄱ',
  // ── 한글 혼합 프로즈 샘플(NS-02 신규 — 프로즈 무손실·수식만 canonical) ──
  '이계도함수 f″(x)를 구하면 f″(x) = 6x + 6 이다',
  '기울기는 ((f(b)-f(a))/(b-a)) 로 계산한다',
  '따라서 x² + 2*x 의 도함수는 2*x + 2 이다',
  '',
];

void main() {
  group('무회귀 바이트 동일 봉인 — 구 조합 vs 신 진입점 (NS-02)', () {
    test('봉인 코퍼스 전건: renderSegments == 구 세그먼트·toRenderLatex == 구 조합', () {
      for (final raw in _sealCorpus) {
        // 세그먼트 리스트 자체가 동일하다(MathSegment == 계약 사용·조각 경계 무변).
        expect(
          renderSegments(raw),
          segmentMathText(normalizeUnicodeMath(raw)),
          reason: '"$raw": renderSegments가 구 조합과 다른 세그먼트를 냈다',
        );
        // 최종 canonical 문자열이 바이트 단위로 동일하다(렌더 결과 무회귀의 근거).
        expect(
          toRenderLatex(raw),
          _legacyComposition(raw),
          reason: '"$raw": toRenderLatex가 구 조합 산출과 다르다(무회귀 위반)',
        );
        // 프리뷰 게이트 판정도 동일 기준이다(NS-01 계약 유지).
        expect(
          hasRenderableMath(raw),
          segmentMathText(normalizeUnicodeMath(raw)).any((s) => s.isMath),
          reason: '"$raw": hasRenderableMath 판정이 구 기준과 다르다',
        );
      }
    });

    test('계약 식 전건도 같은 봉인을 통과한다(fixture 단일 출처)', () {
      final contract = jsonDecode(_contractFile.readAsStringSync(encoding: utf8))
          as Map<String, dynamic>;
      for (final expr in _contractExprs(contract)) {
        expect(toRenderLatex(expr), _legacyComposition(expr),
            reason: '"$expr": 계약 식의 신/구 산출이 다르다');
      }
    });
  });

  group('canonical 진입점 단위 테스트 (NS-02 신규 API)', () {
    test('renderSegments — 유니코드 조판 입력이 수식으로 라우팅된다(정규화 선행 보장)', () {
      final segs = renderSegments('f″(x)');
      expect(segs.length, 1);
      expect(segs.single.isMath, isTrue);
      expect(segs.single.text, 'f^{\\prime\\prime}(x)');
    });

    test('renderSegments — 혼합 문항은 프로즈/수식 조각으로 나뉜다(무손실)', () {
      const q = '삼차함수 f(x) = x^3 + 3x^2 - 144x에서 극소가 되는 x의 값을 구하시오';
      final segs = renderSegments(q);
      expect(segs.map((s) => s.text).join(), q);
      expect(segs.where((s) => s.isMath).length, 1);
    });

    test('renderLatexFor — 수식 조각은 canonical LaTeX·프로즈 조각은 원문 그대로', () {
      const mathSeg = MathSegment('x^2', isMath: true);
      const proseSeg = MathSegment('극소가 되는 ', isMath: false);
      expect(renderLatexFor(mathSeg), plainMathToLatex('x^2'));
      expect(renderLatexFor(mathSeg), 'x^{2}');
      // 프로즈에는 표기 정규화를 적용하지 않는다(한글 무회귀·무손실).
      expect(renderLatexFor(proseSeg), '극소가 되는 ');
    });

    test('toRenderLatex — 순수 수식은 canonical LaTeX 그 자체다', () {
      expect(toRenderLatex('x^2'), 'x^{2}');
      expect(toRenderLatex('f″'), 'f^{\\prime\\prime}');
      expect(toRenderLatex('((1)/(2))'), '\\frac{1}{2}');
      expect(toRenderLatex('2*x'), '2 \\cdot x');
    });

    test('toRenderLatex — 혼합 입력은 프로즈를 보존하고 수식만 canonical로 바꾼다', () {
      expect(
        toRenderLatex('따라서 x² 의 도함수는 2*x 이다'),
        '따라서 x^{2} 의 도함수는 2 \\cdot x 이다',
      );
      // 수식이 전혀 없으면 원문 그대로다(항등·프로즈 무손실).
      expect(toRenderLatex('안녕하세요 반갑습니다'), '안녕하세요 반갑습니다');
      expect(toRenderLatex(''), '');
    });

    test('hasRenderableMath — renderSegments 기준과 동치(시그니처·판정 불변)', () {
      // 참 케이스: 캐럿·유니코드·MathLive LaTeX 모두 같은 진입점으로 판정된다.
      for (final t in <String>['x^2', 'f″(x)', '\\frac{1}{2}', '3*4']) {
        expect(hasRenderableMath(t), isTrue, reason: '"$t"는 수식이 있어야 한다');
        expect(hasRenderableMath(t), renderSegments(t).any((s) => s.isMath));
      }
      // 거짓 케이스: 신호 없는 단순 값·순수 프로즈·빈 문자열(NS-01 프리뷰 게이트 계약).
      for (final t in <String>['x=2', '0', 'ㄱ', '안녕하세요', '', '**']) {
        expect(hasRenderableMath(t), isFalse, reason: '"$t"는 수식이 없어야 한다');
        expect(hasRenderableMath(t), renderSegments(t).any((s) => s.isMath));
      }
    });

    test('anchorFor — Entity 앵커 seam은 지금 항상 null(Phase B 예약·기능 무영향)', () {
      // Registry는 의도적 미구현이다(노드 폭발 방어·notation_semantics_layer.md §5) —
      // 어떤 토큰이 와도 null이며, 렌더 경로는 이 값에 의존하지 않는다.
      for (final token in <String>['\\prime', 'x', '″', 'sqrt', '선분', '']) {
        expect(anchorFor(token), isNull, reason: '"$token": Phase A에선 앵커가 없어야 한다');
      }
    });
  });

  group('지원 표기 매니페스트 정합 — data/notation_support_manifest.json (NS-02)', () {
    late final Map<String, dynamic> manifest;

    setUpAll(() {
      expect(_manifestFile.existsSync(), isTrue,
          reason: '매니페스트 파일이 존재해야 한다(NS-03 커버리지 게이트의 입력)');
      final rawText = _manifestFile.readAsStringSync(encoding: utf8);
      expect(rawText.trim(), isNotEmpty, reason: '매니페스트가 비어 있으면 안 된다');
      manifest = jsonDecode(rawText) as Map<String, dynamic>;
    });

    test('입력형 선언 — 지원 3형 + NL 미지원 stub이 명시돼 있다', () {
      final forms = manifest['input_forms'] as Map<String, dynamic>;
      final supported = (forms['supported'] as List<dynamic>)
          .map((e) => (e as Map<String, dynamic>)['id'])
          .toList();
      expect(supported,
          containsAll(<String>['mathlive_latex', 'unicode_typography', 'caret_plain']));
      final stubs = (forms['unsupported_stub'] as List<dynamic>)
          .map((e) => (e as Map<String, dynamic>)['id'])
          .toList();
      expect(stubs, contains('natural_language'),
          reason: 'NL("선분 AB")은 Phase B까지 미지원 stub으로 명시돼야 한다');
    });

    test('cases 전건 — input을 toRenderLatex에 통과시키면 canonical이 나온다(golden 동결)', () {
      final cases = manifest['cases'] as List<dynamic>;
      expect(cases, isNotEmpty, reason: '매니페스트 cases가 비어 있으면 안 된다');
      for (final c in cases.cast<Map<String, dynamic>>()) {
        expect(
          toRenderLatex(c['input'] as String),
          c['canonical'] as String,
          reason: '${c['id']}: 매니페스트 canonical과 Dart 파이프라인 산출이 어긋난다',
        );
      }
      // 4개 표기 부류가 모두 등재돼 있다(스코프 축소·누락 방지 — 과잉 열거는 하지 않는다).
      final classes = cases
          .map((c) => (c as Map<String, dynamic>)['class'] as String)
          .toSet();
      expect(
        classes,
        <String>{
          'normalization_macro',
          'unicode_typography',
          'structural',
          'contract_canonical',
        },
      );
    });

    test('유니코드 글리프 클래스 전건 — 등재 글리프는 실제로 정규화된다', () {
      final glyphClasses = manifest['unicode_glyph_classes'] as Map<String, dynamic>;
      for (final glyph in (glyphClasses['superscript'] as List<dynamic>).cast<String>()) {
        final input = 'x$glyph';
        expect(normalizeUnicodeMath(input), isNot(input),
            reason: '상첨자 글리프 "$glyph"는 캐럿 그룹으로 정규화돼야 한다');
        expect(normalizeUnicodeMath(input), startsWith('x^{'),
            reason: '상첨자 글리프 "$glyph"의 산출은 캐럿 그룹 형태여야 한다');
      }
      for (final glyph in (glyphClasses['prime'] as List<dynamic>).cast<String>()) {
        expect(normalizeUnicodeMath('f$glyph'), startsWith('f^{\\prime'),
            reason: '프라임 글리프 "$glyph"는 \\prime 캐럿 그룹으로 정규화돼야 한다');
      }
    });

    test('강세 매크로 전건 — 괄호형 인자가 브레이스 그룹으로 복원된다', () {
      final accents = (manifest['accent_macros'] as List<dynamic>).cast<String>();
      expect(accents, isNotEmpty);
      for (final name in accents) {
        expect(plainMathToLatex('\\$name(AB)'), '\\$name{AB}',
            reason: '강세 매크로 \\$name의 괄호형 인자가 복원돼야 한다');
      }
    });
  });

  group('notation_contract 교차검증 — 계약 canonical → 렌더 LaTeX golden (NS-02)', () {
    // 계약 식(caret·명시 `*` ASCII 평문) → toRenderLatex 산출 golden. 표기 변환만 고정한다 —
    // `*`→`\cdot`·`^3`→`^{3}`·`sqrt(...)`→`\sqrt{...}`는 표기 등가(의미 왜곡 없음)다.
    // 어긋남 발견분은 고치지 않고 notation_contract.md "NS-02 정합 검토" 절에 목록화했다
    // (표준함수 이탤릭·무신호 식 평문 폴백·슬래시 나눗셈 — NS-03 입력).
    const golden = <String, String>{
      'x^3': 'x^{3}',
      '3*x^2': '3 \\cdot x^{2}',
      '(x+1)*(x-1)': '(x+1) \\cdot (x-1)',
      'sin(x)^2+cos(x)^2': 'sin(x)^{2}+cos(x)^{2}',
      'sqrt(x^2)': '\\sqrt{x^{2}}',
      'x/4+1': 'x/4+1',
      '2*(x+1)': '2 \\cdot (x+1)',
      '2*x+2': '2 \\cdot x+2',
      '(x+1)^2': '(x+1)^{2}',
      'x^2+2*x+1': 'x^{2}+2 \\cdot x+1',
      '(a+b)^2': '(a+b)^{2}',
      'a^2+b^2': 'a^{2}+b^{2}',
      'x+x+x': 'x+x+x',
      '3*x': '3 \\cdot x',
    };

    // 계약 식 중 수식 신호(`^ _ \ / *`) 없는 식 — 세그먼트가 평문으로 남긴다(과잉 렌더 방지
    // 정책의 의도된 결과·notation_contract.md NS-02 정합 검토 항목 ②로 기록).
    const prosePassthrough = <String>{'x+x+x'};

    late final List<String> exprs;

    setUpAll(() {
      expect(_contractFile.existsSync(), isTrue,
          reason: '표기 계약 fixture가 존재해야 한다');
      final contract = jsonDecode(_contractFile.readAsStringSync(encoding: utf8))
          as Map<String, dynamic>;
      exprs = _contractExprs(contract);
    });

    test('완전성 — 계약의 모든 식에 golden이 있다(fixture 추가 시 golden 갱신 강제)', () {
      for (final expr in exprs) {
        expect(golden.containsKey(expr), isTrue,
            reason: '계약 식 "$expr"의 렌더 golden이 없다 — 이 테스트에 추가하라(NS-02 정합)');
      }
    });

    test('전건 — 계약 식의 canonical LaTeX 산출이 golden과 일치한다', () {
      for (final expr in exprs) {
        expect(toRenderLatex(expr), golden[expr],
            reason: '"$expr": 계약 canonical의 렌더 LaTeX가 golden과 다르다(표기 drift)');
      }
    });

    testWidgets('전건 — 신호 있는 계약 식은 KaTeX로 조판되고 폴백하지 않는다(크래시 0)',
        (tester) async {
      for (final expr in exprs.toSet()) {
        await tester.pumpWidget(_wrap(MathText(expr)));
        if (prosePassthrough.contains(expr)) {
          // 무신호 식은 평문으로 남는다(의도된 세그먼트 정책 — 정합 검토 목록 항목).
          expect(hasRenderableMath(expr), isFalse);
          expect(find.text(expr), findsOneWidget,
              reason: '"$expr"는 평문 폴백(무신호)이어야 한다');
          expect(find.byType(Math), findsNothing);
        } else {
          expect(hasRenderableMath(expr), isTrue);
          expect(find.byType(Math), findsWidgets,
              reason: '"$expr"는 수식으로 라우팅돼야 한다');
          // 성공 렌더 = 원문 폴백 Text가 없다(변별력 — 파싱 실패면 이 단언이 잡는다).
          expect(find.text(expr), findsNothing,
              reason: '"$expr"가 폴백 없이 조판돼야 한다(KaTeX 렌더 가능)');
        }
        expect(tester.takeException(), isNull);
      }
    });
  });
}
