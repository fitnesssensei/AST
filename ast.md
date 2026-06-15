# Проект для парсинга книг с сайта ast.ru

# zapusk neyrosety
cline
                                                            # or
                                                            cline "your task"


начал 20:34 1000-2000

# Все 2355 страниц (полный парсинг)
nohup python3 -u ast_parser.py 1 2355 -w 5 > parse.log 2>&1 &
# Только 1-500
nohup python3 -u ast_parser.py 1 500 -w 5 > parse.log 2>&1 &
# Только 500-1000
nohup python3 -u ast_parser.py 500 1000 -w 5 > parse.log 2>&1 &
# 1000-1500 + перемешанный порядок (снижает нагрузку на сервер)
nohup python3 -u ast_parser.py 1000 1500 -w 5 --shuffle > parse.log 2>&1 &
# 1500-2355
nohup python3 -u ast_parser.py 1500 2355 -w 5 > parse.log 2>&1 &

## Очень важно

- отвечай только на русском языке
- оставляй много комментариев в коде на русском языке
- система macBook pro m4 pro
- 
## новый
python3 ast_parser.py                          # все 2348 страниц, 5 воркеров
python3 ast_parser.py 100                      # первые 100 страниц
python3 ast_parser.py 10 50                    # страницы 10-50
python3 ast_parser.py 10 50 -w 8               # диапазон + 8 воркеров
python3 ast_parser.py 1 100 -w 10 --shuffle    # 10 воркеров + перемешанный порядок
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
    --output books100.json \
    --limit 100 \
    --pretty
    --timeout 60

# Продолжение после прерывания — просто запустить ту же команду ещё раз.
# Очистить прогресс: rm books.progress.json