"""
Модуль парсинга страницы книги с сайта ast.ru.

Извлекает все необходимые данные из HTML-страницы книги, кроме фото и цены.
Использует:
  - JSON-LD (Schema.org/Product) — самый надёжный источник базовых полей.
  - Блок характеристик .characteristics__item — детальные поля.
  - Мета-теги <meta property="books:*"> — резервный источник.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

# Поля, которые требуется извлечь (без фото и цены)
TARGET_FIELDS = (
    "title",
    "author",
    "isbn",
    "description",
    "annotation",
    "year",
    "pages",
    "cover_type",
    "series",
    "cycle",
    "thickness",
    "format",
    "publisher",
    "weight",
    "age_restriction",
    "language",
    "translator",
    "illustrator",
    "editor",
    "category",
    "tags",
    "url",
)


def _clean_text(value):
    """Очистка текста: убираем лишние пробелы и переносы."""
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned if cleaned else None


def _format_isbn(raw):
    """Приводит ISBN к виду 978-5-17-157591-5 (978-X-XX-XXXXXX-X)."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 13:
        return f"{digits[0:3]}-{digits[3]}-{digits[4:6]}-{digits[6:12]}-{digits[12]}"
    if len(digits) == 10:
        return f"{digits[0]}-{digits[1:5]}-{digits[5:9]}-{digits[9]}"
    return raw


def _parse_jsonld(soup):
    """
    Извлекает данные из блока JSON-LD (Schema.org/Product).
    Самый надёжный источник: title, isbn, author, publisher, description.
    """
    result = {}
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        text = script.string or script.get_text()
        if not text:
            continue
        try:
            data = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            result["title"] = _clean_text(data.get("name"))
            desc = data.get("description")
            if desc:
                result["description"] = _clean_text(desc)
            brand = data.get("brand")
            if isinstance(brand, dict):
                result["publisher"] = _clean_text(brand.get("name"))
            elif isinstance(brand, str):
                result["publisher"] = _clean_text(brand)
            gtin = data.get("gtin13")
            if gtin:
                result["isbn"] = _format_isbn(str(gtin))
            product_id = data.get("productID", "")
            if not result.get("isbn") and product_id:
                m = re.search(r"isbn:([\d\-]+)", product_id, re.IGNORECASE)
                if m:
                    result["isbn"] = _format_isbn(m.group(1))
            author = data.get("author")
            if isinstance(author, dict):
                result["author"] = _clean_text(author.get("name"))
            elif isinstance(author, str):
                result["author"] = _clean_text(author)
            elif isinstance(author, list):
                names = [a.get("name") if isinstance(a, dict) else a for a in author]
                names = [n for n in names if n]
                if names:
                    result["author"] = ", ".join(names)
        if isinstance(data, dict) and data.get("@type") == "Book":
            if not result.get("author"):
                author = data.get("author")
                if isinstance(author, dict):
                    result["author"] = _clean_text(author.get("name"))
                elif isinstance(author, list):
                    names = [a.get("name") if isinstance(a, dict) else a for a in author]
                    names = [n for n in names if n]
                    if names:
                        result["author"] = ", ".join(names)
    return result


def _parse_meta_tags(soup):
    """Резервный источник из мета-тегов <meta property="books:*"> и og:*."""
    result = {}
    metas = soup.find_all("meta")
    for m in metas:
        prop = m.get("property", "")
        content = m.get("content", "").strip()
        if not content:
            continue
        if prop == "books:author" and not result.get("author"):
            result["author"] = _clean_text(content)
        elif prop == "books:isbn" and not result.get("isbn"):
            result["isbn"] = _format_isbn(content)
        elif prop == "books:release_date" and not result.get("release_date_raw"):
            result["release_date_raw"] = content
        elif prop == "og:title" and not result.get("title"):
            result["title"] = _clean_text(content)
    return result


# Маппинг названий полей с сайта в нормализованные ключи
KEY_MAP = {
    "автор": "author",
    "авторы": "author",
    "художник": "illustrator",
    "художники": "illustrator",
    "иллюстратор": "illustrator",
    "иллюстраторы": "illustrator",
    "переводчик": "translator",
    "переводчики": "translator",
    "редактор": "editor",
    "редакторы": "editor",
    "составитель": "editor",
    "составители": "editor",
    "isbn": "isbn",
    "издательство": "publisher",
    "издатель": "publisher",
    "год издания": "year",
    "год выпуска": "year",
    "год": "year",
    "количество страниц": "pages",
    "стр.": "pages",
    "страниц": "pages",
    "обложка": "cover_type",
    "тип обложки": "cover_type",
    "переплет": "cover_type",
    "толщина": "thickness",
    "толщина (мм)": "thickness",
    "формат": "format",
    "ширина (мм)": "format",
    "высота (мм)": "format",
    "ширина": "format",
    "высота": "format",
    "вес": "weight",
    "вес (кг)": "weight",
    "возрастные ограничения": "age_restriction",
    "возраст": "age_restriction",
    "знак информационной продукции": "age_restriction",
    "язык": "language",
    "языки": "language",
    "серия": "series",
    "цикл": "cycle",
    "жанр": "tags",
    "жанры": "tags",
    "теги": "tags",
}


def _parse_characteristics(soup):
    """
    Парсит блок характеристик .characteristics__item.
    Возвращает словарь {normalized_key: value}.
    """
    result = {}
    items = soup.select(".characteristics__item")
    for item in items:
        name_el = item.select_one(".characteristics__name")
        value_el = item.select_one(".characteristics__value")
        if not name_el or not value_el:
            continue
        name_raw = name_el.get_text(strip=True).rstrip(":").strip().lower()
        value_raw = " ".join(value_el.stripped_strings)
        value = _clean_text(value_raw)
        if not value:
            continue
        key = KEY_MAP.get(name_raw)
        if not key:
            # Неизвестные поля сохраняем в extras
            result[f"extra:{name_raw}"] = value
            continue
        existing = result.get(key)
        if existing and isinstance(existing, list):
            if value not in existing:
                existing.append(value)
        elif existing and existing != value:
            if isinstance(existing, str):
                result[key] = f"{existing}, {value}"
        elif not existing:
            result[key] = value
    return result


def _parse_annotation(soup):
    """Извлекает полный текст аннотации (таб Описание)."""
    for selector in (".book-detail__about", ".book-about", ".annotation"):
        block = soup.select_one(selector)
        if block:
            text = _clean_text(block.get_text("\n", strip=True))
            if text:
                return text
    for header in soup.find_all(["h2", "h3", "div"], string=re.compile(r"^\s*Аннотация\s*$", re.IGNORECASE)):
        parent = header.parent
        if parent:
            text = _clean_text(parent.get_text("\n", strip=True))
            if text:
                return re.sub(r"^\s*Аннотация\s*", "", text, flags=re.IGNORECASE).strip() or None
    return None


def _parse_breadcrumbs(soup):
    """Извлекает категорию из хлебных крошек."""
    crumbs = soup.select(".breadcrumb a, .breadcrumbs a, [itemtype='http://schema.org/BreadcrumbList'] a")
    if not crumbs:
        return None
    parts = []
    for c in crumbs:
        t = _clean_text(c.get_text())
        if t and t.lower() not in ("главная", "каталог", "ast"):
            parts.append(t)
    return " > ".join(parts) if parts else None


def parse_book_page(html, url):
    """
    Главная функция парсинга страницы книги.

    Args:
        html: HTML-код страницы
        url: URL страницы (для сохранения)

    Returns:
        Словарь с извлечёнными полями.
    """
    soup = BeautifulSoup(html, "lxml")

    # Сбор данных из всех источников
    jsonld_data = _parse_jsonld(soup)
    meta_data = _parse_meta_tags(soup)
    chars = _parse_characteristics(soup)
    annotation = _parse_annotation(soup)
    category = _parse_breadcrumbs(soup)

    # Мерж с приоритетом: jsonld < meta < characteristics
    merged = {}
    for src in (jsonld_data, meta_data, chars):
        for k, v in src.items():
            if k.startswith("extra:"):
                extras = merged.setdefault("extras", {})
                extras[k.removeprefix("extra:")] = v
                continue
            if v is None or v == "":
                continue
            if k not in merged or not merged.get(k):
                merged[k] = v

    if annotation:
        merged["annotation"] = annotation
    if category:
        merged["category"] = category

    # URL всегда сохраняем
    merged["url"] = url

    # Год из release_date_raw, если есть
    release = merged.pop("release_date_raw", None)
    if release and not merged.get("year"):
        m = re.search(r"(\d{4})", release)
        if m:
            merged["year"] = m.group(1)

    # Числовые поля нормализуем
    if merged.get("pages"):
        m = re.search(r"\d+", str(merged["pages"]))
        if m:
            merged["pages"] = m.group(0)
    if merged.get("year"):
        m = re.search(r"\d{4}", str(merged["year"]))
        if m:
            merged["year"] = m.group(0)

    # Возвращаем только целевые поля
    final = {k: merged[k] for k in TARGET_FIELDS if k in merged}
    if "extras" in merged:
        final["extras"] = merged["extras"]
    return final
