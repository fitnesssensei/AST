"""
Парсер ссылок на товары с сайта ast.ru (Художественная литература)
2348 страниц с книгами
Использует Playwright для рендеринга JavaScript

Запуск:
    python3 ast_parser.py              # все 2348 страниц
    python3 ast_parser.py 100          # первые 100 страниц
    python3 ast_parser.py 10 50        # страницы с 10 по 50
"""
import asyncio
import re
import sys
from pathlib import Path
from typing import Set
from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://ast.ru/cat/khudozhestvennaya-literatura/"
MAX_PAGES = 2348
OUTPUT_FILE = Path(__file__).parent / "book_links.txt"


def parse_args():
    """Парсит аргументы командной строки."""
    if len(sys.argv) == 1:
        # Без аргументов - все страницы
        return 1, MAX_PAGES
    elif len(sys.argv) == 2:
        # Одно число - с 1 до N
        n = int(sys.argv[1])
        return 1, n
    elif len(sys.argv) == 3:
        # Два числа - с N по M
        return int(sys.argv[1]), int(sys.argv[2])
    else:
        print("Использование:")
        print("  python3 ast_parser.py              # все 2348 страниц")
        print("  python3 ast_parser.py 100          # первые 100 страниц")
        print("  python3 ast_parser.py 10 50        # страницы с 10 по 50")
        sys.exit(1)


def extract_book_links(html: str) -> Set[str]:
    """Извлекает ссылки на книги из HTML."""
    if not html:
        return set()
    
    # Паттерн для относительных ссылок на книги: /book/название-id/
    pattern = r'/book/[^\"<>\s]+-\d+/'
    matches = re.findall(pattern, html)
    
    # Преобразуем в абсолютные ссылки
    links = {f"https://ast.ru{m}" for m in matches}
    return links


async def fetch_page(page, page_num: int) -> str | None:
    """Загружает страницу каталога."""
    url = f"{BASE_URL}?PAGEN_1={page_num}"
    
    try:
        await page.goto(url, timeout=60000)
        
        # Ждем загрузки контента
        await asyncio.sleep(3)
        
        return await page.content()
    except Exception as e:
        logger.error(f"Страница {page_num}: Ошибка - {e}")
        return None


async def main():
    """Основная функция парсинга."""
    start_page, end_page = parse_args()
    total_pages = end_page - start_page + 1
    
    logger.info(f"Парсинг страниц {start_page} - {end_page} ({total_pages} страниц)")
    
    all_links: Set[str] = set()
    
    # Загружаем существующие ссылки
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            all_links = {line.strip() for line in f if line.strip()}
        logger.info(f"Загружено {len(all_links)} существующих ссылок")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Собираем страницы
        for page_num in range(start_page, end_page + 1):
            if (page_num - start_page + 1) % 50 == 0:
                logger.info(f"Обработано страниц: {page_num - start_page + 1}/{total_pages}")
                # Периодически сохраняем
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    for link in sorted(all_links):
                        f.write(f"{link}\n")
            
            html = await fetch_page(page, page_num)
            if html:
                links = extract_book_links(html)
                all_links.update(links)
                logger.debug(f"Страница {page_num}: +{len(links)} ссылок (всего: {len(all_links)})")
            
            # Пауза между запросами
            await asyncio.sleep(1)
        
        await browser.close()
    
    # Финальное сохранение
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for link in sorted(all_links):
            f.write(f"{link}\n")
    
    logger.info(f"Готово! Всего собрано {len(all_links)} ссылок на книги")
    logger.info(f"Сохранено в: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())