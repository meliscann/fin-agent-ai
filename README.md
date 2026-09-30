# FinAgent

**Türk bireysel yatırımcısına yönelik, yüksek enflasyon ve kur oynaklığı ortamında portföy analizi yapan AI destekli yatırım asistanı.**

> "Paramı enflasyondan nasıl korurum?"

FinAgent, elinizdeki birikimi hangi varlıklara (altın, döviz, BIST 100, tahvil, TÜFE'ye endeksli tahvil, mevduat) dağıtırsanız enflasyona karşı en iyi korunacağınızı; 1000 senaryolu Monte Carlo simülasyonuyla test eder, yapay zeka destekli öneriler sunar ve sonucu **Enflasyon Koruma Skoru (IPS)** adlı özgün bir metrikle 0-100 arası tek bir sayıya indirger.

---

## Özellikler

- **Portföy Simülatörü** — varlık dağılımınızı kaydırıcılarla ayarlayın, 1000 senaryolu Monte Carlo simülasyonuyla beklenen değer/reel getiri/en kötü-en iyi senaryoları anında görün
- **Enflasyon Koruma Skoru (IPS)** — portföyünüzün enflasyonu yenme olasılığını 0-100 arası tek bir skora indirgeyen özgün metrik
- **5 uzman AI ajanı** — portföy analizi, risk profiline göre öneri, Türkçe doğal dil soru-cevap, PDF rapor üretimi, eşik tabanlı uyarılar
- **Hızlı senaryolar** — "Dolar %25 güçlenirse?", "Enflasyon 15 puan yüksek çıkarsa?" gibi gerçek makro şokları tek tıkla test edin
- **Portföy karşılaştırma** — mevcut portföyünüzü farklı bir risk profiliyle yan yana kıyaslayın
- **Piyasa Analizi** — TCMB EVDS ve Yahoo Finance'ten canlı çekilen verilerle 2020'den bugüne varlık performansı, enflasyon/politika faizi karşılaştırması, geçmişe dönük backtest
- **Canlı veri** — USD/TRY, altın, BIST 100, TÜFE ve politika faizi gerçek zamanlı kaynaklardan (TCMB EVDS, Yahoo Finance)

---

## Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| Frontend | Next.js 14, React 18, Tailwind CSS, Recharts |
| Backend | Python 3.11, FastAPI |
| Yapay Zeka | Groq API (`openai/gpt-oss-120b`) |
| Analiz | NumPy, Pandas |
| Veri | TCMB EVDS API, Yahoo Finance |
| Test | pytest (87 test) |

---

## Kurulum ve Çalıştırma

### Gereksinimler
- Python 3.11+ (conda önerilir)
- Node.js 18+
- [TCMB EVDS](https://evds3.tcmb.gov.tr/) API anahtarı (ücretsiz kayıt)
- [Groq](https://console.groq.com/) API anahtarı (ücretsiz katman mevcut)

### Backend

```bash
cd fin-agent-backend
conda create -n fin-agent-backend python=3.11
conda activate fin-agent-backend
pip install -r requirements.txt

cp .env.example .env
# .env dosyasını açıp GROQ_API_KEY ve TCMB_API_KEY'i kendi anahtarlarınızla doldurun

uvicorn app.main:app --reload
# → http://localhost:8000/docs (API dokümantasyonu)
```

### Frontend

```bash
cd fin-agent-frontend
npm install

echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
# → http://localhost:3000
```

### Testler

```bash
cd fin-agent-backend
pytest tests/ -v
```
87 test, ~1 saniyede biter — ağ/LLM çağrısı yapmaz, tamamı mock'lu.

---

## Proje Yapısı

```
fin-agent-backend/     ← FastAPI backend (portföy analizi, AI ajanları, veri entegrasyonları)
fin-agent-frontend/    ← Next.js dashboard (portföy simülatörü + piyasa analizi arayüzü)
veri_analizi.ipynb     ← Vaka çalışması notebook'u — TCMB EVDS/Yahoo Finance veri analizi,
                          Monte Carlo, backtest, karar matrisi (Jupyter ile açılabilir)
```

---

## Vaka Çalışması

Proje, `veri_analizi.ipynb` içindeki bağımsız bir veri analizi çalışmasını temel alır: TCMB EVDS ve Yahoo Finance üzerinden 2020'den bugüne enflasyon, döviz kuru, altın ve BIST 100 verilerinin analizi, geçmişe dönük backtest ve yatırım araçları karar matrisi. Notebook, `evds`, `yfinance`, `pandas`, `matplotlib` ve `seaborn` kütüphaneleriyle çalışır.

---

**Geliştiren:** Melis Can
