// coach verify 신호 카드 — 코치 버블 아래에 이번 세션 백엔드 신호를 *은근하게* 시각화한다.
//
// 경계(CLAUDE.md): 검산·검증 *로직*은 전부 서버(L3·L4)에 있고, 이 카드는 결정된
// 신호([CoachResponse] 구조)를 받아 *cue*로만 그린다(표현≠의미·수학 로직 클라 미구현).
//
// 답 미루기(절대 금기): **위치·종류 cue만** 보여 준다 — 정답값·수정 방법·"틀렸다" 단정은
// 절대 표시하지 않는다(정서 안전·부정 강화 금지·은근/격려 톤). 대부분 단계 신호는 텍스트
// 입력만으론 null(단계 미전송)이므로 **전부 null-guard** — 있을 때만 칩/행을 그리고,
// 신호가 하나도 없으면 카드 자체를 그리지 않는다.
//
// 정직(범위): 줄 번호 정밀 하이라이트(error_span)·전이별 verdict 리스트·단계 입력 UI·
// misconception 카드는 *후속*이다. 이번 슬라이스는 신호 *유무·종류·요약* cue까지만.
// MATH-03: 확인 보류(unverifiable)는 사유 분포 카운트로 *3분기 문구*를 가른다 — 고칠 수 있는
// 것/고칠 게 없는 것/단정하지 않는 것(운영 7종 코드는 내부·학생에겐 3분기만·위치 지시 없음).
import 'package:flutter/material.dart';

import '../../../theme/spacing.dart';
import '../data/coach_models.dart';

/// 코치 발화 아래에 붙는 verify 신호 카드.
///
/// [response]의 `solutionCoaching` 신호를 *있을 때만* 칩/행으로 렌더한다. 신호가
/// 하나도 없으면 [SizedBox.shrink]를 반환해 아무것도 그리지 않는다(빈 공간 없음).
class CoachSignalCard extends StatelessWidget {
  /// 카드를 그릴 원본 코치 응답(coach 메시지가 보관한 값).
  const CoachSignalCard({required this.response, super.key});

  /// 신호를 읽어 올 코치 응답.
  final CoachResponse response;

  @override
  Widget build(BuildContext context) {
    final coaching = response.solutionCoaching;
    // 풀이 코칭 자체가 없으면(텍스트만 주고받는 흔한 경우) 카드 없음.
    if (coaching == null) {
      return const SizedBox.shrink();
    }

    final theme = Theme.of(context);
    final rows = <Widget>[];

    // ① 검산 cue — 거짓 수치 관계가 검출됐을 때만(텍스트 입력으로도 동작).
    //    종류(errorKind)는 *부드러운 한국어 라벨*로만 — 구체 값·정답은 절대 노출 안 함.
    if (coaching.arithmeticError) {
      final kindLabel = _errorKindLabel(coaching.errorKind);
      rows.add(
        _SignalRow(
          icon: Icons.calculate_outlined,
          label: kindLabel == null
              ? '스스로 검산해볼까?'
              : '스스로 검산해볼까? ($kindLabel 부분)',
        ),
      );
    }

    // ② 검산 지점 cue — focusStepIndex가 가리키는 "지점 있음"만 표시한다.
    //    줄 번호 재계산(off-by-one) 금지 — 숫자 노출은 후속, 카드는 위치 마커만.
    if (coaching.trigger.focusStepIndex != null) {
      rows.add(
        const _SignalRow(
          icon: Icons.place_outlined,
          label: '다시 살펴볼 지점이 있어요',
        ),
      );
    }

    // ③ 단계 검증 요약 — 단계를 전송했을 때만(solutionVerification != null).
    final verification = coaching.solutionVerification;
    if (verification != null) {
      rows.add(
        _SignalRow(
          icon: Icons.checklist_rtl_outlined,
          label: _verificationSummary(verification),
        ),
      );
      // 다시 볼 단계가 있으면 *부드럽게*만 — 어느 단계가 왜 틀렸는지·고치는 법 금지.
      if (verification.hasIncorrect) {
        rows.add(
          const _SignalRow(
            icon: Icons.visibility_outlined,
            label: '다시 볼 단계가 있어요',
          ),
        );
      }
      // ③-a 확인 보류 3분기(MATH-03) — 사유 분포가 있을 때만 세분 행을 그린다.
      rows.addAll(_unverifiableRows(verification));
    }

    // ④ OCR 재확인 cue — 풀이 인식이 흐릴 때만(§3.3 게이트). 재촬영 유도.
    if (coaching.verificationOcrGated) {
      rows.add(
        const _SignalRow(
          icon: Icons.photo_camera_outlined,
          label: '풀이가 잘 안 보여요 — 다시 확인해볼까요?',
        ),
      );
    }

    // 어떤 신호도 없으면 카드를 그리지 않는다.
    if (rows.isEmpty) {
      return const SizedBox.shrink();
    }

    // 은근한 카드 — Material 3 surface 톤(과한 경고색·답 강조 없음).
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(top: AppSpacing.hairline, bottom: AppSpacing.xs6, left: AppSpacing.xs),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        constraints: BoxConstraints(
          // 폭만 필요 — `sizeOf`로 size 변화에만 구독한다(MOB-24 ④·버블과 동일 사유: `MediaQuery.of`는 하단 시스템
          // 인셋이 있는 폰에서 키보드 첫·끝 프레임마다 카드를 다시 빌드시킨다).
          maxWidth: MediaQuery.sizeOf(context).width * 0.78,
        ),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          // 행 사이 간격을 위해 spacer를 끼워 넣는다(첫 행 위는 비움).
          children: _withGaps(rows),
        ),
      ),
    );
  }

  /// 슬립 종류 문자열을 *부드러운 한국어 라벨*로 — 정답·구체 값은 담지 않는다.
  /// 백엔드 enum("arithmetic"·"inequality"·"not_equal"·"solution"·"other") 중
  /// 안전하게 *종류*만 알려도 되는 값만 라벨링하고, 나머지는 null(라벨 생략).
  static String? _errorKindLabel(String? errorKind) {
    switch (errorKind) {
      case 'arithmetic':
        return '계산';
      case 'inequality':
        return '부등식';
      default:
        // not_equal·solution·other 등은 *해석 누출* 우려가 있어 라벨을 붙이지 않는다.
        return null;
    }
  }

  /// 단계 검증 요약 문구 — "N단계 중 M단계 확인"(전이 수/확인 수).
  /// unverifiedRatio는 내부값이라 표시하지 않되, 보류가 있으면 한 마디만 덧붙인다.
  ///
  /// MATH-03: 사유 분포([SolutionVerificationResult.unverifiableByReason])가 오면 접미사 대신
  /// [_unverifiableRows]의 3분기 행이 세분을 담당한다. 분포가 *없는* 구판 서버 응답에서만
  /// 기존 '확인 보류 일부' 접미사로 폴백한다 — 이때는 표기 문제(고칠 수 있음)와 비대수 단계
  /// (고칠 게 없음)가 같은 한 문구로 접힌다(접힘 ②의 잔상·클라만 고쳐서는 회복 불가의 실측).
  static String _verificationSummary(SolutionVerificationResult v) {
    final base = '${v.nTransitions}단계 중 ${v.nCorrect}단계 확인';
    if (v.nUnverifiable > 0 && v.unverifiableByReason.isEmpty) {
      return '$base · 확인 보류 일부';
    }
    return base;
  }

  // ── 확인 보류 3분기(MATH-03) ─────────────────────────────────────────────
  //
  // 운영 7종 사유 코드(백엔드 VerifyStepReasonCode)를 학생 노출 *3분기*로만 접는다 —
  // 비대칭은 의도다(검증기 내부를 학생에게 노출하지 않는다·MATH-03 ③). 기준은 "학생 행동이
  // 갈리는가":
  //   ① 고칠 수 있는 것(시스템이 입력을 못 읽음 → 표기 점검): parse_error·empty_input
  //   ② 고칠 게 없는 것(원래 계산으로 확인 못 하는 종류 → 행동 불필요): non_algebraic_step
  //   ③ 단정하지 않는 것(수학적 미결정 → 보류 톤): undecidable·heterogeneous_form·
  //      subset_ambiguous·variable_mismatch — *미지의 새 코드도 여기*(보수 폴백·단정 금지)
  // 문구 제약(교수학 톤): 부정 강화 금지·정답 미제공·낙인 어휘 금지 — 행동 cue만.

  /// ①분기 코드 — 학생이 표기를 고치면 확인이 가능해지는 종류.
  static const Set<String> _fixableReasonCodes = <String>{'parse_error', 'empty_input'};

  /// ②분기 코드 — 계산 검증 대상이 아니라 학생이 고칠 것이 없는 종류.
  static const Set<String> _nothingToFixReasonCodes = <String>{'non_algebraic_step'};

  /// 사유 분포를 3분기 행으로 접는다 — 각 분기는 카운트가 1 이상일 때만 그린다.
  static List<Widget> _unverifiableRows(SolutionVerificationResult v) {
    var fixable = 0; // ① 고칠 수 있는 것
    var nothingToFix = 0; // ② 고칠 게 없는 것
    var indeterminate = 0; // ③ 단정하지 않는 것(미지 코드 포함·보수)
    for (final MapEntry<String, int> entry in v.unverifiableByReason.entries) {
      if (_fixableReasonCodes.contains(entry.key)) {
        fixable += entry.value;
      } else if (_nothingToFixReasonCodes.contains(entry.key)) {
        nothingToFix += entry.value;
      } else {
        indeterminate += entry.value;
      }
    }

    return <Widget>[
      // ① 학생이 *할 수 있는 일*(표기 확인)만 부드럽게 — "틀렸다"가 아니라 "못 읽었다".
      if (fixable > 0)
        const _SignalRow(
          icon: Icons.edit_outlined,
          label: '읽지 못한 단계가 있어요 — 표기를 한 번 확인해볼까요?',
        ),
      // ② 행동 불필요를 명시 — 서술·경우 나누기 단계가 "문제 있음"으로 오독되지 않게.
      if (nothingToFix > 0)
        const _SignalRow(
          icon: Icons.info_outline,
          label: '계산으로 확인하는 종류가 아닌 단계는 건너뛰었어요',
        ),
      // ③ 단정하지 않는 보류 톤 — 옳다/그르다 어느 쪽도 암시하지 않는다.
      if (indeterminate > 0)
        const _SignalRow(
          icon: Icons.hourglass_empty,
          label: '확인을 보류한 단계가 있어요',
        ),
    ];
  }

  /// 행 리스트에 행 간 간격을 끼워 넣는다(첫 행 위는 비우고 사이만 6px).
  static List<Widget> _withGaps(List<Widget> rows) {
    final out = <Widget>[];
    for (var i = 0; i < rows.length; i++) {
      if (i > 0) {
        out.add(const SizedBox(height: AppSpacing.xs6));
      }
      out.add(rows[i]);
    }
    return out;
  }
}

/// 신호 한 줄 — 아이콘 + 부드러운 라벨(은근한 cue·답 강조 없음).
class _SignalRow extends StatelessWidget {
  const _SignalRow({required this.icon, required this.label});

  /// 신호 종류를 암시하는 아이콘.
  final IconData icon;

  /// 학생에게 보일 부드러운 문구(위치·종류 cue만).
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = theme.colorScheme.onSurfaceVariant;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: AppSpacing.sm),
        Flexible(
          child: Text(
            label,
            style: theme.textTheme.bodySmall?.copyWith(color: color),
          ),
        ),
      ],
    );
  }
}
