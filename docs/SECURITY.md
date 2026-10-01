# Güvenlik ve gizlilik

## Kapsam

LitLib kurum kimlik bilgileri, tarayıcı oturumları, yerel makaleler ve bibliyografik
metadata ile çalışır. Bir hata bir hesabı, telif korumalı tam metni ya da kullanıcının
araştırma ilgi alanlarını açığa çıkarabilir. Bu yüzden güvenlik iddialarında varsayılan
davranış ile isteğe bağlı davranış ayrı tutulur.

## Gizli bilgiler

- JLU kullanıcı adı/parolası geçerli kullanıcı altında Windows Credential Manager ile
  saklanır.
- Parola yalnız HTTPS üzerinden, açıkça izin listesine alınmış JLU IdP host adlarına
  gönderilir.
- Kullanım koşulları ve öznitelik paylaşımı seçimleri algılanır ama asla otomatik kabul
  edilmez; bir checkpoint zaman aşımına uğrarsa görünür sekme kullanıcı için korunur.
- `.env` gizli olmayan çalışma ayarları ve bir iletişim e-postası içindir. İçine parola, çerez,
  VPN token'ı, Zotero parolası ya da sağlayıcı API anahtarı koymayın.
- WebVPN host token'ları ve oturum dosyaları çalışma zamanı durumudur, Git dışında tutulur.
- `litlib inst tokens` token değerlerini değil, yalnız var olup olmadıklarını ve
  uzunluklarını gösterir.

Tarayıcı çerezleri normalde özel Chrome profilinin içinde kalır. İsteğe bağlı
`LITLIB_EXPORT_SESSION_COOKIES=1`, geçerli Windows kullanıcısına bağlı DPAPI ile şifreli bir
yedek saklar; varsayılan olarak kapalıdır ve oluşan `.bin` dosyasını Git yok sayar.

## Yerel servisler

- Chrome DevTools Protocol yalnız `127.0.0.1`'e bağlanır.
- Zotero Local API ve ZotSeek MCP loopback'i (`127.0.0.1:23119`) dinler.
- LitLib MCP stdio'dur, ağ üzerinden dinlemez.
- Bu servisleri herkese açık port yönlendirmesi ya da kimlik doğrulamasız bir tünelle dışarı
  açmayın.

## Salt-okur iddiaları

LitLib MCP dosya sistemi/görev/kütüphane açısından salt-okurdur: mevcut SQLite'ı
`mode=ro` ile açar, `query_only` kullanır, tam metin önbelleği yazmayı kapatır ve CLI
günlük/dizin başlatmasını atlar.

ZotSeek MCP çağrıları upstream davranışına göre salt-okurdur. ZotSeek eklentisi elle ya da
otomatik indeksleme ile `zotseek.sqlite`'ı ayrıca güncelleyebilir. İndeks türetilmiş veridir,
Zotero'nun doğruluk kaynağı değildir.

## Günlükler ve denetim

- Dosya günlükleri 20 MB'ta döndürülür, beş yedek tutulur.
- Logger mesajlarından URL query dizeleri ve yaygın key/token/password alanları çıkarılır.
- Rota denemesi kayıtları SQLite'a yazılmadan önce URL query dizelerini, JLU WebVPN host
  token'larını ve gizli bilgi benzeri hata alanlarını ayrıca maskeler.
- Yeniden üretilebilirlik için DOI ve gizli olmayan yol parçaları kalabilir.

Bir issue'ya ham tarayıcı ağ dışa aktarımlarını, HAR dosyalarını, çerezleri, imzalı PDF
URL'lerini ya da maskelenmemiş rota veritabanlarını yapıştırmayın.

## Tam metin ve telif

`.gitignore`; PDF, CAJ, XPI, veritabanları, çıkarılmış tam metin, output, staging, state,
günlükler, tarayıcı profilleri ve `.env` dosyalarını dışarıda bırakır. Katkıcılar yine de
`git status`'u incelemelidir; bir ignore kuralı hak incelemesinin yerini tutmaz.

MIT lisansı yalnız LitLib'in kodu ve belgeleri için geçerlidir. İndirilen makaleleri, yayıncı
HTML'ini ya da lisanslı Zotero eklerini yeniden dağıtma hakkı vermez.

## Erişim denetimi sınırı

LitLib; CAPTCHA, Turnstile, kaydırıcılar, OTP, ödeme duvarları, satın alma/kiralama
sayfaları, desteklenmeyen CARSI servis sağlayıcıları ya da hız sınırlarını aşmaz. Kurum
erişimi gözetimlidir, düşük eşzamanlılıkla çalışır ve kullanıcının kendi yetkisini kullanır.
Bir doğrulama çıkarsa kullanıcı için durulur; yalnız satın alınabilen bir öğede işlem biter.

## Depolama politikası

`litlib doctor` yapılandırılmış proje/çalışma zamanı yollarını raporlar.
`LITLIB_REQUIRE_D_DRIVE=1`, açıkça verilen tek makale ve CNKI hedefleri için D sürücüsüne
çıktıyı zorunlu kılar; büyük çıktı üreten iç yollar proje/çalışma zamanı yapılandırmasından
türetilir. Bu bir yerel depolama politikasıdır, genel bir güvenlik gereksinimi değildir. D:
sürücüsü olmayanlar bunu `0` yapıp başka bir özel disk seçmelidir. Wheel/global kurulumlar,
`LITLIB_ROOT` yapılandırılmadıkça platformun kullanıcı verisi çalışma alanını kullanır;
yazılabilir durumu asla `site-packages`'tan türetmez.

## Güvenlik açığı bildirme

Depo herkese açılmadan önce bakımcıya özel olarak bildirin. GitHub'da yayımlandıktan sonra
GitHub Private Vulnerability Reporting'i açın; kimlik bilgisi, yerel servis, keyfi dosya, kod
çalıştırma ya da oturum sızıntısı sorunları için açık issue yerine onu kullanın.
