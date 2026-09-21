// 수식 표기 정규화·세그먼트·canonical 파이프라인 (S3-21·S3-23·NS-02) — 화면에 도착한
// 평문/캐럿 표기를 한국 수학교과서처럼 조판할 수 있게 준비하는 *순수* 함수 모음이자,
// 표기·의미 계층(notation_semantics_layer.md §3 L5)의 정규화·렌더 서비스 단일 조립점.
//
// 경계(CLAUDE.md 표현≠의미): 여기서 하는 일은 **표기(notation) 정규화·세그먼트**뿐이다.
// 수학 의미·동치·약분·정오 판정은 절대 하지 않는다 — 그 단일 권위는 백엔드(L3 verify·SymPy)다.
// latex_to_plain.dart(LaTeX→평문·*전송* 방향)의 짝으로, 이 파일은 *표시* 방향을 담당한다:
// 이미 화면 상태에 들어온 평문/캐럿 표기를 다시 렌더러(KaTeX)가 받는 LaTeX로 되돌린다.
//
// ── 지원 입력형 디스패치 (NS-02) ─────────────────────────────────────────────
// canonical 진입점([renderSegments]·[toRenderLatex])이 통합해 받는 입력형은 세 가지다:
//   ① MathLive 직렬화 LaTeX — 입력 팔레트 산출(`\frac`·`\doubleprime`·`\mleft`·`\placeholder` …).
//   ② 유니코드 수학 조판 — 코퍼스·코치 발화의 상첨자/프라임(`x²`·`f″`·`x⁻¹`).
//   ③ 캐럿/평문(caret/plain) — 전송 경로 산출·계약 canonical(`x^2`·`((a)/(b))`·`sqrt(x)`·명시 `*`).
// 자연어 표기("선분 AB")는 **미지원 stub**이다 — Phase B(NL↔Entity 매핑·reasoning_type 확장)에서
// 이 진입점에 합류한다(notation_semantics_layer.md §6). 지원 표기 집합의 열거 가능한 정본은
// `data/notation_support_manifest.json`(단일 진실 원천 — NS-03 커버리지 게이트가 소비하며,
// 이 파일과의 정합은 notation_canonical_test.dart가 동결한다).
//
// canonical 표현 = **LaTeX 문자열**(렌더·notation_contract 친화 — 구조 토큰 채택은 과공학이라
// 반려·notation_semantics_layer.md §8 열린 결정 확정). 의미 동치는 이 canonical을 보지 않는다 —
// 의미는 L3 SymPy가 자체 canonicalize로 판정한다(표현≠의미 경계 유지).
//
// 왜 필요한가(2026-07-22 실기기 실측·S3-21): 문항("삼차함수 f(x) = x^3 …")·코치 발화·풀이
// 수식이 raw 캐럿(x^2)·평문 LaTeX(\lbrack·f^(\prime))로 노출됐다. flutter_math_fork(KaTeX)는
// \lbrack·\rbrack·\prime·\cdot을 네이티브로 렌더하지만, latex_to_plain이 중괄호를 괄호로 바꿔
// (x^{2}→x^(2)·f^{\prime}→f^(\prime)) *캐럿 뒤 그룹*이 깨진다(^가 여는 괄호 하나에만 붙음).
// 그래서 캐럿·아래첨자 뒤의 (...)·숫자런을 LaTeX 그룹 {...}로 되돌리는 게 이 정규화의 핵심이다.

/// 프로즈+수식이 섞인 문자열을 조각으로 나눈 결과 한 조각.
///
/// [isMath]이면 [text]를 수식으로 렌더(정규화 후 KaTeX)하고, 아니면 평문으로 그린다.
/// 세그먼트는 텍스트를 조각들로 자르기만 한다 — 어떤 수학 판정도 하지 않는다(표현≠의미).
class MathSegment {
  const MathSegment(this.text, {required this.isMath});

  /// 조각 본문(원문 부분 문자열·무손실).
  final String text;

  /// 수식으로 렌더할 조각인지.
  final bool isMath;

  @override
  bool operator ==(Object other) =>
      other is MathSegment && other.text == text && other.isMath == isMath;

  @override
  int get hashCode => Object.hash(text, isMath);

  @override
  String toString() => isMath ? '수식($text)' : '평문($text)';
}

// ── 표기 정규화(평문/캐럿 → LaTeX) ─────────────────────────────────────────

/// `((X)/(Y))` → `\frac{X}{Y}` — latex_to_plain의 분수 산출형(`_FRAC_RE` 결과)을 되돌린다.
/// 인자에 중첩 괄호는 다루지 않는다(`[^()]*`) — 백엔드 `_FRAC_RE`와 동일 한계(비-중첩만).
final RegExp _fracRe = RegExp(r'\(\(([^()]*)\)/\(([^()]*)\)\)');

/// `sqrt((X))` → `\sqrt{X}` — latex_to_plain의 근호 산출형(`sqrt(($1))`)을 되돌린다.
final RegExp _sqrtDoubleRe = RegExp(r'sqrt\(\(([^()]*)\)\)');

/// `sqrt(X)` → `\sqrt{X}` — 홑괄호 근호(혹시 모를 변형) 폴백.
final RegExp _sqrtSingleRe = RegExp(r'sqrt\(([^()]*)\)');

/// `^(...)` → `^{...}` — 캐럿 뒤 괄호 그룹을 LaTeX 그룹으로(중첩 괄호 제외·비-중첩).
/// 이게 핵심 수정: `f^(\prime)`·`x^(2)`처럼 latex_to_plain이 중괄호를 괄호로 바꾼 지수를
/// 되돌려 `^`가 그룹 전체에 붙게 한다(안 하면 `^`가 여는 괄호 1개에만 붙어 조판이 깨진다).
final RegExp _caretParenRe = RegExp(r'\^\(([^()]*)\)');

/// `_(...)` → `_{...}` — 아래첨자 뒤 괄호 그룹(캐럿과 대칭·`a_(1)`→`a_{1}`).
final RegExp _subParenRe = RegExp(r'_\(([^()]*)\)');

/// `^12` → `^{12}` — 괄호 없는 캐럿 숫자런을 그룹으로(다중 자리 지수 보존·`x^2`→`x^{2}`).
/// 캐럿 그룹 변환(위)을 먼저 돌린 뒤라 `^{`·`^(`는 이 단계에 걸리지 않는다.
final RegExp _caretDigitsRe = RegExp(r'\^(\d+)');

/// `_12` → `_{12}` — 괄호 없는 아래첨자 숫자런을 그룹으로(캐럿과 대칭).
final RegExp _subDigitsRe = RegExp(r'_(\d+)');

// ── flutter_math_fork(KaTeX) 미지원 매크로 → 지원 등가물 정규화 ────────────────
// 실측(S3-23 프로브·flutter_math_fork 0.7.4): 아래 매크로는 파서가 예외를 던져 raw 폴백된다.
// MathLive가 이 형태를 내보내므로(번들 v0.110.0 직렬화 실측) 입력 팔레트 산출이 깨진다.
// 방어: *표기 등가*(수학 의미 불변)인 지원 매크로로 되돌린다 — 표현≠의미, 검증은 백엔드.

/// `\doubleprime`(2계·핵심 누락) → `{\prime\prime}`. MathLive는 이계도함수(■″ 버튼)를
/// `f^\doubleprime`로 직렬화하는데(번들 실측: `\u2033`→`^\\doubleprime`), flutter_math_fork에
/// `\doubleprime`가 없어 raw로 새는 게 이계도함수 표기가 교과서 아니던 원인이다(Kiki #2).
/// 중괄호로 감싸는 이유: 무괄호 `^\prime\prime`은 캐럿이 첫 `\prime`만 잡아 둘째가 baseline로
/// 떨어진다 — `{\prime\prime}`로 그룹화하면 `f^\doubleprime`→`f^{\prime\prime}`로 붙는다.
/// 경계 가드 `(?![a-zA-Z])`로 더 긴 명령(가상)에 부분매치되지 않게 한다.
final RegExp _doublePrimeRe = RegExp(r'\\(?:doubleprime|dprime|backdoubleprime)(?![a-zA-Z])');

/// `\trprime`(3계·삼중 프라임 ‴) → `{\prime\prime\prime}` — 고차도함수 대칭 처리.
final RegExp _triplePrimeRe = RegExp(r'\\(?:trprime|backtrprime)(?![a-zA-Z])');

/// `\differentialD`/`\differentialE`/`\capitalDifferentialD`/`\exponentialE`(MathLive d·e 버튼)
/// → `\mathrm{d}`/`\mathrm{e}`/`\mathrm{D}` — MathLive 자체 내부 매핑과 동일한 교과서 정립체.
final RegExp _differentialDRe = RegExp(r'\\differentialD(?![a-zA-Z])');
final RegExp _differentialERe = RegExp(r'\\(?:differentialE|exponentialE)(?![a-zA-Z])');
final RegExp _capitalDifferentialDRe = RegExp(r'\\capitalDifferentialD(?![a-zA-Z])');

/// `\mleft(`/`\mright)`(MathLive 자동 크기 괄호) → `\left(`/`\right)` — KaTeX 표준 등가.
final RegExp _mleftRe = RegExp(r'\\mleft(?![a-zA-Z])');
final RegExp _mrightRe = RegExp(r'\\mright(?![a-zA-Z])');

/// `\abs{X}` → `\left|X\right|`, `\norm{X}` → `\left\|X\right\|` — KaTeX엔 없는 매크로.
/// 인자 중첩 중괄호는 다루지 않는다(`[^{}]*`) — 걸리면 fail-closed 원문 폴백(안전).
final RegExp _absRe = RegExp(r'\\abs\s*\{([^{}]*)\}');
final RegExp _normRe = RegExp(r'\\norm\s*\{([^{}]*)\}');

/// `\placeholder{X}` → `X`(빈 필드면 빈 문자열) — MathLive 미완성 필드 자리표시자 제거.
final RegExp _placeholderRe = RegExp(r'\\placeholder\s*\{([^{}]*)\}');

/// 강세(accent) 매크로가 latex_to_plain의 `{}`→`()` 변환으로 인자 그룹이 깨진 것을 되돌린다.
/// 예: 학생이 MathLive로 넣은 `\overline{AB}`는 전송 경로에서 `\overline(AB)`가 되는데, KaTeX는
/// `\overline`가 여는 괄호 한 글자만 인자로 잡아 오버바가 `(`에만 걸린다 — `{}`로 되돌려야
/// `AB` 전체에 걸린다. 벡터·화살표·바 등 1-인자 강세를 모두 대칭 처리한다(비-중첩 괄호만).
final RegExp _accentParenRe = RegExp(
  r'\\(overline|underline|overrightarrow|overleftarrow|vec|bar|hat|widehat|widetilde|tilde|dot|ddot|check|breve|acute|grave)\(([^()]*)\)',
);

/// 평문/캐럿 수식 문자열을 KaTeX가 받는 LaTeX로 정규화한다(순수·표기 매핑만).
///
/// 되돌리는 것: 분수 `((a)/(b))`→`\frac{a}{b}`, 근호 `sqrt((x))`→`\sqrt{x}`, 캐럿/아래첨자
/// 그룹 `^(...)`·`_(...)`→`^{...}`·`_{...}`, 캐럿/아래첨자 숫자런 `x^2`→`x^{2}`, 곱셈 `*`→`\cdot`,
/// 그리고 flutter_math_fork 미지원 매크로(`\doubleprime`·`\differentialD`·`\mleft`·`\abs`·
/// `\placeholder`·괄호형 강세)를 지원 등가물로(S3-23 감사). 이미 유효한 LaTeX(`f^{\prime}`·
/// `\lbrack`·`\frac{..}{..}`·`\overline{AB}`)는 건드리지 않는다. 수학 판정은 없다(표현≠의미).
///
/// 실패 안전: 이 함수는 순수 문자열 치환이라 예외를 던지지 않는다. 여기서 만든 LaTeX가
/// 렌더러에서 파싱 불가하면 호출부(위젯)가 원문으로 폴백한다(fail-closed).
String plainMathToLatex(String input) {
  var s = input;
  // 0) 미지원 매크로 정규화(다른 치환보다 먼저 — 산출 `{...}`가 이후 단계에 안 걸리게).
  s = s.replaceAll(_mleftRe, r'\left');
  s = s.replaceAll(_mrightRe, r'\right');
  s = s.replaceAll(_doublePrimeRe, r'{\prime\prime}');
  s = s.replaceAll(_triplePrimeRe, r'{\prime\prime\prime}');
  s = s.replaceAll(_differentialDRe, r'\mathrm{d}');
  s = s.replaceAll(_differentialERe, r'\mathrm{e}');
  s = s.replaceAll(_capitalDifferentialDRe, r'\mathrm{D}');
  s = s.replaceAllMapped(_absRe, (m) => '\\left|${m[1]}\\right|');
  s = s.replaceAllMapped(_normRe, (m) => '\\left\\|${m[1]}\\right\\|');
  s = s.replaceAllMapped(_placeholderRe, (m) => m[1] ?? '');
  s = s.replaceAllMapped(_accentParenRe, (m) => '\\${m[1]}{${m[2]}}');
  // 1) 분수·근호 환원(괄호 그룹을 소비하므로 캐럿 변환보다 먼저).
  s = s.replaceAllMapped(_fracRe, (m) => '\\frac{${m[1]}}{${m[2]}}');
  s = s.replaceAllMapped(_sqrtDoubleRe, (m) => '\\sqrt{${m[1]}}');
  s = s.replaceAllMapped(_sqrtSingleRe, (m) => '\\sqrt{${m[1]}}');
  // 2) 캐럿·아래첨자 괄호 그룹 → 중괄호 그룹(핵심 수정).
  s = s.replaceAllMapped(_caretParenRe, (m) => '^{${m[1]}}');
  s = s.replaceAllMapped(_subParenRe, (m) => '_{${m[1]}}');
  // 3) 괄호 없는 숫자런 지수/아래첨자 → 그룹(다중 자리 보존).
  s = s.replaceAllMapped(_caretDigitsRe, (m) => '^{${m[1]}}');
  s = s.replaceAllMapped(_subDigitsRe, (m) => '_{${m[1]}}');
  // 4) 곱셈 별표 → \cdot(양옆 공백으로 토큰 접합 방지·`3*x`→`3 \cdot x`).
  s = s.replaceAll('*', r' \cdot ');
  return s;
}

// ── 유니코드 수학 조판 → 캐럿 LaTeX 사전 정규화 ──────────────────────────────
// 코퍼스·코치 발화는 유니코드 상첨자(x³·x²)·프라임(f′·f″·f‴)을 그대로 쓴다(오개념 카탈로그
// 실측: `f′(0)`·`x³`). 이 문자들은 비-ASCII라 segmentMathText가 프로즈로 분류해 KaTeX에 닿지
// 못하고 *날 글리프*로 보인다 — 특히 이계도함수 `f″`(‷ U+2033)는 교과서 위첨자 조판이 아니라
// 겹따옴표 모양으로 새는 게 Kiki #2의 코퍼스 측 원인이다. 세그먼트 *전에* 이들을 캐럿 LaTeX로
// 되돌려(`x³`→`x^{3}`·`f″`→`f^{\prime\prime}`) `^` 신호로 수식 라우팅을 성립시킨다(표현≠의미).

/// 유니코드 상첨자 글리프 → 기저 문자(런으로 모아 `^{...}`로 감싼다).
const Map<String, String> _superscriptMap = <String, String>{
  '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
  '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
  '⁺': '+', '⁻': '-', '⁼': '=', '⁽': '(', '⁾': ')',
  'ⁿ': 'n', 'ⁱ': 'i',
};

/// 유니코드 프라임 글리프 → `\prime` 개수(런으로 모아 `^{\prime...}`로 감싼다).
const Map<String, int> _primeMap = <String, int>{
  '′': 1, // ′ 프라임(1계)
  '″': 2, // ″ 더블프라임(2계·핵심)
  '‴': 3, // ‴ 트리플프라임(3계)
};

/// 상첨자 글리프 1개 이상의 런.
final RegExp _superscriptRunRe =
    RegExp('[⁰ⁱ¹²³⁴-ⁿ]+');

/// 프라임 글리프 1개 이상의 런.
final RegExp _primeRunRe = RegExp('[′″‴]+');

/// 유니코드 수학 조판(상첨자·프라임)을 캐럿 LaTeX로 되돌린다(순수·세그먼트 전에 적용).
///
/// 예: `x³`→`x^{3}`, `x⁻¹`→`x^{-1}`, `f′`→`f^{\prime}`, `f″`→`f^{\prime\prime}`.
/// 프라임/상첨자만 다룬다 — 가운뎃점(·)·그리스 등 프로즈에서도 쓰이는 문자는 라우팅을
/// 흔들 수 있어 손대지 않는다(과잉 정규화 금지·한글 프로즈 무회귀). 실패 안전: 순수 치환.
String normalizeUnicodeMath(String input) {
  var s = input.replaceAllMapped(_superscriptRunRe, (m) {
    final buf = StringBuffer();
    for (final ch in m[0]!.split('')) {
      buf.write(_superscriptMap[ch] ?? '');
    }
    return '^{${buf.toString()}}';
  });
  s = s.replaceAllMapped(_primeRunRe, (m) {
    var count = 0;
    for (final ch in m[0]!.split('')) {
      count += _primeMap[ch] ?? 0;
    }
    return '^{${r'\prime' * count}}';
  });
  return s;
}

// ── 프로즈+수식 세그먼트 ────────────────────────────────────────────────────

/// 수식 "신호" 문자 — 이 중 하나라도 있어야 진짜 조판 대상으로 본다(위첨자/아래첨자/명령/분수/곱셈).
final RegExp _signalCharsRe = RegExp(r'[\\^_/*]');

/// 영숫자(피연산자) — 신호만 있고 피연산자가 없으면(`*`·`**`) 수식으로 보지 않는다.
final RegExp _alnumRe = RegExp(r'[A-Za-z0-9]');

/// ASCII 덩어리가 렌더할 만한 *수식*인지 판정한다(과잉 렌더 방지·순수).
///
/// 규칙: 신호 문자(`^ _ \ / *`) 또는 `sqrt`가 있고 **동시에** 영숫자가 있어야 수식이다.
/// 그래서 단순 값(`0`·`2`·`x=2`·`k<-1`)·구두점(`*`·`**`)은 평문으로 남는다 — 조판 이득이
/// 큰 구조(지수·프라임·분수·근호·곱셈)만 렌더해 위험·오버플로·불필요한 렌더를 줄인다.
bool _isMathChunk(String chunk) =>
    (_signalCharsRe.hasMatch(chunk) || chunk.contains('sqrt')) &&
    _alnumRe.hasMatch(chunk);

/// 문자 하나가 공백류인지(스페이스·탭·개행).
bool _isSpace(int c) => c == 0x20 || c == 0x09 || c == 0x0A || c == 0x0D;

/// 프로즈(한국어 등)+수식이 섞인 [text]를 [MathSegment] 리스트로 나눈다(순수·무손실).
///
/// 접근법(최소 실용안·"수식 토큰 런 감지"): 문자를 ①비-ASCII=프로즈(한글·CJK) ②ASCII=수식후보
/// ③공백으로 분류하고, 공백은 양옆이 모두 ASCII일 때만 수식후보에 붙인다(그래야 프로즈와 수식
/// 사이 공백은 프로즈에, 수식 내부 공백은 수식에 남는다). 이어붙인 ASCII 런 각각에 [_isMathChunk]
/// 신호 판정을 적용해 수식이면 독립 조각으로, 아니면 프로즈로 흡수한다. 인접 프로즈는 하나로
/// 병합한다(불필요한 조각 방지). 조각을 이으면 항상 원문과 정확히 같다(글자 무손실).
///
/// 왜 문자 단위인가: "144x에서"·"x의"처럼 공백 없이 한글이 수식에 붙는 한국어 문항을 정확히
/// 자르려면 한글 경계에서 끊어야 한다(공백 분해로는 부족). 수학 의미 추론은 없다(표현≠의미).
List<MathSegment> segmentMathText(String text) {
  if (text.isEmpty) {
    return const <MathSegment>[];
  }
  final n = text.length;
  // 1) 문자별 1차 분류: 0=프로즈(비-ASCII), 1=ASCII, 2=공백.
  final cls = List<int>.filled(n, 0);
  for (var i = 0; i < n; i++) {
    final c = text.codeUnitAt(i);
    if (_isSpace(c)) {
      cls[i] = 2;
    } else if (c <= 0x7F) {
      cls[i] = 1;
    } else {
      cls[i] = 0; // 한글·CJK·이모지(서러게이트) 등 → 프로즈.
    }
  }
  // 2) 공백 런 해소: 양옆 비-공백이 모두 ASCII면 ASCII(1)에, 아니면 프로즈(0)에 귀속.
  var i = 0;
  while (i < n) {
    if (cls[i] != 2) {
      i++;
      continue;
    }
    var j = i;
    while (j < n && cls[j] == 2) {
      j++;
    }
    final leftAscii = i > 0 && cls[i - 1] == 1;
    final rightAscii = j < n && cls[j] == 1;
    final resolved = (leftAscii && rightAscii) ? 1 : 0;
    for (var k = i; k < j; k++) {
      cls[k] = resolved;
    }
    i = j;
  }
  // 3) 같은 부류(ASCII vs 프로즈)로 묶고, ASCII 런은 신호 판정으로 수식/프로즈 결정.
  final result = <MathSegment>[];
  final proseBuf = StringBuffer();
  void flushProse() {
    if (proseBuf.isNotEmpty) {
      result.add(MathSegment(proseBuf.toString(), isMath: false));
      proseBuf.clear();
    }
  }

  i = 0;
  while (i < n) {
    final start = i;
    final isAscii = cls[i] == 1;
    while (i < n && (cls[i] == 1) == isAscii) {
      i++;
    }
    final chunk = text.substring(start, i);
    if (isAscii && _isMathChunk(chunk)) {
      flushProse();
      result.add(MathSegment(chunk, isMath: true));
    } else {
      proseBuf.write(chunk); // 프로즈 또는 신호 없는 ASCII → 프로즈로 흡수(병합).
    }
  }
  flushProse();
  return result;
}

// ── canonical 파이프라인 단일 진입점 (NS-02) ─────────────────────────────────
// 위 순수 함수 4종의 조합 순서(normalizeUnicodeMath → segmentMathText → 조각별
// plainMathToLatex)가 위젯마다 재조립되면 드리프트한다(NS-01까지의 실측 — math_text.dart의
// 4개 좌석이 각자 조립). 그래서 조합을 *이 한 곳*에 캡슐화한다: 위젯·프리뷰·게이트는 아래
// 진입점만 소비하고, 개별 함수는 감사 테스트(S3-23)·전송 짝 검증을 위해 공개로 남긴다.
// fail-closed 계약은 불변이다 — 여기서 만든 canonical LaTeX가 렌더러에서 파싱 불가하면
// 호출부(onErrorFallback)가 *세그먼트 원문*으로 폴백한다(크래시 0·의도된 graceful 폴백).

/// 원문 [raw]를 canonical 파이프라인 1단(유니코드 정규화 → 세그먼트)에 태운다 — 단일 조립점.
///
/// 지원 입력형(모듈 doc 참조: MathLive LaTeX·유니코드 조판·캐럿/평문)을 통합해 받아
/// 프로즈/수식 조각으로 나눈다(무손실·수학 판정 없음). 수식 조각의 canonical LaTeX 산출은
/// [renderLatexFor]가 담당한다(2단). 위젯이 [normalizeUnicodeMath]·[segmentMathText]를
/// 직접 조합하지 않게 하는 것이 목적이다(조합 순서 단일 진실·NS-02).
List<MathSegment> renderSegments(String raw) =>
    segmentMathText(normalizeUnicodeMath(raw));

/// [segment]의 *렌더용 canonical LaTeX*를 산출하는 단일 지점(파이프라인 2단).
///
/// 수식 조각은 [plainMathToLatex]로 canonical LaTeX를 만들고, 프로즈 조각은 원문 그대로
/// 돌려준다(프로즈에 표기 정규화를 적용하지 않는다 — 무손실·한글 무회귀). 위젯은 이 함수만
/// 소비하고 [plainMathToLatex]를 직접 조합하지 않는다(NS-02). [MathSegment]의 공개 계약
/// (생성자·`==`·hashCode)은 불변 — 이 함수는 조각을 감싸는 얇은 helper일 뿐이다.
///
/// fail-closed: 산출 LaTeX가 파싱 불가하면 호출부가 [MathSegment.text](원문)로 폴백한다.
String renderLatexFor(MathSegment segment) =>
    segment.isMath ? plainMathToLatex(segment.text) : segment.text;

/// 원문 [raw] 전체를 한 번에 canonical 표기 문자열로 — 단일식 편의 진입점.
///
/// [renderSegments]로 나눈 뒤 수식 조각만 [renderLatexFor]로 canonical LaTeX로 바꾸고
/// 프로즈는 그대로 이어 붙인다. 순수 수식 입력(`x^2`·`f″`)이면 산출이 canonical LaTeX 그
/// 자체(`x^{2}`·`f^{\prime\prime}`)다. 계약 교차검증(notation_contract)·매니페스트 golden이
/// 이 함수를 기준으로 canonical을 고정한다. 수학 의미·동치 판정은 없다(표현≠의미).
String toRenderLatex(String raw) =>
    renderSegments(raw).map(renderLatexFor).join();

/// [text]에 교과서 조판으로 렌더할 *수식 조각*이 하나라도 있는지 판정한다(순수).
///
/// canonical 진입점 [renderSegments]를 그대로 소비하므로 [MathText] 위젯의 내부 판정과
/// *같은 기준*임이 구조적으로 보장된다(NS-02 — 별도 재조립 없음). 렌더 프리뷰를 *수식일
/// 때만* 띄우는 호출부(풀이 단계 편집기·NS-01)가 재사용해, 빈 필드·순수 프로즈·신호 없는
/// 단순 값(`x=2`·`0`·`ㄱ`)엔 프리뷰를 만들지 않게 한다(빈 공간·중복 표시 억제).
/// 수학 의미·정오 판정은 없다(표현≠의미) — "조판할 수식 표기가 있는가"만 본다.
bool hasRenderableMath(String text) => renderSegments(text).any((s) => s.isMath);

// ── Entity 앵커 seam (NS-02 스켈레톤 — Phase B 예약) ─────────────────────────

/// L1 Symbol Entity Registry 앵커의 자리표시 타입(스켈레톤).
///
/// Phase B에서 정규화된 표기 토큰이 L1 Symbol Entity(학년·교육과정 코드 태그를 단 사실
/// 데이터·단일 진실 원천)로 매핑될 자리다. Entity가 정본이고 {LaTeX·유니코드·NL·Display}는
/// 투영이라는 관계(notation_semantics_layer.md §3 L1)만 계약으로 예약해 둔다. 이 타입은
/// 표기 식별자만 담는다 — 수학 의미·판정·렌더 정보는 담지 않는다(표현≠의미·Concept Purity).
class NotationEntity {
  const NotationEntity({required this.id});

  /// Entity 식별자(예: `math.symbol.prime`) — 파일명·언어·교육과정과 독립(플레이북 게이트).
  final String id;

  @override
  bool operator ==(Object other) => other is NotationEntity && other.id == id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => 'NotationEntity($id)';
}

/// 정규화된 표기 토큰 → L1 Symbol Entity 앵커(스켈레톤 — 지금은 항상 null).
///
/// Phase B에서 L1 Symbol Entity Registry로 매핑될 자리·지금은 Registry 미구현(노드 폭발
/// 방어 — notation_semantics_layer.md §5: 커버리지 *측정*이 적재를 구동해야 하며, 한 번에
/// 전학년 심볼 적재는 금지). null = "앵커 없음"이며 렌더 경로는 이 값에 의존하지 않는다
/// (seam·계약만 예약 — 기능 무영향, fail-closed 불변).
NotationEntity? anchorFor(String token) => null;
