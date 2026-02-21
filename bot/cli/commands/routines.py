"""routines.py — Multi-step automation routines CLI"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from config.elyan_config import elyan_config


def _port(args) -> int:
    p = getattr(args, "port", None)
    if p:
        return int(p)
    return int(elyan_config.get("gateway.port", 18789))


def _api_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, port: int = 18789) -> Dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return {"ok": True, "status": resp.status, "data": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"error": body}
        return {"ok": False, "status": e.code, "data": parsed}
    except Exception as e:
        return {"ok": False, "status": 0, "data": {"error": str(e)}}


def _emit_json(payload: Dict[str, Any]):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_panels(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    items = [x.strip() for x in text.replace("\n", ",").replace(";", ",").split(",")]
    out: list[str] = []
    seen = set()
    for item in items:
        if not item:
            continue
        if not item.startswith("http://") and not item.startswith("https://"):
            if "." in item and " " not in item:
                item = "https://" + item
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _resolve_routine_id(port: int, raw_id: str) -> tuple[str | None, str | None]:
    rid = str(raw_id or "").strip()
    if not rid:
        return None, "id gerekli."

    resp = _api_request("GET", "/api/routines", port=port)
    if not resp["ok"]:
        return None, f"Routines API hatası: {resp['data'].get('error', 'unknown')}"

    routines = resp["data"].get("routines", [])
    ids = [str(x.get("id", "")).strip() for x in routines if isinstance(x, dict)]
    ids = [x for x in ids if x]

    if rid in ids:
        return rid, None

    matches = [x for x in ids if x.startswith(rid)]
    if not matches:
        return None, "routine not found"
    if len(matches) > 1:
        preview = ", ".join(matches[:5])
        more = "" if len(matches) <= 5 else f", +{len(matches) - 5} more"
        return None, f"id belirsiz ({len(matches)} eşleşme): {preview}{more}"
    return matches[0], None


def run(args):
    action = getattr(args, "action", None)
    as_json = bool(getattr(args, "json", False))
    if not action:
        print("Usage: elyan routines [list|templates|suggest|add|rm|enable|disable|run|history]")
        return
    port = _port(args)

    if action == "list":
        r = _api_request("GET", "/api/routines", port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Routines API hatası: {r['data'].get('error', 'unknown')}")
            return
        if as_json:
            _emit_json({"ok": True, "action": action, "status": r["status"], **r["data"]})
            return
        data = r["data"]
        routines = data.get("routines", [])
        summary = data.get("summary", {})
        print(f"Routines: {summary.get('total', len(routines))} (enabled={summary.get('enabled', 0)})")
        if not routines:
            print("Kayıtlı rutin yok.")
            return
        print(f"{'ID':<16} {'DURUM':<8} {'CRON':<14} {'Kanal':<10} {'Ad'}")
        print("─" * 80)
        for x in routines:
            st = "aktif" if x.get("enabled", True) else "pasif"
            print(f"{x.get('id','?'):<16} {st:<8} {x.get('expression','?'):<14} {x.get('report_channel','-'):<10} {x.get('name','')}")
    elif action == "templates":
        r = _api_request("GET", "/api/routines/templates", port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Template API hatası: {r['data'].get('error', 'unknown')}")
            return
        if as_json:
            _emit_json({"ok": True, "action": action, "status": r["status"], **r["data"]})
            return
        templates = r["data"].get("templates", [])
        if not templates:
            print("Template bulunamadı.")
            return
        print(f"{'TEMPLATE':<22} {'KATEGORİ':<14} {'ADIM':<6} {'Ad'}")
        print("─" * 90)
        for t in templates:
            steps = t.get("steps", []) if isinstance(t.get("steps"), list) else []
            print(f"{t.get('id','?'):<22} {t.get('category','-'):<14} {len(steps):<6} {t.get('name','')}")
    elif action == "suggest":
        text = str(getattr(args, "text", "") or "").strip()
        if not text:
            print("❌  --text zorunlu.")
            print("Örn: elyan routines suggest --text \"Her gün saat 09:00 panelleri kontrol et, excel oluştur ve telegram gönder\"")
            return
        r = _api_request("POST", "/api/routines/suggest", payload={"text": text}, port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Suggest API hatası: {r['data'].get('error', 'unknown')}")
            return
        suggestion = r["data"].get("suggestion", {})
        if as_json:
            _emit_json({"ok": True, "action": action, "status": r["status"], "suggestion": suggestion})
            return
        print("Akıllı Rutin Önerisi")
        print("─" * 72)
        print(f"Ad:        {suggestion.get('name', '-')}")
        print(f"Cron:      {suggestion.get('expression', '-')}")
        print(f"Template:  {suggestion.get('template_id', '-') or '-'}")
        print(f"Kanal:     {suggestion.get('report_channel', '-')}")
        print(f"Güven:     {suggestion.get('confidence', '-')}")
        steps = suggestion.get("steps", []) if isinstance(suggestion.get("steps"), list) else []
        if steps:
            print("Adımlar:")
            for s in steps:
                print(f"- {s}")
        panels = suggestion.get("panels", []) if isinstance(suggestion.get("panels"), list) else []
        if panels:
            print("Paneller:")
            for p in panels:
                print(f"- {p}")
    elif action == "add":
        text = str(getattr(args, "text", "") or "").strip()
        if text:
            payload = {
                "text": text,
                "name": str(getattr(args, "name", "") or "").strip(),
                "expression": str(getattr(args, "expression", "") or "").strip(),
                "report_channel": getattr(args, "report_channel", "telegram"),
                "report_chat_id": getattr(args, "report_chat_id", ""),
                "enabled": not bool(getattr(args, "disabled", False)),
                "created_by": "cli-nl",
                "panels": _parse_panels(getattr(args, "panels", "")),
            }
            r = _api_request("POST", "/api/routines/from-text", payload=payload, port=port)
            if not r["ok"]:
                if as_json:
                    _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                    return
                print(f"❌  Metinden rutin oluşturulamadı: {r['data'].get('error', 'unknown')}")
                return
            item = r["data"].get("routine", {})
            if as_json:
                _emit_json({"ok": True, "action": action, "status": r["status"], "routine": item, "mode": "natural_text"})
                return
            print(f"✅  Metinden rutin eklendi: {item.get('id')} — {item.get('name')}")
            return

        name = str(getattr(args, "name", "") or "").strip()
        expression = str(getattr(args, "expression", "") or "").strip()
        steps_raw = str(getattr(args, "steps", "") or "").strip()
        template_id = str(getattr(args, "template_id", "") or "").strip()
        panels = _parse_panels(getattr(args, "panels", ""))
        payload_common = {
            "report_channel": getattr(args, "report_channel", "telegram"),
            "report_chat_id": getattr(args, "report_chat_id", ""),
            "enabled": not bool(getattr(args, "disabled", False)),
            "created_by": "cli",
            "panels": panels,
        }
        if template_id:
            if not expression:
                print("❌  --expression zorunlu (template ile).")
                return
            payload = {
                **payload_common,
                "template_id": template_id,
                "expression": expression,
                "name": name,
            }
            r = _api_request("POST", "/api/routines/from-template", payload=payload, port=port)
            if not r["ok"]:
                if as_json:
                    _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                    return
                print(f"❌  Template rutin eklenemedi: {r['data'].get('error', 'unknown')}")
                return
            item = r["data"].get("routine", {})
            if as_json:
                _emit_json({"ok": True, "action": action, "status": r["status"], "routine": item})
                return
            print(f"✅  Template rutin eklendi: {item.get('id')} — {item.get('name')}")
            return

        if not (name and expression and steps_raw):
            print("❌  --name, --expression ve --steps zorunlu.")
            print("Örn: elyan routines add --name 'Sabah Kontrol' --expression '0 9 * * *' --steps 'Tarayıcıyı aç;Paneli kontrol et;Excel hazırla;Rapor gönder' --panels 'seller.example.com,mail.example.com'")
            print("Örn: elyan routines add --template-id ecommerce-daily --expression '0 9 * * *' --name 'E-ticaret Sabah'")
            return
        steps = [s.strip() for s in steps_raw.replace("\n", ";").split(";") if s.strip()]
        payload = {
            "name": name,
            "expression": expression,
            "steps": steps,
            **payload_common,
        }
        r = _api_request("POST", "/api/routines", payload=payload, port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Rutin eklenemedi: {r['data'].get('error', 'unknown')}")
            return
        item = r["data"].get("routine", {})
        if as_json:
            _emit_json({"ok": True, "action": action, "status": r["status"], "routine": item})
            return
        print(f"✅  Rutin eklendi: {item.get('id')} — {item.get('name')}")
    elif action == "rm":
        rid, rid_err = _resolve_routine_id(port, getattr(args, "id", ""))
        if rid_err:
            print(f"❌  {rid_err}")
            return
        r = _api_request("DELETE", f"/api/routines/{rid}", port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "id": rid, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Kaldırılamadı: {r['data'].get('error', 'unknown')}")
            return
        if as_json:
            _emit_json({"ok": True, "action": action, "id": rid, "status": r["status"]})
            return
        print(f"✅  Rutin kaldırıldı: {rid}")
    elif action in {"enable", "disable"}:
        rid, rid_err = _resolve_routine_id(port, getattr(args, "id", ""))
        if rid_err:
            print(f"❌  {rid_err}")
            return
        enabled = action == "enable"
        r = _api_request("POST", "/api/routines/toggle", payload={"id": rid, "enabled": enabled}, port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "id": rid, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Güncellenemedi: {r['data'].get('error', 'unknown')}")
            return
        if as_json:
            _emit_json({"ok": True, "action": action, "id": rid, "enabled": enabled, "status": r["status"]})
            return
        print(f"✅  {rid} {'aktif' if enabled else 'pasif'}")
    elif action == "run":
        rid, rid_err = _resolve_routine_id(port, getattr(args, "id", ""))
        if rid_err:
            print(f"❌  {rid_err}")
            return
        r = _api_request("POST", "/api/routines/run", payload={"id": rid}, port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "id": rid, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  Çalıştırılamadı: {r['data'].get('error', 'unknown')}")
            return
        result = r["data"].get("result", {})
        if as_json:
            _emit_json({"ok": bool(result.get("success")), "action": action, "id": rid, "status": r["status"], "result": result})
            return
        print(f"{'✅' if result.get('success') else '❌'}  Run {rid} ({result.get('duration_s', '?')}s)")
        report = str(result.get("report", "") or "").strip()
        if report:
            print(report[:1200])
    elif action == "history":
        rid = str(getattr(args, "id", "") or "").strip()
        if rid:
            resolved, rid_err = _resolve_routine_id(port, rid)
            if rid_err:
                print(f"❌  {rid_err}")
                return
            rid = resolved or rid
        path = "/api/routines/history"
        if rid:
            path += f"?id={rid}"
        r = _api_request("GET", path, port=port)
        if not r["ok"]:
            if as_json:
                _emit_json({"ok": False, "action": action, "id": rid or None, "status": r["status"], "error": r["data"].get("error", "unknown")})
                return
            print(f"❌  History alınamadı: {r['data'].get('error', 'unknown')}")
            return
        if as_json:
            _emit_json({"ok": True, "action": action, "id": rid or None, "status": r["status"], **r["data"]})
            return
        data = r["data"]
        if rid:
            hist = data.get("history", [])
            if not hist:
                print("Geçmiş yok.")
                return
            for h in hist:
                print(f"[{h.get('ts')}] {'OK' if h.get('success') else 'FAIL'} {h.get('duration_s')}s {h.get('summary','')}")
        else:
            items = data.get("items", [])
            if not items:
                print("Geçmiş yok.")
                return
            for item in items:
                print(f"\n{item.get('id')} — {item.get('name')}")
                for h in item.get("history", []):
                    print(f"  [{h.get('ts')}] {'OK' if h.get('success') else 'FAIL'} {h.get('duration_s')}s {h.get('summary','')}")
    else:
        print(f"Bilinmeyen action: {action}")
