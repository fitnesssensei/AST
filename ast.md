# Проект для парсинга книг с сайта ast.ru

## Очень важно

- отвечай только на русском языке
- оставляй много комментариев в коде на русском языке
- система macBook pro m4 pro
- 

# Активируем виртуальное окружение
source venv/bin/activate.fish  # для macOS

## Активация парсера
# Запустить полный парсинг (2348 страниц)
python3 ast_parser.py

# Парсить конкретный диапазон
python3 ast_parser.py 1 5

# Первые 5 страниц
python3 ast_parser.py 5

# Нужные данные
"title"
"author"
"isbn"
"description"
"year"
"pages"
"cover"
"series"
"thickness"
"format"

## Воркер для массового сбора по списку URL
# Полный список книг (~1 000 000 URL) лежит в sparseno/book_links1111.txt и подобных
# Подробная документация — в worker/README.md
#
# Базовый запуск:
python3 -m worker --input sparseno/book_links1111.txt
# С параметрами (рекомендуется для 1М URL):
python3 -m worker --input sparseno/book_links.txt \
    --concurrency 50 \
    --output books100.jsonl \
    --limit 100 \
    --pretty
    --timeout 60

# Продолжение после прерывания — просто запустить ту же команду ещё раз.
# Очистить прогресс: rm books.progress.json