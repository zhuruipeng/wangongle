import logging
import os

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import UPLOAD_DIR, get_db
from .middleware import RequestIDMiddleware
from .routers import orders
from .routers.auth import router as auth_router
from .services.rate_limit import create_redis_client
from .settings import get_auth_settings, get_redis_settings

logger = logging.getLogger(__name__)
api_router = APIRouter()


@api_router.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="service unavailable") from None
    return {"status": "ok"}


def create_app() -> FastAPI:
    get_auth_settings()
    application = FastAPI(title="干完了本地开发 API", version="0.1.0")
    application.state.redis = create_redis_client(get_redis_settings())
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.getenv(
                "GANWANLE_CORS_ORIGINS",
                "http://localhost:10086,http://127.0.0.1:10086",
            ).split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestIDMiddleware)
    application.include_router(api_router)
    application.include_router(auth_router)
    application.include_router(orders.router, prefix="/api/v1/service-orders")
    application.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "") or "unknown"
        logger.error("Unhandled request error request_id=%s", request_id)
        if os.getenv("GANWANLE_ENV", "development").strip().lower() == "production":
            return JSONResponse(
                status_code=500,
                content={"detail": "服务暂时不可用", "request_id": request_id},
            )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    return application


app = create_app()
