# Elyan Website — Design System

Register: **brand** (pazarlama yüzeyi). Kişilik: fütüristik, güçlü, akıllı.
Sahne: gün ışığında temiz stüdyo — beyaz zeminde derin zümrüt vurgu; koyu tema "gece komuta merkezi" olarak korunur.

## Renk (OKLCH, `website/app/globals.css` içinde token'lar)

Açık tema varsayılandır (`:root`, saf beyaz zemin), koyu tema `html.theme-dark` (near-black sinematik).

| Rol | Koyu (`html.theme-dark`) | Açık (varsayılan) |
|---|---|---|
| `--background` | `oklch(0.11 0 0)` | `oklch(1 0 0)` |
| `--surface-1..4` | 0.155 → 0.30, hafif 165° kroma | 0.985 → 0.87 |
| `--text` | `oklch(0.965 0.004 165)` | `oklch(0.2 0.012 165)` |
| `--primary` | `oklch(0.87 0.15 162)` parlak mint, üstünde koyu metin (`--on-primary`) | `oklch(0.5 0.13 162)` derin zümrüt, üstünde beyaz |
| `--accent` | `oklch(0.82 0.13 80)` amber | `oklch(0.58 0.13 70)` |
| `--glow` | primary'nin saydam halkası; kart hover ve CTA aurası | aynı, daha zayıf |

Strateji: **Committed** — zümrüt tüm etkileşimi taşır (CTA, demo, durum, parıltılar); yüzey saf near-black.

## Tipografi

- Tek aile: **Bricolage Grotesque** (değişken: wght 200–800, opsz 12–96; self-host `public/fonts/bricolage/`, latin + latin-ext/Türkçe).
- Display: 620–640 ağırlık, letter-spacing −0.03em, `text-wrap: balance`.
- Gövde: 16px / 1.72, `--text-muted`, max 68ch, `text-wrap: pretty`.

## Motion

- Easing: `--ease-out-expo` `cubic-bezier(0.16,1,0.3,1)`; sadece transform/opacity (compositor-dostu, 60fps).
- Hero: kelime kelime maskeli başlık, prompt-typer, cihazlar 3D `rotateX` perspektif düzelmesiyle scroll'a bağlı (`useScroll`+`useSpring`).
- Bölüm reveal'ları çeşitli (`AnimatedBlock` variant: rise/fade/zoom/slide-*), kartlarda imleç-takipli `--mx/--my` radial glow.
- **`lib/use-entrance.ts` zorunlu**: giriş animasyonları yalnızca belge görünürken; gizli sekme/headless'ta içerik anında görünür (boş sayfa gönderme yasağı).
- `prefers-reduced-motion`: global kill-switch + marquee wrap fallback.

## Bileşen dili

- Radius: kartlar 24px, pencere 20px, hap 999px. Kartlar tek tip: 1px `--outline`, hover'da −4px kalkış + glow; nth-child şekil oyunları YOK.
- Nav: yüzer hap, `backdrop-filter` cam, her iki temada koyu.
- 3D maskot: `public/models/elyan-robot.glb` — PNG maskotun prosedürel 3D modeli, `website/scripts/build-robot-glb.mjs` ile üretilir (parça adları animasyon sözleşmesi). Çalışma zamanı `components/robot-3d.tsx`: mouse takibi (kafa+gövde), tıklama jestleri (selam/zıplama/dönüş/coşku), scroll hızına eğilme, göz kırpma, nefes; görünürken frameloop, reduced-motion'da statik.

## Yasaklar (bu projede tekrarlama)

Krem/bej zemin, her bölümde eyebrow, 01/02 numaralı özdeş kart grid'leri, gradient text, glassmorphism-süs, Inter/generic font.
