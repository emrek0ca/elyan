import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/chat_models.dart';
import 'runtime_bridge.dart';

/// Python runtime yaşam döngüsü + yerel-öncelikli sohbet —
/// macOS `PythonRuntimeSupervisor.swift` çekirdeğinin Dart portu.
///
/// Akış macOS ile birebir: mesaj yerel runtime'da çalışır (deterministik
/// router → eşleşmezse yapılandırılmış planlayıcı VPS server_brain'e gider) →
/// plan onayı PlanCard'da → yürütme masaüstünde, canlı checklist
/// `conversation.progress` unsolicited event'leriyle akar.
class PythonRuntimeSupervisor extends ChangeNotifier {
  final RuntimeBridge bridge = RuntimeBridge();

  bool runtimeReady = false;
  String lifecycleState = 'stopped';
  String lastError = '';
  final List<String> diagnostics = [];

  String _localConversationId = '';
  ElyanAuthSession? _pendingAuthSession;
  bool _pendingAuthSync = false;
  String _lastAuthFingerprint = '';
  Timer? _crashRestartTimer;
  ElyanAuthSession? _lastStartSession;

  /// Canlı checklist bloğu geldiğinde (conversationId, task_trace map).
  void Function(String conversationId, Map<String, dynamic> block)? onProgress;

  /// Bridge access token yenilenmesi istediğinde.
  Future<void> Function()? onAuthRefreshNeeded;

  bool get isRunning => bridge.isRunning;

  PythonRuntimeSupervisor() {
    bridge.onDiagnostic = (message) {
      diagnostics.add(message);
      if (diagnostics.length > 200) diagnostics.removeAt(0);
    };
    bridge.onUnsolicitedResponse = _handleUnsolicited;
    bridge.onProcessTerminated = (code) {
      lifecycleState = 'crashed';
      runtimeReady = false;
      notifyListeners();
      // Çökme sonrası tek seferlik gecikmeli yeniden başlatma (çift-bridge
      // token yarışını önlemek için zaten planlı bir restart varsa dokunma).
      _crashRestartTimer ??= Timer(const Duration(seconds: 2), () {
        _crashRestartTimer = null;
        start(initialSession: _lastStartSession);
      });
    };
  }

  Future<void> start({ElyanAuthSession? initialSession}) async {
    _lastStartSession = initialSession;
    try {
      await bridge.startProcess();
      lifecycleState = 'starting';
      notifyListeners();
      if (initialSession != null) {
        await syncAuthSession(initialSession);
      }
      await _bootstrap();
    } catch (e) {
      lastError = e.toString();
      lifecycleState = 'failed';
      notifyListeners();
    }
  }

  Future<void> stop() async {
    _crashRestartTimer?.cancel();
    _crashRestartTimer = null;
    bridge.stopProcess();
    lifecycleState = 'stopped';
    runtimeReady = false;
    notifyListeners();
  }

  Future<void> _bootstrap() async {
    try {
      final response = await bridge.request('runtime.bootstrap',
          timeout: const Duration(seconds: 60));
      runtimeReady = response.ok;
      lifecycleState = response.ok ? 'runtime_started' : 'degraded';
    } catch (e) {
      lastError = e.toString();
      lifecycleState = 'degraded';
    }
    notifyListeners();
  }

  // MARK: - Auth senkronu

  Future<void> syncAuthSession(ElyanAuthSession? session) async {
    _pendingAuthSession = session;
    _pendingAuthSync = true;
    await _flushPendingAuthSync();
  }

  Future<void> _flushPendingAuthSync() async {
    if (!isRunning || !_pendingAuthSync) return;
    final session = _pendingAuthSession;
    final fingerprint = session == null
        ? 'signed_out'
        : '${session.id}|${session.email}|${session.accessToken}';
    if (fingerprint == _lastAuthFingerprint) {
      _pendingAuthSync = false;
      return;
    }
    final payload = session == null
        ? <String, dynamic>{'signedIn': false}
        : <String, dynamic>{
            'signedIn': true,
            'id': session.id,
            'email': session.email,
            'displayName': session.displayName,
            'accessToken': session.accessToken,
            'refreshToken': session.refreshToken,
          };
    try {
      await bridge.request('backend.auth_sync_session',
          payload: payload, timeout: const Duration(seconds: 20));
      _pendingAuthSync = false;
      _lastAuthFingerprint = fingerprint;
    } catch (e) {
      lastError = e.toString();
    }
  }

  // MARK: - Yerel-öncelikli sohbet

  void setLocalConversation(String id) => _localConversationId = id;

  /// Bridge süreci düşükse toparlar; yalnız süreç canlılığını hedefler.
  Future<bool> ensureLocalReady() async {
    if (isRunning) return true;
    if (_crashRestartTimer == null) {
      await start(initialSession: _lastStartSession);
    }
    for (var i = 0; i < 32; i++) {
      if (isRunning) return true;
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
    return isRunning;
  }

  Future<LocalChatReply> sendLocalChat(String text) async {
    if (!isRunning) {
      throw RuntimeBridgeException(
          'RUNTIME_NOT_STARTED', 'Python runtime henüz başlatılmadı.');
    }
    final response = await bridge.request(
      'conversation.send',
      payload: {'conversationId': _localConversationId, 'text': text},
      timeout: const Duration(seconds: 180),
    );
    final map = response.result;
    final cid = (map['conversationId'] as String?) ?? '';
    if (cid.isNotEmpty) _localConversationId = cid;
    final content = (map['assistantMessage'] as String?) ?? '';
    if (!response.ok || content.isEmpty) {
      final message = (map['error'] is Map
              ? (map['error'] as Map)['message'] as String?
              : null) ??
          response.errorMessage;
      throw RuntimeBridgeException('LOCAL_CHAT_FAILED',
          message.isEmpty ? 'Yerel runtime yanıt üretemedi.' : message);
    }
    return LocalChatReply(
      text: content,
      needsConfirmation: map['needsConfirmation'] == true,
      plan: PendingPlan.parse(map),
      permission: PermissionRequest.parse(map, text),
    );
  }

  Future<LocalChatReply> confirmLocalPlan({
    required String conversationId,
    required String pendingPlanId,
    required bool approved,
  }) async {
    final response = await bridge.request(
      'conversation.confirm_plan',
      payload: {
        'conversationId': conversationId,
        'pendingPlanId': pendingPlanId,
        'approved': approved,
      },
      timeout: const Duration(seconds: 600),
    );
    final map = response.result;
    final cid = (map['conversationId'] as String?) ?? '';
    if (cid.isNotEmpty) _localConversationId = cid;
    final fallback = approved ? 'Plan yürütüldü.' : 'İşlem iptal edildi.';
    return LocalChatReply(
      text: (map['assistantMessage'] as String?) ?? fallback,
      needsConfirmation: map['needsConfirmation'] == true,
      plan: PendingPlan.parse(map),
      permission: null,
    );
  }

  /// Yerel konuşma listesi (bridge `conversation.list`) — sidebar geçmişine
  /// "Yerel" rozetiyle karışır.
  Future<List<ElyanSessionSummary>> localConversations() async {
    if (!isRunning) return const [];
    try {
      final response = await bridge.request('conversation.list',
          timeout: const Duration(seconds: 15));
      final items = response.result['items'];
      if (items is! List) return const [];
      return [
        for (final item in items)
          if (item is Map)
            ElyanSessionSummary(
              id: (item['id'] as String?) ?? '',
              title: (item['title'] as String?) ?? 'Yeni sohbet',
              lastMessage: (item['lastMessage'] as String?) ?? '',
              isLocal: true,
            ),
      ];
    } catch (_) {
      return const [];
    }
  }

  void _handleUnsolicited(RuntimeResponse response) {
    switch (response.capability) {
      case 'bridge.ready':
        runtimeReady = response.ok;
        lifecycleState = response.ok ? 'runtime_started' : 'degraded';
        notifyListeners();
        // Süreç yeni ayaklandıysa bekleyen auth senkronunu tamamla.
        unawaited(_flushPendingAuthSync());
        break;
      case 'backend.auth_refresh_needed':
        final handler = onAuthRefreshNeeded;
        if (handler != null) unawaited(handler());
        break;
      case 'conversation.progress':
        final cid = (response.result['conversationId'] as String?) ?? '';
        final block = response.result['block'];
        if (block is Map<String, dynamic>) {
          onProgress?.call(cid, block);
        }
        break;
    }
  }

  @override
  void dispose() {
    _crashRestartTimer?.cancel();
    bridge.stopProcess();
    super.dispose();
  }
}
