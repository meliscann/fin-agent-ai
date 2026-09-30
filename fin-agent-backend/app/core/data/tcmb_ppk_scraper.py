"""
TCMB PPK (Para Politikası Kurulu) basın duyurularından politika faizi
kararlarını ayrıştırıp policy_rate_history.json ile karşılaştıran,
tek seferlik elle çalıştırılan CLI script'i.

Kullanım:
    python -m app.core.data.tcmb_ppk_scraper --year 2026

Ne yapar:
  1. TCMB'nin PPK arşiv sayfasından (verilen yıl) tüm duyuru linklerini toplar.
  2. Her duyurunun <title> etiketine bakarak "Faiz Oranlarına İlişkin Basın
     Duyurusu" olanları alır; ~1 hafta sonra yayınlanan "Toplantı Özeti"
     sayfalarını atlar (aynı kararı tekrar anlattıkları için sahte/yinelenen
     kayıt oluşturmamak amacıyla).
  3. Duyuru metninden politika faizi kararını iki bilinen cümle kalıbından
     biriyle çıkarır: "...yüzde X'te sabit tutulmasına..." veya
     "...yüzde Y'den yüzde X'e ...mesine karar vermiştir."
  4. Sonucu policy_rate_history.json ile karşılaştırır:
     - JSON'da olmayan yeni tarihleri otomatik ekler.
     - JSON'daki bir değerle çelişen bir şey bulursa ÜZERİNE YAZMAZ, sadece
       uyarı olarak loglar (insan onayı gerektirir).
  5. Sayfa yapısı değişirse veya ağ hatası olursa çökmez; JSON dosyasını
     olduğu gibi bırakıp net bir hata mesajı verir.

Zamanlayıcı/cron YOKTUR — ihtiyaç oldukça elle çalıştırılır.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

BASE_URL = "https://www.tcmb.gov.tr"
INDEX_URL_TMPL = (
    f"{BASE_URL}/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/"
    "Para+Politikasi/PPK/{year}"
)
JSON_PATH = Path(__file__).parent / "policy_rate_history.json"

USER_AGENT = "Mozilla/5.0 (compatible; FinAgent-PPK-Scraper/1.0)"

LINK_RE = re.compile(r'href="([^"]*duy\d{4}-\d+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
SAYI_DATE_RE = re.compile(r"Sayı:\s*\d{4}-\d+\s+(\d{1,2})\s+(\w+)\s+(\d{4})")

# İki bilinen TCMB PPK cümle kalıbı ("politika faizi olan bir hafta vadeli
# repo ihale faiz oranının ..." cümlesiyle sınırlı — gecelik borç
# verme/borçlanma faizi gibi başka oranları yanlışlıkla yakalamamak için).
_APOS = r"[’'‘]?"
_NUM = r"(\d+(?:,\d+)?)"
_PREFIX = r"politika faizi olan bir hafta vadeli repo ihale faiz oranının"

PATTERN_STEADY = re.compile(
    rf"{_PREFIX}\s+yüzde\s*{_NUM}{_APOS}\w*\s+sabit\s+tutul\w*\s+karar\s+vermiştir"
)
PATTERN_CHANGE = re.compile(
    rf"{_PREFIX}\s+yüzde\s*{_NUM}{_APOS}\w*\s+yüzde\s*{_NUM}{_APOS}\w*\s+\S+\s+karar\s+vermiştir"
)

TR_MONTHS = {
    "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6,
    "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12,
}


class ScraperError(Exception):
    pass


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _fetch(url: str, client: httpx.Client) -> str:
    resp = client.get(url, timeout=20.0, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def _parse_date(text: str) -> str | None:
    m = SAYI_DATE_RE.search(text)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = TR_MONTHS.get(month_name)
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def _parse_rate(text: str) -> float | None:
    m = PATTERN_STEADY.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    m = PATTERN_CHANGE.search(text)
    if m:
        return float(m.group(2).replace(",", "."))
    return None


def scrape_year(year: int) -> dict[str, float]:
    """Verilen yıl için TCMB PPK arşivinden {tarih: yüzde_oran} sözlüğü döner."""
    index_url = INDEX_URL_TMPL.format(year=year)
    found: dict[str, float] = {}

    with httpx.Client(follow_redirects=True) as client:
        try:
            index_html = _fetch(index_url, client)
        except Exception as e:
            raise ScraperError(f"Arşiv sayfası çekilemedi ({index_url}): {e}") from e

        hrefs = sorted(set(m.group(1) for m in LINK_RE.finditer(index_html)))
        if not hrefs:
            raise ScraperError(
                f"{year} için arşiv sayfasında hiç duyuru linki bulunamadı — "
                "sayfa yapısı değişmiş olabilir."
            )

        for href in hrefs:
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            try:
                html = _fetch(url, client)
            except Exception as e:
                print(f"  [uyarı] {url} çekilemedi: {e}", file=sys.stderr)
                continue

            title_m = TITLE_RE.search(html)
            title = title_m.group(1) if title_m else ""
            if "Toplantı Özeti" in title:
                continue  # aynı kararın ~1 hafta sonraki özeti — atla
            if "Faiz Oranlarına İlişkin Basın Duyurusu" not in title:
                continue  # faiz kararı duyurusu değil

            text = _clean_text(html)
            date_str = _parse_date(text)
            rate = _parse_rate(text)

            if date_str is None or rate is None:
                print(
                    f"  [uyarı] {url}: tarih veya oran ayrıştırılamadı "
                    "(sayfa yapısı değişmiş olabilir) — atlanıyor.",
                    file=sys.stderr,
                )
                continue

            found[date_str] = rate

    return found


def load_history() -> dict[str, float]:
    if not JSON_PATH.exists():
        return {}
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict[str, float]) -> None:
    ordered = dict(sorted(history.items()))
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
        f.write("\n")


def reconcile(
    existing: dict[str, float], scraped: dict[str, float]
) -> tuple[dict[str, float], list[tuple[str, float]], list[tuple[str, float, float]]]:
    """Yeni tarihleri ekler, çelişkileri sadece loglar (üzerine yazmaz)."""
    updated = dict(existing)
    added: list[tuple[str, float]] = []
    conflicts: list[tuple[str, float, float]] = []

    for date_str, rate in scraped.items():
        if date_str not in existing:
            updated[date_str] = rate
            added.append((date_str, rate))
        elif existing[date_str] != rate:
            conflicts.append((date_str, existing[date_str], rate))

    return updated, added, conflicts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TCMB PPK basın duyurularından politika faizi kararlarını çeker."
    )
    parser.add_argument("--year", type=int, required=True, help="Taranacak yıl (örn. 2026)")
    args = parser.parse_args()

    print(f"TCMB PPK {args.year} arşivi taranıyor...")
    try:
        scraped = scrape_year(args.year)
    except ScraperError as e:
        print(f"HATA: {e}", file=sys.stderr)
        print(f"Mevcut {JSON_PATH.name} değiştirilmedi.", file=sys.stderr)
        sys.exit(1)

    if not scraped:
        print("Hiçbir politika faizi kararı ayrıştırılamadı. JSON değiştirilmedi.")
        sys.exit(1)

    print(f"\n{len(scraped)} karar bulundu:")
    for date_str, rate in sorted(scraped.items()):
        print(f"  {date_str}: %{rate:.2f}")

    existing = load_history()
    updated, added, conflicts = reconcile(existing, scraped)

    if conflicts:
        print(
            f"\n[UYARI] {len(conflicts)} çelişki bulundu "
            f"(JSON değiştirilMEDİ, insan onayı gerekli):"
        )
        for date_str, old, new in conflicts:
            print(f"  {date_str}: JSON'da %{old:.2f} var, sitede %{new:.2f} bulundu")

    if added:
        save_history(updated)
        print(f"\n{len(added)} yeni kayıt eklendi, {JSON_PATH.name} güncellendi:")
        for date_str, rate in added:
            print(f"  + {date_str}: %{rate:.2f}")
    else:
        print("\nEklenecek yeni kayıt yok, JSON değiştirilmedi.")


if __name__ == "__main__":
    main()
