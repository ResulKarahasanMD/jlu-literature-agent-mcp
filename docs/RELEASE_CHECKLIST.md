# GitHub sürüm kontrol listesi

## Depo içeriği

- [ ] `git status --short --untracked-files=all` çıktısında PDF, CAJ, XPI, `.env`,
  veritabanı, tarayıcı profili, çerez, WebVPN token'ı, günlük, çıkarılmış tam metin ya da
  kullanıcıya özgü rapor yok.
- [ ] İzlenen içerikte kullanıcı adları, e-posta adresleri, mutlak ev dizini yolları, API
  anahtarları, token'lar ve imzalı URL'ler arandı.
- [ ] `IMPLEMENTATION_PLAN.md` ve yerel WebVPN deneme betiklerinin izlenmediği doğrulandı.
- [ ] Tüm test fixture'larının sentetik olduğu ve korumalı makale metni içermediği doğrulandı.
- [ ] Enzim verisi şemalarının DOI/sayfa/tablo/şekil/ek materyal kanıt konumlarını koruduğu ve
  eksik koşulları sessizce doldurmadığı doğrulandı.

## Metadata ve hukuk

- [ ] Etiketlemeden önce `project.urls`'in hâlâ hedeflenen açık depoyu gösterdiği doğrulandı.
- [ ] Bakımcı adı/iletişim bilgisi ve telif ifadesi doğrulandı.
- [ ] ZotSeek XPI'ı, upstream lisans dosyası yetkili hale gelene kadar harici tutuluyor.
- [ ] Wheel/binary dağıtmadan önce bağımlılık lisans raporu üretildi ve incelendi.
- [ ] GitHub Private Vulnerability Reporting açıldı.

## Doğrulama

- [ ] `uv lock --check`
- [ ] Etkin bir MCP çalıştırılabilir kilidi yokken `uv sync --locked --extra dev`.
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] `uv build`
- [ ] Üretilen wheel temiz bir geçici ortama kuruldu ve `litlib --version` çalıştırıldı.
- [ ] `litlib learn list` temiz wheel kurulumundan çalışıyor ve hatasız olarak boş kütüphane
  raporluyor (kişisel deneyim çalışma zamanında yereldir, asla paketlenmez).
- [ ] `litlib uniprot`, `litlib evidence scan`, `litlib supplement discover` ve
  `litlib cellulase validate/maxima`, canlı yayıncı oturumu olmadan yerel smoke testlerden
  geçiyor.
- [ ] Ek dosyalar `staging/supplements` kullanıyor, maskelenmiş bir manifestleri var ve ana
  makale PDF'iyle asla karıştırılmıyor.
- [ ] OpenCode ve Codex yapılandırma örnekleri istemciler temiz biçimde yeniden
  başlatılarak doğrulandı.
- [ ] Skill dizininin tamamı dağıtıldı ve referansların çözümlendiği doğrulandı.
- [ ] Yeniden dağıtılabilir bir test DOI'siyle bir OA smoke testi çalıştırıldı.
- [ ] Kurum smoke testleri yalnız gözetimli, yetkili bir JLU oturumunda çalıştırıldı.

## Kişisel deneyim

- [ ] `experience.py`, `test_experience.py` ve `learn` CLI komutunun sdist/wheel'e dahil
  olduğu ve CI (`uv run pytest`) tarafından kapsandığı doğrulandı.
- [ ] `experiences.json` ve `experience/` çalışma zamanı dizininin depoda olmadığı doğrulandı
  (git yok sayar; varsayılan `LITLIB_RUNTIME_ROOT` klonun dışındadır).
- [ ] Otomatik öğrenmenin yalnız doğrulanmış başarılara bağlı olduğu doğrulandı: PAYWALLED /
  HUMAN_REQUIRED / RATE_LIMITED / FAILED rotaları kaydedilemez.
- [ ] Tüm deneyim alanlarının yazılmadan önce maskelendiği doğrulandı (URL query token'ları,
  WebVPN token'ları, çerezler, kimlik bilgileri gizlenir).
- [ ] README ve skill `SKILL.md`, `litlib learn list | add | remove | export` komutlarını ve
  öncelik kuralını (kişisel deneyim kanonik `SITE_RECIPES.md`'den önce gelir) belgeliyor.

## Belgeler

- [ ] README, LitLib'in kendisinin kapsamlı bir akademik arama veritabanı olduğunu iddia
  etmiyor.
- [ ] Her site tarifinde tarih, kanıt etiketi, erişim modu, başarılı/başarısız rotalar ve
  durma koşulu var.
- [ ] Bilinen doğrulanmamış yollar doğrulanmamış olarak etiketli kalıyor.
- [ ] Sürüm notları birim testli davranışı canlı site gözlemlerinden ayırıyor.
