---
title: Elyan Second Brain
tags:
  - project/elyan
  - status/active
  - tool/obsidian
aliases:
  - Elyan Context Hub
  - Active Context
---

# Elyan Second Brain

## Entry Points

- [[AGENTS]]
- [[PROGRESS]]
- [[SKILLS]]
- [[ROADMAP]]

## Current State

- P0 yüzeyi temiz: boş email auth guard'ı var, eski onboarding kopyası silinmiş, `.env.example` güncel, Vite production build geçiyor.
- Onboarding içinde model kurulum adımı mevcut: local lane ve cloud fallback ayrı okunuyor, cloud provider key kaydı yapılabiliyor, önerilen Ollama modeli onboarding içinden tetiklenebiliyor ve local pull başlatıldığında ekran otomatik polling ile kendini yeniliyor.
- Türkiye connector'ları artık desktop integrations yüzeyinde ayrı bir "Türkiye Operasyonları" bölümü olarak görünüyor; ürünün ana yönü UI seviyesinde görünür hale geldi.
- Türkiye connector'ları için ilk gerçek dikey dilim açık: desktop üzerinden config kaydı, KVKK consent işaretleme, `health_check` ve `test_credentials` quick action'ları çalışıyor.
- Türkiye connector ayarları artık sadece `elyan_config` fallback'ine bağlı değil; connector repository metadata'sına da yazılıyor. Bu, audit ve kalıcılık açısından daha doğru yön.
- Çalışma ağacı kirli; devam eden desktop UI değişiklikleri var. Var olan kullanıcı değişikliklerine temas etmeden ilerlemek gerekiyor.

## Next Priorities

1. Türkiye connector ayarları için repo metadata yaklaşımını ayrı, explicit bir settings repository/table yapısına dönüştürmek.
2. P2 güvenlik maddelerini repo gerçekliğiyle tekrar doğrulamak.
3. Onboarding model adımında gerçek progress yüzdesi veya stream logu varsa bunu UI'ya bağlamak.

## Verification Snapshot

- `PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build`

> [!note]
> Bu iterasyonda frontend tarafında `tsc --noEmit` ve `vite build` birlikte temiz geçti. Gerçek Türkiye endpoint'lerine karşı canlı entegrasyon testi henüz yapılmadı.
