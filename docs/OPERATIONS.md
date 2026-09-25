# İşletim

## Kurulum ve sağlık kontrolü

```powershell
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run litlib doctor --storage
uv run pytest
uv run ruff check .
```

Bir sarmalayıcı tercih ediliyorsa `scripts/run.ps1` kullanın. `LITLIB_RUNTIME_ROOT`'a uyar,
D:'deki bir klon için varsayılan olarak `D:\LitLibRuntime`'ı, aksi halde klondaki
`.litlib-runtime`'ı kullanır. Yalnız süreç düzeyindeki ortamı değiştirir.

## Olağan iş akışı

```powershell
uv run litlib status --verbose
uv run litlib queue add --file <input.csv>
uv run litlib run --stage fetch-metadata
uv run litlib run --stage oa
uv run litlib verify
```

Gözetimli kurum tarayıcısını ancak bundan sonra, `REQUIRES_INST` görevleri için açın. Parti
bitince her zaman kapatın:

```powershell
uv run litlib inst open
uv run litlib run --stage inst --access-mode auto
uv run litlib inst close
```

## Kurtarma

```powershell
uv run litlib status --attempts <task-id>
uv run litlib queue recover
uv run litlib queue recover --failed
uv run litlib queue recover --paused
```

`--failed`'i yalnız nedeni giderdikten sonra kullanın. `--paused`'ı kullanıcı bir doğrulamayı
tamamladıktan ya da hız sınırı soğuması bittikten sonra kullanın. Sınıflandırmadan tekrar
tekrar denemek işletimsel bir çözüm değildir.

## Zotero'ya aktarma

1. `litlib proposal` çalıştırın; boş bir öneri oluşturmayı ya da eksik PDF eklemeyi reddeder.
2. Kullanıcı RIS'i Zotero'ya aktarır ve öğe metadata'sını/PDF eklerini inceler.
3. İlgili parti için `litlib review` çalıştırın.
4. `litlib import --lookup` çalıştırın; `IMPORTED` öncesinde tam parent item'ları ve PDF'leri
   doğrular.

Zotero kapalıysa, bir öğe belirsizse ya da ek yoksa Zotero'yu yeniden başlatın/onarın ve
tekrar çalıştırın. Doğrulamayı atlamak için SQLite'ı elle güncellemeyin.

## Günlükler ve durum

- `logs/litlib.log`: 20 MB'ta döndürülür, beş yedek tutulur.
- `state/litlib.db`: görev ve denetim durumu; bibliyografik ana veritabanı değildir.
- `staging/downloads`: doğrulanmış ya da kurtarılmış PDF dosyaları.
- `output`: RIS/manifestler/tam metin önbelleği; hepsi üretilir ve Git dışında tutulur.
- `LITLIB_RUNTIME_ROOT/chrome`: özel profil/önbellek/indirmeler.
- `LITLIB_RUNTIME_ROOT/experience/experiences.json`: kişisel deneyim kütüphanesi (aşağıya
  bakın).

Projenin `state/` dizinini yalnız hiçbir LitLib yazma komutu çalışmıyorken yedekleyin.
Zotero yedeği Zotero'nun kendi yönergelerine uyar ve yapılandırılmış veri dizinini
içermelidir. ZotSeek'in indeksi türetilmiştir ve yeniden oluşturulabilir.

## Kişisel deneyim (`litlib learn`)

Başarılı kurum ya da CNKI indirmeleri otomatik olarak
`<LITLIB_RUNTIME_ROOT>\experience\experiences.json` dosyasına kaydedilir; kayıtlar `domain`,
`route`, `url_pattern`, `doi_prefix`, başarı sayısı ve zaman damgalarını tutar ve yazılmadan
önce maskelenir. PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED / FAILED asla kaydedilmez.

- `litlib learn list [--domain <site>]` görüntüler; `litlib learn export` Agent'lar için
  Markdown üretir.
- `litlib learn add --domain <site> --route <rota> --note "<ne işe yaradı>"` elle kayıt ekler.
- `litlib learn remove <id>` hatalı kaydı siler.

Kişisel deneyim deponun dışında durur (git yok sayar) ve kullanıcıya/makineye özeldir. JSON
bozulursa yok sayılır ve boş okunur; dosyayı silmek öğrenmeyi sıfırlar.

## Enzim kanıtı hazırlama

İsteğe bağlı selülaz veri katmanı bir UniProt accession'ından başlar ve makale edinmeyi veri
çıkarımından ayrı tutar:

```powershell
uv run litlib uniprot <accession> --output output\uniprot.json
uv run litlib evidence scan <doğrulanmış-makale.pdf>
uv run litlib supplement discover <makale-url>
uv run litlib supplement download <ek-dosya-url> --doi <ana-makale-doi>
uv run litlib cellulase validate <measurements.jsonl>
uv run litlib cellulase maxima <measurements.jsonl> --output <maxima.jsonl>
```

Ek dosyalar varsayılan olarak `staging/supplements` altına gider ve
`output/supplement_manifest.jsonl` dosyasına kaydedilir; ana makale PDF'iyle asla
karıştırılmaz. Kanıt taraması yalnız eksik alanlar, şekiller, tablolar ve ek materyal
referansları için ön değerlendirme sinyalleri üretir. Bir alanın görselde olmadığını iddia
etmez. Harici çok kipli inceleme her makale için değil, yalnız ortaya çıkan görsel kuyruğu
için çağrılmalıdır.

Selülaz maksimumları yapı × normalleştirilmiş substrat × metrik ailesi × birim × assay method
başına seçilir. Eksik alanlar, bağıl aktivite, sayısallaştırılmış değerler ve çıkarımla elde
edilen yapı dizileri sonraki inceleme için açıkça etiketli kalır.

## Güncelleme

```powershell
git pull --ff-only
uv lock --check
uv sync --locked --extra dev
uv run pytest
uv run litlib doctor
```

`.venv\Scripts\litlib.exe`'yi başlatan eski MCP yapılandırması Windows'ta bu sarmalayıcıyı
kilitleyebilir. Belgelenen yapılandırma `python.exe -m litlib.cli mcp` kullanır; eski
istemcileri taşıyın, yeniden başlatın, sonra `uv sync` çalıştırın. ZotSeek'i güncelledikten
sonra Zotero'yu yeniden başlatın.

## Temizlik

Uygulanmış bir `litlib clean` komutu yoktur. Üretilen dizinleri inceleyin ve bir şey silmeden
önce kullanıcıya sorun. PDF'leri, Zotero eklerini, görev durumunu, tarayıcı profillerini ya da
karantina/kurtarma dosyalarını asla otomatik silmeyin.
