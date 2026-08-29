# Elyan Product Architecture

## Tek sistem

Elyan mobil uygulama, backend ve masaüstü çalışma zamanından oluşan tek bir sistemdir. Mobil uygulama isteği gönderir ve backend sözleşmelerini gösterir. Backend kimlik, sohbet, hafıza, bilgi kaynakları, görev durumu ve yönlendirmeyi yönetir. Masaüstü çalışma zamanı yalnız kullanıcının cihazında yapılması gereken yerel ve özel işleri yürütür.

## Yerel ve bulut sınırı

Genel sohbet, doğrulanmış internet bilgisi, kullanıcı hafızası ve görev koordinasyonu backend üzerinden yürür. Yerel dosyalar, masaüstü uygulamaları, ekran ve bilgisayar kontrolü masaüstü çalışma zamanına aittir. Özel yerel içerik açık izin olmadan backend'e taşınmaz.

## Sonuçlar

Elyan cevapları metin, tablo, grafik, kaynak kartı, onay, görev durumu ve artifact bloklarıyla gösterebilir. Bir yerel dosya veya cihaz eylemi istenmiyorsa masaüstü bağlantısı genel bilgi cevabı için ön koşul değildir.
