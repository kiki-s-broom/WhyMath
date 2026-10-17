// 마지막 대화 세션 ID(dialogueId) 영속 — shared_preferences 래퍼. 복귀 지원 최소 착지(MOB-11).
//
// 경계(CLAUDE.md): 여기 저장하는 건 세션 *참조*(UUID 문자열)일 뿐 대화 *내용*이 아니다 —
// 내용은 서버가 갖고 있고 재시작 시 `GET /v1/coach/sessions/{id}`로 다시 받아온다. 민감한
// 대화 본문을 클라에 영속하지 않으므로(TokenStore와 달리) OS 보안 저장소가 아니라
// shared_preferences로 충분하다.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 마지막 대화 세션 ID 저장소 경계 — 읽기·쓰기.
abstract interface class DialogueStore {
  /// 마지막으로 활성이던 대화 세션 ID(없으면 null).
  Future<String?> readDialogueId();

  /// 새로 생성된 세션 ID를 저장한다(이후 재시작 시 이어하기 대상).
  Future<void> saveDialogueId(String dialogueId);

  /// 저장된 세션 참조를 지운다(로그아웃 — 같은 기기의 다음 학생이 이전 세션 참조를 물려받지 않게).
  Future<void> clearDialogueId();
}

/// shared_preferences 기반 실 구현.
class SharedPreferencesDialogueStore implements DialogueStore {
  const SharedPreferencesDialogueStore();

  static const _key = 'last_dialogue_id';

  @override
  Future<String?> readDialogueId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_key);
  }

  @override
  Future<void> saveDialogueId(String dialogueId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, dialogueId);
  }

  @override
  Future<void> clearDialogueId() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }
}

/// 앱 전역 대화 저장소 provider — 실 구현([SharedPreferencesDialogueStore]) 주입.
final dialogueStoreProvider = Provider<DialogueStore>(
  (ref) => const SharedPreferencesDialogueStore(),
);
