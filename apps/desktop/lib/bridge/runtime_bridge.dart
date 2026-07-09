import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Python runtime köprüsü — macOS `RuntimeBridgeSwift`'in Dart portu.
///
/// Sözleşme birebir aynı: `runtime/bridge.py` alt süreci stdin/stdout üzerinden
/// satır-başına-bir-JSON konuşur. İstek `{id, taskId, capability, payload}`,
/// yanıt `id` ile eşleştirilir; eşleşmeyen yanıtlar unsolicited event'tir
/// (bridge.ready, conversation.progress, backend.auth_refresh_needed ...).
class RuntimeBridgeException implements Exception {
  final String code;
  final String message;
  RuntimeBridgeException(this.code, this.message);
  @override
  String toString() => message;
}

class RuntimeResponse {
  final String id;
  final bool ok;
  final String capability;
  final Map<String, dynamic> result;
  final Map<String, dynamic>? error;

  RuntimeResponse.fromJson(Map<String, dynamic> json)
      : id = (json['id'] ?? '') as String,
        ok = json['ok'] == true,
        capability = (json['capability'] ?? '') as String,
        result = (json['result'] is Map<String, dynamic>)
            ? json['result'] as Map<String, dynamic>
            : <String, dynamic>{},
        error = json['error'] is Map<String, dynamic>
            ? json['error'] as Map<String, dynamic>
            : null;

  String get errorMessage =>
      (error?['message'] as String?) ?? 'Runtime hatası.';
}

class RuntimeBridge {
  Process? _process;
  final Map<String, Completer<RuntimeResponse>> _pending = {};
  StreamSubscription<String>? _stdoutSub;
  StreamSubscription<String>? _stderrSub;
  bool _stoppingIntentionally = false;
  int _requestCounter = 0;

  void Function(RuntimeResponse response)? onUnsolicitedResponse;
  void Function(String message)? onDiagnostic;

  /// Yalnız gerçek çökmede tetiklenir (bilinçli stop'ta değil).
  void Function(int exitCode)? onProcessTerminated;

  bool get isRunning => _process != null;

  /// Motoru bulur ve başlatır. Öncelik macOS tarafıyla aynı:
  /// 1) kaynak checkout + venv (geliştirme) 2) paketli runtime (dağıtım).
  Future<void> startProcess() async {
    if (_process != null) return;
    _stoppingIntentionally = false;

    final repoRoot = _resolveRepoRoot();
    String executable;
    List<String> arguments;

    final packaged = _resolvePackagedRuntime(repoRoot);
    if (packaged != null) {
      executable = packaged;
      arguments = const [];
      onDiagnostic?.call('Paketli Elyan runtime başlatılıyor.');
    } else {
      if (repoRoot == null) {
        throw RuntimeBridgeException(
            'REPO_ROOT_NOT_FOUND', 'Elyan repo kökü bulunamadı.');
      }
      final bridgeScript = '$repoRoot/runtime/bridge.py';
      if (!File(bridgeScript).existsSync()) {
        throw RuntimeBridgeException('BRIDGE_NOT_FOUND',
            'Python runtime bridge bulunamadı: $bridgeScript');
      }
      final python = _resolvePython(repoRoot);
      executable = python;
      arguments = ['-u', bridgeScript];
    }

    final env = Map<String, String>.from(Platform.environment);
    env['PYTHONUNBUFFERED'] = '1';
    // HİBRİT mod: basit komutlar yerel/deterministik; eşleşmeyenler sunucu
    // beynine (server_brain) gider. Yerel LLM bilinçli olarak yok.
    env.remove('ELYAN_DETERMINISTIC_ONLY');
    if (repoRoot != null) env['ELYAN_REPO_ROOT'] = repoRoot;

    final process = await Process.start(
      executable,
      arguments,
      workingDirectory: repoRoot ?? _homeDir,
      environment: env,
    );
    _process = process;

    _stdoutSub = process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(_consumeLine);
    _stderrSub = process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      final trimmed = line.trim();
      if (trimmed.isNotEmpty) onDiagnostic?.call(trimmed);
    });

    unawaited(process.exitCode.then((code) {
      final wasIntentional = _stoppingIntentionally;
      _failAllPending(RuntimeBridgeException(
          'PROCESS_EXITED', 'Python runtime kapandı (exit $code).'));
      _process = null;
      if (!wasIntentional) onProcessTerminated?.call(code);
    }));
  }

  void stopProcess() {
    _stoppingIntentionally = true;
    _stdoutSub?.cancel();
    _stderrSub?.cancel();
    _process?.kill(ProcessSignal.sigterm);
    _process = null;
    _failAllPending(RuntimeBridgeException(
        'RUNTIME_NOT_STARTED', 'Python runtime henüz başlatılmadı.'));
  }

  Future<RuntimeResponse> request(
    String capability, {
    Map<String, dynamic> payload = const {},
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final process = _process;
    if (process == null) {
      throw RuntimeBridgeException(
          'RUNTIME_NOT_STARTED', 'Python runtime henüz başlatılmadı.');
    }

    _requestCounter += 1;
    final id = 'req_${DateTime.now().millisecondsSinceEpoch}_$_requestCounter';
    final envelope = <String, dynamic>{
      'id': id,
      'taskId': 'task_${id.substring(4)}',
      'capability': capability,
      'payload': payload,
    };

    final completer = Completer<RuntimeResponse>();
    _pending[id] = completer;

    try {
      process.stdin.writeln(jsonEncode(envelope));
    } catch (e) {
      _pending.remove(id);
      throw RuntimeBridgeException(
          'WRITE_FAILED', 'Runtime ile bağlantı koptu: $e');
    }

    return completer.future.timeout(timeout, onTimeout: () {
      _pending.remove(id);
      throw RuntimeBridgeException('RESPONSE_TIMEOUT',
          'Sunucuya ulaşılamıyor. Ağ bağlantını kontrol edip tekrar dene.');
    });
  }

  void _consumeLine(String line) {
    if (line.trim().isEmpty) return;
    Map<String, dynamic> decoded;
    try {
      final parsed = jsonDecode(line);
      if (parsed is! Map<String, dynamic>) return;
      decoded = parsed;
    } catch (_) {
      final preview = line.length > 120 ? line.substring(0, 120) : line;
      onDiagnostic?.call('Runtime yanıtı çözümlenemedi: $preview');
      return;
    }
    final response = RuntimeResponse.fromJson(decoded);
    final completer = _pending.remove(response.id);
    if (completer != null) {
      completer.complete(response);
    } else {
      onUnsolicitedResponse?.call(response);
    }
  }

  void _failAllPending(Object error) {
    final pending = List.of(_pending.values);
    _pending.clear();
    for (final completer in pending) {
      if (!completer.isCompleted) completer.completeError(error);
    }
  }

  static String get _homeDir =>
      Platform.environment['HOME'] ??
      Platform.environment['USERPROFILE'] ??
      Directory.current.path;

  /// `runtime/bridge.py` içeren köke, ELYAN_REPO_ROOT → cwd → çalıştırılabilir
  /// konumundan yukarı yürüyerek ulaşır (RuntimeBridgeSwift.resolveRepoRoot).
  static String? _resolveRepoRoot() {
    final candidates = <String>[];
    final override = Platform.environment['ELYAN_REPO_ROOT'];
    if (override != null && override.isNotEmpty) candidates.add(override);
    candidates.add(Directory.current.path);
    candidates.add(File(Platform.resolvedExecutable).parent.path);

    for (final candidate in candidates) {
      var current = Directory(candidate);
      for (var i = 0; i < 8; i++) {
        if (File('${current.path}/runtime/bridge.py').existsSync()) {
          return current.path;
        }
        final parent = current.parent;
        if (parent.path == current.path) break;
        current = parent;
      }
    }
    return null;
  }

  static String _resolvePython(String repoRoot) {
    final candidates = Platform.isWindows
        ? [
            '$repoRoot\\venv\\Scripts\\python.exe',
            '$repoRoot\\.venv\\Scripts\\python.exe',
          ]
        : [
            '$repoRoot/venv/bin/python3',
            '$repoRoot/.venv/bin/python3',
          ];
    for (final candidate in candidates) {
      if (File(candidate).existsSync()) return candidate;
    }
    // Sınırlı fallback: sistem Python'u.
    return Platform.isWindows ? 'python' : 'python3';
  }

  /// Dağıtılmış kurulumda dondurulmuş runtime ikilisi. Geliştirme
  /// makinesinde kaynak+venv varsa bilinçli olarak KULLANILMAZ (bayat paket
  /// canlı kodun önüne geçmesin — RuntimeBridgeSwift'teki kararın aynısı).
  static String? _resolvePackagedRuntime(String? repoRoot) {
    if (repoRoot != null &&
        File('$repoRoot/runtime/bridge.py').existsSync()) {
      final venvPython = Platform.isWindows
          ? '$repoRoot\\venv\\Scripts\\python.exe'
          : '$repoRoot/venv/bin/python3';
      final dotVenvPython = Platform.isWindows
          ? '$repoRoot\\.venv\\Scripts\\python.exe'
          : '$repoRoot/.venv/bin/python3';
      if (File(venvPython).existsSync() || File(dotVenvPython).existsSync()) {
        return null;
      }
    }

    final exeDir = File(Platform.resolvedExecutable).parent.path;
    final binaryName =
        Platform.isWindows ? 'elyan-runtime.exe' : 'elyan-runtime';
    final osDir = Platform.isWindows
        ? 'windows'
        : Platform.isMacOS
            ? 'macos'
            : 'linux';
    final candidates = <String>[
      '$exeDir/elyan-runtime/$binaryName',
      '$exeDir/data/elyan-runtime/$binaryName',
      if (repoRoot != null)
        '$repoRoot/build/runtime/$osDir/elyan-runtime/$binaryName',
    ];
    for (final candidate in candidates) {
      if (File(candidate).existsSync()) return candidate;
    }
    return null;
  }
}
