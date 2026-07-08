# Elyan Mac — Devir Notu (2026-07-08)

Amaç: Elyan macOS uygulamasını Jarvis gibi çalıştırmak — komutları anlayıp
masaüstünde gerçekten yürüten, sunucu beyniyle yalnız JSON veri sözleşmesiyle
konuşan bir agent.

## Mimari (mevcut hal)

- **Swift app** (`apps/macos/ElyanMac/`) → `RuntimeBridgeSwift` ile Python alt
  sürecini (`runtime/bridge.py`, stdin/stdout JSON) yönetir.
- **Komut akışı (yerel-öncelikli)**: mesaj önce yerel runtime'da çalışır
  (`conversation.send`) → deterministik router (`runtime/task_router.py`) →
  eşleşmezse yapılandırılmış planlayıcı (`runtime/structured_planner.py`,
  sözleşme: `elyan.plan.v1`) sunucu beynine JSON zarf gönderir → dönen plan
  doğrulanır → **yürütme daima masaüstünde** (`runtime/executor_core.py`,
  adımlar arası `_previousOutput/_previousResult` veri akışı var).
- Bridge çalışmıyorsa Swift eski bulut yoluna düşer (ChatStore.send fallback).

## Bu oturumlarda yapılanlar

1. **Router güçlendirme** (`task_router.py`): istek kipi normalizasyonu
   ("açar mısın/lütfen"), "X'e git/gir" site rotası (`_KNOWN_SITES`),
   "belgele/dökümante et/rapora dönüştür" → document_write (eskiden shell_run'a
   kaçıyordu!), "hakkında bilgi topla" → web_research.
   Testler: `tests/test_task_router_jarvis_commands.py`.
2. **Bileşik komutlar** (`_compound_route`): "X'i araştır ve belgele" → sıralı
   çok adımlı plan; muhafazakâr bölme (her parça ≥0.8 güvenle rotalanmalı).
   Zamir devamları ("bunu belgele", "sonucu bana mail at" → `me` alıcı çözümü)
   paralel oturumda eklendi. Testler: `tests/test_compound_dispatch_chain.py`.
3. **Yazıcı araç zinciri** (`capability_registry._writer_source_context`):
   document/spreadsheet/presentation/canvas artık önceki adımın çıktısını
   (özet + kaynaklar) içerik olarak devralıyor.
4. **SwiftUI gözlem düzeltmesi**: ChatView `@ObservedObject var chat` oldu
   (eskiden appState üzerinden computed — mesajlar 25 sn'lik watchdog'a kadar
   ekrana düşmüyordu).
5. **Self-pairing** (`bridge.pairing_self_pair` + `_ensure_self_paired_async`):
   masaüstü, telefonsuz kendi pairing oturumunu kendi user token'ıyla claim
   edip runtime'ı register ediyor. Girişte (`backend.auth_sync_session`) ve
   açılışta (`bootstrap`) otomatik. Canlıda doğrulandı (register 200, ws OK).
6. **Yerel-öncelikli chat** (Swift): `PythonRuntimeSupervisor.sendLocalChat`
   → `ChatStore.localSend` → bulut "masaüstü ortamı yok" retleri bitti.
   Canlı doğrulandı: "safariyi aç" gerçekten Safari'yi açıyor.
7. **Yapılandırılmış planlama** (`structured_planner.py`, `elyan.plan.v1`):
   araç kataloğu (JSON Schema) + kurallar + yanıt şeması tek JSON zarf; plan
   tek noktada doğrulanıyor. Bu oturumda eklenen: öğrenilmiş rota geçmişi
   (`intelligence_context`) ve masaüstü canlı durumu (`context.desktop`)
   zarfa veri olarak giriyor; geçersiz plana tek turluk yapılandırılmış
   onarım (`elyan.plan.repair`); eski 80 satırlık düz metin planner prompt
   silindi. Testler: `tests/test_structured_planner_contract.py`.

Test durumu: `./venv/bin/python -m pytest tests/ --ignore=tests/electron`
→ 423 passed. Swift build: `xcodebuild -project ElyanMac.xcodeproj -scheme
ElyanMac -configuration Debug build` → SUCCEEDED.

## Sıradaki işler (öncelik sırasıyla)

1. **desktop_operator planner'ı `elyan.plan.v1`'e taşı** — bridge.py'de
   "You are Elyan's desktop operator planner" serbest metin prompt'u hâlâ
   duruyor (ekran otomasyonu adımları üreten ikinci planlama yüzeyi).
   `structured_planner` altyapısı hazır; aynı zarf + doğrulama uygulanmalı.
2. **Yerel sohbetlerin bulut geçmişine senkronu** — yerel yürüyen konuşmalar
   soldaki "Geçmiş" (cloud sessions) listesine düşmüyor. `send_conversation`
   sonuçlarını backend session'a push etmek veya kenar çubuğunu yerel
   konuşma deposundan (`conversation.list`) beslemek gerek.
3. **Plan onay UX'i** — çok adımlı planlar düz metin özet + "onayla" yazarak
   onaylanıyor; ChatView'da planPreview bloklarını buton/kart olarak çizmek
   (`needsConfirmation`, `pendingPlanId` alanları zaten dönüyor).
4. **Canlı akış** — yerel yol senkron tek cevap dönüyor; uzun görevlerde adım
   adım ilerleme göstermek için bridge'in unsolicited event'leriyle
   (onUnsolicitedResponse) streaming benzeri güncelleme yapılabilir.
5. **Eval setini büyütme** — kullanıcının gerçek ıskalayan komutları
   `test_task_router_jarvis_commands.py`'a eklenerek döngü kapatılmalı.
6. **ReAct döngüsü** — executor statik planı koşuyor; adım sonucunu planlayıcıya
   geri besleyip devam/revize kararı aldırmak (yapı: executor_core +
   structured_planner repair zarfının genellenmesi).

## Bilinmesi gerekenler

- Backend: `https://api.elyan.dev` (config/api_keys.json). Runtime durumu:
  `~/Library/Application Support/Elyan/state/elyan_state.json`.
- **İki bridge sürecini aynı anda çalıştırma** — refresh token rotasyonu
  yarışıp oturumu düşürüyor (test sırasında bir kez yaşandı).
- Yerel modeller bilinçli olarak kapsam dışı bırakıldı (kullanıcı istemedi).
- Değişiklikler commit'lenmedi; working tree'de duruyor (branch:
  v2-desktop-design).
