// 진단·문제 로드 상태 — CAT 추천 스냅샷·로드된 문제·로딩·에러를 담는 불변 상태.
//
// 경계(CLAUDE.md): 순수 표현 상태다. 출제·진단 판정은 서버(L2)가 내리고 이 상태는 결과만 담는다.
import 'package:freezed_annotation/freezed_annotation.dart';

import '../data/problem_models.dart';

part 'diagnosis_state.freezed.dart';

/// 진단(CAT)→문제제시 구간의 단일 상태 트리.
@freezed
abstract class DiagnosisState with _$DiagnosisState {
  const factory DiagnosisState({
    /// 마지막 next-problem(CAT) 응답·미조회면 null.
    NextProblemResponse? nextProblem,

    /// 로드된 문제 상세·미로드면 null.
    Problem? problem,

    /// 조회 진행 중인지(로딩 인디케이터·중복 호출 방지).
    @Default(false) bool isLoading,

    /// 추천 후보가 없음(problem_id==null) — 문제 없이 완료된 정상 상태.
    @Default(false) bool noCandidate,

    /// 마지막 호출 실패 메시지(없으면 null). 가용성을 위해 앱은 죽지 않는다.
    String? error,
  }) = _DiagnosisState;
}
