# EOS-129 ⑤ — 운영 DB 문항당 응답 수 실측 런북 (읽기 전용)

> 게이트: `G-eos129-prod-response-distribution` · 태스크: `EOS-129-irt-discrimination-calibration` acceptance ⑤
> 작성: 2026-09-28 · 판정 기준 main `919865d4`

## 왜 필요한가

`EOS-129`는 문항 변별도 a를 응답 데이터로 추정(2PL 보정)해 CAT 진단의 SE 0.3 도달 문항 수를
줄이는 태스크다. acceptance ⑤는 **착수 전에** 운영 코퍼스의 문항당 응답 분포를 실측해
"a를 추정할 수 있는 문항이 몇 건인가"를 먼저 적으라고 요구한다 — 0건에 가까우면 이 태스크는
데이터 축적 대기이며, 그 사실 자체가 산출물이다.

세션(클라우드)은 운영 DB에 닿을 수 없다. 저장소에 남은 관측은 "`problem_attempt` 0행"
(2026-08-03)뿐인데, 그 뒤 같은 영역에 태스크가 착지해 낡은 관측이다(MEMORY 2026-09-03
"증거의 신선도" 교훈). 그래서 Kiki 머신에서 한 번 실측한다.

기준값(코드 실측):

- b(난이도) 보정 최소 응답 수 = 5 (`l2/item_calibration.py::_MIN_RESPONSES_FOR_CALIBRATION`)
- a(변별도)는 b보다 훨씬 많은 응답이 필요하다. 임계값은 이 실측 결과를 보고 EOS-129가 정한다
  (IRT 문헌의 관례는 문항당 수백 명 수준이며, 이 저장소에서는 아직 측정된 적이 없다)

## Kiki 실행 안내

1. **과제 명칭**: 운영 DB 문항당 응답 수 분포 실측
2. **목적**: 변별도 a를 추정할 만큼 응답이 쌓인 문항이 몇 건인지 알아낸다. 결과가 EOS-129를
   지금 구현할지, 데이터가 쌓일 때까지 기다릴지를 정한다.
3. **구체적 절차**: 아래 블록을 통째로 붙여넣는다. ① 운영 DB 컨테이너가 떠 있는지 확인
   ② 전체 문항 수·채점된 응답 수·응답이 있는 문항 수·학생 수 조회 ③ 문항당 응답 수 구간별 문항 수
   조회. 전부 SELECT라 DB를 바꾸지 않는다. 몇 초 걸린다.
4. **성공 기준**: 첫 줄에 `whymath-pg Up …`이 보이고, 그 아래 표 2개가 나오면 성공이다.
   첫 줄이 비어 있으면 운영 DB 컨테이너가 꺼져 있는 것이다 — Docker Desktop을 켠 뒤 다시 붙여넣는다.
   표 2개를 그대로 복사해 세션에 전달하면 세션이 게이트를 닫고 판정을 이어간다.
5. **실행 환경**: Phaiakes9의 Windows PowerShell · 작업 디렉터리
   `C:\Users\kiki\Desktop\__AI\WhyMath` · 선행 조건: Docker Desktop 실행 중.
6. **창 구분**: 새 PowerShell 창 하나. 서버를 띄우지 않으므로 실행 후에도 그 창을 계속 써도 된다.

```powershell
# [Windows PowerShell · Phaiakes9] EOS-129 ⑤ 운영 DB 문항당 응답 수 분포 — 읽기 전용(SELECT만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker ps --filter "name=whymath-pg" --format "{{.Names}} {{.Status}}"
docker exec whymath-pg psql -U whymath -d whymath -c "SELECT (SELECT count(*) FROM problem) AS problems, count(*) AS graded_attempts, count(DISTINCT problem_id) AS items_with_responses, count(DISTINCT user_id) AS students FROM problem_attempt WHERE is_correct IS NOT NULL AND user_id IS NOT NULL AND problem_id IS NOT NULL;"
docker exec whymath-pg psql -U whymath -d whymath -c "SELECT CASE WHEN n >= 200 THEN '6: 200+' WHEN n >= 100 THEN '5: 100-199' WHEN n >= 20 THEN '4: 20-99' WHEN n >= 5 THEN '3: 5-19' ELSE '2: 1-4' END AS responses_per_item, count(*) AS items FROM (SELECT problem_id, count(*) AS n FROM problem_attempt WHERE is_correct IS NOT NULL AND user_id IS NOT NULL AND problem_id IS NOT NULL GROUP BY problem_id) t GROUP BY 1 ORDER BY 1;"
```

## 결과 해석 (세션이 판정한다)

- `graded_attempts`가 0이거나 모든 문항이 `2: 1-4`·`3: 5-19` 구간이면 → a 추정 가능 문항 ≈ 0건.
  EOS-129는 **데이터 축적 대기**로 결론 내고, 재측정 시점을 게이트 노트에 남긴다.
- `5: 100-199`·`6: 200+` 구간에 문항이 있으면 → 그 문항들로 2PL 보정(acceptance ③)을 착수한다.
- 두 번째 표에 응답이 없는 문항은 나오지 않는다 — 응답 0건 문항 수는
  `problems - items_with_responses`로 계산한다.
