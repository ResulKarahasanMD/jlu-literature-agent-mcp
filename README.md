# LitLib for JLU

Jilin Üniversitesi (JLU) öğrencileri için Agent'a hazır bir literatür edinme ve yerel bilgi
tabanı iş akışı. LitLib makaleleri önce yasal açık erişim (OA) kaynaklarından alır; açık
olmayan literatüre yalnız kullanıcının erişim hakkı varsa kampüs ağı, CARSI/kurum girişi ya
da JLU WebVPN üzerinden küçük partilerle erişir. Tek ana literatür kütüphanesi Zotero'dur.

> Güncel durum: `0.3.0 alpha`. Metadata, OA, PDF doğrulama, görev durumu, RIS içe aktarma
> ve LitLib MCP için otomatik testler var; yayıncı ve CNKI rotaları canlı sayfalara bağlı
> olduğundan yalnız gözetimli smoke test yapılır.

## Nihai mimari

Proje sabit olarak **bir skill + iki MCP**'den oluşur:

| Bileşen | Sorumluluk | Yazar mı? |
|---|---|---|
| `litlib-literature-workflow` skill | Arama/indirme/okuma rotasına karar verir; uyum sınırlarını, insan checkpoint'lerini ve arıza kararlarını uygular | Doğrudan yazmaz |
| LitLib MCP | Zotero/görev veritabanı metadata'sını, PDF yollarını, sayfalı tam metni ve görev durumunu tam olarak okur | Kesinlikle salt-okur |
| ZotSeek MCP | İndekslenmiş Zotero literatüründe semantic/hybrid/keyword arama | MCP salt-okur |
| `litlib` CLI | Görev oluşturur, indirir, doğrular, RIS üretir, Zotero içe aktarımını onaylar | Yazar |

Ayrıntılı sınırlar için [mimari belgesine](docs/ARCHITECTURE.md) bakın. Taşınabilir skill
kaynağı [`skills/litlib-literature-workflow`](skills/litlib-literature-workflow) altındadır.
Skill dağıtılırken `references/` dizini de birlikte dağıtılmalıdır.

## Neler yapabilir, neler yapamaz

LitLib elinizdeki DOI/PMID/PMCID/arXiv/tam başlık ile metadata çözümleme, OA/kurum
üzerinden edinme, sıkı PDF doğrulama, görev takibi ve Zotero'ya aktarma işlerini yapar.
Konu düzeyinde "makale bulma" için önce PubMed, Crossref, OpenAlex, Semantic Scholar gibi
akademik veritabanları kullanılmalı, sonra tanımlayıcılar LitLib'e verilmelidir; proje
sıradan web aramasını akademik arama gibi göstermez.

Proje Sci-Hub/LibGen, ödeme duvarı/CAPTCHA aşma, proxy döndürme, gözetimsiz toplu kurum
kazıması ya da tüm sayıyı indirme sunmaz; `zotero.sqlite` dosyasını da doğrudan değiştirmez.

## Kurulum

Gereksinimler: Windows 10/11, Python 3.11-3.13, [uv](https://docs.astral.sh/uv/),
Chrome/Edge, Zotero 8/9. Kurum kanalı JLU için yazılmıştır; diğer okullar için yeni bir
institution adapter eklemek gerekir.

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
Set-Location jlu-literature-agent-mcp
Copy-Item .env.example .env
# .env'i düzenleyin; en azından gerçek iletişim e-postasını LITLIB_EMAIL'e yazın
uv sync --locked --extra dev
uv run litlib doctor
uv run pytest
```

`.env` içinde JLU parolası, çerez, VPN token'ı ya da Zotero parolası saklanamaz. JLU
birleşik kimlik doğrulama bilgisi yalnız `litlib inst set-cred` ile Windows Credential
Manager'a yazılır.

D sürücüsü olmayan kullanıcılar `LITLIB_REQUIRE_D_DRIVE=0` ayarlar; büyük bir D sürücüsü
olanlar `1` yapıp `LITLIB_RUNTIME_ROOT`'u D sürücüsüne yönlendirebilir. Tüm ayarlar için
[.env.example](.env.example) dosyasına bakın.

## Hızlı iş akışları

### Tek DOI

```powershell
uv run litlib download 10.xxxx/example
uv run litlib verify
uv run litlib status --verbose
```

Bu giriş noktası otomatik olarak görev oluşturur, metadata'yı çözümler, indirir, doğrular
ve kaydeder. Hedef dosya varsa varsayılan olarak üzerine yazmayı reddeder; `--overwrite`
yalnız kullanıcı açıkça istediğinde kullanılır.

### Toplu OA

```powershell
uv run litlib queue add --file examples/input.example.csv
uv run litlib run --stage fetch-metadata
uv run litlib run --stage oa
uv run litlib status --verbose
```

OA adaylarının sırası: arXiv, tanınabilen MDPI public static, Unpaywall, Europe PMC,
OpenAlex; en son da açık OA lisans metadata'sı olan Crossref bağlantısı. Her aday ayrı ayrı
indirilir ve doğrulanır.

### JLU kurum kanalı

Yalnız `REQUIRES_INST` görevleri işlenir; parti başına en fazla 10 makale, eşzamanlılık 1,
aralık 8-15 saniye:

```powershell
uv run litlib inst set-cred
uv run litlib inst check-cred
uv run litlib inst open
uv run litlib run --stage inst --access-mode campus
# kampüs dışında offcampus; ağ bilinmiyorsa auto kullanın
uv run litlib inst close
```

Turnstile, kaydırıcı, OTP ya da CAPTCHA çıktığında program durmalı ve kullanıcı bunu
görünür özel tarayıcıda tamamlamalıdır. Yayıncı açıkça satın alma/kiralama/yalnız HTML
gösteriyorsa durulur; başarılı giriş PDF hakkına sahip olmak anlamına gelmez.

### BVU (GlobalProtect)

Bu fork'un Bezmialem Vakıf Üniversitesi için macOS'a (uv, Python 3.12) eklediği kol.
Kampüs dışı erişim Palo Alto GlobalProtect VPN üzerinden IP tabanlıdır; bu yüzden LitLib
hiçbir parola saklamaz ya da kullanmaz, JLU WebVPN ağ geçidi / IdP giriş rotaları atlanır.
Parti sınırları, hız ayarı ve insan checkpoint'inde durma aynen geçerlidir. git'in yok
saydığı `.env` dosyasına şunları yazın:

```sh
LITLIB_INSTITUTION=bvu
LITLIB_BVU_PROBE_URL=https://doi.org/<BVU'nun abone olduğu bir makale>
```

Her partiden önce deneme sayfasında erişim sağlayıcı olarak Bezmialem geçmelidir (önce
httpx; 403/503 ya da anti-bot sayfasında, olağan insan beklemesiyle birlikte zaten açık olan
özel Chrome). Geçmezse parti durur ve görevler `REQUIRES_INST` durumunda kalır.

Canlı kontrol, 2026-09-19, kampüs dışında GlobalProtect ile (`litlib run --stage inst
--access-mode campus`):

| DOI | Rota | Sayfa / metin karakteri | SHA-256 |
|---|---|---|---|
| `10.1038/s41586-025-08610-1` (Nature 639:360) | `direct-httpx` | 11 / 56115 | `f2ed3cce730b4905f33252003e0ee0227de448ee7df6e7d98779f705566f6f80` |

PDF (24.225.537 B), DOI eşleşmesiyle `validate_pdf_for_work` kontrolünden ve `litlib run
--stage verify` adımından (1/1) geçti. Daha yeni, düzenlenmemiş taslak durumundaki bir
makale (`10.1038/s41586-026-11123-0`) BVU erişimini gösterdi ama henüz ana metin PDF'i
yoktu; PDF olmadığı için doğru biçimde reddedildi.

### CNKI

```powershell
uv run litlib inst open
uv run litlib cnki open
uv run litlib cnki search "<arama terimi>" --limit 10
uv run litlib cnki download "<ayrıntı sayfası URL'i>" --output "<hedef.pdf>"
uv run litlib inst close
```

`bar.cnki.net` kaydırıcısı elle tamamlanmalıdır. CAJ, PDF değildir; şu an PDF doğrulama ve
tam metin hattına dahil edilmez.

### Zotero'ya aktarma

```powershell
uv run litlib proposal --doi-file <batch.csv>
# Kullanıcı RIS'i Zotero'ya aktarır ve kayıtları/ekleri kontrol eder
uv run litlib review --doi-file <batch.csv>
uv run litlib import --lookup --batch <name> --doi-file <batch.csv>
```

Durum yalnız tek bir Zotero parent item'ı, boş olmayan item key ve okunabilir PDF eki tam
olarak eşleştiğinde `IMPORTED` olur. Zotero çalışmıyorsa ya da eşleşme belirsizse sıfır
dışı kodla çıkar ve sahte onay vermez.

Açıkça satın alma/kiralama gerektiren ve PDF yetkisi olmayan görevler kesin `PAYWALLED`
durumuna geçer; CAPTCHA kaynaklı `HUMAN_REQUIRED` ya da 429 kaynaklı `RATE_LIMITED` ile
karıştırılmaz.

## Agent entegrasyonu

Tam yapılandırma için [Agent entegrasyonu](docs/AGENT_INTEGRATION.md) ve skill içindeki
[CLIENT_SETUP](skills/litlib-literature-workflow/references/CLIENT_SETUP.md) belgelerine
bakın. OpenCode, Codex ya da başka bir MCP istemcisinde şunlar kaydedilmelidir:

- LitLib: stdio, `<repo>\.venv\Scripts\python.exe -m litlib.cli mcp`
- ZotSeek: HTTP, `http://127.0.0.1:23119/zotseek/mcp`

ZotSeek harici bir Zotero eklentisidir; bu depo XPI içermez. Kurduktan sonra, semantik
aramanın neden sonuç vermediğini açıklamadan önce etkin modelin indeks kapsamını kontrol
edin. Çince sorgular İngilizce literatürde zayıf sonuç veriyorsa, kütüphanede ilgili makale
olmadığına hemen karar vermek yerine önce İngilizce eş anlamlı sorgu deneyin.

## Site deneyimleri

Tarihli ve kanıt etiketli tam saha kayıtları
[SITE_RECIPES.md](skills/litlib-literature-workflow/references/SITE_RECIPES.md) içindedir:
Wiley signed `pdfdirect`, MDPI `/pdf?version=`, ScienceDirect `pdfft`, T&F CARSI/HTML-only,
OUP, Springer protocol, CNKI slider, ACS unsupported SP ve RSC 429.

Yeni bir siteyle karşılaşınca önce
[DECISION_TREE.md](skills/litlib-literature-workflow/references/DECISION_TREE.md) ile
authentication, anti-bot, partial response, HTML-only, paywall ve wrong-PDF durumlarını
ayırt edin; doğrudan DOI önekine sabit kod eklemeyin.

### Kişisel deneyimle kendini geliştirme (litlib learn)

Depodaki site profilleri salt-okur temel çizgidir; her kullanıcının kendi başarılı
deneyimleri otomatik olarak yerelde
`<LITLIB_RUNTIME_ROOT>\experience\experiences.json` dosyasına kaydedilir (varsayılan
`D:\LitLibRuntime\experience\`); Git'e girmez, yüklenmez, projeyle dağıtılmaz:

- Kurum kanalı ya da CNKI ile başarılı indirmeden (sıkı PDF doğrulamasından geçtikten)
  sonra site + rota otomatik kaydedilir.
- Elle de eklenebilir: `litlib learn add --domain <alan-adı> --route <rota> --note <açıklama>`.
- Görüntüleme: `litlib learn list --domain <site>` ya da `litlib learn export` (Markdown).
- Silme: `litlib learn remove <id>`.
- Ödeme duvarı/doğrulama kodu/hız sınırı durumları asla başarılı deneyim olarak
  öğrenilmez; tüm kayıtlar otomatik maskelenir.

Böylece herkes "bir kez kullanır, bir kez kaydeder", kullandıkça iş kolaylaşır ve projenin
sürekli bakıma ihtiyacı olmaz.

## Selülaz veri eklentisi

LitLib ayrıca UniProt accession'larına yönelik temel veri hazırlama yetenekleri sunar:

```powershell
uv run litlib uniprot P12345 --output output\uniprot_P12345.json
uv run litlib evidence scan staging\downloads\paper.pdf
uv run litlib supplement discover "https://publisher.example/article"
uv run litlib supplement download "https://publisher.example/supp.xlsx" --doi 10.xxxx/example
uv run litlib cellulase validate data\measurements.jsonl
uv run litlib cellulase maxima data\measurements.jsonl --output output\maxima.jsonl
```

Bu eklenti eksik alanlara izin verir; özgün birimleri, substratı, deney koşullarını ve
DOI/sayfa/tablo-şekil kanıt konumlarını korur. Maksimum değerler yalnız aynı yapı, substrat,
metrik ailesi, birim ve assay method içinde karşılaştırılır; bağıl aktivite, grafikten
okunan tahminler ve henüz eklenmemiş ek materyaller sessizce kesin mutlak aktivite olarak
kabul edilmez. Görsel işleme kuyruğu ve harici çok kipli modeller sonraki isteğe bağlı
katmandır; temel literatür edinme iş akışını etkilemez.

## Geliştirme ve sürüm

```powershell
uv run pytest
uv run ruff check .
```

CI, Windows üzerinde Python 3.11 ve 3.13 ile test eder. Yeni bir site adaptörüyle katkı
yapmadan önce [CONTRIBUTING.md](CONTRIBUTING.md) dosyasını okuyun ve fixture ile test yazın;
gerçek kurum oturumları CI'a giremez.

Çalışma verisi, PDF/CAJ, tam metin önbelleği, Zotero/SQLite veritabanları, XPI, tarayıcı
profilleri, günlükler, çerezler, WebVPN token'ları ve `.env` Git dışında tutulur. Sürüm
öncesi kontroller için [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) dosyasına bakın.

## Lisans

LitLib'in kendi kodu ve belgeleri [MIT Lisansı](LICENSE) ile yayımlanır. Üçüncü taraf
bileşenlerin durumu için [THIRD_PARTY.md](docs/THIRD_PARTY.md) dosyasına bakın. Yayıncı
içeriği ve indirilen makaleler bu projenin lisansı sayesinde yeniden dağıtım hakkı kazanmaz.
