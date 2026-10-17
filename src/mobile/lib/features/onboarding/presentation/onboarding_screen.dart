// 온보딩 화면 — 메타인지 접근 안내 + 학습 목표 입력(자동 커리큘럼 정렬 입력 UI). S1-c.
//
// 목적(CLAUDE.md): "답이 아닌, 이유를 묻는 수학" 정체성과 *답 미루기* 철학을 먼저 안내하고
// (기대 관리·정서 안전), 마지막 페이지에서 학습 목표(목표 등급·점수·시험일·출생연도)를
// *3분 무마찰*로 모은다 — 드롭다운·날짜 선택 위주로 자유 입력을 최소화한다. 산출물은 서버
// (`PATCH /v1/users/me`)로 넘어가 `StudentProfile`의 원천이 되고, 자동 커리큘럼 정렬 엔진
// (L1+L6)이 소비한다. L5는 *수집·전달*만 하고 정렬 로직을 구현하지 않는다(7계층 경계).
//
// 절대 금기: 중독성·게임화·카운트다운·보상 연출을 두지 않는다. 톤은 은근하고 격려하는
// 한국어이며, 외부 이미지 자산에 의존하지 않고 텍스트+아이콘만으로 구성한다(asset 경고 회피).
//
// 완료 지점(건너뛰기·시작하기 공통)은 "온보딩 봤음" 플래그를 영속 저장한다(MOB-11 —
// `OnboardingSeenController.markSeen`) — 다음 실행부터는 라우터 redirect가 온보딩을 건너뛰고
// 바로 채팅으로 보낸다("돌아오기 쉽다"·복귀 지원 최소 착지). "건너뛰기"는 목표 입력 없이 바로 학습 루프(진단→문제 `/problem`)로 가고, "시작하기"는
// 입력을 전송한 뒤(실패해도 graceful) 같은 학습 루프로 이동한다 — 입력은 모두 선택이라 비워도 진행된다.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router.dart';
import '../../../theme/spacing.dart';
import '../application/onboarding_controller.dart';
import '../application/onboarding_seen_controller.dart';

/// 온보딩 한 페이지의 콘텐츠 모델(아이콘·제목·설명).
class _OnboardingPage {
  const _OnboardingPage({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;
}

/// 온보딩 안내 페이지 정의 — 메타인지 철학 3단계(뒤에 목표 입력 폼 1페이지가 이어진다).
///
/// ① 브랜드(이유를 묻는다) ② 답 미루기 수용(막혀도 함께 단계를 짚는다) ③ 검산(함께 확인).
const List<_OnboardingPage> _pages = [
  _OnboardingPage(
    icon: Icons.lightbulb_outline,
    title: '답이 아닌, 이유를 묻습니다',
    body: '정답을 바로 알려주지 않아요.\n어떻게 생각했는지, 왜 그런지\n함께 짚어가며 풀이를 만들어 가요.',
  ),
  _OnboardingPage(
    icon: Icons.route_outlined,
    title: '막혀도 괜찮아요',
    body: '막히는 건 배움의 자연스러운 일부예요.\n어디서 멈췄는지 같이 살펴보고\n다음 한 걸음을 함께 찾아요.',
  ),
  _OnboardingPage(
    icon: Icons.checklist_rtl_outlined,
    title: '풀이를 함께 검산해요',
    body: '답이 나와도 끝이 아니에요.\n각 단계가 맞는지 함께 확인하며\n스스로 점검하는 힘을 길러요.',
  ),
];

/// 안내 페이지 뒤에 붙는 목표 입력 폼 페이지의 인덱스(안내 3페이지 다음).
/// `_pages.length`는 const 표현식에서 접근 불가(Dart const-eval 제약) → `final`.
final int _formPageIndex = _pages.length;

/// 전체 페이지 수 = 안내 페이지 + 목표 입력 폼 1페이지.
final int _totalPages = _pages.length + 1;

/// 온보딩 화면 — PageView로 메타인지 철학을 안내한 뒤 목표 입력 폼으로 마무리한다.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final PageController _pageController = PageController();

  /// 현재 페이지 인덱스(인디케이터·버튼 분기에 사용).
  int _index = 0;

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  /// 온보딩 완료 지점(건너뛰기·시작하기 공통) — "봤음" 플래그를 영속하고 진단→문제제시(S1)
  /// 학습 루프로 이동한다.
  ///
  /// 플래그는 [OnboardingSeenController.markSeen]이 *먼저* 메모리 상태에 반영하므로(동기) 영속
  /// 저장이 실패해도(graceful) 이번 이동은 막지 않는다(다음 실행부터 재노출될 뿐·MOB-11). CAT
  /// 추천 문제가 없으면 문제 화면이 코치 대화로 graceful 안내한다(가용성).
  Future<void> _goToLoop() async {
    await ref.read(onboardingSeenControllerProvider.notifier).markSeen();
    if (mounted) {
      context.go(AppRoutes.problemPath);
    }
  }

  /// 다음 페이지로 부드럽게 넘긴다(마지막 페이지면 호출되지 않음).
  void _next() {
    _pageController.nextPage(
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeInOut,
    );
  }

  /// "시작하기" — 입력을 전송한 뒤(성공·실패 무관·graceful) 학습 루프(진단→문제)로 이동한다.
  ///
  /// 입력은 모두 선택이라 비어 있으면 컨트롤러가 전송 없이 완료 처리한다. 전송 실패(403·
  /// 네트워크)도 온보딩을 막지 않는다 — 컨트롤러가 삼키고 화면은 그대로 학습 루프로 넘어간다.
  Future<void> _onStart() async {
    await ref.read(onboardingControllerProvider.notifier).submit();
    if (mounted) {
      await _goToLoop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final isLast = _index == _formPageIndex;
    final isSubmitting = ref.watch(
      onboardingControllerProvider.select((s) => s.isSubmitting),
    );

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // 상단 "건너뛰기" — 목표 입력 폼(마지막 페이지)에선 숨겨 "시작하기"로 자연 수렴한다.
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
                child: isLast
                    ? const SizedBox(height: AppSpacing.huge)
                    : TextButton(
                        onPressed: _goToLoop,
                        child: const Text('건너뛰기'),
                      ),
              ),
            ),
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                itemCount: _totalPages,
                onPageChanged: (i) => setState(() => _index = i),
                itemBuilder: (context, i) => i < _pages.length
                    ? _OnboardingPageView(page: _pages[i])
                    : const _OnboardingFormPage(),
              ),
            ),
            // 페이지 인디케이터 — 현재 위치를 점으로만 표시(보상·진척 게임화 아님).
            _PageIndicator(count: _totalPages, index: _index),
            const SizedBox(height: AppSpacing.lg),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxl, vertical: AppSpacing.lg),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  // 전송 중엔 비활성(중복 전송 방지). 마지막(폼) 페이지는 "시작하기"로 전송·이동.
                  onPressed: isSubmitting
                      ? null
                      : () {
                          if (isLast) {
                            _onStart();
                          } else {
                            _next();
                          }
                        },
                  child: Text(isLast ? '시작하기' : '다음'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 온보딩 한 페이지 렌더 — 아이콘·제목·본문을 가운데 정렬로 보여준다.
class _OnboardingPageView extends StatelessWidget {
  const _OnboardingPageView({required this.page});

  final _OnboardingPage page;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // Center+SingleChildScrollView — 키보드가 올라와 세로 제약이 좁아지면(실기기 실측: h≈200)
    // 넘치는 대신 스크롤로 강등한다(RenderFlex overflow 줄무늬가 시연 녹화에 찍히는 사고 방지).
    // 넉넉한 화면에선 Center가 기존과 동일하게 가운데 정렬한다(레이아웃 의미 불변).
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxxl),
      child: Center(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(page.icon, size: 96, color: theme.colorScheme.primary),
              const SizedBox(height: AppSpacing.xxxl),
              Text(
                page.title,
                textAlign: TextAlign.center,
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                page.body,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyLarge?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 목표 입력 폼 페이지 — 목표 등급·점수·시험일·출생연도를 무마찰로 모은다(자동 정렬 입력 UI).
///
/// 모든 입력은 선택이다(비워도 "시작하기"로 진행). 자유 입력을 최소화해 드롭다운·날짜 선택을
/// 우선한다(3분 무마찰 원칙). 입력값은 [OnboardingController]로 흘러 서버(PATCH)로 전달된다.
class _OnboardingFormPage extends ConsumerWidget {
  const _OnboardingFormPage();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final state = ref.watch(onboardingControllerProvider);
    final notifier = ref.read(onboardingControllerProvider.notifier);

    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxxl, vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '목표를 알려 주세요',
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '모두 선택이에요. 지금 비워 두고 나중에 설정에서 채워도 괜찮아요.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: AppSpacing.xxl),

          // ── 목표 등급(1~9) — 드롭다운(자유 입력 없음). 학년이 아니라 목표 '등급'이다.
          const _FieldLabel(label: '목표 등급'),
          DropdownButtonFormField<int>(
            // Flutter 3.33+에서 value→initialValue deprecated. pubspec flutter floor(^3.24)에는
            // initialValue가 없어 value 유지(3.24~3.35 양쪽 컴파일). floor를 3.35+로 올릴 때
            // initialValue로 전환한다 — MOB-01 후속.
            // ignore: deprecated_member_use
            value: state.targetGrade,
            isExpanded: true,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: '선택 (1~9등급)',
              isDense: true,
            ),
            items: [
              for (var g = 1; g <= 9; g++)
                DropdownMenuItem<int>(value: g, child: Text('$g등급')),
            ],
            onChanged: notifier.setTargetGrade,
          ),
          const SizedBox(height: AppSpacing.xl),

          // ── 목표 표준점수 — 숫자 입력(빈 값이면 미입력).
          const _FieldLabel(label: '목표 표준점수'),
          TextField(
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: '예: 130',
              isDense: true,
            ),
            onChanged: (value) =>
                notifier.setTargetScore(int.tryParse(value.trim())),
          ),
          const SizedBox(height: AppSpacing.xl),

          // ── 목표 시험일 — 날짜 선택(자유 입력 없음). YYYY-MM-DD로 서버에 전달된다.
          const _FieldLabel(label: '목표 시험일'),
          _ExamDateField(
            selected: state.targetExamDate,
            onPick: notifier.setTargetExamDate,
          ),
          const SizedBox(height: AppSpacing.xl),

          // ── 출생 연도 — 숫자 입력(연 단위·월일 미수집·미성년 개인정보 최소화).
          const _FieldLabel(label: '출생 연도'),
          TextField(
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              hintText: '예: 2008',
              isDense: true,
            ),
            onChanged: (value) =>
                notifier.setBirthYear(int.tryParse(value.trim())),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    );
  }
}

/// 폼 필드 라벨 — 접근성·시각 일관성을 위한 작은 제목.
class _FieldLabel extends StatelessWidget {
  const _FieldLabel({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs6),
      child: Text(label, style: Theme.of(context).textTheme.labelLarge),
    );
  }
}

/// 목표 시험일 선택 필드 — 탭하면 날짜 선택기를 열고 고른 날짜를 표시한다.
class _ExamDateField extends StatelessWidget {
  const _ExamDateField({required this.selected, required this.onPick});

  final DateTime? selected;
  final ValueChanged<DateTime?> onPick;

  @override
  Widget build(BuildContext context) {
    final label = selected == null
        ? '날짜 선택'
        : '${selected!.year}년 '
            '${selected!.month.toString().padLeft(2, '0')}월 '
            '${selected!.day.toString().padLeft(2, '0')}일';
    return OutlinedButton.icon(
      icon: const Icon(Icons.event_outlined),
      label: Align(
        alignment: Alignment.centerLeft,
        child: Text(label),
      ),
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
        alignment: Alignment.centerLeft,
      ),
      onPressed: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          initialDate: selected ?? now,
          // 시험일은 미래 — 오늘부터 5년 안쪽으로 범위를 둔다(현실적 상한).
          firstDate: now,
          lastDate: DateTime(now.year + 5, now.month, now.day),
        );
        if (picked != null) {
          onPick(picked);
        }
      },
    );
  }
}

/// 페이지 인디케이터 — 현재 페이지를 채운 점으로 표시한다.
class _PageIndicator extends StatelessWidget {
  const _PageIndicator({required this.count, required this.index});

  final int count;
  final int index;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(count, (i) {
        final isActive = i == index;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 240),
          margin: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
          width: isActive ? 24 : 8,
          height: 8,
          decoration: BoxDecoration(
            color: isActive
                ? theme.colorScheme.primary
                : theme.colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(4),
          ),
        );
      }),
    );
  }
}
