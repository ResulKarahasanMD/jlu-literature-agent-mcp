# Yayıncı ve veritabanı tarifleri

Bu kayıtlar tek bir Windows/JLU kurulumunda yapılan gözetimli testlerden gelir. Tarihler
yerel doğrulama oturumunu gösterir, kalıcı bir yayıncı garantisi değildir. Büyük site
değişikliklerinden sonra yeniden kontrol edin.

Etiketler:

- **Verified (doğrulanmış):** dosya ve DOI kontrollerinden geçen tam bir PDF ile gözlendi.
- **Observed restriction (gözlenen kısıt):** hata/yetki durumu doğrudan gözlendi.
- **Inferred (çıkarım):** canlı doğrulama gerektiren makul bir sonraki deneme.

## Wiley (`10.1002`, `onlinelibrary.wiley.com`)

**Verified, 2026-08-05.** Makale tam erişim gösteriyordu, ama `/doi/epdf/{doi}`'yi doğrudan
almak HTML döndürdü ve imzasız bir `/doi/pdfdirect/{doi}` `403` döndürebiliyordu.

Başarılı rota:

1. Kimliği doğrulanmış tarayıcıyla `/doi/epdf/{doi}`'ye gidin.
2. `performance.getEntriesByType('resource')`'u inceleyin.
3. `/doi/pdfdirect/?hmac=...` içeren kaynağı bulun.
4. Bu imzalı URL'i aynı Wiley sayfa bağlamından fetch edin.
5. Yalnız tam PDF doğrulamasından sonra kaydedin.

Kritik hata: CDP `Network.getResponseBody` yaklaşık 262 KB'lık bir görüntüleyici bayt aralığı
yanıtı döndürdü. PDF gibi başlıyordu ama sıfır sayfa olarak ayrıştırıldı ve dosyanın tam sonu
yoktu. Bir PDF yanıt parçasını tam bir PDF'le bir tutmayın.

Genel çıkarım: görüntüleyici tabanlı sitelerde çerez eklemeden ya da user agent değiştirmeden
önce imzalı performans kaynaklarını ve aralık semantiğini inceleyin.

## MDPI (`10.3390`, `www.mdpi.com`)

**Verified, 2026-08-05.** Güncel makale sayfası `a.UD_ArticlePDF` öğesini sunuyor; href'i eski
`.pdf` kalıbı yerine `/pdf?version=...` ile bitebiliyor. Aynı kökenli fetch tam bir OA PDF'i
döndürdü.

Yeni/sık kullanılan bir oturumda Cloudflare `Access Denied` gözlendi. Test edilen dergi/DOI
biçimleri için `mdpi-res.com` üzerindeki herkese açık statik kaynak çalıştı:

```text
https://mdpi-res.com/d_attachment/{journal}/{journal}-{volume:02d}-{article:05d}/article_deploy/{journal}-{volume:02d}-{article:05d}.pdf
```

Mevcut kod kısa DOI kalıbını tanır ve test edilen `antib` ile `biom` önekleri için açık slug
eşlemeleri içerir. Diğer dergiler için statik URL kurmayı **inferred** sayın ve dönen PDF'teki
DOI'yi doğrulayın. Her MDPI DOI'sinin cilt/makale numarasını aynı biçimde kodladığını
varsaymayın.

## Elsevier / ScienceDirect (`10.1016`, `sciencedirect.com`)

**Verified platform behavior, 2026-08-05.** Yetkili bir makale sayfası
`.../pdfft?md5=...&pid=...-main.pdf` benzeri bir `View PDF` isteği sunar. Oturuma bağlıdır ve
kimliği doğrulanmış sayfa bağlamından istenmelidir.

Gözlenen kısıtlar:

- `/user/institution/login` Cloudflare Turnstile gösterebilir.
- Bazı otomatik oturumlarda görünür doğrulama bileşeni düzgün işlenmedi.
- Kurum girişinden sonra erişim metadata'sını okumadan ya da PDF'e tıklamadan önce makaleyi
  yeniden yükleyin ya da ona geri dönün.

Turnstile'da görünür özel tarayıcıda kullanıcıyı bekleyin. WebVPN, ağ geçidinin ağ/TLS parmak
izi farklı olduğu için katı Cloudflare sitelerinde başarısız olabilir; doğrudan tarayıcıda
kurum girişi tercih edilen yedek yoldur.

## Taylor & Francis (`10.1080`, `tandfonline.com`)

**Verified WAYF behavior and observed restriction, 2026-08-05.** Platform, kampüs bağlantısı
görünür olsa bile şu kurum akışını gerektirdi:

1. `Access through your institution` / Shibboleth `ssostart` işlemine tıklayın.
2. WAYF sayfasında önce `select#shib-search--fed` içinde CARSI/CERNET federasyonunu seçin.
3. Yalnız `jilin` arayın, sonra Jilin University'yi seçin.
4. JLU kimlik doğrulamasını tamamlayın; araç kimlik bilgilerini yalnız izin listesindeki bir
   HTTPS JLU IdP'sinde doldurabilir/gönderebilir.
5. Beyan/koşullar sayfasını elle inceleyip karar verin. Öznitelik paylaşımı sayfasında
   sayfanın alt kısmındaki `接受` ("Kabul et") düğmesini bulacak kadar kaydırın/metni okuyun.
   400 karakterlik gövde örneği onu kaçırdı; 2000+ karakter işe yaradı.

DOI `10.1080/17460441.2025.2599178` için kimliği doğrulanmış öğe HTML sundu ama kurum
yetkisiyle bir PDF sunmadı. `dc.Format` `text/HTML` bildirdi ve sayfa `$104 / 48 hours` satın
alma teklif etti. Bu **öğeye özgü gözlenen bir kısıttır**; tüm T&F makalelerinin yalnız HTML
olduğunun kanıtı değildir. Açık bir yalnız satın alma durumunda durun.

## Oxford University Press (`10.1093`, `academic.oup.com`)

**Verified, 2026-08-05.** Makale sayfasında gezinip ardından PDF işlemi ve yetkili aynı
kökenli/CDN isteği tam bir PDF üretti. OUP Silverchair altyapısını kullanır; son PDF bir
CDN'de olabilir, bu yüzden kalıcı bir CDN URL'i kurmak yerine bağlantıyı sayfadan yakalayın.

## Springer Nature (`10.1007`, `link.springer.com`)

**Mixed (karışık).** Standart OA ya da yetkili makaleler `/content/pdf/{doi}.pdf`
kullanabilir ve yine de doğrulamadan geçmelidir. Test edilen bir *Methods in Molecular
Biology* protokol bölümü `Buy Protocol` gösterdi ve yetkili bir PDF sunmadı. İçerik türü
önemlidir: belirli bölüm yalnız satın alınabiliyorsa genel uç noktayı tekrar tekrar denemek
yerine durun.

## Frontiers (`10.3389`)

**Verified OA behavior, 2026-08-05.** Doğrudan OA edinme çalıştı. Açılış URL'leri ve CDN
yolları değişebileceği için OA metadata'sını ve tam PDF doğrulamasını kullanmaya devam edin.

## CNKI (`cnki.net`, `bar.cnki.net`)

**Verified search; human checkpoint for download, 2026-08-05.** Gizli doğrulama DOM'u yok
sayıldıktan sonra arama çalıştı. PDF/CAJ indirme bir `bar.cnki.net` kaydırıcısını tetikledi.
Görünür doğrulama tamamlanmadan yapılan doğrudan fetch `来源应用不正确(01)` ("kaynak uygulama
hatalı (01)") döndürdü.

Gereken yanıt:

1. Özel tarayıcıyı görünür tutun.
2. Kullanıcıdan kaydırıcıyı tamamlamasını isteyin.
3. O tarayıcı oturumunu yeniden kullanın.
4. Asıl teslimatın PDF mi CAJ mı olduğunu algılayın.

CAJ baytlarını asla `.pdf` uzantısıyla kaydetmeyin. Mevcut LitLib doğrulama hattı yalnız PDF
kabul eder; CAJ dönüştürme/okuma bu uygulamanın kapsamı dışındadır.

Kampüs erişimi test edildi. `litlib cnki login-carsi` var, ama kampüs dışı CNKI CARSI bu proje
oturumunda **unverified** kaldı.

## ACS (`10.1021`, `pubs.acs.org`)

**Observed restriction, 2026-08-05.** JLU CARSI yolu, web giriş servisinin isteği
desteklemediğini söyleyen bir kimlik sağlayıcı sayfası döndürdü. Bu, aşılacak bir CAPTCHA değil,
bir servis sağlayıcı/federasyon yapılandırma sorunudur. O CARSI rotasını durdurun. Kampüs
IP'si ya da meşru bir WebVPN rotası varsa ayrıca test edilebilir.

## Royal Society of Chemistry (`10.1039`, `pubs.rsc.org`)

**Observed restriction, 2026-08-05.** Özel tarayıcı profili tekrar tekrar
`429 Too Many Requests` aldı. Kaynak düşük öncelikli olduğu için proje atlatmaya çalışmadı.
`RATE_LIMITED` işaretleyin, gereksiz sekmeleri kapatın, soğumayı bekleyin ve daha sonra tek
bir DOI ile yeniden test edin.

## Genel kurum sayfaları

JLU rotası girişten sonra birkaç durumla karşılaştı. LitLib bu sayfaları algılar ama kullanıcı
adına hukuki koşulları ya da kalıcı öznitelik paylaşımını kabul etmez:

- Açık onay gerektiren koşullar/beyan sayfası.
- `接受` ("Kabul et") gerektiren öznitelik paylaşımı/bilgi yayımlama sayfası.
- `we now know you're from...` gibi Elsevier kişiselleştirme sayfası.
- Kimlik bilgisi formunu göstermeden geri yönlendiren, hatırlanmış yayıncı oturumları.

Bunları hem URL hem de yeterince uzun görünür gövde metniyle algılayın. Kullanıcı adı/parola
alanlarının olmamasını başarısızlık saymayın; önce oturumun zaten giriş sonrası bir sayfaya ya
da yayıncı sayfasına geçip geçmediğini belirleyin.

## WebVPN

JLU WebVPN bir hedefi kabaca şöyle yeniden yazar:

```text
https://vpn.jlu.edu.cn/https/{publisher-host-token}/{path}
```

Host token'ı ve VPN çerezleri oturum bilgisidir. Onları asla yayımlamayın ya da günlüğe
yazmayın. Token, kullanıcının yetkili portal oturumundan öğrenilmelidir ve bayatlayabilir.
Eksik token ya da bilet WebVPN rotasını atlatmalı ve uygun olduğunda kurum girişiyle devam
edilmelidir.

WebVPN her yerde daha iyi değildir: katı anti-bot/CDN platformları ağ geçidini reddedebilir.
Onu tüm yayıncılar için global bir proxy olarak değil, rotalardan biri olarak kullanın.
