# Elyan Website Design System

## 1. Visual Theme and Atmosphere
Yerel zekâyı fiziksel bir sistem gibi gösteren koyu, sinematik ve teknik bir atmosfer. Ana görsel dil; mobil, kontrol düzlemi ve masaüstü katmanlarını birbirine bağlayan yörüngeler ve derinlik geçişleri.

## 2. Color Palette and Roles
- Ink Canvas: `oklch(0.16 0.012 145)` — ana zemin
- Warm Paper: `oklch(0.93 0.025 88)` — ana metin
- Sage Signal: `oklch(0.72 0.09 154)` — birincil aksiyon
- Copper Pulse: `oklch(0.70 0.12 55)` — vurgu ve çalışma durumu
- Muted Moss: `oklch(0.65 0.025 145)` — ikincil metin

## 3. Typography Rules
Başlık: `Bodoni Moda`, yüksek kontrastlı ve editoryal. Gövde: `Manrope`, küçük boyutlarda okunaklı. Büyük başlıklarda `-0.035em`, ara başlıklarda `-0.018em` izleme.

## 4. Component Stylings
Butonlar 14px sabit yarıçaplı, hover'da 3px yükselir, active'da `scale(.97)`. İçerik yüzeyleri kart ızgarası yerine ince ayırıcılar ve zemin parlaklık basamakları kullanır.

## 5. Layout Principles
12 kolon; asimetrik 7/5 hero, 80–120px bölüm ritmi, en fazla 1240px içerik genişliği. Mobilde tek kolon ve 20px yatay güvenli alan.

## 6. Depth and Elevation
Derinlik Three.js sahnesi, yumuşak radyal ışık ve `rgba(255,255,255,.03-.06)` yüzey basamaklarıyla kurulur. Glass blur kullanılmaz.

## 7. Do / Don't
- Gerçek Elyan logosunu kullan.
- Yerel gizlilik ve izin akışını açık anlat.
- Üç katman sınırını doğru göster.
- Mor-mavi AI gradient kullanma.
- Sahte puan, kullanıcı sayısı veya mağaza rozeti üretme.
- Masaüstü motorunu bulut servisi gibi anlatma.

## 8. Responsive Behavior
980px altında nav drawer'a döner; 760px altında 3B sahne küçülür ve metnin arkasına geçmez. Tüm hedefler en az 44px. Reduced motion'da yörünge ve sayfa girişleri durur.

## 9. Agent Prompt Guide
`canvas: oklch(0.16 0.012 145)`, `paper: oklch(0.93 0.025 88)`, `signal: oklch(0.72 0.09 154)`, `copper: oklch(0.70 0.12 55)`, `radius: 14px`.
