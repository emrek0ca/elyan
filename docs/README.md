# Elyan AI Operator

Elyan, doğal dili alan ve işi gerçek bilgisayarda, gerçek kanıtla tamamlayan local-first bir AI operatörüdür.

## Kurulum

```bash
curl -fsSL https://get.elyan.ai | bash
elyan status
elyan dashboard
```

## İlk Çalıştırma

İlk onboarding sırasında Elyan şunları hazırlar:

- `agents.md`
- `memory.md`
- Docker sandbox
- Screenpipe MCP
- Ollama modelleri
- Actuator daemon
- `browser`, `desktop`, `calendar` skill'leri

## Kullanım Akışı

1. Görevi doğal dille ver.
2. Elyan planlar, yetenek seçer ve gerekirse approval ister.
3. Action'lar sandbox içinde çalışır.
4. Trace, evidence ve artifact dashboard'da görünür.
5. `elyan/trace/{task_id}` sayfasından tam yürütme kaydını aç.

## Temel Yüzeyler

- CLI
- Dashboard
- Gateway
- Telegram / WhatsApp
- Skill Store
- Integrations
- Autopilot

## Güvenlik

- Zero-permission default
- Approval matrix
- Destructive action onayı
- Evidence-first completion
- Local-only veri saklama

## Demo Notu

Yatırımcı demosunda önce Dashboard açılır, sonra bir görev başlatılır ve Trace/Evidence paneli ile kanıt gösterilir.

## İlgili Dosyalar

- [`docs/pitch-deck.md`](./pitch-deck.md)
- [`docs/index.html`](./index.html)
- [`ui/web/dashboard.html`](../ui/web/dashboard.html)
- [`elyan/dashboard/routes/trace.py`](../elyan/dashboard/routes/trace.py)
