# Graveyard (Quarantine)

Bu klasör, geçici/kirli çıktıların silinmeden önce karantinaya alındığı yerdir.

Kural:
1. Doğrudan silme yok.
2. Önce `/_graveyard/YYYYMMDD/` altına taşı.
3. Daha sonra manuel inceleme ile kalıcı temizleme yapılır.

Örnek:
```bash
mkdir -p _graveyard/$(date +%Y%m%d)
mv tmpdir/* _graveyard/$(date +%Y%m%d)/
```

