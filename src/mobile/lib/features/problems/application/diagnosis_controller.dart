// 진단 컨트롤러 — CAT 추천(next-problem)으로 문제를 확보하고 그 문제 상세를 로드한다.
//
// 경계(CLAUDE.md): 출제·진단(IRT/BKT) 결정은 전부 서버(L2)가 내린다. 이 컨트롤러(L5)는
// (1) next-problem을 조회해 problem_id를 얻고 (2) 그 문제 상세를 로드할 뿐이다 — 어떤 수학·능력
// 판정도 하지 않는다(수학 로직 클라 미구현·표현≠의미).
//
// 흐름(백엔드 E2E 테스트 미러): GET /v1/me/next-problem → (problem_id 있으면) GET
// /v1/problems/{id}. problem_id가 null이면 후보 없음으로 graceful 종료(noCandidate)한다 —
// 앱은 코치 없이도 진행 가능해야 한다(가용성).
//
// MOB-24 ①: 예전에는 문제 상세 뒤에 개념 진단 목록(`getDiagnosisConcepts`)을 *한 번 더 순서대로*
// 기다렸다. MOB-10 때는 이 적재분을 나 탭이 재사용하는 설계였지만, 지금 나 탭은 `MeTabController`가
// 자기 진단을 따로 불러오고 문제 화면(`problem_screen.dart`)은 이 값을 어디에도 표시하지 않는다
// (lib 전수 검색 표시처 0건 — 학생은 문제가 뜨기까지 안 쓰이는 왕복 한 번을 더 기다린 셈이다).
// 그래서 호출과 상태 필드(`diagnoses`)를 함께 제거했다. 다시 필요해지면 문제 상세와 *병렬*
// (`Future.wait` — 나 탭 선례)로 붙여야 하고, 직렬로 되돌리면 안 된다.
import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../data/problems_api.dart';
import 'diagnosis_state.dart';

part 'diagnosis_controller.g.dart';

/// 서버 최소버전 계약 미달 사유코드(OPS-17) — `app.py _service_metrics_middleware`가 돌려주는
/// `426 Upgrade Required`. 표준 HTTP status(`status.HTTP_426_UPGRADE_REQUIRED`)와 동형이며
/// 401/404/422 등 다른 실패와 구분해 전용 문구로 분기하는 데만 쓴다.
const int _updateRequiredStatusCode = 426;

/// 진단(CAT)→문제제시 흐름을 관장하는 Riverpod Notifier.
@riverpod
class DiagnosisController extends _$DiagnosisController {
  @override
  DiagnosisState build() => const DiagnosisState();

  /// CAT 추천으로 다음 문제를 확보하고 상세를 로드한다.
  ///
  /// ① next-problem 조회 → ② problem_id가 null이면 noCandidate로 종료(정상) →
  /// ③ 있으면 문제 상세 로드 →
  /// ④ 실패는 에러만 남기고 앱을 막지 않는다(가용성). 중복 호출(isLoading)은 무시한다.
  Future<void> load({bool prioritizeWeakConcepts = false}) async {
    if (state.isLoading) {
      return; // 조회 중 재진입 방지.
    }
    state = state.copyWith(isLoading: true, error: null, noCandidate: false);
    try {
      final next = await ref
          .read(problemsApiProvider)
          .getNextProblem(prioritizeWeakConcepts: prioritizeWeakConcepts);

      final pid = next.problemId;
      if (pid == null) {
        // 추천 후보 없음 — 문제 없이 정상 종료(측정 충분·또는 미시딩).
        state = state.copyWith(
          isLoading: false,
          nextProblem: next,
          problem: null,
          noCandidate: true,
        );
        return;
      }

      final problem = await ref.read(problemsApiProvider).getProblem(pid);

      state = state.copyWith(
        isLoading: false,
        nextProblem: next,
        problem: problem,
        noCandidate: false,
      );
    } catch (e) {
      if (e is DioException && e.response?.statusCode == _updateRequiredStatusCode) {
        // OPS-17: 서버 최소버전 계약 미달(426) — 일반 실패와 다른 전용 문구로 분기한다.
        state = state.copyWith(
          isLoading: false,
          error: '앱을 최신 버전으로 업데이트해주세요.',
        );
        return;
      }
      // graceful — 네트워크·인증 실패 모두 앱을 막지 않는다.
      state = state.copyWith(
        isLoading: false,
        error: '문제를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.',
      );
    }
  }
}
