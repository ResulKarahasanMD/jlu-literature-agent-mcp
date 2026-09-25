# Değişiklik günlüğü

## 0.3.0 - 2026-08-12

- UniProt accession sorgusu eklendi: dizi, enzim metadata'sı ve bağlantılı DOI/PMID/PMCID
  referansları.
- Hedef alanlar, şekiller, tablolar ve ek materyal referansları için temkinli PDF kanıt ön
  değerlendirmesi eklendi.
- Ayrı bir staging dizini ve maskelenmiş JSONL manifestiyle ek dosya
  bulma/indirme/doğrulama eklendi.
- Selülaz ölçüm şeması ve yapı, substrat, metrik ailesi, birim ve ölçüm yöntemine göre
  gruplanmış en yüksek gözlenen değer seçimi eklendi; eksik alanlar ve sayısallaştırılmış
  kanıt sessizce doldurulmaz, açıkça belirtilir.
- Güvenli substrat takma adları ve yalnız belirsizliği olmayan birim dönüşümleri eklendi;
  bağıl aktivite sessizce mutlak aktiviteye çevrilmez.

## 0.2.1 - 2026-08-06

- Kişisel deneyim kütüphanesi eklendi (`litlib learn list | add | remove | export`):
  başarılı kurum/CNKI indirmeleri yerelde `alan adı + rota + URL kalıbı + DOI öneki`
  olarak `LITLIB_RUNTIME_ROOT\experience\experiences.json` altına kaydedilir; elle gözlem
  eklenebilir; güvensiz sonuçlar (PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED / FAILED)
  asla öğrenilmez; kaydedilen tüm içerik maskelenir; kişisel deneyim kanonik site
  tariflerinden önce gelir ve Git'e asla commit edilmez.

## 0.2.0 - 2026-08-06

- Nihai bir-skill/iki-MCP mimarisi ve taşınabilir skill referansları oluşturuldu.
- LitLib MCP'nin SQLite ve tam metin erişimi dosya sistemi düzeyinde salt-okur yapıldı.
- Sıkı PDF EOF ve beklenen DOI kontrolleri eklendi.
- Unicode güvenli başlık/yazar tekilleştirmesi ve açık metadata çakışma hataları eklendi.
- `IMPORTED` öncesinde tam Zotero öğesi ve PDF doğrulaması zorunlu kılındı.
- Boş doğrulama ve karşılanmamış içe aktarma ön koşulları için güvenilir sıfır dışı çıkış
  kodları eklendi.
- Rota URL'i/token maskelemesi eklendi, çerez dışa aktarma varsayılan olarak kapatıldı.
- Taşınabilir çalışma zamanı yapılandırması, üzerine yazmayan tekli indirmeler, CI, sürüm
  belgeleri ve GitHub için güvenli ignore kuralları eklendi.
- Kimlik bilgisi gönderimi izin listesindeki HTTPS JLU IdP host'larıyla sınırlandı;
  koşulları/öznitelik paylaşımını onaylamak yalnız insana bırakıldı.
- Kesin `PAYWALLED` durumu, kurum partileri için katı 10 makale sınırı, üzerine yazmayan
  parti kurtarma ve kısmi başarısızlık çıkış kodları eklendi.
- PyMuPDF yerine BSD lisanslı pypdf kullanıldı; ilk sayfa/ilk üç sayfa PDF kimlik
  kontrolleri güçlendirildi.

## 0.1.0 - 2026-08-05

- Metadata, OA/kurum üzerinden edinme, PDF doğrulama, RIS içe aktarma, Zotero Local API
  okumaları ve yayıncı rotası denemeleri için ilk yerel iş akışı.
