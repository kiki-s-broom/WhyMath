# 잔여 축 교차검증 게이트 강등전 — 1차 실측 기록 (S4-16, 2026-08-10)

> **판정: 게이트 패배 — 인간 검수 대체 승격 기각.** K=3 교차검증 게이트(`residue_cross_verify_eval`,
> S4-13 배선)는 주입 결함 12건 중 **2건(16.7%)** 만 검출했다(95% Wilson 단측 하한 5.68%·상한 ≈40%).
> 어떤 합리적 승격 기준(통상 90%+)에도 미달하며, 표본이 작아도 이 결론은 견고하다 — 상한조차
> 승격 바에 닿지 않는다. 파일럿 코퍼스 `problem_bank_probability_finite_v0`(34문)는
> **`is_published=False`(인간 검수 필수) 유지**. `docs/standards/superhuman_verification_standard.md`
> 검증 권위 서열의 원칙 그대로: 측정이 증명하지 못한 게이트는 승격되지 않는다.

## 실행 조건 (재현 정보)

| 항목 | 값 |
|---|---|
| 실행 일시 | 2026-08-09 야간 → 08-10 (총 **11h 36m 38s**) |
| 머신 | Phaiakes9 — GMKtec(NucBox EVO-X2급) Ryzen AI Max+ 395 · Radeon 8060S iGPU(100% GPU) · 통합 LPDDR5X |
| 모델 | `qwen3.5:27b`(추론형·thinking 활성) — `num_ctx` 262144→**8192** 조정본 |
| 하네스 | `harness/residue_gate_demotion_battle.py` @ `d6b77a9e` |
| 호출 | `--sample-n 3` · seed `S4-16` · 총 45콜(seeded 12×3관점 + clean 3×3관점) |
| 타임아웃 | `WHYMATH_OLLAMA_REQUEST_TIMEOUT_S=900` — **판정불가: seeded 0/12 · clean 1/3** (900s에서 타임아웃 사실상 해소) |
| 콜당 평균 | ≈15.5분(11.6h/45콜) — `adversarial_falsification` 관점이 최장(180s에서 25/25 전멸·300s에서 4/5 타임아웃 이력) |
| 원자료 | `battle_audit_night.jsonl`(Kiki 머신 repo 루트 — 항목별 판정·as-found 요약) |

## 리포트 원문 (2026-08-10)

```
[커버리지 - 코퍼스 전체(34건) 기준 결함류별 적용 가능 건수]
  missing_condition          25/34건 적용 가능
  unstated_equiprobability   20/34건 적용 가능
  ambiguous_wording          26/34건 적용 가능
  multiple_valid_answers     6/34건 적용 가능
[결함류별 검출 - 실 표본(95% Wilson 하한)]
  missing_condition          표본 3건 판정 3건 검출 0건  하한 0.0000  판정불가 0건
  unstated_equiprobability   표본 3건 판정 3건 검출 0건  하한 0.0000  판정불가 0건
  ambiguous_wording          표본 3건 판정 3건 검출 1건  하한 0.0783  판정불가 0건
  multiple_valid_answers     표본 3건 판정 3건 검출 1건  하한 0.0783  판정불가 0건
[전체]
  결함 검출률   : 2/12 (95% 하한 0.0568)  판정불가 0건
  무결함 오검출 : 0/2 (95% 상한 0.5750)  판정불가 1건
```

## 해석

1. **조건 결측 계열에 사실상 실명(失明)** — `missing_condition`(구별 가능 전제 소실)·
   `unstated_equiprobability`(등확률 미서술) 검출 **0/3 + 0/3**. 검증 대상 조립이 원본 기계 모델
   서술(`machine_model_ko`)을 함께 제공하므로 "발문에 그 전제가 더 이상 없다"는 불일치를 잡아야
   하는데, 세 관점 모두 놓쳤다. 한국 교육과정 관례상 암묵 전제로 취급되는 표현이라 모델이 결측을
   결함으로 보지 않았을 가능성이 크다.
2. **중의성·복수 정답은 부분 검출** — 각 1/3. 방향은 맞으나 승격 수준이 아니다.
3. **오검출률 보정(`--max-defect-upper`) 불가** — 대조군 판정 표본 **n=2**(1건 판정불가)로,
   Wilson 상한 0.575는 표본 부족의 인공물이다. acceptance가 요구한 "0.05 기본값의 실측 보정"은
   대조군 n≥20 확보 전에는 수행 불가(기존 `residue_cross_verify_eval --min-n 20` 기준과 정합).
   현행 0.05는 **미검증 초기값** 상태로 남는다.
4. **로컬 실행 경제성** — 콜당 ≈15.5분. 대조군 20건 보정 측정만 ≈15h. 야간 배치로는 가능하나
   반복 실험 사이클로는 무겁다.

## 판정과 효력

- **인간 검수 대체 승격: 기각.** 이 경로(잔여 축 K=3 교차검증)는 현행 구성으로 검수 게이트가
  될 수 없다. 파일럿 코퍼스 노출 게이팅은 종전대로 인간 검수를 요구한다.
- 승격 재도전은 검증기 개선 후 **재강등전 승리**로만 가능하다(아래 후속 방향). S4-16 acceptance의
  "Wilson 게이트 CLI PASS"는 미충족 — 태스크는 개선·재도전 컨테이너로 열린 채 유지한다.

## 부록 — 항목별 원자료 (`battle_audit_night.jsonl` 전문)

```jsonl
{"problem_id": "wm-finite-bf467bc92512", "role": "seeded", "defect_class": "missing_condition", "mutation_note": "조건 결측: '서로 구별되는 ' 제거(구별 가능 전제 소실)", "aggregate": "ok"}
{"problem_id": "wm-finite-53bcd6a36208", "role": "seeded", "defect_class": "missing_condition", "mutation_note": "조건 결측: '서로 구별되는 ' 제거(구별 가능 전제 소실)", "aggregate": "ok"}
{"problem_id": "wm-finite-2457627c3b5d", "role": "seeded", "defect_class": "missing_condition", "mutation_note": "조건 결측: '서로 구별되는 ' 제거(구별 가능 전제 소실)", "aggregate": "ok"}
{"problem_id": "wm-finite-162069932205", "role": "seeded", "defect_class": "unstated_equiprobability", "mutation_note": "등확률 미명시: '매번 앞면과 뒷면이 나올 가능성이 같을 때, ' 제거(균등분포 가정 미서술)", "aggregate": "ok"}
{"problem_id": "wm-finite-53bcd6a36208", "role": "seeded", "defect_class": "unstated_equiprobability", "mutation_note": "등확률 미명시: '각 주사위의 여섯 눈이 나올 가능성이 모두 같을 때, ' 제거(균등분포 가정 미서술)", "aggregate": "ok"}
{"problem_id": "wm-finite-c49dec23e37c", "role": "seeded", "defect_class": "unstated_equiprobability", "mutation_note": "등확률 미명시: '매번 앞면과 뒷면이 나올 가능성이 같을 때, ' 제거(균등분포 가정 미서술)", "aggregate": "ok"}
{"problem_id": "wm-finite-14edcb97ce41", "role": "seeded", "defect_class": "ambiguous_wording", "mutation_note": "중의성: '모두' 제거(전부 빨간지 일부인지 모호)", "aggregate": "defect"}
{"problem_id": "wm-finite-79f76e668779", "role": "seeded", "defect_class": "ambiguous_wording", "mutation_note": "중의성: '앞면이 정확히 ' 제거(정확히 M번 vs M번 이상 모호)", "aggregate": "ok"}
{"problem_id": "wm-finite-625d20e10738", "role": "seeded", "defect_class": "ambiguous_wording", "mutation_note": "중의성: '의 합' 소실(두 눈의 수의 합이 N일 → 두 눈의 수가 N일)", "aggregate": "ok"}
{"problem_id": "wm-finite-a8cb473c65dc", "role": "seeded", "defect_class": "multiple_valid_answers", "mutation_note": "복수 정답: '동시에' 제거(비복원·무순서 추출 가정 소실 → 대안 해석 발생)", "aggregate": "defect"}
{"problem_id": "wm-finite-cd43a94bbe38", "role": "seeded", "defect_class": "multiple_valid_answers", "mutation_note": "복수 정답: '동시에' 제거(비복원·무순서 추출 가정 소실 → 대안 해석 발생)", "aggregate": "ok"}
{"problem_id": "wm-finite-14edcb97ce41", "role": "seeded", "defect_class": "multiple_valid_answers", "mutation_note": "복수 정답: '동시에' 제거(비복원·무순서 추출 가정 소실 → 대안 해석 발생)", "aggregate": "ok"}
{"problem_id": "wm-finite-9471f2dd9b2d", "role": "clean", "defect_class": null, "mutation_note": "", "aggregate": "ok"}
{"problem_id": "wm-finite-430b6612cd7f", "role": "clean", "defect_class": null, "mutation_note": "", "aggregate": "unclear"}
{"problem_id": "wm-finite-a7ae58c7d484", "role": "clean", "defect_class": null, "mutation_note": "", "aggregate": "ok"}
{"as_found_overall_detected": 2, "as_found_overall_resolved": 12, "as_found_clean_false_alarms": 0, "as_found_clean_resolved": 2}
```

항목 단위 관찰 (개선 설계의 표적):

- **검출 2건이 전부 공 추출(그룹 C) 문항** — `wm-finite-14edcb97ce41`('모두' 제거)·
  `wm-finite-a8cb473c65dc`('동시에' 제거). 주사위·동전 그룹의 결함은 전건 놓쳤다.
- **같은 문항·다른 변조의 비대칭** — `wm-finite-14edcb97ce41`에서 '모두' 제거(중의성)는 잡고
  '동시에' 제거(복수 정답)는 놓쳤다. 같은 변조('동시에' 제거)도 `a8cb473c65dc`에서는 잡고
  `cd43a94bbe38`·`14edcb97ce41`에서는 놓쳤다 — 검출이 결함 유형의 함수라기보다 문항별
  우연에 가깝다는 신호(재현성 낮음). 재강등전 설계 시 같은 변조의 반복 시행으로 검출의
  일관성 자체를 측정할 가치가 있다.
- as-found 요약(2/12·0/2)은 본문 리포트 집계와 일치 — 이중 회계 무결.

## 후속 방향 (태스크화 전 후보 — 채택은 별도 결정)

1. **관점 프롬프트 개선** — 조건 완전성·등확률 명시 여부를 직접 조준하는 점검 축 추가.
   단 S3-15 교훈("패턴 패치 축적 단독 재시도 금지") 준수: 이번 결함 4종에 맞춘 프롬프트 튜닝은
   teaching-to-the-test이므로, 재강등전에는 **신규 결함류 홀드아웃**을 동반해야 한다.
2. **상위 모델 검증기 별도 강등전** — CLOUD_MID(Sonnet) 구성으로 같은 배터리 측정. 단 측정
   구성=배포 구성 원칙: 배포 라우팅을 실제로 클라우드로 바꿀 때만 그 측정이 인증이 된다.
3. **대조군 확대**(clean n≥20) — `--max-defect-upper` 실측 보정의 선결 조건.
4. **레이턴시 축**: `/no_think`(사고 비활성) 실험 — 속도↔검출률 트레이드오프를 *함께* 측정
   (속도만 보고 채택 금지 — 검출률 16.7%가 더 떨어질 수 있다).
