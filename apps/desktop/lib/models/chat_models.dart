/// Sohbet modelleri — macOS `ChatStore.swift` içindeki ChatMessage/PlanStep/
/// PendingPlan/PermissionRequest modellerinin Dart karşılığı. Blok modeli
/// (`ChatBlock.swift`) kademeli port ediliyor: bu dilimde text + task_trace
/// (canlı checklist) tam, diğer türler generic karta düşer.
library;

enum ChatRole { user, assistant }

class PlanStep {
  final String description;
  final String capability;
  const PlanStep({required this.description, required this.capability});
}

class PendingPlan {
  final String pendingPlanId;
  final String conversationId;
  final String summary;
  final List<PlanStep> steps;
  bool isConfirming;

  PendingPlan({
    required this.pendingPlanId,
    required this.conversationId,
    required this.summary,
    required this.steps,
    this.isConfirming = false,
  });

  static PendingPlan? parse(Map<String, dynamic> map) {
    if (map['needsConfirmation'] != true) return null;
    final pendingPlanId = (map['pendingPlanId'] as String?) ?? '';
    if (pendingPlanId.isEmpty) return null;
    final preview = map['planPreview'] is Map<String, dynamic>
        ? map['planPreview'] as Map<String, dynamic>
        : <String, dynamic>{};
    final rawSteps = preview['steps'] is List ? preview['steps'] as List : [];
    return PendingPlan(
      pendingPlanId: pendingPlanId,
      conversationId: (map['conversationId'] as String?) ?? '',
      summary: (preview['summary'] as String?) ??
          (map['assistantMessage'] as String?) ??
          'Plan onayı bekleniyor.',
      steps: [
        for (final step in rawSteps)
          if (step is Map)
            PlanStep(
              description: (step['description'] as String?) ??
                  (step['capability'] as String?) ??
                  'Adım',
              capability: (step['capability'] as String?) ?? '',
            ),
      ],
    );
  }
}

class PermissionRequest {
  final String reason;
  final String permissionKey;
  final bool canGrantPersistently;
  final String systemPermissionKey;
  final bool systemPermissionRequired;
  final String originalText;
  bool isGranting;

  PermissionRequest({
    required this.reason,
    required this.permissionKey,
    required this.canGrantPersistently,
    required this.systemPermissionKey,
    required this.systemPermissionRequired,
    required this.originalText,
    this.isGranting = false,
  });

  static PermissionRequest? parse(
      Map<String, dynamic> map, String originalText) {
    if (map['permissionNeeded'] != true) return null;
    final permissionKey = (map['permissionKey'] as String?) ?? '';
    final systemKey = (map['systemPermissionKey'] as String?) ?? '';
    final systemRequired = map['systemPermissionRequired'] == true;
    if (permissionKey.isEmpty && systemKey.isEmpty && !systemRequired) {
      return null;
    }
    return PermissionRequest(
      reason: (map['permissionReason'] as String?) ??
          (map['assistantMessage'] as String?) ??
          'Bu işlem için izin gerekiyor.',
      permissionKey: permissionKey,
      canGrantPersistently: map['canGrantPersistently'] == true,
      systemPermissionKey: systemKey,
      systemPermissionRequired: systemRequired,
      originalText: originalText,
    );
  }
}

/// Canlı checklist adımı (task_trace bloğu step'i).
class TaskTraceStep {
  final String id;
  final String label;
  final String status; // pending | running | completed | failed
  final String detail;
  const TaskTraceStep({
    required this.id,
    required this.label,
    required this.status,
    required this.detail,
  });
}

class TaskTraceBlock {
  final String stableBlockId;
  final String taskId;
  final String status; // running | completed | failed
  final String title;
  final List<TaskTraceStep> steps;

  const TaskTraceBlock({
    required this.stableBlockId,
    required this.taskId,
    required this.status,
    required this.title,
    required this.steps,
  });

  static TaskTraceBlock? parse(Map<String, dynamic> map) {
    if ((map['type'] as String?) != 'task_trace') return null;
    final rawSteps = map['steps'] is List ? map['steps'] as List : [];
    return TaskTraceBlock(
      stableBlockId: (map['stableBlockId'] as String?) ?? '',
      taskId: (map['taskId'] as String?) ?? '',
      status: (map['status'] as String?) ?? 'running',
      title: (map['title'] as String?) ?? 'Görev yürütülüyor',
      steps: [
        for (final step in rawSteps)
          if (step is Map)
            TaskTraceStep(
              id: (step['id'] as String?) ?? '',
              label: (step['label'] as String?) ?? '',
              status: (step['status'] as String?) ?? 'pending',
              detail: (step['detail'] as String?) ?? '',
            ),
      ],
    );
  }

  TaskTraceBlock finalized() {
    final anyFailed = steps.any((s) => s.status == 'failed');
    return TaskTraceBlock(
      stableBlockId: stableBlockId,
      taskId: taskId,
      status: anyFailed ? 'failed' : 'completed',
      title: title,
      steps: [
        for (final s in steps)
          TaskTraceStep(
            id: s.id,
            label: s.label,
            status: s.status == 'running' || s.status == 'pending'
                ? (anyFailed ? 'failed' : 'completed')
                : s.status,
            detail: s.detail,
          ),
      ],
    );
  }
}

class ChatMessage {
  final String id;
  final ChatRole role;
  String text;
  DateTime timestamp;
  PendingPlan? plan;
  PermissionRequest? permission;
  TaskTraceBlock? taskTrace;

  ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    DateTime? timestamp,
    this.plan,
    this.permission,
    this.taskTrace,
  }) : timestamp = timestamp ?? DateTime.now();
}

class LocalChatReply {
  final String text;
  final bool needsConfirmation;
  final PendingPlan? plan;
  final PermissionRequest? permission;
  const LocalChatReply({
    required this.text,
    required this.needsConfirmation,
    this.plan,
    this.permission,
  });
}

/// Oturum listesi girdisi (sidebar geçmişi) — ElyanSession karşılığı.
class ElyanSessionSummary {
  final String id;
  final String title;
  final String lastMessage;
  final bool isLocal;
  const ElyanSessionSummary({
    required this.id,
    required this.title,
    required this.lastMessage,
    this.isLocal = false,
  });
}

/// Mobilden gönderilmiş görev — runtime yerel görev kutusundaki hali
/// (`runtime.bootstrap` → result.runtime.taskInbox.items; RuntimeModels.swift
/// RuntimeTaskItem karşılığı).
class RuntimeApprovalRequest {
  final String title;
  final String message;
  final String summary;
  final String confirmLabel;
  final String rejectLabel;
  const RuntimeApprovalRequest({
    required this.title,
    required this.message,
    required this.summary,
    required this.confirmLabel,
    required this.rejectLabel,
  });
}

class RuntimeTaskItem {
  final String id;
  final String title;
  final String status;
  final String summary;
  final String error;
  final String updatedAt;
  final RuntimeApprovalRequest? approvalRequest;

  const RuntimeTaskItem({
    required this.id,
    required this.title,
    required this.status,
    required this.summary,
    required this.error,
    required this.updatedAt,
    this.approvalRequest,
  });

  bool get isWaitingApproval =>
      status == 'waiting_approval' && approvalRequest != null;
  bool get isTerminal =>
      const {'completed', 'failed', 'canceled'}.contains(status);

  static RuntimeTaskItem? parse(Map<String, dynamic> map) {
    final id = (map['id'] as String?) ?? '';
    if (id.isEmpty) return null;
    RuntimeApprovalRequest? approval;
    final rawApproval = map['approvalRequest'];
    if (rawApproval is Map) {
      final title = (rawApproval['title'] as String?) ?? '';
      if (title.isNotEmpty) {
        approval = RuntimeApprovalRequest(
          title: title,
          message: (rawApproval['message'] as String?) ?? '',
          summary: (rawApproval['summary'] as String?) ?? '',
          confirmLabel: _nonEmpty(rawApproval['confirmLabel']) ?? 'Onayla',
          rejectLabel: _nonEmpty(rawApproval['rejectLabel']) ?? 'Reddet',
        );
      }
    }
    return RuntimeTaskItem(
      id: id,
      title: _nonEmpty(map['title']) ?? 'Yeni görev',
      status: _nonEmpty(map['status']) ?? 'queued',
      summary: (map['summary'] as String?) ?? '',
      error: (map['error'] as String?) ?? '',
      updatedAt: (map['updatedAt'] as String?) ?? '',
      approvalRequest: approval,
    );
  }

  static String? _nonEmpty(dynamic value) {
    if (value is String && value.isNotEmpty) return value;
    return null;
  }
}

class ElyanAuthSession {
  final String id;
  final String displayName;
  final String email;
  final String accessToken;
  final String refreshToken;
  final bool hasAvatar;
  final int avatarVersion;

  const ElyanAuthSession({
    required this.id,
    required this.displayName,
    required this.email,
    required this.accessToken,
    required this.refreshToken,
    this.hasAvatar = false,
    this.avatarVersion = 0,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'displayName': displayName,
        'email': email,
        'accessToken': accessToken,
        'refreshToken': refreshToken,
        'hasAvatar': hasAvatar,
        'avatarVersion': avatarVersion,
      };

  static ElyanAuthSession fromJson(Map<String, dynamic> json) =>
      ElyanAuthSession(
        id: (json['id'] as String?) ?? '',
        displayName: (json['displayName'] as String?) ?? '',
        email: (json['email'] as String?) ?? '',
        accessToken: (json['accessToken'] as String?) ?? '',
        refreshToken: (json['refreshToken'] as String?) ?? '',
        hasAvatar: json['hasAvatar'] == true,
        avatarVersion: (json['avatarVersion'] as num?)?.toInt() ?? 0,
      );
}
