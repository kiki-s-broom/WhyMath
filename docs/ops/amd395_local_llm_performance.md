# Phaiakes9 (AMD Ryzen AI Max+ 395 / Radeon 8060S) 로컬 LLM 성능 극대화 런북

> **대상 머신**: GMKtec EVO-X2 · Ryzen AI Max+ 395(Strix Halo) · Radeon 8060S(gfx1151) · 128GB LPDDR5X-8000 · Windows 11
> **목적**: WhyMath L3 로컬 추론(Ollama·Qwen 계열)의 처리량·지연을 이 하드웨어에서 물리 한계 근처까지 끌어올리는 조건을 **측정으로** 확정한다.
> **작성**: 2026-08-21 · 브랜치 `claude/amd-395-gpu-diagnosis-jinh6i`
> **갱신**: 2026-09-10 · OPS-52 ROCm 7.2.1 standalone 시도 결과 회수·§5 Phase 6·§6 항목4 추가

> 🚨 **정정 (2026-09-10, `SEC-34`) — 이 문서의 측정 구간 전체가 오염 가능 구간과 겹친다.**
> 이 문서의 최초 측정 시작(2026-08-21)부터 침해 봉쇄(2026-09-10 17:50 KST)까지 Phaiakes9는
> 위장 예약 작업(`\Microsoft\Windows\Google\GoogleUpdateTask{,SYSTEM}`)에 의한 무단 채굴 감염
> 상태였을 가능성이 크다(§5 "커밋 고갈 2회차" 정정 박스 참조 — 근거: 종료 즉시 공유 커밋 152.845 GiB
> 회수, 2026-08-22 "커밋 235GB의 정체"와 지문이 동일). 즉 **★ 확정 결론 7항을 포함해 이 문서의 t/s·왕복
> 지연 수치는 배경 채굴과 GPU·메모리·전력을 다퉜을 가능성을 배제하지 않은 상태에서 측정됐다** — 채굴
> 자식 프로세스가 AMD OpenCL 라이브러리를 로드하고 있었다는 관측(침해 조사 기록)은 GPU 경쟁 가능성을
> 특히 시사한다. 대역폭 상한 모델([계산] §2)이 실측과 정합했다는 사실 자체는 채굴이 상시 전력으로 GPU를
> 점유하지는 않았음을 방향적으로 뒷받침하지만, **오염 여부를 배제한 증거는 아니다.**
> 재측정 계획은 `OPS-75`(SEC-34 완결 후 착수)가 소유한다 — 감염기간 수치를 그대로 인용해 새 결정을
> 내리지 말 것. 아래 ★확정 결론과 §5의 개별 수치는 **재검증 전까지 잠정치**로 읽는다.

---

## ★ 확정 결론 — Phaiakes9 성능 극대화 조건 (2026-08-22 실측)

레버를 하나씩 갈라 측정한 최종 권고. **왕복 지연**(prefill + 생성)이 판단축이다 — WhyMath 호출은 긴 프롬프트·짧은 출력이 주력이기 때문이다.

| # | 조건 | 값 | 실측 근거 |
|---|---|---|---|
| 1 | **모델 구조** | dense보다 **MoE** | 27B dense 11.7 t/s vs 30B-A3B **70.1** t/s — **6.0배**. 최대 레버 |
| 2 | **모델 상주** | `OLLAMA_MAX_LOADED_MODELS=3`+ · `OLLAMA_KEEP_ALIVE=30m` | 재방문 로드 2,340 ms → **2.6 ms** (**900배**) |
| 3 | **flash attention** | `OLLAMA_FLASH_ATTENTION=1` | MoE 생성 **+20.3%** · prefill **+21.7%** · 왕복 **−34.8%**. 부작용 없음 |
| 4 | **백엔드** | **ROCm 유지** (`OLLAMA_IGPU_ENABLE` 설정하지 않음) | Vulkan은 생성 +9~21%를 주지만 prefill을 **−25~75%** 깎는다 → 27B 왕복 13.1s → **21.1s (+68%)** |
| 5 | **컨텍스트 예산** | `OLLAMA_CONTEXT_LENGTH=8192` · `OLLAMA_NUM_PARALLEL=1` | 자동 262,144는 로드 실패를 유발 |
| 6 | **VGM** | 64 GB (이미 설정됨) | 레지스트리 실측 65,536 MB |
| 7 | **위생** | 주기적 재시작 · 고아 `llama-server` 정리 | 커밋 여유 0.9 GB → 205 GB 회복. 방치 시 **전건 로드 실패** |

**적용 명령** (`resident` 프리셋이 3·5를 포함하고, 4는 `IGPU_ENABLE`을 두지 않는 것이 곧 적용이다):
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","8192","User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","3","User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","30m","User")
[Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE",$null,"User")   # Vulkan 후보 제외 = ROCm 유지
# 적용하려면 Ollama 재시작 필요
```

**넘을 수 없는 벽**: 생성 속도 상한은 메모리 대역폭 256 GB/s가 정한다(§2). dense 27B의 11.7 t/s는
이론 상한 15.5의 75%로 **이미 물리 한계 근처**다. 여기서 더 얻으려면 설정이 아니라 **모델을 바꿔야 한다**(레버 1).

---

## 0. 이 문서의 근거 등급 (읽기 전에)

이 저장소 규칙상 **검증 없는 실행 안내는 금지**다. 아래 표기를 각 주장에 붙였다.

| 등급 | 뜻 | 이 문서에서의 취급 |
|---|---|---|
| **[계산]** | 하드웨어 사양에서 직접 유도 (본 문서 §2) | 검산 가능·재현 가능 |
| **[문헌]** | 외부 실측 보고·공식 문서 (§8 출처) | 방향은 신뢰, **수치는 이 머신에서 재측정 필요** |
| **[코드]** | 이 저장소 코드에서 확인 | 사실 |
| **[미측정]** | Phaiakes9에서 아직 안 잰 것 | **가정 금지 — 측정 후 이 표를 갱신** |

> ✅ **2026-08-22 Phase 0·1 완주.** 환경 실측(9/9 섹션) + **벤치 5모델 전건 성공**(10/10 런, 전부 GPU 100%).
> §2의 대역폭 상한 계산 모델이 **전 구간에서 검증**됐고, dense↔MoE 대조가 나왔다. §5 진단표 참조.
> 게이트 `G-amd395-perf-baseline`(사람 게이트 대장)이 이 측정을 추적한다.

---

## 1. 사전 브리핑 (Kiki 직접 수행 과제 · 6항목)

1. **과제 명칭** — Phaiakes9 GPU 추론 경로 진단 및 성능 레버 1개씩 측정
2. **목적** — "8060S에서 GPU 추론이 되는가"를 넘어서 **어떤 설정 조합이 최대 t/s를 내는가**를 확정한다. 결과는 ①WhyMath L3 라우터의 로컬 티어 지연 상수(`LOCAL_LATENCY_MS`) 보정 ②로컬 vs OpenRouter 비용/정확도 비교 ③QUALITY 티어 모델(현 `qwen3.5:27b`) 유지 여부 판단에 쓰인다.
3. **구체적 절차** — Phase 0(증거 수집, 2분) → Phase 1(베이스라인 벤치, 5~15분) → Phase 2~5(레버 **하나씩** 바꾸고 재측정, 각 5~20분). 각 Phase는 스크립트 1개 실행이 전부이며, 결과는 `.gpu_evidence\` 아래 파일로 남는다.
4. **성공 기준** — Phase 0에서 `evidence_*.txt`가 생성되고 그 안에 GPU 이름·전용 VRAM 바이트 수가 찍힌다. Phase 1에서 `bench_*.csv`의 `gpu_fraction` 열이 1.0에 가까우면 GPU 추론, 0.0이면 CPU 추론이다. **실패 시 대처**: 스크립트가 `[FAIL]`로 끝나면 그 줄을 그대로 붙여넣고 멈춘다(추정으로 다음 단계 진행 금지).
5. **실행 환경** — Phaiakes9의 **Windows PowerShell**(= 평소 쓰는 그 창. SSH·WSL 진입 불요). 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: Ollama for Windows 설치·기동, 이 브랜치 체크아웃.
6. **창 구분** — Phase 0~1은 **아무 PowerShell 창 1개**에서 끝난다(서버 점유 없음). Phase 4(백엔드 스위치)만 `ollama serve`가 창을 점유하므로 **창을 2개** 쓴다 — 해당 절에 명시.

### 선행: 브랜치 체크아웃 (창 A · Windows PowerShell)

```powershell
# [실행 시스템] Windows PowerShell (Phaiakes9 본체 · 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/amd-395-gpu-diagnosis-jinh6i
git checkout -B claude/amd-395-gpu-diagnosis-jinh6i origin/claude/amd-395-gpu-diagnosis-jinh6i
# 자가검증 — 스크립트 2개가 실제로 있는지 (없으면 여기서 멈춘다)
Test-Path .\scripts\ops\collect_gpu_evidence.ps1, .\scripts\ops\bench_ollama.ps1
```

> 두 줄 모두 `True`가 아니면 체크아웃이 안 된 것이다. 다음 단계로 넘어가지 않는다.

---

## 2. 먼저 알아야 할 것: 이 머신의 성능 상한은 **메모리 대역폭**이 정한다 [계산]

Strix Halo의 LPDDR5X-8000 / 256-bit 구성 → **피크 대역폭 256 GB/s**(`8000 MT/s × 32 B`).
LLM 토큰 생성은 매 토큰마다 활성 가중치를 통째로 읽으므로, **생성 속도 상한 ≈ 대역폭 ÷ 활성 가중치 바이트**다.

| 모델 (WhyMath 실제 핀 [코드]) | Q4 크기 | 이론 상한 | 현실 기대(상한의 55~70%) |
|---|---|---|---|
| `qwen2-math:1.5b` | ~1.0 GB | 256 t/s | **141 ~ 179 t/s** |
| `qwen2.5:3b` | ~2.0 GB | 128 t/s | **70 ~ 90 t/s** |
| `qwen2-math:7b` | ~4.4 GB | 58 t/s | **32 ~ 41 t/s** |
| `qwen2.5:7b` | ~4.7 GB | 55 t/s | **30 ~ 38 t/s** |
| `qwen3-vl:8b` | ~6.1 GB | 42 t/s | **23 ~ 29 t/s** (+비전 인코더 prefill 별도) |
| `qwen3.5:27b` (QUALITY·**dense**) | ~16.5 GB | **15.5 t/s** | **8.5 ~ 11 t/s** |
| (참고) 30B-A3B **MoE**, 활성 ~3B | 적재 17 GB / 활성 ~1.9 GB | 135 t/s | **74 ~ 94 t/s** |

> **Phaiakes9 실측 확인 (2026-08-22)**: `NUCBOX_EVO-X2` · AMD RYZEN AI MAX+ 395 (16C/32T) ·
> AMD Radeon(TM) 8060S (driver `32.0.31035.1003`, 2026-07-24) · **LPDDR5X 16GB × 8ch @ 8000 MT/s** ·
> Windows 11 Pro 26200. 즉 위 표의 대역폭 전제(8000 MT/s × 256-bit = 256 GB/s)는 **이 머신에서 확인된 값**이다.

**이 추정 모델은 외부 실측으로 검증된다**: 같은 하드웨어에서 Qwen3-30B-A3B가 llama.cpp/Vulkan으로 **~100 t/s** 보고 [문헌] — 위 표의 MoE 기대치(74~94)와 정합한다.

### 여기서 나오는 결론 3개

1. **27B dense가 10 t/s 근처로 나오면 그건 고장이 아니라 물리 한계다.** 드라이버·백엔드를 아무리 만져도 15.5 t/s를 넘지 못한다. 이 사실을 모르고 튜닝하면 며칠을 태운다.
2. **가장 큰 레버는 설정이 아니라 모델 구조다.** dense 27B → 동급 MoE(30B-A3B류)는 **약 10배**. 백엔드 튜닝(Vulkan↔ROCm)은 잘해야 ±25% [문헌].
3. **7B 이하 티어(WhyMath 주력)는 이미 대역폭 여유가 크다.** 여기서 부족하면 원인은 대역폭이 아니라 **GPU 오프로드 실패(CPU 폴백)** 이다 — §4 Phase 1의 `gpu_fraction`이 바로 그 판정치다.

---

## 3. 성능 극대화 조건 — 레버 7개 (효과 큰 순)

> **원칙: 한 번에 하나만 바꾸고 잰다.** 여러 개를 동시에 바꾸면 무엇이 효과였는지 영구히 알 수 없다.

### L1. 가변 그래픽 메모리(VGM) — GPU가 모델을 아예 못 올리는 1순위 원인 [문헌]

> ✅ **Phaiakes9 현재값 = 약 64GB (2026-08-22 실측) — 이 레버는 이미 권장 상태다.**
> 판정 근거: 물리 설치 128.0GB(16GB × 8ch) − Windows 가용 63.6GB = **카브아웃 64.4GB**.
> 이 계산은 관리자 권한도 dxdiag도 필요 없다(레지스트리 키는 권한 부족으로 막혔고 dxdiag는 실패했으나 판정은 성립했다).
> ⇒ **Phase 2(VGM 조정)는 건너뛴다.** 아래 설명은 값이 어긋났을 때의 조정 방법으로 남긴다.
- **무엇**: AMD Adrenalin → **성능 → 튜닝 → 가변 그래픽 메모리 → 사용자 지정**. 128GB 머신에서 최대 96GB. 설정 후 **재부팅**(펌웨어 레벨 저장 → 드라이버/OS 업데이트에도 유지).
- **왜**: Ollama·llama.cpp·LM Studio는 **"전용 GPU 메모리"** 보고값을 보고 "이 모델이 GPU에 들어가는가"를 판단한다. 전용값이 작으면 메모리가 남아돌아도 **CPU로 폴백**한다.
- **권장값(이 머신 한정 판단)**: **64GB**. 96GB가 아니다 —
  Phaiakes9는 추론 전용기가 아니라 **개발기**다(Docker Postgres `whymath-pg`·백엔드 uvicorn·Flutter 빌드가 상주). 96GB를 떼면 OS+개발 스택에 32GB만 남는다.
  WhyMath가 동시에 상주시켜야 할 모델 총합은 27b(16.5)+7b(4.7)+vl 8b(6.1)+KV ≈ **30~35GB** [계산] → 64GB면 충분하고 30GB 가까운 여유가 남는다.
- **주의** [문헌]: Windows ROCm/HIP 경로에는 **단일 프로세스 VRAM 할당이 32GB를 넘으면 shared memory로 흘러내리는** 보고(ROCm #5940, closed)가 있다. WhyMath 모델은 모두 32GB 미만이라 해당 없음 — 단, 나중에 70B급을 얹으면 이 벽을 먼저 의심한다.

### L2. 전원 모드 — 54W / 85W / **140W** [문헌]
- EVO-X2는 **전면 전용 버튼**으로 Quiet(54W)/Balanced(85W)/Performance(140W)를 전환한다(BIOS 진입 불요).
- 추가로 Windows **전원 모드 = 최고 성능**.
- **기대**: 토큰 생성(대역폭 바운드)보다 **프롬프트 처리(연산 바운드)** 에서 이득이 크다 [계산 근거: prefill은 GEMM, decode는 메모리 읽기]. WhyMath는 **긴 프롬프트 + 짧은 출력**(PRM 단계 검증·동치 판정) 비중이 커서 이 레버가 체감상 크게 작동할 수 있다 — **[미측정]**.

### L3. 백엔드: Vulkan vs ROCm/HIP [문헌]

> ✅ **Phaiakes9 현재 상태 = ROCm 사용 중 (2026-08-22 실측)**. 서버 로그가 두 줄로 말해 준다:
> ```
> library=Vulkan  msg="dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1"  name=Vulkan0
> library=ROCm    msg="inference compute"  compute=gfx1151  type=iGPU  total="99.7 GiB"
> ```
> 즉 **Vulkan 장치는 iGPU라는 이유로 버려졌고, ROCm이 gfx1151을 잡아 실제 추론 장치로 선택됐다.**
> `HSA_OVERRIDE_GFX_VERSION` 없이도 인식된다(문헌의 우회는 이 버전에선 불요).
> ⇒ **"ROCm이 안 잡힌다"는 최초 전제는 이 머신에 해당하지 않는다.** 남은 질문은 "잡혔는가"가 아니라
> **"Vulkan으로 바꾸면 더 빠른가"** 이며, 그것이 Phase 4다(`OLLAMA_IGPU_ENABLE=1`로 Vulkan 장치를 살려 비교).
- 같은 하드웨어 비교에서 **ROCm은 프롬프트 처리 +20%, Vulkan은 토큰 생성 +25%** 로 서로 반대 방향의 우위가 보고된다.
- Ollama에서 Vulkan은 **실험적**으로 0.12.6부터 들어왔고 `OLLAMA_VULKAN=1`(끄기 `=0`)로 제어된다. iGPU는 `OLLAMA_IGPU_ENABLE=1`을 **명시해야** GPU를 쓰는 사례가 보고된다(안 하면 GPU를 *감지하고도* CPU로 돈다).
- ROCm 경로는 `HSA_OVERRIDE_GFX_VERSION=11.5.1`로 gfx1151 인식이 풀린 보고가 있다.
- **주의**: 위 두 경로의 환경변수는 **섞으면 안 된다**. ROCm 경로에서 `HIP_VISIBLE_DEVICES=-1`을 켜면 GPU가 통째로 꺼진다.
- **WhyMath 판단축**: 생성 t/s가 아니라 **왕복 지연**으로 고른다. §4 Phase 4가 두 경로를 각각 잰다.

### L4. 런타임: Ollama 번들 llama.cpp vs standalone llama.cpp [문헌]
- standalone 최신 llama.cpp가 더 빠른 사례가 반복 보고된다(Qwen3-30B-A3B ~101 t/s).
- **하지만 교체 비용이 있다**: WhyMath는 `l3/providers/ollama.py`에 Ollama 클라이언트로 배선돼 있다 [코드]. 교체하려면 `llama-server`의 OpenAI 호환 API로 프로바이더를 새로 쓰거나(라우터 경유 원칙은 유지), Ollama를 그대로 두어야 한다.
- **판단 기준**: Phase 6에서 standalone이 **+20% 이상**일 때만 배선 변경을 태스크로 등재한다. 그 미만이면 Ollama 유지가 총비용상 이득이다.
- 🔴 **OPS-52 실측 시도 완료(2026-08-23 실측 · 2026-09-10 문서 회수)**: 진짜 standalone `llama-server`(Ollama 밖에서 새로 빌드/기동하는 OpenAI 호환 API)가 아니라, 더 가벼운 변형 — AMD 공식 ROCm 7.2.1 Windows wheel을 격리 설치해 Ollama 0.32.15의 내장 HIP DLL을 7.2로 교체하는 방식을 먼저 시도했다(경로 ①의 wheel 배포 변형). **+20% 기준 미달로 Ollama 유지 결정**. 상세는 §5 Phase 6 실측·§6 항목 4.

### L5. 모델·양자화 선택 — **가장 큰 레버** [계산]
- **MoE 우선**. §2 표대로 dense 27B(≈10 t/s) → MoE 30B-A3B(≈100 t/s)는 10배다.
- ✅ **비교에 필요한 모델이 이미 다 깔려 있다 (2026-08-22 실측)** — `qwen3:30b-a3b`(17.3GB·MoE)와
  `qwen3-coder:30b`(17.3GB·MoE)가 `qwen3.5:27b`(16.2GB·dense)와 나란히 있다. **다운로드 없이 즉시 대조 가능**하다.
  이 세 모델의 t/s 비교가 이 프로젝트에서 가장 값어치 있는 단일 측정이다.
- 양자화는 **Q4_K_M / IQ4_XS**가 크기·품질 균형점. Q8_0은 크기가 2배 → 대역폭 바운드 구간에서 **속도가 절반**이 된다.
- 🔴 **실측 확정(2026-08-22)**: `qwen3.5:27b` **11.9 t/s** vs `qwen3:30b-a3b` **71.5 t/s** = **생성 6.0배 · prefill 3.9배**.
  같은 17GB급인데 MoE는 토큰당 약 2.7 GB만 읽는다.
- **WhyMath 제안(결정 아님 — 정확도 대조가 남았다)**: QUALITY 티어 `qwen3.5:27b`(dense)를 MoE로 교체하면 **비동기 티어를 동기로 승격**할 수 있는 크기의 이득이다(12.4초 → 2.3초, 동일 프롬프트·128토큰 실측).
  **단, 속도만으로 결정하지 않는다** — 채택 조건 3건(라우터 경유·실측 근거·MEMORY 결정 로그) 중 실측 근거의 *정확도 축*이 아직 없다. 결함 주입 강등전으로 대조한 뒤 결정한다. → §6.

### L6. 모델 상주 정책 · 컨텍스트 예산 — WhyMath에서 **체감 1순위** [코드+계산+실측]

> 🔴 **Phaiakes9에서 즉시 손봐야 할 것이 실측으로 드러났다 (2026-08-22)**
>
> | 항목 | 현재값 | 문제 | 권장 |
> |---|---|---|---|
> | `OLLAMA_CONTEXT_LENGTH` | unset → **자동 262,144** | 로그: `vram-based default context ... default_num_ctx=262144`. ROCm이 VRAM을 99.7 GiB로 보고해 **256K 컨텍스트**가 기본값이 됐다 | **8192~32768 명시** |
> | `OLLAMA_NUM_PARALLEL` | **4** | KV 캐시가 병렬 슬롯 수만큼 곱해진다 | **1~2** |
> | `OLLAMA_FLASH_ATTENTION` | **false** | KV 메모리·속도 손해 | **1** |
> | `OLLAMA_MAX_LOADED_MODELS` | **2** | 라우터는 6개 핀을 오간다 → 스왑 발생 | **4** |
> | `OLLAMA_KEEP_ALIVE` | 10m | 무난 | 30m |
>
> **왜 컨텍스트가 1순위인가** [계산]: 27B급에서 KV 캐시는 대략 컨텍스트 길이에 비례한다.
> 256K × 4병렬은 물리적으로 불가능한 크기라 Ollama의 자동 fit이 끼어들어 **로드 때마다 예측 불가능하게 줄인다** —
> 로드 시간이 길어지고, 최악의 경우 GPU에 다 못 올려 **CPU로 흘러내린다**(= `gpu_fraction < 1`).
> 8K로 명시하면 같은 계산에서 KV가 1/32이 된다. WhyMath 호출은 대부분 단문이므로 손해가 없다.
- 라우터는 한 학습 흐름에서 MATH(1.5b/7b)·GENERAL(3b/7b)·VISION(8b)·QUALITY(27b)를 **오간다** [코드 `LOCAL_MODEL_MATRIX`]. Ollama 기본값은 동시 상주 모델 수가 적어, 모델이 바뀔 때마다 **언로드→로드**가 일어난다.
- 27B를 디스크에서 다시 올리는 비용은 수 초 단위다. 이게 붙으면 **모델 스왑이 p50 지연을 지배**한다 — 토큰 속도를 아무리 올려도 안 보인다.
- **그래서 VGM 64GB의 진짜 값어치는 "큰 모델 하나"가 아니라 "여러 모델 동시 상주"다.**
- 설정(창 A에서 1회, 영구):
  ```powershell
  # [실행 시스템] Windows PowerShell (Phaiakes9)
  cd C:\Users\kiki\Desktop\__AI\WhyMath
  [Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","8192","User")
  [Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","2","User")
  [Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","User")
  [Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","4","User")
  [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","30m","User")
  # 자가검증 — 값이 실제로 박혔는지 (레지스트리를 되읽는다. 현재 셸 변수가 아님)
  "OLLAMA_CONTEXT_LENGTH","OLLAMA_NUM_PARALLEL","OLLAMA_FLASH_ATTENTION","OLLAMA_MAX_LOADED_MODELS","OLLAMA_KEEP_ALIVE" |
    ForEach-Object { "{0} = {1}" -f $_, [Environment]::GetEnvironmentVariable($_,"User") }
  ```
  > 위 4줄이 **빈 값이 아니어야** 한다. 그리고 **Ollama를 재시작해야** 적용된다(트레이 아이콘 → Quit → 재실행).
- `OLLAMA_KV_CACHE_TYPE=q8_0`은 KV 캐시를 절반으로 줄여 긴 컨텍스트에서 이득이지만 **품질 영향이 있어 WhyMath 기본값으로 권장하지 않는다** — 컨텍스트가 실제로 모자랄 때만.

### L7. 컨텍스트 길이 — 필요한 만큼만 [계산]
- 컨텍스트를 키우면 KV 캐시가 선형으로 커지고(30B·200K에서 50~70GB 보고 [문헌]), 속도와 안정성을 함께 깎는다.
- WhyMath 호출은 대부분 단문 프롬프트다. **기본값(4K~8K) 유지**, 필요 호출만 개별 상향.

---

## 4. 진단 절차 — 레버 하나씩

### Phase 0. 증거 수집 (창 A · 2분)

```powershell
# [실행 시스템] Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\collect_gpu_evidence.ps1
```

- 산출물: `.gpu_evidence\evidence_<타임스탬프>.txt` (GPU 이름·드라이버·**전용 VRAM 바이트**·전원 계획·Ollama 버전/모델/상주 상태·`OLLAMA_*`/`HSA_*`/`GGML_*` 환경변수·Ollama 서버 로그의 GPU 탐지 줄)
- **자가검증**: 스크립트가 마지막에 파일 존재·크기를 되읽어 `[OK]`/`[FAIL]`과 함께 **exit code**를 낸다. `[FAIL]`이면 그 줄을 붙여넣고 멈춘다.
- 이 파일 하나가 §1에서 물어본 4가지(Ollama 버전 / 모델 / GPU 탐지 / `ollama ps`의 processor)를 **전부** 담는다.
- **옵션**: `-WithDxdiag`(느리고 실패 잦아 기본 꺼짐) · `-NativeTimeoutSec 30`(외부 명령 타임아웃) · `-OllamaHost`
- **권한**: 관리자 권한은 필요 없다. §4의 레지스트리 조회만 권한이 있으면 더 나오고, 없으면 [ERR]로 남기고 넘어간다 —
  VGM 판정은 §2 카브아웃이 담당하므로 영향 없다.

### Phase 1. 베이스라인 벤치 (창 A · 5~15분)

```powershell
# [실행 시스템] Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\bench_ollama.ps1 -Label baseline
```

- 산출물: `.gpu_evidence\bench_baseline_<타임스탬프>.csv` — 모델별 `gen_tps`(생성 t/s)·`prompt_tps`(프롬프트 처리 t/s)·`load_ms`·**`gpu_fraction`**
- **판정**:
  | 관측 | 뜻 | 다음 행동 |
  |---|---|---|
  | `gpu_fraction` ≈ 1.0 | GPU 추론 성립 | Phase 2로 (극대화 단계) |
  | `gpu_fraction` ≈ 0.0 | **CPU 폴백** | L1(VGM) → L3(백엔드 env) 순서로 원인 추적 |
  | 0 < `gpu_fraction` < 1 | 부분 오프로드 | VRAM 부족 → L1 상향 |
  | `gen_tps`가 §2 기대치의 **50% 미만** | 오프로드는 됐으나 느림 | L2(전원)·L3(백엔드) 후보 |
  | `gen_tps`가 §2 기대치 범위 안 | **이미 물리 한계 근처** | 더 짜지 말고 L5(모델 교체)로 |

### Phase 2. VGM 조정 (재부팅 포함)
AMD Adrenalin → 성능 → 튜닝 → 가변 그래픽 메모리 → 사용자 지정 **64GB** → 재부팅 → 재측정:
```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\collect_gpu_evidence.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\ops\bench_ollama.ps1 -Label vgm64
```

### 🤖 Phase 2~5 자동 실행 — `tune_and_bench.ps1` (권장)

수작업 단계(환경변수 → Ollama 재시작 → 실효 설정 확인 → 벤치)를 전부 스크립트가 한다.
**2026-08-22 진단에서 측정 4회가 측정 자체가 아닌 이유로 공전했기 때문이다** — 재시작 누락 2회, 고아 프로세스 1회, 인자 파싱 1회.

```powershell
# [실행 시스템] Windows PowerShell (Phaiakes9 본체)
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\tune_and_bench.ps1 -Presets "baseline,resident,rocm,vulkan"
# 전원 레버는 별도 실행 2회 — ①전면 버튼 Balanced 상태에서 baseline만:
powershell -ExecutionPolicy Bypass -File .\scripts\ops\tune_and_bench.ps1 -Presets "baseline"
# ②전면 버튼을 Performance(140W)로 전환한 뒤 power140만:
powershell -ExecutionPolicy Bypass -File .\scripts\ops\tune_and_bench.ps1 -Presets "power140" -PowerMode140W
# (baseline과 power140을 같은 실행에 넣으면 같은 물리 전원 상태에서 측정돼 스크립트가 중단한다 — 2026-08-25 Codex 리뷰)
```

프리셋마다 ①환경변수 적용 ②Ollama·고아 전부 종료 ③재기동 ④`/api/version` 응답 대기
⑤**`server.log`의 실효 설정이 의도와 일치하는지 대조**(불일치면 즉시 중단 — 잘못된 상태로 재지 않는다) ⑥벤치
⑦**벤치 후 `inference compute` 라벨을 서버 기동 시각 이후 줄만 읽어 확정**(2026-08-22 도구 결함 10회차 재발 방지).
마지막에 프리셋 간 비교표(회차별 CommitFree_GB·고아 llama-server 수 포함)를 출력한다. Windows 고성능 전원 계획도 함께 적용하며 되돌리는 명령을 출력한다
(`-SkipPowerPlan`으로 생략 가능).

| 프리셋 | 내용 | 측정 모델 | 소요 |
|---|---|---|---|
| `baseline` | 현행 확정 조건(ctx 8192 · np 1 · flash off · `VULKAN=0`) — 비교 기준선 | 3b·7b·27b·30b-a3b | ~2분 |
| `power140` | baseline + 전면 버튼 140W 수기 확인(`-PowerMode140W` 필수) | 3b·7b·27b·30b-a3b | ~2분 |
| `resident` | L6 상주 정책 — **같은 모델 재방문 시 `load_ms`가 0에 수렴하는지** | 1.5b·3b·7b **× 2회** (`-NoUnload`) | ~1분 |
| `rocm` | flash on · `VULKAN=0` — `vulkan`과 백엔드 레버 하나만 다름 | 3b·7b·27b·30b-a3b | ~2분 |
| `vulkan` | L3 백엔드 대조 — `OLLAMA_VULKAN=1`+`IGPU_ENABLE=1`로 Vulkan 장치를 살린다 | 3b·7b·27b·30b-a3b | ~2분 |
| `vulkan_forced` | `OLLAMA_LLM_LIBRARY=vulkan`으로 ROCm 후보까지 제외(라벨 혼재 해소용) | 3b·7b·27b·30b-a3b | ~2분 |

**5개 전부 = 약 12분** (2026-08-25 실측: 11:26 기동 → 11:33 완료).

> **`resident`의 모델이 다른 이유** — 상주 효과는 *같은 모델을 다시 부를 때* 드러나므로 3모델을 2회씩 방문한다.
> 27B(16.2GB)를 넣지 않는 것은 의도적이다: 3모델 합이 22GB가 되어 **커밋 여유 20GB 천장을 넘고, 그러면
> 상주가 아니라 실패를 재현하게 된다**. 1.5b+3b+7b = 7.1GB는 안전하다.

> ⚠️ **전면 버튼(54/85/140W)은 OS에서 못 바꾼다.** 스크립트는 Windows 전원 계획만 고성능으로 돌린다 —
> 140W는 **눈으로 확인**해야 한다.

### Phase 3. 전원 모드 140W (수동 참고)
전면 버튼으로 Performance 전환 → `tune_and_bench.ps1 -Presets "power140" -PowerMode140W`로 재측정.
**반드시 baseline과 별도 실행이어야 한다**(같은 실행이면 물리 전원 상태가 같아 비교가 무효 — §5 OPS-51 ①).

### Phase 4. 백엔드 스위치 — **창 2개** ⚠️

> 이 Phase에서 **창 B는 `ollama serve`가 점유**한다. 창 B에 다른 명령을 붙여넣지 말 것.
> **창 B에서 Ctrl+C는 "복사"가 아니라 서버 중단 신호다.**

먼저 트레이의 Ollama를 **Quit**으로 완전 종료한다.

```powershell
# ── 창 B (서버 전용 · 이후 조작 금지) ──────────────────────────────
# [실행 시스템] Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:OLLAMA_DEBUG="1"; $env:OLLAMA_VULKAN="1"; $env:OLLAMA_IGPU_ENABLE="1"
ollama serve
```

```powershell
# ── 창 C (측정용 · 새 창) ─────────────────────────────────────────
# [실행 시스템] Windows PowerShell (Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\bench_ollama.ps1 -Label vulkan
```

ROCm 경로도 같은 방식으로 (창 B를 Ctrl+C로 내리고 다시):
```powershell
# ── 창 B (서버 전용 · 이후 조작 금지) ──────────────────────────────
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:OLLAMA_DEBUG="1"; $env:OLLAMA_VULKAN="0"; $env:HSA_OVERRIDE_GFX_VERSION="11.5.1"
Remove-Item Env:\HIP_VISIBLE_DEVICES -ErrorAction SilentlyContinue   # 있으면 GPU가 꺼진다
ollama serve
```
```powershell
# ── 창 C (측정용) ────────────────────────────────────────────────
cd C:\Users\kiki\Desktop\__AI\WhyMath
powershell -ExecutionPolicy Bypass -File .\scripts\ops\bench_ollama.ps1 -Label rocm
```

> 창 B의 로그에서 `gfx1151` / `8060S` / `ROCm` / `Vulkan` / `library=` 줄을 찾아 evidence 파일에 함께 남긴다.
> **`ollama serve`가 "address already in use"로 죽으면** 좀비 프로세스가 11434를 잡고 있는 것이다(2026-07-17 선례).
> `Get-NetTCPConnection -LocalPort 11434 | Select OwningProcess` 로 확인 후 종료한다 — `/health` 응답이나 프로세스 존재는 **성공 근거가 아니다**.

### Phase 5. 상주 정책 (L6) 적용 후 **왕복 지연** 재측정
§3 L6의 환경변수를 박고 Ollama 재시작 → `-Label resident`로 재측정. 여기서는 t/s보다 **`load_ms`가 0에 수렴하는지**가 판정치다.

### Phase 6 (조건부). standalone llama.cpp / WSL ROCm
Phase 1~5로 §2 기대치에 도달했으면 **하지 않는다**. 도달 못 했을 때만 진행하며, WSL2 경로에는 **ROCm이 .wslconfig 메모리에 묶여 96GB UMA를 못 쓰는** 알려진 제약이 있다 [문헌] — Windows 네이티브가 먼저다.

---

## 5. 진단표 (측정 기록)

| Phase | 설정 | `gpu_fraction` | `gen_tps` (7b) | `gen_tps` (27b) | `prompt_tps` | 판정 |
|---|---|---|---|---|---|---|
| 0 | 현행 그대로 | | | | | **환경 실측 완료 2026-08-22**(아래) · 2026-08-25 재측정 완료 |
| 1 | ctx 8192 · np 1 · 고아 정리 | **1.0** | **42.3** | **11.9** | 293~2,331 | ✅ **10/10 성공** (MoE 30B = 71.5) |
| 2 | VGM 64GB | — | — | — | — | ✅ **이미 충족**(카브아웃 64.4GB 실측) — 조정 불요 |
| 3 | +140W | 1.0 | 40.1 | 11.7 | 310~2,635 | ⚠️ **판정 유보** — 같은 실행의 baseline과 물리 전원 상태가 동일(2026-08-25). 전원 레버는 별도 실행 2회 필요(아래 ①) |
| 4a | Vulkan (`OLLAMA_VULKAN=1`+`IGPU_ENABLE=1`) | 1.0 | 42.4 | 11.9 | 315~2,577 | ✅ 라벨 잡힘 — 다만 `ROCm / gfx1151`과 `Vulkan / 0.0` 혼재 → §5 2026-08-25 |
| 4b | ROCm (`OLLAMA_VULKAN=0`) | 1.0 | 42.6 | 12.0 | 313~2,489 | ✅ 라벨 확정 `ROCm / gfx1151` — 2026-08-25 |
| 5 | 상주 정책 | 1.0 | 42.1 (재방문 load 3.1 ms) | — | 1,467~5,490 | ✅ 재방문 로드 3~4 ms — 2026-08-25 |
| 6 | ROCm 7.2.1 DLL 교체(Ollama 경유) | 1.0(GPU offload 정상) | — | — | 30b-a3b만: 왕복 13.93s | ⚠️ **부분 실측**(OPS-52, 2026-08-23) — +20% 미달·dense 미측정·진짜 standalone 미시행. 상세 = 아래 |

**기대 기준선**(§2 [계산]): 7b = 30~41 t/s · 27b = 8.5~11 t/s · 1.5b = 141~179 t/s

### Phase 0 1차 실측 (2026-08-22 · `evidence_20260822_003545`)

| 항목 | 실측값 | 판정 |
|---|---|---|
| 호스트 | `NUCBOX_EVO-X2` / GMKtec NucBox_EVO-X2 | — |
| CPU | AMD RYZEN AI MAX+ 395 · 16C/32T | — |
| GPU | AMD Radeon(TM) 8060S · driver `32.0.31035.1003`(2026-07-24) · Status OK | ✅ 드라이버 정상 |
| 메모리 | 16GB × 8ch @ **8000 MT/s** (설치 128.0GB) | ✅ 대역폭 전제 확인 |
| Windows 가용 | 63.6 GB | — |
| **GPU 카브아웃** | **64.4 GB** | ✅ **VGM 이미 64GB — L1 충족** |
| OS | Windows 11 Pro 26200 | — |
| 전원 계획 | `4e2a2b94-…` (Camomile) | ⚠️ 최고 성능 여부 미확인 → Phase 3 |
| 전용 VRAM 레지스트리 | `SecurityException` (권한 부족) | 무해 — §2로 대체 판정 |
| dxdiag | 90초 내 미생성 | 무해 — 기본 비활성으로 전환 |
| Ollama | **미수집** — v1 스크립트가 이 지점에서 정지 | 도구 결함, v2에서 수정 |

### Phase 0 완주 (2026-08-22 07:38 · `evidence_20260822_073859` · 9/9 `[OK]`)

| 항목 | 실측값 | 판정 |
|---|---|---|
| **백엔드** | `library=ROCm compute=gfx1151 type=iGPU total=99.7 GiB` | ✅ **ROCm이 이미 GPU를 잡고 있다** |
| Vulkan 장치 | `dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1` | iGPU라 자동 제외 → Phase 4에서 살려 비교 |
| Ollama | `0.32.15` · server UP (`0.0.0.0:11434`) | ✅ |
| 전용 VRAM(레지스트리) | **65,536 MB = 64.0 GB** | ✅ 카브아웃 추정 64.4GB와 0.4GB 차 = 펌웨어 예약 |
| ROCm 보고 VRAM | 99.7 GiB | 전용 64GB + 공유(RAM 절반 ~32GB) 합산치 |
| **기본 컨텍스트** | **`default_num_ctx=262144`** (VRAM 기반 자동) | 🔴 **과대** — L6 참조 |
| `OLLAMA_NUM_PARALLEL` | 4 | 🔴 KV × 4 |
| `OLLAMA_FLASH_ATTENTION` | false | 🔴 꺼짐 |
| `OLLAMA_MAX_LOADED_MODELS` | 2 | ⚠️ 라우터 6핀 대비 부족 |
| `OLLAMA_KEEP_ALIVE` / `OLLAMA_MODELS` | 10m / `D:\ollama_models` | — |
| 전원 계획 | `381b4222…` = **균형 조정(Balanced)** | ⚠️ 고성능 아님 → Phase 3 |
| 설치 모델 15종 | `qwen3.5:27b`(dense) · **`qwen3:30b-a3b`·`qwen3-coder:30b`(MoE)** · `qwen2.5:{3b,7b,14b,32b}` · `qwen2-math:{1.5b,7b}` · `qwen3-vl:8b` · `deepseek-r1:32b` · `gpt-oss:20b` · `llama3.3`(39.6GB) · `bge-m3` | ✅ **dense↔MoE 대조에 필요한 모델이 이미 전부 있다** |

### Phase 0 재측정 (2026-08-25 10:55 · `evidence_20260825_105523` · 10/10 `[OK]`)

| 항목 | 실측값 | 판정 |
|---|---|---|
| 카브아웃 | 64.4 GB (레지스트리 65,536 MB) | ✅ 08-22와 동일 — VGM 불변 |
| 커밋 여유 | **219.5 GB** · 고아 llama-server **0** | ✅ 08-22의 커밋 고갈(0.9 GB)과 대조 — 재시작 후 정상 |
| 전원 | Windows 고성능 계획 + 전면 버튼 140W 수기 확인 플래그 | ✅ Phase 3 조건 |
| GPU 클럭/온도 | 표준 WMI 미지원 → N/A | ⚠️ Adrenalin/AMDSmiCLI 필요 — "획득 가능 시" 조건으로 기록 |
| 서버 로그 GPU 탐지 줄 | 0건 | ⚠️ 트레이 앱 경로라 `server.log` 갱신이 없을 수 있음 — §5 OPS-51 재측정의 벤치 후 라벨로 대체 |
| **잔해 환경변수** | `OLLAMA_VULKAN`(기본값 true)·`OLLAMA_LLM_LIBRARY=vulkan`이 남아 있으면 **CPU 폴백** 재현 | 🔴 도구 결함 11회차 — §5 OPS-51 재측정 참조 |

### Phase 1 베이스라인 1차 (2026-08-22 07:54 · `bench_baseline_20260822_075405.csv`)

| 모델 | gen t/s | prompt t/s | gpu_fraction | ctx | 기대치(§2) | 판정 |
|---|---|---|---|---|---|---|
| `qwen2-math:1.5b` | **163.3 / 164.6** | 5,262 / 91,950 | **1.0** | 4096 | 141~179 | ✅ **기대 범위 적중** |
| 나머지 7종 | — | — | — | — | — | 🔴 **HTTP 500 전건 실패** |

**이 결과가 확정한 것 2가지**
1. **GPU 추론이 실제로 작동한다** — `gpu_fraction=1.0`(전량 GPU) + 164 t/s.
2. **§2의 대역폭 상한 계산 모델이 이 머신에서 검증됐다** — 예측 141~179 t/s, 실측 164 t/s.
   ⇒ 같은 모델로 예측한 **dense 27B ≈ 8.5~11 t/s** 역시 신뢰할 수 있는 수치다.

**500 연쇄 — 미규명 [측정 중]**
- 성공한 유일한 모델의 `ctx = 4096`(이 모델의 학습 컨텍스트 상한). 실패한 7종은 모두 **더 긴 컨텍스트를 지원**하는 모델이다.
- ⇒ **가설**: 기본 컨텍스트 262,144(L6 참조)가 이 7종에는 그대로 적용돼 KV 할당이 실패한다. 1.5b만 자기 상한 4096에 걸려 살아남았다.
- **이 가설은 아직 검증되지 않았다.** 1차 도구가 500의 *응답 본문*을 버리고 예외 타입명만 남겨 원인 판정이 불가능했다(도구 결함, 수정 완료).

### 🔴 로드 실패 근본 원인 (2026-08-22 08:01 · `bench_diag` 로그)

`qwen3:30b-a3b`(qwen3moe) 로드 시퀀스가 로그에 그대로 남았다:

```
1차: alloc_tensor_range: failed to allocate ROCm_Host buffer of size 16049422336   (14.95 GiB, 호스트)
     → "reducing automatic context and retrying once"  old_num_ctx=262144 → new_num_ctx=32768
2차: ggml_backend_cuda_buffer_type_alloc_buffer: allocating 17524.43 MiB on device 0:
     cudaMalloc failed: out of memory
     alloc_tensor_range: failed to allocate ROCm0 buffer of size 18375698432        (17.11 GiB, 디바이스)
```

그런데 같은 로그에서 fitter는 **"메모리 충분"** 이라고 판단했다:

```
| ROCm0 | 102129 = 101832 + (29980 = 17524 + 12288 + 168) + -29683 |
projected to use 29980 MiB vs 101832 MiB free → "no changes needed"
system memory total=63.6 GiB free=36.5 GiB free_swap=2.8 GiB
gpu memory library=ROCm available=99.1 GiB free=99.6 GiB
```

**핵심**: 보고된 free 99.6 GiB와 실제 할당 가능량이 다르다. 메모리 회계의 `unaccounted`가 **-29,683 MiB(음수)** 인 것이
그 불일치의 지문이다. 문헌의 Windows Strix Halo 할당 이슈(ROCm #5940 — Windows에서 hipMalloc이 VRAM 대신 shared로
새거나 실패)와 부합한다.

**확정된 것**: 1.5b(0.9GB, ctx 4096)는 성공, MoE 30B(17.3GB)는 실패. **실제 천장은 그 사이 어딘가이며 아직 미측정이다.**

### 🔴 사다리 측정 결과 — **모델 크기 문제가 아니다** (2026-08-22 08:07 · `bench_ladder`)

`OLLAMA_CONTEXT_LENGTH=8192` 적용 상태에서 7종 전건 실패. 실패한 **할당 크기**를 작은 순으로 세우면:

| 모델 | 실패한 할당 | 버퍼 종류 |
|---|---|---|
| `qwen3.5:27b` | **1.00 GiB** | **CPU** (+ `0xc0000409` 스택 오버런 크래시) |
| `qwen3-vl:8b` | **1.38 GiB** | **CPU** |
| `qwen2.5:3b` | **1.79 GiB** | ROCm0 |
| `qwen2.5:7b` | 4.07 GiB | ROCm0 |
| `qwen2.5:14b` | 7.96 GiB | ROCm0 |
| `gpt-oss:20b` | 11.75 GiB | ROCm0 |
| `qwen3:30b-a3b` | 17.11 GiB | ROCm0 |

**판정 전환**: 천장이 낮은 게 아니라 **천장이 없다시피 하다**. 1.00 GiB짜리 **CPU 버퍼**(GPU가 아니다) 할당조차 실패했다.
그 시점의 시스템 상태:

```
system memory total=63.6 GiB  free=34.9 GiB  free_swap=891.3 MiB
gpu memory library=ROCm available=99.1 GiB free=99.6 GiB
```

**물리 여유 34.9 GiB에서 1.0 GiB CPU 할당이 실패한다** — 이건 물리 메모리 문제가 아니라
**Windows 커밋 한도(= 물리 RAM + 페이지파일)** 문제다. `free_swap`이 07:56 **2.8 GiB** → 08:08 **891 MiB**로
줄어든 것이 그 지문이다. 페이지파일이 고갈되면 커밋 한도가 막히고, 물리 여유와 무관하게 모든 대형 할당이 거부된다.

⇒ **대책 사다리의 순서가 바뀐다. 페이지파일이 1순위다.**

### 🔴 구속 자원은 **Windows 커밋 여유** — 그리고 고아 `llama-server` (2026-08-22 08:2x 실측)

| 지표 | 값 | 해석 |
|---|---|---|
| 커밋 한도 | 255.6 GB | 물리 63.6 + 페이지파일 192 |
| **커밋 여유** | **0.9 GB** | 🔴 **진짜 벽.** llama.cpp의 `free_swap=891.3 MiB`와 정확히 일치 |
| 페이지파일 | 할당 192 GB / 사용 **1.0 GB** | ✅ **넉넉하다 — 페이지파일 확대 가설은 기각** |
| 물리 여유 | 34.9 GB | 물리 메모리는 문제가 아니다 |

**고아 프로세스 실측**: `/api/ps`는 "상주 모델 0건"인데 `llama-server` 프로세스가 **2개** 살아 있었다
(시작 시각 **2026-08-21 08:47 / 09:22** — 하루 전부터 남아 있었다). 강제 종료하자:

```
CommitFree_GB : 0.9  →  20.2      (고아 2개가 잡고 있던 커밋 = 19.3 GB)
```

⇒ **실패한 로드가 남긴 고아가 커밋을 점유해 다음 로드를 실패시키는 자기증식 구조**다.
첫 실패 이후의 모든 측정이 이 오염 위에서 이루어졌다.

**미규명 [측정 중]**: 고아를 치운 뒤에도 커밋 점유가 235 GB로 남는다. 물리 여유 34.9 GB·페이지파일 사용 1.0 GB와
산술이 맞지 않으므로 커밋 회계에 다른 요인이 있다. **"llama-server가 ROCm 힙 99.7 GiB를 각각 매핑한다"는 가설은 기각**
(고아 2개의 실제 점유는 19.3 GB였다). 원인을 더 파기 전에 **20.2 GB 여유에서 어디까지 로드되는지**를 먼저 잰다.

> 🚨 **정정 (2026-09-10, `SEC-34`)**: 이 "미규명 235 GB"는 미규명이 아니었다 — §5 "커밋 고갈 2회차"의
> 09-10 정정 박스가 밝힌 무단 채굴 감염(위장 예약 작업)과 같은 지문이다(회수량 자릿수·시점 정합).
> 아래의 "재시작으로 해소된다" 결론은 **대증 요법을 원인 규명으로 오인한 것**이었다 — 정정은 바로 아래
> "① 커밋 미스터리 해소" 절 참조.

**후보 대책 사다리** (위에서부터 싸고 되돌리기 쉬운 순서)

| # | 대책 | 근거 | 되돌리기 |
|---|---|---|---|
| **1** | **고아 `llama-server` 정리 → Ollama 재시작** | 🔴 **1순위(08:2x 실측 확정)** — 커밋 여유 0.9→20.2 GB 회복. 매 측정 **전에** 확인한다 | 없음(정리일 뿐) |
| ~~1b~~ | ~~페이지파일 확대~~ | ❌ **기각** — 이미 192 GB 할당·1.0 GB 사용. 부족하지 않았다 | — |
| 2 | `OLLAMA_CONTEXT_LENGTH=8192` + `OLLAMA_NUM_PARALLEL=1` | 로그의 `-c 131072 -np 4`가 컨텍스트만 12,288 MiB를 먹었다. 둘은 **곱해지므로 하나의 KV 예산 레버**로 다룬다. ctx는 적용됐고 np는 재시작 대기 | 환경변수 삭제 |
| 3 | Vulkan 백엔드(`OLLAMA_IGPU_ENABLE=1`) | 할당 경로가 ROCm과 다르다. 속도 비교가 아니라 **우회 수단**으로 먼저 쓴다 | 환경변수 삭제 |
| 4 | VGM 하향(64GB → 32GB) | 호스트 할당이 실패하는 상황이면 Windows 가용 RAM 63.6GB가 오히려 병목이다. **반직관적이므로 1~3 실패 후에만** | Adrenalin 원복 + 재부팅 |

**모델 크기 사다리로 천장을 먼저 잰다** — 대책을 고르기 전에 "어디까지 되는가"를 알아야 한다:
`qwen2.5:3b`(1.8) → `qwen2.5:7b`(4.4) → `qwen3-vl:8b`(5.7) → `qwen2.5:14b`(8.4) → `gpt-oss:20b`(12.8) → `qwen3.5:27b`(16.2) → `qwen3:30b-a3b`(17.3)

### ✅ Phase 1 확정 측정 (2026-08-22 08:29 · `bench_clean_20260822_082902.csv` · 10/10 성공)

`OLLAMA_CONTEXT_LENGTH=8192` · `NUM_PARALLEL=1` · 고아 프로세스 정리 후. **전 모델 `gpu_fraction = 1.0`(전량 GPU).**

| 모델 | 크기 | **생성 t/s** | 예측(§2) | 유효 대역폭 | 효율 | prefill t/s | 로드 |
|---|---|---|---|---|---|---|---|
| `qwen2.5:3b` | 2.0 GB | **83.4** | 70~90 | 167 GB/s | 65% | 2,331 | 3.0s |
| `qwen2.5:7b` | 4.7 GB | **42.3** | 30~38 | 199 GB/s | 78% | 1,230 | 4.8s |
| `qwen2.5:14b` | 8.4 GB | **22.2** | — | 187 GB/s | 73% | 662 | 7.5s |
| `qwen3.5:27b` (dense) | 16.2 GB | **11.9** | 8.5~11 | 193 GB/s | 75% | 293 | 16.0s |
| **`qwen3:30b-a3b` (MoE)** | 17.3 GB | **71.5** | 74~94 | — | — | 1,148 | 13.4s |

**① 대역폭 모델이 전 구간에서 검증됐다** — dense 4종의 유효 대역폭이 **167~199 GB/s(피크 256의 65~78%)** 로 일관된다.
즉 §2의 `상한 ≈ 대역폭 ÷ 활성 가중치`는 이 하드웨어에서 **실측으로 성립하는 법칙**이다. 예측 범위도 전부 적중하거나 소폭 상회했다.

**② dense 27B → MoE 30B-A3B = 생성 6.0배, prefill 3.9배** 🔴
같은 17GB급 적재량인데 MoE는 토큰당 **약 2.7 GB**만 읽는다(dense 27B는 16.2 GB 전량). 이 프로젝트에서 가장 큰 단일 레버다.

**③ 로드 시간이 지연을 지배한다** — 27B 로드 16.0초 vs 생성 128토큰 10.7초. **모델 스왑 1회가 생성보다 비싸다**(L6 근거 실측 확정).

**④ 커밋 여유는 20.7 → 20.9 GB로 안정** — 고아 프로세스 0. **정리만으로 전건 실패가 전건 성공이 됐다.**

**⑤ 도구 결함 7회차(같은 실행에서 발견·수정)**: 2회차 prefill이 **프롬프트 캐시 히트**라 43,542 t/s 같은 허수를 냈다.
위 prefill 열은 캐시 없는 1회차 값이다. 대책 = 매 실행 고유 접두사로 캐시 무력화 + 요약의 중앙값을 하위 중앙값으로 정정
(`floor(n/2)`는 n=2에서 *최댓값*을 골랐다).

### ⚠️ 재현성 — 같은 조건 두 번 측정이 8~18% 벌어졌다 (2026-08-22)

`clean`(08:29)과 `baseline`(09:40)은 **같은 설정**(ctx 8192 · np 1 · flash off · 전원 균형)인데 결과가 다르다:

| 모델 | clean 08:29 | baseline 09:40 | 차이 |
|---|---|---|---|
| `qwen2.5:3b` | 83.4 | 76.1 | **−8.8%** |
| `qwen2.5:7b` | 42.3 | 39.8 | −5.9% |
| `qwen3.5:27b` | 11.9 | 11.7 | −1.8% |
| **`qwen3:30b-a3b`** | 71.5 | **58.7** | **−17.9%** |
| 27B 로드 | 16.0s | 23.4s | +46% |

**[미규명]**. 후보: ①전원 상태(전면 버튼 54/85/140W는 OS에서 안 보인다 — 두 측정 사이에 달랐을 수 있다)
②발열에 따른 클럭 하강 ③배경 부하. **MoE가 가장 크게 흔들린 것**은 이 모델이 전문가 라우팅으로
메모리 접근 패턴이 불규칙해 캐시·전력 상태에 민감하다는 가설과 부합하나 확인되지 않았다.

**측정 규칙에 반영**: 프리셋 간 차이가 **20% 미만이면 유의하다고 말하지 않는다.** 이 재현성 폭이 그만큼이다.
전원 레버(L2)를 고정한 뒤 다시 재는 것이 우선이며, 그래서 오케스트레이터가 고성능 계획을 **없으면 만들어서** 적용한다.

> ✅ **캐시 무력화는 작동 확인**: 이번 런의 `prompt_tps`는 run1 2,488 / run2 2,487로 일치한다.
> 이전 런의 43,542 t/s 같은 허수가 사라졌다.

### ✅ 프리셋 3종 완주 (2026-08-22 21:17~21:20 · 고성능 전원 계획 적용 · `bench_{baseline,resident,vulkan}_2026082221*`)

#### ① 커밋 미스터리 해소 — 재시작이 답이었다 [🚨 2026-09-10 정정 — 오진, 아래 참조]

`CommitFree_GB`가 **20.9 → 205.5 GB**로 돌아왔다. 커밋 한도 255.6 GB 중 정체불명의 235 GB를 점유하던 것은
**시간이 지나며 누적되는 상태**였고, 머신 재시작으로 해소된다. ⇒ **운영 규칙: 로컬 LLM을 쓰는 머신은 주기적으로 재시작한다.**
(어제의 전건 로드 실패는 이 누적 + 고아 프로세스의 합작이었다.)

> 🚨 **정정 (2026-09-10, `SEC-34`)**: 이 운영 규칙은 **틀렸다.** "누적되는 정체불명 커밋 → 재시작으로 해소"는
> 원인이 아니라 증상 서술이었다 — 실체는 위장 예약 작업이 구동한 무단 채굴 계통이었고, 재시작은 그 프로세스를
> 정리해 증상만 지웠을 뿐 감염(예약 작업 자체)은 그대로 남겨 두어 **재발했다**(§5 "커밋 고갈 2회차" 09-10 실측).
> **올바른 운영 규칙으로 대체**: 커밋 점유와 프로세스 private 총합의 격차가 배제 4단(고아·컨텍스트·커널 풀·WSL)을
> 전부 반증하며 남으면, 재시작이 아니라 `Get-ScheduledTask`로 예약 작업·자동시작 항목을 먼저 점검한다
> (§4 "§0 위생 3종"·`.claude/commands/llm-perf-doctor.md` §0 참조). 후속 대응은 `SEC-34`가 소유한다.

#### ② 상주 정책(L6) — 재방문 로드가 **2.6 ms**, 600~900배 단축

| 모델 | 1회차 로드 | 재방문 로드 | 단축 |
|---|---|---|---|
| `qwen2-math:1.5b` | 2,353 ms | **2.6 ms** | 905배 |
| `qwen2.5:3b` | 1,587 ms | **2.6 ms** | 610배 |
| `qwen2.5:7b` | 2,340 ms | **2.6 ms** | 900배 |

**L6 가설이 실측으로 확정됐다.** 라우터가 6개 핀을 오가는 구조에서 스왑 비용이 사실상 사라진다.
`MAX_LOADED_MODELS=3` + `KEEP_ALIVE=30m`로 3모델(7.1 GB)이 전부 상주했다.

#### ③ 백엔드·flash attention — **[교란 있음, 재측정 필요]**

| 모델 | `baseline`(ROCm·flash off) | `vulkan`(IGPU_ENABLE=1·flash **on**) | 차이 |
|---|---|---|---|
| `qwen2.5:3b` | 75.2 | 81.4 | +8.1% |
| `qwen2.5:7b` | 39.8 | 41.9 | +5.2% |
| `qwen3.5:27b` | 11.7 | 11.9 | +1.9% |
| **`qwen3:30b-a3b`** | 58.2 | **70.8** | **+21.5%** (prefill +26.8%) |

⚠️ **이 비교는 그대로 결론이 될 수 없다 — 두 가지 결함이 있다.**
1. **레버 2개가 동시에 바뀌었다**(백엔드 + flash attention). 어느 쪽 효과인지 갈리지 않는다.
2. **`vulkan` 프리셋이 Vulkan을 썼다는 보장이 없다.** `OLLAMA_IGPU_ENABLE=1`은 Vulkan iGPU 장치를 *후보로 살릴 뿐*이고,
   실제 선택은 서버 로그의 `msg="inference compute" library=…`가 정본이다. 그 줄을 확인하지 않았다.

**대책(반영 완료)**: `rocm` 프리셋 신설 — `vulkan`과 **`OLLAMA_IGPU_ENABLE` 하나만** 다르다.
`baseline → rocm`이 flash attention 효과, `rocm → vulkan`이 백엔드 효과로 갈린다.
오케스트레이터는 이제 매 프리셋마다 서버가 **실제로 고른 `library`/`compute`를 출력**한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ops\tune_and_bench.ps1 -Presets "baseline,rocm,vulkan"
```

> **20% 규칙 적용**: MoE의 +21.5%만 재현성 폭(8~18%)을 넘어선다. 나머지 3종(+1.9~8.1%)은 **유의하다고 말하지 않는다.**

#### ④ 재현성 3회차 — 전원 고정 후에도 첫 회차는 여전히 높다

| 모델 | clean 08:29 | baseline 09:40 | baseline 21:17 |
|---|---|---|---|
| `qwen2.5:3b` | 83.4 | 76.1 | 75.2 |
| `qwen2.5:7b` | 42.3 | 39.8 | 39.8 |
| `qwen3.5:27b` | 11.9 | 11.7 | 11.7 |
| `qwen3:30b-a3b` | 71.5 | 58.7 | 58.2 |

2·3회차는 서로 잘 맞는다(≤1.5%). **1회차만 높다.** 즉 재현성 문제는 무작위 산포가 아니라
**1회차 특이성**일 가능성이 크다 — 그 측정만 `-NoUnload` 없이 5모델을 돌린 첫 세션이었다. **[미규명]**

#### ⑤ 도구 결함 9회차 — 빈 응답을 0 t/s로 기록

`resident`의 재방문 첫 런이 `gen 0 t/s | out  tok`으로 찍혔다(`eval_count` 없음).
0은 측정이 아니라 실패인데 정상값으로 섞여 중앙값을 오염시킨다. **대책**: `eval_count ≤ 0`이면 실패로 분류한다.

### ✅ 레버 분리 측정 — flash attention과 백엔드를 갈랐다 (2026-08-22 21:30 · 3 프리셋 각 8/8 성공)

`baseline`(flash off) → `rocm`(flash **on**) → `vulkan`(flash on + `IGPU_ENABLE=1`). 인접 프리셋은 **레버 하나만** 다르다.

#### flash attention 효과 (`baseline` → `rocm`, 둘 다 ROCm)

| 모델 | 생성 | prefill | **왕복** |
|---|---|---|---|
| `qwen2.5:3b` | +7.2% | +3.7% | −18.9% |
| `qwen2.5:7b` | +3.7% | +3.3% | −14.0% |
| `qwen3.5:27b` | −0.5% | +3.1% | −4.3% |
| **`qwen3:30b-a3b`** | **+20.3%** | **+21.7%** | **−34.8%** |

⇒ **채택.** MoE에서 20% 규칙을 넘고, 나머지도 왕복이 일관되게 줄며 **손해가 없다.**

#### 백엔드 효과 (`rocm` → `vulkan`) — **트레이드오프**

| 모델 | 생성 | prefill | **왕복** |
|---|---|---|---|
| `qwen2.5:3b` | +14.4% | −12.4% | −7.3% |
| `qwen2.5:7b` | +12.5% | −24.9% | −3.9% |
| **`qwen3.5:27b`** | +9.3% | **−75.2%** | **+68.1%** (13.1s → 21.1s) |
| **`qwen3:30b-a3b`** | **+21.2%** | **−46.7%** | +8.8% |

⇒ **ROCm 유지.** Vulkan은 문헌대로 생성에서 앞서지만 **prefill을 크게 깎는다.**
WhyMath는 긴 프롬프트·짧은 출력(PRM 단계 검증·동치 판정)이 주력이라 **왕복이 판단축**이고, 그 축에서 큰 모델이 크게 손해다.
생성 t/s만 봤다면 정반대 결론을 냈을 것이다.

> **[미확정] 백엔드 라벨** — `library=` 출력이 세 프리셋 모두 `ROCm`으로 찍혔다. 그러나 성능 지문(생성↑·prefill↓)은
> 백엔드 전환과 정확히 부합한다. **원인은 도구 결함 10회차**: 그 줄에 **시간 필터가 없어 이전 기동의 로그를 읽었을 수 있다**
> (bench 로그 tail에는 넣었던 필터를 여기엔 빠뜨렸다 — 같은 실수의 반복). 수정 완료, 다음 실행에서 확정된다.
> **결론(ROCm 유지)은 라벨이 아니라 왕복 수치에 근거하므로 이 미확정에 영향받지 않는다.**

**이 시점의 결론 전환**: 최초 질문("ROCm이 왜 안 잡히나")은 **이 머신에서 성립하지 않는다** — 이미 잡혀 있다.
실제 병목 후보는 ①과대 컨텍스트(256K) ②병렬 4 ③flash attention 꺼짐 ④전원 Balanced ⑤dense 27B의 대역폭 벽이다.

### ✅ OPS-51 재측정 — 5프리셋 완주 + 백엔드 라벨 확정 (2026-08-25 11:26~11:33 · `bench_{baseline,power140,resident,rocm,vulkan}_2026082511*`)

**전원·도구 상태**: Windows 전원 계획 고성능 · EVO-X2 전면 버튼 Performance(140W) 수기 확인 플래그(`-PowerMode140W`) ·
전 구간 `gpu_fraction = 1.0` · CommitFree 193~219 GB · 백엔드 라벨은 **벤치 후 서버 로그의 `inference compute` 줄**을 서버 기동 시각 이후로 필터해 확정.

| 프리셋 | 설정 | 3b | 7b | 27b | 30b-a3b | 백엔드 라벨 |
|---|---|---|---|---|---|---|
| `baseline` | flash off | 78.2 | 40.6 | 12.1 | 58.2 | ✅ `ROCm / gfx1151` |
| `power140` | flash off + 140W | 76.8 | 40.1 | 11.7 | 57.3 | ✅ `ROCm / gfx1151` |
| `resident` | flash on · 상주 | 83.6 (재방문 load **3.6 ms**) | 42.1 (**3.1 ms**) | — | — | ✅ `ROCm / gfx1151` |
| `rocm` | flash on | 83.5 | 42.6 | 12.0 | 72.6 | ✅ `ROCm / gfx1151` |
| `vulkan` | flash on + `VULKAN=1`+`IGPU_ENABLE=1` | 84.1 | 42.4 | 11.9 | 72.5 | ⚠️ **`Vulkan / 0.0`과 `ROCm / gfx1151` 혼재** |

**① Phase 3 (전원 140W) — 판정 유보 (측정 설계 결함, Codex 리뷰로 발견)**: 오늘 실행은 `baseline`과 `power140`을 **같은 실행**에서 연속 측정했고, 프리셋 환경은 동일하며 물리 전원 상태(전면 버튼)를 프리셋 사이에 바꾸는 단계가 없다. 즉 두 프리셋은 **같은 물리 전원 상태**에서 측정됐다. 나온 1~2% 차이는 재현성 데이터로는 유효하지만 **전원 레버 효과 판정에는 쓸 수 없다**.
⇒ 스크립트를 수정해 `baseline`과 `power140`을 같은 실행에 넣으면 중단한다. 전원 비교는 ①Balanced 상태에서 `baseline`만 측정 → ②전면 버튼 Performance(140W) 전환 → ③`power140`만 측정하는 **두 번의 별도 실행**이 필요하다(후속 측정 과제).

**② Phase 4a/4b (백엔드 라벨) — 도구 결함 10회차 재발 방지 검증 완료**: 라벨 추출이 이제 서버 기동 시각 이후 줄만 읽고,
`rocm` 계열 4프리셋은 전부 `ROCm / gfx1151`, `vulkan`은 `Vulkan / 0.0` + `ROCm / gfx1151` 혼재를 정확히 잡아낸다(불일치 시 경고까지 나옴).
단, `vulkan`의 혼재는 `OLLAMA_LLM_LIBRARY`를 비워 두면 **두 라이브러리가 같이 로드**되기 때문이다 — 실 계산 장치 구분은
`vulkan_forced`(`OLLAMA_LLM_LIBRARY=vulkan`)로 한 번 더 재야 한다(후속).

**③ `rocm` vs `vulkan` 성능 — 오늘은 동일(±2% 내)**: 2026-08-22 측정의 큰 차이(27b prefill −75%·왕복 +68%)가 재현되지 않았다.
두 가능성: (가) 08-22 `vulkan` 측정이 도구 결함 10회차로 라벨만 바뀐 상태였거나 다른 상태 오염이 있었다, (나) 0.32.15에서 Vulkan 경로가 개선됐다.
**백엔드 결론(ROCm 유지)은 왕복 수치 근거이므로 유지**하되, 08-22의 prefill 열화 수치는 "확정 트레이드오프"로 더 이상 인용하지 않는다.

**④ Phase 5 (상주 정책) — 재방문 로드 3.1~4.3 ms 재확인**: `MAX_LOADED_MODELS=3`에서 3모델이 전부 상주.
단 재방문 첫 런 1건이 빈 응답으로 실패했다 — 도구 결함 9회차 대책(`eval_count ≤ 0` → 실패 분류)이 정상 작동해 중앙값 오염은 없었다.

**⑤ 재현성 1회차 특이성 가설 축소**: baseline MoE(30b-a3b)는 3일에 걸쳐 **58.7 → 58.2 → 58.2**로 안정.
반면 1회차(clean 08:29) 71.5는 오늘 flash-on 측정(rocm 72.6, vulkan 72.5)과 일치한다.
⇒ 가설이 "**1회차 측정은 flash attention이 켜진 상태였다**"로 축소된다. 단 08:29 당시 evidence(07:38)는 `FLASH_ATTENTION=false`였으므로
확정은 아니다. 발열·전원 가설은 ①의 측정 설계 결함으로 **판정 유보**(오늘 power140 비교는 무효) — 별도 실행 2회로 다시 재야 한다.

**추가 정정 (2026-08-25 Codex 리뷰 반영)**:
- 오늘 CSV의 `orphan_llama_servers` 열은 **정상 runner까지 포함한 값**이었다(모델 로드 중 llama-server 1개가 떠 있으면 1로 기록).
  스크립트를 수정해 `/api/ps` 로드 수를 뺀 값만 고아로 기록한다. 오늘 값(1~3)은 실제 고아 0 + 상주 모델 수로 읽어야 한다.
- `gpu_temp_c`는 표준 WMI로 GPU 온도를 식별할 수 없어 **항상 null**로 기록한다 — ACPI thermal zone의 첫 값을 GPU로 단정하지 않는다.

**도구 결함 11~13회차 (이번 세션에서 발견·수정)**
- **11회차 — `OLLAMA_VULKAN` 기본값이 true (Ollama 0.32.15)**: 명시 없이 `IGPU_ENABLE`만 지우면 Vulkan이 기본 활성으로 남아
  CPU 폴백(`gpu_fraction=0`, 3b 40 t/s·27b 5.8 t/s)이 재현된다. ROCm 계열 프리셋에는 `OLLAMA_VULKAN=0` 명시 필수. 프리셋표에 반영.
- **12회차 — 실효 설정 대조가 stale server config를 읽음**: `Test-EffectiveConfig`에 시간 필터(기동 시각 이후)가 없어
  이전 기동의 `server config` 줄을 읽고 정상 상태를 MISS로 중단시켰다. 기동 직전 시각(`ServerReadyAt`) 이후 줄만 읽게 수정.
- **13회차 — 한글 포함 .ps1은 UTF-8 BOM이 없으면 파서가 통째로 깨진다**: 에이전트 편집 도구가 BOM을 벗겨 Windows PowerShell 5.1이
  ANSI로 읽으며 구문 오류 발생. 세 스크립트에 BOM을 유지하고, 콘솔 인코딩 설정을 `param` 블록 **이후**로 이동했다
  (`param` 앞의 실행문은 특정 조건에서 파싱을 막는다).

### ⚠️ Phase 6 실측 — ROCm 7.2.1 DLL 교체 시도, 진짜 standalone llama-server는 미시행 (2026-08-23 실측 · OPS-52 · 2026-09-10 문서 회수)

> **회수 경위**: 이 실측은 2026-08-23에 Phaiakes9에서 실제로 실행됐으나, 원래 커밋(브랜치 `claude/ops-50-51-52-moe-rocm-followup`)이 PR #860으로 열린 채 머지되지 않고 방치됐다(라벨 `eos-postpone`). 2026-09-07 `stray-code` 7회차가 스크립트 4종(`install_rocm72_standalone.ps1`·`activate_rocm72_standalone.ps1/py`·`restore_rocm72_builtin.py`)만 main으로 회수했고, 이 결과 서술은 2026-09-10 OPS-52 세션이 PR #860 diff에서 추가로 포팅했다. **스크립트 자체는 재검증(정적 검사 `check_ps_scripts.py` 통과·`py_compile` 통과)했지만, 아래 수치는 2026-08-23 원 실행 결과를 그대로 인용한 것이며 이 세션이 재실행하지는 않았다.**

**방법**: AMD 공식 ROCm 7.2.1 Windows wheel 3종(`rocm_sdk_core`/`rocm_sdk_devel`/`rocm_sdk_libraries_custom`, `repo.radeon.com/rocm/windows/rocm-rel-7.2.1`)을 `work/rocm-7.2.1-standalone/`에 `pip install --target`(격리·비침습)로 설치한 뒤, Ollama 0.32.15의 내장 HIP DLL(`amdhip64.dll`/`hipblas.dll`)을 standalone 7.2 빌드로 교체(`amdhip64_7.dll → amdhip64.dll` 별칭 복사)하고 Ollama를 재기동해 측정했다. **이것은 acceptance ②가 요구하는 "standalone llama-server(OpenAI 호환 API)"가 아니다** — Ollama 서버·API·모델 로더는 그대로이고 HIP 런타임 DLL만 바뀐, 더 가벼운 변형이다. 다만 WhyMath L3 라우터는 경유하지 않고 Ollama API에 직접 요청했다.

| 조건 | 왕복 지연(첫 호출·64토큰) | 비고 |
|---|---|---|
| 내장 ROCm 7.1(대조군) | 15.99s (eval 46.56 t/s) | `rocm_v7_1/amdhip64_7.dll` — Ollama가 버전별 서브디렉터리로 선택하는 정식 경로 |
| standalone ROCm 7.2.1 DLL 교체 | 13.93s | GPU offload 정상(`size_vram` 18GB), 모델 로드 성공. eval t/s는 원 실행 로그에 미기록 |

- **판정**: (15.99 − 13.93) / 15.99 = **12.9% 단축** — §3 L4의 +20% 기준 **미달**.
- **원 자료 간 불일치 (정직하게 남긴다)**: 이 실측을 담은 원 커밋(f663eda6)의 서술은 "이득이 없었다"라고 적었고, 같은 작업을 요약한 PR #860 본문은 "생성 속도가 현저히 느려"라고 적었다 — 그러나 위 표의 왕복 수치(13.93s < 15.99s)만 보면 방향이 반대(더 빠름)다. 이 세션은 재실행 접근이 없어(Windows/gfx1151 실물 하드웨어가 이 세션에 없음) 어느 서술이 맞는지 판정하지 않는다. **다만 +20% 결정에는 영향이 없다** — 12.9% 단축으로 읽어도 기준 미달이라는 결론은 바뀌지 않는다.
- **ABI/버전 경로 리스크**: Ollama 0.32.15는 HIP 런타임을 `rocm_v7_1/` 같은 버전별 서브디렉터리로 명시 선택하도록 빌드돼 있다. 이번 시도의 `amdhip64_7.dll → amdhip64.dll` 별칭 복사는 이 버전 선택 로직을 **우회**하는 비공식 경로라, 표면적 동작(모델 로드·생성 성공)과 별개로 잠재적 미검증 거동(정밀도 저하·드문 커널 실패 등)이 있을 수 있다.
- **범위 한계 (acceptance ② 대비)**: `qwen3:30b-a3b`(MoE)만 측정했고 **dense `qwen3.5:27b`는 이 시도에서 측정하지 않았다**. 진짜 standalone `llama-server`(Ollama 밖에서 새로 빌드·기동하는 OpenAI 호환 API 서버)도 시도하지 않았다.
- **왜 여기서 멈췄는가**: Phase 1~5가 이미 §2 기대 기준선(§5 진단표)을 만족했고, 이 가벼운 DLL-교체 실험조차 +20% 기준에 못 미쳐 신호가 부정적이었다. 정식 standalone `llama-server`를 새로 빌드·검증하는 것은 Ollama 재현보다 훨씬 큰 엔지니어링 투자(HIP SDK로 llama.cpp 소스 빌드 또는 release 바이너리 검증·모델 변환·OpenAI 호환 어댑터)인데, 이미 나온 두 신호(미달 폭·ABI 우회 리스크)가 기대값을 낮춘다고 판단해 보류했다. 재검토 트리거는 **Ollama가 ROCm 7.2를 공식 지원**하거나 **§2 기대 기준선을 밑도는 상황이 재발**할 때다.
- **도구**(재현 명령, Phaiakes9 전용):
  ```powershell
  # 창 A (리포 루트) — 다운로드·설치만
  cd C:\Users\kiki\Desktop\__AI\WhyMath
  powershell -ExecutionPolicy Bypass -File .\scripts\ops\install_rocm72_standalone.ps1 -Phase DownloadInstall
  # 적용·시험 (Ollama 종료·재기동 포함 — 다른 Ollama 사용자 없는지 확인 후)
  powershell -ExecutionPolicy Bypass -File .\scripts\ops\install_rocm72_standalone.ps1 -Phase ActivateAndBench
  # 원복(내장 ROCm 7.1로 되돌림)
  python .\scripts\ops\restore_rocm72_builtin.py
  ```
  Python 등가 경로: `scripts/ops/activate_rocm72_standalone.py`(설치 이후 적용·시험 단계만 수행).
- **원복 확인**: 원 실행(2026-08-23)에서 `restore_rocm72_builtin.py`로 내장 ROCm 7.1 복원 및 정상 동작을 확인했다(PR #860 서술 — 이 세션은 재확인하지 않음).

### 🔴 커밋 고갈 2회차 — **고아도 드라이버도 WSL도 아니었다** (2026-09-10 실측 · 배제 경로 확정)

`problem_corpus_accumulate`(MP-02 1회차)가 **10/10 생성 실패**로 중단됐다. 로그는 08-22와 같은 얼굴이다:

```
cudaMalloc failed: out of memory
alloc_tensor_range: failed to allocate ROCm0 buffer of size 4370558976   # 4.07 GiB
```

그런데 **1순위 처방(고아 정리)이 듣지 않았다.** 08-22 기록이 "대개 고아"라고 안내하는 지점이라, 그때
무엇을 어떤 순서로 배제했는지를 여기 남긴다 — 이번 사례의 가치는 원인 규명이 아니라 **배제 경로**다.

| # | 가설 | 실측 | 판정 |
|---|---|---|---|
| 1 | 고아 `llama-server` | `ORPHANS=0` (정리 전후 동일) | ❌ |
| 2 | 컨텍스트 폭주(`262144`) | `OLLAMA_CONTEXT_LENGTH=8192` 이미 적용 · `NUM_PARALLEL=1` · `IGPU_ENABLE` 비움 | ❌ |
| 3 | GPU 드라이버 풀 누수 | `Pool Nonpaged` **1.97 GB** · `Pool Paged` 3.17 GB | ❌ |
| 4 | WSL2 VM 백킹 메모리 | `wsl --shutdown` 후 커밋 여유 2.1 → **4.0 GB**(+1.9뿐) | ❌ |

**회계가 맞지 않는다**: 커밋 **326.4 GB** 점유인데 프로세스 **366개 전부**의 private 합이 **19.4 GB**,
커널 풀이 5.1 GB다 — 약 **302 GB가 어느 회계에도 잡히지 않는다**. 페이지파일은 `232.7 / 232.7 GB`로
**100% 소진**이었다. 프로세스도 커널 풀도 아닌 커밋은 드라이버 잠금 메모리나 페이지파일 기반 공유 섹션뿐이며,
이름까지 특정하려면 RAMMap이 필요하다 — **거기서 멈추고 재부팅했다.**

**재부팅 결과 (누적형 확정)**

| 지표 | 재부팅 전 | 재부팅 후 |
|---|---|---|
| 커밋 여유 | **2.1 GB** | **256.7 GB** |
| 페이지파일 사용 | 232.7 GB (100%) | **0.0 GB** |

즉 08-22의 "재시작이 답이었다"가 **장기 가동 시 재발**함이 확인됐다(2회차). 원인은 여전히 미규명이나,
**배제 순서 ①고아 ②컨텍스트 ③커널 풀 ④WSL이 전부 반증되면 더 파지 말고 재부팅**한다 — 넷을 재는 데
1분이면 되고, 그 뒤의 규명은 RAMMap 없이는 진척이 없다.

> ### 🚨 **정정 (같은 날 저녁) — 원인은 "미규명"이 아니었다. 침해였다.**
>
> 위 진단을 마친 뒤 Kiki가 예약 작업을 점검해 **`\Microsoft\Windows\Google\GoogleUpdateTaskSYSTEM` ·
> `\Microsoft\Windows\Google\GoogleUpdateTask`**가 ⓐ**보안 검사 예외 추가** ⓑ**외부 스크립트 다운로드·실행**
> ⓒ**채굴 의심 파일 실행**을 하고 있었음을 확인했다. 이름과 경로가 **Microsoft 트리 안의 Google 업데이터로
> 위장**돼 있어 목록을 훑는 것만으로는 눈에 띄지 않는다 — 이름이 아니라 **실행 파일·인자**를 봐야 한다.
>
> **실측(2026-09-10 · 사용자는 설치·허용한 적 없음을 확인)**
>
> | 시각(KST) | 조치 | 공유 커밋 |
> |---|---|---|
> | 16:41 | 채굴 부모·자식 프로세스 종료 | **156.699 → 3.854 GiB** (**152.845 GiB 회수**) |
> | 16:41~ | 5분간 31개 표본 관측 | 약 3.83 GiB로 **안정** · 알려진 채굴 계통 0건 |
> | 17:50 | 관리자 승인으로 자동실행 작업 2개 **비활성화** | 3.876 GiB (전체 커밋 25.517 GiB) |
>
> 16:41 시점에는 작업 비활성화가 **접근 거부로 실패**해 재실행 경로가 남아 있었고, 17:50에 관리자 토큰으로
> 둘 다 `Enabled=false · State=Disabled`가 됐다(변경 전 FAIL → 변경 후 PASS로 독립 검증). 변경 전 원문 XML은
> 백업했다.
>
> **회계에 안 잡히던 302 GB의 정체가 이것이다.** 그리고 2026-08-22의 "커밋 235GB의 정체를 모른다"도
> 같은 지문일 가능성이 높다 — 그렇다면 **약 3주간 감염 상태로 측정·운영해 온 것**이며, 그 기간의
> 로드 실패·저성능 관측 일부는 하드웨어가 아니라 침해의 결과일 수 있다.
>
> **배제 4단은 방법으로 유효하다. 다만 종착점이 바뀐다.**
> 넷이 모두 반증되고 **커밋 점유와 프로세스 private 총합의 격차**만 남으면, 그것은 "원인 미규명"이 아니라
> **회계 밖에서 무언가가 커밋을 쥐고 있다**는 뜻이다. 그때 할 일은 재부팅이 아니라 **예약 작업·자동시작
> 항목 점검**이다 — 재부팅은 증상만 지우고 감염은 남긴다.
>
> ```powershell
> # 커밋 격차가 확인됐을 때 다음 한 줄 — 이름이 그럴듯해도 경로·인자를 본다
> Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } |
>   ForEach-Object { [pscustomobject]@{ Name=$_.TaskName; Path=$_.TaskPath
>     Action=($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' | ' } } |
>   Where-Object { $_.Action -match 'powershell|curl|wget|bitsadmin|mshta|rundll32|http' } | Format-List
> ```
>
> **아직 끝난 것이 아니다.** 확인된 실행과 그 재실행 경로는 차단됐지만 **백신 검사 · 확인된 악성 파일의
> 선별 격리 · 채굴이 추가해 둔 보안 예외 원복 · 추가 침해 조사**가 남아 있다. 특히 보안 예외를 되돌리지
> 않으면 재감염이 쉽다. 프로세스 조회 0건을 **시스템 전체 악성코드 부재로 해석하지 않는다.**
>
> 후속 대응(자격증명 전량 로테이션 · 학생 데이터 노출 판정 · 재발 탐지)은 **`SEC-34`**가 소유한다.
> 이 문서의 성능 수치들도 감염 기간과 겹치는 구간은 재측정 대상이다.

**부수 소득**: 이 사례에서 하네스는 옳게 작동했다. 롤링 불량률 100%(임계 30%)에서 배치를 자동 중단하고
`generation_failed: 10`으로 원인을 분류해 남겼으며 `appended: 0`이라 코퍼스 오염이 없었다.
`prompt_cache`도 `"적중 0%가 아니다(미측정)"`로 **모른다와 아니다를 구분**해 기록했다.

---

## 6. WhyMath 적용 — 측정이 끝나면 결정할 것 4개

1. ✅ **`LOCAL_LATENCY_MS` 보정 — 불요로 판정(2026-08-22)** [코드+실측]. 실측 왕복(prefill 796자 + 128토큰)을 현행 상수와 대조:

   | 티어 | 현행 상수 | 실측 | 판정 |
   |---|---|---|---|
   | FAST (`qwen2-math:1.5b`) | 1,010 ms | 906 ms | 상수가 10% 보수적 — 유지 |
   | MID (`qwen2-math:7b`급) | 3,918 ms | 3,551 ms | 상수가 9% 보수적 — 유지 |
   | QUALITY (`qwen3:30b-a3b`) | 2,300 ms | 2,300 ms(왕복) | MoE 채택에 따라 갱신 |

   **FAST·MID는 여전히 실측보다 보수적** — 클라우드 승급 쪽으로 기우는 *안전측* 오차다.
   QUALITY는 dense 27B → MoE로 교체되면서 왕복 지연 상수를 13,886 ms → **2,300 ms**로 갱신했다.
   이 값은 ctx 8192 · np 1 · flash attention · ROCm 조건에서의 Phaiakes9 실측(§2, §6.2)이다.
2. ✅ **QUALITY 티어 재검토 → MoE 교체(2026-08-22)** [코드+실측]. `qwen3.5:27b`(dense)와 `qwen3:30b-a3b`(MoE)를 같은 결함 주입 시험지 100문항(결함 50 · 무결함 50 · seed 20260708)으로 대조. 판정은 `docs/standards/superhuman_verification_standard.md`의 Wilson 단측 경계·CLI exit 0/1. **결과: 후보(MoE)가 기준(dense)보다 열등하지 않음.**

   | 지표 | qwen3.5:27b (기준) | qwen3:30b-a3b (후보) | 비고 |
   |---|---|---|---|
   | 처리 문항 / 미분류·파싱실패 | 100 / 1 | 100 / 16 | 후보가 clean에서도 10/50, broken_latex에서 4/7 파싱 실패 |
   | 검출률 (결함 中) | 24/49 = **0.490** | 28/44 = **0.636** | 95% Wilson 하한 0.376 → 0.512 |
   | 오경보율 (무결함 中) | 3/50 = **0.060** | 2/40 = **0.050** | 95% Wilson 상한 0.141 → 0.140 |
   | 평균 지연 | **7,376 ms** | **1,408 ms** | 약 **5.2배** 빠름(§2 왕복 12.4s→2.3s와 일치) |

   **판정**: `require-candidate-not-worse-than-baseline` 마진 0.05 — exit 0. 후보의 검출률 하한(0.512)이 기준 하한(0.376)보다 높고, 오경보 상한(0.140)이 기준(0.141)과 같거나 낮다.

   **반영 완료(OPS-49)**:
   - `src/backend/whymath_backend/l3/router.py`: `QUALITY_MODEL_ID="qwen3:30b-a3b"`, `LOCAL_LATENCY_MS[QUALITY]=2300`
   - `tests/backend/l3/test_router.py`: QUALITY 해석·지연 상수 테스트 갱신
   - `AGENTS.md`: 기술 스택 표의 로컬 모델 목록에 `qwen3:30b-a3b`(QUALITY·MoE) 반영

   **주의**: 후보의 **파싱 실패율이 16%**로 기준(1%)보다 높다. 미분류된 문항은 판정에서 제외되며, 이는 “속도가 빠르지만 정답 형식을 덜 잘 따른다”는 리스크를 의미한다. clean 문항 20%, broken_latex 57%에서 실패한 점은 결함 클래스별 강인성이 불균등함을 시사한다. **운영 전에는 broken_latex 등 파싱 실패 클래스에 대한 추가 샘플링·프롬프트 엔지니어링을 권장한다.**
   - 실행기: `scripts/ops/run_moe_quality_battle.ps1`
   - 감사 파일: `data/audit/ops-48-moe-accuracy-battle-20260822_232452.jsonl`
   - 하니스: `src/backend/whymath_backend/harness/quality_tier_moe_accuracy_battle.py`

3. **로컬 vs OpenRouter 비교축** — t/s만으로 고르지 않는다. `detection accuracy` / `false alarm` / `왕복 지연` / `t/s` / `컨텍스트` / `비용` / `반복 실행 안정성` 7축으로 비교하고, **정확도 축은 결함 주입 강등전으로 판정**한다(`docs/standards/superhuman_verification_standard.md`). 로컬이 정확도에서 지더라도 지연·비용에서 이기는 구간이 있고, 그 반대도 있다.

4. ✅ **ROCm 7.2.1 standalone 시도 — 배선 변경 보류 결정(OPS-52, 2026-08-23 실측 · 2026-09-10 문서 회수)** [실측]. 상세는 §5 "Phase 6 실측" 참조. DLL 교체 방식(진짜 standalone `llama-server`가 아닌 가벼운 변형)의 왕복 지연 단축은 12.9%로 §3 L4의 +20% 기준에 못 미쳤고, HIP 런타임 버전 선택을 우회하는 비공식 경로라는 리스크도 있다. **결정: Ollama 번들 유지, `l3/router.py`·`l3/providers/ollama.py`에 신규 provider 경로를 설계하는 태스크로 승격하지 않는다.** 정식 standalone `llama-server` 빌드·isolated 벤치(acceptance ②의 원래 요구)는 Phase 1~5가 이미 §2 기대 기준선을 충족한 상태에서 추가 투자 대비 기대값이 낮다고 판단해 보류한다 — 재검토 트리거는 Ollama의 ROCm 7.2 공식 지원 또는 §2 기대 기준선 미달 재발.

---

## 7. 하지 말 것 (안티패턴)

- ❌ **여러 레버를 동시에 바꾸기** — 무엇이 효과였는지 영구히 알 수 없게 된다.
- ❌ **재설치부터 하기** — 드라이버·ROCm 재설치는 증거를 지운다. 측정이 먼저다.
- ❌ **`ollama ps`의 "100% GPU" 문자열만 보고 성공 판정** — 오프로드 비율은 맞아도 t/s가 기대치의 1/3일 수 있다. `gpu_fraction`과 `gen_tps`를 **둘 다** 본다.
- ❌ **`HIP_VISIBLE_DEVICES=-1`을 ROCm 경로에 남겨두기** — GPU가 통째로 꺼진다.
- ❌ **27B dense가 느린 것을 설정 탓으로 돌리기** — §2 물리 한계다.
- ❌ **검사 명령 출력을 `-q`/`tail`로 잘라 통과 선언** — 판정은 exit code로 한다(CLAUDE.md 2026-08-09 등재).
- ❌ **로그 tail을 시간 필터 없이 붙여 "이번 실행의 증거"로 읽기** — 실행이 아예 안 된 런에 **이전 런의 로그**가 붙어 나오면,
  없는 원인을 분석하게 된다. 실행 시작 시각 이후의 줄만 자르고, 해당 줄이 **0건이면 그 사실 자체를 보고**한다
  ("서버가 로드를 시도조차 하지 않았다" = 요청이 서버에 닿기 전에 거부됐다는 결정적 단서다).
  (사고 경위: 2026-08-22 `-Models` 파싱 버그로 실행이 안 된 두 런에 07:56 OOM 로그가 그대로 붙었다.)
- ❌ **`powershell.exe -File` 로 배열 인자를 넘기면서 콤마 분해를 기대하기** — `-File` 모드는 인자를 **문자열 그대로** 넘긴다.
  `-Models a,b` 는 원소 2개가 아니라 `"a,b"` 원소 1개로 도착해 서버에서 `invalid model name`이 된다.
  스크립트가 스스로 콤마를 분해하고, **서버에 던지기 전에 설치 목록과 대조**한다.
  (사고 경위: 2026-08-22 측정 2회가 이 한 가지 이유로 통째 공전했다.)
- ❌ **실패한 로드의 잔해를 치우지 않고 다음 측정 돌리기** — 실패한 `llama-server`는 종료되지 않고 남아 **커밋을 계속 점유**한다.
  그러면 다음 로드가 더 적은 자원으로 시작해 또 실패하고, 잔해가 하나 더 쌓인다. **실패가 실패를 만드는 자기증식**이다.
  측정 전에 `/api/ps`(상주 모델)와 `Get-Process llama-server`(실제 프로세스)를 **대조**하고, 불일치하면 정리부터 한다.
  (사고 경위: 2026-08-22, 하루 전 08:47·09:22에 뜬 고아 2개가 커밋 19.3 GB를 잡아 커밋 여유를 0.9 GB로 만들었다.
  그 상태에서 잰 사다리 측정 전체가 오염돼 있었다.)
- ❌ **물리 메모리 여유만 보고 "메모리는 충분하다"고 판정** — Windows의 구속 자원은 **커밋 한도(물리 + 페이지파일)** 이고,
  물리 여유 34.9 GB에서도 커밋 여유가 0.9 GB면 1.0 GiB 할당이 실패한다. 물리·커밋·페이지파일을 **각각** 본다.
- ❌ **HTTP 실패를 예외 *타입명*만으로 기록하기** — 500의 원인은 타입명이 아니라 **응답 본문**에 들어 있다.
  `System.Net.WebException`은 8개 모델이 전부 다른 이유로 죽어도 똑같이 찍힌다.
  (사고 경위: 2026-08-22 Phase 1 1차에서 7개 모델이 전건 500이었는데 본문을 버려 원인 판정이 불가능했고, 측정 1회가 통째로 공전했다.
  대책 = `Get-HttpErrorBody`(ErrorDetails.Message → Response 스트림 순서로 본문 추출) + 실패 시 서버 로그 tail 자동 첨부.)
- ❌ **증거 수집 도구를 "마지막에 한 번 저장" 구조로 만들기** — 중간에 한 단계가 멈추면 **앞서 모은 증거가 통째로 사라진다**.
  섹션마다 파일에 append 하고, **외부 프로세스 호출에는 전부 타임아웃**을 건다. 멈추는 명령은 "멈춘다"는 사실 자체가 증거다.
  (사고 경위: 2026-08-22 v1 첫 실행에서 §6 `ollama` CLI가 무한 대기 → 화면에는 5개 섹션이 찍혔지만 파일은 생성조차 되지 않았다.
  단일 권한 실패(레지스트리)나 단일 도구 실패(dxdiag)가 전체 수집을 무력화하지 않도록 **판정 경로를 이중화**하는 것도 같은 원칙 —
  VGM 판정이 레지스트리·dxdiag 없이 카브아웃 계산으로 성립한 것이 그 예다.)

---

## 8. 출처 (모든 [문헌] 표기의 근거)

- AMD 공식 — [FAQs: AMD Variable Graphics Memory, VRAM, AI Model Sizes, Quantization](https://www.amd.com/en/blogs/2025/faqs-amd-variable-graphics-memory-vram-ai-model-sizes-quantization-mcp-more.html)
- AMD 공식 — [AI Inference on AMD Ryzen AI Max Processor (ROCm Blogs)](https://rocm.blogs.amd.com/artificial-intelligence/ryzen-uma-llm/README.html)
- AMD 공식 — [Strix Halo system optimization (ROCm Docs)](https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html)
- Windows VRAM 할당 이슈 — [ROCm #5940 (Windows) Strix Halo: Memory allocations not going to VRAM](https://github.com/ROCm/ROCm/issues/5940)
- WSL2 제약 — [ROCm #6022 librocdxg fails to map Dedicated VRAM in WSL2](https://github.com/ROCm/ROCm/issues/6022)
- Ollama gfx1151 동작 설정 — [ollama #14855 AMD Strix Halo (gfx1151) ROCm Working Guide](https://github.com/ollama/ollama/issues/14855)
- Ollama Windows ROCm 파손 이력 — [ollama #9553](https://github.com/ollama/ollama/issues/9553) · [ollama #10993](https://github.com/ollama/ollama/issues/10993)
- Vulkan 실험 지원 — [Phoronix: ollama Rolls Out Experimental Vulkan Support](https://www.phoronix.com/news/ollama-Experimental-Vulkan) · [Ollama Hardware support](https://docs.ollama.com/gpu)
- 백엔드 비교 실측 — [llama.cpp: Vulkan vs ROCm on Strix Halo](https://www.soothill.io/blog/2026/08/03/llamacpp-vulkan-vs-rocm-strix-halo/) · [AMD Strix Halo Backend Benchmarks (grid)](https://kyuz0.github.io/amd-strix-halo-toolboxes/)
- 셋업·벤치 종합 — [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide) · [strix-halo-gmktec-evo-x2 QWEN3-CODER-30B 벤치](https://github.com/pablo-ross/strix-halo-gmktec-evo-x2/blob/main/QWEN3-CODER-30B_BENCHMARK.md)
- VGM 설정 절차 — [How to Allocate VRAM on Strix Halo (Adrenalin)](https://www.jdhodges.com/blog/amd-strix-halo-vram-allocation-ryzen-ai-max-395/)
- 전원 모드 54/85/140W — [PCWorld: GMKtec EVO-X2 review](https://www.pcworld.com/article/3011421/gmktec-evo-x2-review.html)
