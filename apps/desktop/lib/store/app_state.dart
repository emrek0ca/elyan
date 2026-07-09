import 'package:flutter/foundation.dart';

import '../backend/elyan_backend.dart';
import '../bridge/runtime_supervisor.dart';
import '../models/chat_models.dart';
import 'chat_store.dart';

/// Uygulama durumu — macOS `AppState.swift` karşılığı: backend oturumu,
/// Python runtime supervisor ve ChatStore'u birbirine bağlar.
class AppState extends ChangeNotifier {
  final ElyanBackend backend = ElyanBackend();
  final PythonRuntimeSupervisor supervisor = PythonRuntimeSupervisor();
  late final ChatStore chat = ChatStore(supervisor);

  bool bootstrapped = false;

  AppState() {
    supervisor.addListener(notifyListeners);
    supervisor.onAuthRefreshNeeded = _handleAuthRefreshNeeded;
  }

  bool get isSignedIn => backend.isSignedIn;

  /// Açılış: kalıcı oturumu geri yükle, motoru başlat, auth'u senkronla.
  Future<void> bootstrap() async {
    final restored = await backend.restoreSession();
    await supervisor.start(initialSession: restored);
    bootstrapped = true;
    notifyListeners();
  }

  Future<void> signIn({required String email, required String password}) async {
    final session = await backend.login(email: email, password: password);
    await supervisor.syncAuthSession(session);
    notifyListeners();
  }

  Future<void> registerAccount({
    required String displayName,
    required String email,
    required String password,
  }) async {
    final session = await backend.register(
        displayName: displayName, email: email, password: password);
    await supervisor.syncAuthSession(session);
    notifyListeners();
  }

  Future<void> signOut() async {
    chat.reset();
    await backend.logout();
    await supervisor.syncAuthSession(null);
    notifyListeners();
  }

  Future<void> _handleAuthRefreshNeeded() async {
    final refreshed = await backend.refreshSession();
    if (refreshed) {
      await supervisor.syncAuthSession(backend.session);
    }
    notifyListeners();
  }

  Future<List<ElyanSessionSummary>> localSessions() =>
      supervisor.localConversations();

  @override
  void dispose() {
    supervisor.removeListener(notifyListeners);
    supervisor.dispose();
    super.dispose();
  }
}
