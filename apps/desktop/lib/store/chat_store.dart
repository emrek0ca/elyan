import 'package:flutter/foundation.dart';

import '../bridge/runtime_supervisor.dart';
import '../models/chat_models.dart';

/// Sohbet durumu — macOS `ChatStore.swift`'in saf-yerel `send()` akışının
/// Dart portu. Bulut SSE yolu bilinçli olarak YOK (macOS'ta kaldırıldı):
/// mesaj → localRecover → sendLocalChat; başarısızsa gerçek durum gösterilir.
class ChatStore extends ChangeNotifier {
  final PythonRuntimeSupervisor supervisor;

  final List<ChatMessage> messages = [];
  bool isStreaming = false;
  String lastError = '';
  int _messageCounter = 0;

  ChatStore(this.supervisor) {
    supervisor.onProgress = applyProgressBlock;
  }

  String _nextId() => 'msg_${DateTime.now().millisecondsSinceEpoch}_'
      '${_messageCounter++}';

  void reset() {
    messages.clear();
    lastError = '';
    isStreaming = false;
    supervisor.setLocalConversation('');
    notifyListeners();
  }

  Future<void> send(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || isStreaming) return;
    lastError = '';

    // İyimser kullanıcı baloncuğu — ağdan önce ekranda.
    messages.add(ChatMessage(id: _nextId(), role: ChatRole.user, text: trimmed));
    final assistant =
        ChatMessage(id: _nextId(), role: ChatRole.assistant, text: '');
    messages.add(assistant);
    isStreaming = true;
    notifyListeners();

    try {
      final recovered = await supervisor.ensureLocalReady();
      if (!recovered) {
        throw Exception(
            'Motor yeniden bağlanıyor olabilir — birkaç saniye sonra tekrar dene. '
            '(${supervisor.lifecycleState}'
            '${supervisor.lastError.isEmpty ? '' : ': ${supervisor.lastError}'})');
      }
      final reply = await supervisor.sendLocalChat(trimmed);
      _finishLocal(assistant, reply);
    } catch (e) {
      assistant.text = '';
      lastError = e.toString();
      messages.remove(assistant);
    } finally {
      isStreaming = false;
      notifyListeners();
    }
  }

  void _finishLocal(ChatMessage assistant, LocalChatReply reply) {
    assistant.text = reply.text;
    assistant.plan = reply.plan;
    assistant.permission = reply.permission;
  }

  Future<void> confirmPlan(String messageId, bool approved) async {
    final message = messages.where((m) => m.id == messageId).firstOrNull;
    final plan = message?.plan;
    if (message == null || plan == null || plan.isConfirming) return;
    plan.isConfirming = true;
    notifyListeners();

    // Onayda CANLI baloncuk: checklist orada tik atar, sonuç oraya yerleşir.
    final live = approved
        ? (ChatMessage(id: _nextId(), role: ChatRole.assistant, text: ''))
        : null;
    if (live != null) {
      messages.add(live);
      isStreaming = true;
      notifyListeners();
    }

    try {
      final reply = await supervisor.confirmLocalPlan(
        conversationId: plan.conversationId,
        pendingPlanId: plan.pendingPlanId,
        approved: approved,
      );
      message.plan = null;
      if (live != null) {
        _finishLocal(live, reply);
        finalizeChecklist(live);
      } else {
        messages.add(ChatMessage(
            id: _nextId(), role: ChatRole.assistant, text: reply.text));
      }
    } catch (e) {
      plan.isConfirming = false;
      lastError = e.toString();
      if (live != null) {
        finalizeChecklist(live, failed: true);
        if (live.text.isEmpty && live.taskTrace == null) messages.remove(live);
      }
    } finally {
      isStreaming = false;
      notifyListeners();
    }
  }

  Future<void> grantPermission(String messageId) async {
    final message = messages.where((m) => m.id == messageId).firstOrNull;
    final permission = message?.permission;
    if (message == null || permission == null || permission.isGranting) return;
    permission.isGranting = true;
    notifyListeners();
    try {
      await supervisor.bridge.request('permissions.grant', payload: {
        'permissionKey': permission.permissionKey,
      });
      message.permission = null;
      // İzin verildi — komutu otomatik yeniden çalıştır.
      if (permission.originalText.isNotEmpty) {
        await send(permission.originalText);
      }
    } catch (e) {
      permission.isGranting = false;
      lastError = e.toString();
    } finally {
      notifyListeners();
    }
  }

  Future<void> openSystemPermission(String messageId) async {
    final message = messages.where((m) => m.id == messageId).firstOrNull;
    final permission = message?.permission;
    if (permission == null) return;
    try {
      await supervisor.bridge.request('desktop_os.open_permission_settings',
          payload: {'permission': permission.systemPermissionKey});
    } catch (e) {
      lastError = e.toString();
      notifyListeners();
    }
  }

  /// Canlı checklist: gelen task_trace bloğunu aktif asistan mesajına işler.
  void applyProgressBlock(String conversationId, Map<String, dynamic> block) {
    final trace = TaskTraceBlock.parse(block);
    if (trace == null) return;
    // Progress hedefi: akış hâlindeki son asistan baloncuğu; yoksa
    // aynı stableBlockId'yi taşıyan mesaj (yarışta geç gelen final event).
    ChatMessage? host;
    for (final message in messages.reversed) {
      if (message.role != ChatRole.assistant) continue;
      if (message.taskTrace?.stableBlockId == trace.stableBlockId) {
        host = message;
        break;
      }
      if (isStreaming && host == null) {
        host = message;
        break;
      }
    }
    if (host == null) return;
    host.taskTrace = trace;
    notifyListeners();
  }

  /// Plan çözülünce kalan running/pending adımları deterministik kapatır —
  /// final progress event'i yarışta kaybolsa bile spinner asla takılı kalmaz.
  void finalizeChecklist(ChatMessage message, {bool failed = false}) {
    final trace = message.taskTrace;
    if (trace == null || trace.status != 'running') return;
    message.taskTrace = failed
        ? TaskTraceBlock(
            stableBlockId: trace.stableBlockId,
            taskId: trace.taskId,
            status: 'failed',
            title: trace.title,
            steps: trace.steps,
          )
        : trace.finalized();
  }
}

extension<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
