// 골든 패스 HTTP 클라이언트 — 서버 `golden.api:app`의 엔드포인트 3개만 부른다(S6).
//
// 옛 `core/api_client.dart`의 `dioProvider`는 쓰지 않는다 — 인증 인터셉터가 붙어 있는데
// 골든 패스는 닉네임만으로 시작하므로 필요 없다. 옛 코드에서 가져오는 것은 베이스 URL
// (`Env.apiUrl`, `--dart-define=API_URL=`) 하나뿐이다.
//
// 수학 로직은 여기에도 없다 — 채점·숙련도 계산은 전부 서버가 하고, 여기서는 받은 JSON을
// Dart 클래스로 옮기기만 한다.

import 'package:dio/dio.dart';

import '../core/env.dart';

/// 서버에 닿지 못했을 때(꺼짐·타임아웃) 화면에 보여줄 문구 — 지시서 S6 그대로.
const String kServerUnreachableMessage = '서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.';

/// `POST /golden/session` 응답.
class GoldenSession {
  const GoldenSession({
    required this.sessionId,
    required this.nickname,
    required this.mastery,
  });

  final String sessionId;
  final String nickname;

  /// 숙련도 0.0~1.0 (같은 닉네임이면 서버가 이어받은 값을 준다).
  final double mastery;

  factory GoldenSession.fromJson(Map<String, dynamic> json) => GoldenSession(
        sessionId: json['session_id'] as String,
        nickname: json['nickname'] as String,
        mastery: (json['mastery'] as num).toDouble(),
      );
}

/// `GET /golden/next` 응답 — 문제 1개. 정답·힌트 필드는 받지 않는다(서버도 평소엔 안 보낸다).
class GoldenProblem {
  const GoldenProblem({
    required this.id,
    required this.stem,
    required this.index,
    required this.total,
  });

  /// 문항 ID (예: "LF-07").
  final String id;

  /// 문제 본문 — 한국어 + 인라인 LaTeX(`$...$`).
  final String stem;

  /// 몇 번째 문제인지(1부터) / 전체 문항 수.
  final int index;
  final int total;

  factory GoldenProblem.fromJson(Map<String, dynamic> json) => GoldenProblem(
        id: json['id'] as String,
        stem: json['stem'] as String,
        index: json['index'] as int,
        total: json['total'] as int,
      );
}

/// `POST /golden/answer` 응답 — 종류가 둘이라 sealed class로 나눈다.
///
/// - [TutorTurn]: 튜터의 되묻기(아직 판정 안 함)
/// - [Graded]: 판정(맞음/틀림)과 갱신된 숙련도
sealed class AnswerResult {
  const AnswerResult();

  factory AnswerResult.fromJson(Map<String, dynamic> json) {
    final Object? kind = json['kind'];
    switch (kind) {
      case 'tutor_turn':
        return TutorTurn(
          message: json['message'] as String,
          turn: json['turn'] as int,
          // 서버가 LLM 장애로 대체 문장을 냈을 때만 붙는 선택 필드(S4).
          degraded: json['degraded'] == true,
        );
      case 'graded':
        return Graded(
          correct: json['correct'] as bool,
          mastery: (json['mastery'] as num).toDouble(),
          turnsUsed: json['turns_used'] as int,
          feedback: json['feedback'] as String,
        );
      default:
        // 계약에 없는 kind — 조용히 넘기지 않고 예외로 알린다.
        throw FormatException('알 수 없는 응답 kind: $kind');
    }
  }
}

/// 튜터 되묻기 1턴.
final class TutorTurn extends AnswerResult {
  const TutorTurn({
    required this.message,
    required this.turn,
    this.degraded = false,
  });

  /// 튜터의 되묻기 1~3문장.
  final String message;

  /// 이 문제에서 몇 번째 튜터 턴인지(1~3).
  final int turn;

  /// 서버가 LLM 대신 대체 문장을 썼는지.
  final bool degraded;
}

/// 판정 결과 — 맞음/틀림은 서버가 정한 값을 그대로 받는다.
final class Graded extends AnswerResult {
  const Graded({
    required this.correct,
    required this.mastery,
    required this.turnsUsed,
    required this.feedback,
  });

  final bool correct;

  /// 갱신된 숙련도 0.0~1.0.
  final double mastery;
  final int turnsUsed;

  /// 서버가 준 한 줄 피드백(결과 화면은 S7에서 쓴다).
  final String feedback;
}

/// API 호출 실패 — 화면에 그대로 보여줄 한국어 문구를 담는다.
class GoldenApiException implements Exception {
  const GoldenApiException(this.message);

  final String message;

  @override
  String toString() => 'GoldenApiException: $message';
}

/// 골든 패스 API 3개를 부르는 클라이언트.
///
/// 위젯 테스트는 이 클래스를 `implements`한 가짜를 Provider로 주입한다(Dart는 모든 클래스가
/// 암묵적 인터페이스라 별도 추상 클래스를 만들지 않는다).
class GoldenApi {
  GoldenApi({Dio? dio})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: Env.apiUrl,
                // 서버 꺼짐은 빨리 알아차리고, 튜터 응답(LLM 1회 호출 — S4 실측 3~9초)은 넉넉히 기다린다.
                connectTimeout: const Duration(seconds: 5),
                sendTimeout: const Duration(seconds: 10),
                receiveTimeout: const Duration(seconds: 30),
              ),
            );

  final Dio _dio;

  /// GP-1 세션 시작 — 닉네임만 보낸다.
  Future<GoldenSession> createSession(String nickname) async {
    final Map<String, dynamic> json = await _call(
      () => _dio.post<Map<String, dynamic>>(
        '/golden/session',
        data: <String, Object>{'nickname': nickname},
      ),
    );
    return GoldenSession.fromJson(json);
  }

  /// GP-2 문제 제시 — 세션의 현재 문제를 받는다.
  Future<GoldenProblem> nextProblem(String sessionId) async {
    final Map<String, dynamic> json = await _call(
      () => _dio.get<Map<String, dynamic>>(
        '/golden/next',
        queryParameters: <String, Object>{'session_id': sessionId},
      ),
    );
    return GoldenProblem.fromJson(json);
  }

  /// GP-3 답변 전송 → 튜터 되묻기 또는 판정.
  Future<AnswerResult> answer(
    String sessionId,
    String problemId,
    String text,
  ) async {
    final Map<String, dynamic> json = await _call(
      () => _dio.post<Map<String, dynamic>>(
        '/golden/answer',
        data: <String, Object>{
          'session_id': sessionId,
          'problem_id': problemId,
          'text': text,
        },
      ),
    );
    return AnswerResult.fromJson(json);
  }

  /// 요청 1회 + 실패를 [GoldenApiException]으로 바꾼다(앱이 죽지 않게).
  Future<Map<String, dynamic>> _call(
    Future<Response<Map<String, dynamic>>> Function() send,
  ) async {
    try {
      final Response<Map<String, dynamic>> res = await send();
      final Map<String, dynamic>? body = res.data;
      if (body == null) {
        throw const GoldenApiException('서버 응답이 비어 있어요.');
      }
      return body;
    } on DioException catch (e) {
      throw GoldenApiException(_messageFor(e));
    }
  }

  /// Dio 오류 종류 → 화면 문구. 서버 꺼짐·타임아웃은 지시서의 고정 문구로 통일한다.
  static String _messageFor(DioException e) {
    if (e.type == DioExceptionType.badResponse) {
      // 서버에는 닿았지만 오류 코드(404 = 모르는 세션·문제, 422 = 입력 형식 등)
      final int? code = e.response?.statusCode;
      if (code == 404) {
        return '세션이나 문제를 찾지 못했어요. 처음부터 다시 시작해 주세요.';
      }
      return '요청을 처리하지 못했어요 (HTTP $code).';
    }
    // 그 밖(연결 거부·각종 타임아웃·인증서·취소·알 수 없음)은 전부 "서버에 닿지 못함"으로 본다.
    // (Dio 버전마다 오류 종류가 늘어나므로 개별 나열 대신 기본값으로 묶는다)
    return kServerUnreachableMessage;
  }
}
