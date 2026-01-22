# AI Purchase Agent — Контекст для Claude

## Стек
- Backend: FastAPI + Python 3.11
- Frontend: Vanilla JS (sites/tasks.html)
- База: SQLite (tasks.db, price_history)
- Парсинг: Playwright (headless Chromium)
- AI: Perplexity API (sonar-pro)
- Deploy: Docker + nginx на VPS 62.113.37.2

## Структура проекта
- main.py — FastAPI endpoints (/api/tasks, /api/ask-ai, /api/price-history)
- worker.py — фоновый парсер цен
- database.py — работа с SQLite
- sites/tasks.html — фронтенд (PWA)
- backend/api/ — роутеры API

## Парсеры (5 источников)
✅ ZZAP, STparts, Trast, AutoVID, AutoTrade

## Правила кода
- Комментарии на русском
- API возвращает JSON с полем answer (не объект целиком)
- Тесты: pytest
- Перед коммитом: проверить синтаксис JS (была ошибка try без catch)

## Деплой
```bash
git add -A && git commit -m "message" && git push
ssh root@62.113.37.2 "cd /opt/ai-purchase-agent && git pull && docker-compose restart web"
```

## Текущие фичи
- Поиск цен по артикулу/бренду
- AI-чат с Perplexity (работает!)
- История цен (price_history)
- PWA для мобильных

## TODO
- [ ] Голосовой ввод (Web Speech API) — на iOS PWA не работает
- [ ] CSV импорт/экспорт
- [ ] Уведомления о снижении цен

