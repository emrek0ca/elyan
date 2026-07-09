import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elyan_desktop/models/chat_models.dart';
import 'package:elyan_desktop/theme/elyan_theme.dart';

void main() {
  test('tema renkleri macOS ElyanTheme ile birebir', () {
    // apps/macos/ElyanMac/ChatView.swift kaynak değerleri.
    expect(ElyanTheme.canvasLight, const Color(0xFFF2EEE5));
    expect(ElyanTheme.canvasDark, const Color(0xFF1B1B19));
    expect(ElyanTheme.userBubbleLight, const Color(0xFFE5DFD3));
    expect(ElyanTheme.composerFieldLight, const Color(0xFFFBF9F4));
    expect(ElyanTheme.surfaceLight, const Color(0xFFF8F5EF));
  });

  test('PendingPlan.parse bridge sözleşmesini okur', () {
    final plan = PendingPlan.parse({
      'needsConfirmation': true,
      'pendingPlanId': 'plan_1',
      'conversationId': 'conv_1',
      'planPreview': {
        'summary': 'Araştır ve belgele',
        'steps': [
          {'description': 'Web araştırması', 'capability': 'web_research'},
          {'description': 'Belge yaz', 'capability': 'document_write'},
        ],
      },
    });
    expect(plan, isNotNull);
    expect(plan!.pendingPlanId, 'plan_1');
    expect(plan.steps.length, 2);
    expect(plan.steps.first.capability, 'web_research');
  });

  test('task_trace bloğu parse + finalize takılı spinner bırakmaz', () {
    final trace = TaskTraceBlock.parse({
      'type': 'task_trace',
      'stableBlockId': 'tasktrace_x',
      'taskId': 'x',
      'status': 'running',
      'title': 'Görev yürütülüyor',
      'steps': [
        {'id': 's1', 'label': 'Araştır', 'status': 'completed', 'detail': ''},
        {'id': 's2', 'label': 'Belge yaz', 'status': 'running', 'detail': ''},
      ],
    });
    expect(trace, isNotNull);
    final finalized = trace!.finalized();
    expect(finalized.status, 'completed');
    expect(finalized.steps.every((s) => s.status == 'completed'), isTrue);
  });
}
