import 'dart:convert';
import 'dart:io';

import '../models/chat_models.dart';

/// Elyan backend istemcisi — macOS `ElyanBackend.swift`'in Dart karşılığı
/// (bu dilimde: login/register/refresh/logout + oturum kalıcılığı).
///
/// Tek beyin VPS'teki server_brain'dir; bu istemci yalnız kimlik ve oturum
/// verisi taşır. Sohbet yürütmesi Python köprüsü üzerinden yereldedir.
class ElyanBackendException implements Exception {
  final String message;
  ElyanBackendException(this.message);
  @override
  String toString() => message;
}

class ElyanBackend {
  static const String baseUrl = 'https://api.elyan.dev';

  ElyanAuthSession? session;
  final HttpClient _client = HttpClient();

  bool get isSignedIn => (session?.accessToken.isNotEmpty ?? false);

  /// POST /v1/auth/login — mobil/macOS ile aynı gövde.
  Future<ElyanAuthSession> login(
      {required String email, required String password}) async {
    final raw = await _postJson('/v1/auth/login', {
      'email': email,
      'password': password,
    });
    final parsed = _parseAuthSession(raw);
    session = parsed;
    await _persistSession();
    return parsed;
  }

  /// POST /v1/auth/register
  Future<ElyanAuthSession> register({
    required String displayName,
    required String email,
    required String password,
  }) async {
    final raw = await _postJson('/v1/auth/register', {
      'displayName': displayName,
      'email': email,
      'password': password,
    });
    final parsed = _parseAuthSession(raw);
    session = parsed;
    await _persistSession();
    return parsed;
  }

  /// POST /v1/auth/refresh
  Future<bool> refreshSession() async {
    final current = session;
    if (current == null || current.refreshToken.isEmpty) return false;
    try {
      final raw = await _postJson(
          '/v1/auth/refresh', {'refreshToken': current.refreshToken},
          requireAuth: false);
      session =
          _parseAuthSession(raw, refreshTokenFallback: current.refreshToken);
      await _persistSession();
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<void> logout() async {
    if (isSignedIn) {
      try {
        await _postJson('/v1/auth/logout', {}, requireAuth: true);
      } catch (_) {}
    }
    session = null;
    final file = _sessionFile();
    if (file.existsSync()) file.deleteSync();
  }

  // MARK: - Oturum kalıcılığı
  //
  // macOS Keychain kullanır; Windows/Linux'ta uygulama config dizinine yazılır
  // (motorla aynı dizin ailesi: %APPDATA%\Elyan / ~/.config/Elyan).

  static Directory _configDir() {
    if (Platform.isMacOS) {
      final home = Platform.environment['HOME'] ?? '';
      return Directory('$home/Library/Application Support/Elyan');
    }
    if (Platform.isWindows) {
      final appData = Platform.environment['APPDATA'] ??
          '${Platform.environment['USERPROFILE']}\\AppData\\Roaming';
      return Directory('$appData\\Elyan');
    }
    final xdg = Platform.environment['XDG_CONFIG_HOME'];
    if (xdg != null && xdg.isNotEmpty) return Directory('$xdg/Elyan');
    final home = Platform.environment['HOME'] ?? '';
    return Directory('$home/.config/Elyan');
  }

  static File _sessionFile() =>
      File('${_configDir().path}${Platform.pathSeparator}desktop_session.json');

  Future<void> _persistSession() async {
    final current = session;
    if (current == null) return;
    final dir = _configDir();
    if (!dir.existsSync()) dir.createSync(recursive: true);
    await _sessionFile().writeAsString(jsonEncode(current.toJson()));
  }

  Future<ElyanAuthSession?> restoreSession() async {
    try {
      final file = _sessionFile();
      if (!file.existsSync()) return null;
      final decoded = jsonDecode(await file.readAsString());
      if (decoded is! Map<String, dynamic>) return null;
      final restored = ElyanAuthSession.fromJson(decoded);
      if (restored.accessToken.isEmpty) return null;
      session = restored;
      return restored;
    } catch (_) {
      return null;
    }
  }

  // MARK: - HTTP

  Future<dynamic> _postJson(String path, Map<String, dynamic> body,
      {bool requireAuth = false}) async {
    final request = await _client.postUrl(Uri.parse('$baseUrl$path'));
    request.headers.contentType = ContentType.json;
    if (requireAuth) {
      final token = session?.accessToken ?? '';
      if (token.isEmpty) throw ElyanBackendException('Önce giriş yapmalısın.');
      request.headers.set('Authorization', 'Bearer $token');
    }
    request.write(jsonEncode(body));
    final response = await request.close();
    final text = await response.transform(utf8.decoder).join();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      String message = text;
      try {
        final decoded = jsonDecode(text);
        if (decoded is Map) {
          message = (decoded['message'] ?? decoded['error'] ?? text).toString();
        }
      } catch (_) {}
      throw ElyanBackendException('Sunucu (${response.statusCode}): $message');
    }
    if (text.isEmpty) return <String, dynamic>{};
    return jsonDecode(text);
  }

  /// Backend `{ data: {...} }` sarabilir — mobil `unwrapData` ile aynı.
  static Map<String, dynamic> _unwrap(dynamic raw) {
    if (raw is Map<String, dynamic>) {
      final data = raw['data'];
      if (data is Map<String, dynamic>) return data;
      return raw;
    }
    return <String, dynamic>{};
  }

  static ElyanAuthSession _parseAuthSession(dynamic raw,
      {String refreshTokenFallback = ''}) {
    final unwrapped = _unwrap(raw);
    final tokens = (unwrapped['tokens'] is Map<String, dynamic>
            ? unwrapped['tokens']
            : unwrapped['token'] is Map<String, dynamic>
                ? unwrapped['token']
                : null) as Map<String, dynamic>? ??
        unwrapped;
    final accessToken = (tokens['accessToken'] as String?) ??
        (tokens['access_token'] as String?) ??
        '';
    final refreshToken = (tokens['refreshToken'] as String?) ??
        (tokens['refresh_token'] as String?) ??
        refreshTokenFallback;
    if (accessToken.isEmpty) {
      throw ElyanBackendException(
          'Auth yanıtında access token yok.');
    }
    final user = unwrapped['user'] is Map<String, dynamic>
        ? unwrapped['user'] as Map<String, dynamic>
        : unwrapped;
    return ElyanAuthSession(
      id: (user['id'] as String?) ?? (user['userId'] as String?) ?? 'elyan-user',
      displayName:
          (user['displayName'] as String?) ?? (user['name'] as String?) ?? '',
      email: (user['email'] as String?) ?? '',
      accessToken: accessToken,
      refreshToken: refreshToken,
      hasAvatar: user['hasAvatar'] == true,
      avatarVersion: (user['avatarVersion'] as num?)?.toInt() ?? 0,
    );
  }
}
