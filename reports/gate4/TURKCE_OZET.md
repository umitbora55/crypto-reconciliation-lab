# Gate 4 — işlem maliyeti ve dayanıklılık

**Karar: NO_CHANGE. Üretim kodu ve DELETE/FULL varsayılanı korunuyor.**
WAL/FULL bu sınırlı sentetik deneyde daha hızlıydı; mevcut inceleme aracıyla
uyumsuz olduğu için aday kabul edilmedi.

Her veri boyutunda aynı dosyalarla, yeni veritabanlarında ve dönüşümlü sırayla
yedi eşleştirilmiş tekrar yapıldı. 10.000/25.000 olaya 17'şer yardımcı kayıt
eklendi. Her kayıt için tek transaction ve COMMIT sonrası yanıt korundu;
`synchronous=2`, yabancı anahtarlar ve schema 6 değişmedi. Süreler süreç
başlatma, kayıt alma, hesaplama, sonuç/kanıt saklama, kanonik çıktı,
doğrulama, checkpoint, kapanış ve yeniden açılmayı içeriyor.

| Olay | DELETE/FULL medyanı | WAL/FULL medyanı | Eşleştirilmiş süre azalması, %95 aralık | Eşleştirilmiş göreli azalma, %95 aralık |
|---:|---:|---:|---:|---:|
| 10.000 | 15,576 sn | 6,369 sn | 9,220 sn [8,910–9,805] | %59,5 [%57,9–62,9] |
| 25.000 | 39,989 sn | 17,961 sn | 22,811 sn [21,311–23,908] | %55,9 [%54,7–57,8] |

Etki sütunları her çiftin farkı/oranı alındıktan sonra hesaplanan medyanlardır;
aralıklar önceden belirlenmiş 10.000 bootstrap örneklemesine dayanır. Sonuçlar
bu makineyi ve iki sabit sentetik girdiyi kapsar. Yedi tekrarda p95, gözlenen
en büyük süredir. Önceden sabitlenen hız eşiği iki boyutta da aşıldı.

İlk ısınma süreci, veritabanı oluşmadan bellek limiti aktarımında hata verdi.
Bu hata ve 33 NOT_RUN kaydı korundu. Dar araç düzeltmesinden sonraki ayrı
devam çalışmasının 34 hücresi geçti; yukarıdaki sayılar bu çalışmaya aittir.
İlk programın tüm koşulları geçtiği iddia edilmiyor. İki denemenin toplamı
613,934 saniye, 331,277 CPU saniyesi ve örneklenen en yüksek 3,713 GiB dosya
alanıyla başlangıç bütçesinin içinde kaldı.

20 gerçek SIGKILL örneği, sınanan işlem noktalarında COMMIT/yanıt ve yeniden
deneme davranışlarının eşleştiğini gösterdi. Mantıksal tablolar, kayıt sırası,
bakiyeler, run kimlikleri ve kanıtlar eşleşti. Bu sonuç elektrik kesintisi,
disk önbelleği veya farklı dosya sistemlerinde kalıcılığı kanıtlamaz.

WAL, checkpoint ve temiz kapanıştan sonra bile mevcut finansal inceleme
aracında `SNAPSHOT_UNSUPPORTED` hatası veriyor. Beş dosyalı kayıtlı çalıştırma
çıktısı ise iki yöntemde aynı. Ayrıca checkpoint öncesinde yalnız ana WAL
veritabanını kopyalamak onaylanmış 30 kaydı taşımadı; SQLite yedekleme API'si
ve gerekli yan dosyalarla kopya bu kayıtları korudu. Hız kazancı bu uyumluluk
engellerini gidermiyor.

Bağımsız kurumsal iki taraflı finansal veri ve temsil edici doğal hata
etiketleri yok. Kurumsal üstünlük, banka maliyet tasarrufu, risk azalması,
RTO/RPO veya mevzuata uyum sonucu çıkarılamaz. Gate 1/2/3 kanıtları ve
sayım temelli denetimin tarihsel 12 yanlış negatifi korunmuştur.

**Tek önerilen sonraki adım:** üretim yaması düşünülmeden önce WAL uyumlu
snapshot/çıktı sınırını ayrı bir tasarım incelemesine almak.
