---
name: litlib-literature-workflow
description: Kullanıcı makale bulmak/edinmek istediğinde ya da literatür arama, makale indirme, toplu makale edinme, kurum erişimi (JLU/BVU), CARSI/WebVPN/GlobalProtect, CNKI, PDF doğrulama, Zotero'ya aktarma, yerel literatür kütüphanesinde arama, LitLib veya ZotSeek dediğinde kullanın. Akademik arama araçlarını, litlib CLI'ı, salt-okur LitLib MCP'yi ve salt-okur ZotSeek MCP'yi CAPTCHA ya da ödeme duvarlarını aşmadan yönetir.
license: MIT
compatibility: Windows 10/11; Python 3.11-3.13; uv; Zotero 8/9; Jilin Üniversitesi rotaları kuruma özgüdür.
metadata:
  author: LitLib contributors
  version: "0.3.0"
---

# LitLib literatür iş akışı

## Amaç

Bu skill'i üç parçalı bir sistemin yürütme politikası olarak kullanın:

1. **Bu skill** hangi yeteneğin kullanılacağına karar verir, uyum kurallarını ve insan
   checkpoint'lerini uygular, hataları yorumlar ve neyin doğrulandığını kaydeder.
2. **LitLib MCP** metadata, görev durumu, PDF yolları, Zotero koleksiyonları ve sayfalı PDF
   metni için belirlenimci, yerel, salt-okur sorgu yapar.
3. **ZotSeek MCP** ayrıca tutulan bir Zotero indeksi üzerinde yerel semantik ya da hibrit
   arama yapar.

Tüm değişiklikler `litlib` CLI ile ya da insanın açık bir Zotero işlemiyle yapılır. MCP
araçları makale indirmez, görev durumunu değiştirmez, öğe içe aktarmaz ya da Zotero
kütüphanesini değiştirmez.

## Abartılı iddiada bulunmayın

LitLib bir edinme ve yerel kütüphane iş akışıdır, eksiksiz bir bibliyografik arama
veritabanı değildir. Konu araması için önce Agent'a kurulu akademik veritabanı yeteneğini
kullanın (örneğin PubMed, Crossref, OpenAlex, Semantic Scholar ya da onaylı başka bir akademik
kaynak), DOI/PMID ve kaynak bilgisini koruyun, sonra tanımlayıcıları LitLib'e verin. Akademik
veritabanı aracı varken genel web aramasını onun yerine kullanmayın.

ZotSeek harici bir Zotero eklentisidir, LitLib'le birlikte gelen kod değildir. MCP'si yalnız
etkin embedding modelinin kapsadığı öğelerde arama yapabilir. Semantik benzerlik bir arama
kanıtıdır; bir makalenin bilimsel bir iddiayı desteklediğinin kanıtı değildir.

## Kurulumu bulun ve inceleyin

Başka bir makinede `D:\op\projects\literature-library` yolunu asla varsaymayın. Projeyi şu
sırayla çözün:

1. Kullanıcının verdiği proje yolu.
2. Ayarlıysa `LITLIB_ROOT`.
3. Proje adı `litlib` olan `pyproject.toml`'u içeren depo.
4. `PATH` üzerinde kurulu bir `litlib` çalıştırılabiliri.

Yazan bir iş akışından önce şunları çalıştırın:

```powershell
litlib --version
litlib doctor
litlib status
```

Örneklerde okunabilirlik için `litlib` kullanılır. Etkinleştirilmemiş bir kaynak klonunda
karşılığı olan `uv run litlib ...` komutunu çalıştırın; Windows'ta MCP istemcileri, güncelleme
sırasında console-script sarmalayıcısı kilitlenmesin diye mutlak `.venv\Scripts\python.exe`
yolunu `-m litlib.cli mcp` argümanlarıyla kullanmalıdır.

Çalıştırılabilir dosya yoksa [references/CLIENT_SETUP.md](references/CLIENT_SETUP.md)
belgesini okuyun. Neyin değişeceğini kullanıcıya söylemeden paket ya da eklenti kurmayın,
Zotero ayarlarını değiştirmeyin, kimlik bilgisi saklamayın ya da Agent'ın MCP yapılandırmasını
değiştirmeyin.

## İsteği sınıflandırın

### Mevcut kütüphanede arama

1. ZotSeek varsa önce `zotseek_index_status` çağırın.
2. Kavramlar için `zotseek_search`'ü `hybrid` modunda kullanın. Yalnız İngilizce içerikli bir
   kütüphanede başka dilden İngilizceye arama zayıfsa İngilizce sorgu kullanın.
3. Tam başlık, DOI, yazar ya da görev sorgusu için `library_search_metadata` kullanın.
4. `library_get_pdf_path` ya da `library_get_fulltext`'i tam bir DOI ya da item key ile
   kullanın. Geniş sorgular belirsiz olabilir ve sessizce ilk makaleyi seçmemelidir.
5. Yalnız gereken sayfaları ya da karakter penceresini okuyun. Kullanıcı açıkça tüm belgenin
   işlenmesini istemedikçe bir makalenin tamamını Agent bağlamına koymayın.

### Bir konuda yeni makaleler bulma

1. Agent'ın akademik arama yeteneğiyle bir akademik veritabanında arayın.
2. DOI ya da PMID'yi, kaynak veritabanını, sorgu tarihini ve belirsizliği döndürün ve saklayın.
3. Edinmeden önce tanımlayıcıları tekilleştirin.
4. Aşağıdaki edinme iş akışıyla devam edin.

### Tek bir DOI edinme

Tek giriş noktasını kullanın. Gerekirse görev oluşturur, metadata'yı çözümler, indirir,
doğrular ve dosyayı kaydeder:

```powershell
litlib download 10.xxxx/example
litlib verify
```

Komut, `--overwrite` açıkça verilmedikçe mevcut bir hedefin üzerine yazmayı reddeder. PDF
dosyası olsa bile kayıt başarısızlığı bir başarısızlıktır; başarı iddia etmek yerine dosyayı
koruyun ve görev veritabanını inceleyin.

### Toplu edinme

```powershell
litlib queue add --file examples/input.example.csv
litlib run --stage fetch-metadata
litlib run --stage oa
litlib status --verbose
```

Kurum erişimine yalnız `REQUIRES_INST` durumundaki görevler geçer. Kurum partilerini en fazla
10 makale, eşzamanlılık 1 ve 8-15 saniye beklemeyle tutun:

```powershell
litlib inst check-cred
litlib inst open
litlib run --stage inst --access-mode campus
litlib inst close
```

`offcampus`'u yalnız kullanıcı kampüs dışındaysa ve yetkili JLU kimlik bilgileri varsa
kullanın. Ağ durumu bilinmiyorsa `auto` kullanın. Bir hatayı teşhis etmeden önce
[references/DECISION_TREE.md](references/DECISION_TREE.md), bir yayıncı rotasını
değiştirmeden önce [references/SITE_RECIPES.md](references/SITE_RECIPES.md) belgesini okuyun.

### CNKI içeriği edinme

CNKI ayrı bir tarayıcı akışıdır. Arama, indirme doğrulaması geçilmeden de çalışabilir;
aramanın başarılı olmasını indirme yetkisi saymayın.

```powershell
litlib inst open
litlib cnki open
litlib cnki search "<arama terimi>" --limit 10
litlib cnki download "<ayrıntı-sayfası-url>" --output "<kayıt-yolu>"
litlib inst close
```

`bar.cnki.net` bir kaydırıcı gösterirse `HUMAN_REQUIRED` döndürün ve kullanıcıdan bunu görünür
özel tarayıcıda tamamlamasını isteyin. Kaydırıcıyı asla otomatikleştirmeyin ya da başkasına
yaptırmayın. CAJ, PDF değildir; doğru uzantıyı koruyun ve CAJ'ı PDF doğrulamasından
geçirmeyin.

## PDF başarı sözleşmesi

Bir indirme ancak ilgili tüm kontrollerden geçerse başarılıdır:

1. Dosya `%PDF-` ile başlar.
2. Dosyanın sonuna yakın `%%EOF` bulunur; `206 Partial Content` parçası yetmez.
3. `pypdf` en az bir sayfayı ayrıştırır.
4. Beklenen DOI, satır sonlarıyla bölünmüş DOI metni dahil, çıkarılan ilk üç sayfada geçer;
   1. sayfada farklı bir DOI kesin uyumsuzluktur.
5. İlk üç sayfa dosyayı ek/destekleyici materyal olarak tanımlamaz.
6. Sonraki doğrulamada SHA-256 görev kaydıyla eşleşir.
7. Görev veritabanına kayıt başarılı olmuştur.

Teslimden önce `litlib verify` çalıştırın. Sıfır öğeli bir doğrulama başarı değildir.

## Zotero içe aktarma sözleşmesi

Desteklenen yazma yolu bilerek insan onayına bağlanmıştır:

```powershell
litlib proposal --doi-file <batch.csv>
# Kullanıcı üretilen RIS'i Zotero'ya aktarır ve koleksiyonu/öğeleri kontrol eder.
litlib review --doi-file <batch.csv>
litlib import --lookup --batch <name> --doi-file <batch.csv>
```

`IMPORTED`, LitLib'in tam DOI ile (ya da yedek olarak normalleştirilmiş tam başlıkla) tam
olarak bir Zotero parent item'ı bulduğu, boş olmayan bir Zotero item key aldığı ve var olan
bir PDF ekini çözümlediği anlamına gelir. Zotero kapalıysa, tam eşleşen öğe yoksa, birden
fazla eşleşme varsa ya da PDF eki eksikse görevi içe aktarılmış olarak işaretlemeyin.

`zotero.sqlite`'ı asla doğrudan düzenlemeyin. Keyfi kod çalıştıran bir Zotero köprüsü
kurmayın. RIS içe aktarma dışındaki Zotero kütüphanesi yazımları ayrı kullanıcı onayı ve
güvenlik incelemesi gerektirir.

## İnsan checkpoint'leri ve durma koşulları

Şunlardan biri olursa durun ve kullanıcıya sorun:

- CAPTCHA, Turnstile, kaydırıcı, OTP ya da görünür bir insan doğrulama sayfası.
- İlk kez kimlik bilgisi saklama, eklenti kurulumu, Zotero yapılandırması ya da MCP
  yapılandırma değişikliği.
- Kabulü hukuki/hesap sonuçları olan kullanım koşulları ya da öznitelik paylaşımı sayfası.
- Mevcut bir çıktının üzerine yazılacak olması.
- Mevcut tek nesnenin CAJ ya da HTML olması ve istenen teslimatın PDF olması.

Şu durumlarda otomatik denemeleri durdurun ve nedenini raporlayın:

- Sayfa açıkça satın alma, kiralama, `Buy Protocol` sunuyor ya da başka biçimde yetkili PDF
  hakkı olmadığını gösteriyor.
- Kurumun kimlik sağlayıcısı servis sağlayıcıyı desteklenmiyor diye reddediyor.
- Tekrarlanan `429` ya da yayıncı hız sınırı oluşuyor. Soğumasını bekleyin; atlatmak için
  kimlik, profil ya da proxy değiştirmeyin.
- Bir rota ödeme duvarı, CAPTCHA, teknik erişim denetimi ya da lisansı aşmayı gerektiriyor.

## Hata yönetimi

`litlib status --attempts <task-id>` kullanın ve yeniden denemeden önce hatayı
sınıflandırın:

- `HUMAN_REQUIRED`: görünür doğrulama; kullanıcıyı bekleyin, sonra
  `litlib queue recover --paused`.
- `RATE_LIMITED`: durun ve soğumayı bekleyin; ancak makul bir süreden sonra kurtarın.
- `PAYWALLED`: açık satın alma/kiralama/yetki yok nedeniyle durma; bir insan erişim durumunu
  LitLib dışında değiştirip yeni bir görev oluşturmadıkça kesin son durumdur.
- `REQUIRES_INST`: OA adayları başarısız oldu ama yetkili bir kurum rotası kalmış olabilir.
- `FAILED`: metadata'yı, tekilleştirme çakışmasını, dosya kimliğini ya da iç istisnayı
  inceleyin.
- PDF gibi görünen bir URL'den HTML gelmesi: kimlik doğrulama, anti-bot yanıtı, açılış sayfası
  yönlendirmesi ya da yalnız HTML yetkisini teşhis edin. HTML'i `.pdf` olarak yeniden
  adlandırmayın.

CLI çıkış kodu belirleyicidir: `0` başarı, `1` çalışma zamanı/doğrulama/sonuç yok hatası,
`2` kullanım hatası ya da karşılanmamış ön koşul, `3` CNKI insan checkpoint'i. Çıkış kodu
sıfır değilken yalnız konsol metnine bakarak tamamlandı demeyin.

## Raporlama

Her parti için şunları raporlayın:

- İstenen, çözümlenen, indirilen, doğrulanan, içe aktarılan, insan gerektiren, hız sınırına
  takılan ve ödeme duvarına takılan sayıları.
- Her makalenin DOI/PMID'si ve kaynağı.
- Her başarılı PDF için kullanılan rota.
- `verified`, `inferred` ve `unverified` davranış arasında açık ayrım.
- Kullanıcının hâlâ tamamlaması gereken canlı tarayıcı adımları.

Kimlik bilgilerini, çerezleri, WebVPN host token'larını, API anahtarlarını, imzalı PDF
URL'lerini ya da tam query dizelerini açığa çıkarmayın. PDF'leri, çıkarılmış tam metni,
Zotero veritabanlarını, tarayıcı profillerini, günlükleri, XPI dosyalarını ya da çalışma
zamanı durumunu commit etmeyin.

## Kişisel deneyim (kendini geliştiren)

Depodaki tarifler kodla birlikte gelen salt-okur temel çizgidir. Her kullanıcının ayrıca
otomatik büyüyen yerel, özel bir deneyim kütüphanesi (`litlib learn`) vardır:

- **Konum**: `<LITLIB_RUNTIME_ROOT>\experience\experiences.json` (varsayılan
  `D:\LitLibRuntime\experience\experiences.json`). Git'e asla commit edilmez.
- **Otomatik öğrenme**: işe yarayan bir rotayla doğrulanmış başarılı bir kurum ya da CNKI
  indirmesinden sonra LitLib yerelde `domain + route + url_pattern + doi_prefix` kaydeder.
  PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED / FAILED asla başarı olarak kaydedilmez.
- **Elle öğrenme**: bir Agent ya da kullanıcı
  `litlib learn add --domain <alan-adı> --route <rota> --note "<ne işe yaradı>"` ile gözlem
  ekleyebilir.
- **Yeni bir siteyi denemeden önce okuyun**: önce `litlib learn list --domain <site>` ya da
  `litlib learn export` çalıştırın. Çeliştiklerinde kişisel deneyim kanonik
  `SITE_RECIPES.md`'den önce gelir.
- **Kaydedilen tüm içerik maskelenir** (URL'lerden query token'ları atılır; WebVPN token'ları,
  çerezler ve kimlik bilgileri gizlenir). Kişisel deneyim kullanıcıya ve makineye özeldir;
  depo üzerinden paylaşılmaz.
- `litlib learn list | add | remove | export` ile yönetin. Hatalı kaydı temizlemek için:
  `litlib learn remove <id>`.

Kişisel deneyim yalnız bir arama yardımıdır. Ödeme duvarını, CAPTCHA'yı, hız sınırını ya da
desteklenmeyen CARSI servis sağlayıcısını aşmaya asla yetki vermez.

## UniProt ve enzim verisi iş akışı

Kullanıcı UniProt accession'ları verip enzim/selülaz ölçümleri istediğinde edinmeyi veri
çıkarımından ayrı tutun:

1. Kanonik diziyi, organizmayı, enzim metadata'sını ve bağlantılı DOI/PMID/PMCID
   referanslarını saklamak için `litlib uniprot <accession> --output <json>` çalıştırın.
   `--queue`, accession çıktısı incelendikten sonra bu tanımlayıcıları LitLib görev kuyruğuna
   ekleyebilir.
2. Ana makaleleri olağan OA/kurum iş akışıyla edinip doğrulayın. Makale okunmadan bir UniProt
   atfının aktivite ölçümü içerdiğini varsaymayın.
3. `litlib evidence scan <doğrulanmış.pdf>` çalıştırın. Bu yalnız ön değerlendirmedir: hedef
   alan sayfalarını, şekil/tablo referanslarını, ek materyal referanslarını ve eksik metin
   kanıtını raporlar. Bir görselde değer olmadığını kanıtlamaz.
4. Makale ek bilgilere ya da kaynak veriye işaret ediyorsa
   `litlib supplement discover <makale-url>` çalıştırın ve yalnız gereken dosyayı indirin.
   Dosyalar ayrı olarak `staging/supplements` altında saklanır ve maskelenmiş bir manifeste
   kaydedilir.
5. Enzim ölçümlerini selülaz şemasıyla JSONL olarak saklayın. Bir kayıtta eksik alan olabilir
   ama ham birimler, normalleştirilmiş substrat, deney koşulları, DOI ve sayfa/tablo/şekil/ek
   materyal kanıt konumları korunmalıdır.
6. Veriyi kullanmadan önce `litlib cellulase validate <measurements.jsonl>`, maksimumları
   seçmek için `litlib cellulase maxima <measurements.jsonl> --output <maxima.jsonl>`
   çalıştırın.

Varsayılan maksimum kuralı: yalnız aynı yapı dizisi, normalleştirilmiş substrat, metrik
ailesi, standartlaştırılmış birim ve assay method içinde karşılaştırın. Bu yüzden aynı enzimin
farklı substratlar için birden fazla maksimum kaydı olabilir. `U/mL`, `U/mg`, bağıl aktivite,
`kcat`, `Km` ve `kcat/Km`'yi tek bir sıralamada birleştirmeyin. Aynı deneyde mutlak bir
dayanağı olmayan bağıl aktivite ayrı bir aday kayıt olarak kalır; asla sessizce dönüştürülmez.

Mutantlar ve kesik yapılar yalnız deneysel yapı açıkça verilmişse ya da dizisi tam bir
referans dizisi ile belirsiz olmayan mutasyonlar ve kalıntı sınırlarından yeniden
kurulabiliyorsa uygundur. Aksi halde yapıyı çözümlenmemiş olarak işaretleyin ve resmi eğitim
kümesinin dışında tutun.

Yalnız görselde bulunan değerler için önce metin, tablo ve kaynak veri rotalarını kullanın.
Yalnız kanıt ön değerlendirmesinin işaretlediği sayfalar için küçük bir görsel inceleme
kuyruğu oluşturun. Sayısallaştırılmış bir değer `digitized` olarak işaretlenmelidir; gerçek
değer yoksa kesin bir hata yüzdesi iddia etmek yerine tekrarlanabilirlik/belirsizlik
raporlayın. Harici çok kipli modeli her makalenin tamamı için değil, yalnız seçilen
kırpım/panel için kullanın.

## Referanslar

- [Karar ağacı ve genelleştirilmiş teşhis](references/DECISION_TREE.md)
- [Doğrulanmış yayıncı ve veritabanı tarifleri](references/SITE_RECIPES.md)
- [Kurulum, Zotero, ZotSeek ve MCP istemci yapılandırması](references/CLIENT_SETUP.md)
