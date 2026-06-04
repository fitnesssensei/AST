"""
================================================================================
ПАРСЕР ССЫЛОК НА ТОВАРЫ С САЙТА AST.RU
================================================================================

Описание:
    Парсер собирает ссылки на книги с каталога художественной литературы
    издательства АСТ (ast.ru). Всего на сайте 2348 страниц каталога.
    
Технологии:
    - Playwright: для рендеринга JavaScript (сайт динамический)
    - asyncio: для асинхронной работы
    
Особенности:
    - Автоматически дожидается загрузки контента
    - Сохраняет результаты в файл
    - Поддерживает частичный парсинг (диапазон страниц)
    - Не нагружает сервер (пауза между запросами)

Запуск:
    python3 ast_parser.py              # все 2348 страниц
    python3 ast_parser.py 100          # первые 100 страниц
    python3 ast_parser.py 10 50        # страницы с 10 по 50

Пример результата:
    https://ast.ru/book/1984-866365/
    https://ast.ru/book/akademiya-futbola-glupaya-travma-877306/
    https://ast.ru/book/amerikanskie-bogi-879178/
================================================================================
"""
import asyncio
import re
import sys
from pathlib import Path
from typing import Set
import random
from playwright.async_api import async_playwright
import logging

# ==============================================================================
# КОНФИГУРАЦИЯ
# ==============================================================================

# Базовый URL каталога художественной литературы
BASE_URL = "https://ast.ru/cat/khudozhestvennaya-literatura/"

# Всего страниц в каталоге (указано на сайте)
MAX_PAGES = 2348

# Имя выходного файла для сохранения ссылок
OUTPUT_FILE = Path(__file__).parent / "book_links.txt"

# ==============================================================================
# НАСТРОЙКИ USER-AGENT
# ==============================================================================

# Список User-Agent ов реальных браузеров для ротации
# Каждый запрос будет выглядеть как от другого браузера/устройства
USER_AGENTS = [
    # macOS Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # macOS Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # macOS Firefox
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0",
    # Windows Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Windows Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Windows Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    # Linux Chrome
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    """
    Возвращает случайный User-Agent из списка USER_AGENTS.

    Зачем это нужно:
        Сайты отслеживают User-Agent и могут заблокировать,
        если все запросы идут с одного и того же.
        Ротация User-Agent ов делает бота похожим на реальных
        пользователей с разных устройств и браузеров.

    Returns:
        Строка с случайным User-Agent ом
    """
    return random.choice(USER_AGENTS)


# Настройка логирования: показываем время, уровень и сообщение
logging.basicConfig(
    level=logging.INFO,  # Уровень логирования (DEBUG, INFO, WARNING, ERROR)
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ==============================================================================
# ФУНКЦИИ ДЛЯ ОБРАБОТКИ АРГУМЕНТОВ КОМАНДНОЙ СТРОКИ
# ==============================================================================

def parse_args():
    """
    Парсит аргументы командной строки и возвращает диапазон страниц для парсинга.
    
    Поддерживаемые форматы:
        - Без аргументов: с 1 по MAX_PAGES (все страницы)
        - 1 аргумент: с 1 по N
        - 2 аргумента: с N по M
    
    Returns:
        tuple: (start_page, end_page) - начальная и конечная страница
    
    Примеры:
        python3 ast_parser.py        -> (1, 2348)
        python3 ast_parser.py 10     -> (1, 10)
        python3 ast_parser.py 5 15   -> (5, 15)
    """
    # Получаем количество аргументов (без имени скрипта)
    # sys.argv[0] = имя файла, sys.argv[1] = первый аргумент и т.д.
    arg_count = len(sys.argv) - 1
    
    # Вариант 1: нет аргументов - парсим все страницы
    if arg_count == 0:
        logger.info("Аргументы не указаны, парсим все страницы")
        return 1, MAX_PAGES
    
    # Вариант 2: один аргумент - парсим с 1 до указанного числа
    elif arg_count == 1:
        n = int(sys.argv[1])  # Преобразуем строку в число
        logger.info(f"Указан один аргумент: парсим страницы 1-{n}")
        return 1, n
    
    # Вариант 3: два аргумента - парсим с N по M
    elif arg_count == 2:
        start = int(sys.argv[1])
        end = int(sys.argv[2])
        logger.info(f"Указаны два аргумента: парсим страницы {start}-{end}")
        return start, end
    
    # Вариант 4: слишком много аргументов - показываем справку
    else:
        print("\n" + "=" * 60)
        print("ОШИБКА: Слишком много аргументов!")
        print("=" * 60)
        print("\nПравильное использование:")
        print("  python3 ast_parser.py              # все 2348 страниц")
        print("  python3 ast_parser.py 100          # первые 100 страниц")
        print("  python3 ast_parser.py 10 50        # страницы с 10 по 50")
        print("\n" + "=" * 60)
        sys.exit(1)  # Выход с кодом ошибки 1


# ==============================================================================
# ФУНКЦИИ ДЛЯ ИЗВЛЕЧЕНИЯ ССЫЛОК
# ==============================================================================

def extract_book_links(html: str) -> Set[str]:
    """
    Извлекает ссылки на книги из HTML-кода страницы.
    
    Как это работает:
        1. Ищет в HTML все ссылки вида /book/название-id/
        2. Преобразует их в полные URL: https://ast.ru/book/...
        3. Возвращает уникальные ссылки (множество Set)
    
    Args:
        html: HTML-код страницы каталога
        
    Returns:
        Множество уникальных ссылок на книги
        
    Пример найденной ссылки:
        Исходный HTML: <a href="/book/1984-866365/">1984</a>
        Результат: https://ast.ru/book/1984-866365/
    """
    # Если HTML пустой или None - возвращаем пустое множество
    if not html:
        return set()
    
    # Ищем ВСЕ возможные форматы ссылок на книги
    # Анализируем HTML разными способами для максимального охвата
    
    # Способ 1: Классические ссылки /book/название-id/
    pattern1 = re.compile(r'/book/[^"<>\s]+-\d+/')
    matches1 = pattern1.findall(html)
    
    # Способ 2: Ссылки /book/...-id без слеша в конце
    pattern2 = re.compile(r'/book/[^"<>\s]+-\d+')
    matches2 = pattern2.findall(html)
    
    # Способ 3: Ищем любые href со словом book внутри кавычек
    pattern3 = re.compile(r'href="[^"]*book[^"]*"')
    matches3 = pattern3.findall(html)
    
    # Объединяем все результаты и удаляем дубликаты
    all_matches = set()
    
    # Добавляем совпадения из способов 1 и 2
    for m in matches1 + matches2:
        all_matches.add(f"https://ast.ru{m}")
    
    # Добавляем совпадения из способа 3 (извлекаем URL из href="...")
    for m in matches3:
        # Извлекаем URL из href="url"
        url = m.replace('href="', '').replace('"', '')
        if url.startswith("/"):
            all_matches.add(f"https://ast.ru{url}")
        elif url.startswith("http"):
            all_matches.add(url)
    
    # Нормализуем и фильтруем ссылки
    cleaned = set()
    for link in all_matches:
        # Убираем trailing slash для нормализации
        normalized = link.rstrip("/")
        
        # Оставляем ТОЛЬКО ссылки на книги формата /book/...-id
        # Отбрасываем:
        #   - /cat/audiobooks/  (аудиокниги)
        #   - /cat/ebooks/      (электронные книги)
        #   - /cat/...          (любые другие категории)
        #   - любые ссылки без /book/ в пути
        if "/book/" not in normalized:
            continue
        
        # Проверяем, что это именно ссылка на книгу (содержит ID)
        # Формат: https://ast.ru/book/название-id
        if not re.search(r'/book/[^/]+-\d+$', normalized):
            continue
        
        cleaned.add(normalized)
    
    # Возвращаем нормализованные ссылки
    return {link + "/" for link in cleaned}



# ==============================================================================
# ФУНКЦИИ ДЛЯ ЗАГРУЗКИ СТРАНИЦ
# ==============================================================================

async def fetch_page(browser, page_num: int) -> str | None:
    """
    Загружает одну страницу каталога и возвращает её HTML.

    Как это работает:
        1. Создаёт новый контекст браузера со случайным User-Agent'ом
        2. Формирует URL с параметром ?PAGEN_1=N (Bitrix пагинация)
        3. Открывает страницу в браузере (Playwright)
        4. Ждёт случайную задержку для полной загрузки контента
        5. Закрывает контекст (чтобы каждый запрос был как новый пользователь)
        6. Возвращает HTML-код страницы

    Зачем новый контекст для каждой страницы:
        - Каждый контекст имеет свой User-Agent (имитация разных устройств)
        - Контекст не хранит cookies/сессии между страницами
        - Сайт видит каждый запрос как от нового посетителя

    Args:
        browser: Объект браузера Playwright (chromium)
        page_num: Номер страницы каталога для загрузки

    Returns:
        HTML-код страницы или None в случае ошибки

    Пример URL:
        Страница 1: https://ast.ru/cat/khudozhestvennaya-literatura/?PAGEN_1=1
        Страница 50: https://ast.ru/cat/khudozhestvennaya-literatura/?PAGEN_1=50
    """
    # Формируем URL страницы
    # ?PAGEN_1= - параметр пагинации для Bitrix (CMS сайта)
    url = f"{BASE_URL}?PAGEN_1={page_num}"

    try:
        logger.info(f"Страница {page_num}: Начинаю загрузку {url}")

        # Создаём НОВЫЙ контекст браузера со случайным User-Agent'ом
        # Это ключевой момент: каждый запрос выглядит как от другого пользователя
        ua = get_random_user_agent()
        logger.info(f"Страница {page_num}: User-Agent: {ua[:50]}...")
        
        # Создаём контекст с большим viewport (1920x1080)
        # Чем больше viewport, тем больше контента сайт может загрузить сразу
        context = await browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080}
        )

        # Создаём новую страницу (вкладку) в этом контексте
        page = await context.new_page()

        # Переходим по URL с ожиданием полной загрузки
        # networkidle - ждём, пока не останется сетевых запросов
        # timeout=90000 - таймаут 90 секунд на загрузку
        await page.goto(url, timeout=90000, wait_until="networkidle")
        logger.info(f"Страница {page_num}: Загружена, жду рендеринг...")

        # Ждём 2–4 секунды для полной загрузки JavaScript контента
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # Прокручиваем страницу, чтобы активировать lazy loading
        await scroll_page(page, page_num)

        # Дополнительное ожидание для подгрузки контента после скролла
        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Получаем HTML-код страницы после рендеринга
        html = await page.content()
        logger.info(f"Страница {page_num}: HTML получен ({len(html)} байт)")

        # Закрываем контекст (вместе с cookies, сессией, кэшем)
        await context.close()

        return html

    except Exception as e:
        # Логируем ошибку, но не прерываем парсинг
        logger.error(f"Страница {page_num}: Ошибка загрузки - {e}")
        return None


async def scroll_page(page, page_num: int):
    """
    Плавно прокручивает страницу сверху вниз мелкими шагами,
    чтобы активировать ленивую загрузку (lazy loading) книг.

    ast.ru использует динамическую подгрузку контента при скролле.
    Без скролла парсер видит только первые 5-9 книг.
    С правильным скроллом — все 20-40 книг на странице.

    Как это работает:
        1. Прокручиваем страницу на 600px (половина экрана)
        2. Ждём 200-500ms, чтобы контент успел загрузиться
        3. Повторяем, пока не дойдём до самого низа
        4. Делаем 3 прохода для гарантии полной загрузки

    Args:
        page: Объект страницы Playwright
        page_num: Номер страницы (только для логирования)
    """
    # Делаем 3 прохода скролла для гарантии полной загрузки
    for pass_num in range(3):
        await page.evaluate("""
            async () => {
                const totalHeight = document.body.scrollHeight;
                const step = 600;  // шаг 600px для более плавного скролла
                let currentPosition = 0;

                // Скролл вниз мелкими шагами
                while (currentPosition < totalHeight) {
                    window.scrollTo(0, currentPosition);
                    await new Promise(r => setTimeout(r, 200));
                    currentPosition += step;
                }

                // Дополнительная пауза внизу
                await new Promise(r => setTimeout(r, 400));

                // Скролл наверх для следующего прохода
                window.scrollTo(0, 0);
                await new Promise(r => setTimeout(r, 200));
            }
        """)
        logger.info(f"Страница {page_num}: Проход скролла {pass_num + 1}/3 завершён")

    logger.info(f"Страница {page_num}: Скролл полностью завершён")


# ==============================================================================
# ОСНОВНАЯ ФУНКЦИЯ ПАРСИНГА
# ==============================================================================

async def main():
    """
    Главная функция парсера.
    
    Алгоритм работы:
        1. Получает диапазон страниц из аргументов
        2. Запускает браузер через Playwright
        3. Проходит по всем страницам диапазона
        4. Извлекает ссылки на книги с каждой страницы
        5. Сохраняет результаты в файл
    
    Процесс:
        - Каждые 50 страниц промежуточное сохранение
        - Пауза 1 секунда между запросами (не нагружать сервер)
        - При ошибке страница пропускается, парсинг продолжается
    """
    # Получаем диапазон страниц для парсинга
    start_page, end_page = parse_args()
    
    # Вычисляем общее количество страниц
    total_pages = end_page - start_page + 1
    
    # Логируем начало работы
    logger.info("=" * 50)
    logger.info(f"НАЧАЛО ПАРСИНГА")
    logger.info(f"Страницы: {start_page} - {end_page} ({total_pages} шт.)")
    logger.info(f"Выходной файл: {OUTPUT_FILE}")
    logger.info("=" * 50)
    
    # Множество для хранения всех ссылок (автоматически убирает дубликаты)
    all_links: Set[str] = set()
    
    # Проверяем, есть ли уже собранные ссылки
    # Это позволяет продолжить парсинг после прерывания
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            # Читаем все строки, убираем пустые и пробелы
            all_links = {line.strip() for line in f if line.strip()}
        logger.info(f"Загружено {len(all_links)} существующих ссылок из файла")
    
    # Запускаем Playwright для автоматизации браузера
    logger.info("Запускаю Playwright...")
    async with async_playwright() as p:
        # Запускаем Chromium в безголовом режиме ( headless=True )
        # Безголовый режим работает быстрее и не показывает окно браузера
        logger.info("Запускаю браузер Chromium...")
        browser = await p.chromium.launch(
            headless=True  # headless=True - безголовый режим (без окна браузера)
        )

        logger.info("Браузер готов, начинаю парсинг...")
        logger.info("Для каждой страницы будет создан новый контекст со случайным User-Agent")
        logger.info("Это имитирует поведение разных пользователей с разных устройств")
        
        # Проходим по каждой странице каталога
        for page_num in range(start_page, end_page + 1):
            
            # Загружаем страницу и получаем HTML
            html = await fetch_page(browser, page_num)
            
            # Если страница загрузилась успешно - извлекаем ссылки
            if html:
                # Извлекаем ссылки из HTML
                links = extract_book_links(html)
                
                # Добавляем в общее множество (дубликаты автоматически уберутся)
                all_links.update(links)
                
                # Логируем результат (только для отладки)
                logger.info(f"Страница {page_num}: +{len(links)} ссылок (всего: {len(all_links)})")
            
            # Каждые 10 страниц — логируем прогресс и сохраняем промежуточный результат
            current_num = page_num - start_page + 1
            if current_num % 10 == 0:
                logger.info(f"Прогресс: {current_num}/{total_pages} страниц обработано")
                
                # Промежуточное сохранение (на случай прерывания)
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    for link in sorted(all_links):
                        f.write(f"{link}\n")
            
            # Случайная пауза 2–5 секунд между запросами
            # Это важно, чтобы не нагружать сервер и не получить бан
            # Случайное значение имитирует поведение реального пользователя
            await asyncio.sleep(random.uniform(2.0, 5.0))
        await browser.close()
    
    # Финальное сохранение всех ссылок в файл
    # Сортируем для удобства чтения
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for link in sorted(all_links):
            f.write(f"{link}\n")
    
    # Логируем завершение
    logger.info("=" * 50)
    logger.info(f"ПАРСИНГ ЗАВЕРШЕН")
    logger.info(f"Всего собрано: {len(all_links)} уникальных ссылок")
    logger.info(f"Сохранено в: {OUTPUT_FILE}")
    logger.info("=" * 50)


# ==============================================================================
# ТОЧ��А ВХОДА
# ==============================================================================

if __name__ == "__main__":
    """
    Точка входа в скрипт.
    
    Запускается автоматически при выполнении файла.
    asyncio.run() - запускает асинхронную функцию main()
    """
    # Запускаем главную функцию через asyncio
    # Это необходимо, так как мы используем async/await
    asyncio.run(main())