import 'package:flutter/material.dart';

import '../store/app_state.dart';
import '../theme/elyan_theme.dart';

/// Giriş ekranı — macOS `LoginView.swift`'in krem tasarım dilindeki karşılığı
/// (bu dilimde e-posta/şifre + kayıt; Google OAuth sonraki dilim).
class LoginView extends StatefulWidget {
  final AppState appState;
  const LoginView({super.key, required this.appState});

  @override
  State<LoginView> createState() => _LoginViewState();
}

class _LoginViewState extends State<LoginView> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _displayName = TextEditingController();
  bool _isRegistering = false;
  bool _isBusy = false;
  String _error = '';

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty || password.isEmpty) return;
    setState(() {
      _isBusy = true;
      _error = '';
    });
    try {
      if (_isRegistering) {
        await widget.appState.registerAccount(
          displayName: _displayName.text.trim(),
          email: email,
          password: password,
        );
      } else {
        await widget.appState.signIn(email: email, password: password);
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _isBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Scaffold(
      backgroundColor: ElyanTheme.canvas(brightness),
      body: Center(
        child: Container(
          width: 360,
          padding: const EdgeInsets.all(28),
          decoration: BoxDecoration(
            color: ElyanTheme.surface(brightness),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: ElyanTheme.hairline(brightness)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Image.asset(
                'assets/logo.png',
                width: 52,
                height: 52,
                errorBuilder: (_, _, _) => const Icon(Icons.auto_awesome,
                    size: 52, color: ElyanTheme.accent),
              ),
              const SizedBox(height: 14),
              const Text(
                'Elyan',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 4),
              Text(
                _isRegistering ? 'Hesap oluştur' : 'Tekrar hoş geldin',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 14,
                  color: ElyanTheme.secondaryText(brightness),
                ),
              ),
              const SizedBox(height: 22),
              if (_isRegistering) ...[
                _field(_displayName, hint: 'Ad Soyad', brightness: brightness),
                const SizedBox(height: 10),
              ],
              _field(_email,
                  hint: 'E-posta',
                  brightness: brightness,
                  keyboardType: TextInputType.emailAddress),
              const SizedBox(height: 10),
              _field(_password,
                  hint: 'Şifre',
                  brightness: brightness,
                  obscure: true,
                  onSubmitted: (_) => _submit()),
              if (_error.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(
                  _error,
                  style: const TextStyle(fontSize: 12, color: Colors.orange),
                ),
              ],
              const SizedBox(height: 18),
              FilledButton(
                onPressed: _isBusy ? null : _submit,
                style: FilledButton.styleFrom(
                  backgroundColor: ElyanTheme.accent,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(22),
                  ),
                ),
                child: _isBusy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      )
                    : Text(
                        _isRegistering ? 'Kayıt ol' : 'Giriş yap',
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600),
                      ),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: _isBusy
                    ? null
                    : () => setState(() => _isRegistering = !_isRegistering),
                child: Text(
                  _isRegistering
                      ? 'Zaten hesabın var mı? Giriş yap'
                      : 'Hesabın yok mu? Kayıt ol',
                  style: TextStyle(
                    fontSize: 12,
                    color: ElyanTheme.secondaryText(brightness),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field(
    TextEditingController controller, {
    required String hint,
    required Brightness brightness,
    bool obscure = false,
    TextInputType? keyboardType,
    ValueChanged<String>? onSubmitted,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: ElyanTheme.composerField(brightness),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ElyanTheme.hairline(brightness)),
      ),
      child: TextField(
        controller: controller,
        obscureText: obscure,
        keyboardType: keyboardType,
        onSubmitted: onSubmitted,
        style: const TextStyle(fontSize: 14),
        decoration: InputDecoration(
          hintText: hint,
          isDense: true,
          border: InputBorder.none,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        ),
      ),
    );
  }
}
