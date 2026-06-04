"""
Точка входа: запускалка воркера из командной строки.

Примеры:
    python3 -m worker --input links.txt
    python3 -m worker --input links.txt --concurrency 50
    python3 -m worker --input links.txt --limit 100   # первые 100 URL
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .crawler import WorkerConfig, load_urls, run_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Воркер для парсинга книг с ast.ru",
    )
    parser.add_argument(
        "-i", "--input", required=True, type=Path,
        help="Путь к текстовому файлу со списком URL (по одному на строку)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("books.jsonl"),
        help="Путь к выходному .jsonl файлу (по умолчанию books.jsonl)",
    )
    parser.add_argument(
        "--progress", type=Path, default=Path("books.progress.json"),
        help="Файл прогресса для возможности продолжения (по умолчанию books.progress.json)",
    )
    parser.add_argument(
        "--errors", type=Path, default=Path("books.errors.jsonl"),
        help="Файл с ошибками (по умолчанию books.errors.jsonl)",
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=30,
        help="Число одновременных запросов (по умолчанию 30)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Таймаут одного запроса в секундах (по умолчанию 60)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=4,
        help="Сколько раз ретраить неудачный запрос (по умолчанию 4)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Обработать только первые N URL (0 = все)",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="Пропустить первые N URL",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Подробный вывод (DEBUG)",
    )
    parser.add_argument(
        "-p", "--pretty", action="store_true",
        help="Форматировать JSON красиво: каждый атрибут на новой строке, "
             "книги разделены пустой строкой. По умолчанию — компактный JSONL.",
    )
    args = parser.parse_args(argv)

    # Настройка логов
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    if not args.input.exists():
        print(f"Файл не найден: {args.input}", file=sys.stderr)
        return 1

    urls = load_urls(args.input)
    if args.offset:
        urls = urls[args.offset:]
    if args.limit:
        urls = urls[:args.limit]

    cfg = WorkerConfig(
        concurrency=args.concurrency,
        timeout=args.timeout,
        max_retries=args.max_retries,
        pretty=args.pretty,
        output_path=args.output,
        progress_path=args.progress,
        errors_path=args.errors,
    )

    try:
        asyncio.run(run_worker(urls, cfg))
    except KeyboardInterrupt:
        print("\nПрервано пользователем", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
