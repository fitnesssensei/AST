"""
Асинхронный воркер для массового сбора данных о книгах с сайта ast.ru.

Читает список URL из файла, обходит их параллельно с настраиваемой
конкуррентностью, ретраями и ротацией User-Agent, сохраняет результат
в формате JSON Lines (.jsonl) и опционально в общий JSON.

Особенности:
  - асинхронный I/O на базе aiohttp
  - экспоненциальные ретраи с джиттером
  - локальный кэш прогресса (можно продолжить после сбоя)
  - подробный вывод статистики в реальном времени
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import aiohttp

from .parser import parse_book_page

# Настройка логирования
logger = logging.getLogger("ast.worker")


# Список User-Agent'ов для ротации (реальные браузеры)
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
]


@dataclass
class WorkerConfig:
    """Конфигурация воркера."""

    concurrency: int = 30          # Число одновременных запросов
    timeout: int = 60              # Таймаут одного запроса, сек
    max_retries: int = 4           # Сколько раз ретраить
    retry_base_delay: float = 1.0  # Базовая задержка между ретраями, сек
    min_request_delay: float = 0.05  # Минимальная задержка между запросами с одного воркера
    pretty: bool = False           # Форматировать JSON красиво (по строкам на атрибут)
    output_path: Path = field(default_factory=lambda: Path("books.jsonl"))
    progress_path: Path = field(default_factory=lambda: Path("books.progress.json"))
    errors_path: Path = field(default_factory=lambda: Path("books.errors.jsonl"))


def _format_json(data: dict, pretty: bool) -> str:
    """
    Сериализует словарь в JSON-строку.
    При pretty=True — многострочный формат с отступами, удобный для чтения.
    При pretty=False — компактный (одна строка), экономный по месту.
    """
    if pretty:
        # sort_keys=False — сохраняем порядок ключей как в TARGET_FIELDS (логичный)
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    return json.dumps(data, ensure_ascii=False, sort_keys=False)


@dataclass
class WorkerStats:
    """Статистика работы воркера."""

    total: int = 0
    done: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: float = field(default_factory=time.time)
    last_report_at: float = field(default_factory=time.time)
    last_report_done: int = 0


def load_urls(path: Path) -> list[str]:
    """Загружает список URL из текстового файла (по одному на строку)."""
    with open(path, "r", encoding="utf-8") as f:
        urls = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def load_progress(path: Path) -> set[str]:
    """Загружает множество уже обработанных URL из файла прогресса."""
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("done", []))
    except (OSError, ValueError):
        return set()


def save_progress(path: Path, done: set[str]) -> None:
    """Атомарно сохраняет прогресс в файл."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"done": sorted(done), "updated_at": time.time()}, f)
    tmp.replace(path)


def calc_delay(attempt: int, base: float) -> float:
    """Экспоненциальная задержка с джиттером для ретраев."""
    return base * (2 ** attempt) + random.uniform(0, base)


async def fetch_one(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    cfg: WorkerConfig,
) -> tuple[str, str | None, str | None]:
    """
    Загружает одну страницу с ретраями.

    Returns:
        Кортеж (url, html, error). error == None при успехе.
    """
    last_error = None
    for attempt in range(cfg.max_retries + 1):
        async with semaphore:
            # Соблюдаем минимальную задержку, чтобы не перегружать сервер
            await asyncio.sleep(cfg.min_request_delay * random.uniform(0.5, 1.5))
            try:
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Cache-Control": "no-cache",
                }
                timeout = aiohttp.ClientTimeout(total=cfg.timeout)
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        # Ограничиваем размер ответа (защита от мусорных страниц)
                        data = await resp.text(errors="replace")
                        if len(data) < 5000:
                            last_error = f"too_small:{len(data)}"
                        else:
                            return url, data, None
                    elif resp.status == 404:
                        # Страница удалена — нет смысла ретраить
                        return url, None, "not_found_404"
                    elif resp.status in (429, 503):
                        # Нас ограничивают — подождём подольше
                        last_error = f"rate_limit_{resp.status}"
                        await asyncio.sleep(calc_delay(attempt, cfg.retry_base_delay) * 2)
                        continue
                    else:
                        last_error = f"http_{resp.status}"
            except asyncio.TimeoutError:
                last_error = "timeout"
            except aiohttp.ClientError as e:
                last_error = f"client_error:{type(e).__name__}"
            except Exception as e:  # noqa: BLE001
                last_error = f"exception:{type(e).__name__}:{e}"
        # Задержка перед следующей попыткой
        if attempt < cfg.max_retries:
            await asyncio.sleep(calc_delay(attempt, cfg.retry_base_delay))
    return url, None, last_error or "unknown"


def _print_progress(stats: WorkerStats) -> None:
    """Выводит текущую статистику в stderr (перезапись строки)."""
    now = time.time()
    elapsed = now - stats.started_at
    interval = now - stats.last_report_at
    if interval < 5:  # обновляем не чаще раза в 5 сек
        return
    delta_done = stats.done - stats.last_report_done
    rate = delta_done / interval if interval > 0 else 0
    rate_avg = stats.done / elapsed if elapsed > 0 else 0
    remaining = stats.total - stats.done
    eta_sec = remaining / rate_avg if rate_avg > 0 else 0
    eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60):02d}s" if eta_sec else "?"

    pct = (stats.done / stats.total * 100) if stats.total else 0
    msg = (
        f"\r[{pct:5.1f}%] {stats.done}/{stats.total} "
        f"OK:{stats.success} ERR:{stats.failed} SKIP:{stats.skipped} "
        f"| rate: {rate:.1f}/s avg: {rate_avg:.1f}/s ETA: {eta_str}   "
    )
    sys.stderr.write(msg)
    sys.stderr.flush()
    stats.last_report_at = now
    stats.last_report_done = stats.done


async def run_worker(
    urls: Iterable[str],
    cfg: WorkerConfig,
) -> None:
    """
    Главная функция воркера.

    Args:
        urls: Итерабельный объект со списком URL.
        cfg: Конфигурация воркера.
    """
    all_urls = list(urls)
    done = load_progress(cfg.progress_path)
    pending = [u for u in all_urls if u not in done]
    skipped = len(all_urls) - len(pending)

    stats = WorkerStats(
        total=len(all_urls),
        skipped=skipped,
        success=skipped,
    )

    if skipped:
        logger.info("Пропускаем %d уже обработанных URL", skipped)
    if not pending:
        logger.info("Все URL уже обработаны. Готово.")
        return
    logger.info("К обработке: %d URL, конкуррентность: %d", len(pending), cfg.concurrency)

    # Настройка пула соединений
    connector = aiohttp.TCPConnector(
        limit=cfg.concurrency * 2,
        limit_per_host=cfg.concurrency,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )
    semaphore = asyncio.Semaphore(cfg.concurrency)

    # Открываем файлы на дозапись
    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    out_file = open(cfg.output_path, "a", encoding="utf-8")
    err_file = open(cfg.errors_path, "a", encoding="utf-8")

    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                asyncio.create_task(
                    _process_url(session, url, semaphore, cfg, out_file, err_file, done, stats)
                )
                for url in pending
            ]
            # Ждём завершения всех задач
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        out_file.close()
        err_file.close()
        save_progress(cfg.progress_path, done)

    elapsed = time.time() - stats.started_at
    logger.info(
        "\nГотово за %.1f сек. Успехов: %d, ошибок: %d, пропущено: %d",
        elapsed, stats.success, stats.failed, stats.skipped,
    )


async def _process_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    cfg: WorkerConfig,
    out_file,
    err_file,
    done: set,
    stats: WorkerStats,
) -> None:
    """Обрабатывает один URL: скачивает, парсит, пишет в файл."""
    try:
        u, html, err = await fetch_one(session, url, semaphore, cfg)
        if err:
            stats.failed += 1
            err_file.write(json.dumps(
                {"url": url, "error": err, "ts": time.time()},
                ensure_ascii=False,
            ) + "\n")
            err_file.flush()
            logger.debug("FAIL %s: %s", url, err)
        else:
            try:
                data = parse_book_page(html, u)
            except Exception as e:  # noqa: BLE001
                stats.failed += 1
                err_file.write(json.dumps(
                    {"url": url, "error": f"parse_error:{type(e).__name__}:{e}"},
                    ensure_ascii=False,
                ) + "\n")
                err_file.flush()
                logger.debug("PARSE FAIL %s: %s", url, e)
            else:
                # Записываем книгу в файл
                # При pretty=True — многострочный JSON с переносом строки между книгами
                # При pretty=False — компактный JSONL (по одной книге на строку)
                payload = _format_json(data, cfg.pretty)
                out_file.write(payload)
                if cfg.pretty:
                    # Разделяем книги пустой строкой для удобства чтения
                    out_file.write("\n\n")
                else:
                    out_file.write("\n")
                out_file.flush()
                stats.success += 1
        done.add(url)
        stats.done += 1
        _print_progress(stats)
        # Периодически сохраняем прогресс
        if stats.done % 50 == 0:
            save_progress(cfg.progress_path, done)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        stats.failed += 1
        stats.done += 1
        err_file.write(json.dumps(
            {"url": url, "error": f"task_error:{type(e).__name__}:{e}"},
            ensure_ascii=False,
        ) + "\n")
        err_file.flush()
        logger.exception("TASK FAIL %s", url)
