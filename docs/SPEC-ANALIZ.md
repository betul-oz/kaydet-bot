# SPEC: Analiz modülü (sosyal medya büyüme analizi)

## Amaç
~10 markanın her birinin TikTok, YouTube ve Instagram hesabını tek yerde izlemek; hangi içeriğin neden tuttuğunu (hook, kurgu, ses, konu, süre, yayın zamanı) veriyle bulup bir sonraki içeriği iyileştirmek. Büyüme mühendisi bakışı: ölç → kalıp bul → hipotez üret → dene → tekrar ölç.

## Arayüz
- Üst çubukta en sağda **Kaydet | Analiz** anahtarı. Analiz modunda sol ray marka listesine döner (`#/analiz`, `#/analiz/<marka>`).
- Marka kutusu: toplam izlenme, video sayısı, hesaplar. Hesap satırı: takipçi, medyan izlenme, son çekim, "Verileri çek", "Video linki ekle".
- **Güç skoru** = videonun izlenmesi ÷ o hesabın medyan izlenmesi (≥2× "tuttu").

## Veri katmanları (gerçekçi durum, 2026-10-24 denendi)
| Katman | Kaynak | Durum |
|---|---|---|
| A. Herkese açık sayılar (izlenme, beğeni, yorum, süre, tarih, takipçi) | yt-dlp | **YouTube: profil listesiyle çalışıyor.** TikTok profil listesi yt-dlp'de bozuk, Instagram profil listesi desteklenmiyor → tek tek video linki (çalışır, IG için cookies gerekebilir) |
| B. Sahip verisi (erişim, ort. izlenme süresi, tutma eğrisi, kaydetme, paylaşım, takipçi kaynağı) | Resmi API / panel dışa aktarma | YouTube Analytics (OAuth), Instagram Graph API (Professional hesap + Facebook sayfası), TikTok (Display/Business API onayı gerekir) → **panel CSV/ekran görüntüsü içe aktarma** yedek yol |
| C. Video içi analiz (hook, ritim, ses) | Yerel: ffmpeg + faster-whisper + OpenCV; yorum: Claude oturumu | Planlı |

Not: Meta Ads MCP yalnızca reklamlanabilir medya listeler, organik içgörü (erişim/izlenme süresi) vermez; analiz için ana kaynak yapılmadı.

## Veri modeli (SQLite, `kaydet.db` içinde)
`accounts` (marka, platform, kullanıcı adı, takipçi, eşitleme durumu), `posts` (hesaba bağlı video: url, başlık, tarih, süre, izlenme, beğeni, yorum), `snapshots` (her çekimde sayaçların anlık görüntüsü → büyüme hızı). Planlı: `post_features` (video içi ölçümler), `post_reviews` (hook notu, Claude yorumu).

## Kabul kriterleri (İş 11, bu oturum)
1. Üstte Kaydet/Analiz anahtarı; Kaydet görünümü eskisi gibi çalışır.
2. Marka + platform + kullanıcı adı/linkle hesap eklenir; aynı hesap iki kez eklenmez; hesap silinir.
3. YouTube hesabı için "Verileri çek" arka planda çalışır, takipçi ve son Shorts/uzun videolar kaydedilir; hata kartta görünür, uygulama çökmez.
4. TikTok/Instagram için video linki ekleme çalışır; profil listesi desteklenmiyorsa açık mesaj verilir.
5. Güç skoru ve etkileşim oranı doğru hesaplanır. Testler ağ kullanmadan geçer.
6. Hesap verisi `kaydet.db`'de kalır; repoya girmez (public repo).

## Sonraki işler
Bkz. `IS-LISTESI.json` (iş 12-18): panolar/karşılaştırma, içe aktarma, resmi API bağlayıcıları, video içi analiz, hook puanlama, öneri motoru, zamanlanmış otomatik çekim.


## Güncelleme (2026-10-26): yeni sayfa yapısı
- **Marka** önce oluşturulur; bir markaya istediğin kadar hesap eklenir (YouTube/TikTok/Instagram). Marka sayfası: içerik planı (ilerleme, tahmini bitiş, gecikme riski, sıradaki işler, toplu plan ekleme), hesap karşılaştırma, öncelikli yapılacaklar.
- **Hesap sayfası:** KPI'lar, "Ne yapmalısın?" önerileri, en çok tutan / en zayıf videolar, "Hangi tür içerik tutuyor?" (süre, gün, saat dilimi, biçim, konu kelimesi, başlık özelliği, hashtag; güç + etkileşim), tüm videolar.
- **Video sayfası:** video içi analiz (ffmpeg): hook/orta/ritim/ses/bitiş brief'i ve enerji grafiği; "Claude'a ver" ile derin yorum istemi.
- Kaynaklar: bkz. KARARLAR #50-54 (açık kaynak araştırması: bangermap-mcp, youtube-niche-finder, yuben-app, Trend-Lens fikirleri; kod kopyalanmadı).
