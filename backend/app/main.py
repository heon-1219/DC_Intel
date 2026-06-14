from fastapi import FastAPI

from app.routers import health, stocks


def create_app() -> FastAPI:
    app = FastAPI(title="DC Intel API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(stocks.router)
    return app


app = create_app()
