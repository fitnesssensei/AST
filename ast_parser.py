#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Парсер ссылок на карточки товаров (книг) с сайта издательства АСТ
# Собирает все URL книг по заданной категории и сохраняет их в текстовый файл
#
# Многопоточная версия (зеркалит eksmo_links_parser.py):
#   - класс-парсер с методами init / get_page / parse_book_list /
#     find_next_page / parse_category_page / save_links_to_txt / collect_all_links
#   - набор USER_AGENTS - список словарей с ПОЛНЫМИ заголовками
#     (10 разных браузеров: Chrome / Firefox / Safari / Edge / Linux-Chrome
#      + Android / iOS / Ubuntu-Firefox / macOS-Chrome / Windows-Edge)
#   - get_random_headers() возвращает КОПИЮ случайного словаря заголовков
#   - sentinel _NOT_FOUND - сигнал «страница закончилась» (404/410)
#   - на 404/410 НЕ повторяем запрос, сразу отдаём sentinel
#   - промежуточное сохранение каждые links_save_page_interval страниц
#   - многопоточный обход: N воркеров берут задачи (page_url, page_num)
#     из общей очереди, обрабатывают и кладут следующую страницу
#
# Технологии:
#   - requests.Session - ast.ru отдаёт каталог с серверным рендером
#   - re: для извлечения ссылок на книги из HTML
#   - threading + queue.Queue: пул воркеров-страниц
#   - argparse: CLI с --start-page / --end-page / --max-books / --page-workers

import re
import os
import sys
import time
import random
import argparse
import threading
from pathlib import Path
from queue import Queue, Empty
from urllib.parse import urljoin

import requests

# ==============================================================================
# КОНФИГУРАЦИЯ
# ==============================================================================

# Базовый URL каталога художественной литературы
#BASE_URL = "https://ast.ru/cat/khudozhestvennaya-literatura/"
#BASE_URL = "https://ast.ru/cat/biografii-i-memuary/"
#BASE_URL = "https://ast.ru/cat/graficheskiy-roman-komiks/"
#BASE_URL = "https://ast.ru/cat/detyam-i-roditelyam/"
#BASE_URL = "https://ast.ru/cat/shkolnaya-uchebnaya-literatura/"
#BASE_URL = "https://ast.ru/cat/psikhologiya-i-razvitie-lichnosti/"
#BASE_URL = "https://ast.ru/cat/nauchno-populyarnaya-literatura/"
#BASE_URL = "https://ast.ru/cat/inostrannyeyazyki/"
#BASE_URL = "https://ast.ru/cat/iskusstvo-i-kultura/"
#BASE_URL = "https://ast.ru/cat/istoricheskaya-i-voennaya-literatura/"
#BASE_URL = "https://ast.ru/cat/zdorove-krasota-sport/"
#BASE_URL = "https://ast.ru/cat/eda-i-napitki/"
#BASE_URL = "https://ast.ru/cat/astrologiya-ezoterika/"
#BASE_URL = "https://ast.ru/cat/khobbi-i-dosug/"
#BASE_URL = "https://ast.ru/cat/dom-sad-ogorod/"
#BASE_URL = "https://ast.ru/cat/puteshestviya/"
#BASE_URL = "https://ast.ru/cat/biznes-literatura/"
#BASE_URL = "https://ast.ru/cat/obshchestvo-politika-pravo/"
#BASE_URL = "https://ast.ru/cat/filosofiya/"
#BASE_URL = "https://ast.ru/cat/religiya/"
#BASE_URL = "https://ast.ru/cat/publitsistika-esseistika/"
#BASE_URL = "https://ast.ru/cat/entsiklopedii/"
#BASE_URL = "https://ast.ru/cat/litsenzionnye-izdaniya/"
#BASE_URL = "https://ast.ru/cat/ezhednevniki-dnevniki-bloknoty/"
BASE_URL = "https://ast.ru/cat/knigi-v-podarok/"

# Всего страниц в каталоге (по данным сайта, см. PAGEN_1=2355 в пагинации)
MAX_PAGES = 2355

# Имя выходного файла для сохранения ссылок
OUTPUT_FILE = Path(__file__).parent / "podaroc94.txt"

# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================

# Каждые N успешно обработанных страниц делать промежуточное сохранение
LINKS_SAVE_PAGE_INTERVAL = 5

# ==============================================================================
# НАСТРОЙКИ RETRY (повторных попыток)
# ==============================================================================

# Сколько раз пытаемся загрузить страницу при неудаче.
# Попытка 1 - сразу. Потом пауза и попытка 2. И т.д.
# Если все MAX_RETRIES попыток провалились - страница попадает в «битые».
MAX_RETRIES = 3

# ==============================================================================
# 5 разных наборов заголовков с разными User-Agent.
# На каждой загрузке страницы выбирается случайный набор,
# чтобы имитировать запросы от разных браузеров.
# (Идентично eksmo_links_parser.py по структуре.)
# ==============================================================================
USER_AGENTS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"125\", \"Google Chrome\";v=\"125\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"125\", \"Microsoft Edge\";v=\"125\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"125\", \"Google Chrome\";v=\"125\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Linux\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    # === Дополнительные 5 UA с разными ОС ===
    {
        # Android (мобильный Chrome)
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"125\", \"Google Chrome\";v=\"125\"",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": "\"Android\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    {
        # iOS (мобильный Safari)
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        # Ubuntu Firefox
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    {
        # macOS Chrome
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"125\", \"Google Chrome\";v=\"125\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"macOS\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
    {
        # Windows 11 Edge
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"126\", \"Microsoft Edge\";v=\"126\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
    },
]


def get_random_headers():
    """Возвращает копию случайного набора заголовков из USER_AGENTS.

    Возвращается копия (.copy()), чтобы случайно выбранный dict
    не мутировал между вызовами.
    """
    return random.choice(USER_AGENTS).copy()


# Sentinel-объект: сигнал «страницы больше нет (404)»,
# используется для остановки обхода категории.
_NOT_FOUND = object()


def safe_print(*args, **kwargs):
    """Удобная обёртка над print (раньше обёртка нужна была для потокобезопасности)."""
    print(*args, **kwargs)


# ==============================================================================
# ОСНОВНОЙ КЛАСС ПАРСЕРА
# ==============================================================================

class AstLinksParser:
    """Класс для многопоточного сбора ссылок на карточки книг с сайта АСТ.

    Архитектурно зеркалит EksmoLinksParser:
        - те же имена и сигнатуры ключевых методов
        - те же «контракты» возвращаемых значений (sentinel _NOT_FOUND)
        - многопоточный обход страниц через Queue + N воркеров

    Технические особенности (обусловлены спецификой ast.ru):
        - Внутри используется requests (а не Playwright) - ast.ru отдаёт каталог
          с серверным рендером.
        - requests.Session с пулом соединений.
        - «Следующая страница» в каталоге АСТ - это URL вида
          https://ast.ru/cat/.../?PAGEN_1=N, поэтому пагинация числовая.
        - Sentinel _NOT_FOUND возвращается при 404/410.
    """

    def __init__(self):
        """Инициализация парсера ссылок.

        Сохраняем имена атрибутов близкими к eksmo_links_parser.py:
            - session
            - base_url
            - print_lock (используется для потокобезопасной печати)
            - links_save_page_interval
            - links_filename
        """
        # requests.Session с пулом соединений
        self.session = requests.Session()
        # Дефолтные заголовки (UA обновляется на КАЖДОЙ попытке через get_random_headers)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        self.base_url = BASE_URL
        # Лок для потокобезопасной печати (используется в воркерах)
        self.print_lock = threading.Lock()
        # Интервал промежуточного сохранения
        self.links_save_page_interval = LINKS_SAVE_PAGE_INTERVAL
        # Имя выходного файла
        self.links_filename = str(OUTPUT_FILE)

    # ==========================================================================
    # ЗАГРУЗКА СТРАНИЦЫ
    # ==========================================================================

    def get_page(self, url, max_retries=3):
        """Загрузка веб-страницы с механизмом повторных попыток.

        Имя и сигнатура совпадают с EksmoLinksParser.get_page():
            - На КАЖДОЙ попытке случайно выбирается один из 5 наборов
              заголовков из USER_AGENTS (Chrome / Firefox / Safari / Edge / Linux).
            - 404/410 (страница не существует) - НЕ повторяем, сразу возвращаем
              _NOT_FOUND.
            - В остальных случаях - до max_retries попыток с экспоненциальной
              паузой + jitter.

        Args:
            url (str): URL-адрес страницы для загрузки
            max_retries (int): Максимальное количество попыток загрузки

        Returns:
            requests.Response | _NOT_FOUND | None:
                - Response: успешный ответ (status 200)
                - _NOT_FOUND: sentinel - страница не существует (404/410)
                - None: все попытки провалились (сетевая ошибка)
        """
        last_exc = None
        for attempt in range(max_retries):
            # Берём новый случайный набор заголовков на КАЖДОЙ попытке
            headers = get_random_headers()
            try:
                response = self.session.get(url, headers=headers, timeout=30)
                # 404/410: страница закончилась - НЕ повторяем
                if response.status_code in (404, 410):
                    ua_short = headers["User-Agent"].split(") ")[0]
                    with self.print_lock:
                        print(
                            f"  ⚠ {response.status_code} для {url} "
                            f"(страница не существует) UA: ...{ua_short})"
                        )
                    return _NOT_FOUND
                response.raise_for_status()
                response.encoding = "utf-8"
                ua_short = headers["User-Agent"].split(") ")[0]
                with self.print_lock:
                    print(
                        f"  → UA: ...{ua_short}) [попытка {attempt + 1}]"
                    )
                return response
            except requests.RequestException as e:
                last_exc = e
                with self.print_lock:
                    print(f"Попытка {attempt + 1} не удалась для {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(0.1, 0.5))
                else:
                    return None
        return None

    # ==========================================================================
    # ИЗВЛЕЧЕНИЕ ССЫЛОК ИЗ HTML
    # ==========================================================================

    def parse_book_list(self, page_num):
        """Парсинг списка ссылок на книги со страницы каталога.

        Имя и сигнатура совпадают с EksmoLinksParser.parse_book_list():
        - возвращает _NOT_FOUND, если страница не существует (404/410)
        - возвращает [] если HTML пустой / не удалось загрузить
        - возвращает list уникальных URL карточек книг

        Args:
            page_num (int): Номер страницы каталога (PAGEN_1).

        Returns:
            list[str] | _NOT_FOUND: список уникальных URL книг или sentinel.
        """
        url = f"{self.base_url}?PAGEN_1={page_num}"
        with self.print_lock:
            print(f"Загрузка страницы: {url}")
        response = self.get_page(url)

        # 404/410: страница не существует - отдаём маркер
        if response is _NOT_FOUND:
            return _NOT_FOUND

        if not response:
            with self.print_lock:
                print("Не удалось загрузить страницу категории")
            return []

        # Главное и единственное надёжное правило: ищем href=".../book/..."
        # Паттерн матчит:
        #   /book/название-id
        #   /book/название-id/
        #   /book/название-id/?ast_utm=...
        #   https://ast.ru/book/название-id
        #   /book/название-id/#reviews
        href_pattern = re.compile(
            r"href=[\"\']"  # открывающая кавычка (любая)
            r"(?:https?://ast\.ru)?"  # опциональный абсолютный префикс
            r"(/book/"  # обязательный /book/
            r"[A-Za-z0-9_\-]+"  # имя книги (буквы, цифры, -, _)
            r"-\d+)"  # -id (id = только цифры)
            r"(?:[/?#][^\"\'<>]*)?"  # опционально: /, ?..., #...
            r"[\"\']",  # закрывающая кавычка
            re.IGNORECASE,
        )

        cleaned = set()
        for m in href_pattern.finditer(response.text):
            book_path = m.group(1)

            # Нормализация: убираем query/якоря, оставляем только путь
            book_path = book_path.split("?")[0].split("#")[0].rstrip("/")

            # Защита от мусорных путей
            if book_path.startswith(("/cat/", "/series/", "/authors/", "/audio", "/ebooks/")):
                continue

            # Финальная проверка формата: должно быть /book/имя-id (id = цифры)
            if not re.search(r"/book/[A-Za-z0-9_\-]+-\d+$", book_path):
                continue

            cleaned.add(f"https://ast.ru{book_path}/")

        book_links = list(cleaned)
        with self.print_lock:
            print(f"Найдено {len(book_links)} ссылок на книги")
        return book_links

    # ==========================================================================
    # ПОИСК «СЛЕДУЮЩЕЙ» СТРАНИЦЫ КАТАЛОГА
    # ==========================================================================

    def find_next_page(self, current_url, current_page_num):
        """Динамический поиск следующей страницы на основе текущей.

        В eksmo_links_parser эта функция ищет «Показать ещё» / «Далее»
        на HTML-странице. В АСТ пагинация другая - это числовой параметр
        PAGEN_1 в URL. Поэтому здесь мы возвращаем следующий URL простым
        инкрементом номера страницы (PAGEN_1 = current + 1).
        По аналогии с eksmo_links_parser метод называется find_next_page
        и принимает current_url + current_page_num, но логика - числовая.

        Args:
            current_url (str): URL текущей страницы (не используется,
                сохранён для совместимости сигнатуры).
            current_page_num (int): Номер текущей страницы.

        Returns:
            str: URL следующей страницы.
        """
        # На АСТ пагинация - это просто ?PAGEN_1=N, поэтому «следующая»
        # = текущая + 1. URL всегда один и тот же, меняется только число.
        next_page_num = current_page_num + 1
        return f"{self.base_url}?PAGEN_1={next_page_num}"

    # ==========================================================================
    # ПАРСИНГ ОДНОЙ СТРАНИЦЫ КАТАЛОГА (ОБЁРТКА)
    # ==========================================================================

    def parse_category_page(self, page_url, page_num):
        """Парсинг одной страницы каталога.

        Сигнатура и возвращаемое значение совпадают с EksmoLinksParser.parse_category_page:
        - возвращает dict {"page_num", "url", "book_links", "next_url"} при успехе
        - возвращает _NOT_FOUND, если страница вернула 404/410 - воркер остановит обход
        - возвращает None при сетевой ошибке

        Args:
            page_url (str): URL страницы каталога
            page_num (int): Номер страницы

        Returns:
            dict | _NOT_FOUND | None
        """
        try:
            # parse_book_list принимает page_num, а не url
            book_links = self.parse_book_list(page_num)

            # parse_book_list мог вернуть _NOT_FOUND
            if book_links is _NOT_FOUND:
                with self.print_lock:
                    print(
                        f"[Страница {page_num}] 404/410: "
                        f"категория закончилась ({page_url})"
                    )
                return _NOT_FOUND

            if not book_links:
                with self.print_lock:
                    print(
                        f"[Страница {page_num}] Ссылки на книги не найдены"
                    )
                # Возвращаем dict с пустым списком
                return {
                    "page_num": page_num,
                    "url": page_url,
                    "book_links": [],
                    "next_url": self.find_next_page(page_url, page_num),
                }

            with self.print_lock:
                print(f"[Страница {page_num}] Найдено книг: {len(book_links)}")

            return {
                "page_num": page_num,
                "url": page_url,
                "book_links": book_links,
                "next_url": self.find_next_page(page_url, page_num),
            }

        except Exception as e:
            with self.print_lock:
                print(
                    f"[Страница {page_num}] Ошибка при парсинге {page_url}: {e}"
                )
            return None

    # ==========================================================================
    # СОХРАНЕНИЕ ССЫЛОК
    # ==========================================================================

    def save_links_to_txt(self, links, filename=None):
        """Сохранение ссылок на книги в текстовый файл.

        Полная сигнатура и поведение совпадают с EksmoLinksParser.save_links_to_txt:
        принимает список ссылок и (опционально) имя файла, по умолчанию -
        self.links_filename.

        Args:
            links (list): Список URL-адресов книг
            filename (str, optional): Имя файла. Если None - используется self.links_filename
        """
        if filename is None:
            filename = self.links_filename
        with open(filename, "w", encoding="utf-8") as f:
            for link in links:
                f.write(link + "\n")
        with self.print_lock:
            print(f"Ссылки сохранены в файл: {filename} (всего: {len(links)})")

    # ==========================================================================
    # СБОР ССЫЛОК (многопоточный)
    # ==========================================================================

    def collect_all_links(
        self,
        category_url=None,
        start_page=1,
        end_page=None,
        max_books=None,
        page_workers=10,
    ):
        """Многопоточный сбор всех ссылок на книги из категории.

        Зеркалит EksmoLinksParser.collect_all_links (многопоточная версия):
            - N воркеров берут задачи (page_url, page_num) из page_queue
            - sentinel _NOT_FOUND останавливает обход
            - промежуточное сохранение каждые links_save_page_interval страниц
            - при max_books - обрезаем результат и останавливаем обход

        Args:
            category_url (str, optional): URL категории (не используется, оставлен
                для совместимости сигнатуры с EksmoLinksParser).
            start_page (int): Номер первой страницы (по умолчанию 1).
            end_page (int, optional): Номер последней страницы (по умолчанию MAX_PAGES).
            max_books (int, optional): Максимум собранных уникальных ссылок.
            page_workers (int): Количество потоков для сбора страниц (по умолчанию 10).

        Returns:
            list: Уникальные URL книг.
        """
        page_queue = Queue()
        all_book_links = []
        all_book_links_lock = threading.Lock()
        processed_pages = 0
        processed_pages_lock = threading.Lock()
        collection_done = threading.Event()
        active_tasks = [0]
        active_tasks_lock = threading.Lock()

        first_url = f"{self.base_url}?PAGEN_1={start_page}"
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
                        print(f"\n{'=' * 60}")
                        print(f"СБОР ССЫЛОК СО СТРАНИЦЫ {page_num}: {page_url}")
                        print(f"{'=' * 60}")

                    result = self.parse_category_page(page_url, page_num)

                    # 404/410 - категория закончилась, останавливаем обход
                    if result is _NOT_FOUND:
                        with self.print_lock:
                            print(
                                f"[Страница {page_num}] ⛔ Категория закончилась "
                                f"(404). Останавливаем обход."
                            )
                        collection_done.set()
                        with active_tasks_lock:
                            active_tasks[0] -= 1
                        page_queue.task_done()
                        try:
                            while True:
                                page_queue.get_nowait()
                                page_queue.task_done()
                        except Empty:
                            pass
                        break

                    if result and result["book_links"]:
                        with all_book_links_lock:
                            all_book_links.extend(result["book_links"])
                            if max_books and len(all_book_links) > max_books:
                                all_book_links = all_book_links[:max_books]
                                collection_done.set()

                        with processed_pages_lock:
                            processed_pages += 1

                        if page_num % self.links_save_page_interval == 0:
                            with all_book_links_lock:
                                current_links = list(all_book_links)
                            self.save_links_to_txt(current_links)

                        if result["next_url"] and not collection_done.is_set():
                            next_page_num = page_num + 1
                            if end_page is not None and next_page_num > end_page:
                                with self.print_lock:
                                    print(
                                        f"[Страница {page_num}] Достигнут лимит страницы "
                                        f"{end_page}, останавливаемся"
                                    )
                            else:
                                with all_book_links_lock:
                                    if not max_books or len(all_book_links) < max_books:
                                        page_queue.put((result["next_url"], next_page_num))
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


# ==============================================================================
# ТОЧКА ВХОДА
# ==============================================================================

def main():
    """Главная функция для сбора ссылок на книги с сайта АСТ.

    CLI (многопоточный режим):
        --start-page, --end-page, --max-books, --page-workers
    Плюс обратная совместимость с позиционными аргументами:
        python3 ast_parser.py            # все страницы
        python3 ast_parser.py 100        # с 1 по 100
        python3 ast_parser.py 10 50      # с 10 по 50
    """
    parser = argparse.ArgumentParser(
        description="Парсер ссылок на книги с сайта издательства АСТ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры запуска:
  %(prog)s                                          # все страницы с 1-й
  %(prog)s --start-page 3                           # начиная со страницы 3
  %(prog)s --end-page 10                            # страницы 1-10
  %(prog)s --start-page 5 --end-page 15             # страницы 5-15
  %(prog)s --max-books 500                          # не более 500 ссылок
  %(prog)s --page-workers 5                         # 5 потоков
        """,
    )
    parser.add_argument(
        "start_pos", type=int, nargs="?",
        help="Начальная страница (по умолчанию 1)",
    )
    parser.add_argument(
        "end_pos", type=int, nargs="?",
        help="Конечная страница (по умолчанию MAX_PAGES)",
    )
    parser.add_argument(
        "--start-page", type=int, default=None,
        help="Номер начальной страницы (по умолчанию: 1)"
    )
    parser.add_argument(
        "--end-page", type=int, default=None,
        help="Номер конечной страницы (по умолчанию: все страницы)"
    )
    parser.add_argument(
        "--max-books", type=int, default=48000,
        help="Максимальное количество собираемых ссылок (по умолчанию: 48000)"
    )
    parser.add_argument(
        "--page-workers", type=int, default=10,
        help="Количество потоков для сбора страниц (по умолчанию: 10)"
    )

    args = parser.parse_args()

    # Определяем диапазон страниц: именованные > позиционные > дефолты
    start_page = args.start_page if args.start_page is not None else (
        args.start_pos if args.start_pos is not None else 1
    )
    end_page = args.end_page if args.end_page is not None else (
        args.end_pos if args.end_pos is not None else None
    )

    parser_obj = AstLinksParser()

    safe_print(f"Начинаем сбор ссылок из категории: {parser_obj.base_url}")
    if start_page > 1 or end_page is not None:
        safe_print(
            f"Диапазон страниц: {start_page}",
            end=""
        )
        if end_page is not None:
            safe_print(f" - {end_page}")
        else:
            safe_print(" и до последней")
    safe_print(f"Максимальное количество книг: {args.max_books}")
    safe_print(f"Количество потоков: {args.page_workers}")

    links = parser_obj.collect_all_links(
        start_page=start_page,
        end_page=end_page,
        max_books=args.max_books,
        page_workers=args.page_workers,
    )
    parser_obj.save_links_to_txt(links)
    safe_print(f"Сбор завершён. Всего собрано ссылок: {len(links)}")


if __name__ == "__main__":
    main()
