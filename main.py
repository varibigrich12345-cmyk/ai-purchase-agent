from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, Dict, Any
import sqlite3
import httpx
import os

from config import DB_PATH

# Perplexity API
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
PERPLEXITY_MODEL = "sonar-pro"
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


# === Perplexity AI ===
class AskAIRequest(BaseModel):
    partnumber: str
    brand: Optional[str] = None
    prices: Optional[Dict[str, float]] = None
    question: Optional[str] = None  # Новый вопрос пользователя в чате


class AskAIResponse(BaseModel):
    answer: str
    sources: Optional[list] = None


@app.post("/api/ask-ai", response_model=AskAIResponse)
async def ask_ai(request: AskAIRequest):
    """Спросить Perplexity AI о запчасти"""
    if not PERPLEXITY_API_KEY:
        raise HTTPException(status_code=500, detail="PERPLEXITY_API_KEY not configured")

    # Формируем контекст про деталь
    price_info = ""
    if request.prices:
        price_lines = [f"- {site}: {price}₽" for site, price in request.prices.items() if price]
        if price_lines:
            price_info = f"\n\nНайденные цены:\n" + "\n".join(price_lines)

    brand_info = f" бренда {request.brand}" if request.brand else ""

    # Если есть вопрос пользователя - это продолжение чата
    if request.question:
        # Контекст + новый вопрос
        context = f"Контекст: автозапчасть с артикулом {request.partnumber}{brand_info}."
        if price_info:
            context += price_info
        
        prompt = f"""{context}

Пользователь спрашивает: {request.question}

Ответь на вопрос пользователя, используя контекст про эту запчасть. Отвечай на русском языке."""
    else:
        # Первое сообщение - автоматический рассказ про деталь
        prompt = f"""Расскажи про автозапчасть с артикулом {request.partnumber}{brand_info}.

Ответь кратко (3-5 предложений):
1. Что это за деталь и для каких автомобилей
2. Оригинал это или аналог
3. Качество производителя{price_info}

Отвечай на русском языке."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": PERPLEXITY_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                }
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Perplexity API error: {response.text}")

            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "Нет ответа")

            # Извлекаем источники если есть
            sources = None
            if "citations" in data:
                sources = data["citations"]

            return AskAIResponse(answer=answer, sources=sources)

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Perplexity API timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Статические файлы (фронтенд) - ВАЖНО: должно быть в конце, после всех API эндпоинтов!
app.mount("/", StaticFiles(directory=BASEDIR / "sites", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
