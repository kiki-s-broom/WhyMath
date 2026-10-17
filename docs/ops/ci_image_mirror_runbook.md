# CI 컨테이너 이미지 ghcr 미러 운영 런북 (OPS-135)

> 정본 문서다. 미러를 고치거나 이미지를 더하기 전에 읽는다.
> 판정 근거: 게이트 `G-ops135-ci-image-source-decision` — 2026-10-14 Kiki가 ①ghcr 미러를 선택했다.

## 1. 왜 있는가

2026-10-09 20:53~21:16Z에 CI의 컨테이너 이미지 다운로드가 Docker Hub 익명 한도에 걸렸다
(`toomanyrequests: You have reached your unauthenticated pull rate limit`). 서비스 컨테이너를 띄우는
`Initialize containers` 단계가 3회 연속 실패해 PR #1529가 머지 큐에서 3번 탈락했고, 한도는 최소
23분 지속됐다. GitHub 호스트 러너는 IP를 다른 사용자와 나눠 쓰므로 우리가 얼마나 적게 받든 한도가
소진될 수 있다. 그래서 CI가 쓰는 이미지의 **사본을 GitHub 안(ghcr.io)에 두고 CI는 사본만 받게** 했다.

## 2. 구성

| 구성요소 | 위치 | 역할 |
|---|---|---|
| 미러 목록 | `infra/ci/mirrored-images.yaml` | 무엇을 미러하는가(단일 진실 원천) |
| 미러 도구 | `scripts/ops/mirror_ci_images.py` | digest 해석 → 그 digest로 복사 → 복사 후 검증 |
| 미러 워크플로 | `.github/workflows/mirror-ci-images.yml` | 주 1회·목록 변경 시·수동 실행 |
| 사본 주소 | `ghcr.io/<소유자>/whymath-ci-mirror/<이름>:<태그>` | CI가 받는 곳 |

**소비처 (OPS-135 2단계가 사본으로 전환한 곳)**: 계약은 `tests/infra/test_ci_image_sources.py`가
집행한다 — 워크플로 YAML을 파싱해 서비스 컨테이너·`container:`·`docker run|create|pull`·`uses: docker://`와
`Dockerfile`의 `FROM`·`# syntax=`를 전수로 읽고, 미러 사본이 아니면 RED다(스캔 0건도 RED).

| 소비처 | 어떻게 사본을 받는가 |
|---|---|
| `ci.yml` `backend-migrations` · `data-pipeline-integration` · `e2e-nightly`(PG) · `data-pipeline-neo4j`(Neo4j) | 서비스 `image:` = 사본 주소 + `credentials`(`GITHUB_TOKEN`) + 잡 `permissions: packages: read` |
| `weekly-metrics.yml` `report`(PG) | 같은 방식, 워크플로 최상위 `packages: read` |
| `ci.yml` `docker-build` + `Dockerfile` | Dockerfile은 `ARG PYTHON_IMAGE`(기본값 = Docker Hub `python:3.12-slim`)로 받고, CI는 `docker login ghcr.io` 뒤 `--build-arg PYTHON_IMAGE=<사본>`을 넘긴다. `# syntax=` 지시어는 제거했다(그 지시어는 빌드마다 프런트엔드 이미지를 Docker Hub에서 따로 받는다) |

로컬·운영 빌드는 `ARG` 기본값(Docker Hub)을 그대로 쓴다 — 사본이 필요한 곳은 CI뿐이다. 이 경로의 Docker
Hub 한도는 이 런북이 다루지 않는다(운영 compose의 이미지 참조는 CI가 아니라서 OPS-135 범위 밖이다).

## 3. 새 이미지를 더하는 순서 (순서를 거꾸로 하면 전 CI가 깨진다)

1. `infra/ci/mirrored-images.yaml`의 `sources`에 `저장소:태그`를 한 줄 추가하고 main에 머지한다.
2. 머지 직후 미러 워크플로가 자동으로 돈다(목록 변경 트리거). Actions 탭에서 성공을 확인한다.
3. **사본이 생긴 것을 확인한 뒤에만** CI의 이미지 참조를 사본 주소로 바꾼다.

사본이 없는 이미지를 CI가 받으려 하면 그 잡은 이미지 pull 단계에서 실패한다.

## 4. 갱신 주기와 책임

- **주기**: 매주 월요일 04:23 UTC(KST 13:23) 자동 실행. 업스트림 태그(`pg16` 등)가 받은 보안 패치를
  사본에 반영하는 유일한 경로다. 긴급하면 Actions 탭 → `mirror-ci-images` → `Run workflow`로 수동 실행한다.
- **책임**: 실패 알림은 GitHub이 예약 실행 실패 시 기본 제공하는 저장소 알림이다(새 채널을 만들지 않았다).
  실패를 본 사람(Kiki 또는 세션)이 §6 순서로 원인을 가린다. 주 1회 실행이 연속 2회 실패하면 사본이 2주 이상
  낡는다 — 그때는 태스크로 등재한다.

## 5. 잔여 위험 (정직한 공백 — 미러가 해결하지 못하는 것)

| # | 위험 | 크기 | 대응 |
|---|---|---|---|
| ① | **사본이 낡는다** — 업스트림이 보안 패치를 내도 다음 미러 실행 전까지 CI는 옛 이미지를 쓴다. | 최대 7일 지연. CI 전용 이미지(운영 배포와 무관)라 영향이 작다. | 주 1회 갱신. 긴급 패치는 수동 실행. |
| ② | **미러 자체는 여전히 Docker Hub를 읽는다** — 한도에 걸리면 미러 실행이 실패한다. | 주 1회·목록 변경 시만 읽으므로 모든 CI 실행이 읽던 때보다 훨씬 드물다. 실패해도 CI는 기존 사본으로 계속 돈다. | 지수 백오프 재시도(최대 약 18분) + 전체 예산 40분. |
| ③ | **사본 패키지는 비공개다**(2026-10-14 첫 미러 실행 뒤 실측: 로그인 없이 `imagetools inspect` → 3종 모두 401 `failed to fetch anonymous token`). | 같은 저장소의 워크플로(`GITHUB_TOKEN`)로만 받을 수 있다. 포크 PR·로컬 개발 머신은 받지 못한다. | CI는 서비스 `credentials`·`docker login`으로 받는다(계약 테스트가 집행). 공개 전환은 ④의 라이선스 확인 뒤에만 한다 — 공개하면 이 의존이 사라지지만 재배포가 된다. |
| ④ | **재배포 라이선스를 확인하지 않았다** — 사본은 업스트림 이미지의 재배포다. | `pgvector/pgvector`(PostgreSQL·pgvector 계열)와 `python`은 허용 범위가 넓다고 알고 있으나 이 저장소에서 검증하지 않았다. `neo4j`는 Community 판 조건(GPL 계열)을 확인하지 못했다. | 사본이 **공개 패키지로 전환되기 전에** 확인한다(비공개 상태에서는 외부 재배포가 아니다). Neo4j만 막히면 `data-pipeline-neo4j` 잡을 분리 판정한다. |
| ⑤ | **조직·소유자 이관** — 사본 주소에 소유자가 들어간다. | 이관 후 CI 참조(`github.repository_owner`)는 따라가지만 새 소유자 아래 사본이 없다. | 이관 직후 미러를 수동 실행한다. 대문자가 든 소유자는 ghcr 규칙상 쓸 수 없고 도구가 거부한다(종료 코드 2). |
| ⑥ | **한도 실패가 코드 실패로 읽힌다** — 컨테이너 초기화가 실패하면 그 잡의 뒤 스텝은 실행되지 않아 CI 안에서 원인을 따로 표시할 수 없다. | 사본으로 옮긴 뒤에는 Docker Hub 한도가 CI를 막지 않으므로 이 위험 자체가 줄었다. | 원인 판별은 `Initialize containers` 로그의 pull 오류 문구로 한다(§6). 별도 감시 장치는 만들지 않았다. |

## 6. 장애 대응 순서

사본을 받는 잡이 `Initialize containers`에서 실패했을 때:

1. 로그의 오류 문구를 읽는다. `manifest unknown` · `not found`면 **사본이 없거나 이름이 틀린 것**이다 → 미러 워크플로 최근 실행을 본다.
2. `unauthorized` · `denied`면 **패키지 접근 권한**이다 → §7의 패키지 설정(저장소 접근·공개 여부)을 본다.
   사본은 비공개이므로 `credentials`·`docker login`·`packages: read`가 빠졌거나, 패키지의 Actions 접근에서 이 저장소가 빠진 경우다(§5 ③). 포크 PR에서만 나면 정상 제약이다.
3. `toomanyrequests`가 ghcr.io 주소에서 나오면 ghcr 쪽 한도다(드문 경우) → 같은 실행을 한 번 다시 돌리고, 반복되면 태스크로 등재한다.
4. `toomanyrequests`가 `docker.io`/`registry-1.docker.io`에서 나오면 **Docker Hub 익명 참조가 되돌아온 것**이다 → `tests/infra/test_ci_image_sources.py`가 막았어야 하므로 그 테스트가 왜 통과했는지부터 본다.

## 7. 첫 미러 실행 뒤 Kiki가 확인할 것 (GitHub 웹)

1. 저장소 → Actions → `mirror-ci-images` 실행이 초록인지 본다. 실행 요약 표에 이미지 3종의 digest가 있어야 한다.
2. 조직 페이지 `kiki-s-broom` → Packages에 `whymath-ci-mirror/pgvector` · `neo4j` · `python` 3개가 보이는지 본다.
3. 각 패키지 → Package settings에서 **공개 여부**와 **Manage Actions access**(이 저장소가 읽기 이상으로 등록돼 있는지)를 확인한다.
4. 공개로 전환하기 전에 위 ④의 라이선스 확인을 끝낸다.
