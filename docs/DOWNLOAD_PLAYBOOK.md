# İndirme Playbook'u girişi

Skill ile proje belgelerinin birbirinden kopmaması için ayrıntılı deneyimin tek kaynağı,
dağıtılabilir skill paketindeki iki referans belgesidir:

- [DECISION_TREE.md](../skills/litlib-literature-workflow/references/DECISION_TREE.md):
  genel teşhis, tarayıcıya yükseltme, yeni yayıncı keşfi ve durma koşulları.
- [SITE_RECIPES.md](../skills/litlib-literature-workflow/references/SITE_RECIPES.md): Wiley,
  MDPI, Elsevier, T&F, OUP, Springer, Frontiers, CNKI, ACS, RSC, JLU IdP ve WebVPN saha
  kayıtları.

## En kısa karar sırası

```text
akademik tanımlayıcı
  -> OA adayları, her biri ayrı ayrı doğrulanır
  -> geçerli yetkili oturumla doğrudan HTTP/tarayıcı
  -> varsa mevcut WebVPN bileti + token
  -> JLU kurum girişi
  -> insan checkpoint'i / soğuma / yalnız satın alma durumunda dur
```

## Tamamlanma koşulu

PDF aynı anda şunların hepsini karşılamalıdır: `%PDF-` başlığı, sonda `%%EOF`, en az bir
sayfa, ilk üç sayfada hedef DOI, ilk sayfada çakışan DOI olmaması, ek materyal olmaması,
SHA-256; ayrıca görev veritabanına başarıyla kaydedilmiş olmalıdır. `200` yanıtı, `.pdf`
uzantısı ya da tarayıcı görüntüleyicisinde görünmesi tek başına indirmenin tamamlandığını
kanıtlamaz.

## Yeni deneyim kaydı biçimi

`SITE_RECIPES.md` dosyasına eklenen kayıt şunları içermelidir:

- Tarih, ağ/erişim modu, DOI öneki, gerçek açılış sayfası host'u ve içerik türü.
- `verified`, `observed restriction` ya da `inferred` etiketi.
- Başarılı rota, başarısız rotalar, insan checkpoint'i ve durma koşulu.
- Doğrulama sonucu: boyut, sayfa sayısı, beklenen DOI, EOF, ana makale olup olmadığı.
- Çerez, imzalı query, WebVPN token'ı ya da korumalı içeriğin tamamını içermeyen
  fixture/test.
