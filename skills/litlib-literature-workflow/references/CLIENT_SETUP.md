# İstemci ve kurulum ayarları

## 1. LitLib'i bir klondan kurun

Gereksinimler: Windows 10/11, Python 3.11-3.13, `uv`, Chrome ya da Edge ve Zotero 8/9.
Kurum kimlik bilgileri ve JLU rotaları Windows/JLU'ya özgüdür; OA ve metadata kodu başka yerde
geliştirilebilir ama kurum smoke testleri yalnız Windows'ta yapılır.

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
Set-Location jlu-literature-agent-mcp
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run litlib doctor
uv run pytest
```

Unpaywall ve API'lere nazik kimlik bildirimi için `.env` içine gerçek bir iletişim e-postası
yazın. `.env` içine JLU parolası, Zotero parolası, API anahtarı, çerez ya da VPN token'ı
koymayın.

Depolama ayarları:

- `LITLIB_RUNTIME_ROOT`: geçici dosyalar, önbellek, model ve özel Chrome profili kökü.
- `LITLIB_ROOT`: wheel ya da global kurulumlar için yazılabilir durum/çıktı çalışma alanı.
  Düzenlenebilir klonlar otomatik olarak klon kökünü kullanır.
- `LITLIB_ZOTERO_DATA`: ek yolu çözümlemede Zotero veri dizini için yedek.
- `LITLIB_REQUIRE_D_DRIVE=1`: D: veri sürücüsü olan makineler için isteğe bağlı yerel
  politika.
- `LITLIB_EXPORT_SESSION_COOKIES=0`: önerilen varsayılan. `1`, yalnız geçerli Windows
  kullanıcısına bağlı DPAPI ile şifreli bir yedek saklar.

## 2. Zotero'yu hazırlayın

1. Zotero 8 ya da 9'u resmi Zotero sitesinden kurun.
2. Zotero'yu başlatın ve Gelişmiş > Dosyalar ve Klasörler altında etkin veri dizinini
   doğrulayın.
3. `127.0.0.1:23119` yanıt versin diye Gelişmiş ayarlarda Zotero'nun yerel HTTP sunucusuna
   izin verin.
4. İki MCP'den birini kullanırken Zotero'yu açık tutun.
5. LitLib'i `zotero.sqlite`'a yönlendirmeyin ya da bu dosyayı doğrudan düzenlemeyin.

LitLib'in içe aktarma yolu RIS artı insan onayıdır. RIS'in `L1` alanı doğrulanmış yerel PDF'i
gösterir. İçe aktarmadan sonra `litlib import --lookup`, `IMPORTED` ayarlamadan önce parent
item'ı ve PDF ekini Zotero'nun Local API'si üzerinden doğrular.

## 3. ZotSeek'i ayrıca kurun

ZotSeek LitLib ile birlikte paketlenmez ya da yeniden dağıtılmaz.

1. Yeniden üretilebilirlik için yerelde doğrulanmış temel sürüm ZotSeek `v1.18.0`'ı
   `https://github.com/introfini/ZotSeek/releases/tag/v1.18.0` adresinden kurun. Bu skill
   eşdeğer davranış iddia etmeden önce daha yeni bir sürümün araç şeması, indeks davranışı,
   depolama ve lisans açısından yeniden kontrol edilmesi gerekir.
2. Zotero'da Araçlar > Eklentiler > dişli menüsü > Eklentiyi Dosyadan Kur'u açın.
3. Zotero'yu yeniden başlatın.
4. Zotero Ayarlar > ZotSeek altında AI Agent Access/MCP'yi etkinleştirin.
5. Bir indeksleme modu seçin ve kütüphane indeksini güncelleyin.
6. Arama sonuçlarına güvenmeden önce `zotseek_index_status` çağırın ve hedef kütüphane için
   etkin model kapsamının `N of N` olduğunu doğrulayın.

Yerel testlere ve upstream belgelerine dayalı model önerileri:

- `nomic-embed-text-v1.5`: paketle gelir, İngilizce odaklıdır, kurulum yükü en azdır.
- `paraphrase-multilingual-MiniLM-L12-v2`: daha küçük çok dilli seçenek.
- `multilingual-e5-base`: dengeli çok dilli model; test edilen İngilizce makale kümesinde
  Çince sorgular yine de eşdeğer İngilizce sorgulardan daha az güvenilir sonuç verdi.
- `BGE-M3`: daha büyük çok dilli seçenek; yalnız doğruluk kazancı model boyutunu ve yeniden
  indeksleme süresini haklı çıkarıyorsa kullanın.

Model değiştirmek etkin model için kapsam gerektirir. Başka bir modelin embedding'leri bir
öğeyi yeni etkin modelle aranabilir yapmaz.

2026-08-06'daki kontrole göre ZotSeek'in README'si MIT diyor, ama depo kökünde `LICENSE`
dosyası bulunamadı ve GitHub API'si algılanmış bir lisans bildirmedi. Upstream lisansı
belirsizliğini yitirene kadar XPI'ı LitLib'in parçası olarak yeniden dağıtmayın; kullanıcıları
upstream Releases'a yönlendirin.

## 4. İki MCP sunucusunu kaydedin

İstemci yapılandırmasında mutlak yollar kullanın. `<repo>` yerine gerçek klon yolunu yazın.

### OpenCode

`~/.config/opencode/opencode.json` dosyasına ekleyin ve mevcut tüm alanları koruyun:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "litlib": {
      "type": "local",
      "command": ["<repo>\\.venv\\Scripts\\python.exe", "-m", "litlib.cli", "mcp"],
      "enabled": true
    },
    "zotseek": {
      "type": "remote",
      "url": "http://127.0.0.1:23119/zotseek/mcp",
      "enabled": true
    }
  }
}
```

Yapılandırmayı düzenledikten ya da skill'i kurduktan/güncelledikten sonra OpenCode'u yeniden
başlatın.

### Codex

`~/.codex/config.toml` dosyasına ekleyin:

```toml
[mcp_servers.litlib]
command = '<repo>\.venv\Scripts\python.exe'
args = ["-m", "litlib.cli", "mcp"]

[mcp_servers.zotseek]
url = "http://127.0.0.1:23119/zotseek/mcp"
```

Yapılandırmayı düzenledikten ya da skill'i kurduktan/güncelledikten sonra Codex'i yeniden
başlatın.

Diğer MCP istemcilerinde LitLib'i `python.exe -m litlib.cli mcp` ile stdio sunucusu, ZotSeek'i
yukarıdaki URL'de Streamable HTTP sunucusu olarak kaydedin. İstemciye özgü önekler görünen
araç adlarını değiştirebilir; yalnız sabit kodlu bir öneke değil, araç açıklamalarına bakın.

## 5. Skill'i kurun

`references/` dahil olmak üzere `skills/litlib-literature-workflow` dizininin tamamını
dağıtın. Yalnız `SKILL.md`'yi kurmak sorun giderme bilgisini kaybettirir.

Yaygın konumlar:

- OpenCode proje: `.opencode/skills/litlib-literature-workflow/`
- OpenCode global: `~/.config/opencode/skills/litlib-literature-workflow/`
- Codex global: `~/.codex/skills/litlib-literature-workflow/`
- Agent Skills uyumlu istemciler: istemcinin belgelediği skills dizini

Skill'ler ve MCP yapılandırması istemci başlarken yüklenir. Değişikliklerden sonra yeniden
başlatın.

## 6. Smoke test

Bunları ödeme duvarlı bir makale indirmeden çalıştırın:

```powershell
uv run litlib doctor
uv run litlib status
uv run litlib verify
```

Beklenen ayrıntı: kayıtlı PDF yokken `litlib verify` sıfır dışı kod döndürür. Bu bilinçlidir
ve boş bir doğrulamanın başarı olarak raporlanmasını önler.

Zotero çalışırken:

1. `library_list_collections` çağırın.
2. Bilinen tam bir DOI ile `library_search_metadata` çağırın.
3. `zotseek_index_status` çağırın.
4. İngilizce indekslenmiş bir makaleye karşı bir İngilizce hibrit sorgu çalıştırın.

Canlı bir kurum indirmesini gözetimsiz bir CI testi olarak kullanmayın. Yayıncı sayfaları,
kimlik bilgileri ve insan doğrulamaları yalnız gözetimli smoke testlerle test edilir.
