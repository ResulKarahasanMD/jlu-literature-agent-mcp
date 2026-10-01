# Nihai mimari: bir skill + iki MCP

## Bileşen sınırları

```text
                        akademik veritabanı araçları
                                   |
                                   v
Kullanıcı isteği --> litlib-literature-workflow skill
                    |          |            |
                    |          |            +--> ZotSeek MCP (semantik hatırlama)
                    |          +---------------> LitLib MCP (tam, yerel okumalar)
                    +--------------------------> litlib CLI (tüm değişiklikler)
                                                         |
        metadata API'leri / OA / JLU tarayıcısı ---------+
                                                         v
             görev SQLite + doğrulanmış PDF'ler --> RIS --> Zotero
                                                         |
                                                         +--> ZotSeek yerel indeksi
```

### Skill

`skills/litlib-literature-workflow/`, taşınabilir Agent politika paketidir. İçeriği:

- `SKILL.md`: tetikleyiciler, yönlendirme, uyum, başarı sözleşmeleri, insan checkpoint'leri.
- `references/DECISION_TREE.md`: genelleştirilmiş arıza teşhisi ve yeni site keşfi.
- `references/SITE_RECIPES.md`: tarihli, kanıt etiketli yayıncı gözlemleri.
- `references/CLIENT_SETUP.md`: klonlama, Zotero, ZotSeek, MCP ve skill kurulumu.

Skill kendi başına bir şey çalıştırmaz ve akademik arama veritabanının yerini tutmaz.
Agent'ın akademik arama yeteneğini, LitLib CLI'ı ve iki MCP sunucusunu yönetir.

### LitLib MCP

Projenin kendi stdio sunucusu: `litlib mcp`.

- Zotero Local API ve LitLib görev veritabanında tam/yerel metadata araması.
- Belirsizlik algılamalı PDF yolu çözümleme.
- Sayfalı PDF metni çıkarma.
- Zotero koleksiyonlarını ve görev durumlarını okuma.
- SQLite'ı `mode=ro` ve `PRAGMA query_only=ON` ile açar.
- Şema başlatmaz, günlük oluşturmaz, tam metin önbelleği yazmaz, görevleri değiştirmez,
  Zotero'ya yazmaz.

### ZotSeek MCP

Harici Zotero eklentisinin HTTP sunucusu: `http://127.0.0.1:23119/zotseek/mcp`.

- Etkin modelin yerel indeksi üzerinde semantik, hibrit ve anahtar sözcük araması.
- İndeks kapsamı/durumu ve benzer makale sorgusu.
- MCP çağrıları salt-okurdur; ayar açıksa ZotSeek eklentisi Zotero değişikliklerini ayrıca
  otomatik indeksleyebilir.
- ZotSeek upstream'den kurulur, bu depoda yeniden dağıtılmaz.

## Değişiklik matrisi

| İşlem | Skill | LitLib MCP | ZotSeek MCP | LitLib CLI / insan |
|---|---:|---:|---:|---:|
| Mevcut metadata'yı arama | yönlendirir | evet | anahtar sözcük kısmı | isteğe bağlı |
| Kütüphanede semantik arama | yönlendirir | hayır | evet | hayır |
| PDF indirme | yönlendirir | hayır | hayır | CLI |
| Görev durumunu değiştirme | yönlendirir | hayır | hayır | CLI |
| RIS üretme | yönlendirir | hayır | hayır | CLI |
| Zotero'ya aktarma | checkpoint | hayır | hayır | insanın Zotero işlemi |
| `IMPORTED` onayı | yönlendirir | hayır | hayır | CLI `import --lookup` |
| Embedding oluşturma | checkpoint | hayır | yalnız durum | ZotSeek eklenti arayüzü |

## Veri akışı ve güven sınırları

1. Tanımlayıcılar akademik veritabanlarından ya da kullanıcı girdisinden gelir.
2. SQLite, makalelerin tam metnini değil, iş akışı durumunu ve rota denetimini saklar.
3. PDF'ler yalnız başlık, EOF, sayfa, DOI, ek materyal ve SHA-256 kontrollerinden sonra kabul
   edilir.
4. RIS içe aktarma bilerek insan onayına bağlanmıştır.
5. Bibliyografik doğruluğun kaynağı Zotero'dur. LitLib `zotero.sqlite` dosyasını asla
   düzenlemez.
6. ZotSeek kendi `zotseek.sqlite` dosyasını tutar; bu türetilmiş bir yerel indekstir, ana
   kütüphane değildir.

Kimlik bilgileri Windows Credential Manager'da durur. Tarayıcı çerezleri özel Chrome
profilinde kalır; isteğe bağlı çerez dışa aktarımı varsayılan olarak kapalıdır, açıkça
açılırsa DPAPI ile şifreli bir dosya kullanır. CAPTCHA/Turnstile/kaydırıcı/OTP her zaman
insan tarafından çözülür.

## Durum sözleşmesi

```text
QUEUED -> METADATA_FETCH -> DEDUPED
  |                           |-- OA_OK -> DOWNLOADING -> VERIFYING -> READY
  |                           `-- REQUIRES_INST -> INST_QUEUED -> ... -> READY
  |-- FAILED

READY -> PROPOSAL_GENERATED -> USER_REVIEWED -> IMPORTED

DOWNLOADING/VERIFYING -> PAYWALLED (açıkça yalnız satın alma; kesin son durum)
```

`IMPORTED` bir kullanıcı beyanı değildir. Tek bir tam eşleşen Zotero parent item'ı, boş
olmayan item key ve çözümlenebilir bir PDF eki gerektirir. İnsan doğrulamaları ve hız
sınırları `HUMAN_REQUIRED` ve `RATE_LIMITED` durumlarını kullanır, ardından açıkça
`queue recover --paused` gerekir.

## Taşınabilirlik

Hiçbir açık talimat sabit bir klon yolu varsaymaz. Çalışma zamanı depolaması
`LITLIB_RUNTIME_ROOT` ile denetlenir; D sürücüsü zorunluluğu `LITLIB_REQUIRE_D_DRIVE` ile
isteğe bağlıdır. Kurum adaptörü şu an JLU/Windows'a özgüdür; metadata, OA, doğrulama, görev
durumu ve MCP kodu ise yalıtılmış testler ve gelecekteki adaptörler için tasarlanmıştır.
