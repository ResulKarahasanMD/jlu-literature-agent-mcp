## Değişiklik

Kullanıcının göreceği davranışı ve neden gerektiğini açıklayın.

## Kanıt

- [ ] Testler sentetik/asgari fixture'lar kullanıyor ve korumalı tam metin içermiyor.
- [ ] Site gözlemleri test tarihiyle birlikte doğrulanmış, çıkarım ya da doğrulanmamış olarak etiketlendi.
- [ ] `docs` ve taşınabilir skill referansları uygulamayla tutarlı.

## Doğrulama

- [ ] `uv lock --check`
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] PDF, CAJ, XPI, `.env`, veritabanı, tarayıcı profili, çerez, token ya da günlük eklenmedi.
- [ ] CAPTCHA/ödeme duvarı/hız sınırı aşma ya da güvensiz Zotero veritabanı yazımı eklenmedi.
