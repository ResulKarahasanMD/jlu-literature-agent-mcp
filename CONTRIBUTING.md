# Katkıda bulunma

LitLib öncelikle yeniden üretilebilir, yetkili bir literatür iş akışına ihtiyaç duyan
Jilin Üniversitesi öğrencileri için yazıldı. Katkılar bu sınırı korumalıdır.

## Geliştirme ortamı

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
cd jlu-literature-agent-mcp
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run pytest
uv run ruff check .
```

`.env`, PDF'ler, CAJ dosyaları, Zotero veritabanları, tarayıcı profilleri, çerezler,
WebVPN token'ları, indirilen XPI dosyaları, günlükler ya da üretilmiş tam metin commit
edilmez.

## Pull request'ler

1. Yayıncıya özgü davranışı küçük, test edilebilir bir adaptörde ya da yönlendirme dalında
   tutun.
2. Canlı kurum oturumu gerektirmeyen, fixture tabanlı bir test ekleyin.
3. `docs/DOWNLOAD_PLAYBOOK.md` dosyasını gözlenen belirti, başarılı rota, başarısız rotalar,
   durma koşulu, erişim ortamı ve doğrulama tarihiyle güncelleyin.
4. Gözlemleri `verified`, `inferred` ya da `unverified` olarak etiketleyin.
5. Asla CAPTCHA aşma, ödeme duvarı aşma, yüksek eşzamanlılıklı kazıma ya da varsayılan
   olarak açık kimlik bilgisi/çerez dışa aktarımı eklemeyin.

Canlı smoke testlerde katkıcının kendi yetkili hesabı, görünür bir tarayıcı, en fazla 10
makalelik partiler, eşzamanlılık 1 ve 8-15 saniyelik bekleme kullanılmalıdır.

## Site gerilemesi bildirme

DOI önekini, açılış sayfası host'unu, erişim modunu (`campus`, `offcampus` ya da WebVPN),
HTTP durumunu ya da görünen hata metnini, insan doğrulaması çıkıp çıkmadığını, maskelenmiş
`litlib status --attempts <task-id>` çıktısını ve test tarihini ekleyin. Kimlik bilgilerini,
çerezleri, query token'larını ya da oturum bilgisi içeren tam yayıncı URL'lerini asla
yapıştırmayın.
