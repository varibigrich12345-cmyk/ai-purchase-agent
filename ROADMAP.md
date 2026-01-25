# Roadmap: Улучшение процесса разработки

## 1. Unit-тесты для парсеров
- [ ] tests/test_zzap.py
- [ ] tests/test_trast.py
- [ ] tests/test_stparts.py
- [ ] tests/test_autovid.py
- [ ] tests/test_autotrade.py

Каждый тест проверяет:
- Извлечение цены из HTML
- Фильтрацию б/у товаров
- Обработку "Заказ от"
- Фильтрацию по бренду

## 4. Staging окружение
- [ ] docker-compose.staging.yml
- [ ] Отдельная база данных
- [ ] Тестирование перед production

## 5. Мониторинг и алерты
- [ ] Логирование в файл
- [ ] Алерты при timeout > 50%
- [ ] Дашборд статистики парсеров
