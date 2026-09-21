# Phaiakes9 머신 셋업 가이드 (M1.0a)

> 새 박스를 켜는 순간부터 `bash benchmark/run_bench.sh` 실행 직전까지의 *전 과정*.
>
> 이 가이드는 Kiki가 *직접* 머신 앞에서 따라가는 체크리스트입니다. 자동화 가능한 부분은 `bootstrap.sh` 한 줄로 묶었고, 보안·네트워크 정책처럼 *Kiki의 판단이 필요한 부분*은 의도적으로 수동 단계로 두었습니다.

---

## 📑 진행 순서 한눈에

| Phase | 단계 | 자동화 | 예상 시간 |
|---|---|---|---|
| **A** | 하드웨어 확인 | 수동 | 30분 |
| **B** | Ubuntu 24.04 LTS 설치 | 수동 (설치 마법사) | 30~60분 |
| **C** | 초기 로그인·SSH 키 등록 | 수동 + `bootstrap.sh` 일부 | 15분 |
| **D** | 네트워크·sshd·방화벽 강화 | `bootstrap.sh` | 자동 5분 |
| **E** | 드라이버·시간·자동 업데이트 | `bootstrap.sh` | 자동 10분 |
| **F** | WhyMath 클론 → Ollama 셋업 → 벤치마크 | 기존 `README.md`로 핸드오프 | 30분 |
| **합계** | | | 2~3시간 |

---

## Phase A. 하드웨어 확인

### A.1 사양 체크리스트

| 부품 | 권장 | WhyMath 근거 |
|---|---|---|
| CPU/APU | **AMD Ryzen AI Max+ 395** (Strix Halo, Zen 5 16C/32T) | `CLAUDE.md` 기술 스택 |
| iGPU | Radeon 8060S (RDNA 3.5, 40 CU) | Ollama ROCm 가속 (`gfx1151`) |
| NPU | XDNA 2 (50 TOPS) | 향후 OnnxRuntime QNN 경로 — Phase 2+ |
| RAM | **128 GB LPDDR5X** (통합 메모리) | 72B 4bit 모델 단독 + Redis + Postgres 여유 |
| SSD | NVMe 1 TB+ (모델·데이터) + 별도 부트 256 GB 권장 | 모델 캐시 + Postgres data + 로그 |
| 전원 | 350 W+ (Strix Halo APU 단독은 ~120 W지만 여유) | — |
| 네트워크 | 유선 RJ-45 또는 Wi-Fi 6E | 안정적 LAN 노출 |

### A.2 BIOS/펌웨어 사전 점검
- [ ] 메인보드 최신 BIOS 적용 (Strix Halo 마이크로코드 포함 여부)
- [ ] **IOMMU 활성화** (`AMD-Vi`) — Ollama ROCm·향후 컨테이너 GPU 패스스루
- [ ] Secure Boot — 켜두되 Ubuntu 서명 키 신뢰 (설치 마법사가 처리)
- [ ] CPU 가상화 활성화 (`SVM`) — 향후 Docker GPU 가속용

---

## Phase B. Ubuntu 24.04 LTS 설치

### B.1 설치 매체 준비 (다른 PC에서)
```bash
# Windows PowerShell 예시 (Rufus 또는 balenaEtcher 권장)
# 1. https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso
# 2. balenaEtcher 또는 Rufus 로 USB 3.0 8GB+ 에 굽기
```

### B.2 설치 옵션 선택
- [ ] **Ubuntu Server 24.04 LTS** (Desktop 아님 — 자원 절약, X 서버 불필요)
- [ ] 언어: English (한국어는 *로캘로만*, 시스템 메시지는 영어 유지 — 디버깅 검색 용이)
- [ ] 키보드: Korean
- [ ] 네트워크: 유선 우선, DHCP 또는 정적 IP (LAN 관리 정책에 맞춰)
- [ ] 프록시: 사내망 사용 시 입력
- [ ] **저장소 레이아웃**:
  - 부트(EFI): 512 MB
  - `/`: 100 GB ext4 (또는 btrfs)
  - 스왑: 16 GB (LPDDR5X 풍부하므로 형식적)
  - `/var/lib/ollama` 마운트: NVMe 나머지 — 모델 캐시 별도 디스크 가능
- [ ] 호스트명: **`phaiakes9`** (이 가이드 전체가 이 이름 가정)
- [ ] 초기 사용자명: `kiki` 권장 (또는 본인 닉네임, root 직접 사용 금지)
- [ ] **OpenSSH server 설치 체크** ← *중요*. 이후 SSH 접속 위해 필수
- [ ] Snap 추천 패키지: 모두 *체크 해제* (불필요·디스크 낭비)

### B.3 첫 부팅 후 확인
```bash
# 콘솔에서 로그인 후
hostnamectl                    # 호스트명 phaiakes9 확인
ip a                           # IP 주소 메모 (Windows PC에서 SSH 할 때 사용)
sudo apt update && sudo apt -y upgrade
sudo reboot                    # 커널 업데이트 반영
```

---

## Phase C. 초기 로그인·SSH 키 등록

### C.1 Windows PC에서 SSH 키 생성 (한 번만)
```powershell
# Windows PowerShell 에서
ssh-keygen -t ed25519 -C "kiki@whymath" -f $HOME\.ssh\id_ed25519_phaiakes9
# 비밀번호 설정 권장 (빈 칸도 가능)
type $HOME\.ssh\id_ed25519_phaiakes9.pub
# 출력된 공개키를 복사
```

### C.2 Phaiakes9에 공개키 등록 (콘솔에서)
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
# 위에서 복사한 공개키 한 줄 붙여넣기 → 저장
chmod 600 ~/.ssh/authorized_keys
```

### C.3 Windows에서 SSH 접속 테스트
```powershell
# Windows PowerShell
ssh -i $HOME\.ssh\id_ed25519_phaiakes9 kiki@<phaiakes9_ip>
# 첫 접속 시 fingerprint 확인 yes
```

### C.4 SSH config 단축 (`~/.ssh/config`)
```ssh-config
Host phaiakes9
    HostName 192.168.0.XXX     # 실제 IP 입력
    User kiki
    IdentityFile ~/.ssh/id_ed25519_phaiakes9
    ServerAliveInterval 30
```
이후 `ssh phaiakes9` 한 줄로 접속.

---

## Phase D. `bootstrap.sh` 실행 (자동화)

이 단계는 *Phaiakes9에 SSH로 접속한 상태에서* 실행합니다.

```bash
# Phaiakes9 콘솔에서
cd ~
git clone https://github.com/kiki-s-broom/WhyMath.git whymath
cd whymath/infra/phaiakes9
bash bootstrap.sh          # ← Phase D + E를 한 번에 수행
```

`bootstrap.sh`가 수행하는 작업:
- apt 필수 도구 설치 (`curl jq git build-essential ufw chrony unattended-upgrades amdgpu-install`)
- sshd 하드닝 (root 로그인 비활성·비밀번호 인증 비활성·키 인증만)
- ufw 방화벽 (SSH 22 + Ollama 11434 *LAN 대역만* 허용)
- 시간대 `Asia/Seoul` + chrony 시작
- `unattended-upgrades` (보안 패치만 자동, 커널은 *수동* — 운영 중 재부팅 방지)
- AMD ROCm 드라이버 PPA 추가 (`amdgpu-install --usecase=rocm,opencl --no-dkms`)
- Strix Halo `HSA_OVERRIDE_GFX_VERSION=11.5.1` 환경 등록 (`gfx1151`)

스크립트는 **멱등적**이며 단계마다 종료 코드를 분리합니다. 실패 단계에서 멈추고 메시지 출력.

---

## Phase E. 드라이버 검증 (bootstrap.sh 직후)

```bash
# ROCm 설치 확인
rocminfo | grep -E "(Name|gfx)" | head -20
# 다음 라인이 보이면 OK:
#   Marketing Name:          AMD Radeon Graphics
#   Name:                    gfx1151

# Ollama가 GPU를 인식할지 사전 점검
clinfo | grep -i "device name"     # OpenCL device로 보여야 함

# 재부팅 1회 (커널 모듈 반영)
sudo reboot
```

⚠️ **드라이버 미인식 시**: Strix Halo가 ROCm 정식 지원 목록에 없을 수 있습니다. 그 경우:
- 옵션 1: `HSA_OVERRIDE_GFX_VERSION=11.0.0` 로 강제 (성능 저하 가능)
- 옵션 2: **Ollama CPU 모드**로 진행 (Zen 5 16C, 128GB로 7B는 충분히 빠름)
- 옵션 3: Ollama Vulkan backend 빌드 (커뮤니티 포크)

CPU 폴백 결정 시 `pull_models.sh`는 그대로 동작. `benchmark/run_bench.sh` 결과로 게이트 판정.

---

## Phase F. Ollama 셋업·벤치마크 (기존 README로 핸드오프)

여기부터는 [`README.md` §2 빠른 시작](./README.md#2-빠른-시작-5단계-약-30분)을 따라갑니다.

```bash
cd ~/whymath/infra/phaiakes9
bash install_ollama.sh
sudo cp systemd/ollama.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
bash pull_models.sh
bash healthcheck.sh
bash benchmark/run_bench.sh
```

벤치마크 결과 JSON에서 `"gate_p50_under_2s": true` 면 **M1.1 게이트 통과**.

---

## ✅ 완료 게이트 (M1.0a)

다음을 모두 만족해야 M1.0a 단계 종료:

- [ ] `ssh phaiakes9` 키 인증 성공
- [ ] `sudo systemctl status ollama` → `active (running)`
- [ ] `bash infra/phaiakes9/healthcheck.sh` → 3단계 모두 ✅
- [ ] `rocminfo` 또는 `clinfo` 로 GPU/CPU 가속 경로 확인
- [ ] `ufw status` → 22 (SSH) + 11434 (LAN만) 만 열림

위 5개 통과 후 → `benchmark/run_bench.sh` → 결과를 `MEMORY.md` 결정 로그에 첨부 → **M1.1 게이트 판정**.

---

## 🛟 트러블슈팅

### B 단계 — 설치 매체가 부팅 안 됨
- BIOS에서 USB Boot 우선 순위 상단
- Secure Boot 일시 OFF 후 재시도
- Ubuntu 24.04.x *최신 패치* ISO 사용 (Strix Halo 칩셋 드라이버 포함)

### C 단계 — SSH 연결 거부
- `sudo systemctl status ssh` 확인
- 방화벽 차단 여부 (`sudo ufw status` — bootstrap 전에는 비활성 가능)
- 라우터·스위치 격리 정책 (VLAN·게스트망)

### D 단계 — `bootstrap.sh` 실패
- 멱등이므로 *그대로 재실행* 가능
- 실패 직전 단계의 로그를 보고 패키지 미러·DNS 문제 우선 검토
- 사내망 프록시 시 `~/.bashrc` 에 `http_proxy`·`https_proxy` 설정 후 재시도

### E 단계 — ROCm 미작동
- 위 *CPU 폴백* 경로로 우회
- `dmesg | grep -i amdgpu` 커널 메시지 확인
- AMD 공식 호환표는 변동하므로 *공식 문서 최신본* 우선

### F 단계 — `gate_p50_under_2s = false`
- 모델을 더 작은 양자화로 교체: `WHYMATH_MODELS_OVERRIDE="qwen2.5-math:7b-instruct-q4_K_M"`
- KEEP_ALIVE 늘려 콜드스타트 방지 (`systemd/ollama.service` 수정)
- NUM_PARALLEL 낮춰 단일 요청에 자원 집중

---

## 📌 다음 단계 (M1.0a 종료 후)

1. 벤치마크 결과를 `MEMORY.md` 결정 로그 항목 *2026-MM-DD: M1.1 게이트 통과* 로 추가 (양식은 `README.md` §4 참조)
2. L3 LLM 라우터 작업 착수 — `/implement llm:phaiakes9-router`
3. M1.2 — 사람 수학자 검수 라운드 일정 잡기
