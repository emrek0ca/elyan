import 'package:flutter/material.dart';

import '../models/chat_models.dart';
import '../store/app_state.dart';
import '../theme/elyan_theme.dart';

/// Mobilden gönderilen görevler — macOS `TaskInboxView.swift` portu.
/// Yürütücü her zaman Python runtime'dır; bu ekran görünürlük + onay
/// (waiting_approval → İncele ve Onayla) içindir.
class TaskInboxView extends StatefulWidget {
  final AppState appState;
  const TaskInboxView({super.key, required this.appState});

  @override
  State<TaskInboxView> createState() => _TaskInboxViewState();
}

class _TaskInboxViewState extends State<TaskInboxView> {
  bool _isRefreshing = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    if (_isRefreshing) return;
    setState(() => _isRefreshing = true);
    await widget.appState.supervisor.refreshTaskInbox();
    if (mounted) setState(() => _isRefreshing = false);
  }

  Future<void> _decide(RuntimeTaskItem task, bool approved) async {
    Navigator.of(context).pop();
    await widget.appState.supervisor
        .approveTask(taskId: task.id, approved: approved);
    if (mounted) setState(() {});
  }

  void _showApprovalSheet(RuntimeTaskItem task) {
    final approval = task.approvalRequest;
    if (approval == null) return;
    final brightness = Theme.of(context).brightness;
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: ElyanTheme.surface(brightness),
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        title: Text(approval.title,
            style:
                const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (approval.message.isNotEmpty)
              Text(approval.message, style: const TextStyle(fontSize: 13)),
            if (approval.summary.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                approval.summary,
                style: TextStyle(
                  fontSize: 12,
                  color: ElyanTheme.secondaryText(brightness),
                ),
              ),
            ],
          ],
        ),
        actions: [
          OutlinedButton(
            onPressed: () => _decide(task, false),
            child: Text(approval.rejectLabel),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: ElyanTheme.accent),
            onPressed: () => _decide(task, true),
            child: Text(approval.confirmLabel),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final tasks = widget.appState.supervisor.taskInbox;
    return Container(
      color: ElyanTheme.canvas(brightness),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Mobilden görevler',
                        style: TextStyle(
                            fontSize: 17, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'Telefondan gönderilen işler burada listelenir.',
                        style: TextStyle(
                          fontSize: 12,
                          color: ElyanTheme.secondaryText(brightness),
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  onPressed: _refresh,
                  icon: _isRefreshing
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(Icons.refresh,
                          size: 18,
                          color: ElyanTheme.secondaryText(brightness)),
                ),
              ],
            ),
          ),
          Container(height: 1, color: ElyanTheme.hairline(brightness)),
          Expanded(
            child: tasks.isEmpty
                ? _emptyState(brightness)
                : ListView(
                    padding: const EdgeInsets.all(20),
                    children: [
                      for (final task in tasks) ...[
                        _TaskRow(
                          task: task,
                          brightness: brightness,
                          onReview: () => _showApprovalSheet(task),
                        ),
                        const SizedBox(height: 12),
                      ],
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _emptyState(Brightness brightness) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.inbox_outlined,
              size: 34, color: ElyanTheme.tertiaryText(brightness)),
          const SizedBox(height: 10),
          const Text('Henüz görev yok',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          SizedBox(
            width: 320,
            child: Text(
              'Mobilde bir görev gönderdiğinde burada görürsün.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 13,
                color: ElyanTheme.secondaryText(brightness),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TaskRow extends StatelessWidget {
  final RuntimeTaskItem task;
  final Brightness brightness;
  final VoidCallback onReview;

  const _TaskRow({
    required this.task,
    required this.brightness,
    required this.onReview,
  });

  Color get _statusColor {
    switch (task.status) {
      case 'completed':
        return Colors.green;
      case 'failed':
      case 'canceled':
        return Colors.red;
      case 'waiting_approval':
        return Colors.orange;
      default:
        return ElyanTheme.accent;
    }
  }

  String get _statusLabel {
    switch (task.status) {
      case 'queued':
        return 'Sırada';
      case 'running':
      case 'planning':
        return 'Çalışıyor';
      case 'waiting_approval':
        return 'Onay bekliyor';
      case 'completed':
        return 'Tamamlandı';
      case 'failed':
        return 'Başarısız';
      case 'canceled':
        return 'İptal edildi';
      default:
        return task.status;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ElyanTheme.surface(brightness),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: ElyanTheme.hairline(brightness)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: _statusColor.withValues(alpha: 0.2),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(task.title,
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600)),
                    if (task.summary.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        task.summary,
                        style: TextStyle(
                          fontSize: 12,
                          color: ElyanTheme.secondaryText(brightness),
                        ),
                      ),
                    ],
                    const SizedBox(height: 4),
                    Text(
                      _statusLabel,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: _statusColor,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (task.error.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(task.error,
                style: const TextStyle(fontSize: 11, color: Colors.red)),
          ],
          if (task.isWaitingApproval) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: ElyanTheme.accent),
                onPressed: onReview,
                child: const Text('İncele ve Onayla',
                    style: TextStyle(fontSize: 12)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
