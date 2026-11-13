# Beş dakikalık teknik anlatım

Bu projede tek bir soruyu ele alıyorum: işlem defterinden hesaplanan müşteri
bakiyeleri, platformun bildirdiği bakiyeler ve müşteriler adına saklanan varlıklar
birbirini doğruluyor mu? Çalışma sentetik bir referans model. Kurumların mevcut
sistemlerinde bir eksik olduğunu, resmî KVMKS uyumunu veya üretim hazırlığını
iddia etmiyorum.

İki kontrolü ayrı tutuyorum. A kontrolü her yatırımcının defter bakiyesini kendi
bakiye raporuyla karşılaştırıyor. B kontrolü defterden türetilen toplam müşteri
yükümlülüğünü platform müşteri cüzdanı ve dış saklamacı toplamıyla karşılaştırıyor.
Öz varlıklar bu toplamda yok. Varlıklar birbirinin farkını kapatmıyor; miktarlar
Decimal ile hesaplanıyor ve kanıtlarda tam metin olarak korunuyor.

İkinci mesele zaman. Ekonomik olayın gerçekleşmesi ile sistemin olayı öğrenmesi
aynı şey değil. `occurred_at` ve `received_at` bu ayrımı tutuyor; `balance_at` ile
`knowledge_at` hangi bakiye anını, hangi bilgi kesitiyle değerlendirdiğimizi
belirliyor. Geç gelen çekim, önceki değerlendirmeyi değiştirmiyor. Manifesto
kapsamın eksik olduğunu gösteriyorsa sonuç kesin açık yerine
`INCOMPLETE / NOT_EVALUATED` oluyor. Kayıt geldiğinde yeni bir değerlendirme
üretiliyor ve eski kanıtlar yerinde kalıyor.

Düzeltmelerde de aynı ayrım var. Geçmiş bir işlem tutarının düzeltilmesi,
yatırımcı raporunu veya saklama raporunu kendiliğinden düzeltmiyor. Bu raporların
ayrı sürümleri ve öğrenilme zamanları var. Offline inceleme ekranı kayıtlı
sonuçları gösteriyor; bugünkü verilerle geçmişi yeniden hesaplamıyor. Bir bulgudan
seçilen rapora, işlem izine ve alınan mesaja geri gidilebiliyor.

Performans iddiasını ölçümün sınırında tutuyorum. Tarihsel 0.3.2/0.3.3 deneyinde
tek değişiklik `receipt_hash` indeksi. 10.000 olay ve 20 yatırımcılı P2 örneğinde
mutabakat ve kaydetme medyanı 4,725224 saniyeden 1,052749 saniyeye indi; azalma
%77,72. Ancak veri alma medyanı %5,24 arttı. Her varyantta yalnız üç normal
ölçüm var; P3 finansal faz toplamı %8,48 kötüleşti. Süreç genelindeki beklemeler
nedeniyle bunu sistemin tamamında güvenilir uçtan uca hızlanma diye sunmuyorum.
[Orijinal yorum ve koşullar](evidence/stage3_3-performance_interpretation.md)
seçilmiş tarihsel kanıtlarda korunuyor; Aşama 6 yeni benchmark çalıştırmıyor.

AI bölümünde de sonucu olumlu göstermek için ölçüt değiştirmiyorum. Önceden
sabitlenmiş LogisticRegression modeli, kurallara göre testte 0, challenge'da
−2,083 yüzde puan fark üretti. Bu sentetik deneyde ek fayda gösterilmedi.
Aynı gözlenen geçmişin farklı geleceklere açıldığı çiftler, mevcut bilgiyle
hangi ayrımın yapılamadığını görünür kılıyor. Düşük skor bir bulguyu kapatmıyor.
[Kaydedilmiş değerlendirme](evidence/stage5-evaluation.md) yeni sürümün ölçümü
olarak yeniden etiketlenmiyor; ana model tekrar eğitilmiyor.

Bakım aşamasında üç sınır hatası kapatıldı: Decimal dış bağlamı uzun sayıları
ve sıralamayı etkiliyordu; provenance özet zamanı iç kaynak zamanı ile
çelişebiliyordu; kendi içinde tutarlı bir altküme tam deney gibi kabul
edilebiliyordu. Her biri önce gerçek kırmızı regresyonla gösterildi, sonra aynı
regresyonla doğrulandı. Onarımlar sırasıyla bağlamdan bağımsız işaret işlemleri,
her kaynağın zaman ve bağlantı kontrolü, bağımsız public episode×asset kapsamı
kontrolü oldu. Eski modelin olumsuz sonucu değişmedi.

İncelemek için Python 3.12 veya üzeriyle kaynak dizininde şu komut yeterli:

```sh
python scripts/reproduce_review.py --output review-new
```

Yeni dizindeki `index.md`, dokuz demo ve 24 kayıtlı değerlendirmeyi gösteren
HTML'e ve küçük JSON-model sıralamasına yönlendiriyor. Beklenen sentetik
`MISMATCH` bir uygulama hatası değil. Bozuk H/T örneği ise exit 2 vermeli ve
başarılı queue üretmemeli. Wheel doğrulaması ayrıca kaynak dışı çalışma dizini,
`-I` ve gerçek site-packages import konumuyla yapılıyor.

GitHub Actions dosyası Python 3.12 ve 3.14 için hazırlanmış olsa da bu görevde
remote CI çalıştırılmadı: durumu `NOT_RUN`. Yerel test sonuçları, tarihsel
ölçümler ve hazırlanmış CI hücreleri ayrı raporlanıyor. Amaç finansal veri
mühendisliği kararlarını, hataları ve kanıt sınırlarını incelemeye açmak.
