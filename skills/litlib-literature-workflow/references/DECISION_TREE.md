# Edinme karar ağacı

Bu referans, genellenebilen gözlemleri yayıncıya özgü tariflerden ayırır. Her adımı yalnız
kullanıcının yetkili erişim hakları içinde uygulayın.

## 1. Hedefi belirleyin

Önce DOI, sonra PMID/PMCID/arXiv, sonra tam başlık tercih edin. Kuyruğa eklemeden önce
`https://doi.org/10.xxxx/...` gibi DOI URL'lerini normalleştirin. Kaynak veritabanını ve
amaçlanan öğe türünü kaydedin. Bir veri kümesi, protokol bölümü, düzeltme, ek materyal, kitap
bölümü ve dergi makalesi aynı yayıncı altyapısını paylaşabilir ama farklı edinme mantığı
gerektirir.

İndirmeden önce şu soruları yanıtlayın:

- Hedef bir makale PDF'i mi, HTML makale mi, CAJ dosyası mı, ek materyal mi, veri kümesi mi?
- OA mı, kurum yetkisiyle mi erişilebilir, yalnız satın alınabilir mi, bilinmiyor mu?
- Kullanıcı kampüste mi, kampüs dışında CARSI ile mi, WebVPN ile mi?
- Görev LitLib'de ya da Zotero'da zaten var mı?

## 2. Rotaları bu sırayla deneyin

1. **OA keşfi:** arXiv, tanınıyorsa MDPI public static adayı, Unpaywall, Europe PMC, OpenAlex;
   sonra yalnız lisans metadata'sı OA olduğunu kanıtlıyorsa bir Crossref bağlantısı.
2. **Doğrudan HTTP adayı:** bilinen kararlı bir PDF uç noktasını yalnız yetki ve içerik türü
   uygunsa kullanın.
3. **Görünür tarayıcıda doğrudan:** DOI'yi çözün, işlenmiş makale sayfasını inceleyin ve
   kullanıcının mevcut kampüs ya da kimliği doğrulanmış yayıncı oturumunu yeniden kullanın.
4. **WebVPN:** yalnız geçerli bir JLU bileti ve yayıncı token'ı zaten varsa. Eksik token,
   atlanan bir rotadır; sonraki tüm rotaları iptal etmek için bir neden değildir.
5. **Kurum girişi:** gerçek DOI açılış host'unu çözün, WAYF/CARSI federasyonunda Jilin
   Üniversitesi'ni seçin, yalnız izin listesindeki bir HTTPS JLU IdP'sinde kimlik doğrulayın,
   kullanıcının koşulları/öznitelik paylaşımını incelemesi ve elle karar vermesi için durun,
   yayıncıya geri dönün, sonra PDF'i yeniden deneyin.

Her aday ayrı ayrı doğrulanmalıdır. Başarısız bir OA açılış sayfası sonraki OA sağlayıcısını
engellememelidir. Başarısız bir WebVPN rotası doğrudan kurum girişi rotasını engellememelidir.

## 3. Dönen nesneyi teşhis edin

Bu sırayla inceleyin:

1. HTTP durumu ve son URL.
2. `Content-Type`, `Content-Length` ve `Content-Disposition`.
3. İlk beş bayt (`%PDF-`) ve sona yakın `%%EOF`.
4. Ayrıştırılan sayfa sayısı ve çıkarılan metin.
5. İlk üç sayfada beklenen DOI, 1. sayfada çakışan DOI ve ek materyal göstergeleri.

Yaygın birleşimleri şöyle yorumlayın:

| Gözlem | Olası neden | Sonraki adım |
|---|---|---|
| PDF URL'inden `200 text/html` | Giriş sayfası, anti-bot sayfası, HTML görüntüleyici ya da yalnız HTML yetkisi | Görünür sayfayı ve kimlik doğrulama durumunu inceleyin; PDF olarak kaydetmeyin |
| `206 application/pdf`, çok küçük, sıfır sayfa | Görüntüleyicinin aralık parçası | Kaynağın tamamını aynı kökenli fetch, yerel indirme ya da tamamlanmış aralık birleştirmeyle alın |
| `%PDF-` var ama `%%EOF` yok | Kesilmiş aktarım ya da kısmi yanıt | Reddedin, başka bir rota deneyin |
| Geçerli PDF ama hedef DOI yok | Yanlış makale, ek materyal, sayının ön kısmı ya da çıkarma hatası | Varsayılan olarak reddedin; bir istisna yapmadan önce elle inceleyin |
| İlk sayfa başlığında farklı bir DOI | Yanlış makale | Hemen reddedin |
| Doğrudan `403` ama makale tarayıcıda görünüyor | İmzalı URL, köken/oturum gereksinimi ya da anti-bot politikası | Aynı sayfa kökeninden fetch edin ya da yayıncının yerel indirmesini tetikleyin |
| `429` | Hız sınırı | Durun, soğumayı bekleyin, `RATE_LIMITED` durumunu koruyun |
| Satın alma/kiralama metni | Güncel yetki yok | Durun ve yalnız satın alınabilir olarak raporlayın |

## 4. Tarayıcıya yükseltme basamakları

Tarayıcı gerektiğinde, yetkili oturumu koruyan en az müdahaleci yöntemi kullanın:

1. `citation_pdf_url`, `dc.*`, JSON-LD, canonical URL ve görünür PDF bağlantılarını okuyun.
2. Yayıncının PDF görüntüleyicisine gidin ve `performance.getEntriesByType('resource')`'u
   inceleyin.
3. Tam bir dosya üretiyorsa tarayıcının yerel indirmesini tercih edin.
4. İmzalı ya da oturuma bağlı bir PDF URL'i için sayfa bağlamında aynı kökenli `fetch`
   kullanın.
5. CDP yanıt gövdelerini ancak durumu ve aktarım semantiğini kontrol ettikten sonra kullanın.
   Görüntüleyiciler çoğu zaman bayt aralıkları ister; `Network.getResponseBody` PDF'in
   tamamı yerine tek bir parça döndürebilir.

Kimlik bilgilerini rastgele üçüncü taraf sayfalara enjekte etmeyin. Kimlik bilgileri yalnız
Windows Credential Manager'dan okunabilir ve beklenen JLU kimlik sağlayıcısı host'una
gönderilebilir.

## 5. Kimlik doğrulama kararı

Dört hatayı birbirinden ayırın:

- **Yayıncı oturumu yok:** kurum erişimi bağlantısına tıklayın ve WAYF üzerinden devam edin.
- **İnsan doğrulaması:** görünür tarayıcıda bekleyin. Otomatik yeniden deneme döngüsüne
  girmeyin.
- **Desteklenmeyen SP:** JLU IdP servisin/isteğin desteklenmediğini söylüyor; o yayıncı için
  CARSI'yi bırakın ve kampüs IP'si/WebVPN alternatiflerini raporlayın.
- **Kimliği doğrulanmış ama PDF yetkisi yok:** makale HTML'i okunabilirken PDF yalnız satın
  alınabilir kalabilir. Yetkiyi başarılı girişten ayrı değerlendirin.

Kimlik doğrulamasından sonra makaleyi yeniden yükleyin ya da tekrar ziyaret edin. Bazı
yayıncılar zaten açık belgede erişim metadata'sını güncellemez.

## 6. Yeni bir yayıncıya genelleme

Bilinmeyen bir host için hemen sabit kodlu bir DOI öneki rotası eklemeyin. Şunları toplayın:

- DOI öneki ve gerçek yönlendirme host'u.
- Makale türü ve OA/lisans metadata'sı.
- PDF işlemi için kararlı sayfa metadata'sı/DOM seçicisi.
- PDF URL'inin aynı kökenli mi, imzalı mı, kısa ömürlü mü, CDN URL'i mi olduğu.
- Doğrudan HTTP'nin, yerel gezinmenin, aynı kökenli fetch'in ya da kurum girişinin işe yarayıp
  yaramadığı.
- Doğrulama, hız sınırı ve yalnız satın alma göstergeleri.
- Kullanıcı yetkili bir oturumdan alınmış, tam ve doğrulanmış bir PDF.

Sonra en küçük adaptörü ve fixture tabanlı bir testi yazın. Host algılamayı DOI öneki
algılamasından ayrı tutun; çünkü yayıncılar dergi satın alır ve yönlendirme host'ları değişir.

Yararlı çıkarım denemeleri, sırasıyla:

1. DOI'yi çözün ve standartlara dayalı metadata'yı inceleyin.
2. Görünür bir PDF bağlantısını ve tıklamadan sonraki hedefini inceleyin.
3. Performans zaman çizelgesinde imzalı bir PDF kaynağı arayın.
4. Başarılı bir tarayıcı isteğini başarısız doğrudan istekle karşılaştırın: köken, referer,
   çerezler, yöntem, durum, aralık semantiği ve yönlendirme zinciri.
5. Kod yazmadan önce öğenin yalnız HTML mi yoksa makale dışı bir içerik türü mü olduğunu
   kontrol edin.

Aynı platformda en az bir makale daha kontrol edilmeden tek bir DOI'den geçici çözümü
genellemeyin. Doğrulanmamış rotaları `verified` değil, `inferred` olarak kaydedin.

## 7. Kurtarma ve teslim

Bir çökmeden sonra:

```powershell
litlib queue recover
litlib queue recover --failed
litlib queue recover --paused
```

`--failed`'i yalnız kök neden düzeltildikten ve deneme sınırları izin veriyorsa kullanın.
`--paused`'ı yalnız insan doğrulaması ya da soğuma tamamlandıktan sonra kullanın.

Teslimden önce:

```powershell
litlib verify
litlib status --verbose
```

Görev dosya kaydı olmayan, diskteki bir PDF kurtarma dosyasıdır; tamamlanmış bir indirme
değildir. Doğrulanmış bir Zotero parent item'ı ve PDF eki olmayan bir RIS dosyası `IMPORTED`
değildir.
