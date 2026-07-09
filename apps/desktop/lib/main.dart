import 'package:flutter/material.dart';

import 'store/app_state.dart';
import 'theme/elyan_theme.dart';
import 'ui/app_shell.dart';
import 'ui/login_view.dart';

/// Elyan Desktop — Windows/Linux arayüzü (Flutter).
///
/// Mimari macOS Swift uygulamasıyla birebir: arayüz işletim sistemine göre
/// değişir (macOS: SwiftUI, Windows/Linux: bu uygulama), motor HER YERDE aynı
/// Python runtime'dır (`runtime/bridge.py`, stdin/stdout JSON). Tek beyin
/// VPS'teki server_brain'dir — yerel LLM yok.
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ElyanDesktopApp());
}

class ElyanDesktopApp extends StatefulWidget {
  const ElyanDesktopApp({super.key});

  @override
  State<ElyanDesktopApp> createState() => _ElyanDesktopAppState();
}

class _ElyanDesktopAppState extends State<ElyanDesktopApp> {
  final AppState appState = AppState();

  @override
  void initState() {
    super.initState();
    appState.addListener(_onStateChanged);
    appState.bootstrap();
  }

  @override
  void dispose() {
    appState.removeListener(_onStateChanged);
    appState.dispose();
    super.dispose();
  }

  void _onStateChanged() => setState(() {});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Elyan',
      debugShowCheckedModeBanner: false,
      theme: ElyanTheme.themeData(Brightness.light),
      darkTheme: ElyanTheme.themeData(Brightness.dark),
      themeMode: ThemeMode.system,
      home: !appState.bootstrapped
          ? const _SplashView()
          : appState.isSignedIn
              ? AppShell(appState: appState)
              : LoginView(appState: appState),
    );
  }
}

class _SplashView extends StatelessWidget {
  const _SplashView();

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Scaffold(
      backgroundColor: ElyanTheme.canvas(brightness),
      body: const Center(
        child: SizedBox(
          width: 22,
          height: 22,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ),
    );
  }
}
