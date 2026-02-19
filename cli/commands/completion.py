"""completion.py — Shell auto-completion kurulumu"""
import os
import sys
from pathlib import Path

_ZSH_SCRIPT = '''# Elyan CLI — Zsh completion
# ~/.zshrc dosyasına şunu ekleyin:
#   source ~/.elyan/completion.zsh
#
# Veya: elyan completion install --shell zsh

_elyan_completion() {
    local cur prev words
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local commands="doctor health logs status routines config gateway channels skills security models cron memory webhooks agents browser voice message service dashboard onboard update version completion"

    case "$prev" in
        elyan)
            COMPREPLY=($(compgen -W "$commands" -- "$cur"))
            return ;;
        gateway)
            COMPREPLY=($(compgen -W "start stop status restart logs reload health" -- "$cur"))
            return ;;
        routines)
            COMPREPLY=($(compgen -W "list templates add rm enable disable run history" -- "$cur"))
            return ;;
        channels)
            COMPREPLY=($(compgen -W "list status add remove enable disable test login logout info sync" -- "$cur"))
            return ;;
        models)
            COMPREPLY=($(compgen -W "list status test use set-default set-fallback cost ollama add" -- "$cur"))
            return ;;
        cron)
            COMPREPLY=($(compgen -W "list status add rm enable disable run history next" -- "$cur"))
            return ;;
        security)
            COMPREPLY=($(compgen -W "audit status events sandbox" -- "$cur"))
            return ;;
        skills)
            COMPREPLY=($(compgen -W "list info install enable disable update remove search check" -- "$cur"))
            return ;;
        memory)
            COMPREPLY=($(compgen -W "status index search export import clear stats" -- "$cur"))
            return ;;
        webhooks)
            COMPREPLY=($(compgen -W "list add remove test logs" -- "$cur"))
            return ;;
        agents)
            COMPREPLY=($(compgen -W "list status add remove start stop logs" -- "$cur"))
            return ;;
        config)
            COMPREPLY=($(compgen -W "show get set unset validate reset export import edit" -- "$cur"))
            return ;;
        logs)
            COMPREPLY=($(compgen -W "--tail --level --filter" -- "$cur"))
            return ;;
        voice)
            COMPREPLY=($(compgen -W "start stop status test transcribe speak" -- "$cur"))
            return ;;
        browser)
            COMPREPLY=($(compgen -W "snapshot screenshot navigate click type extract scroll close" -- "$cur"))
            return ;;
    esac
}

complete -F _elyan_completion elyan
'''

_ZSH_NATIVE = '''# Elyan CLI — Zsh native completion (_elyan)
if [[ -o interactive ]]; then
  if ! typeset -f compdef >/dev/null 2>&1; then
    autoload -Uz compinit
    compinit -i
  fi
fi

_elyan() {
  local state
  local -a commands

  commands=(
    'doctor:Sistem tanılaması'
    'health:Hızlı sağlık özeti'
    'logs:Gateway logları'
    'status:Genel durum'
    'routines:Rutin otomasyon yönetimi'
    'config:Yapılandırma yönetimi'
    'gateway:Gateway başlat/durdur'
    'channels:Kanal yönetimi'
    'skills:Beceri yönetimi'
    'security:Güvenlik araçları'
    'models:Model yönetimi'
    'cron:Cron işleri'
    'memory:Bellek yönetimi'
    'webhooks:Webhook yönetimi'
    'agents:Agent yönetimi'
    'browser:Tarayıcı otomasyonu'
    'voice:Ses komutları'
    'message:Mesaj gönder'
    'service:Sistem servisi'
    'dashboard:Web paneli aç'
    'onboard:Kurulum sihirbazı'
    'update:Güncelle'
    'version:Sürüm bilgisi'
    'completion:Shell completion kur'
  )

  _arguments -C \
    '1: :->cmd' \
    '*:: :->args'

  case $state in
    cmd) _describe 'elyan komutları' commands ;;
    args)
      case $words[1] in
        gateway) _values 'eylem' start stop status restart logs reload health ;;
        routines) _values 'eylem' list templates add rm enable disable run history ;;
        channels) _values 'eylem' list status add remove enable disable test login logout info sync ;;
        models) _values 'eylem' list status test use set-default set-fallback cost ollama ;;
        cron) _values 'eylem' list status add rm enable disable run history next ;;
        security) _values 'eylem' audit status events sandbox ;;
        skills) _values 'eylem' list info install enable disable update remove search check ;;
        config) _values 'eylem' show get set unset validate reset export import edit ;;
        memory) _values 'eylem' status index search export import clear stats ;;
        webhooks) _values 'eylem' list add remove test logs ;;
        logs) _arguments '*:log filtreleri: ' ;;
      esac
      ;;
  esac
}

if [[ -o interactive ]] && typeset -f compdef >/dev/null 2>&1; then
  compdef _elyan elyan
fi
'''

_FISH_SCRIPT = '''# Elyan CLI — Fish completion
# Kopyala: ~/.config/fish/completions/elyan.fish

set -l elyan_commands doctor health logs status routines config gateway channels skills security models cron memory webhooks agents browser voice message service dashboard onboard update version completion

complete -c elyan -f -n __fish_use_subcommand -a "$elyan_commands"
complete -c elyan -n "__fish_seen_subcommand_from gateway" -a "start stop status restart logs reload health"
complete -c elyan -n "__fish_seen_subcommand_from routines" -a "list templates add rm enable disable run history"
complete -c elyan -n "__fish_seen_subcommand_from channels" -a "list status add remove enable disable test login logout info sync"
complete -c elyan -n "__fish_seen_subcommand_from models" -a "list status test use set-default set-fallback cost ollama"
complete -c elyan -n "__fish_seen_subcommand_from cron" -a "list status add rm enable disable run history next"
complete -c elyan -n "__fish_seen_subcommand_from security" -a "audit status events sandbox"
complete -c elyan -n "__fish_seen_subcommand_from skills" -a "list info install enable disable update remove search check"
complete -c elyan -n "__fish_seen_subcommand_from memory" -a "status index search export import clear stats"
complete -c elyan -n "__fish_seen_subcommand_from config" -a "show get set unset validate reset export import edit"
'''


def handle_completion(args):
    action = getattr(args, "action", "show")
    shell = getattr(args, "shell", _detect_shell())

    if action == "show" or not action:
        _show(shell)
    elif action == "install":
        _install(shell)
    elif action == "uninstall":
        _uninstall(shell)
    else:
        print(f"Bilinmeyen eylem: {action}")


def _detect_shell() -> str:
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return "zsh"
    if "fish" in shell:
        return "fish"
    return "bash"


def _show(shell: str):
    if shell == "zsh":
        print(_ZSH_NATIVE)
    elif shell == "fish":
        print(_FISH_SCRIPT)
    else:
        print(_ZSH_SCRIPT)


def _install(shell: str):
    elyan_dir = Path.home() / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)

    if shell == "zsh":
        dest = elyan_dir / "completion.zsh"
        dest.write_text(_ZSH_NATIVE)
        rc = Path.home() / ".zshrc"
        source_line = f'\n# Elyan completion\n[[ -f {dest} ]] && source {dest}\n'
        existing = rc.read_text() if rc.exists() else ""
        if str(dest) not in existing:
            rc.write_text(existing + source_line)
            print(f"✅  ~/.zshrc güncellendi: {dest}")
        else:
            print(f"ℹ️   Completion zaten ~/.zshrc'de mevcut.")
        print("    Değişiklikleri uygulamak için: source ~/.zshrc")

    elif shell == "fish":
        fish_dir = Path.home() / ".config" / "fish" / "completions"
        fish_dir.mkdir(parents=True, exist_ok=True)
        dest = fish_dir / "elyan.fish"
        dest.write_text(_FISH_SCRIPT)
        print(f"✅  Fish completion yüklendi: {dest}")

    else:  # bash
        dest = elyan_dir / "completion.bash"
        dest.write_text(_ZSH_SCRIPT)
        rc = Path.home() / ".bashrc"
        source_line = f'\n# Elyan completion\n[[ -f {dest} ]] && source {dest}\n'
        existing = rc.read_text() if rc.exists() else ""
        if str(dest) not in existing:
            rc.write_text(existing + source_line)
        print(f"✅  Bash completion yüklendi: {dest}")
        print("    Değişiklikleri uygulamak için: source ~/.bashrc")


def _uninstall(shell: str):
    elyan_dir = Path.home() / ".elyan"
    removed = []
    for fname in ("completion.zsh", "completion.bash"):
        p = elyan_dir / fname
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if shell == "fish":
        p = Path.home() / ".config" / "fish" / "completions" / "elyan.fish"
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if removed:
        print(f"✅  Kaldırıldı: {', '.join(removed)}")
        print("    Shell'i yeniden başlatın.")
    else:
        print("Kurulu completion dosyası bulunamadı.")
