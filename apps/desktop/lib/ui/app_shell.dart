import 'package:flutter/material.dart';

import '../models/chat_models.dart';
import '../store/app_state.dart';
import '../theme/elyan_theme.dart';
import 'chat_view.dart';

/// Giriş sonrası ana kabuk — macOS `ContentView.swift` portu: solda oturum
/// geçmişli sidebar (Claude Code stili), altta profil çipi, sağda sohbet.
class AppShell extends StatefulWidget {
  final AppState appState;
  const AppShell({super.key, required this.appState});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  String _selection = 'chat';
  List<ElyanSessionSummary> _sessions = const [];
  bool _sessionsLoaded = false;
  bool _isLoadingSessions = false;

  AppState get appState => widget.appState;

  Future<void> _refreshSessions() async {
    if (_isLoadingSessions) return;
    setState(() => _isLoadingSessions = true);
    final sessions = await appState.localSessions();
    if (!mounted) return;
    setState(() {
      _sessions = sessions;
      _sessionsLoaded = true;
      _isLoadingSessions = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Scaffold(
      body: Row(
        children: [
          _sidebar(brightness),
          Container(width: 1, color: ElyanTheme.hairline(brightness)),
          Expanded(child: ChatView(chat: appState.chat)),
        ],
      ),
    );
  }

  Widget _sidebar(Brightness brightness) {
    return Container(
      width: 230,
      color: ElyanTheme.sidebar(brightness),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Başlık satırı
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 10),
            child: Row(
              children: [
                Image.asset(
                  'assets/logo.png',
                  width: 22,
                  height: 22,
                  errorBuilder: (_, _, _) => const Icon(
                      Icons.auto_awesome,
                      size: 22,
                      color: ElyanTheme.accent),
                ),
                const SizedBox(width: 8),
                const Text(
                  'Elyan',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          _sidebarItem(
            id: 'chat',
            icon: Icons.edit_square,
            label: 'Yeni sohbet',
            brightness: brightness,
            onTap: () {
              setState(() => _selection = 'chat');
              appState.chat.reset();
            },
          ),
          _sidebarItem(
            id: 'taskInbox',
            icon: Icons.move_to_inbox_outlined,
            label: 'Mobilden görevler',
            brightness: brightness,
            onTap: () => setState(() => _selection = 'taskInbox'),
          ),
          _sidebarItem(
            id: 'pairing',
            icon: Icons.phonelink_ring_outlined,
            label: 'Cihaz eşleştir',
            brightness: brightness,
            onTap: () => setState(() => _selection = 'pairing'),
          ),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Text(
              'Geçmiş',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: ElyanTheme.secondaryText(brightness),
              ),
            ),
          ),
          Expanded(child: _historyList(brightness)),
          Container(height: 1, color: ElyanTheme.hairline(brightness)),
          _profileChip(brightness),
        ],
      ),
    );
  }

  Widget _historyList(Brightness brightness) {
    if (!_sessionsLoaded) {
      return Align(
        alignment: Alignment.topLeft,
        child: _sidebarItem(
          id: 'showHistory',
          icon: Icons.history,
          label: 'Geçmişi göster',
          brightness: brightness,
          onTap: _refreshSessions,
        ),
      );
    }
    if (_isLoadingSessions && _sessions.isEmpty) {
      return const Center(
        child: SizedBox(
          width: 16,
          height: 16,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }
    if (_sessions.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'Henüz sohbet yok.',
          style: TextStyle(
            fontSize: 12,
            color: ElyanTheme.secondaryText(brightness),
          ),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      children: [
        for (final session in _sessions)
          _SessionRow(
            session: session,
            selected: _selection == 'session:${session.id}',
            brightness: brightness,
            onTap: () {
              setState(() => _selection = 'session:${session.id}');
              // Yerel konuşma: bridge conversation bağlamına geç.
              appState.chat.reset();
              appState.supervisor.setLocalConversation(session.id);
            },
          ),
      ],
    );
  }

  Widget _sidebarItem({
    required String id,
    required IconData icon,
    required String label,
    required Brightness brightness,
    required VoidCallback onTap,
  }) {
    final selected = _selection == id;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: Material(
        color: selected
            ? ElyanTheme.primaryText(brightness).withValues(alpha: 0.07)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
          borderRadius: BorderRadius.circular(6),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            child: Row(
              children: [
                Icon(icon, size: 16, color: ElyanTheme.accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    label,
                    style: const TextStyle(fontSize: 13),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _profileChip(Brightness brightness) {
    final session = appState.backend.session;
    final displayName = session?.displayName.isNotEmpty == true
        ? session!.displayName
        : 'Kullanıcı';
    final email = session?.email ?? '';
    final initial = (displayName.isNotEmpty ? displayName : 'E')
        .substring(0, 1)
        .toUpperCase();

    return InkWell(
      onTap: () => _showProfileMenu(brightness),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(
          children: [
            CircleAvatar(
              radius: 14,
              backgroundColor: ElyanTheme.accent.withValues(alpha: 0.15),
              child: Text(
                initial,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: ElyanTheme.accent,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    displayName,
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w500),
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (email.isNotEmpty)
                    Text(
                      email,
                      style: TextStyle(
                        fontSize: 11,
                        color: ElyanTheme.secondaryText(brightness),
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                ],
              ),
            ),
            Icon(Icons.more_horiz,
                size: 14, color: ElyanTheme.tertiaryText(brightness)),
          ],
        ),
      ),
    );
  }

  void _showProfileMenu(Brightness brightness) {
    showMenu<String>(
      context: context,
      position: const RelativeRect.fromLTRB(8, double.infinity, 0, 56),
      items: [
        const PopupMenuItem(
          value: 'signOut',
          child: Row(
            children: [
              Icon(Icons.logout, size: 16, color: Colors.red),
              SizedBox(width: 8),
              Text('Oturumu kapat', style: TextStyle(color: Colors.red)),
            ],
          ),
        ),
      ],
    ).then((value) {
      if (value == 'signOut') appState.signOut();
    });
  }
}

class _SessionRow extends StatelessWidget {
  final ElyanSessionSummary session;
  final bool selected;
  final Brightness brightness;
  final VoidCallback onTap;

  const _SessionRow({
    required this.session,
    required this.selected,
    required this.brightness,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final title = session.title.trim().isEmpty ? 'Yeni sohbet' : session.title;
    return Material(
      color: selected
          ? ElyanTheme.primaryText(brightness).withValues(alpha: 0.07)
          : Colors.transparent,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      title,
                      style: const TextStyle(fontSize: 13),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  if (session.isLocal)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: ElyanTheme.secondaryText(brightness)
                            .withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        'Yerel',
                        style: TextStyle(
                          fontSize: 9,
                          fontWeight: FontWeight.w600,
                          color: ElyanTheme.secondaryText(brightness),
                        ),
                      ),
                    ),
                ],
              ),
              if (session.lastMessage.isNotEmpty)
                Text(
                  session.lastMessage,
                  style: TextStyle(
                    fontSize: 11,
                    color: ElyanTheme.secondaryText(brightness),
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
            ],
          ),
        ),
      ),
    );
  }
}
