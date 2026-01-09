from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from backend.api.tasks_api import router as tasks_router

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

# API роутер
app.include_router(tasks_router, prefix="/api", tags=["tasks"])

# Статические файлы (фронтенд)
app.mount("/", StaticFiles(directory=BASEDIR / "sites", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
