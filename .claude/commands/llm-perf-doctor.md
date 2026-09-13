---
description: 로컬 LLM 성능 닥터 — Phaiakes9(AMD 395/8060S)에서 실측된 로드 실패·저성능·측정 공전 전 사례 카탈로그로 즉시 진단
argument-hint: "[에러 메시지 또는 증상] (인자 없으면 골든 패스 점검)"
---

# /llm-perf-doctor — 로컬 LLM 성능·로드 실패 진단

## 임무
Phaiakes9(GMKtec EVO-X2 · Ryzen AI Max+ 395 / Radeon 8060S gfx1151 · 128GB LPDDR5X · Win11)에서
Ollama 로드 실패·저성능·측정 공전을 **2026-08-22 실측·해결된 전 사례 카탈로그**로 즉시 진단한다.
새로 디버깅하지 말고 **먼저 아래 표에서 증상을 매칭**하라 — 전부 한 번씩 실제로 겪고 고친 것들이다.

정본 = `docs/ops/amd395_local_llm_performance.md` (★ 확정 결론 7항 + §5 실측표).

## 사용법
1. 증상을 주면 → 카탈로그에서 매칭 → 해법 제시. **1차 처방은 거의 항상 §0 위생 3종**이다.
2. 인자가 없으면 → §골든 패스를 순서대로 점검한다.
3. "느리다"는 신고는 **§기대 기준표와 대조부터** 한다 — 물리 한계인 경우가 많다.
4. 카탈로그에 없는 새 문제면 → 진단 후 **이 파일에 행을 추가**하고 커밋한다(살아있는 문서).

## 대원칙 (이 여정에서 배운 것)
- **판단축은 생성 t/s가 아니라 왕복 지연이다.** WhyMath는 긴 프롬프트·짧은 출력(단계 검증·동치 판정)이
  주력이다. 생성만 봤다면 Vulkan을 채택했을 것이고, 왕복으로 보니 27B가 **+68% 느려졌다**.
- **20% 규칙**: 같은 설정 재측정이 8~18% 흔들린다. **차이가 20% 미만이면 유의하다고 말하지 않는다.**
- **레버는 한 번에 하나만.** 인접 프리셋이 딱 하나만 다르게 설계한다(`baseline`→`rocm`은 flash만,
  `rocm`→`vulkan`은 IGPU_ENABLE만). 두 개를 같이 바꾸면 무엇이 효과였는지 영구히 모른다.
- **물리 한계를 먼저 계산한다.** 생성 상한 ≈ 메모리 대역폭 256 GB/s ÷ 활성 가중치 바이트.
  실측 효율 65~78%가 dense 전 구간에서 일관한다 — 이건 추정이 아니라 **이 머신의 법칙**이다.
- **측정 도구는 실패 경로부터 설계한다.** 이 여정에서 도구 결함 10건이 났고 측정 4회가 공전했다.
  세 가지를 항상 묻는다: ①실패해도 증거가 남는가 ②실패 *원인*이 남는가 ③지금 보는 게 이번 실행 것인가.

## 골든 패스 (권장 설정 = 확정 조건 7항)
```powershell
# [실행 시스템] Windows PowerShell (Phaiakes9 본체)
cd C:\Users\kiki\Desktop\__AI\WhyMath
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","8192","User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","3","User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","30m","User")
[Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE",$null,"User")   # Vulkan 제외 = ROCm 유지
# → Ollama 재시작 필수 (트레이 Quit → 재실행). 안 하면 이전 값으로 돈다.

# 진단·측정 (전부 자가검증 내장 · exit code로 판정)
powershell -ExecutionPolicy Bypass -File .\scripts\ops\collect_gpu_evidence.ps1     # 환경 증거 9섹션
powershell -ExecutionPolicy Bypass -File .\scripts\ops\bench_ollama.ps1 -Label x    # 모델별 t/s
powershell -ExecutionPolicy Bypass -File .\scripts\ops\tune_and_bench.ps1 -Presets "baseline,rocm,vulkan"
```
나머지 확정 조건: **MoE 모델 우선**(dense 대비 6.0배) · **VGM 64GB**(이미 설정됨).

## §0 위생 3종 — 로드 실패 신고의 1차 처방
```powershell
# ① 고아 프로세스 확인 — /api/ps 는 0건인데 llama-server 가 살아 있으면 고아다
Get-Process llama-server -ErrorAction SilentlyContinue | Select Id,StartTime
# ② 커밋 여유 — 물리 여유가 아니라 이 값이 구속 자원이다
"{0:N1} GB" -f ((Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB)
# ③ 정리 후 재시작
Get-Process ollama*, llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
```
커밋 여유가 **20GB 미만이면 위험, 5GB 미만이면 전건 실패**한다. 정리해도 안 오르면 **머신 재시작**.
정리해도 안 오를 때의 **배제 4단**(2026-09-10 확정): `Pool Nonpaged`가 수십 GB면 드라이버 누수,
`wsl --shutdown`으로 크게 오르면 WSL2, 프로세스 private 총합이 커밋에 근접하면 앱 —
**셋 다 아니고 커밋과 프로세스 총합의 격차만 남으면 🚨침해를 의심한다.**
2026-09-10 실측: 커밋 326 GB vs 프로세스 366개 총합 19.4 GB → `\Microsoft\Windows\Google\`
아래에 위장한 채굴 예약 작업 2개(보안 예외 추가·외부 스크립트 실행)가 범인. 프로세스 종료로
공유 커밋 **156.699 → 3.854 GiB**(152.845 GiB 회수), 이후 관리자 승인으로 두 작업 비활성화.
**이름이 아니라 실행 파일·인자를 본다** — Microsoft 트리 안에 있어 훑어서는 안 보인다.
**재부팅은 증상만 지우고 감염은 남긴다** — `Get-ScheduledTask`로 예약 작업·자동시작을 먼저 본다(SEC-34).

## 문제 카탈로그 (증상 → 원인 → 해법 · 전부 실측)

### A. 로드 실패 / 메모리
| 증상 | 원인 | 해법 |
|---|---|---|
| `cudaMalloc failed: out of memory` — GPU free는 99.6 GiB로 보이는데 17 GiB 할당 실패 | ROCm 보고 free가 실물이 아니다. 회계의 `unaccounted`가 음수면 그 지문 | §0 위생 3종. 대개 고아 프로세스 |
| `failed to allocate CPU buffer of size 1.0 GiB` — 물리 여유 34.9 GB인데 1 GB 실패 | **커밋 한도**(물리+페이지파일)가 벽이다. 물리 여유는 무관 | §0 ②로 커밋 확인 → 정리 → 재시작 |
| 작은 모델(3b)까지 전건 실패 | 크기 문제가 아니다. 커밋 고갈 | §0 위생 3종 |
| `exit status 0xc0000409` (스택 버퍼 오버런) | OOM 처리 경로의 2차 증상 | 위와 동일. 크래시 자체를 쫓지 말 것 |
| `free_swap`이 회를 거듭할수록 줄어듦 | 실패한 로드가 고아를 남기고, 고아가 다음 실패를 부르는 **자기증식** | 측정 **전에** 항상 §0 ① 확인 |
| 페이지파일을 키워도 안 낫는다 | 페이지파일은 이미 192GB로 충분했다. 문제는 점유 | 재시작. 확대는 대책이 아니다 |
| **§0을 해도 커밋이 안 오른다**(고아 0건인데 여유 2GB) | **장기 가동 누적형.** 2026-09-10 실측: 커밋 326/328GB인데 프로세스 366개 private 합 19.4GB·Pool Nonpaged 1.97GB — 약 302GB가 어느 회계에도 없다(페이지파일 232.7GB 100% 소진) | **배제 4단을 1분에 끝내고 재부팅**: ①고아 ②`CTX=8192` 확인 ③`Pool Nonpaged`(드라이버 누수면 수십GB) ④`wsl --shutdown`. 넷 다 반증되면 더 파지 말 것 — RAMMap 없이는 진척 없다. 재부팅 시 2.1→**256.7GB** 회복 실측 |
| 컨텍스트가 `262144`로 잡힘 | ROCm이 VRAM 99.7 GiB를 보고해 자동 기본값이 폭주 | `OLLAMA_CONTEXT_LENGTH=8192` + 재시작 |

### B. 측정이 공전할 때 (도구·절차)
| 증상 | 원인 | 해법 |
|---|---|---|
| 설정을 바꿨는데 효과가 없다 | **Ollama 재시작 누락**. env는 기동 시 읽는다 | 벤치 시작의 `[SRV ]` 줄로 실효값 확인 → 다르면 재시작 |
| `{"error":"invalid model name"}` | `powershell -File`은 인자를 문자열 그대로 넘긴다. `-Models a,b`가 원소 1개로 도착 | 수정 완료(스크립트가 콤마 분해 + 설치 목록 대조) → `git pull` |
| 실패 로그를 붙였는데 시각이 이전 실행 것 | 로그 tail에 시간 필터 없음 | 수정 완료. "이번 실행 이후 로그 없음"이 뜨면 **서버가 로드를 시도조차 안 한 것** |
| 정상인데 프리셋이 중단됨 (`기대 '1' / 실제 'true'`) | Ollama가 불리언을 정규화. 문자열 동등 비교라 오탐 | 수정 완료(의미 비교) → `git pull` |
| `prompt 43542 t/s` 같은 허수 | 2회차가 프롬프트 캐시 히트 | 수정 완료(매 실행 고유 접두사) |
| `gen 0 t/s \| out  tok` | 빈 응답(`eval_count` 없음). 0은 측정이 아니라 실패 | 수정 완료(실패로 분류) |
| 스크립트가 중간에 멈추고 파일도 안 생김 | 외부 프로세스 무한 대기 + 마지막에 한 번 저장 구조 | 수정 완료(타임아웃 + 섹션별 즉시 append) |
| `CommandNotFoundException` (스크립트 자기 함수) | PowerShell은 위→아래 실행. 정의가 호출보다 아래 | `python3 scripts/ops/check_ps_scripts.py` (CI 차단 스텝) |
| 고성능 전원 계획이 목록에 없다 | Win11이 기본 숨김 | 수정 완료(`duplicatescheme`으로 생성 후 활성화) |
| 레지스트리 `SecurityException` / dxdiag 미생성 | 권한·도구 문제 | **무시 가능**. VGM 판정은 카브아웃 계산(설치 물리 − Windows 가용)이 담당 |

### C. "느리다" 신고
| 증상 | 원인 | 해법 |
|---|---|---|
| 27B가 12 t/s밖에 안 나온다 | **물리 한계**. 이론 상한 15.5의 75% | 정상이다. 설정이 아니라 **모델을 바꿔야** 한다(MoE 6.0배) |
| 모델 전환마다 수 초씩 걸린다 | 스왑 로드가 생성보다 비싸다(27B 로드 16초 > 생성 10.7초) | `MAX_LOADED_MODELS=3` + `KEEP_ALIVE=30m` → 재방문 **2.6 ms** |
| Vulkan이 생성은 빠른데 체감이 나쁘다 | Vulkan은 prefill을 −25~75% 깎는다 | **ROCm 유지**. `IGPU_ENABLE`을 지운다 |
| 같은 설정인데 측정이 8~18% 흔들린다 | **[미규명]** 1회차만 높은 특이성 | 20% 규칙 적용. 2회 이상 재고 중앙값을 쓴다 |

## 기대 기준표 — "느리다" 판정의 기준 (2026-08-22 실측)
| 모델 | 크기 | 생성 t/s | 이론 상한 | 효율 |
|---|---|---|---|---|
| `qwen2-math:1.5b` | 0.9 GB | 164 | 256 | 64% |
| `qwen2.5:3b` | 2.0 GB | 81.7 | 128 | 64% |
| `qwen2.5:7b` | 4.7 GB | 41.7 | 55 | 76% |
| `qwen2.5:14b` | 8.4 GB | 22.2 | 30 | 73% |
| `qwen3.5:27b` (dense) | 16.2 GB | 11.7 | 15.5 | 75% |
| `qwen3:30b-a3b` (**MoE**) | 17.3 GB | **70.1** | — | 활성 ~2.7 GB/token |

**기대치의 절반 이하 + `gpu_fraction < 1`** = CPU 폴백. **기대 범위 안** = 물리 한계, 더 짜지 말 것.

## 미확정 (건드리기 전에 알아둘 것)
- **백엔드 라벨** — `library=` 판독에 시간 필터가 없어 세 프리셋 모두 ROCm으로 찍혔다. 수정됐고 다음 실행에서 확정.
  단 ROCm 유지 결론은 라벨이 아니라 왕복 수치에 근거하므로 영향 없음.
- **재현성 1회차 특이성** — 2·3회차는 ≤1.5% 일치, 1회차만 높다. 원인 미규명.
- ~~**커밋 235GB의 정체** — 무엇이 점유하는지 모른다. 재시작하면 풀린다는 것만 안다(대증 요법).~~
  🚨 **정정(2026-09-10, `SEC-34`)**: 규명됐다 — 위장 예약 작업이 구동한 무단 채굴 감염이었다(§0 위생 3종의
  🚨 항목 참조). "재시작하면 풀린다"는 대증 요법을 원인 규명으로 오인한 것이었고, 예약 작업을 그대로 두면
  재발한다(2026-09-10 실제로 재발 확인). **이 문서의 성능 수치(§ 기대 기준표 포함)도 감염 기간과 겹치는
  구간에서 측정됐을 수 있다** — 재측정 계획은 `OPS-75`가 소유한다.
- **MoE 정확도** — 6배 빠른 건 확정, 검출률은 미측정. `OPS-48`이 소유.
