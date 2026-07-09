import 'package:flutter/material.dart';

import '../models/chat_models.dart';
import '../store/chat_store.dart';
import '../theme/elyan_theme.dart';

/// Sohbet yüzeyi — macOS `ChatView.swift`'in birebir portu.
/// Asistan cevabı balonsuz doğrudan krem zeminde, kullanıcı mesajı yumuşak
/// krem balonda (radius 18), hap biçimli composer (radius 22).
class ChatView extends StatefulWidget {
  final ChatStore chat;
  const ChatView({super.key, required this.chat});

  @override
  State<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends State<ChatView> {
  final TextEditingController _draft = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final FocusNode _focus = FocusNode();
  static const double fontSize = 14;

  @override
  void initState() {
    super.initState();
    widget.chat.addListener(_onChatChanged);
  }

  @override
  void didUpdateWidget(covariant ChatView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.chat != widget.chat) {
      oldWidget.chat.removeListener(_onChatChanged);
      widget.chat.addListener(_onChatChanged);
    }
  }

  @override
  void dispose() {
    widget.chat.removeListener(_onChatChanged);
    _draft.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onChatChanged() {
    setState(() {});
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 150),
        curve: Curves.easeOut,
      );
    });
  }

  bool get _canSend =>
      !widget.chat.isStreaming && _draft.text.trim().isNotEmpty;

  void _send() {
    final text = _draft.text;
    if (text.trim().isEmpty) return;
    _draft.clear();
    widget.chat.send(text);
    _focus.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Container(
      color: ElyanTheme.canvas(brightness),
      child: Column(
        children: [
          Expanded(child: _messageScrollArea(brightness)),
          _inputArea(brightness),
        ],
      ),
    );
  }

  Widget _messageScrollArea(Brightness brightness) {
    final chat = widget.chat;
    final children = <Widget>[];

    if (chat.messages.isEmpty) {
      children.add(_emptyState(brightness));
    }

    for (var i = 0; i < chat.messages.length; i++) {
      final message = chat.messages[i];
      final isTail = chat.isStreaming && i == chat.messages.length - 1;
      children.add(_ChatBubble(
        message: message,
        isStreamingTail: isTail,
        fontSize: fontSize,
        onPlanDecision: (id, approved) => chat.confirmPlan(id, approved),
        onGrantPermission: (id) => chat.grantPermission(id),
        onOpenSystemPermission: (id) => chat.openSystemPermission(id),
      ));
    }

    if (chat.lastError.isNotEmpty) {
      children.add(Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Row(
          children: [
            const Icon(Icons.warning_rounded, size: 16, color: Colors.orange),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                chat.lastError,
                style: TextStyle(
                  fontSize: 12,
                  color: ElyanTheme.secondaryText(brightness),
                ),
              ),
            ),
          ],
        ),
      ));
    }

    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(20),
      children: [
        for (var i = 0; i < children.length; i++) ...[
          if (i > 0) const SizedBox(height: 14),
          children[i],
        ],
      ],
    );
  }

  Widget _emptyState(Brightness brightness) {
    return Padding(
      padding: const EdgeInsets.only(top: 60, bottom: 12),
      child: Column(
        children: [
          Opacity(
            opacity: 0.65,
            child: Image.asset(
              'assets/logo.png',
              width: 52,
              height: 52,
              errorBuilder: (_, _, _) => Icon(Icons.auto_awesome,
                  size: 52, color: ElyanTheme.secondaryText(brightness)),
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            'Elyan',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 6),
          Text(
            'Bir şey yaz, beraber çalışalım.',
            style: TextStyle(
              fontSize: 15,
              color: ElyanTheme.secondaryText(brightness),
            ),
          ),
        ],
      ),
    );
  }

  Widget _inputArea(Brightness brightness) {
    return Container(
      color: ElyanTheme.canvas(brightness),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: ElyanTheme.composerField(brightness),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: ElyanTheme.hairline(brightness)),
              ),
              child: TextField(
                controller: _draft,
                focusNode: _focus,
                minLines: 1,
                maxLines: 8,
                style: const TextStyle(fontSize: fontSize),
                onChanged: (_) => setState(() {}),
                onSubmitted: (_) => _send(),
                textInputAction: TextInputAction.send,
                decoration: const InputDecoration(
                  hintText: 'Bir şey sor…',
                  isDense: true,
                  border: InputBorder.none,
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 16, vertical: 11),
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          IconButton(
            onPressed: _canSend ? _send : null,
            padding: EdgeInsets.zero,
            icon: Icon(
              widget.chat.isStreaming
                  ? Icons.pending_rounded
                  : Icons.arrow_circle_up_rounded,
              size: 30,
              color: _canSend
                  ? ElyanTheme.accent
                  : ElyanTheme.secondaryText(brightness)
                      .withValues(alpha: 0.4),
            ),
          ),
        ],
      ),
    );
  }
}

// MARK: - ChatBubble

class _ChatBubble extends StatelessWidget {
  final ChatMessage message;
  final bool isStreamingTail;
  final double fontSize;
  final void Function(String messageId, bool approved) onPlanDecision;
  final void Function(String messageId) onGrantPermission;
  final void Function(String messageId) onOpenSystemPermission;

  const _ChatBubble({
    required this.message,
    required this.isStreamingTail,
    required this.fontSize,
    required this.onPlanDecision,
    required this.onGrantPermission,
    required this.onOpenSystemPermission,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final isUser = message.role == ChatRole.user;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (isUser) const SizedBox(width: 40),
        Expanded(
          child: Column(
            crossAxisAlignment:
                isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Text(
                  isUser ? 'Sen' : 'Elyan',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: ElyanTheme.secondaryText(brightness),
                  ),
                ),
              ),
              const SizedBox(height: 5),
              _contentView(brightness),
              if (message.taskTrace != null) ...[
                const SizedBox(height: 8),
                _TaskTraceChecklist(
                    trace: message.taskTrace!, fontSize: fontSize),
              ],
              if (message.plan != null) ...[
                const SizedBox(height: 8),
                _PlanCard(
                  plan: message.plan!,
                  fontSize: fontSize,
                  onApprove: () => onPlanDecision(message.id, true),
                  onCancel: () => onPlanDecision(message.id, false),
                ),
              ],
              if (message.permission != null) ...[
                const SizedBox(height: 8),
                _PermissionCard(
                  permission: message.permission!,
                  fontSize: fontSize,
                  onGrant: () => onGrantPermission(message.id),
                  onOpenSettings: () => onOpenSystemPermission(message.id),
                ),
              ],
            ],
          ),
        ),
        if (!isUser) const SizedBox(width: 40),
      ],
    );
  }

  Widget _contentView(Brightness brightness) {
    if (isStreamingTail && message.text.isEmpty && message.taskTrace == null) {
      // Düşünme göstergesi
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: ElyanTheme.surface(brightness),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 8),
            Text(
              'Düşünüyor…',
              style: TextStyle(
                fontSize: fontSize,
                color: ElyanTheme.secondaryText(brightness),
              ),
            ),
          ],
        ),
      );
    }
    if (message.role == ChatRole.user) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
        decoration: BoxDecoration(
          color: ElyanTheme.userBubble(brightness),
          borderRadius: BorderRadius.circular(18),
        ),
        child: SelectableText(
          message.text,
          style: TextStyle(fontSize: fontSize),
        ),
      );
    }
    if (message.text.isEmpty) return const SizedBox.shrink();
    // Asistan: balonsuz, doğrudan zeminde.
    return SelectableText(
      message.text,
      style: TextStyle(fontSize: fontSize, height: 1.4),
    );
  }
}

// MARK: - Canlı checklist (task_trace)

class _TaskTraceChecklist extends StatelessWidget {
  final TaskTraceBlock trace;
  final double fontSize;
  const _TaskTraceChecklist({required this.trace, required this.fontSize});

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Container(
      constraints: const BoxConstraints(maxWidth: 420),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ElyanTheme.surface(brightness),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ElyanTheme.hairline(brightness)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                trace.status == 'completed'
                    ? Icons.check_circle_rounded
                    : trace.status == 'failed'
                        ? Icons.error_rounded
                        : Icons.timelapse_rounded,
                size: 15,
                color: trace.status == 'failed'
                    ? Colors.orange
                    : trace.status == 'completed'
                        ? Colors.green
                        : ElyanTheme.secondaryText(brightness),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  trace.title,
                  style: TextStyle(
                    fontSize: fontSize - 1,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          for (final step in trace.steps) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _stepIcon(step.status, brightness),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      step.label,
                      style: TextStyle(
                        fontSize: fontSize - 1,
                        color: step.status == 'pending'
                            ? ElyanTheme.secondaryText(brightness)
                            : ElyanTheme.primaryText(brightness),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _stepIcon(String status, Brightness brightness) {
    switch (status) {
      case 'completed':
        return const Icon(Icons.check_circle_rounded,
            size: 15, color: Colors.green);
      case 'failed':
        return const Icon(Icons.cancel_rounded,
            size: 15, color: Colors.orange);
      case 'running':
        return const SizedBox(
          width: 15,
          height: 15,
          child: CircularProgressIndicator(strokeWidth: 2),
        );
      default:
        return Icon(Icons.circle_outlined,
            size: 15, color: ElyanTheme.tertiaryText(brightness));
    }
  }
}

// MARK: - Plan Card

class _PlanCard extends StatelessWidget {
  final PendingPlan plan;
  final double fontSize;
  final VoidCallback onApprove;
  final VoidCallback onCancel;

  const _PlanCard({
    required this.plan,
    required this.fontSize,
    required this.onApprove,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Container(
      constraints: const BoxConstraints(maxWidth: 420),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ElyanTheme.surface(brightness),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ElyanTheme.hairline(brightness)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.checklist_rounded,
                  size: 16, color: ElyanTheme.secondaryText(brightness)),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'Onay bekleyen plan',
                  style: TextStyle(
                    fontSize: fontSize - 1,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (plan.isConfirming)
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          if (plan.summary.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              plan.summary,
              style: TextStyle(
                fontSize: fontSize - 1,
                color: ElyanTheme.secondaryText(brightness),
              ),
            ),
          ],
          if (plan.steps.isNotEmpty) ...[
            const SizedBox(height: 10),
            for (var i = 0; i < plan.steps.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 18,
                      height: 18,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: ElyanTheme.secondaryText(brightness)
                            .withValues(alpha: 0.15),
                        shape: BoxShape.circle,
                      ),
                      child: Text(
                        '${i + 1}',
                        style: TextStyle(
                          fontSize: fontSize - 3,
                          fontWeight: FontWeight.bold,
                          color: ElyanTheme.secondaryText(brightness),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        plan.steps[i].description,
                        style: TextStyle(fontSize: fontSize - 1),
                      ),
                    ),
                  ],
                ),
              ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  onPressed: plan.isConfirming ? null : onApprove,
                  style: FilledButton.styleFrom(
                    backgroundColor: ElyanTheme.accent,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                  child: Text(
                    'Onayla',
                    style: TextStyle(
                      fontSize: fontSize - 1,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton(
                  onPressed: plan.isConfirming ? null : onCancel,
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                  child: Text('İptal',
                      style: TextStyle(fontSize: fontSize - 1)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// MARK: - Permission Card

class _PermissionCard extends StatelessWidget {
  final PermissionRequest permission;
  final double fontSize;
  final VoidCallback onGrant;
  final VoidCallback onOpenSettings;

  const _PermissionCard({
    required this.permission,
    required this.fontSize,
    required this.onGrant,
    required this.onOpenSettings,
  });

  bool get _needsSystem =>
      permission.systemPermissionRequired ||
      permission.systemPermissionKey.isNotEmpty;
  bool get _canGrantInApp => permission.permissionKey.isNotEmpty;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Container(
      constraints: const BoxConstraints(maxWidth: 420),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ElyanTheme.surface(brightness),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.shield_outlined,
                  size: 16, color: Colors.orange),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'İzin gerekiyor',
                  style: TextStyle(
                    fontSize: fontSize - 1,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (permission.isGranting)
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            permission.reason,
            style: TextStyle(
              fontSize: fontSize - 1,
              color: ElyanTheme.secondaryText(brightness),
            ),
          ),
          const SizedBox(height: 10),
          if (_canGrantInApp)
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: permission.isGranting ? null : onGrant,
                style: FilledButton.styleFrom(
                  backgroundColor: ElyanTheme.accent,
                  padding: const EdgeInsets.symmetric(vertical: 8),
                ),
                child: Text(
                  'İzin ver',
                  style: TextStyle(
                    fontSize: fontSize - 1,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            )
          else if (_needsSystem)
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: permission.isGranting ? null : onOpenSettings,
                style: FilledButton.styleFrom(
                  backgroundColor: ElyanTheme.accent,
                  padding: const EdgeInsets.symmetric(vertical: 8),
                ),
                child: Text(
                  'Sistem ayarlarını aç',
                  style: TextStyle(
                    fontSize: fontSize - 1,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
