from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path
from typing import Optional, Dict, Any
import sqlite3

from config import DB_PATH
from backend.api.tasks_api import router as tasks_router
from backend.api.brands_api import router as brands_router

BASEDIR = Path(__file__).resolve().parent

app = FastAPI(title="AI Purchase Agent API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API роутеры
app.include_router(tasks_router, prefix="/api", tags=["tasks"])
app.include_router(brands_router, prefix="/api", tags=["brands"])

# НОВОЕ: Редирект с корня на tasks.html
@app.get("/")
async def root():
    return RedirectResponse(url="/tasks.html")

# Статические файлы (фронтенд)
app.mount("/", StaticFiles(directory=BASEDIR / "sites", html=True), name="static")


@app.get("/api/article-brands")
async def get_article_brands(partnumber: Optional[str] = None) -> Dict[str, Any]:
    """Возвращает бренды, найденные ранее для этого артикула"""
    if not partnumber:
        return {"brands": []}

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT brand FROM tasks
            WHERE LOWER(partnumber) = LOWER(?)
              AND brand IS NOT NULL
              AND brand != ''
            """,
            (partnumber,),
        )
        brands = [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

    return {"brands": brands}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
