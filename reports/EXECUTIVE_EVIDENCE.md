# Gerçek veri ve karşılaştırmalı doğrulama — kanıt özeti

16 Kasım 2026 · Uygulama başlangıcı `b48021273405128c67e2969fd4b46f8d7e876a99` · Sürüm 0.11.1

**Karar: `NOT_READY`.** Sonlu laboratuvar koşullarında finansal hesaplama ve birçok hata sınırı doğrulandı. Gerçek kamu verisi doğrulanamadı; kurumsal üstünlük, maliyet tasarrufu veya operasyonel risk azalması kanıtlanmadı. Başarısız ve eksik sonuçlar korunmuştur.

| Soru | Gerçekte gözlenen sonuç | Sonucun sınırı |
|---|---|---|
| Finansal hesaplama doğru mu? | Python 3.12 kaynak ve izole kurulumda ayrı ayrı 875 test geçti. 69 senaryo / 162 değerlendirme ve 373 referans dosyası eşleşti. Bağımsız integer beklentilerle 264 kontrollü vaka uyumlu. | Sonlu sentetik evren; gerçek kurum doğruluğu veya bütün kombinasyonlar için garanti değil. |
| Hataların hepsi yakalanıyor mu? | TP=132, FP=0, TN=120, FN=12; bu evrende recall %91,67. | 12 yanlış negatif, miktarı değiştirmeyen aynı sayılı kimlik ikameleri. Sayı manifestosu içerik kimliğini garanti etmiyor. Gerçek hata oranı değil. |
| Dayanıklılık ne ölçüde gözlendi? | 21 sabit recovery senaryosu ve 33 ek sınır/SQLite kontrolü geçti; gerçek süreç öldürme ve tekrar teslim testleri çalıştı. | Fiziksel güç/disk kaybı, dağıtık exactly-once, kurumsal RTO/RPO ve aylar süren soak kanıtı yok. |
| Alternatiflerden hızlı mı? | 10.000 olay medyanı: uygulama 21,04 sn; dar stdlib 13,57 sn; dar SQLite 12,85 sn. 100/1.000/10.000 olayda 45 tamamlanmış koşu ortak oracle ile eşleşti. | Uygulama daha kapsamlı tarihçe/kanıt üretir. Tam semantik eşitlik sağlanmadığından üstünlük `INCONCLUSIVE`; gözlenen süreler uygulama lehine değil. |
| Büyük profil tamamlandı mı? | 100.000 olaylık tek üretim denemesi 60,065 sn sınırında zaman aşımına uğradı. Program toplam 334,824 sn. | Kalan 100.000 olay koşuları `NOT_RUN`; bu bir replay deneyi veya genel kapasite tahmini değil. |
| Gerçek veride çalıştı mı? | Treasury, SEC ve BIS için 19 resmî istek proxy tünelinde 403 ile engellendi. Alınan gerçek finansal satır ve doğrulanan gerçek eşitlik: 0. | `REAL_DATA_UNVERIFIED`. Kullanıcının örnek değerleri indirilmiş veri gibi kullanılmadı. |

Python 3.14 kaynak koşusunda 875 testten biri mevcut testin senkronizasyon yarışı nedeniyle başarısız oldu. Değişmeyen test üç dar tekrarda geçti; deterministik iki zamanlama tanığı, hata gözetleyicisi ile testin yardımcı gözlemi arasındaki farkı gösterdi. **P2 açık kaldı.** Ayrı Python 3.14 kurulu paket koşusunda 875 test; core ve auth-only kontrolleri geçti. Bunlar ilk başarısız kaynak koşusunu silmez.

Bağımsız denetim, yeni araştırma araçlarında boş/eksik/ikame kapsamın başarı sayılması ve yanlış olay sayısıyla throughput üretilmesi gibi kusurlar buldu. Dar onarımlar ve RED/GREEN kanıtları eklendi; son birleşik araştırma paketi 67 testle geçti; ayrı çevrimdışı smoke da başarılıydı. Üretim kodu, 875 eski test kimliği, finansal referans ve donmuş ML deneyi değişmedi. İki keşif kanıtı dosyasının yanlışlıkla üzerine yazılması ve kullanılan nitelikli yeniden üretimler ayrıca açıklanmıştır.

Gerçek veri alanlarını ve uzaktaki GitHub CI sonuçlarını doğrulamak için izinli ağ erişimi hâlâ gerekiyor. Yerel başarı uzaktaki CI yerine konmadı. Kurum içi işlem/kustodi verisi, doğal hata etiketleri, maliyetler ve olay kayıpları olmadan MKK, Takasbank, BIST veya başka bir kurum hakkında üstünlük ya da uyum sertifikası sonucu çıkarılamaz.

Kanıtlar: [teknik sonuçlar](TECHNICAL_VALIDATION.md), [hata tespiti](ERROR_DETECTION.md), [ölçümler](BASELINE_COMPARISON.md), [gerçek veri](REAL_DATA_VALIDATION.md), [açık konular](OPEN_ISSUES.md), [ayrı kararlar](DECISION.json), [yeniden üretim](../docs/validation/REPRODUCE.md).
