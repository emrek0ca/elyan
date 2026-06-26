# Elyan Desktop Frontend Integration Note

Bu not desktop frontend geliştiricisine bırakılmak içindir. Amaç, belge/görsel akışını UI içinde değil runtime bridge + backend truth üzerinden güvenli şekilde bağlamaktır.

## Temel Kurallar

- UI hiçbir zaman Python runtime internals ile konuşmamalı.
- Dosya okuma, OCR, belge özetleme ve kaydetme işleri sadece RuntimeBridge üzerinden gitmeli.
- Backend truth daima tek kaynak olmalı:
  - `task.summary`
  - `task.artifacts`
  - `task.status`
  - `task.targetDeviceId`
  - `task.routeDecision`
- Renderer içinde raw binary taşıma, parse etme veya dosya yolu üretme yapılmamalı.

## Belge Akışı

- Desktop üzerinde seçilmiş dosya varsa runtime’a `selectedArtifacts` ile iletilmeli.
- Mobilden gelen belge komutları için UI, `task` metnini kısa tutmalı; içerik zaten backend tarafında compact text/chunk olarak hazırlanmış olmalı.
- Elyan’ın yeni birleşik belge akışı şu skill üzerinden yürür:
  - `run_skill`
  - `skillId = "document.summary_and_save"`
- Bu skill yerelde iki adım çalıştırır:
  - `document_read` ile kaynak içeriği özetler
  - `document_write` ile özeti DOCX olarak kaydeder

## UI / Payload Örnekleri

Seçili yerel dosya:

```json
{
  "selectedArtifacts": [
    {
      "path": "/Users/me/Desktop/report.pdf",
      "kind": "document",
      "title": "report.pdf"
    }
  ]
}
```

Mobilden gelen compact belge içeriği:

```json
{
  "metadata": {
    "chatSurface": "mobile",
    "attachments": [
      {
        "name": "rapor.pdf",
        "type": "document",
        "content": "Kısa okunabilir metin veya OCR çıktısı",
        "summary": "Kısa önizleme",
        "chunks": [
          { "text": "..." }
        ],
        "sourceType": "manual",
        "contentTruncated": true
      }
    ]
  }
}
```

## Frontend Yapmaması Gerekenler

- Dosya içeriğini UI katmanında yeniden parse etme.
- Prompt içinden dosya yolu invent etme.
- Backend response beklemeden local state’i truth sanma.
- Save-to-desktop davranışını doğrudan render thread’de çalışma.

## Beklenen Davranış

- Belge komutu geldiğinde UI sadece:
  - seçili artifact’i gösterir,
  - runtime durumunu bekler,
  - plan preview ve artifact sonucu backend truth’tan okur.
- Görev tamamlanınca UI sadece:
  - özet mesajı,
  - çıktı artifact referansını,
  - yeni dosyanın yolunu
  gösterir.
