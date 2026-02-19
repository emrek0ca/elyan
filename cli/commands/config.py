"""config.py — Yapılandırma yönetimi CLI"""
import json
import os
import sys
from pathlib import Path
from config.elyan_config import elyan_config

def handle_config(args):
    action = getattr(args, "action", None)

    if not action or action == "show":
        _show(masked=getattr(args, "masked", False))
    elif action == "get":
        _get(getattr(args, "key", None))
    elif action == "set":
        _set(getattr(args, "key", None), getattr(args, "value", None))
    elif action == "unset":
        _unset(getattr(args, "key", None))
    elif action == "validate":
        _validate()
    elif action == "reset":
        _reset()
    elif action == "export":
        _export(getattr(args, "output", None))
    elif action == "import":
        _import(getattr(args, "file", None))
    elif action == "edit":
        _edit()
    else:
        print(f"Bilinmeyen eylem: {action}")
        print("Usage: elyan config [show|get|set|unset|validate|reset|export|import|edit]")


def _show(masked: bool = False):
    data = elyan_config.get_all()
    if masked:
        data = _mask_secrets(data)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _mask_secrets(data: dict) -> dict:
    """API anahtarlarını maskele."""
    SENSITIVE = {"token", "key", "secret", "password", "apikey", "api_key"}
    result = {}
    for k, v in data.items():
        if any(s in k.lower() for s in SENSITIVE):
            result[k] = "***" if v else ""
        elif isinstance(v, dict):
            result[k] = _mask_secrets(v)
        else:
            result[k] = v
    return result


def _get(key: str):
    if not key:
        _show()
        return
    val = elyan_config.get(key)
    print(f"{key} = {json.dumps(val, ensure_ascii=False)}")


def _set(key: str, value: str):
    if not key or value is None:
        print("Hata: anahtar ve değer gereklidir.")
        return
    # Tip tahmini
    v = value
    if isinstance(v, str):
        if v.lower() == "true":
            v = True
        elif v.lower() == "false":
            v = False
        elif v.isdigit():
            v = int(v)
        else:
            try:
                v = json.loads(v)
            except Exception:
                pass
    elyan_config.set(key, v)
    print(f"✅  {key} = {json.dumps(v, ensure_ascii=False)}")


def _unset(key: str):
    if not key:
        print("Hata: anahtar gereklidir.")
        return
    if elyan_config.unset(key):
        print(f"✅  {key} silindi.")
    else:
        print(f"⚠️  Anahtar bulunamadı: {key}")


def _validate():
    print("\n🔍  Yapılandırma Doğrulama\n" + "─" * 35)
    errors = 0

    required = ["models.default.provider"]
    for key in required:
        val = elyan_config.get(key)
        ok = bool(val)
        print(f"  {'✅' if ok else '❌'}  {key}: {val or 'EKSİK'}")
        if not ok:
            errors += 1

    # Kanal kontrolü
    channels = elyan_config.get("channels", [])
    print(f"  ℹ️   Kanal sayısı: {len(channels)}")

    # Güvenlik
    op_mode = elyan_config.get("security.operatorMode", "?")
    print(f"  ℹ️   Operator modu: {op_mode}")

    print()
    if errors == 0:
        print("✅  Yapılandırma geçerli.")
    else:
        print(f"❌  {errors} zorunlu alan eksik.")


def _reset():
    confirm = input("⚠️  Tüm yapılandırma sıfırlanacak. Devam? (evet/hayır): ").strip().lower()
    if confirm == "evet":
        elyan_config.reset()
        print("✅  Yapılandırma varsayılana sıfırlandı.")
    else:
        print("İptal edildi.")


def _export(output_path: str = None):
    data = elyan_config.get_all()
    if not output_path:
        output_path = str(Path.home() / "elyan_config_export.json")
    Path(output_path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"✅  Yapılandırma dışa aktarıldı: {output_path}")


def _import(file_path: str = None):
    if not file_path:
        print("Hata: dosya yolu gereklidir.")
        return
    p = Path(file_path)
    if not p.exists():
        print(f"Dosya bulunamadı: {file_path}")
        return
    try:
        data = json.loads(p.read_text())
        for key, value in data.items():
            elyan_config.set(key, value)
        print(f"✅  {len(data)} anahtar içe aktarıldı.")
    except Exception as e:
        print(f"Hata: {e}")


def _edit():
    editor = os.environ.get("EDITOR", "nano")
    config_path = elyan_config.config_path if hasattr(elyan_config, "config_path") else (
        Path.home() / ".elyan" / "elyan.json"
    )
    os.system(f"{editor} {config_path}")
