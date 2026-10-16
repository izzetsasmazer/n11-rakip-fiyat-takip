# Bağımsız N11 kontrolü

- GitHub Actions yaklaşık 15 dakikada bir işi başlatır (GitHub zamanlaması gecikebilir).
- Kodu çalıştırmak ChatGPT/Work kredisi tüketmez. GitHub Actions kullanım limitleri ve fiyatlandırması ayrı değerlendirilir.
- Sadece aynı N11 katalog bağlantılarında ŞaşmazerLtd ve üç hedef rakibin satıcı adı ve fiyatı birlikte doğrulanırsa karşılaştırılır.
- Değer veya satıcı belirsizse otomatik olarak atlanır. N11 sayfa yapısı değişirse sıfır karşılaştırma oluşabilir.
- Her seferde en fazla 8 katalog denenir; liste birden fazla çalışmada dolaşılır.
- Telegram yalnız doğrulanmış yeni ucuz teklif için kullanılır. Tespit ve teslim garantisi verilmez.
- GitHub Secrets TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID gerekir (mevcut bildirim sistemiyle ortak).
- Çalışma durumunu Actions > N11 bagimsiz fiyat kontrolu bölümünden kontrol edin.
- ÖNEMLİ: İlk gerçek çalışma doğrulanmadan taramanın işe yaradığını kabul etmeyin.
