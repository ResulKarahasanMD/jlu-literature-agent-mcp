# Agent entegrasyonu ve çalışma sözleşmesi

## Entegrasyon ön koşulları

Bir Agent'ın LitLib'i tam kullanabilmesi için üç tür yetenek gerekir:

1. `litlib-literature-workflow` skill dizininin tamamını yükleyebilmek.
2. Tüm indirme ve durum yazma işleri için yerel shell/CLI çalıştırabilmek.
3. Yerel okuma için LitLib ve ZotSeek olmak üzere iki MCP kaydetmek.

Konu düzeyinde literatür araması için Agent'ın ayrıca PubMed/Crossref/OpenAlex gibi akademik
veritabanı yeteneklerine sahip olması gerekir. LitLib sistematik derleme türü aramayı tek
başına yapamaz.

## İki MCP

### LitLib stdio MCP

Başlatma komutu:

```text
<depo-mutlak-yolu>\.venv\Scripts\python.exe -m litlib.cli mcp
```

Araçlar:

| Araç | Sözleşme |
|---|---|
| `library_search_metadata(query, limit)` | Zotero'da ve görev durumunda başlık/DOI/yazar ile künye arar |
| `library_get_pdf_path(query)` | Tek eşleşen PDF'i döndürür; belirsizlikte tahmin etmek yerine adayları döndürür |
| `library_get_fulltext(query, offset, limit_chars)` | Önbelleğe yazmadan sayfalı tam metin, üst sınır 20000 karakter |
| `library_list_collections()` | Zotero koleksiyonlarını okur |
| `library_task_status(state)` | Görev durumunu okur; veritabanı oluşturmaz/taşımaz |

LitLib MCP, SQLite'ı `mode=ro` ve `query_only` ile kullanır; başlarken çalışma dizini ya da
günlük oluşturmaz. Kesin PDF gerekiyorsa önce DOI ya da 8 karakterlik Zotero item key verin.

### ZotSeek HTTP MCP

Adres: `http://127.0.0.1:23119/zotseek/mcp`

Upstream ham araçlar genellikle şunlardır:

- `search`
- `index_status`
- `find_similar`

İstemci bunları `zotseek_search` gibi ad alanlı adlarla gösterebilir. Yalnız ada bakarak
karar vermeyin, araç açıklamasını okuyun. Aramadan önce `index_status` ile etkin modelin
kapsamını doğrulayın. MCP'nin kendisi kütüphaneyi ya da indeksi değiştirmez; ZotSeek
eklentisinin otomatik indekslemesi ayrı bir arka plan davranışıdır.

## İstemci yapılandırması

OpenCode ve Codex için kopyalanabilir yapılandırma skill içindeki
[`CLIENT_SETUP.md`](../skills/litlib-literature-workflow/references/CLIENT_SETUP.md)
dosyasındadır. Önemli noktalar:

- Yapılandırmada her makinenin kendi mutlak çalıştırılabilir yolu kullanılır; bu projenin
  geliştirme makinesinin yolu sabit yazılmaz.
- OpenCode yerel MCP'sinde `command` bir dize dizisidir.
- ZotSeek stdio değil, uzak/HTTP MCP kullanır.
- Skill ya da MCP yapılandırması değişince Agent istemcisi tamamen yeniden başlatılmalıdır.
- Zotero çalışıyor olmalı ve yerel HTTP sunucusuna izin vermelidir.

## Agent başlangıç sırası

```powershell
litlib --version
litlib doctor
litlib status
```

Sonra:

1. Mevcut kütüphane isteği: `zotseek index_status` → semantik arama → LitLib ile tam metin.
2. Yeni konu isteği: akademik veritabanı araması → tanımlayıcılar/kaynak bilgisi → LitLib
   ile edinme.
3. Tek DOI: önce OA akışı (`queue add <DOI>` → `run --stage fetch-metadata` →
   `run --stage oa`). `litlib download <DOI>` → `litlib verify` OA denemez; PDF'i yalnız
   özel Chrome ile indirir, bu yüzden önce `litlib inst open` gerekir.
4. Toplu: kuyruk → metadata → OA → yalnız `REQUIRES_INST` gözetimli kurum aşamasına girer.
5. İçe aktarma: proposal → insanın RIS'i içe aktarması → review → `import --lookup`.
6. Kişisel deneyim (kendini geliştiren): tanımadığınız bir siteyi denemeden önce
   `litlib learn list --domain <site>` (ya da `litlib learn export`) okuyun; kişisel deneyim
   kanonik `SITE_RECIPES.md`'den önce gelir. Doğrulanmış başarılı kurum/CNKI indirmeleri
   otomatik kaydedilir; Agent'lar
   `litlib learn add --domain <site> --route <rota> --note "<ne işe yaradı>"` ile gözlem de
   ekleyebilir.

## Çıkış kodları

Agent, "başarılı görünen" konsol metnine değil, çıkış koduna güvenmelidir:

| Kod | Anlamı |
|---:|---|
| 0 | Komutun hedefi tamamlandı |
| 1 | Çalışma zamanı, doğrulama, sonuç yok ya da kısmi başarısızlık |
| 2 | Kullanım hatası ya da karşılanmamış ön koşul (örn. mevcut dosyanın üzerine yazılacak) |
| 3 | CNKI insan doğrulaması checkpoint'i |

`litlib verify` hiç dosya yoksa 1 döndürür. `litlib import`, `--lookup` kullanılmadıysa ya da
Zotero öğesi/PDF doğrulanamadıysa `IMPORTED` işaretlemez.

`PAYWALLED`, açık satın alma/kiralama/yetki yok durumunun kesin son durumudur;
`queue recover --paused` ile otomatik yeniden denenmemelidir. Kurum aşamasına daha büyük bir
`--limit` verilse bile 10'a kesilir.

## İnsan katılımı

Agent şunları otomatik geçemez: CAPTCHA, Turnstile, CNKI kaydırıcısı, OTP, satın alma
sayfaları, koşullara/öznitelik paylaşımına hukuki onay. Kimlik bilgisinin ilk kaydı,
ZotSeek kurulumu, MCP yapılandırma değişikliği, dosya üzerine yazma ve Zotero'ya yazma
kullanıcıya açıklanmalıdır.

Kurum rotaları gözetimli olmalıdır: parti üst sınırı 10, eşzamanlılık 1, bekleme 8-15
saniye. 429 çıkarsa durulur ve soğuma beklenir; profil değiştirerek, proxy ya da kimlik
değiştirerek atlatılamaz.

## Kişisel deneyim sözleşmesi

- Kişisel deneyim kütüphanesi `<LITLIB_RUNTIME_ROOT>\experience\experiences.json`
  dosyasındadır; depoda değildir, Git'e girmez, kullanıcıya/makineye göre ayrıdır.
- Yalnız sıkı PDF doğrulamasından geçen gerçek başarılar otomatik kaydedilir; `PAYWALLED` /
  `HUMAN_REQUIRED` / `RATE_LIMITED` / `FAILED` asla deneyime yazılmaz.
- Agent yeni bir sitenin deneyimini okurken önce `litlib learn list` çalıştırmalıdır;
  hafızaya dayanamaz ya da rota uyduramaz.
- Deneyim içeriği maskelenmiştir (URL query'si, WebVPN token'ı, çerez, kimlik bilgisi).
  Agent, `learn add`'in note'una ya da URL kalıbına anahtar yazamaz.
- Kişisel deneyim yalnız arama kararlarını hızlandırır, uyum sınırlarını değiştirmez: hiçbir
  deneyim kaydı ödeme duvarı, doğrulama kodu, hız sınırı ya da desteklenmeyen CARSI SP'yi
  aşmaya yetki vermez.
- Selülaz verisi için varsayılan kurallar: en yüksek gözlenen değer yapı × substrat × metrik
  ailesi × birim × assay method'a göre seçilir; farklı substratlar ya da karşılaştırılamaz
  birimler birbiriyle yarışmaz. Mutant/kesik yapılar yalnız dizi açıkça verilmişse ya da açık
  mutasyon/sınırlardan kesin olarak yeniden kurulabiliyorsa resmi veri kümesine girer.
  Grafikten okunan değerler `digitized` olarak işaretlenmeli; gerçek değer yoksa yalnız
  belirsizlik/tekrarlanabilirlik raporlanabilir, gerçek hata yüzdesi iddia edilemez.
- Hatalı deneyimi temizleme: `litlib learn remove <id>`.

## Çıktı gereksinimleri

Her teslimatta requested/resolved/downloaded/verified/imported/human-required/rate-limited/
paywalled sayıları raporlanır; her makale için DOI/PMID, kaynak, başarılı rota ve
verified/inferred/unverified etiketi tutulur. Çerez, parola, API anahtarı, imzalı URL,
WebVPN host token'ı ya da maskelenmemiş rota query'si çıktıya yazılamaz.
