# Üçüncü taraf bileşenler

## Çalışma zamanı bağımlılıkları

Python bağımlılıkları `pyproject.toml` ve `uv.lock` içinde tanımlanır ve kilitlenir.
Upstream lisansları kendilerine aittir; deponun MIT lisansı onları yeniden lisanslamaz.
Çalışma zamanında PDF ayrıştırma için BSD-3-Clause lisanslı `pypdf` kullanılır; testler
sentetik PDF'leri BSD lisanslı ReportLab ile üretir. AGPL/ticari dağıtım belirsizliğinden
kaçınmak için PyMuPDF herkese açık sürümden önce kaldırıldı. Sürüm CI'ı, binary yayımlamadan
önce yine de otomatik bir bağımlılık lisans raporu eklemelidir.

Kilitli Python 3.13 geliştirme ortamında 2026-08-06'da yapılan `pip-licenses` denetimi MIT,
BSD, Apache-2.0, PSF, MIT-CMU ve MPL-2.0 (`certifi`) paketleri buldu; GPL/AGPL çalışma
zamanı bağımlılığı bulmadı. `uv.lock` her değiştiğinde bu denetimi yeniden çalıştırın; paket
metadata'sı incelenecek bir kanıttır, yetkili upstream lisans metninin yerini tutmaz.

## İncelenen projeler ve eklentiler

| Bileşen | Upstream iddiası / gözlenen lisans | LitLib'de kullanımı | Dağıtım durumu |
|---|---|---|---|
| `zju-paper-fetcher` | MIT | Yalnız CDP/WebVPN tasarım referansı | Kopyalanan paket/binary yok |
| `zju-literature-downloader` | MIT | Yalnız iş akışı referansı | Kopyalanan paket/binary yok |
| `pygetpapers` | Apache-2.0 | Europe PMC iş akışı referansı | Paketlenmedi |
| `cli-anything-zotero` v1.2.1 anlık görüntüsü | Apache-2.0 | Yalnız güvenlik değerlendirmesi | Reddedildi; kurulmadı/paketlenmedi |
| ZotSeek | README MIT diyor; depo lisansı aşağıda açıklandığı gibi belirsiz | Harici semantik MCP | Upstream sürümüne bağlantı; XPI asla paketlenmez |

## ZotSeek lisans kontrolü

2026-08-06'da `introfini/ZotSeek`'e karşı kontrol edildi:

- Upstream README `MIT License - see LICENSE` diyor.
- `https://raw.githubusercontent.com/introfini/ZotSeek/main/LICENSE` 404 döndürdü.
- GitHub depo API'si `license: null` döndürdü.
- Yerelde indirilen XPI, yeniden dağıtıma uygun bir lisans dosyası içermiyordu.

Sonuç: kullanıcılar ZotSeek'i upstream yazarının koşullarına göre doğrudan upstream
Releases'tan kurabilir; ancak upstream yetkili bir lisans dosyası ekleyene ya da gösterene
kadar LitLib XPI'ı yeniden dağıtmamalı ve binary'nin doğrulanmış MIT olduğunu
söylememelidir.

## Reddedilen Zotero köprüsü

Değerlendirilen `cli-anything-zotero` köprüsü benimsenmedi; çünkü anlık görüntüsü, gönderilen
JavaScript'i kimlik doğrulama sınırı olmadan çalıştıran yerel bir HTTP uç noktası açıyordu ve
yardımcı kodu `zotero.sqlite`'ı doğrudan değiştiriyordu. İkisi de LitLib'in tehdit modelini
ihlal eder.

Desteklenen entegrasyon şöyle kalır:

- Zotero Local API üzerinden okuma.
- `L1` ek yollarıyla, insan onayına bağlı RIS içe aktarma.
- Salt-okur Local API ile içe aktarma sonrası doğrulama.
- Doğrudan SQLite yazımı ve keyfi kod köprüsü yok.

## Yayıncı içeriği

Yayıncı sayfaları, PDF dosyaları, metadata yanıtları ve CNKI CAJ dosyaları üçüncü taraf
kaynak bağımlılıkları değildir ve asla açık deponun parçası olmaz. Test fixture'ları sentetik
ya da korumalı tam metni yeniden üretmeyen asgari metadata temsilleri olmalıdır.
