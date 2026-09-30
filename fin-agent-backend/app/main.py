"""
FinAgent — Backend API
FastAPI uygulaması giriş noktası.

Çalıştırma:
    uvicorn app.main:app --reload --port 8000

Dokümantasyon:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import portfolio, agents, data, insights

logger = logging.getLogger("finagent.startup")

# PPK taramasını her --reload'da tekrar tetiklememek için basit bir bekleme
# süresi — TCMB'nin sitesine gereksiz yere sık istek atmayı önler.
_LAST_CHECK_PATH = Path(__file__).parent / "core" / "data" / ".policy_rate_last_check"
_CHECK_COOLDOWN = timedelta(hours=24)


async def _check_policy_rate_updates() -> None:
    """
    Uygulama açılışında TCMB PPK arşivini (bu yılki kararlar) tarar, JSON'da
    olmayan yeni bir karar varsa ekler. Son 24 saat içinde zaten
    kontrol edildiyse atlar. Ağ hatası olursa sessizce loglar, uygulamanın
    açılışını hiçbir şekilde engellemez/geciktirmez (arka planda çalışır).
    """
    try:
        if _LAST_CHECK_PATH.exists():
            last_check = datetime.fromisoformat(_LAST_CHECK_PATH.read_text().strip())
            if datetime.now() - last_check < _CHECK_COOLDOWN:
                logger.info("Politika faizi: son 24 saatte kontrol edilmiş, atlanıyor.")
                return

        from app.core.data.tcmb_ppk_scraper import scrape_year, load_history, save_history, reconcile

        year = datetime.now().year
        scraped = await asyncio.to_thread(scrape_year, year)
        existing = load_history()
        updated, added, conflicts = reconcile(existing, scraped)

        if added:
            save_history(updated)
            logger.info(f"Politika faizi: {len(added)} yeni kayıt eklendi ({year}) — {[d for d, _ in added]}")
        if conflicts:
            logger.warning(f"Politika faizi: {len(conflicts)} çelişki bulundu, JSON değiştirilmedi (insan onayı gerekli).")
        if not added and not conflicts:
            logger.info("Politika faizi: güncel, yeni kayıt yok.")

        _LAST_CHECK_PATH.write_text(datetime.now().isoformat())
    except Exception as e:
        # Mevcut policy_rate_history.json'a dokunulmadı — bu sadece bir
        # tazeleme denemesiydi, başarısız olması uygulamayı etkilemez.
        logger.warning(f"Politika faizi otomatik kontrolü başarısız (önemli değil): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_check_policy_rate_updates())
    yield


app = FastAPI(
    title="FinAgent",
    description="Belirsizlik ortamında bireysel yatırım asistanı",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — frontend (Next.js) ile iletişim için
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları kaydet
app.include_router(portfolio.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(insights.router, prefix="/api")


@app.get("/", tags=["root"])
async def root():
    return {
        "app": "FinAgent",
        "version": "1.0.0",
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
async def health():
    return {"status": "ok"}
