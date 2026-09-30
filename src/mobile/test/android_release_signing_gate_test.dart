// Android release 서명 게이트 배선 테스트 (MOB-15 결함 B).
//
// 무엇을 막는가: `android/app/build.gradle`의 release 빌드타입은 아직 실 keystore가 없어
// debug 키로 서명한다(사전 릴리스 상태 — 정상). 실 keystore 생성·Play Console 서명키 등록은
// Kiki 소유 비밀/계정이 필요해 기계 대체가 불가하므로(사람 소유 행위 — 서명키는 저장소
// 밖 비밀), 이 결함의 승격은 사람 게이트(`G-android-release-store-signing`,
// backlog/gates.yaml)로 처리했다 — 코드가 임의로 실 signingConfig로 바꾸지 않는다.
//
// 이 테스트가 동결하는 것은 "배선이 끊기지 않았는가"다: release가 여전히 debug 키로 서명
// 중이라면 그 사실을 알리는 게이트 참조 문자열이 build.gradle에 반드시 남아 있어야 한다.
// 주석만 삭제되고 debug 서명이 남으면(추적이 끊긴 채 위험만 남는 상태) 회귀로 fail한다.
// 반대로 release가 실 서명키로 전환됐다면(개선) 게이트 참조 유무와 무관하게 pass한다
// (오탐 방지 — 실 전환 자체를 막는 테스트가 되면 안 된다).
//
// 술어는 순수 함수로 분리하고 결함주입 테스트를 동반한다(mathlive_autofocus_test.dart 관례 —
// 변별력 없는 검사는 위장 검사다·CLAUDE.md).
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 게이트 추적용 마커 — build.gradle·backlog/gates.yaml 양쪽에서 동일해야 한다.
const String _gateId = 'G-android-release-store-signing';

/// release 블록이 `signingConfigs.debug`로 서명하는 상태인가.
///
/// 정규식은 `release { ... }` 블록 *내부*에서 `signingConfig = signingConfigs.debug`를
/// 찾는다(다른 buildType 블록의 우연한 문자열 일치를 피하기 위해 블록 범위로 검사).
bool _releaseSignsWithDebugKey(String gradle) {
  final RegExpMatch? releaseBlock =
      RegExp(r'release\s*\{([\s\S]*?)\n\s*\}', multiLine: true)
          .firstMatch(gradle);
  if (releaseBlock == null) return false;
  final String body = releaseBlock.group(1) ?? '';
  return RegExp(r'signingConfig\s*=\s*signingConfigs\.debug').hasMatch(body);
}

/// build.gradle이 추적 게이트 ID를 언급하는가(release 블록 근방 포함 전체 파일 스캔으로 충분 —
/// 이 파일에 다른 목적의 동일 문자열이 우연히 등장할 일은 없다).
bool _referencesTrackingGate(String gradle) => gradle.contains(_gateId);

/// 이 결함의 게이트 배선이 온전한가 — 핵심 판정 함수.
///
/// - debug 서명이 아니면(=실 서명키로 전환됨) 무조건 pass(개선은 막지 않는다).
/// - debug 서명이면 게이트 참조가 반드시 있어야 pass(참조가 사라지면 회귀 — 추적 없이
///   위험만 남은 상태이므로 fail).
bool _signingGateWiringIsIntact(String gradle) {
  if (!_releaseSignsWithDebugKey(gradle)) return true;
  return _referencesTrackingGate(gradle);
}

void main() {
  // 테스트 실행 cwd = src/mobile(mathlive_autofocus_test.dart 등 기존 관례와 동일).
  final String gradleSource =
      File('android/app/build.gradle').readAsStringSync();

  group('현재 build.gradle — 서명 게이트 배선이 온전하다', () {
    // 스캔 0건은 실패(CLAUDE.md "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지" ④):
    // release 블록을 못 찾으면 `_releaseSignsWithDebugKey`가 false → 종합 판정이 공허하게 pass한다.
    // 파일 구조가 바뀌어 술어가 대상을 놓치는 상태를 먼저 RED로 막는다.
    test('release 블록을 찾는다(술어가 실제 파일에 닿는다)', () {
      expect(
        RegExp(r'release\s*\{([\s\S]*?)\n\s*\}', multiLine: true).hasMatch(gradleSource),
        isTrue,
        reason: 'android/app/build.gradle에서 release 블록을 찾지 못하면 이 게이트 검사는 공허하다',
      );
    });

    test('debug 서명 중이면 추적 게이트 $_gateId를 참조한다', () {
      // 실 서명키로 전환됐다면(개선) 이 검사는 적용되지 않는다 — 전환 자체를 막지 않는다.
      if (!_releaseSignsWithDebugKey(gradleSource)) {
        return;
      }
      expect(
        _referencesTrackingGate(gradleSource),
        isTrue,
        reason: 'debug 서명 상태에선 사람 게이트 참조가 반드시 남아 있어야 스토어 배포 착수 '
            '시점에 이 위험이 감지된다(backlog/gates.yaml)',
      );
    });

    test('종합: 서명 게이트 배선이 온전하다', () {
      expect(_signingGateWiringIsIntact(gradleSource), isTrue);
    });
  });

  group('결함주입 — 술어가 변별력을 갖는다', () {
    test('debug 서명 + 게이트 문자열 없음 → fail', () {
      const String synthetic = '''
        buildTypes {
            release {
                signingConfig = signingConfigs.debug
            }
        }
      ''';
      expect(_releaseSignsWithDebugKey(synthetic), isTrue);
      expect(_referencesTrackingGate(synthetic), isFalse);
      expect(
        _signingGateWiringIsIntact(synthetic),
        isFalse,
        reason: '게이트 주석이 삭제된 채 debug 서명만 남은 회귀 상태 — 반드시 fail해야 한다',
      );
    });

    test('release가 debug가 아닌 다른 signingConfig로 전환 → 게이트 문자열 유무와 무관하게 pass', () {
      const String syntheticNoGate = '''
        buildTypes {
            release {
                signingConfig = signingConfigs.release
            }
        }
      ''';
      const String syntheticWithGate = '''
        buildTypes {
            release {
                // 예전엔 G-android-release-store-signing 게이트로 추적했으나 이제 실 서명키 사용.
                signingConfig = signingConfigs.release
            }
        }
      ''';
      expect(_releaseSignsWithDebugKey(syntheticNoGate), isFalse);
      expect(_signingGateWiringIsIntact(syntheticNoGate), isTrue,
          reason: '실 서명키 전환은 개선이지 회귀가 아니다 — 게이트 문자열이 없어도 pass');
      expect(_signingGateWiringIsIntact(syntheticWithGate), isTrue);
    });

    test('release 블록 자체가 없으면(파싱 실패) debug 서명 아님으로 처리되어 pass', () {
      const String noReleaseBlock = '''
        buildTypes {
            debug {
                applicationIdSuffix ".debug"
            }
        }
      ''';
      expect(_releaseSignsWithDebugKey(noReleaseBlock), isFalse);
      expect(_signingGateWiringIsIntact(noReleaseBlock), isTrue);
    });

    test('다른 buildType(debug)이 우연히 게이트와 무관한 텍스트를 가져도 오탐하지 않는다', () {
      const String debugBlockOnly = '''
        buildTypes {
            debug {
                signingConfig = signingConfigs.debug
            }
            release {
                signingConfig = signingConfigs.debug
            }
        }
      ''';
      // release 블록 자체에서 debug 서명을 검출해야 하며(주변 debug 블록과 혼동 없이),
      // 게이트 문자열이 없으므로 여전히 fail이어야 한다.
      expect(_releaseSignsWithDebugKey(debugBlockOnly), isTrue);
      expect(_signingGateWiringIsIntact(debugBlockOnly), isFalse);
    });
  });
}
