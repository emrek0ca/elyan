import 'package:flutter/material.dart';

/// Elyan tasarım dili — macOS SwiftUI `ElyanTheme` ile BİREBİR aynı değerler
/// (apps/macos/ElyanMac/ChatView.swift). Sıcak krem zemin, asistan cevabı
/// balonsuz doğrudan zeminde, kullanıcı mesajı yumuşak krem balonda, hap
/// biçimli composer. Karanlık modda koyu nötr tonlara düşer.
///
/// Swift kaynak değerleri (calibratedRed 0-1) → 8-bit RGB:
///   canvas        açık (242,238,229) / koyu (27,27,25)
///   userBubble    açık (229,223,211) / koyu (46,46,43)
///   composerField açık (251,249,244) / koyu (37,37,35)
///   surface       açık (248,245,239) / koyu (40,40,38)
///   hairline      primary %8 opaklık
class ElyanTheme {
  ElyanTheme._();

  static const Color canvasLight = Color(0xFFF2EEE5);
  static const Color canvasDark = Color(0xFF1B1B19);

  static const Color userBubbleLight = Color(0xFFE5DFD3);
  static const Color userBubbleDark = Color(0xFF2E2E2B);

  static const Color composerFieldLight = Color(0xFFFBF9F4);
  static const Color composerFieldDark = Color(0xFF252523);

  static const Color surfaceLight = Color(0xFFF8F5EF);
  static const Color surfaceDark = Color(0xFF282826);

  /// macOS accentColor karşılığı — sistem mavisi.
  static const Color accent = Color(0xFF007AFF);

  static Color canvas(Brightness b) =>
      b == Brightness.dark ? canvasDark : canvasLight;
  static Color userBubble(Brightness b) =>
      b == Brightness.dark ? userBubbleDark : userBubbleLight;
  static Color composerField(Brightness b) =>
      b == Brightness.dark ? composerFieldDark : composerFieldLight;
  static Color surface(Brightness b) =>
      b == Brightness.dark ? surfaceDark : surfaceLight;
  static Color hairline(Brightness b) =>
      (b == Brightness.dark ? Colors.white : Colors.black).withValues(alpha: 0.08);

  static Color primaryText(Brightness b) =>
      b == Brightness.dark ? const Color(0xFFEDEDEA) : const Color(0xFF1C1C1A);
  static Color secondaryText(Brightness b) =>
      primaryText(b).withValues(alpha: 0.55);
  static Color tertiaryText(Brightness b) =>
      primaryText(b).withValues(alpha: 0.33);

  /// Sidebar zemini — macOS `.sidebar` list stilinin krem karşılığı:
  /// canvas'tan bir tık farklı, ayrıştırıcı hairline ile.
  static Color sidebar(Brightness b) =>
      b == Brightness.dark ? const Color(0xFF212120) : const Color(0xFFEDE8DC);

  static ThemeData themeData(Brightness brightness) {
    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      fontFamily: _platformFontFamily,
      colorScheme: ColorScheme.fromSeed(
        seedColor: accent,
        brightness: brightness,
        surface: canvas(brightness),
      ),
      scaffoldBackgroundColor: canvas(brightness),
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      hoverColor: primaryText(brightness).withValues(alpha: 0.04),
    );
    return base.copyWith(
      textTheme: base.textTheme.apply(
        bodyColor: primaryText(brightness),
        displayColor: primaryText(brightness),
      ),
      textSelectionTheme: TextSelectionThemeData(
        selectionColor: accent.withValues(alpha: 0.25),
        cursorColor: accent,
      ),
    );
  }

  /// İşletim sistemi arayüz fontu — macOS SF Pro'nun her platformdaki dengi
  /// (Windows: Segoe UI, Linux: dağıtım varsayılanı) → görünüm platform-doğal
  /// ama ölçüler/aralıklar birebir aynı kalır.
  static String? get _platformFontFamily => null;
}
