#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Парсер ссылок на карточки товаров (книг) с сайта издательства Эксмо
# Собирает все URL книг по заданной категории и сохраняет их в текстовый файл

import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import urljoin
import re
import threading
from queue import Queue, Empty


# 5 разных наборов заголовков с разными User-Agent.
# На каждой загрузке страницы выбирается случайный набор,
# чтобы имитировать запросы от разных браузеров.
USER_AGENTS = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    },
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
    },
    {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Opera";v="106"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
    },
]


def get_random_headers():
    """Возвращает копию случайного набора заголовков из USER_AGENTS.

    Возвращается копия (.copy()), чтобы потоки не делили один и тот же dict.
    """
    return random.choice(USER_AGENTS).copy()


# Sentinel-объект: сигнал «страницы больше нет (404)»,
# воркер использует его для остановки обхода категории.
_NOT_FOUND = object()


class EksmoLinksParser:
    """Класс для многопоточного сбора ссылок на карточки книг с сайта Эксмо"""

    def __init__(self):
        """Инициализация парсера ссылок"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.base_url = 'https://eksmo.ru'
        self.print_lock = threading.Lock()
        self.links_save_page_interval = 10
        self.links_filename = 'eksmo_links.txt'

    def get_page(self, url, max_retries=3):
        """Загрузка веб-страницы с механизмом повторных попыток

        На КАЖДОЙ попытке случайно выбирается один из 5 наборов заголовков
        из списка USER_AGENTS (Chrome / Firefox / Safari / Edge / Opera),
        чтобы имитировать запросы от разных браузеров и снизить шанс блокировки.

        404 / 410 (страница не существует) — не повторяем, возвращаем сразу
        специальный объект-маркер, чтобы воркер мог остановить дальнейший обход.

        Args:
            url (str): URL-адрес страницы для загрузки
            max_retries (int): Максимальное количество попыток загрузки

        Returns:
            requests.Response или None: Объект ответа или None в случае неудачи
            Для 404/410 возвращает объект-маркер с атрибутом .status_code == 404
        """
        last_exc = None
        for attempt in range(max_retries):
            # Берём новый случайный набор заголовков на каждую попытку
            headers = get_random_headers()
            try:
                response = self.session.get(url, headers=headers, timeout=10)
                # 404/410: страница закончилась — НЕ повторяем
                if response.status_code in (404, 410):
                    with self.print_lock:
                        ua_short = headers['User-Agent'].split(') ')[0]
                        print(f"  ⚠ {response.status_code} для {url} "
                              f"(страница не существует) UA: ...{ua_short})")
                    return response  # status_code == 404/410
                response.raise_for_status()
                response.encoding = 'utf-8'
                with self.print_lock:
                    ua_short = headers['User-Agent'].split(') ')[0]
                    print(f"  → UA: ...{ua_short}) [попытка {attempt + 1}]")
                return response
            except requests.RequestException as e:
                last_exc = e
                with self.print_lock:
                    print(f"Попытка {attempt + 1} не удалась для {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(1, 3))
                else:
                    return None
        return None

    def parse_book_list(self, category_url):
        """Парсинг списка ссылок на книги со страницы категории

        Собирает ТОЛЬКО бумажные книги:
          - ссылки Эксмо формата /book/название-ITD<id>/
          - партнёрские ссылки на litres.ru формата litres.ru/book/.../

        Аудио-обзоры (/audio/...) и их дубликаты НЕ собираются намеренно,
        чтобы не плодить дубликаты по ID с бумажными версиями.

        Отбрасывает разделы каталога и посторонние ссылки на категории
        (bestsellery, sell-out, dobro и т.п.).

        Args:
            category_url (str): URL страницы категории

        Returns:
            list: Список URL-адресов книг.
            Возвращает _NOT_FOUND (sentinel), если страница вернула 404/410
            (категория закончилась, дальше идти не надо).
        """
        print(f"Загрузка страницы: {category_url}")
        response = self.get_page(category_url)

        # 404/410: страница не существует — отдаём маркер, воркер остановит обход
        if response is not None and getattr(response, 'status_code', 200) in (404, 410):
            return _NOT_FOUND

        if not response:
            print("Не удалось загрузить страницу категории")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        book_links = []

        # Разделы каталога, которые НЕ являются страницами конкретных книг
        skip_subpaths = (
            '/book/bestsellery',
            '/book/sell-out',
            '/book/dobro',
            '/book/novinki',
            '/book/skidki',
            '/book/podpiska',
            '/book/serial',
            '/book/ekspert',
        )

        def is_book_url(href: str) -> bool:
            """Проверяем, что это ссылка на КОНКРЕТНУЮ книгу, а не раздел каталога.

            Поддерживаем 2 типа ссылок (только бумажные книги):
              1) внутренняя Эксмо:    /book/<slug>-ITD<id>/
              2) партнёрская litres.ru: litres.ru/book/<author>/<slug>-<id>/

            Аудио-обзоры (/audio/...) НЕ собираются, чтобы не дублировать
            одни и те же книги в разных форматах.
            """
            if not href:
                return False
            is_internal_book = href.startswith('/book/') or '/eksmo.ru/book/' in href
            is_partner = 'litres.ru/book/' in href
            if not (is_internal_book or is_partner):
                return False
            # Разделы каталога — пропускаем
            for sub in skip_subpaths:
                if sub in href:
                    return False
            # Внутренняя ссылка без slug после /book/ — это просто /book/ (главная)
            if is_internal_book:
                tail = href.split('/book/', 1)[1].strip('/')
                if not tail:
                    return False
            # Внутренние ссылки: должны либо содержать ITD, либо иметь slug
            if is_internal_book:
                if 'ITD' in href:
                    return True
                if re.search(r'/book/[\w-]+/?.+', href):
                    return True
                return False
            # Партнёрская ссылка на litres.ru: www.litres.ru/book/<author>/<slug>-<id>/
            if is_partner:
                m_lit = re.search(r'litres\.ru/book/[^/]+/[^/?#]+-\d+/?', href)
                return bool(m_lit)
            return False

        # Берём только ссылки, у которых в href встречается /book/
        # (аудио /audio/ игнорируем намеренно)
        links = soup.select('a[href*="/book/"]')
        for link in links:
            href = link.get('href')
            if not href:
                continue
            if not is_book_url(href):
                continue
            # Приводим к абсолютному URL
            if href.startswith('http'):
                full_url = href
            else:
                full_url = urljoin(self.base_url, href)
            # Убираем query-параметры у внутренних ссылок (lfrom=... и т.п.)
            if 'litres.ru' in full_url:
                # litres-ссылки оставляем как есть (с query)
                pass
            else:
                full_url = full_url.split('?')[0].split('#')[0]
            if full_url and full_url not in book_links:
                book_links.append(full_url)

        print(f"Найдено {len(book_links)} ссылок на книги")
        return book_links

    def find_next_page(self, current_url, soup):
        """Динамический поиск следующей страницы на основе текущей

        Args:
            current_url (str): URL текущей страницы
            soup (BeautifulSoup): Объект BeautifulSoup текущей страницы

        Returns:
            str или None: URL следующей страницы или None, если следующей нет
        """
        # 1. Ищем кнопку "Показать еще"
        show_more = soup.find('a', string=re.compile(r'показать еще', re.I))
        if show_more and show_more.get('href'):
            next_url = urljoin(self.base_url, show_more['href'])
            print(f"Найдена кнопка 'Показать еще': {next_url}")
            return next_url

        # 2. Ищем ссылку на следующую страницу (текущая + 1)
        current_page_match = re.search(r'page(\d+)', current_url)
        if current_page_match:
            current_page_num = int(current_page_match.group(1))
            next_page_num = current_page_num + 1
            next_link = soup.find('a', href=re.compile(f'page{next_page_num}'))
            if next_link:
                next_url = urljoin(self.base_url, next_link['href'])
                print(f"Найдена следующая страница: {next_url}")
                return next_url

        # 3. Ищем кнопку "Далее"
        next_button = soup.find('a', string=re.compile(r'далее|следующая|next', re.I))
        if next_button and next_button.get('href'):
            next_url = urljoin(self.base_url, next_button['href'])
            print(f"Найдена кнопка 'Далее': {next_url}")
            return next_url

        # 4. Ищем числовые ссылки пагинации
        page_links = soup.select('a[href*="page"]')
        page_numbers = []
        for link in page_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            if text.isdigit():
                page_numbers.append(int(text))
            else:
                match = re.search(r'page(\d+)', href)
                if match:
                    page_numbers.append(int(match.group(1)))

        if page_numbers:
            max_page = max(page_numbers)
            current_page_match = re.search(r'page(\d+)', current_url)
            if current_page_match:
                current_page_num = int(current_page_match.group(1))
                if current_page_num < max_page:
                    next_page_num = current_page_num + 1
                    base_url = re.sub(r'/page\d+/', '/', current_url)
                    next_url = f"{base_url.rstrip('/')}/page{next_page_num}/"
                    print(f"Вычислена следующая страница: {next_url}")
                    return next_url

        print("Следующая страница не найдена")
        return None

    def parse_category_page(self, page_url, page_num):
        """Парсинг одной страницы категории

        Args:
            page_url (str): URL страницы категории
            page_num (int): Номер страницы

        Returns:
            dict или None: {'page_num', 'url', 'book_links', 'next_url'} или None
            Возвращает _NOT_FOUND, если страница вернула 404/410 — воркер остановит обход.
        """
        try:
            response = self.get_page(page_url)

            # 404/410 — пробрасываем маркер дальше
            if response is not None and getattr(response, 'status_code', 200) in (404, 410):
                with self.print_lock:
                    print(f"[Страница {page_num}] 404/410: категория закончилась ({page_url})")
                return _NOT_FOUND

            if not response:
                with self.print_lock:
                    print(f"[Страница {page_num}] Не удалось загрузить: {page_url}")
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            book_links = self.parse_book_list(page_url)

            # parse_book_list тоже мог вернуть _NOT_FOUND (если get_page внутри него)
            if book_links is _NOT_FOUND:
                return _NOT_FOUND

            if not book_links:
                with self.print_lock:
                    print(f"[Страница {page_num}] Ссылки на книги не найдены")
                return []

            with self.print_lock:
                print(f"[Страница {page_num}] Найдено книг: {len(book_links)}")

            next_url = self.find_next_page(page_url, soup)

            return {
                'page_num': page_num,
                'url': page_url,
                'book_links': book_links,
                'next_url': next_url
            }

        except Exception as e:
            with self.print_lock:
                print(f"[Страница {page_num}] Ошибка при парсинге {page_url}: {e}")
            return None

    def save_links_to_txt(self, links, filename=None):
        """Сохранение ссылок на книги в текстовый файл

        Args:
            links (list): Список URL-адресов книг
            filename (str, optional): Имя файла. Если None — используется self.links_filename
        """
        if filename is None:
            filename = self.links_filename
        with open(filename, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(link + '\n')
        print(f"Ссылки сохранены в файл: {filename} (всего: {len(links)})")



    def collect_all_links(self, category_url, max_books=None, page_workers=10, start_page=1, end_page=None):
        """Многопоточный сбор всех ссылок на книги из категории

        Args:
            category_url (str): URL страницы категории
            max_books (int, optional): Максимальное количество книг
            page_workers (int): Количество потоков для сбора страниц
            start_page (int): Номер первой страницы для парсинга (по умолчанию: 1)
            end_page (int, optional): Номер последней страницы для парсинга (по умолчанию: None — все страницы)

        Returns:
            list: Список всех собранных URL-адресов книг
        """
        from queue import Queue, Empty
        import threading
        import time

        page_queue = Queue()
        all_book_links = []
        all_book_links_lock = threading.Lock()
        processed_pages = 0
        processed_pages_lock = threading.Lock()
        collection_done = threading.Event()
        active_tasks = [0]
        active_tasks_lock = threading.Lock()

        if start_page > 1:
            base = category_url.rstrip('/')
            first_url = f'{base}/page{start_page}/'
        else:
            first_url = category_url

        page_queue.put((first_url, start_page))
        with active_tasks_lock:
            active_tasks[0] += 1

        def page_worker():
            nonlocal processed_pages, all_book_links, collection_done

            while True:
                try:
                    try:
                        page_url, page_num = page_queue.get(timeout=1)
                    except Empty:
                        if collection_done.is_set():
                            break
                        continue

                    with self.print_lock:
                        print(f"\n{'='*60}")
                        print(f"СБОР ССЫЛОК СО СТРАНИЦЫ {page_num}: {page_url}")
                        print(f"{'='*60}")

                    result = self.parse_category_page(page_url, page_num)

                    # 404/410 — категория закончилась, останавливаем обход
                    if result is _NOT_FOUND:
                        with self.print_lock:
                            print(f"[Страница {page_num}] ⛔ Категория закончилась (404). Останавливаем обход.")
                        collection_done.set()
                        with active_tasks_lock:
                            active_tasks[0] -= 1
                        page_queue.task_done()
                        # Очищаем очередь от оставшихся задач
                        try:
                            while True:
                                page_queue.get_nowait()
                                page_queue.task_done()
                        except Empty:
                            pass
                        break

                    if result and result['book_links']:
                        with all_book_links_lock:
                            all_book_links.extend(result['book_links'])

                            if max_books and len(all_book_links) > max_books:
                                all_book_links = all_book_links[:max_books]
                                collection_done.set()

                        with processed_pages_lock:
                            processed_pages += 1

                        if page_num % self.links_save_page_interval == 0:
                            with all_book_links_lock:
                                current_links = list(all_book_links)
                            self.save_links_to_txt(current_links)

                        if result['next_url'] and not collection_done.is_set():
                            next_page_num = page_num + 1
                            if end_page is not None and next_page_num > end_page:
                                with self.print_lock:
                                    print(f"[Страница {page_num}] Достигнут лимит страницы {end_page}, останавливаемся")
                            else:
                                with all_book_links_lock:
                                    if not max_books or len(all_book_links) < max_books:
                                        page_queue.put((result['next_url'], next_page_num))
                                        with active_tasks_lock:
                                            active_tasks[0] += 1

                    with active_tasks_lock:
                        active_tasks[0] -= 1
                    page_queue.task_done()

                except Exception as e:
                    with self.print_lock:
                        print(f"Ошибка в worker: {e}")
                    continue

        workers = []
        for _ in range(page_workers):
            t = threading.Thread(target=page_worker, daemon=True)
            t.start()
            workers.append(t)

        while True:
            with active_tasks_lock:
                current_active = active_tasks[0]
            if current_active == 0 and page_queue.empty():
                break
            time.sleep(0.5)

        collection_done.set()
        for t in workers:
            t.join(timeout=5)

        return all_book_links


def main():
    """Главная функция для сбора ссылок на книги с сайта Эксмо"""
    import argparse

    parser_cli = argparse.ArgumentParser(
        description="Парсер ссылок на книги с сайта издательства Эксмо",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры запуска:
  %(prog)s                                          # все страницы с 1-й
  %(prog)s --start-page 3                           # начиная со страницы 3
  %(prog)s --end-page 10                            # страницы 1–10
  %(prog)s --start-page 5 --end-page 15             # страницы 5–15
  %(prog)s --max-books 500                          # не более 500 ссылок
  %(prog)s --page-workers 5                         # 5 потоков
  %(prog)s --category-url "https://eksmo.ru/detective/" --start-page 1 --end-page 5
        """,
    )
    parser_cli.add_argument(
        '--start-page', type=int, default=1,
        help='Номер начальной страницы (по умолчанию: 1)'
    )
    parser_cli.add_argument(
        '--end-page', type=int, default=None,
        help='Номер конечной страницы (по умолчанию: все страницы)'
    )
    parser_cli.add_argument(
        '--max-books', type=int, default=48000,
        help='Максимальное количество собираемых ссылок (по умолчанию: 48000)'
    )
    parser_cli.add_argument(
        '--page-workers', type=int, default=10,
        help='Количество потоков для сбора страниц (по умолчанию: 2)'
    )
    parser_cli.add_argument(
        '--category-url', type=str,
        default="https://eksmo.ru/khudozhestvennaya-literatura/",
        help='URL категории книг (по умолчанию: художественная литература)'
    )

    args = parser_cli.parse_args()

    parser = EksmoLinksParser()

    print(f"Начинаем сбор ссылок из категории: {args.category_url}")
    if args.start_page > 1 or args.end_page is not None:
        print(f"Диапазон страниц: {args.start_page}", end='')
        if args.end_page is not None:
            print(f" — {args.end_page}")
        else:
            print(" и до последней")
    print(f"Максимальное количество книг: {args.max_books}")
    print(f"Количество потоков: {args.page_workers}")

    links = parser.collect_all_links(
        args.category_url,
        max_books=args.max_books,
        page_workers=args.page_workers,
        start_page=args.start_page,
        end_page=args.end_page,
    )
    parser.save_links_to_txt(links)
    print(f"Сбор завершён. Всего собрано ссылок: {len(links)}")


if __name__ == "__main__":
    main()
