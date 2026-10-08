"""P3-03 미분 문항 은행 — '선수 계산 우회로' 판정기(순수 함수·결정론·LLM 0).

독립 감사 3회차(`docs/data/p3_calculus1_diff_audit/round3/defects.json`·κ 0.854)의 결함
대부분은 "미분 없이 선수 계산만으로 풀린다"(bad_tag) 한 부류였다. 생성기가 기계 검증을 위해
정수 중근·깔끔한 인수를 가진 다항식을 고르는데, 바로 그 성질이 인수분해·판별식·대입 우회로를
연다. 1·2회차 교정은 지적된 *발문 서명*을 지우는 방식이라 같은 원인이 새 틀로 재발했다
(74 → 90 → 122).

이 모듈은 서명이 아니라 **수학 재료**를 본다 — 발문에 보이는 다항식·검산 조건(`verify`)·
해설에서 "이 문항이 그 개념의 인지 행동(미분) 없이 풀리는가"를 개념별 규칙으로 판정한다.
생성기 빌드(`p3_diff_skeleton_base.P3DiffSlotGenerator._validate_slot`)가 문항마다 부르고
위반이 하나라도 있으면 빌드를 멈춘다(fail-loud). 은행 전수 0건은 테스트
(`test_p3_diff_shortcut_guard`)가 단언한다.

입력은 생성기의 `DiffItem`이 아니라 **중립 표본**(`ShortcutProbe`)이다 — 같은 판정기를 은행
JSONL 레코드(`probe_from_record`)에도 그대로 적용해 감사 회차의 교정 전 은행에서 재현율을 잴
수 있게 한다.

독립 감사 4회차(`round4/defects.json`·합집합 88·둘 다 27)는 이 판정기를 통과한 은행에서 다시
결함을 찾았다 — ① 학생 대면 텍스트의 코드식 부등호 '<='·'>='와 근호 'sqrt(' ② 극값 위치를 둘
이상 주는 02-08 문항(대입·대소 비교) ③ 복이차 사차식(완전제곱) ④ 포물선 꼭짓점의 수평 접선·직선의
접선(02-05) ⑤ 위치가 일차 이하인 운동의 속도·가속도(02-10) ⑥ x^n의 도함수를 0에서 보는 문항(오답
경로도 전부 0) ⑦ 방정식·부등식 맥락이 없는 02-09 최솟값 ⑧ 발문에 없는 '두 점'·'접점'을 쓰는 해설.
4회차 규칙(아래 [4회차])이 그 부류를 생성 시점에 막는다.

은행 감사 5회차(2026-10-08 · `bank_audit/disposition.json` · 결함 68건 · 원인 14종)는 4회차 규칙을
통과한 은행에서 다시 결함을 찾았다 — ① 이차함수의 평균값 정리·롤·속도 0(c가 늘 구간의 중점·꼭짓점)
② 발문이 답을 알려 줌(근 나열·구간 안 자연수 하나·접점 좌표) ③ 오답 경로가 정답과 일치(함숫값 대입·
일차항 계수 읽기·상수의 미분·차수/임계점 세기) ④ 해설 결함(전제 역전·정의 없는 기호·버린 근 미기술·
v(t) 누락·멈춤의 뜻·y축 x = 0·비문·롤 용어) ⑤ 오개념 귀속(절차 값이 아닌 선지·설명 손상 M0677)
⑥ 발문–검산 불일치(284122b4). 5회차 규칙(아래 [5회차] · `ROUND5_RULE_IDS`)이 그 부류를 막는다.
그중 *매개변수 선택의 우연 일치*(`COINCIDENCE_RULE_IDS`)는 생성기 라운드로빈이 그 파라미터를
건너뛰는 거부 조건으로 쓰고(`parameter_coincidences`), 나머지는 틀 설계 결함이라 빌드를 멈춘다.

은행 감사 6회차(2026-10-08 · `bank_audit_r2/disposition.json` · 결함 23건 · 원인 7종)는 5회차 규칙을
통과한 은행에서 다시 결함을 찾았다 — ① 오개념 M0615의 설명 자기모순('두 개로 단정' 대 '(차수만큼
근)') ② 속도 해설의 v(t)·a(t) 정의 없는 등장 ③ 비례 짐작·미분 오류 경로가 정답과 일치 (f'(a) =
m·f'(1) · 대칭 근) ④ 상수항을 옮기면 인수분해·부호만으로 실근 개수가 정해짐 ⑤ 발문에 c 구간이 없어
해가 둘 ⑥ 개수 문항의 검산이 발문의 구간을 반영하지 않음 ⑦ '곡선 … 이 극대가 되는' 용어. 6회차
규칙(아래 [6회차] · `ROUND6_RULE_IDS`)이 그 부류를 막는다. 자격 측정을 통과한 감사 프로토콜의 기계
투표는 4회차 규칙 집합으로 고정돼 있으므로, 측정 뒤에 더한 회차 규칙 전부를
`POST_QUALIFICATION_RULE_IDS`로 묶는다(`p3_audit_qualification.EXCLUDED_GUARD_RULES`가 그 집합을
투표에서 뺀다).

은행 감사 7회차(2026-10-08 · `bank_audit_r3/disposition.json` · 결함 11건 · 원인 4종 · 전부 확신
'불확실')는 6회차 규칙을 통과한 은행에서 다시 결함을 찾았다 — ① 이차곡선의 접선 기울기·평행·수직으로
접점을 묻는 틀(판별식 중근 · 5건) ② 오답 경로가 정답과 같음(x = 1 평가 · cx^m의 c만 묻기 · 성분
함수의 임계점에서 평가 · 3건) ③ 해설 문장(v(t)를 주어 자리에서 소개하지 않음·발문에 없는 x(5) · 증감
문항을 극값으로 맺음 · 2건) ④ 위치 (t - 1)^3 꼴 — 가속도 0인 시각의 속도도 0(1건). 7회차 규칙(아래
[7회차] · `ROUND7_RULE_IDS`)이 그 부류를 막는다.

규칙(위반 id — 사유는 `ShortcutViolation.reason`)
--------------------------------------------
[공통 · 표기]
  W-notation         학생 대면 문면(발문·선지·해설·정답)에 SymPy 표기('*'·'Derivative(' 등)가
                     있다.
  W-ascii-inequality [4회차] 학생 대면 문면에 코드식 부등호 '<='·'>='가 있다 — 승인 은행 4종은
                     '≤'·'≥'만 쓴다(Flutter 렌더는 '<='를 그대로 두 글자로 낸다).
  W-sqrt-call        [4회차] 학생 대면 문면에 함수 호출꼴 근호 'sqrt('가 있다 — 승인 은행 관례는
                     '8√3'이다(3회차 교정이 고른 '8sqrt(3)'은 감사자 둘이 모두 코드 표기로 봤다).
  W-point-x          '곡선 … 위의 x = 1에서의'처럼 점을 x값으로만 부른다('x좌표가 1인 점').
  W-trivial-ineq     '(-1 < 0 < 2)'처럼 상수만으로 된 자명한 부등식이 괄호로 붙어 있다
                     (템플릿 흔적).
  W-zero-hour        '출발 후 0시간부터'(템플릿 값 0이 그대로 들어간 시각 표현).
  W-extremum-josa    'f(x) …의 극값을 갖는'(주어 조사 오류)·'점이 x = '(점을 x값과 등치).
[공통 · 해설(핵심 중간 단계)]
  E-derivative       발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·
                     v(t) = …)이 없다.
  E-parameter        발문 함수식의 미지 상수(x^n의 n·ax^2의 a)가 해설에 결론('n은 3')으로만
                     나오고 세운 식(nx^(n - 1)·6a + 18 = 0) 안에 한 번도 들지 않는다.
  E-kinematics       발문이 (순간)속도·운동 방향을 다루는데 해설에 v(t) 식이 없거나,
                     가속도를 다루는데 a(t) 식이 없다.
  E-sign             운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다.
  E-symbol-intro     해설이 발문에 없는 기호(f'(c)의 c)를 소개 없이 쓴다.
  E-tautology        'q = 3에서 q = 3이다' 같은 순환 서술.
  E-term             '기울기 0인 일차함수'(상수함수를 일차함수라 부름).
  E-object-intro     [4회차] 해설이 발문에 없는 도형 대상('두 점을 잇는 직선'·'접점'·'접선')을
                     소개 없이 쓴다(발문에 점·곡선·직선·그래프가 하나도 없다).
[개념 · 우회로(bad_tag)]
  T05-quadratic-tangency  (02-05) 접할 조건·곡선 밖의 점에서 그은 접선을 묻는데 곡선이
                          이차 이하라 판별식만으로 풀린다(곡선 차수 ≥ 3이어야 한다).
  T-value-determines      (02-05·02-08) 발문의 함숫값 조건(극값의 값·두 곡선이 만나는 점)
                          만으로 구하는 상수가 정해진다 — 미분계수 조건이 풀이에 쓰이지 않는다.
  T06-given-rate          (02-06) 발문이 평균변화율의 값을 직접 준다(평균값 정리의 행위가
                          빠진다).
  T08-derivative-inequality
                          (02-08) 발문이 f'(x) < 0 같은 도함수 부등식을 직접 준다(증감 판정이
                          빠진다).
  T08-pinned-kind         (02-08) 극값의 위치(x = a)와 종류를 함께 주고 그 값을 묻는다(대입만).
  T09-rational-root       (02-09) 발문에 보이는 방정식·부등식의 다항식이 유리수 근을 갖는다
                          (인수정리).
  T09-biquadratic         (02-09) 발문의 사차식이 어떤 x = h에 대해 대칭이라((x - h)^2 = u)
                          이차방정식으로 환원된다(복이차식 — 근의 공식·판별식).
  T09-repeated-root       (02-09) 등호가 성립하는 점(근)을 묻는데 그 점이 중근이다
                          (완전제곱·인수 우회로).
  T09-low-degree          (02-09) 발문에 보이는 방정식이 이차 이하다(판별식·근의 공식).
  T09-pinned-minimizer    (02-09) 최솟값을 묻는데 발문이 최솟값을 갖는 x를 알려 주거나 그 x가
                          0이다(상수항이 곧 답 — 대입만).
  T10-average-only        (02-10) 평균속도만 묻는다(위치 대입·차분몫 — 미분 불요).
  T-zero-monomial         [4회차] (전 개념) 발문의 함수가 단항식 c·x^n(n ≥ 2)인데 x = 0(원점)에서의
                          미분계수나 방정식 f'(x) = 0의 근을 묻는다 — 정답도, 원함수 대입도,
                          거듭제곱 미분법의 어떤 오답 경로도 0이라 변별이 없다.
  T05-vertex-tangent      [4회차] (02-05) 곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선·기울기 0을
                          묻는다 — 꼭짓점 공식 -b/(2a)·완전제곱으로 풀린다.
  T05-line-tangent        [4회차] (02-05) 직선 위의 점에서의 접선을 묻는다 — 직선의 기울기를 읽기만
                          하면 된다.
  T08-given-critical-points
                          [4회차] (02-08) 발문이 극값을 갖는 x 위치를 둘 이상 준다 — 대입하고 대소를
                          비교하면 극댓값·극솟값이 정해진다(삼차·사차에서 '큰 값이 극댓값'이 늘
                          맞는다). 부호가 바뀌지 않는 임계점이 섞여 *극값인지* 가려야 하는 경우는
                          세지 않는다(극값 위치는 둘 미만이 된다).
  T08-biquadratic         [4회차] (02-08) 발문의 사차식이 x = h에 대해 대칭(복이차)이라
                          (x - h)^2 = u로 두면 완전제곱만으로 극값의 위치·값이 나온다.
  T09-no-application      [4회차] (02-09) 발문에 방정식·부등식·교점·위치 관계 맥락이 없다 — 최댓값·
                          최솟값 기술(02-07/02-08 영역)만으로 풀리는 문항이다.
  T10-linear-position     [4회차] (02-10) 위치가 일차 이하(x = 7·x = 2t + 1)인데 속도·가속도를
                          묻는다 — 정지·등속이라는 상식(일차함수의 기울기)으로 풀린다.
[5회차 · 우회로·우연 일치(*는 매개변수 거부 조건 — `COINCIDENCE_RULE_IDS`)]
  T-quadratic-mean-value  (02-06·02-10) 이차 이하 함수의 평균값 정리·롤·평균속도 = 순간속도 — c가
                          늘 구간의 중점이라 '가운데 값'으로 풀린다.
  T10-quadratic-rest      (02-10) 위치가 이차 이하인데 속도 0 시각을 묻는다(포물선 꼭짓점).
  T-midpoint-answer*      (02-06·02-10) 정답이 구간의 중점(끝점 미지수형이면 2c - 고정 끝점).
  T-integer-pinned-by-interval*
                          자연수 답인데 발문 구간 안의 자연수가 정답 하나뿐.
  T06-roots-given         (02-06) 발문이 f'(x) = (평균변화율)의 근을 모두 적는다.
  T-function-value-path*  미분계수 대신 함숫값(가속도면 위치·속도)을 넣어도 같은 답.
  T-coefficient-reading*  발문 다항식의 x = 0 미분계수 — 일차항 계수를 읽으면 끝난다('상수항' 과제
                          제외).
  T-constant-derivative*  발문의 두 함수 차가 상수라 미분하는 식이 상수(답·오답 전부 0).
  T09-degree-count*       (02-09) 실근 개수 = 방정식의 차수.
  T09-critical-count*     (02-09) 실근 개수 = f'(x) = 0의 서로 다른 실근 개수.
  T09-given-extremum-values
                          (02-09) 개수 문항의 방정식이 발문에 없고 극값을 발문이 준다.
  T05-quadratic-tangent-constant
                          (02-05) 곡선이 이차 이하인데 접선의 y절편·곡선의 상수·원점에서 그은 접선을
                          판별식형으로 검산한다(중근만으로 풀린다).
  T05-given-coordinate*   (02-05) 정답이 발문에 적힌 점의 y좌표.
  M-link-procedure        오개념 귀속 선지가 그 오개념 절차(M0615 차수 · 임계점=극값 · M0674 f'(c) =
                          0)의 값이 아니거나, 묻는 대상(극대·극소)이 그 절차의 산출과 다르다.
  M-link-undescribed      설명에 절차가 적히지 않은 오개념(M0677 — 원문 손상·QUAL-14 소관)에 귀속.
  V05-touch-verify-mismatch
                          (02-05) 접점이 발문에서 고정된 문항(두 곡선이 x = a에서 접함 · 위의 점/
                          x좌표가 a인 점에서의 접선의 y절편)의 검산 조건 해집합이 발문 문제의
                          해집합과 다르다(보호 조건은 읽지 않는다 — 발문에 없는 보호로 해를 고르는
                          것이 결함).
[5회차 · 해설]
  E-premise-reversal      발문은 'f'(x) = 0의 한 근이 x = p'인데 해설이 'x = p에서 극값을 가지므로'.
  E-undefined-letter      발문에 없는 기호(k·v 등)를 소개 없이 식에 쓴다(운동 문항의 v·a는 '속도'·
                          '가속도'를 말하면 관례 기호).
  E-excluded-root         보호 조건이 버리는 근을 해설이 보이지 않는다(a = 0 배제·± 단계 누락).
  E-velocity-before-acceleration
                          가속도를 묻는데 해설에 v(t) 식이 없다.
  E-rest-meaning          멈추는 시각을 묻는데 해설이 'v(t)는 위치의 도함수'·'멈춤 ⇔ v(t) = 0'을
                          말하지 않는다.
  E-y-axis-zero           y축과 만나는 점을 다루는데 해설에 'x좌표는 0' 단계가 없다.
  E-run-on                한 문장에 '~인데, ~인데,'가 겹친다(비문).
  E-term-rolle            수 하나를 '롤의 정리의 결론'이라 부른다.
[6회차 · 은행 감사 2회차(*는 매개변수 거부 조건 — `COINCIDENCE_RULE_IDS`)]
  M-link-contradictory    설명이 서로 다른 두 절차를 함께 적은 오개념(M0615 '두 개로 단정'
                          대 '(차수만큼 근)')에 귀속 — 연결 선지가 주 절차의 값인지 정해지지
                          않는다.
  M-link-extremum-point   '극값·극점 혼동'(extremum-value-vs-point-confused) 귀속 선지가 그
                          절차(극값 자리에 극대·극소가 되는 점의 x좌표를 넣고 표준 비교 규칙으로
                          센다)로 나오는 값이 아니거나 판독에 따라 갈린다 · 또는 해설이 그
                          절차를 보이지 않는다.
  E-motion-symbol-intro   해설이 v(t)·a(t)를 '속도는 위치를 시각 t로 미분한 값'·'가속도는
                          속도를 시각 t로 미분한 값' 정의 없이 처음 쓴다.
  T-ratio-shortcut*       f'(a) = m·f'(b) — 정답이 비례 짐작 m·b와 같거나, 계수 누락·지수 유지
                          도함수로 풀어도 같은 a.
  T-derivative-roots-coincidence*
                          발문이 f'(x) = 0의 두 근을 줄 때 계수 누락·미분하지 않은 경로로 세운
                          연립의 답이 정답과 같다(대칭 근 ±r이면 늘 0) · 또는 정답이 발문의 근
                          하나다.
  T09-factored-level*     (02-09) 개수 문항의 방정식(좌변 − 우변)이나 상수항을 뺀 식이 중근
                          인수를 갖는다(극값이 0·f(0)과 같거나 임계점이 0) — 인수분해·부호만으로
                          센다.
  U-extra-solution        (02-06·02-10) 정답 말고도 발문 조건을 만족하는 해가 있는데 선지·답
                          형식이 배제하지 않거나, 해설이 발문에 없는 조건으로 그 해를 버린다.
  V-count-interval        개수 문항의 발문이 구간을 주는데 검산 조건의 구간이 그것과
                          다르다(없음 포함).
  W-curve-subject         '곡선 y = …이(가) (x = a에서) 극대·극소·극값·증가·감소' — 그 성질의
                          주어는 함수다.
[7회차 · 은행 감사 3회차(*는 매개변수 거부 조건 — `COINCIDENCE_RULE_IDS`)]
  T05-quadratic-slope     (02-05) 발문의 곡선이 이차 이하인데 접선의 기울기·접점을 미분 평가로
                          정한다 — 기울기 m인 직선과 연립한 이차방정식의 중근(판별식)이 접점이다. 절
                          둘: 접점이 미지수(기울기가 주어진 값·평행·수직) · 기울기를 구한다.
  T-power-path-coincidence*
                          거듭제곱 미분이 검사 대상인 문항(02-03 · 'power-rule-step-omitted' 선지 ·
                          미분하는 식이 상수항 빼고 거듭제곱 하나)에서 두 대표 오답 경로(계수 누락
                          x^(n - 1) · 지수 유지 n·x^n) 중 하나라도 정답과 같은 값을 낸다 — 평가 절
                          (f'(1) 등)·꼴 읽기 절('cx^m 꼴로 나타낼 때 c')·주어진 도함수 꼴 절 ('f'(x)
                          = 8x^7일 때 n').
  T-component-critical-point*
                          합·차·실수배(발문이 보인 함수들의 일차결합)의 미분계수인데 평가점이 한
                          성분 함수의 임계점이다 — 그 성분의 처리를 틀려도 같은 값.
  T10-confusable-quantity*
                          (02-10) 묻는 양과 혼동하기 쉬운 양(속도↔가속도·위치↔속도)이 같은 시각에
                          같은 값이다(가속도 0인 시각의 속도도 0 등).
  E-motion-symbol-subject 해설이 v(t)·a(t)를 '속도 v(t)는 …'처럼 기호를 주어 자리에 두어 소개하지
                          않는다.
  E-function-notation     해설이 발문에 없는 함수 표기('x(5)')를 소개 없이 쓴다.
  E-conclusion-target     (02-08) 해설의 결론 문장이 발문의 대상과 어긋난다 — 증가·감소가 바뀌는
                          점을 묻는데 극값으로 맺음 · 결론 문장에 정답이 없음.

정직 범위(이 판정기가 보증하지 **않는** 것)
-------------------------------------------
· 발문 문자열의 *템플릿 표현*을 정규식으로 읽는 휴리스틱이 섞여 있다. 같은 수학을 다른 어휘로
  쓴 문항(예: '접할 때' 대신 '한 점에서만 만날 때')은 T05 규칙이 읽지 못할 수 있다.
· '미분 없이 풀린다'의 판정은 이 규칙들이 아는 우회로(인수정리·판별식·대입·이차부등식·
  평균속도 차분몫)에 한정된다. 학생이 쓸 수 있는 모든 우회로(산술·기하 평균 등)를 열거하지
  않는다.
· 해설 규칙은 *형식*(도함수 식·세운 식의 존재)을 본다 — 그 식이 옳은지는 Tier1·
  corpus_reverify의 몫이다.

7계층: L3 지역. SymPy 문자열 파싱은 `l3.safe_parse`(CONST-09 단일 진입점)로만 한다 — 입력은
저작 코퍼스·생성기 산출이지만 진입점을 우회하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final

import sympy

from whymath_backend.l3.safe_parse import safe_sympify

__all__ = [
    "COINCIDENCE_RULE_IDS",
    "EXTREMUM_POINT_KEBAB",
    "POST_QUALIFICATION_RULE_IDS",
    "ROUND4_RULE_IDS",
    "ROUND5_RULE_IDS",
    "ROUND6_RULE_IDS",
    "ROUND7_RULE_IDS",
    "RULE_IDS",
    "ShortcutProbe",
    "ShortcutViolation",
    "extremum_point_count",
    "has_rational_root",
    "is_shifted_biquadratic",
    "motion_symbols_not_in_subject",
    "parameter_coincidences",
    "power_path_derivative",
    "probe_from_record",
    "shortcut_violations",
    "undefined_motion_symbols",
    "violations_by_rule",
    "visible_polynomials",
]

#: 판정기가 낼 수 있는 규칙 id 전부(테스트·보고가 참조하는 단일 원천).
RULE_IDS: Final[tuple[str, ...]] = (
    "W-notation",
    "W-point-x",
    "W-trivial-ineq",
    "W-zero-hour",
    "W-extremum-josa",
    "E-derivative",
    "E-parameter",
    "E-kinematics",
    "E-sign",
    "E-symbol-intro",
    "E-tautology",
    "E-term",
    "T05-quadratic-tangency",
    "T-value-determines",
    "T06-given-rate",
    "T08-derivative-inequality",
    "T08-pinned-kind",
    "T09-rational-root",
    "T09-biquadratic",
    "T09-repeated-root",
    "T09-low-degree",
    "T09-pinned-minimizer",
    "T10-average-only",
    # ── 4회차(2026-10-07) 결함 부류 — `ROUND4_RULE_IDS` ──
    "W-ascii-inequality",
    "W-sqrt-call",
    "E-object-intro",
    "T-zero-monomial",
    "T05-vertex-tangent",
    "T05-line-tangent",
    "T08-given-critical-points",
    "T08-biquadratic",
    "T09-no-application",
    "T10-linear-position",
    # ── 5회차(2026-10-08 · 은행 감사 S5 불합격 k = 68) 결함 부류 — `ROUND5_RULE_IDS` ──
    "T-quadratic-mean-value",
    "T10-quadratic-rest",
    "T-midpoint-answer",
    "T-integer-pinned-by-interval",
    "T06-roots-given",
    "T-function-value-path",
    "T-coefficient-reading",
    "T-constant-derivative",
    "T09-degree-count",
    "T09-critical-count",
    "T09-given-extremum-values",
    "T05-quadratic-tangent-constant",
    "T05-given-coordinate",
    "M-link-procedure",
    "M-link-undescribed",
    "E-premise-reversal",
    "E-undefined-letter",
    "E-excluded-root",
    "E-velocity-before-acceleration",
    "E-rest-meaning",
    "E-y-axis-zero",
    "E-run-on",
    "E-term-rolle",
    "V05-touch-verify-mismatch",
    # ── 6회차(2026-10-08 · 은행 감사 2회차 S5 불합격 k = 23) 결함 부류 — `ROUND6_RULE_IDS` ──
    "M-link-contradictory",
    "M-link-extremum-point",
    "E-motion-symbol-intro",
    "T-ratio-shortcut",
    "T-derivative-roots-coincidence",
    "T09-factored-level",
    "U-extra-solution",
    "V-count-interval",
    "W-curve-subject",
    # ── 7회차(2026-10-08 · 은행 감사 3회차 S5 불합격 k = 11) 결함 부류 — `ROUND7_RULE_IDS` ──
    "T05-quadratic-slope",
    "T-power-path-coincidence",
    "T-component-critical-point",
    "T10-confusable-quantity",
    "E-motion-symbol-subject",
    "E-function-notation",
    "E-conclusion-target",
)

#: 4회차 감사(합집합 88·둘 다 27)를 계기로 더한 규칙 — 3회차 재현율·과잉 거부 동결 테스트는 이
#: 규칙들을 빼고 본다(3회차 판정자는 '<=' 등을 결함으로 보지 않았다 — 같은 원문에 대한 기준이
#: 회차마다 다르므로, 회차별 측정은 그 회차의 규칙 집합으로 한다).
ROUND4_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("W-ascii-inequality") : RULE_IDS.index("T-quadratic-mean-value")]
)

#: 5회차 은행 감사(2026-10-08 · `docs/data/p3_calculus1_diff_audit/bank_audit/` · as-found k = 68)를
#: 계기로 더한 규칙. 4회차 이전 회차의 재현율·과잉 거부 동결은 이 규칙들을 빼고 본다(회차별 측정은
#: 그 회차의 규칙 집합으로 한다 — `ROUND4_RULE_IDS`와 같은 원칙). 끝 경계는 6회차 첫 규칙이다(6회차
#: 규칙이 이 슬라이스에 섞이면 5회차 동결이 6회차 규칙까지 세게 된다).
ROUND5_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("T-quadratic-mean-value") : RULE_IDS.index("M-link-contradictory")]
)

#: 6회차 은행 감사(2026-10-08 · `bank_audit_r2/` · as-found k = 23)를 계기로 더한 규칙 — 같은
#: 원칙으로 5회차 동결은 이 규칙들을 빼고 본다. 끝 경계는 7회차 첫 규칙이다(7회차 규칙이 이
#: 슬라이스에 섞이면 6회차 동결이 7회차 규칙까지 세게 된다).
ROUND6_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("M-link-contradictory") : RULE_IDS.index("T05-quadratic-slope")]
)

#: 7회차 은행 감사(2026-10-08 · `bank_audit_r3/` · as-found k = 11)를 계기로 더한 규칙 — 같은
#: 원칙으로 6회차 동결은 이 규칙들을 빼고 본다. 다음 회차 규칙은 이 슬라이스 *뒤*에 붙이고 끝 경계를
#: 고친다.
ROUND7_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("T05-quadratic-slope") :]
)

#: 자격 측정(`qualification/` · 2026-10-08) **뒤에** 더한 회차 규칙 전부. 측정을 통과한 감사
#: 프로토콜의 기계 투표는 4회차 규칙 집합으로 고정돼 있으므로 이 집합은 생성기 빌드 가드 전용이다
#: (`p3_audit_qualification.EXCLUDED_GUARD_RULES`·시더의 원본 선별이 같은 집합을 뺀다). 앞으로 더할
#: 회차의 규칙 집합도 여기에 합친다 — 합치지 않으면 투표·시험지 재현이 조용히 바뀐다.
POST_QUALIFICATION_RULE_IDS: Final[frozenset[str]] = (
    ROUND5_RULE_IDS | ROUND6_RULE_IDS | ROUND7_RULE_IDS
)

#: 5·6회차 규칙 중 *매개변수 선택*의 우연 일치를 보는 규칙 — 틀(frame)의 설계가 아니라 고른 수치가
#: 오답 경로와 정답을 겹치게 만든 경우다(f'(1) 대신 f(1)로 풀어도 같은 a · 구간 안 자연수가 하나뿐 ·
#: 차수로 센 개수가 정답 · 대칭 근 · 극값이 0이라 인수분해로 센다 등). 생성기는 이 규칙에 걸리는
#: 매개변수를 *건너뛴다*(`p3_diff_skeleton_base.round_robin_items`의 `standard_code` 인자 — 매개변수
#: 거부 조건의 단일 원천). 나머지 규칙은 틀 설계 결함이라 빌드가 멈춘다(fail-loud).
COINCIDENCE_RULE_IDS: Final[frozenset[str]] = frozenset(
    {
        "T-midpoint-answer",
        "T-integer-pinned-by-interval",
        "T-function-value-path",
        "T-coefficient-reading",
        "T-constant-derivative",
        "T09-degree-count",
        "T09-critical-count",
        "T05-given-coordinate",
        # ── 6회차 ──
        "T-ratio-shortcut",
        "T-derivative-roots-coincidence",
        "T09-factored-level",
        # ── 7회차 ──
        "T-power-path-coincidence",
        "T-component-critical-point",
        "T10-confusable-quantity",
    }
)

_C05: Final = "[12미적Ⅰ-02-05]"
_C06: Final = "[12미적Ⅰ-02-06]"
_C08: Final = "[12미적Ⅰ-02-08]"
_C09: Final = "[12미적Ⅰ-02-09]"
_C10: Final = "[12미적Ⅰ-02-10]"
_REAL_ROOT_COUNT: Final = "real_root_count"


@dataclass(frozen=True, slots=True)
class ShortcutProbe:
    """판정 대상 문항 1건의 중립 표본 — 생성기 문항과 은행 레코드가 같은 모양으로 들어온다."""

    standard_code: str
    question_text: str
    answer: str
    explanation: str
    choices: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None
    #: [5회차] 답 형식('자연수'·'분수'·'실수') — 자연수 답과 구간 단서가 답을 하나로 좁히는지 본다.
    answer_format: str | None = None
    # [5회차] 오답 선지–오개념 연결 (선지 인덱스, 오개념 id) — 연결 선지가 그 오개념 절차의 값인지
    # 본다.
    distractors: tuple[tuple[int, str], ...] = ()
    #: [5회차] 슬롯 id(`p3-slot:` 태그 값) — 보고용(규칙 판정에는 쓰지 않는다).
    slot: str | None = None

    @property
    def answer_dict(self) -> dict[str, str]:
        return dict(self.answer_map)


@dataclass(frozen=True, slots=True)
class ShortcutViolation:
    """위반 1건 — 어느 규칙을 왜 어겼는지(사람이 틀을 고칠 수 있게)."""

    rule: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.reason}"


def probe_from_record(record: Mapping[str, object]) -> ShortcutProbe:
    """은행 JSONL 레코드 → 표본(`verify` 재료·선지·해설을 그대로 옮긴다)."""
    codes = record.get("achievement_standard_codes")
    code = str(codes[0]) if isinstance(codes, list) and codes else ""
    verify = record.get("verify")
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None
    if isinstance(verify, Mapping):
        raw = verify.get("conditions")
        if isinstance(raw, str):
            conditions = (raw,)
        elif isinstance(raw, list):
            conditions = tuple(str(c) for c in raw)
        amap = verify.get("answer_map")
        if isinstance(amap, Mapping):
            answer_map = tuple((str(k), str(v)) for k, v in amap.items())
        kind = verify.get("answer_kind")
        answer_kind = str(kind) if isinstance(kind, str) else None
    choices = record.get("choices")
    raw_format = record.get("answer_format")
    distractors: list[tuple[int, str]] = []
    raw_map = record.get("distractor_map")
    if isinstance(raw_map, list):
        for entry in raw_map:
            if isinstance(entry, Mapping):
                index, mid = entry.get("choice_index"), entry.get("misconception_id")
                if isinstance(index, int) and isinstance(mid, str):
                    distractors.append((index, mid))
    tags = record.get("tags")
    slot = next(
        (
            str(t)[len("p3-slot:") :]
            for t in (tags if isinstance(tags, list) else [])
            if str(t).startswith("p3-slot:")
        ),
        None,
    )
    return ShortcutProbe(
        standard_code=code,
        question_text=str(record.get("question_text") or ""),
        answer=str(record.get("answer") or ""),
        explanation=str(record.get("answer_explanation") or ""),
        choices=tuple(str(c) for c in choices) if isinstance(choices, list) else (),
        conditions=conditions,
        answer_map=answer_map,
        answer_kind=answer_kind,
        answer_format=str(raw_format) if isinstance(raw_format, str) else None,
        distractors=tuple(distractors),
        slot=slot,
    )


# ──────────────────────────────────────────────────────────────────────────
# 학생 표기 다항식 읽기 — '2x^3 - 3x + 1'·'x^3 + ax^2 - 9x + 4'·'x^n'
# ──────────────────────────────────────────────────────────────────────────
# 항: (정수 계수)(문자^지수)… 또는 정수. 지수는 숫자 또는 문자 하나(x^n).
_TERM = r"(?:\d+)?(?:[a-z](?:\^(?:\d+|[a-z]))?)+|\d+"
#: 발문의 다항식 덩어리 — 함수 기호의 인자 'f(x)'의 x나 프라임 'f'(x)'의 일부는 잡지 않는다.
_POLY_RE = re.compile(
    rf"(?<![A-Za-z0-9'^(/])-?(?:{_TERM})(?:\s[-+]\s(?:{_TERM}))*(?![A-Za-z0-9^'(/])"
)


def _student_to_sympy_text(text: str) -> str:
    """학생 표기 → SymPy 표기('2ax^2' → '2*a*x**2'). 곱을 명시하고 캐럿을 거듭제곱으로 바꾼다."""
    out = re.sub(r"(\d)([a-z])", r"\1*\2", text)
    while True:
        nxt = re.sub(r"([a-z])([a-z])", r"\1*\2", out)
        if nxt == out:
            break
        out = nxt
    out = re.sub(r"([a-z0-9])\^", r"\1**", out)
    return out


def _parse_student(text: str) -> sympy.Expr | None:
    try:
        value = safe_sympify(_student_to_sympy_text(text.strip()))
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    return value if isinstance(value, sympy.Expr) else None


def visible_polynomials(question_text: str) -> list[sympy.Expr]:
    """발문에 학생이 *보는* 다항식 덩어리(문자를 하나 이상 포함한 것)를 SymPy 식으로 모은다."""
    out: list[sympy.Expr] = []
    for match in _POLY_RE.finditer(question_text):
        chunk = match.group(0)
        if not re.search(r"[a-z]", chunk):
            continue
        expr = _parse_student(chunk)
        if expr is not None and expr.free_symbols:
            out.append(sympy.expand(expr))
    return out


# ──────────────────────────────────────────────────────────────────────────
# 검산 조건 읽기
# ──────────────────────────────────────────────────────────────────────────
_REL_RE = re.compile(r"\s(<=|>=|!=|=|<|>)\s")


@dataclass(frozen=True, slots=True)
class _Relation:
    lhs: sympy.Expr
    op: str
    rhs: sympy.Expr

    @property
    def difference(self) -> sympy.Expr:
        return sympy.expand(self.lhs - self.rhs)


def _parse_relation(condition: str) -> _Relation | None:
    """'lhs op rhs'(공백으로 감싼 관계 연산자 하나) → 관계. 미분 조건은 읽지 않는다(None)."""
    if "Derivative" in condition:
        return None
    match = _REL_RE.search(condition)
    if match is None:
        return None
    try:
        lhs = safe_sympify(condition[: match.start()])
        rhs = safe_sympify(condition[match.end() :])
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    if not isinstance(lhs, sympy.Expr) or not isinstance(rhs, sympy.Expr):
        return None
    return _Relation(lhs, match.group(1), rhs)


def _variable_of(probe: ShortcutProbe) -> sympy.Symbol:
    """문항의 독립변수 — 검산 조건에 t가 있으면 t(운동), 아니면 x."""
    joined = " ".join(probe.conditions)
    return (
        sympy.Symbol("t") if re.search(r"(?<![A-Za-z])t(?![A-Za-z])", joined) else sympy.Symbol("x")
    )


def has_rational_root(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """유리수 근이 있는가(일차 인수) — 생성기가 같은 술어로 미리 거른다(판정 정의의 단일 원천)."""
    _, factors = sympy.factor_list(expr, var)
    return any(sympy.degree(f, var) == 1 for f, _ in factors)


def is_shifted_biquadratic(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """사차식이 어떤 x = h에 대해 대칭인가 — P(x + h)가 짝수 차 항만 가지면 이차식으로 환원된다."""
    poly = sympy.Poly(expr, var)
    if poly.degree() != 4:
        return False
    coeffs = poly.all_coeffs()
    h = sympy.Rational(-coeffs[1], 4 * coeffs[0])
    shifted = sympy.Poly(sympy.expand(expr.subs(var, var + h)), var)
    return all(c == 0 for (e,), c in shifted.terms() if e % 2 == 1)


def _has_repeated_factor(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    _, factors = sympy.factor_list(expr, var)
    return any(mult >= 2 and sympy.degree(f, var) >= 1 for f, mult in factors)


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 표기]
# ──────────────────────────────────────────────────────────────────────────
#: 학생 문면에 새어 나온 SymPy 함수명(근호 'sqrt('는 4회차 규칙 W-sqrt-call이 따로 본다).
_SYMPY_FUNCTION = re.compile(r"\b(?:Derivative|Abs|Rational|Integer|Symbol|Poly|Eq)\(")
#: [4회차] 코드식 부등호 — 학생 표기는 '≤'·'≥'(승인 은행 관례). '=>'·'=<'는 쓰지 않으므로
#: 보지 않는다.
_W_ASCII_INEQ = re.compile(r"<=|>=")
#: [4회차] 함수 호출꼴 근호 — 학생 표기는 '√3'·'8√3'.
_W_SQRT_CALL = re.compile(r"sqrt\(")
_W_POINT_X = re.compile(r"위의 [xt] = -?\d+(?:/\d+)?에서")
_NUM = r"-?\d+(?:/\d+)?"
#: 부등호는 코드식('<=')과 학생 표기('≤') 둘 다 읽는다 — 표기를 바꿔도 자명 부등식 검출이 꺼지지
#: 않게(4회차 표기 교정이 이 규칙을 무력화하지 않게) 한다.
_LE = r"(?:<=?|≤)"
_W_TRIVIAL_INEQ = re.compile(rf"\(\s*{_NUM}\s*{_LE}\s*{_NUM}\s*{_LE}\s*{_NUM}\s*\)")
_W_ZERO_HOUR = re.compile(r"(?<!\d)0\s*시간\s*(?:부터|후|동안)|후\s+0\s*시간")
_W_EXTREMUM_JOSA = re.compile(r"의 극(?:값|댓값|솟값)을 갖는|점이 [xt] = ")


def _notation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    fields = [("발문", probe.question_text), ("해설", probe.explanation)]
    fields += [(f"선지 {i + 1}", c) for i, c in enumerate(probe.choices)]
    fields += [("정답", probe.answer)]
    for name, text in fields:
        if "*" in text or _SYMPY_FUNCTION.search(text):
            out.append(
                ShortcutViolation(
                    "W-notation",
                    f"{name} {text!r}에 SymPy 표기('*'·'Derivative(' 등)가 학생에게 노출된다 — "
                    "곱은 이어 쓴다('3x^2'·'8√3').",
                )
            )
        if _W_ASCII_INEQ.search(text):
            out.append(
                ShortcutViolation(
                    "W-ascii-inequality",
                    f"{name} {text!r}에 코드식 부등호('<='·'>=')가 있다 — 학생 표기 "
                    "'≤'·'≥'로 쓴다.",
                )
            )
        if _W_SQRT_CALL.search(text):
            out.append(
                ShortcutViolation(
                    "W-sqrt-call",
                    f"{name} {text!r}에 함수 호출꼴 근호 'sqrt('가 있다 — 학생 표기 '√'로 쓴다"
                    "('8sqrt(3)' → '8√3').",
                )
            )
    q = probe.question_text
    if _W_POINT_X.search(q):
        out.append(
            ShortcutViolation(
                "W-point-x", "'위의 x = a에서의'는 점을 x값으로만 부른다 — 'x좌표가 a인 점'."
            )
        )
    if _W_TRIVIAL_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "W-trivial-ineq",
                "상수만으로 된 자명한 부등식 괄호(예 '(-1 < 0 < 2)')는 템플릿 흔적이다.",
            )
        )
    if _W_ZERO_HOUR.search(q):
        out.append(
            ShortcutViolation("W-zero-hour", "'출발 후 0시간'은 템플릿 값 0이 그대로 든 표현이다.")
        )
    if _W_EXTREMUM_JOSA.search(q):
        out.append(
            ShortcutViolation(
                "W-extremum-josa",
                "'f(x)…의 극값을 갖는'(주어 조사)·'점이 x = '(점과 x값 등치)는 잘못된 표현이다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 해설]
# ──────────────────────────────────────────────────────────────────────────
#: 도함수 식의 머리 — 'f'(x) = …'·"f'(x)는 3x^2"·"y' = …"·'v(t) = …'·'a(t) = …'·'dy/dx = …'·
#: "f'(a)는 9a^8"(문자에서의 미분계수를 문자식으로)·'도함수는 6x^2 - 2'·'도함수 -3x^2 + 4x'.
#: 우변(그룹 rhs)이 독립변수(또는 괄호 안 문자)를 품어야 *식*이다 — 'f'(x) = 0의 근'은 식이 아니다.
_DERIV_FORMULA = re.compile(
    r"(?<![A-Za-z])(?:(?P<fn>[a-z]'{1,2})\((?P<arg>[a-z])\)|y'|v\(t\)|a\(t\)|dy/dx)"
    r"\s*(?:=|는|은)\s*(?P<rhs>[^가-힣]+)"
    r"|도함수(?:는|가|인|)\s+(?P<rhs2>\(?-?[\dxt(][^가-힣]*)"
)
_VELOCITY_FORMULA = re.compile(r"(?<![A-Za-z])(?:v\(t\)|[a-z]'\(t\))\s*=\s*\S")
_ACCEL_FORMULA = re.compile(r"(?<![A-Za-z])(?:a\(t\)|v'\(t\)|[a-z]''\(t\))\s*=\s*\S")
#: 함수 정의 — 'f(x) = …'·'y = …'·'x = …'(운동의 위치)·'x(t) = …'·'s(t) = …'.
_DEFINITION = re.compile(
    r"(?<![A-Za-z'])(?P<name>[a-z])(?:\((?P<arg>[xt])\))?\s*=\s*(?P<rhs>[^가-힣,=]+)"
)
_FUNCTION_NAMES: Final = frozenset("fghy")


def _clean_rhs(raw: str, var: str) -> str:
    """정의 우변에서 다항식 부분만 남긴다.

    닫히지 않은 괄호 꼬리('(n')·변수 없는 괄호 꼬리('(km)')를 뗀다.
    """
    rhs = raw.strip()
    rhs = re.sub(r"\s*\([^)]*$", "", rhs)
    tail = re.search(r"\s+\(([^()]*)\)\s*$", rhs)
    if tail and var not in tail.group(1):
        rhs = rhs[: tail.start()]
    return rhs.strip()


def _definitions(text: str, var: str) -> list[tuple[str, str]]:
    """발문의 다항함수 정의 (이름, 우변) — 'x = a'(점 지정)·'h(x) = 4f(x) - 2g(x)'(추상 함수 결합)는
    다항함수 정의가 아니다."""
    out: list[tuple[str, str]] = []
    for m in _DEFINITION.finditer(text):
        name, rhs = m.group("name"), _clean_rhs(m.group("rhs"), var)
        if m.group("arg") is None and name == var:
            continue
        if m.group("arg") is None and name not in ("y", "x"):
            continue
        if re.search(r"[a-z]\(", rhs):
            continue
        if not re.search(rf"(?<![A-Za-z]){var}|\d*{var}", rhs):
            continue
        out.append((name, rhs))
    return out


def _max_degree(definitions: Iterable[tuple[str, str]], var: str) -> int:
    """정의된 다항함수의 최고 차수(파싱 불가는 2로 본다 — 상수 도함수 예외를 열지 않는다)."""
    symbol = sympy.Symbol(var)
    best = 0
    for _, rhs in definitions:
        expr = _parse_student(rhs)
        if expr is None or symbol not in expr.free_symbols:
            best = max(best, 2 if expr is None else 0)
            continue
        try:
            best = max(best, int(sympy.degree(sympy.expand(expr), symbol)))
        except sympy.PolynomialError:
            best = max(best, 2)
    return best


def _has_derivative_formula(explanation: str, var: str, max_degree: int) -> bool:
    """해설에 도함수 *식*이 있는가 — 우변이 독립변수(또는 미분계수의 문자 인자)를 품거나, 함수가
    일차 이하라 도함수가 상수일 때(우변 상수 허용)."""
    for m in _DERIV_FORMULA.finditer(explanation):
        rhs = m.group("rhs") if m.group("rhs") is not None else (m.group("rhs2") or "")
        letters = {var}
        if m.group("arg"):
            letters.add(m.group("arg"))
        if any(re.search(rf"\d*{letter}(?![A-Za-z(])", rhs) for letter in letters):
            return True
        # 미분 차수 — 프라임 개수(f''는 2)·a(t)는 2계·그 밖(y'·v(t)·dy/dx·'도함수')은 1계.
        head = m.group(0)
        order = len(m.group("fn")) - 1 if m.group("fn") else (2 if head.startswith("a(") else 1)
        if max_degree <= order and re.search(r"-?\d", rhs):
            return True  # 차수 이하로 미분한 도함수는 상수다(우변 상수 허용)
    return False


def _parameters(definitions: Iterable[tuple[str, str]], var: str) -> set[str]:
    """함수 정의 우변의 미지 상수 — 독립변수·함수 기호(뒤에 '('가 오는 문자)를 뺀 문자."""
    params: set[str] = set()
    for _, rhs in definitions:
        for m in re.finditer(r"[a-z]", rhs):
            letter = m.group(0)
            after = rhs[m.end() : m.end() + 1]
            if letter == var or after == "(" or letter in _FUNCTION_NAMES:
                continue
            params.add(letter)
    return params


def _algebraic_use(text: str, letter: str) -> bool:
    """해설에서 `letter`가 결론('a = 3'·'n은 3')이 아니라 *세운 식* 안에 한 번이라도 드는가."""
    for m in re.finditer(letter, text):
        i, j = m.start(), m.end()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[j] if j < len(text) else ""
        if prev and (prev.isascii() and (prev.isalnum() or prev in ")^")):
            return True
        if nxt and (nxt.isascii() and (nxt.isalnum() or nxt in "^(")):
            return True
        before = text[:i].rstrip()
        after = text[j:].lstrip()
        if before and before[-1] in "+-*/^(":
            return True
        if after and after[0] in "+-*/^)":
            return True
    return False


_INTRO = (
    r"{L}\s*(?:이라|라)\s*(?:하|두|놓)|{L}로\s*(?:두|놓)|[을를]\s+{L}(?![A-Za-z])"
    r"|[xt]\s*=\s*{L}(?![A-Za-z])|인\s+{L}(?:가|이|는|를|의)"
)
_TAUTOLOGY = re.compile(
    r"(?<![A-Za-z0-9])([a-z])\s*=\s*(-?\d+(?:/\d+)?)에서\s*\1\s*=\s*\2(?![\d/])"
)
_TERM_LINEAR = re.compile(r"기울기(?:가)?\s*((?:-?\d+)(?:\s*,\s*-?\d+)*)\s*인\s*일차함수")
#: [4회차] 해설이 꺼내는 도형 대상 — 발문(`_Q_OBJECT`)에 그 대상을 소개하는 말이 하나도 없으면 결함.
_E_OBJECT = re.compile(r"두 점을 잇는|접점|접선")
_Q_OBJECT = re.compile(r"점|접|곡선|직선|그래프")


def _explanation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    q, e = probe.question_text, probe.explanation
    var = str(_variable_of(probe))
    defs = _definitions(q, var)
    if defs and not _has_derivative_formula(e, var, _max_degree(defs, var)):
        out.append(
            ShortcutViolation(
                "E-derivative",
                "발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·v(t) = …)이 없다 — "
                "결론만 적은 해설이다.",
            )
        )
    for letter in sorted(_parameters(defs, var)):
        if not _algebraic_use(e, letter):
            out.append(
                ShortcutViolation(
                    "E-parameter",
                    f"발문 함수식의 미지 상수 {letter}가 해설에 세운 식(예 {letter}를 포함한 "
                    "방정식) "
                    "없이 결론으로만 나온다.",
                )
            )
    instant_q = re.sub(r"평균\s*속도", "", q).replace("가속도", "")
    if re.search(r"속도|속력|멈추|정지|운동 방향|방향을 바|방향이 바뀌", instant_q):
        if not _VELOCITY_FORMULA.search(e):
            out.append(
                ShortcutViolation("E-kinematics", "속도를 다루는 문항인데 해설에 v(t) 식이 없다.")
            )
    if "가속도" in q and not _ACCEL_FORMULA.search(e):
        out.append(
            ShortcutViolation("E-kinematics", "가속도를 묻는 문항인데 해설에 a(t) 식이 없다.")
        )
    if re.search(r"방향을 바|방향이 바뀌", q) and "부호" not in e:
        out.append(
            ShortcutViolation(
                "E-sign",
                "운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다(v = 0이 곧 방향 전환은 "
                "아니다).",
            )
        )
    q_letters = set(re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", q))
    for m in re.finditer(r"(?<![A-Za-z])[a-z]'{1,2}\(([a-z])\)", e):
        letter = m.group(1)
        if letter in ("x", "t") or letter in q_letters:
            continue
        if not re.search(_INTRO.format(L=letter), e):
            out.append(
                ShortcutViolation(
                    "E-symbol-intro",
                    f"해설이 발문에 없는 기호 {letter}를 소개 없이 쓴다('구하는 x좌표를 {letter}라 "
                    "하자').",
                )
            )
            break
    if _TAUTOLOGY.search(e):
        out.append(ShortcutViolation("E-tautology", "'q = 3에서 q = 3이다' 같은 순환 서술이 있다."))
    for m in _TERM_LINEAR.finditer(e):
        slopes = [s.strip() for s in m.group(1).split(",")]
        if "0" in slopes:
            out.append(
                ShortcutViolation("E-term", "기울기가 0인 함수는 상수함수이지 일차함수가 아니다.")
            )
    named = _E_OBJECT.search(e)
    if named is not None and not _Q_OBJECT.search(q):
        out.append(
            ShortcutViolation(
                "E-object-intro",
                f"해설이 발문에 없는 대상 '{named.group(0)}'을(를) 소개 없이 쓴다 — 발문에 점·곡선·"
                "직선·그래프가 없으면 '구간에서의 평균변화율'·'f'(c)'처럼 발문의 말로 쓴다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [개념 · 우회로]
# ──────────────────────────────────────────────────────────────────────────
_TANGENCY = re.compile(r"접할 때|접하도록|접한다|접하는 (?:점|직선)|그은 (?:두 )?접선")
_CURVE = re.compile(r"곡선 y = ")


def _curve_degrees(q: str) -> list[int]:
    degrees: list[int] = []
    for m in _CURVE.finditer(q):
        chunk = _POLY_RE.match(q, m.end())
        if chunk is None:
            continue
        expr = _parse_student(chunk.group(0))
        if expr is None:
            continue
        x = sympy.Symbol("x")
        if x in expr.free_symbols:
            degrees.append(int(sympy.degree(expr, x)))
    return degrees


#: [4회차] 수평 접선을 묻는 표현 — 포물선이면 꼭짓점 공식으로 바로 풀린다.
_HORIZONTAL = re.compile(r"꼭짓점|x축에 평행|수평|기울기가 0(?:일|인)")
#: [4회차] 직선 위의 점에서의 접선 — '직선 y = 2x - 5 위의 점 (2, -1)에서의 접선'.
_LINE_POINT = re.compile(r"직선 y = [^가-힣]+ 위의")


def _tangent_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    degrees = _curve_degrees(q)
    if _TANGENCY.search(q) and degrees and max(degrees) <= 2:
        out.append(
            ShortcutViolation(
                "T05-quadratic-tangency",
                "접할 조건을 묻는데 곡선이 이차 이하라 연립 이차방정식의 판별식만으로 풀린다 — "
                "곡선 차수가 3 이상이거나 접점의 미분계수가 풀이에 필수여야 한다.",
            )
        )
    if degrees and max(degrees) <= 2 and _HORIZONTAL.search(q):
        out.append(
            ShortcutViolation(
                "T05-vertex-tangent",
                "곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선(기울기 0)을 묻는다 — 포물선의 수평 "
                "접선은 꼭짓점에만 생기므로 -b/(2a)·완전제곱으로 미분 없이 풀린다.",
            )
        )
    if "접선" in q and _LINE_POINT.search(q):
        out.append(
            ShortcutViolation(
                "T05-line-tangent",
                "직선 위의 점에서의 접선을 묻는다 — 직선의 접선은 그 직선 자신이라 기울기를 읽기만 "
                "하면 되고, 미분계수 개념이 없는 학생도 맞힌다.",
            )
        )
    return out


#: [4회차] x = 0에서의 값을 묻는 표현 — 대입('10을 대입'은 아니다)·미분계수 f'(0)·원점·
#: 'x좌표가 0인'.
#: 'x = 0'은 x 위치 고정 읽기(`_PIN_X` — 분수까지 수 하나를 통째로 읽는다)를 그대로 쓴다.
_ZERO_PHRASE = re.compile(r"(?<!\d)0을 대입|[a-z]'\(0\)|원점|x좌표가 0인")
#: [4회차] 방정식 f'(x) = 0의 근을 묻는 표현.
_DERIV_ROOT = re.compile(r"[a-z]'\(x\) = 0의 (?:실근|근|해)")


def _is_power_monomial(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """x에 대해 항이 하나뿐이고 차수가 2 이상인가(c·x^n).

    계수 c는 문자여도 된다 — kx^2도 x = 0에서의 미분계수가 0이다.
    """
    try:
        poly = sympy.Poly(expr, var)
    except sympy.PolynomialError:
        return False
    return len(poly.terms()) == 1 and poly.degree() >= 2


def _zero_monomial_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """단항식 c·x^n의 x = 0(또는 f'(x) = 0의 근) — 정답·원함수 대입·오답 경로가 모두 0이다."""
    q = probe.question_text
    x = sympy.Symbol("x")
    if not any(_is_power_monomial(p, x) for p in visible_polynomials(q)):
        return []
    pinned = {sympy.Rational(v) for v in _PIN_X.findall(q)}  # `_PIN_X`는 02-08 절에 정의(같은 경계)
    at_zero = _ZERO_PHRASE.search(q) is not None or 0 in pinned
    if at_zero or _DERIV_ROOT.search(q):
        return [
            ShortcutViolation(
                "T-zero-monomial",
                "단항식 c·x^n(n ≥ 2)의 x = 0에서의 미분계수(또는 f'(x) = 0의 근)를 묻는다 — "
                "정답이 0이고 원함수에 대입해도, 지수를 안 줄이거나 계수를 빠뜨려도 0이라 거듭제곱 "
                "미분법을 변별하지 못한다.",
            )
        ]
    return []


_EXTREMUM_VALUE = re.compile(r"(?<![A-Za-z])[xt] = (-?\d+)에서 극(?:댓|솟)?값 (-?\d+)")
_TOUCH_AT = re.compile(r"(?:(?<![A-Za-z])x = |x좌표가 )(-?\d+)인 점에서 (?:서로 )?접")
_ASKED_CONSTANT = re.compile(r"상수 ([a-z])의 값")


def _asked_parameter(probe: ShortcutProbe) -> str | None:
    amap = probe.answer_dict
    for key, value in amap.items():
        if key not in ("x", "y", "t", "s") and value.strip() == probe.answer.strip():
            return key
    m = _ASKED_CONSTANT.search(probe.question_text)
    return m.group(1) if m else None


def _value_equations(probe: ShortcutProbe, var: sympy.Symbol) -> list[sympy.Expr]:
    """발문이 주는 *미분 없는* 조건 — 극값의 값(f(a) = V)·두 곡선이 a에서 만남(C1(a) = C2(a))."""
    q = probe.question_text
    defs = _definitions(q, str(var))
    funcs = [e for e in (_parse_student(rhs) for _, rhs in defs) if e is not None]
    eqs: list[sympy.Expr] = []
    m = _EXTREMUM_VALUE.search(q)
    if m and funcs:
        a, value = int(m.group(1)), int(m.group(2))
        with_params = [f for f in funcs if f.free_symbols - {var}]
        if with_params:
            eqs.append(with_params[0].subs(var, a) - value)
    touch = _TOUCH_AT.search(q)
    curves = visible_polynomials(q)
    curves = [c for c in curves if var in c.free_symbols and sympy.degree(c, var) >= 1]
    if touch and len(curves) >= 2:
        a = int(touch.group(1))
        eqs.append(curves[0].subs(var, a) - curves[1].subs(var, a))
    return eqs


def _value_determines_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    asked = _asked_parameter(probe)
    if asked is None:
        return []
    eqs = _value_equations(probe, var)
    if not eqs:
        return []
    target = sympy.Symbol(asked)
    unknowns = sorted(set().union(*(e.free_symbols for e in eqs)) - {var}, key=str)
    if target not in unknowns:
        return []
    solutions = sympy.solve(eqs, unknowns, dict=True)
    values = {sol.get(target) for sol in solutions}
    if len(values) == 1 and None not in values and not next(iter(values)).free_symbols:
        return [
            ShortcutViolation(
                "T-value-determines",
                f"발문의 함숫값 조건만으로 상수 {asked}가 정해진다 — 미분계수 조건이 풀이에 쓰이지 "
                "않는다(대입만으로 풀린다).",
            )
        ]
    return []


_GIVEN_RATE = re.compile(r"평균변화율(?:은|이|는)?\s+-?\d")


def _mvt_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _GIVEN_RATE.search(probe.question_text):
        return [
            ShortcutViolation(
                "T06-given-rate",
                "발문이 평균변화율의 값을 직접 준다 — 평균변화율을 구해 미분계수와 잇는 평균값 "
                "정리의 "
                "행위가 빠진다.",
            )
        ]
    return []


#: 도함수 부등식 — 코드식('<=')과 학생 표기('≤') 둘 다 읽는다(표기 교정이 규칙을 끄지 않게).
_DERIV_INEQ = re.compile(r"(?<![A-Za-z])[a-z]'\((?:x|t)\)\s*(?:<|>|<=|>=|≤|≥)\s")
_PINNED_KIND = re.compile(r"(?<![A-Za-z])x = -?\d+에서(?:의)? 극(?:댓|솟)값")
#: [4회차] 발문이 고정한 x 위치 — 'x = -1과 x = 3'·'x = 1/2'.
_PIN_X = re.compile(r"(?<![A-Za-z])x = (-?\d+(?:/\d+)?)")


def _sign_change_roots(expr: sympy.Expr, var: sympy.Symbol) -> set[sympy.Rational]:
    """f'의 유리수 근 중 좌우에서 부호가 바뀌는 근(= 극값을 갖는 x) — 판정 정의의 단일 원천."""
    deriv = sympy.expand(sympy.diff(expr, var))
    if deriv.free_symbols != {var}:
        return set()
    roots = sorted(
        r for r in sympy.roots(sympy.Poly(deriv, var)) if r.is_rational  # 정수·분수 근만
    )
    if not roots:
        return set()
    middles = [(a + b) / 2 for a, b in zip(roots, roots[1:], strict=False)]
    probes = [roots[0] - 1, *middles, roots[-1] + 1]
    signs = [sympy.sign(deriv.subs(var, p)) for p in probes]
    return {r for i, r in enumerate(roots) if signs[i] * signs[i + 1] < 0}


def _graph_shape_round4_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[4회차] 02-08 — 극값 위치를 둘 이상 준 문항·복이차 사차식."""
    q = probe.question_text
    x = sympy.Symbol("x")
    pins = {sympy.Rational(v) for v in _PIN_X.findall(q)}
    out: list[ShortcutViolation] = []
    given = False
    biquadratic = False
    for poly in visible_polynomials(q):
        if x not in poly.free_symbols:
            continue
        if len(pins & _sign_change_roots(poly, x)) >= 2:
            given = True
        if poly.free_symbols == {x} and is_shifted_biquadratic(poly, x):
            biquadratic = True
    if given:
        out.append(
            ShortcutViolation(
                "T08-given-critical-points",
                "발문이 극값을 갖는 x 위치를 둘 이상 준다 — 그 위치에 대입해 대소를 비교하면 "
                "극댓값·극솟값이 정해져(삼차·사차에서 '큰 값이 극댓값') 도함수와 부호 판정이 필요 "
                "없다. 임계점은 학생이 f'(x) = 0을 풀어 찾게 한다.",
            )
        )
    if biquadratic:
        out.append(
            ShortcutViolation(
                "T08-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(복이차)이라 (x - h)^2 = u로 두면 완전제곱만으로 "
                "극값의 위치·값이 나온다 — 비대칭 사차식을 쓴다.",
            )
        )
    return out


def _graph_shape_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    if _DERIV_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "T08-derivative-inequality",
                "발문이 도함수 부등식(f'(x) < 0 등)을 직접 준다 — 증가·감소 판정 없이 이차부등식만 "
                "풀면 된다.",
            )
        )
    if _PINNED_KIND.search(q) and _asked_parameter(probe) is None:
        out.append(
            ShortcutViolation(
                "T08-pinned-kind",
                "극값의 위치와 종류를 발문이 모두 주고 그 값을 묻는다 — 대입만으로 풀린다.",
            )
        )
    return out


def _equation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    amap = probe.answer_dict
    out: list[ShortcutViolation] = []
    has_derivative_condition = any("Derivative" in c for c in probe.conditions)
    if probe.answer_kind == _REAL_ROOT_COUNT:
        form = "count"
    elif set(amap) == {str(var)} and not has_derivative_condition:
        form = "root"
    elif str(var) in amap and has_derivative_condition:
        form = "extremum"
    else:
        return []
    if form == "extremum":
        pinned = amap[str(var)]
        if pinned.strip() == "0":
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 x = 0에서 갖는다 — 다항식의 상수항이 곧 답이라 미분이 필요 "
                    "없다.",
                )
            )
        if re.search(rf"(?<![A-Za-z]){var} = {re.escape(pinned)}(?![\d/])", probe.question_text):
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 묻는데 발문이 그 값을 갖는 x를 알려 준다 — 대입만으로 풀린다.",
                )
            )
        return out
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    if relation is None:
        return []
    poly = relation.difference
    if poly.free_symbols != {var}:
        return []
    visible = visible_polynomials(probe.question_text)
    for side in (relation.lhs, relation.rhs):
        if side.free_symbols and not any(sympy.expand(side - v) == 0 for v in visible):
            return []  # 학생이 보지 못하는 대표 함수(극값 증인)로 검산하는 문항
    if sympy.degree(poly, var) <= 2:
        out.append(
            ShortcutViolation(
                "T09-low-degree",
                "발문의 방정식·부등식이 이차 이하라 판별식·근의 공식만으로 풀린다.",
            )
        )
    if has_rational_root(poly, var):
        out.append(
            ShortcutViolation(
                "T09-rational-root",
                f"발문에 보이는 다항식 {poly}이 유리수 근을 갖는다 — 인수정리·인수분해로 근(또는 "
                "등호점)을 바로 얻어 도함수가 필요 없다.",
            )
        )
    if is_shifted_biquadratic(poly, var):
        out.append(
            ShortcutViolation(
                "T09-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(짝수 차 항만)이라 (x - h)^2 = u로 두면 "
                "이차방정식이 "
                "된다 — 도함수 없이 근의 공식·판별식으로 풀린다.",
            )
        )
    if form == "root" and _has_repeated_factor(poly, var):
        out.append(
            ShortcutViolation(
                "T09-repeated-root",
                "등호가 성립하는 점(근)을 묻는데 그 점이 중근이다 — 완전제곱·인수로 바로 얻는다.",
            )
        )
    return out


#: [4회차] 02-09의 '활용' 맥락 — 방정식·부등식·교점·위치 관계 중 하나는 발문에 있어야 한다.
_APPLICATION = re.compile(
    r"방정식|부등식|실근|만나|교점|위쪽|아래쪽|보이려|성립|보다 크|보다 작|오른쪽|왼쪽"
    r"|시각의 개수|x축"
)


def _application_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _APPLICATION.search(probe.question_text):
        return []
    return [
        ShortcutViolation(
            "T09-no-application",
            "발문에 방정식·부등식·교점·위치 관계 맥락이 없는 최댓값·최솟값 문항이다 — "
            "02-09(방정식과 부등식에의 활용)의 인지 행동 없이 극값 비교(02-07/02-08 영역)만으로 "
            "풀린다.",
        )
    ]


#: [4회차] 운동 문항의 위치 함수 — '위치가 x = 7로'·'위치가 x = -3t + 2일 때'·'위치가 x(t) = …'.
_POSITION = re.compile(r"위치가 (?:x|x\(t\)) = (?P<rhs>[^가-힣,]+)")


def _velocity_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    instant = re.sub(r"평균\s*속도", "", q)
    out: list[ShortcutViolation] = []
    if re.search(r"평균\s*속도", q) and not re.search(r"속도|속력|멈추|정지|방향", instant):
        out.append(
            ShortcutViolation(
                "T10-average-only",
                "평균속도만 묻는다 — 위치에 두 시각을 대입한 차분몫이라 미분(순간속도)이 필요 "
                "없다.",
            )
        )
    t = sympy.Symbol("t")
    if re.search(r"속도|속력", instant):
        for m in _POSITION.finditer(q):
            expr = _parse_student(_clean_rhs(m.group("rhs"), "t"))
            if expr is None:
                continue
            degree = int(sympy.degree(expr, t)) if t in expr.free_symbols else 0
            if degree <= 1:
                out.append(
                    ShortcutViolation(
                        "T10-linear-position",
                        f"위치 {m.group('rhs').strip()!r}가 t의 일차 이하인데 속도·가속도를 "
                        "묻는다 — "
                        "정지(속도 0)·등속(가속도 0)·일차함수의 기울기라는 선수 지식으로 풀린다.",
                    )
                )
                break
    return out


# ──────────────────────────────────────────────────────────────────────────
# [5회차] 은행 감사 S5(2026-10-08 · as-found k = 68) — 레코드 *구조*를 읽는 규칙
# ──────────────────────────────────────────────────────────────────────────
# 발문 어휘보다 레코드 구조(검산 조건의 미분 평가·함수 차수·정답 맵·선지·답 형식)를 먼저 읽는다.
# 미분 평가는 `Derivative(식, 변수[, 변수|횟수]).doit().subs(변수, 점)` 꼴로 쓰인다(Tier1 표기).
@dataclass(frozen=True, slots=True)
class _DerivCall:
    """검산 조건 문자열 안의 미분 평가 1개(바깥쪽 호출만 — 안에 든 Derivative는 몸통의 일부)."""

    body: str
    var: str
    order: int
    point: str | None
    start: int
    end: int


def _match_paren(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_args(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _derivative_calls(text: str) -> list[_DerivCall]:
    """조건 문자열의 바깥쪽 `Derivative(...)` 호출 목록(몸통·변수·미분 횟수·대입점·위치)."""
    out: list[_DerivCall] = []
    cursor = 0
    head = "Derivative("
    while True:
        start = text.find(head, cursor)
        if start < 0:
            return out
        open_index = start + len(head) - 1
        close = _match_paren(text, open_index)
        if close < 0:
            return out
        args = _split_args(text[open_index + 1 : close])
        body = args[0]
        var = args[1] if len(args) > 1 else "x"
        rest = args[2:]
        if not rest:
            order = 1
        elif len(rest) == 1 and rest[0].isdigit():
            order = int(rest[0]) if rest[0] != var else 2
        else:
            order = 1 + len(rest)
        end = close + 1
        point: str | None = None
        if text.startswith(".doit()", end):
            end += len(".doit()")
            if text.startswith(".subs(", end):
                subs_open = end + len(".subs")
                subs_close = _match_paren(text, subs_open)
                if subs_close > 0:
                    subs_args = _split_args(text[subs_open + 1 : subs_close])
                    if len(subs_args) == 2 and subs_args[0] == var:
                        point = subs_args[1]
                    end = subs_close + 1
        out.append(_DerivCall(body, var, order, point, start, end))
        cursor = end


def _sides(condition: str) -> tuple[str, str, str] | None:
    """'lhs op rhs' → (lhs, op, rhs) 원문(공백으로 감싼 첫 관계 연산자)."""
    match = _REL_RE.search(condition)
    if match is None:
        return None
    return condition[: match.start()].strip(), match.group(1), condition[match.end() :].strip()


def _plain_call(side: str) -> _DerivCall | None:
    """한 변이 통째로 미분 평가 하나인가(`Derivative(F, x).doit().subs(x, P)`) — 그 호출."""
    calls = _derivative_calls(side)
    if len(calls) == 1 and calls[0].start == 0 and calls[0].end == len(side):
        return calls[0]
    return None


def _sym(text: str) -> sympy.Expr | None:
    try:
        value = safe_sympify(text)
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    return value if isinstance(value, sympy.Expr) else None


def _poly_degree(body: str, var: str) -> int | None:
    """몸통이 var의 다항식이면 차수(몸통에 Derivative가 섞이면 None — 단순 함수만 본다)."""
    if "Derivative" in body:
        return None
    expr = _sym(body)
    if expr is None:
        return None
    symbol = sympy.Symbol(var)
    try:
        return int(sympy.Poly(sympy.expand(expr), symbol).degree())
    except (sympy.PolynomialError, sympy.GeneratorsError):
        return None


@dataclass(frozen=True, slots=True)
class _MainRelation:
    """미분 평가가 한 변을 통째로 차지하는 등식 — (호출, 다른 변의 식)."""

    call: _DerivCall
    other: sympy.Expr


def _main_relations(probe: ShortcutProbe) -> list[_MainRelation]:
    out: list[_MainRelation] = []
    for condition in probe.conditions:
        parts = _sides(condition)
        if parts is None or parts[1] != "=":
            continue
        lhs, _, rhs = parts
        for side, other in ((lhs, rhs), (rhs, lhs)):
            call = _plain_call(side)
            if call is None or "Derivative" in other:
                continue
            other_expr = _sym(other)
            if other_expr is not None:
                out.append(_MainRelation(call, other_expr))
    return out


def _answer_var(probe: ShortcutProbe) -> sympy.Symbol | None:
    """정답이 가리키는 미지수 — 정답 맵에서 값이 정답과 같은 키(하나일 때)."""
    amap = probe.answer_dict
    keys = [k for k, v in amap.items() if v.strip() == probe.answer.strip()]
    if len(keys) == 1:
        return sympy.Symbol(keys[0])
    if len(amap) == 1:
        return sympy.Symbol(next(iter(amap)))
    return None


def _rational(text: str) -> sympy.Rational | None:
    expr = _sym(text)
    if expr is None or expr.free_symbols or not expr.is_rational:
        return None
    return sympy.Rational(expr)


def _side_filters(probe: ShortcutProbe, var: sympy.Symbol) -> list[_Relation]:
    """var에 대한 부등식·≠ 조건(한 변이 var, 다른 변이 수)."""
    out: list[_Relation] = []
    for condition in probe.conditions:
        relation = _parse_relation(condition)
        if relation is None or relation.op == "=":
            continue
        if relation.lhs == var and not relation.rhs.free_symbols:
            out.append(relation)
    return out


def _passes(value: sympy.Expr, filters: Sequence[_Relation]) -> bool:
    for f in filters:
        if f.op == ">" and not value > f.rhs:
            return False
        if f.op == ">=" and not value >= f.rhs:
            return False
        if f.op == "<" and not value < f.rhs:
            return False
        if f.op == "<=" and not value <= f.rhs:
            return False
        if f.op == "!=" and value == f.rhs:
            return False
    return True


def _open_bounds(probe: ShortcutProbe, var: sympy.Symbol) -> tuple[sympy.Expr | None, ...]:
    """var의 (하한, 상한) — 조건 목록의 부등식에서 읽는다(없으면 None)."""
    lows = [f.rhs for f in _side_filters(probe, var) if f.op in (">", ">=")]
    highs = [f.rhs for f in _side_filters(probe, var) if f.op in ("<", "<=")]
    return (max(lows) if lows else None, min(highs) if highs else None)


def _solutions(eq: sympy.Expr, var: sympy.Symbol, filters: Sequence[_Relation]) -> set[sympy.Expr]:
    """eq = 0의 실수 해 중 보호 조건을 통과하는 것(풀 수 없으면 빈 집합 — 판정 보류)."""
    if eq.free_symbols != {var}:
        return set()
    try:
        raw = sympy.solve(eq, var)
    except (NotImplementedError, ValueError, TypeError):
        return set()
    return {r for r in raw if r.is_real and _passes(r, filters)}


def _answer_value(probe: ShortcutProbe) -> sympy.Rational | None:
    return _rational(probe.answer.strip())


_MVT_CODES: Final = frozenset({"[12미적Ⅰ-02-06]", "[12미적Ⅰ-02-10]"})


def _shown_functions(question: str, var: str) -> list[sympy.Expr]:
    """발문에 학생이 보는 var의 다항식 중 변수 하나('x = 1에서'의 x)가 아닌 것."""
    v = sympy.Symbol(var)
    return [p for p in visible_polynomials(question) if v in p.free_symbols and p != v]


def _is_shown(body: sympy.Expr, question: str, var: str) -> bool:
    """미분하는 식이 발문의 다항식 그대로인가(전개해 비교)."""
    expanded = sympy.expand(body)
    return any(sympy.expand(expanded - p) == 0 for p in _shown_functions(question, var))


def _quadratic_mean_value_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 이차함수의 평균값 정리·롤의 정리·평균속도 = 순간속도 — c는 늘 구간의 중점이다."""
    code = probe.standard_code
    hit = False
    if code == _C06:
        for condition in probe.conditions:
            for call in _derivative_calls(condition):
                degree = _poly_degree(call.body, call.var)
                if degree is not None and degree <= 2:
                    hit = True
        if probe.answer_kind == _REAL_ROOT_COUNT:
            relation = next(
                (r for r in map(_parse_relation, probe.conditions) if r is not None), None
            )
            if relation is not None:
                diff = relation.difference
                free = sorted(diff.free_symbols, key=str)
                if len(free) == 1 and sympy.degree(diff, free[0]) <= 1:
                    hit = True
    elif code == _C10:
        for rel in _main_relations(probe):
            call = rel.call
            if call.order != 1 or call.point is None or _rational(call.point) is not None:
                continue
            degree = _poly_degree(call.body, call.var)
            if degree is None or degree > 2 or rel.other.free_symbols:
                continue
            low, high = _open_bounds(probe, sympy.Symbol(call.point))
            if low is None or high is None or low == high:
                continue
            body = _sym(call.body)
            assert body is not None
            v = sympy.Symbol(call.var)
            rate = (body.subs(v, high) - body.subs(v, low)) / (high - low)
            if sympy.simplify(rate - rel.other) == 0:
                hit = True
    if not hit:
        return []
    return [
        ShortcutViolation(
            "T-quadratic-mean-value",
            "이차 이하 함수에 평균값 정리·롤의 정리(평균속도 = 순간속도)를 쓴다 — 도함수가 일차라 "
            "c가 늘 구간의 중점(롤은 대칭축)이어서 미분 없이 '가운데 값'으로 풀린다. 삼차 "
            "이상으로 쓴다.",
        )
    ]


def _quadratic_rest_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-10) 이차 위치함수의 속도 0 시각 — 위치 포물선의 꼭짓점이다."""
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) is not None:
            continue
        degree = _poly_degree(call.body, call.var)
        body = _sym(call.body)
        if body is None or not _is_shown(body, probe.question_text, call.var):
            # 두 점의 위치 차처럼 발문에 그대로 보이지 않는 식의 꼭짓점은 학생의 경로가 아니다
            continue
        if degree is not None and degree <= 2 and rel.other == 0:
            return [
                ShortcutViolation(
                    "T10-quadratic-rest",
                    "위치가 이차 이하인데 속도가 0인(멈추는·방향이 바뀌는) 시각을 묻는다 — 위치 "
                    "포물선의 꼭짓점 -b/(2a)로 미분 없이 풀린다. 위치를 삼차 이상으로 쓴다.",
                )
            ]
    return []


def _midpoint_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-06·02-10) 정답이 구간의 중점 — '가운데 값' 추측이 정답이 된다(변별 없음)."""
    if probe.standard_code not in _MVT_CODES:
        return []
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    low, high = _open_bounds(probe, var)
    hit = low is not None and high is not None and answer == (low + high) / 2
    if not hit:
        # 끝점 미지수형 — c와 한 끝점이 주어지고 다른 끝점을 묻는다(중점이면 2c - 끝점).
        for rel in _main_relations(probe):
            point = _rational(rel.call.point) if rel.call.point is not None else None
            if point is None or var not in rel.other.free_symbols:
                continue
            for fixed in (low, high):
                if fixed is not None and answer == 2 * point - fixed:
                    hit = True
    if not hit:
        return []
    return [
        ShortcutViolation(
            "T-midpoint-answer",
            "정답이 구간의 중점(끝점 미지수형이면 2c - 끝점)과 같다 — 평균값 정리를 모르고 '구간의 "
            "가운데'를 고르는 경로가 정답에 닿는다. c ≠ 중점인 매개변수를 쓴다.",
        )
    ]


def _integer_pin_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 자연수 답인데 발문의 구간 안 자연수가 하나뿐 — 구간 단서가 답을 알려 준다."""
    if probe.choices:
        return []
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None or not answer.is_integer or answer <= 0:
        return []
    if probe.answer_format not in (None, "자연수"):
        return []
    low, high = _open_bounds(probe, var)
    if low is None or high is None:
        return []
    inside = [n for n in range(int(sympy.floor(low)) + 1, int(sympy.ceiling(high))) if n > 0]
    inside = [n for n in inside if low < n < high]
    if inside == [int(answer)]:
        return [
            ShortcutViolation(
                "T-integer-pinned-by-interval",
                f"답 형식이 자연수인데 구간 ({low}, {high}) 안의 자연수가 {answer} 하나뿐이다 — "
                "구간 단서만으로 답이 정해진다. 구간을 넓히거나 정수가 아닌 답을 쓴다.",
            )
        ]
    return []


_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9_.^/])-?\d+(?:/\d+)?(?![A-Za-z0-9_^/])")


def _roots_given_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-06) 발문이 방정식 f'(x) = (평균변화율)의 근을 모두 적는다 — 고르기만 남는다."""
    if probe.standard_code != _C06 or "근" not in probe.question_text:
        return []
    numbers = set(_NUMBER_TOKEN.findall(probe.question_text))
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) is not None:
            continue
        body = _sym(call.body)
        if body is None or rel.other.free_symbols:
            continue
        v = sympy.Symbol(call.var)
        roots = _solutions(sympy.diff(body, v) - rel.other, v, ())
        texts = {str(sympy.Rational(r)) for r in roots if r.is_rational}
        if len(texts) >= 2 and len(texts) == len(roots) and texts <= numbers:
            return [
                ShortcutViolation(
                    "T06-roots-given",
                    "발문이 평균값 정리 방정식 f'(x) = (평균변화율)의 근을 모두 적는다 — "
                    "도함수·평균변화율 계산 없이 구간 안의 값을 고르기만 하면 된다.",
                )
            ]
    return []


def _function_value_path_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 미분계수 대신 함숫값(가속도면 위치·속도)을 넣어도 같은 답 — 대표 오답 경로와 일치."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    for rel in _main_relations(probe):
        call = rel.call
        if call.point is None or "Derivative" in call.body:
            continue
        body, point = _sym(call.body), _sym(call.point)
        if body is None or point is None:
            continue
        v = sympy.Symbol(call.var)
        # 학생이 보는 다항식이 없으면(추상 함수 f·g의 미분계수만 준 문항) 검산 조건의 함수는 증인일
        # 뿐이라 그 함숫값은 학생의 경로가 아니다. 미지수가 지수에 든 검산식(cx^m 꼴 대조)도 같은
        # 이유로 본다.
        shown = _shown_functions(probe.question_text, call.var) or re.search(
            rf"(?<![A-Za-z]){call.var}\^\d", probe.question_text
        )
        if not shown:
            continue
        if var in rel.other.free_symbols and not rel.other.is_polynomial(var):
            continue
        wrong_sides = [body] + [sympy.diff(body, v, k) for k in range(1, call.order)]
        for wrong in wrong_sides:
            eq = sympy.expand(wrong.subs(v, point) - rel.other)
            if var not in eq.free_symbols:
                continue
            if _solutions(eq, var, filters) == {answer}:
                return [
                    ShortcutViolation(
                        "T-function-value-path",
                        "미분계수 대신 함숫값(가속도 문항이면 위치·속도)을 대입하는 대표 오답 "
                        "경로로 풀어도 정답과 같은 값이 나온다 — 변별이 없다. 그 매개변수를 쓰지 "
                        "않는다.",
                    )
                ]
    return []


def _coefficient_reading_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 발문에 보이는 다항식의 x = 0(t = 0) 미분계수 — 일차항 계수를 읽으면 끝난다.

    '도함수 f'(x)의 상수항'을 묻는 문항은 검산이 같은 f'(0)이지만 과제 자체가 '도함수를 구해
    상수항을 읽는 것'이고, 미분을 모르는 학생은 어느 계수를 읽을지 정하지 못한다 — 이 규칙의 대상이
    아니다.
    """
    if "상수항" in probe.question_text:
        return []
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) != 0:
            continue
        body = _sym(call.body)
        if body is None or "Derivative" in call.body:
            continue
        if _is_shown(body, probe.question_text, call.var):
            return [
                ShortcutViolation(
                    "T-coefficient-reading",
                    "발문의 다항식을 x = 0(t = 0, y축 위의 점·출발 순간)에서 미분한 값을 묻는다 — "
                    "그 값은 일차항 계수 그대로라 계수를 읽기만 해도(거듭제곱 미분 오류가 있어도) "
                    "정답이 나온다.",
                )
            ]
    return []


def _constant_derivative_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 미분하는 식이 상수 — f - g가 상수인 두 함수처럼 모든 경로가 0이다.

    발문이 두 함수를 *따로 명시*할 때만 본다. 'g(x) = f(x) + 2일 때 g'(a) - f'(a)'처럼 상수 차이
    자체가 진단 대상인 문항(상수의 미분이 0임을 묻는다)은 상수가 살아남는다고 보는 오답 경로가
    정답과 갈린다.
    """
    for condition in probe.conditions:
        for call in _derivative_calls(condition):
            body = _sym(call.body)
            if body is None or len(_shown_functions(probe.question_text, call.var)) < 2:
                continue
            if sympy.Symbol(call.var) not in sympy.expand(body).free_symbols:
                return [
                    ShortcutViolation(
                        "T-constant-derivative",
                        "미분하는 식이 변수에 대한 상수다(예: f - g가 상수인 두 함수의 f'(a) - "
                        "g'(a)) — 답이 늘 0이고 어떤 오답 경로도 0이라 변별이 없다.",
                    )
                ]
    return []


def _count_polynomial(probe: ShortcutProbe) -> tuple[sympy.Expr, sympy.Symbol] | None:
    if probe.answer_kind != _REAL_ROOT_COUNT:
        return None
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    if relation is None:
        return None
    poly = relation.difference
    free = sorted(poly.free_symbols, key=str)
    if len(free) != 1:
        return None
    return poly, free[0]


def _count_path_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-09) 실근 개수의 대표 오답 경로 — 차수로 센 값·임계점 개수가 정답과 같다."""
    found = _count_polynomial(probe)
    answer = _answer_value(probe)
    if found is None or answer is None:
        return []
    poly, var = found
    out: list[ShortcutViolation] = []
    if answer == sympy.degree(poly, var):
        out.append(
            ShortcutViolation(
                "T09-degree-count",
                "실근의 개수가 방정식의 차수와 같다 — 'n차방정식이니 근이 n개'라는 차수 세기 오답 "
                "경로가 미분 없이 정답에 닿는다.",
            )
        )
    critical = sympy.real_roots(sympy.Poly(sympy.diff(poly, var), var))
    if answer == len(set(critical)):
        out.append(
            ShortcutViolation(
                "T09-critical-count",
                "실근의 개수가 f'(x) = 0의 서로 다른 실근(극값 후보)의 개수와 같다 — 극값 후보를 "
                "근으로 센 오답 경로가 정답에 닿는다.",
            )
        )
    return out


def _given_extremum_values_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-09) 개수 문항의 방정식이 발문에 보이지 않는다 — 극값을 발문이 알려 준다."""
    found = _count_polynomial(probe)
    if found is None:
        return []
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    assert relation is not None
    visible = visible_polynomials(probe.question_text)
    shown = [
        side
        for side in (relation.lhs, relation.rhs)
        if side.free_symbols and any(sympy.expand(side - v) == 0 for v in visible)
    ]
    if shown:
        return []
    return [
        ShortcutViolation(
            "T09-given-extremum-values",
            "실근 개수를 묻는데 방정식의 함수가 발문에 없고 극댓값·극솟값을 발문이 준다 — 도함수 "
            "없이 개형 상식과 대소 비교만으로 풀린다. 함수를 명시해 극값을 미분으로 구하게 한다.",
        )
    ]


def _quadratic_tangent_constant_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 이차 곡선의 접선 조건을 미분 없이(판별식·중근) 검산한다 — 그 경로로
    풀린다."""
    if any("Derivative" in c for c in probe.conditions) or not probe.conditions:
        return []
    x = sympy.Symbol("x")
    degrees = [
        int(sympy.degree(p, x))
        for p in visible_polynomials(probe.question_text)
        if x in p.free_symbols
    ]
    if not degrees or max(degrees) > 2 or "접" not in probe.question_text:
        return []
    return [
        ShortcutViolation(
            "T05-quadratic-tangent-constant",
            "곡선이 이차 이하인데 접선의 y절편·곡선의 상수·곡선 밖의 점에서 그은 접선을 묻는다 — "
            "연립한 이차방정식의 중근(판별식)만으로 풀린다. 곡선을 삼차 이상으로 쓴다.",
        )
    ]


_GIVEN_POINT = re.compile(r"\((-?\d+(?:/\d+)?), (-?\d+(?:/\d+)?)\)")


def _given_coordinate_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 정답이 발문에 적힌 점의 y좌표 — 발문이 답을 알려 준다(x = 1의 m + n 등)."""
    answer = _answer_value(probe)
    if answer is None:
        return []
    for m in _GIVEN_POINT.finditer(probe.question_text):
        if sympy.Rational(m.group(2)) == answer:
            return [
                ShortcutViolation(
                    "T05-given-coordinate",
                    f"정답 {answer}이(가) 발문에 적힌 점 {m.group(0)}의 y좌표와 같다 — 접선을 "
                    "몰라도 그 좌표를 옮겨 적으면 맞는다(예: x = 1에서 m + n은 접점의 y좌표).",
                )
            ]
    return []


#: 설명에 *절차*가 적히지 않은 오개념 — 연결 선지가 그 절차의 값인지 판정할 수 없다(설명 손상).
#: M0677: '…관점을 — …관점을 못 쓴다'(서술어 절단·절차 미기술 — QUAL-14가 원문 정정을 소유한다).
_UNDESCRIBED_MISCONCEPTIONS: Final = frozenset({"M0677"})


def _misconception_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 오답 선지–오개념 연결 — 연결 선지가 그 오개념 절차로 실제로 나오는 값인가."""
    if not probe.distractors or not probe.choices:
        return []
    out: list[ShortcutViolation] = []
    linked: dict[str, list[sympy.Rational | None]] = {}
    for index, mid in probe.distractors:
        value = _rational(probe.choices[index]) if 0 <= index < len(probe.choices) else None
        linked.setdefault(mid, []).append(value)
    if _UNDESCRIBED_MISCONCEPTIONS & set(linked):
        out.append(
            ShortcutViolation(
                "M-link-undescribed",
                "연결한 오개념의 설명에 잘못된 절차가 적혀 있지 않다 — 선지 값이 그 오개념에서 "
                "나오는지 판정할 수 없다. 절차가 적힌 오개념에 연결하거나 연결하지 않는다.",
            )
        )
    bad = False
    count = _count_polynomial(probe)
    if "M0615" in linked:
        degree = sympy.degree(count[0], count[1]) if count is not None else None
        bad |= any(value is None or value != degree for value in linked["M0615"])
    if "critical-point-implies-extremum" in linked:
        roots = _critical_roots(probe)
        asks_kind = re.search(r"극대|극소|극댓값|극솟값", probe.question_text) is not None
        bad |= asks_kind or any(
            value is None or value not in roots
            for value in linked["critical-point-implies-extremum"]
        )
    if "M0674" in linked:
        roots = _critical_roots(probe)
        bad |= any(value is None or value not in roots for value in linked["M0674"])
    if bad:
        out.append(
            ShortcutViolation(
                "M-link-procedure",
                "오개념이 연결된 선지가 그 오개념의 절차(차수만큼 근을 센다 · f'(a) = 0이면 "
                "극값으로 본다 · 롤의 정리처럼 f'(c) = 0을 푼다)로 나오는 값이 아니다 — 또는 묻는 "
                "대상(극대·극소)이 그 절차의 산출과 다르다.",
            )
        )
    return out


def _critical_roots(probe: ShortcutProbe) -> set[sympy.Expr]:
    """검산 조건의 미분 대상 함수 F에 대해 F'(x) = 0의 실근(유리근) — 오개념 절차 값 판정용."""
    roots: set[sympy.Expr] = set()
    for condition in probe.conditions:
        for call in _derivative_calls(condition):
            if call.order != 1 or "Derivative" in call.body:
                continue
            body = _sym(call.body)
            if body is None:
                continue
            v = sympy.Symbol(call.var)
            if body.free_symbols != {v}:
                continue
            roots |= _solutions(sympy.diff(body, v), v, ())
    return roots


# ── [5회차] 해설 ──────────────────────────────────────────────────────────
_PREMISE_ROOT = re.compile(r"[a-z]'\(x\) = 0의 한 근이 x = (-?\d+)")
_LETTER_TOKEN = re.compile(r"(?<![A-Za-z])([a-z])(?![A-Za-z])")


def _math_use(text: str, index: int, letter: str) -> bool:
    """explanation[index]의 문자 하나가 수식 안에서 쓰였는가(앞뒤가 숫자·연산자·괄호·등호)."""
    before = text[:index].rstrip()
    after = text[index + len(letter) :].lstrip()
    prev = before[-1:] if before else ""
    nxt = after[:1] if after else ""
    return bool(
        (prev and (prev.isdigit() or prev in "=+-*/^(),"))
        or (nxt and (nxt in "=+-*/^()" or nxt.isdigit()))
    )


def _explanation_round5_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q, e = probe.question_text, probe.explanation
    out: list[ShortcutViolation] = []
    premise = _PREMISE_ROOT.search(q)
    if premise is not None:
        p = premise.group(1)
        if re.search(rf"x = {re.escape(p)}에서 극값을 가지므로", e) and not re.search(
            rf"x = {re.escape(p)}에서 극", q
        ):
            out.append(
                ShortcutViolation(
                    "E-premise-reversal",
                    "발문은 'f'(x) = 0의 한 근이 x = p'만 주는데 해설은 'x = p에서 극값을 "
                    "가지므로'를 근거로 쓴다 — 발문 조건 f'(p) = 0을 그대로 쓴다(f'(p) = 0이 "
                    "극값을 뜻하지 않는다).",
                )
            )
    q_letters = set(_LETTER_TOKEN.findall(q))
    exempt = {"x", "t", "f", "g", "h", "y"}
    # 운동 문항의 v(t)·a(t)는 발문·해설이 '속도'·'가속도'를 말하면 관례 기호로 본다(멈춤 문항처럼 두
    # 말이 다 없으면 소개 없는 기호다 — 판정자 지적 be76bfc1).
    if "속도" in e or "속도" in q:
        exempt.add("v")
    if "가속도" in e or "가속도" in q:
        exempt.add("a")
    for m in _LETTER_TOKEN.finditer(e):
        letter = m.group(1)
        if letter in exempt or letter in q_letters or not _math_use(e, m.start(), letter):
            continue
        if re.search(_INTRO.format(L=letter), e):
            continue
        out.append(
            ShortcutViolation(
                "E-undefined-letter",
                f"해설이 발문에 없는 기호 {letter}를 소개 없이 식에 쓴다"
                f"('{e[max(0, m.start() - 8) : m.end() + 6]}') — 기호를 쓰지 않거나 먼저 "
                f"'…를 {letter}라 하자'로 정의한다.",
            )
        )
        break
    out += _excluded_root_rule(probe)
    if "가속도" in q and not _VELOCITY_FORMULA.search(e):
        out.append(
            ShortcutViolation(
                "E-velocity-before-acceleration",
                "가속도를 묻는데 해설에 속도 v(t)의 식이 없다 — 위치를 미분한 v(t)를 먼저 쓰고 "
                "다시 미분해 a(t)를 쓴다.",
            )
        )
    if re.search(r"멈추|정지", q) and not ("도함수" in e and re.search(r"v\(t\) = 0|속도가 0", e)):
        out.append(
            ShortcutViolation(
                "E-rest-meaning",
                "멈추는 시각을 묻는데 해설이 '속도 v(t)는 위치의 도함수'와 '멈춤 ⇔ v(t) = 0'을 "
                "말하지 않는다.",
            )
        )
    if "y축과 만나는 점" in q and not re.search(r"x좌표는 0|x = 0", e):
        out.append(
            ShortcutViolation(
                "E-y-axis-zero",
                "y축과 만나는 점을 다루는데 해설에 '그 점의 x좌표는 0'(x = 0) 단계가 없다.",
            )
        )
    if re.search(r"(?:인데|는데),[^.]*(?:인데|는데),", e):
        out.append(
            ShortcutViolation(
                "E-run-on", "해설 한 문장에 '~인데, ~인데,'가 겹친다(비문) — 문장을 나눈다."
            )
        )
    if re.search(r"롤의 정리의 결론(?:이다|인데)", e):
        out.append(
            ShortcutViolation(
                "E-term-rolle",
                "수 하나를 '롤의 정리의 결론'이라 부른다 — 결론은 'f'(c) = 0인 c가 존재한다'는 "
                "명제다.",
            )
        )
    return out


#: 세운 방정식을 정리한 꼴 — 'a^2 = 16'·'a^2이 16'·'t^2 = 25'·'(3a + 10)(a - 4) = 0'·
#: 'a^8(a - 9) = 0'.
_REDUCED_EQUATION = re.compile(r"[a-z]\^\d+\s*(?:=|이|가)\s*-?\d|\)\s*=\s*0")
#: 보호 조건으로 근을 고르는 근거 — 양수·음수·부등식·0이 아님·'~가 아닌 근'.
_SELECTION = re.compile(r"양수|음수|[a-z] > -?\d|[a-z] < -?\d|0이 아니|≠ 0|아닌 근")
_ZERO_EXCLUDED = re.compile(r"0이 아니|≠ 0|[a-z] = 0")


def _excluded_root_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 보호 조건(양수·0이 아님)이 버리는 근을 해설이 보이지 않는다(a = ±3 → 양수 3 단계
    누락)."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    if not filters:
        return []
    e = probe.explanation
    for rel in _main_relations(probe):
        call = rel.call
        body, point = _sym(call.body), _sym(call.point) if call.point else None
        if body is None or point is None or "Derivative" in call.body:
            continue
        v = sympy.Symbol(call.var)
        eq = sympy.expand(sympy.diff(body, v, call.order).subs(v, point) - rel.other)
        if eq.free_symbols != {var}:
            continue
        all_roots = _solutions(eq, var, ())
        dropped = [r for r in all_roots if r != answer and not _passes(r, filters)]
        if not dropped:
            continue
        tokens = set(_NUMBER_TOKEN.findall(e))
        named = all(
            str(sympy.Rational(r)) in tokens or (r == 0 and _ZERO_EXCLUDED.search(e))
            for r in dropped
            if r.is_rational
        ) and all(r.is_rational for r in dropped)
        # 근을 다 적지 않아도 *세운 방정식을 정리한 꼴*(a^2 = 16 · 인수분해 = 0)과 *고르는
        # 근거*(양수· t > 0·0이 아닌)가 함께 있으면 핵심 단계를 보인 것으로 본다(판정자 A가 받아들인
        # 형제 해설 형태).
        reduced = _REDUCED_EQUATION.search(e) is not None
        selected = _SELECTION.search(e) is not None
        missing = [] if (named or "±" in e or (reduced and selected)) else dropped
        if missing:
            return [
                ShortcutViolation(
                    "E-excluded-root",
                    f"방정식의 근 {', '.join(str(r) for r in missing)}을(를) 발문의 조건으로 "
                    "버리는 단계가 해설에 없다 — 세운 방정식·근 전부·조건으로 고르는 단계를 "
                    "보인다.",
                )
            ]
    return []


def _evaluated(condition: str) -> _Relation | None:
    """조건 문자열의 미분 평가를 SymPy로 계산해 넣은 관계(미분 몸통에 다른 미분이 섞이면 None)."""
    parts = _sides(condition)
    if parts is None:
        return None
    lhs_text, op, rhs_text = parts
    sides: list[sympy.Expr] = []
    for text in (lhs_text, rhs_text):
        calls = _derivative_calls(text)
        if any("Derivative" in c.body for c in calls):
            return None
        rebuilt = text
        for call in reversed(calls):
            body = _sym(call.body)
            if body is None:
                return None
            v = sympy.Symbol(call.var)
            value = sympy.diff(body, v, call.order)
            if call.point is not None:
                point = _sym(call.point)
                if point is None:
                    return None
                value = value.subs(v, point)
            rebuilt = rebuilt[: call.start] + f"({sympy.sstr(value)})" + rebuilt[call.end :]
        expr = _sym(rebuilt)
        if expr is None:
            return None
        sides.append(expr)
    return _Relation(sides[0], op, sides[1])


_TOUCH_STATEMENT = re.compile(
    r"곡선 y = (?P<family>[^가-힣]+?)(?:가|이) 곡선 y = (?P<curve>[^가-힣]+?)(?:와|과) "
    r"(?:x = |x좌표가 )(?P<a>-?\d+)인 점에서 (?:서로 )?접"
)


#: 접점이 발문에서 고정된 접선의 y절편 —
#: (a) '곡선 y = F 위의 점 (a, b)에서의 접선의 y절편을 구하시오'
#: (b) '곡선 y = H + c (c는 상수) 위의 x좌표가 a인 점에서의 접선의 y절편이 n일 때'.
_INTERCEPT_AT_POINT = re.compile(
    r"곡선 y = (?P<curve>[^가-힣]+?) 위의 점 \((?P<a>-?\d+), -?\d+\)에서의 접선의 y절편을 구하"
)
_INTERCEPT_GIVEN = re.compile(
    r"곡선 y = (?P<curve>[^가-힣]+?) \([a-z]는 상수\) 위의 x좌표가 (?P<a>-?\d+)인 점에서의 접선의 "
    r"y절편이 (?P<n>-?\d+)일 때"
)


def _touch_statement(probe: ShortcutProbe, var: sympy.Symbol) -> tuple[int, set[object]] | None:
    """발문이 접점 x = a를 고정하는 세 형태의 (a, 발문 문제의 답 해집합) — 해당 없으면 None.

    판정기 쪽 참값은 미분(sympy.diff)으로 낸다 — 생성기의 검산 경로(미분 없는 항등식·판별식)와
    독립이다.
    """
    x = sympy.Symbol("x")
    match = _TOUCH_STATEMENT.search(probe.question_text)
    if match is not None:
        family, curve = _parse_student(match["family"]), _parse_student(match["curve"])
        if family is None or curve is None:
            return None
        a = int(match["a"])
        unknowns = sorted(family.free_symbols - {x}, key=str)
        if var not in unknowns:
            return None
        gap = sympy.expand(family - curve)
        statement = sympy.solve(
            [gap.subs(x, a), sympy.diff(gap, x).subs(x, a)], unknowns, dict=True
        )
        return a, {sol.get(var) for sol in statement}
    match = _INTERCEPT_AT_POINT.search(probe.question_text)
    if match is not None:
        curve = _parse_student(match["curve"])
        if curve is None or curve.free_symbols != {x}:
            return None
        a = int(match["a"])
        return a, {sympy.expand(curve.subs(x, a) - a * sympy.diff(curve, x).subs(x, a))}
    match = _INTERCEPT_GIVEN.search(probe.question_text)
    if match is not None:
        curve = _parse_student(match["curve"])
        if curve is None or var not in curve.free_symbols:
            return None
        a, n = int(match["a"]), int(match["n"])
        intercept = curve.subs(x, a) - a * sympy.diff(curve, x).subs(x, a)
        return a, set(sympy.solve(sympy.expand(intercept - n), var))
    return None


def _touch_verify_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 접점이 발문에서 고정된 문항 — 검산 조건이 발문의 문제를 담는가.

    대상: '두 곡선이 x = a인 점에서 접할 때'(곡선족의 상수 전부 미지 — 함숫값 일치 + 기울기 일치)와
    '위의 점 (a, b) / x좌표가 a인 점에서의 접선의 y절편'(접점 고정). 검산 조건만 풀어 얻는 답 후보가
    발문의 해와 다르면(예: 상수 하나를 고정하고 접점을 풀어 둔 판별식, 기울기만 같은 다른 접선까지
    담는 판별식 — 발문에 없는 보호 조건으로 둘째 해를 버린다) 다른 문제를 가리킨다(판정자 지적
    284122b4). 보호 조건(부등식·`!=`)은 일부러 읽지 않는다 — 발문에 없는 보호로 해를 고르는 것이
    결함 자체다.
    """
    var = _answer_var(probe)
    if var is None:
        return []
    touched = _touch_statement(probe, var)
    if touched is None:
        return []
    a, expected = touched
    equations: list[sympy.Expr] = []
    for condition in probe.conditions:
        relation = _evaluated(condition)
        if relation is not None and relation.op == "=":
            equations.append(relation.difference)
    if not equations:
        return []
    free = sorted(set().union(*(e.free_symbols for e in equations)), key=str)
    if var not in free:
        return []
    verified = {sol.get(var) for sol in sympy.solve(equations, free, dict=True)}
    if verified == expected:
        return []
    return [
        ShortcutViolation(
            "V05-touch-verify-mismatch",
            f"발문(접점 x = {a} 고정 · {var} 미지)의 해 {sorted(map(str, expected))}와 검산 조건의 "
            f"해 {sorted(map(str, verified))}가 다르다 — 검산 조건이 다른 문제를 담는다. 함숫값 "
            "일치와 기울기 일치(또는 (x - a)^2 인수 조건)로 검산한다.",
        )
    ]


def _round5_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """5회차 규칙 전부(성취기준별 분기 포함)."""
    code = probe.standard_code
    out = (
        _midpoint_rule(probe)
        + _integer_pin_rule(probe)
        + _function_value_path_rule(probe)
        + _coefficient_reading_rule(probe)
        + _constant_derivative_rule(probe)
        + _misconception_rules(probe)
        + _explanation_round5_rules(probe)
    )
    if code in _MVT_CODES:
        out += _quadratic_mean_value_rule(probe)
    if code == _C06:
        out += _roots_given_rule(probe)
    if code == _C10:
        out += _quadratic_rest_rule(probe)
    if code == _C09:
        out += _count_path_rules(probe) + _given_extremum_values_rule(probe)
    if code == _C05:
        out += (
            _quadratic_tangent_constant_rule(probe)
            + _given_coordinate_rule(probe)
            + _touch_verify_rule(probe)
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [6회차] 은행 감사 2회차(2026-10-08 · `bank_audit_r2/` · as-found k = 23)
# ──────────────────────────────────────────────────────────────────────────
#: 설명이 서로 다른 두 절차를 함께 적은 오개념 — 연결 선지가 *주 절차*의 값인지 정해지지 않는다.
#: M0615: '고차방정식의 근을 두 개로 단정한다(차수만큼 근)' — 본문 절차로는 2, 괄호로는 차수가
#: 나온다 (판정자 지적 12건 · 원문 정정은 별건).
_CONTRADICTORY_MISCONCEPTIONS: Final = frozenset({"M0615"})
#: '극값·극점 혼동' kebab(정본 L4 카탈로그 · 설명 '극댓값은 극대가 되는 점의 x좌표이다').
EXTREMUM_POINT_KEBAB: Final = "extremum-value-vs-point-confused"


def _extremum_points(
    expr: sympy.Expr, var: sympy.Symbol
) -> list[tuple[sympy.Rational, str]] | None:
    """극값을 갖는 점 (x좌표, 'max'|'min') — 도함수의 실근이 전부 유리수 단순근일 때만(아니면 None).

    극점의 x좌표를 '극값'으로 넣는 절차는 x좌표가 깔끔한 수일 때만 판정자가 재현할 수 있다.
    """
    deriv = sympy.expand(sympy.diff(expr, var))
    if deriv.free_symbols != {var}:
        return None
    poly = sympy.Poly(deriv, var)
    real = sympy.real_roots(poly)
    if not real or any(not r.is_rational for r in real) or len(set(real)) != len(real):
        return None
    # 단순근만 남았으므로 근마다 도함수의 부호가 바뀐다(극값) — 왼쪽 부호가 +면 극대.
    roots = sorted(sympy.Rational(r) for r in real)
    left = [roots[0] - 1, *((a + b) / 2 for a, b in zip(roots, roots[1:], strict=False))]
    return [
        (r, "max" if deriv.subs(var, p) > 0 else "min") for r, p in zip(roots, left, strict=True)
    ]


def _verbal_counts(
    points: Sequence[tuple[sympy.Rational, str]],
    values: Sequence[sympy.Rational],
    k: sympy.Rational,
    *,
    symmetric: bool,
) -> set[int]:
    """'극솟값과 극댓값 사이면 3개, 같으면 2개, 밖이면 1개'류 표준 비교 규칙(삼차·W자·M자 사차·극값
    하나) — 실제 극값을 넣으면 f(x) = k의 서로 다른 실근 수와 같다(테스트가 SymPy 근 개수와
    대조한다).

    조건이 성립하는 조항의 결과를 *모두* 모은다(값이 실제 극값과 순서가 맞지 않으면 조항이 겹치거나
    비어 판독이 갈린다 — 호출자가 그 경우를 모호로 본다). `symmetric`이면 '사이'를 두 수의 대소와
    무관하게 읽는다(판독 B는 순서대로, 판독 C는 대칭으로).
    """
    kinds = [kind for _, kind in points]

    def between(lo: sympy.Rational, hi: sympy.Rational) -> bool:
        if symmetric:
            return bool(min(lo, hi) < k < max(lo, hi))
        return bool(lo < k < hi)

    out: set[int] = set()
    if kinds in (["max", "min"], ["min", "max"]):
        top = values[kinds.index("max")]
        bottom = values[kinds.index("min")]
        if between(bottom, top):
            out.add(3)
        if k in (bottom, top):
            out.add(2)
        if symmetric:
            if k < min(bottom, top) or k > max(bottom, top):
                out.add(1)
        elif k > top or k < bottom:
            out.add(1)
        return out
    if kinds == ["min", "max", "min"]:
        lo, hi = sorted((values[0], values[2]))
        top = values[1]
        clauses = [
            (k < lo, 0),
            (k == lo and lo != hi, 1),
            (k == lo == hi, 2),
            (lo < k < hi, 2),
            (k == hi and lo != hi, 3),
            (between(hi, top), 4),
            (k == top, 3),
            (k > top, 2),
        ]
        return {n for hit, n in clauses if hit}
    if kinds == ["max", "min", "max"]:
        lo, hi = sorted((values[0], values[2]))
        bottom = values[1]
        clauses = [
            (k > hi, 0),
            (k == hi and lo != hi, 1),
            (k == lo == hi, 2),
            (lo < k < hi, 2),
            (k == lo and lo != hi, 3),
            (between(bottom, lo), 4),
            (k == bottom, 3),
            (k < bottom, 2),
        ]
        return {n for hit, n in clauses if hit}
    if kinds == ["min"]:
        return {
            n for hit, n in ((k < values[0], 0), (k == values[0], 1), (k > values[0], 2)) if hit
        }
    if kinds == ["max"]:
        return {
            n for hit, n in ((k > values[0], 0), (k == values[0], 1), (k < values[0], 2)) if hit
        }
    return {-1}  # 다루지 않는 모양(극값 4개 이상) — 모호로 본다


def extremum_point_count(expr: sympy.Expr, var: sympy.Symbol, k: sympy.Expr) -> int | None:
    """'극값·극점 혼동' 절차로 센 방정식 f(x) = k의 실근 개수 — 판독이 갈리면 None.

    절차: 극댓값·극솟값 자리에 극대·극소가 되는 점의 **x좌표**를 넣고, 나머지는 표준 비교 규칙(k가
    극솟값과 극댓값 사이면 3개, 같으면 2개, 밖이면 1개 — 사차는 극값 3개로 같은 방식)을 그대로 쓴다.
    판정자가 이 값을 재현할 수 있어야 하므로 두 판독 — B 순서가 정해진 비교 규칙, C '사이'를
    대칭으로 읽은 비교 규칙 — 이 **모두 같은 수 하나**를 낼 때만 그 수를 돌려준다. 극점 x좌표가 실제
    극값과 순서가 다르면(삼차 계수 양수 등) 판독이 갈리고 None이다. 해설 본문의 '증감 구간마다
    지나는 값의 범위'에 값을 넣어 세는 판독은 B가 한 값을 낼 때 늘 B와 같아 따로 두지 않는다(실측:
    임계점 -4..4의 삼차·사차 × k 반정수 6,000건에서 두 판독이 갈린 408건은 전부 B 자신이 이미
    모호했다). 생성기가 오답 선지 값을 고르는 데와 판정기 `M-link-extremum-point`가 같은 정의를
    쓴다(단일 원천).
    """
    if not isinstance(k, sympy.Expr) or k.free_symbols or not k.is_rational:
        return None
    points = _extremum_points(expr, var)
    if points is None:
        return None
    level = sympy.Rational(k)
    values = [x for x, _ in points]  # ← 혼동: 극값 대신 x좌표
    readings = _verbal_counts(points, values, level, symmetric=False)
    readings |= _verbal_counts(points, values, level, symmetric=True)
    return next(iter(readings)) if len(readings) == 1 and -1 not in readings else None


def _count_level(probe: ShortcutProbe) -> tuple[sympy.Expr, sympy.Symbol, sympy.Expr] | None:
    """개수 문항의 방정식을 f(x) = k로 읽는다 — 해설이 극값과 비교하는 바로 그 f와 k.

    우변이 상수면 (좌변, 우변), 두 변에 모두 x가 있으면(두 곡선) 차를 정리해 상수항을 우변으로 넘긴
    꼴(해설의 '정리하면 f(x) = k')이다. 좌변이 상수인 꼴('k = f(x)')은 생성기가 쓰지 않으므로 읽지
    않는다(None — 연결 선지 판정이 실패로 드러난다).
    """
    found = _count_polynomial(probe)
    if found is None:
        return None
    _, var = found
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    assert relation is not None
    lhs, rhs = sympy.expand(relation.lhs), sympy.expand(relation.rhs)
    if not rhs.free_symbols:
        return lhs, var, rhs
    if not lhs.free_symbols:
        return None
    gap = sympy.expand(lhs - rhs)
    constant = gap.subs(var, 0)
    return sympy.expand(gap - constant), var, -constant


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[다요])\.\s*", text) if s]


def _extremum_point_link_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] '극값·극점 혼동' 연결 선지가 그 절차의 값인가 · 해설이 그 절차를 보이는가."""
    values = [
        _rational(probe.choices[index]) if 0 <= index < len(probe.choices) else None
        for index, mid in probe.distractors
        if mid == EXTREMUM_POINT_KEBAB
    ]
    level = _count_level(probe)
    if level is None:
        # 개수 문항이 아니면 고전 형태 — 극값의 *값*을 묻는데 극점의 x좌표를 답한 선지.
        roots = _critical_roots(probe)
        expected: set[sympy.Expr] | None = roots or None
    else:
        count = extremum_point_count(*level)
        expected = None if count is None else {sympy.Integer(count)}
    out: list[ShortcutViolation] = []
    if expected is None or any(v is None or v not in expected for v in values):
        out.append(
            ShortcutViolation(
                "M-link-extremum-point",
                "'극값·극점 혼동' 연결 선지가 그 절차(극값 자리에 극대·극소가 되는 점의 "
                "x좌표를 넣고 표준 비교 규칙으로 센다)로 나오는 값이 아니다 — 또는 판독(구간별 "
                "값 범위·비교 규칙)에 따라 값이 갈린다.",
            )
        )
    if level is not None:
        sentences = _sentences(probe.explanation)
        shown = all(
            v is not None and any("x좌표" in s and f"{v}개" in s and "극" in s for s in sentences)
            for v in values
        )
        if not shown:
            out.append(
                ShortcutViolation(
                    "M-link-extremum-point",
                    "해설이 '극값·극점 혼동' 연결 선지의 절차(극대·극소가 되는 점의 x좌표를 "
                    "극값으로 넣어 센 개수)를 보이지 않는다 — 판정자가 그 선지 값을 재현할 수 "
                    "없다.",
                )
            )
    return out


def _misconception_round6_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] 오개념 연결 — 자기모순 설명(M0615) · '극값·극점 혼동'의 절차 값."""
    if not probe.distractors:
        return []
    linked = {mid for _, mid in probe.distractors}
    out: list[ShortcutViolation] = []
    if _CONTRADICTORY_MISCONCEPTIONS & linked:
        out.append(
            ShortcutViolation(
                "M-link-contradictory",
                "연결한 오개념의 설명이 서로 다른 두 절차를 함께 적는다(M0615 '근을 두 개로 "
                "단정' 대 '(차수만큼 근)') — 연결 선지가 주 절차로 나오는 값인지 정해지지 "
                "않는다. 절차가 하나인 오개념에 연결하거나 연결하지 않는다.",
            )
        )
    if EXTREMUM_POINT_KEBAB in linked:
        out += _extremum_point_link_rule(probe)
    return out


#: 속도·가속도의 정의 문장 — '속도는 위치를 시각 t로 미분한 값'·'속도 v(t)는 위치 x의 도함수'.
#: '가속도는'의 '속도는'을 속도 정의로 읽지 않는다(뒤 lookbehind).
_V_DEFINITION = re.compile(r"(?<!가)속도(?:는| v\(t\)는)[^.]*?위치[^.]*?(?:미분한 값|도함수)")
_A_DEFINITION = re.compile(r"가속도(?:는| a\(t\)는)[^.]*?속도[^.]*?(?:미분한 값|도함수)")


def undefined_motion_symbols(explanation: str) -> tuple[str, ...]:
    """해설이 정의 없이 처음 쓰는 운동 기호('v(t)'·'a(t)') — 정의 문장이 첫 사용보다 앞서거나 그
    자리에서 시작해야 한다(생성기와 판정기 `E-motion-symbol-intro`가 같은 정의를 쓴다)."""
    out: list[str] = []
    for symbol, definition in (("v(t)", _V_DEFINITION), ("a(t)", _A_DEFINITION)):
        first = explanation.find(symbol)
        if first < 0:
            continue
        match = definition.search(explanation)
        if match is None or match.start() > first:
            out.append(symbol)
    return tuple(out)


def _motion_symbol_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] 해설이 v(t)·a(t)를 '속도(가속도)는 위치(속도)를 시각 t로 미분한 값' 없이
    처음 쓴다."""
    out: list[ShortcutViolation] = []
    for symbol in undefined_motion_symbols(probe.explanation):
        what = "속도는 위치를" if symbol == "v(t)" else "가속도는 속도를"
        out.append(
            ShortcutViolation(
                "E-motion-symbol-intro",
                f"해설이 {symbol}를 정의 없이 처음 쓴다 — '{what} 시각 t로 미분한 값이므로 "
                f"{symbol} = …'처럼 정의와 함께 소개한다.",
            )
        )
    return out


#: 'f'(a) = 4f'(1)' — 미분계수의 배수 관계(함수 기호·미지수·배수·비교점).
_RATIO = re.compile(r"(?<![A-Za-z])([a-z])'\(([a-z])\) = (\d+)\1'\((-?\d+)\)")


def _coefficient_dropped(expr: sympy.Expr, var: sympy.Symbol) -> sympy.Expr:
    """계수 내리기 누락 도함수 — c·x^n → c·x^(n - 1)(지수만 줄인다)."""
    poly = sympy.Poly(expr, var)
    return sympy.expand(sum(c * var ** (n - 1) for (n,), c in poly.terms() if n >= 1))


def _exponent_kept(expr: sympy.Expr, var: sympy.Symbol) -> sympy.Expr:
    """지수 유지 도함수 — c·x^n → n·c·x^n(지수를 줄이지 않는다)."""
    poly = sympy.Poly(expr, var)
    return sympy.expand(sum(n * c * var**n for (n,), c in poly.terms()))


def _shown_function(probe: ShortcutProbe, name: str) -> sympy.Expr | None:
    for fn, rhs in _definitions(probe.question_text, "x"):
        if fn == name:
            return _parse_student(rhs)
    return None


def _ratio_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] f'(a) = m·f'(b) — 비례 짐작(a = m·b)·계수 누락·지수 유지 경로가 정답과
    같은 a를 낸다."""
    match = _RATIO.search(probe.question_text)
    answer = _answer_value(probe)
    if match is None or answer is None:
        return []
    name, unknown, mult, point = match.groups()
    function = _shown_function(probe, name)
    x = sympy.Symbol("x")
    if function is None or function.free_symbols != {x}:
        return []
    var = sympy.Symbol(unknown)
    m, b = sympy.Integer(mult), sympy.Integer(point)
    filters = _side_filters(probe, var)
    paths: list[str] = []
    if answer == m * b:
        paths.append(f"비례 짐작(a = {m} × {b})")
    for label, wrong in (
        ("계수 누락 도함수", _coefficient_dropped(function, x)),
        ("지수 유지 도함수", _exponent_kept(function, x)),
    ):
        equation = sympy.expand(wrong.subs(x, var) - m * wrong.subs(x, b))
        if _solutions(equation, var, filters) == {answer}:
            paths.append(label)
    if not paths:
        return []
    return [
        ShortcutViolation(
            "T-ratio-shortcut",
            f"{name}'({unknown}) = {m}{name}'({b})의 정답이 {', '.join(paths)} 경로와 같다 — "
            "거듭제곱 미분법을 몰라도(또는 틀려도) 정답에 닿는다. 그 매개변수를 쓰지 않는다.",
        )
    ]


_GIVEN_DERIVATIVE_ROOTS = re.compile(
    r"(?<![A-Za-z])([a-z])'\(x\) = 0의 두 (?:실근|근)이 (-?\d+(?:/\d+)?), (-?\d+(?:/\d+)?)"
)


def _solve_parameters(
    equations: Sequence[sympy.Expr], unknowns: Sequence[sympy.Symbol], target: sympy.Symbol
) -> sympy.Expr | None:
    """연립의 해에서 target 값(해가 하나로 정해질 때만)."""
    try:
        solutions = sympy.solve(list(equations), list(unknowns), dict=True)
    except (NotImplementedError, ValueError, TypeError):
        return None
    values = {sol.get(target) for sol in solutions}
    if len(values) != 1:
        return None
    value = next(iter(values))
    return None if value is None or value.free_symbols else value


def _derivative_roots_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] 발문이 f'(x) = 0의 두 근을 줄 때 — 미분을 틀린 경로·발문의 근 옮겨 적기가 정답과
    같다.

    대표 예: f(x) = x^3 + ax^2 + bx에서 두 근이 ±5면 계수 누락(f'(x) = x^2 + ax + b)도, 미분하지
    않고 f(x) = x(x^2 + ax + b)의 근으로 봐도 a = 0이 나온다(대칭 근이면 늘 일치). 지수 유지 경로
    (x·f'(x))는 0이 아닌 근이 원래 도함수와 같아 *틀 구조상* 늘 같은 답이라 매개변수로 고칠 수 없다
    — 이 규칙의 대상이 아니다(정직 범위).
    """
    match = _GIVEN_DERIVATIVE_ROOTS.search(probe.question_text)
    answer, target = _answer_value(probe), _answer_var(probe)
    if match is None or answer is None or target is None:
        return []
    name, r1, r2 = match.group(1), sympy.Rational(match.group(2)), sympy.Rational(match.group(3))
    function = _shown_function(probe, name)
    x = sympy.Symbol("x")
    if function is None or target not in function.free_symbols:
        return []
    unknowns = sorted(function.free_symbols - {x}, key=str)
    paths: list[str] = []
    for label, wrong in (
        ("계수 누락 도함수", _coefficient_dropped(function, x)),
        ("미분하지 않은 식", function),
    ):
        # 근 0이 있으면 미분하지 않은 식 f(x) = x(…)의 등식 하나가 0 = 0이 되어 연립의 해가 하나로
        # 정해지지 않는다 — `_solve_parameters`가 None을 내 경로로 세지 않는다.
        if _solve_parameters([wrong.subs(x, r) for r in (r1, r2)], unknowns, target) == answer:
            paths.append(label)
    if answer in (r1, r2):
        paths.append("발문의 근 옮겨 적기")
    if not paths:
        return []
    return [
        ShortcutViolation(
            "T-derivative-roots-coincidence",
            f"발문이 {name}'(x) = 0의 두 근 {r1}, {r2}를 주는데 {', '.join(paths)} 경로가 "
            f"정답 {answer}와 같다 — 도함수 단계를 변별하지 못한다(대칭 근이면 늘 0). 그 "
            "매개변수를 쓰지 않는다.",
        )
    ]


def _factored_level_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] (02-09) 개수 문항의 방정식이나 상수항을 옮긴 식이 중근 인수를 갖는다.

    2x^3 - 12x^2 + 18x = -2(극솟값 0 → 2x(x - 3)^2 = -2)·x^3 + 6x^2 + 9x - 2 = 0(극댓값이 f(0) →
    x(x + 3)^2 = 2)처럼 인수분해와 부호만으로 개수가 정해진다(판정자 지적 9f4b4a55·2cc1e0d6).
    극값이 0이거나, 극값이 상수항(f(0))과 같거나, 임계점이 0이면 상수항을 옮긴 식에 중근이 생긴다.
    """
    found = _count_polynomial(probe)
    if found is None:
        return []
    poly, var = found
    reduced = sympy.expand(poly - poly.subs(var, 0))
    forms = []
    if _has_repeated_factor(poly, var):
        forms.append(f"방정식 {poly} = 0")
    if reduced != 0 and _has_repeated_factor(reduced, var):
        forms.append(f"상수항을 옮긴 {sympy.factor(reduced)} = {-poly.subs(var, 0)}")
    if not forms:
        return []
    return [
        ShortcutViolation(
            "T09-factored-level",
            f"{' · '.join(forms)}가 중근 인수를 가져 인수분해와 부호 판단만으로 실근 개수가 "
            "정해진다(극값이 0·상수항과 같거나 임계점이 0) — 그 매개변수를 쓰지 않는다.",
        )
    ]


# ── [6회차] 발문이 주는 범위(유일성 조건)·개수 문항의 구간 ─────────────────
_QNUM = r"(-?\d+(?:/\d+)?)"
_Q_CHAIN = re.compile(rf"{_QNUM}\s*(<=|<|≤)\s*([a-z])\s*(<=|<|≤)\s*{_QNUM}(?![\d/])")
_Q_SIDE = re.compile(rf"(?<![A-Za-z0-9/<≤=])([a-z])\s*(<=|>=|<|>|≤|≥)\s*{_QNUM}(?![\d/])")
_Q_OPEN = re.compile(rf"열린구간 \({_QNUM}, {_QNUM}\)")
_Q_THEOREM = re.compile(
    rf"구간 \[{_QNUM}, {_QNUM}\]에서 [^.?]*?(?:평균값 정리|롤의 정리)를 만족시키는"
)
_Q_BETWEEN = re.compile(rf"A\({_QNUM}, [^)]*\), B\({_QNUM}, [^)]*\) 사이")
_OP_NORMAL: Final = {"≤": "<=", "≥": ">=", "<=": "<=", ">=": ">=", "<": "<", ">": ">"}
_FLIP: Final = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
#: 서수·대소 선택어 — 발문이 근 하나를 *고르는* 말을 주면 유일성은 선택으로 정해진다.
_ORDINAL = re.compile(r"처음|두 번째|마지막|가장 큰|가장 작은|큰 값|작은 값|큰 근|작은 근")


def _question_bounds(question: str, letters: AbstractSet[str]) -> list[tuple[str, sympy.Rational]]:
    """발문이 미지수에 거는 범위 (연산자, 수) — 문자 범위는 `letters`의 문자만, 문자 없는 구간 표현
    ('열린구간 (a, b)'·'구간 [a, b]에서 평균값(롤의) 정리를 만족시키는'·'두 점 A, B 사이')은 늘
    쓴다. '양수 c'·'c는 양수'도 읽는다."""
    out: list[tuple[str, sympy.Rational]] = []
    for m in _Q_CHAIN.finditer(question):
        lo, op1, letter, op2, hi = m.groups()
        if letter in letters:
            out.append((_FLIP[_OP_NORMAL[op1]], sympy.Rational(lo)))
            out.append((_OP_NORMAL[op2], sympy.Rational(hi)))
    for m in _Q_SIDE.finditer(question):
        letter, op, value = m.groups()
        if letter in letters:
            out.append((_OP_NORMAL[op], sympy.Rational(value)))
    for pattern in (_Q_OPEN, _Q_THEOREM, _Q_BETWEEN):
        for m in pattern.finditer(question):
            a, b = sympy.Rational(m.group(1)), sympy.Rational(m.group(2))
            out += [(">", min(a, b)), ("<", max(a, b))]
    for letter in letters:
        if re.search(rf"양수 {letter}(?![A-Za-z])|{letter}는 양수", question):
            out.append((">", sympy.Integer(0)))
    return out


def _within(value: sympy.Expr, bounds: Sequence[tuple[str, sympy.Rational]]) -> bool:
    ops = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
    }
    return all(bool(ops[op](value, bound)) for op, bound in bounds)


def _interval_of(
    bounds: Sequence[tuple[str, sympy.Rational]],
) -> tuple[sympy.Rational | None, bool, sympy.Rational | None, bool]:
    """범위 목록 → (하한, 하한 포함, 상한, 상한 포함) — 같은 끝이 여럿이면 가장 좁은 것."""
    lo: sympy.Rational | None = None
    lo_closed = False
    hi: sympy.Rational | None = None
    hi_closed = False
    for op, value in bounds:
        if op in (">", ">="):
            closed = op == ">="
            if lo is None or value > lo:
                lo, lo_closed = value, closed
            elif value == lo:
                lo_closed = lo_closed and closed  # 같은 끝에 열린 조건이 하나라도 있으면 열린 끝
        elif op in ("<", "<="):
            closed = op == "<="
            if hi is None or value < hi:
                hi, hi_closed = value, closed
            elif value == hi:
                hi_closed = hi_closed and closed
    return lo, lo_closed, hi, hi_closed


def _discarded_in_explanation(explanation: str, value: sympy.Expr) -> bool:
    """해설이 그 해를 조건으로 *버리는* 문장을 갖는가('-2는 열린구간에 속하지 않으므로 버린다')."""
    if not value.is_rational:
        return False
    token = str(sympy.Rational(value))
    for sentence in _sentences(explanation):
        if token in set(_NUMBER_TOKEN.findall(sentence)) and re.search(
            r"버린|버리|속하지 않|제외|해당하지 않|맞지 않", sentence
        ):
            return True
    return False


def _format_admits(value: sympy.Expr, answer_format: str | None) -> bool:
    """답 형식이 그 해를 받아들이는가 — 자연수는 양의 정수, 분수는 정수가 아닌 유리수만."""
    if answer_format == "자연수":
        return bool(value.is_integer and value > 0)
    if answer_format == "분수":
        return bool(value.is_rational and not value.is_integer)
    return bool(value.is_real)


def _extra_solution_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] (02-06·02-10) 정답 말고도 발문 조건을 만족하는 해 — 선지·답 형식이 배제하지 않거나
    해설이 발문에 없는 조건으로 그 해를 버린다(평균속도 객관식의 c 구간 누락 — 판정자 지적 2건)."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None or _ORDINAL.search(probe.question_text):
        return []
    letters = {str(var)} | {
        letter
        for letter in "xt"
        if re.search(rf"{letter} = {var}(?![A-Za-z])", probe.question_text)
    }
    if str(var) == "s":
        letters.add("t")  # 운동 문항의 검산 미지수 s는 발문의 시각 t다
    bounds = _question_bounds(probe.question_text, letters)
    choice_values = {_rational(c) for c in probe.choices} - {None}
    for rel in _main_relations(probe):
        call = rel.call
        if call.point != str(var) or "Derivative" in call.body:
            continue
        body = _sym(call.body)
        if body is None:
            continue
        v = sympy.Symbol(call.var)
        equation = sympy.diff(body, v, call.order).subs(v, var) - rel.other
        for extra in _solutions(sympy.expand(equation), var, ()) - {answer}:
            if bounds and not _within(extra, bounds):
                continue  # 발문 조건이 이 해를 배제한다
            admitted = (
                extra in choice_values
                if probe.choices
                else _format_admits(extra, probe.answer_format)
            )
            discarded = _discarded_in_explanation(probe.explanation, extra)
            if admitted or discarded:
                why = (
                    "선지·답 형식이 배제하지 않는다"
                    if admitted
                    else "해설이 발문에 없는 조건으로 버린다"
                )
                return [
                    ShortcutViolation(
                        "U-extra-solution",
                        f"정답 {answer} 말고도 {extra}가 발문 조건을 만족하는데 {why} — 발문에 구간"
                        "(예 '(단, a < c < b)')을 넣어 해를 하나로 정한다.",
                    )
                ]
    return []


def _count_interval_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] 개수 문항 — 발문이 세는 범위(구간)를 주면 검산 조건도 *같은* 구간에서 세야 한다.

    '닫힌구간 [-4, 4]에서 평균값 정리를 만족시키는 실수 c의 개수'의 검산이 방정식 하나만 둬 실수
    전체의 근을 세면, 구간 밖 근이 생기는 매개변수에서 검산과 발문이 다른 답을 낸다(판정자 지적
    c743fda0 — 지금 두 근이 다 구간 안이라 값이 같아도 검산이 다른 문제를 가리킨다).
    """
    found = _count_polynomial(probe)
    if found is None:
        return []
    _, var = found
    question_interval = _interval_of(_question_bounds(probe.question_text, {str(var)}))
    verify_interval = _interval_of(
        [(f.op, sympy.Rational(f.rhs)) for f in _side_filters(probe, var)]
    )
    if question_interval == verify_interval:
        return []
    missing = verify_interval == (None, False, None, False)
    return [
        ShortcutViolation(
            "V-count-interval",
            (
                "발문이 세는 범위를 주는데 검산 조건이 그 구간 없이 실수 전체의 근을 센다"
                if missing
                else (
                    f"검산 조건의 구간 {verify_interval}이 발문의 구간 "
                    f"{question_interval}과 다르다"
                )
            )
            + " — 검산 조건에 발문의 구간(부등식)을 그대로 넣는다.",
        )
    ]


_CURVE_SUBJECT = re.compile(
    r"곡선 y = [^가-힣]+?(?:이|가) (?:[xt] = -?\d+(?:/\d+)?에서 )?(?:극|증가|감소)"
)


def _curve_subject_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[6회차] '곡선 y = …이 극대가 되는'·'곡선 y = …가 감소하다가' — 극대·극소·증감의
    주어는 함수다."""
    match = _CURVE_SUBJECT.search(probe.question_text)
    if match is None:
        return []
    return [
        ShortcutViolation(
            "W-curve-subject",
            f"'{match.group(0)}…' — 극대·극소·극값·증가·감소는 함수의 성질이다. 주어를 '함수 "
            "f(x) = …'로 쓴다.",
        )
    ]


def _round6_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """6회차 규칙 전부(성취기준별 분기 포함)."""
    code = probe.standard_code
    out = (
        _misconception_round6_rules(probe)
        + _motion_symbol_rule(probe)
        + _ratio_rule(probe)
        + _derivative_roots_rule(probe)
        + _count_interval_rule(probe)
        + _curve_subject_rule(probe)
    )
    if code in _MVT_CODES:
        out += _extra_solution_rule(probe)
    if code == _C09:
        out += _factored_level_rule(probe)
    return out


# ──────────────────────────────────────────────────────────────────────────
# [7회차] 은행 감사 3회차(2026-10-08 · `bank_audit_r3/` · as-found k = 11)
# ──────────────────────────────────────────────────────────────────────────
_C03: Final = "[12미적Ⅰ-02-03]"
#: 거듭제곱 미분의 두 대표 오답 경로를 오답 선지로 거는 kebab(정본 L4 카탈로그 · M0671).
_POWER_RULE_KEBAB: Final = "power-rule-step-omitted"
#: 거듭제곱 미분의 두 대표 오답 경로 — (x^n)' = x^(n - 1)(계수 누락) · (x^n)' = n·x^n(지수 유지).
_POWER_PATHS: Final = ("계수 누락", "지수 유지")


def _tangent_curve_degree(question: str) -> int | None:
    """발문에 보이는 x의 다항식 중 최고 차수 — 접선 문항의 곡선(직선·좌표는 차수가 낮아 묻힌다)."""
    x = sympy.Symbol("x")
    degrees = [
        int(sympy.degree(p, x)) for p in visible_polynomials(question) if x in p.free_symbols
    ]
    return max(degrees) if degrees else None


def _quadratic_slope_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] (02-05) 접선의 기울기·접점을 미분 평가로 정하는데 발문의 곡선이 이차 이하다.

    이차곡선 y = Ax^2 + bx + c와 기울기 m인 직선 y = mx + n을 연립한 이차방정식이 중근을 가질
    조건(판별식 = 0)에서 그 중근 x = (m - b)/(2A)가 곧 접점이다 — 미분 없이 기울기 → 접점(기울기가
    주어진 값·평행·수직)이 나오고(판정자 지적 4d287bbd·1006bee0·5209729b·ac28058d·ee5a4588), 같은
    중근 조건이 접점 → 기울기(m = 2Aa + b)도 준다. 5회차 `T05-quadratic-tangent-constant`는 검산에
    미분이 *없는*(판별식형) y절편 틀만 덮었다.

    곡선은 발문에서 읽는다 — 검산 조건의 미분 몸통은 Tier1 표기 제약으로 합성된 식(f(x + d) - f(x)
    등)이라 곡선의 차수와 다를 수 있다. 절 둘: (가) 접점이 미지수(미분 평가점이 문자) · (나)
    기울기를 구한다(미분 평가점이 수).
    """
    if "접" not in probe.question_text:
        return []
    degree = _tangent_curve_degree(probe.question_text)
    if degree is None or degree > 2:
        return []
    clauses: set[str] = set()
    for condition in probe.conditions:
        for call in _derivative_calls(condition):
            if call.order != 1 or "Derivative" in call.body:
                continue
            numeric = call.point is not None and _rational(call.point) is not None
            clauses.add("기울기" if numeric else "접점")
    out: list[ShortcutViolation] = []
    if "접점" in clauses:
        out.append(
            ShortcutViolation(
                "T05-quadratic-slope",
                "곡선이 이차 이하인데 접선의 기울기(주어진 값·평행·수직)로 접점을 구하게 한다 — 그 "
                "기울기의 직선과 연립한 이차방정식의 중근(판별식 = 0)이 곧 접점이라 미분 없이 "
                "풀린다. 곡선을 삼차 이상으로 쓴다.",
            )
        )
    if "기울기" in clauses:
        out.append(
            ShortcutViolation(
                "T05-quadratic-slope",
                "곡선이 이차 이하인데 접점에서의 접선의 기울기를 구하게 한다 — 접선과 연립한 "
                "이차방정식이 그 점에서 중근을 가질 조건(근과 계수의 관계)으로 미분 없이 기울기가 "
                "나온다. 곡선을 삼차 이상으로 쓴다.",
            )
        )
    return out


def power_path_derivative(expr: sympy.Expr, var: sympy.Symbol, path: str) -> sympy.Expr | None:
    """거듭제곱 미분의 대표 오답 경로로 '미분한' 식(생성기·판정기 단일 원천).

    `path`가 '계수 누락'이면 c·x^e → c·x^(e - 1), '지수 유지'면 c·x^e → e·c·x^e. 항마다 c·var^e
    꼴로 읽어 지수 e가 문자여도 된다(x^n). 상수항은 두 경로 모두 지운다(상수의 미분은 오개념과
    무관하다). c·var^e 꼴이 아닌 항이 있으면 None.
    """
    out = sympy.Integer(0)
    for term in sympy.Add.make_args(sympy.expand(expr)):
        coeff, exponent = term.as_coeff_exponent(var)
        if var in coeff.free_symbols:
            return None
        if exponent == 0:
            continue
        if path == "계수 누락":
            out += coeff * var ** (exponent - 1)
        elif path == "지수 유지":
            out += exponent * coeff * var**exponent
        else:  # pragma: no cover — 호출 오류
            raise ValueError(f"알 수 없는 경로: {path}")
    return sympy.expand(out)


def _path_solutions(
    eq: sympy.Expr, var: sympy.Symbol, filters: Sequence[_Relation]
) -> set[sympy.Expr]:
    """오답 경로 방정식의 해 — var가 지수에 들면(x^n의 n) 0..30의 정수를 대입해 찾는다.

    거듭제곱의 지수 n은 자연수라 정수 탐색이 해 전부다(초월방정식을 SymPy로 풀지 않는다).
    """
    if eq.free_symbols != {var}:
        return set()
    if eq.is_polynomial(var):
        return _solutions(eq, var, filters)
    return {
        sympy.Integer(k)
        for k in range(31)
        if sympy.simplify(eq.subs(var, k)) == 0 and _passes(sympy.Integer(k), filters)
    }


def _is_power_monomial_body(body: sympy.Expr, var: sympy.Symbol) -> bool:
    """미분하는 식이 상수항을 빼면 거듭제곱 하나(c·x^n · n ≥ 2 또는 문자 지수)인가 — '거듭제곱
    미분계수'(2x^3 - 5의 도함수는 6x^2 하나라 미분 단계가 곧 거듭제곱 미분이다)."""
    terms = [t for t in sympy.Add.make_args(sympy.expand(body)) if var in t.free_symbols]
    if len(terms) != 1:
        return False
    coeff, exponent = terms[0].as_coeff_exponent(var)
    if var in coeff.free_symbols or exponent == 0:
        return False
    return bool(exponent.free_symbols) or bool(exponent >= 2)


def _power_scope(probe: ShortcutProbe, body: sympy.Expr, var: sympy.Symbol) -> bool:
    """거듭제곱 미분이 *검사 대상*인 문항 — 02-03(x^n의 도함수)·그 오개념을 건 오답 선지·몸통이
    거듭제곱 하나인 미분계수. 02-04(합·곱의 미분법)처럼 거듭제곱 미분이 선수 지식인 문항의 f'(0)·
    f'(1) 읽기는 보지 않는다(정직 범위 — 그 개념의 검사 대상이 아니다)."""
    if probe.standard_code == _C03:
        return True
    if any(mid == _POWER_RULE_KEBAB for _, mid in probe.distractors):
        return True
    return _is_power_monomial_body(body, var)


def _evaluated_path_hits(probe: ShortcutProbe) -> list[str]:
    """평가 절 — 미분 평가를 오답 경로 도함수로 바꿔 풀어도 정답과 같은 해 하나가 나오는 경로."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    hits: list[str] = []
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or "Derivative" in call.body:
            continue
        body = _sym(call.body)
        v = sympy.Symbol(call.var)
        point = v if call.point is None else _sym(call.point)
        if body is None or point is None or not _power_scope(probe, body, v):
            continue
        for path in _POWER_PATHS:
            wrong = power_path_derivative(body, v, path)
            if wrong is None or sympy.simplify(wrong - sympy.diff(body, v)) == 0:
                # 그 경로가 이 함수에서는 오답이 아니다(f(x) = x의 계수 누락 x^0 = 1은 참 도함수다)
                continue
            eq = sympy.expand(wrong.subs(v, point) - rel.other)
            if var in eq.free_symbols and _path_solutions(eq, var, filters) == {answer}:
                hits.append(f"{path} 경로({call.var}에서의 값)")
    return hits


#: 도함수 꼴 읽기 — 발문의 거듭제곱 함수와 도함수 꼴 'cx^m'·'kx^m'.
_FORM_FUNCTION = re.compile(
    r"(?:(?<![A-Za-z'])[a-z]\((?P<v>[xt])\)|(?<![A-Za-z'])y) = (?P<c>-?\d*)(?P<v2>[xt])\^(?P<n>\d+)"
    r"(?![\d^])"
)
_FORM_SHAPE = re.compile(r"(?<![A-Za-z'])(?P<k>[ck])(?P<v>[xt])\^m(?![A-Za-z])")
#: 주어진 도함수 꼴 — 'f(x) = x^n'(문자 지수)와 "f'(x) = 5x^4"·"f'(x) = kx^5".
_SYMBOLIC_POWER = re.compile(
    r"(?:(?<![A-Za-z'])[a-z]\([xt]\)|(?<![A-Za-z'])y) = (?P<v>[xt])\^(?P<e>[a-z])(?![A-Za-z])"
)
_GIVEN_FORM = re.compile(
    r"(?<![A-Za-z'])[a-z]'\((?P<v>[xt])\) = (?P<g>-?\d+|[a-z]|)(?P=v)\^(?P<m>\d+)(?![\d^])"
)


def _asked_form_value(
    question: str, letter: str, coef: sympy.Expr, exponent: sympy.Expr
) -> sympy.Expr | None:
    """발문이 묻는 도함수 꼴의 값 — 'c + m'·'c와 m의 곱'('cm')·'c'('계수 c')·'m'(그 순서로 본다)."""
    k = re.escape(letter)
    if re.search(rf"{k} \+ m(?:의 값|[을를])|m \+ {k}(?:의 값|[을를])", question):
        return coef + exponent
    if re.search(rf"{k}와 m의 곱|{k}m의 값|m{k}의 값", question):
        return coef * exponent
    if re.search(rf"(?<![A-Za-z]){k}의 값|계수 {k}[를을]", question):
        return coef
    if re.search(r"(?<![A-Za-z])m의 값", question):
        return exponent
    return None


def _form_path_hits(probe: ShortcutProbe) -> list[str]:
    """꼴 읽기 절 — 도함수를 c·x^m 꼴로 읽는 문항에서 오답 경로의 c·m으로도 정답이 나오는가.

    (가) '거듭제곱 함수의 도함수를 cx^m 꼴로 나타낼 때 c(m)의 값' — 지수 유지(n·x^n)는 c를, 계수
    누락(x^(n - 1))은 m을 늘 맞힌다(판정자 지적 76a9f5ac — x^8 → c = 8). (나) '도함수가
    f'(x) = 5x^4일 때 n' — 계수 누락은 지수 비교로, 지수 유지는 계수 비교로 n을 맞힌다.
    """
    q = probe.question_text
    answer = _answer_value(probe)
    if answer is None:
        return []
    hits: list[str] = []
    shape = _FORM_SHAPE.search(q)
    function = _FORM_FUNCTION.search(q)
    if shape is not None and function is not None:
        raw = function.group("c")
        lead = sympy.Integer(1 if raw in ("", None) else (-1 if raw == "-" else int(raw)))
        n = sympy.Integer(function.group("n"))
        paths = {"계수 누락": (lead, n - 1), "지수 유지": (lead * n, n)}
        for path, (coef, exponent) in paths.items():
            value = _asked_form_value(q, shape.group("k"), coef, exponent)
            if value is not None and value == answer:
                hits.append(f"{path} 경로(도함수 꼴 읽기)")
    symbolic, given = _SYMBOLIC_POWER.search(q), _GIVEN_FORM.search(q)
    if symbolic is not None and given is not None:
        letter = symbolic.group("e")
        m = sympy.Integer(given.group("m"))
        g = given.group("g")
        asked = str(_answer_var(probe) or "")
        wrong: dict[str, set[sympy.Expr]] = {"계수 누락": set(), "지수 유지": set()}
        if asked == letter:
            # 계수 누락 x^(n - 1): 지수 비교 n - 1 = m · 지수 유지 n·x^n: 지수 비교 n = m, 계수 비교
            # n = g
            wrong["계수 누락"].add(m + 1)
            wrong["지수 유지"].add(m)
            if re.fullmatch(r"-?\d+", g):
                wrong["지수 유지"].add(sympy.Integer(g))
        elif re.fullmatch(r"[a-z]", g) and asked == g:
            # 계수 누락이면 n = m + 1이고 계수는 1 · 지수 유지면 n = m이고 계수는 m
            wrong["계수 누락"].add(sympy.Integer(1))
            wrong["지수 유지"].add(m)
        hits += [
            f"{path} 경로(주어진 도함수 꼴 비교)" for path, vals in wrong.items() if answer in vals
        ]
    return hits


def _power_path_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] 거듭제곱 미분의 두 대표 오답 경로 중 하나라도 정답과 같은 값을 낸다.

    판정자 지적 3건 중 2건 — f(x) = x^2의 f'(1)(x = 1이면 지수 유지 n·x^n도 같은 값 · cbde3ec3)·
    x^8의 도함수 cx^m의 c(지수 유지 8x^8도 c = 8 · 76a9f5ac). 거듭제곱 미분이 검사 대상인 문항
    (`_power_scope`)에서 평가 절(미분 평가를 오답 경로 도함수로 바꿔 푼 해가 정답 하나)과 꼴 읽기
    절(도함수를 c·x^m 꼴로 읽는 문항)을 본다. 매개변수 거부 조건이다(x = 1·x = 0 같은 평가점은
    파라미터 선택이다) — 꼴 읽기 절은 틀 자체가 늘 걸리므로 생성기가 묻는 값을 c + m 등으로 바꾼다.
    """
    hits = _evaluated_path_hits(probe) + _form_path_hits(probe)
    if not hits:
        return []
    return [
        ShortcutViolation(
            "T-power-path-coincidence",
            f"거듭제곱 미분의 대표 오답 경로({', '.join(sorted(set(hits)))})로 풀어도 정답 "
            f"{probe.answer.strip()}이(가) 나온다 — 지수를 내리는 단계·1 줄이는 단계 중 하나를 "
            "빠뜨린 학생도 맞힌다(변별 없음). 그 매개변수를 쓰지 않는다.",
        )
    ]


def _named_functions(question: str, var: str) -> list[tuple[str, sympy.Expr]]:
    """발문이 이름을 붙여 보여 주는 다항함수 'f(x) = …'·'g(x) = …'(var만의 수치 다항식)."""
    v = sympy.Symbol(var)
    out: list[tuple[str, sympy.Expr]] = []
    for m in _DEFINITION.finditer(question):
        if m.group("arg") != var or m.group("name") == var:
            continue
        rhs = _clean_rhs(m.group("rhs"), var)
        if re.search(r"[a-z]\(", rhs):
            continue  # 'h(x) = 2f(x) - 3g(x)'(추상 함수 결합)는 성분이 아니라 결합이다
        expr = _parse_student(rhs)
        if expr is not None and expr.free_symbols == {v}:
            out.append((m.group("name"), sympy.expand(expr)))
    return out


def _combination_weights(
    body: sympy.Expr, components: Sequence[sympy.Expr], var: sympy.Symbol
) -> list[sympy.Expr] | None:
    """body = Σ αᵢ·성분ᵢ(αᵢ 상수)의 계수 — 성분의 일차결합이 아니거나 계수가 하나로 정해지지 않으면
    None."""
    weights = sympy.symbols(f"w0:{len(components)}")
    gap = sympy.expand(body - sum(w * c for w, c in zip(weights, components, strict=True)))
    equations = sympy.Poly(gap, var).coeffs() if gap != 0 else []
    try:
        solved = sympy.solve(equations, list(weights), dict=True)
    except (NotImplementedError, ValueError, TypeError):
        return None
    if len(solved) != 1 or any(w not in solved[0] for w in weights):
        return None
    values = [solved[0][w] for w in weights]
    return None if any(v.free_symbols for v in values) else values


def _component_critical_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] 합·차·실수배의 미분계수인데 평가점이 한 성분 함수의 임계점이다(성분 도함수가 0).

    h(x) = 2f(x) - 3g(x)의 h'(-1)에서 g'(-1) = 0이면 -3g 항의 기여가 0이라, 실수배·차의 처리를 g
    쪽에서 틀려도(부호를 +로 · 계수 3을 빠뜨려) 모두 정답이 나온다(판정자 지적 0bcf3427). 미분하는
    식이 발문이 이름 붙여 보인 함수들의 *일차결합*(계수 0이 아닌 성분 둘 이상)일 때만 본다 — 곱의
    미분법은 성분 도함수가 0이어도 다른 성분의 함숫값이 곱해져 남는다(대상 아님).
    """
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or "Derivative" in call.body:
            continue
        point, body = _rational(call.point), _sym(call.body)
        v = sympy.Symbol(call.var)
        if point is None or body is None or body.free_symbols != {v}:
            continue
        named = _named_functions(probe.question_text, call.var)
        if len(named) < 2:
            continue
        weights = _combination_weights(body, [expr for _, expr in named], v)
        if weights is None or sum(1 for w in weights if w != 0) < 2:
            continue
        flat = [
            name
            for (name, expr), w in zip(named, weights, strict=True)
            if w != 0 and sympy.diff(expr, v).subs(v, point) == 0
        ]
        if flat:
            return [
                ShortcutViolation(
                    "T-component-critical-point",
                    f"평가점 {call.var} = {point}에서 성분 함수 {', '.join(flat)}의 도함수가 "
                    "0이다 — 그 성분의 실수배·부호 처리를 틀려도 정답이 같다(변별 없음). 어느 "
                    "성분의 도함수도 평가점에서 0이 아닌 매개변수를 쓴다.",
                )
            ]
    return []


#: 미분 차수 → 혼동하기 쉬운 양의 차수(속도↔위치·가속도 · 가속도↔속도 — 고등 운동 문항의 혼동).
_CONFUSABLE_ORDERS: Final[dict[int, tuple[int, ...]]] = {1: (0, 2), 2: (1,)}
_QUANTITY_NAMES: Final[dict[int, str]] = {0: "위치", 1: "속도", 2: "가속도"}


def _confusable_quantity_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] (02-10) 묻는 양과 혼동하기 쉬운 양(속도↔가속도·위치↔속도)이 같은 시각에 같은 값이다.

    '가속도가 0이 되는 시각의 속도'에서 위치가 (t - 1)^3 + c 꼴이면 그 시각의 속도도 0이라, 속도와
    가속도를 혼동한 경로·조건값 0을 옮겨 적는 경로가 정답이다(판정자 지적 30d80000). 미분하는 식이
    발문의 위치 다항식 그대로일 때만 본다(속도의 합·변화량처럼 합성된 검산식은 학생의 양이 아니다).
    """
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    for rel in _main_relations(probe):
        call = rel.call
        if call.point is None or "Derivative" in call.body:
            continue
        body, point = _sym(call.body), _sym(call.point)
        if body is None or point is None or not _is_shown(body, probe.question_text, call.var):
            continue
        v = sympy.Symbol(call.var)
        for order in _CONFUSABLE_ORDERS.get(call.order, ()):
            quantity = body if order == 0 else sympy.diff(body, v, order)
            eq = sympy.expand(quantity.subs(v, point) - rel.other)
            if var in eq.free_symbols and _solutions(eq, var, filters) == {answer}:
                asked = _QUANTITY_NAMES[call.order]
                other = _QUANTITY_NAMES[order]
                return [
                    ShortcutViolation(
                        "T10-confusable-quantity",
                        f"묻는 양({asked})을 {other}로 혼동해 구해도 같은 답 {answer}이 나온다 — "
                        f"{asked}와 {other}를 구별하지 못하는 학생도 맞힌다(변별 없음). 그 "
                        "매개변수를 쓰지 않는다.",
                    )
                ]
    return []


#: 운동 기호를 *주어 자리에서* 소개하는 정의 — '속도 v(t)는 위치 x를 시각 t로 미분한 값'.
_V_SUBJECT = re.compile(r"(?<!가)속도 v\(t\)는[^.]*?위치[^.]*?(?:미분한 값|도함수)")
_A_SUBJECT = re.compile(r"가속도 a\(t\)는[^.]*?속도[^.]*?(?:미분한 값|도함수)")


def motion_symbols_not_in_subject(explanation: str) -> tuple[str, ...]:
    """해설이 주어 자리에서 소개하지 않는 운동 기호 — v(t)·a(t)의 *첫 등장*이 '속도 v(t)는 …
    미분한 값'(가속도도 같다)의 그 기호여야 한다(생성기와 판정기 `E-motion-symbol-subject`의 단일
    원천).

    6회차 `undefined_motion_symbols`는 '속도는 위치를 미분한 값이다. v(t) = …'처럼 정의 문장이
    기호보다 앞서기만 하면 통과시킨다 — 그 형태는 기호 v(t)를 소개하지 않는다(판정자 지적 fb9ec6bc).
    """
    out: list[str] = []
    for symbol, pattern, word in (("v(t)", _V_SUBJECT, "속도 "), ("a(t)", _A_SUBJECT, "가속도 ")):
        first = explanation.find(symbol)
        if first < 0:
            continue
        match = pattern.search(explanation)
        if match is None or match.start() + len(word) != first:
            out.append(symbol)
    return tuple(out)


def _motion_subject_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] v(t)·a(t)를 '속도 v(t)는 …'처럼 주어 자리에서 소개하지 않는다."""
    out: list[ShortcutViolation] = []
    for symbol in motion_symbols_not_in_subject(probe.explanation):
        word = "속도 v(t)는 위치 x를" if symbol == "v(t)" else "가속도 a(t)는 속도 v(t)를"
        out.append(
            ShortcutViolation(
                "E-motion-symbol-subject",
                f"해설이 {symbol}를 기호로 소개하지 않고 쓴다 — 첫 문장을 '{word} 시각 t로 미분한 "
                f"값이므로 {symbol} = …'처럼 기호를 주어 자리에 두어 소개한다.",
            )
        )
    return out


#: 함수 표기 L(수)·L(문자)·L'(…) — 'x(5)'·"f'(3)"(곱 '2x(x + 3)'은 인자가 식이라 잡지 않는다).
_CALL_NOTATION = re.compile(r"(?<![A-Za-z'])([a-z])'*\((-?\d+(?:/\d+)?|[a-z])\)")


def _introduces(explanation: str, letter: str, before: int) -> bool:
    """해설이 `before` 이전(또는 그 자리)에서 letter를 함수로 소개하는가('f(x)라 하자'·
    'h(x) = … 이라 하자'·"f'(x)라 하면")."""
    k = re.escape(letter)
    patterns = (
        rf"(?<![A-Za-z']){k}'*\([a-z]\)\s*(?:이라|라|로)\s*(?:하|두|놓)",
        rf"(?<![A-Za-z']){k}\([a-z]\)\s*=\s*[^.]*?(?:이라|라)\s*(?:하|두|놓)",
    )
    return any(
        m is not None and m.start() <= before for m in (re.search(p, explanation) for p in patterns)
    )


def _function_notation_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] 해설이 발문에 없는 함수 표기('x(5)')를 소개 없이 쓴다.

    발문은 '위치가 x = 2t^2 - 6t + 5'로 x를 *변수*로만 쓰는데 해설이 'x(5) = 25'처럼 함수 표기를
    쓴다(판정자 지적 fb9ec6bc). 운동 기호 v(t)·a(t)는 운동 기호 규칙이 따로 본다.
    """
    q, e = probe.question_text, probe.explanation
    motion = "속도" in e or "속도" in q
    seen: set[str] = set()
    for m in _CALL_NOTATION.finditer(e):
        letter = m.group(1)
        if letter in seen or (motion and letter in ("v", "a")):
            continue
        seen.add(letter)
        if re.search(rf"(?<![A-Za-z']){re.escape(letter)}'*\(", q):
            continue
        if _introduces(e, letter, m.start()):
            continue
        return [
            ShortcutViolation(
                "E-function-notation",
                f"해설이 발문에 없는 함수 표기 '{m.group(0)}'를 소개 없이 쓴다 — 't = 5일 때의 "
                "위치'처럼 말로 풀어 쓰거나 먼저 기호를 정의한다.",
            )
        ]
    return []


#: 증가·감소가 바뀌는 점을 묻는 발문(극값 어휘 없이).
_TURNING_TARGET = re.compile(r"증가·감소가 바뀌는|증가하다가 감소|감소하다가 증가")
_EXTREMUM_WORD = re.compile(r"극값|극대|극소")


def _conclusion_target_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[7회차] (02-08) 해설의 결론 문장이 발문이 묻는 대상과 어긋난다.

    절 둘: (가) 발문은 '증가·감소가 바뀌는 점'을 묻는데 결론은 '극값을 갖는 x좌표'로 맺는다(판정자
    지적 b2d3bc4b) · (나) 결론 문장에 정답이 없다(상수 a를 묻는데 'x = 3에서 극솟값을 갖는다'로
    맺는 검산 문장 — 결론이 묻는 대상을 말하지 않는다).
    """
    sentences = _sentences(probe.explanation)
    if not sentences:
        return []
    last, q = sentences[-1], probe.question_text
    out: list[ShortcutViolation] = []
    if (
        _TURNING_TARGET.search(q)
        and not _EXTREMUM_WORD.search(q)
        and _EXTREMUM_WORD.search(last)
        and "바뀌" not in last
    ):
        out.append(
            ShortcutViolation(
                "E-conclusion-target",
                "발문은 증가·감소가 바뀌는 점을 묻는데 해설의 결론은 극값(극대·극소)으로 맺는다 — "
                "'증가·감소가 바뀌는 점의 x좌표는 …'처럼 발문의 대상으로 맺는다.",
            )
        )
    answer = probe.answer.strip()
    if _rational(answer) is not None and answer not in set(_NUMBER_TOKEN.findall(last)):
        out.append(
            ShortcutViolation(
                "E-conclusion-target",
                f"해설의 결론 문장('{last[:40]}…')이 발문이 묻는 값 {answer}을 말하지 않는다 — "
                "마지막 문장을 묻는 대상의 값으로 맺는다.",
            )
        )
    return out


def _round7_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """7회차 규칙 전부(성취기준별 분기 포함)."""
    code = probe.standard_code
    out = (
        _power_path_rule(probe)
        + _component_critical_rule(probe)
        + _motion_subject_rule(probe)
        + _function_notation_rule(probe)
    )
    if code == _C05:
        out += _quadratic_slope_rule(probe)
    if code == _C08:
        out += _conclusion_target_rule(probe)
    if code == _C10:
        out += _confusable_quantity_rule(probe)
    return out


def parameter_coincidences(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """매개변수 선택의 우연 일치 위반만(`COINCIDENCE_RULE_IDS`) — 생성기의 매개변수 거부 조건."""
    return [
        v
        for v in _round5_rules(probe) + _round6_rules(probe) + _round7_rules(probe)
        if v.rule in COINCIDENCE_RULE_IDS
    ]


def shortcut_violations(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """문항 1건의 우회로·해설·표기 위반 목록 — 빈 리스트면 통과."""
    out = _notation_rules(probe) + _explanation_rules(probe) + _zero_monomial_rule(probe)
    code = probe.standard_code
    if code == _C05:
        out += _tangent_rules(probe)
    if code in (_C05, _C08):
        out += _value_determines_rule(probe)
    if code == _C06:
        out += _mvt_rules(probe)
    if code == _C08:
        out += _graph_shape_rules(probe) + _graph_shape_round4_rules(probe)
    if code == _C09:
        out += _equation_rules(probe) + _application_rule(probe)
    if code == _C10:
        out += _velocity_rules(probe)
    return out + _round5_rules(probe) + _round6_rules(probe) + _round7_rules(probe)


def violations_by_rule(probes: Sequence[ShortcutProbe]) -> dict[str, int]:
    """표본 묶음의 규칙별 위반 문항 수(보고용) — 한 문항이 같은 규칙을 여러 번 어겨도 1로 센다."""
    counts: dict[str, int] = {rule: 0 for rule in RULE_IDS}
    for probe in probes:
        for rule in {v.rule for v in shortcut_violations(probe)}:
            counts[rule] += 1
    return counts
