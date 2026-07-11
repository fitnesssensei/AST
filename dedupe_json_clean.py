#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Дедупликация каталога книг по ISBN.

Жёсткое правило:
  • Сравниваем ТОЛЬКО нормализованный ISBN (только цифры и 'X', без учёта регистра).
  • Если ISBN отсутствует / пустой / не строка — запись НИКОГДА не считается
    дублем и всегда сохраняется.

Поддерживаемые форматы входа:
  • JSON-массив  [{"isbn": "...", ...}, ...]
  • NDJSON / JSON Lines — по одному объекту на строку
  • «Pretty-printed» NDJSON — каждый объект занимает несколько строк,
    объекты идут друг за другом без обёрточного [ ] и без запятых
    (как в sparseno/books100.json). Чтение через подсчёт глубины фигурных скобок.

Выход: NDJSON (по одному объекту на строку), удобно для следующих шагов пайплайна.
"""

import json
import re
import sys


# ---------- НАСТРОЙКИ ----------

# Входной JSON/NDJSON файл для обработки
INPUT_FILE = 'JSONSS/religi.json'

# Выходной файл (результат)
OUTPUT_FILE = 'JSONSS/religiClean.json'

# Список полей, которые нужно удалить из каждой записи.
# Оставьте список пустым [], если ничего удалять не нужно.
DELETE_FIELDS = [
    'extras',
    'url',
    
    # 'source',
    # 'rating',
]

# Добавлять запятую после каждой книги (кроме последней).
# Полезно, если потом нужно обернуть весь вывод в [ ] для валидного JSON-массива.
ADD_COMMAS = False

# ---------- НОРМАЛИЗАЦИЯ ISBN ----------

def normalize_isbn(isbn):
    """Привести ISBN к каноническому виду для сравнения.

    Возвращает строку из цифр и (опционально) 'X' в верхнем регистре.
    Для None, не-строк, пустых строк и мусора без цифр — возвращает ''.

    Это единственное место, где решается «совпадают ли два ISBN»,
    поэтому правила строгие: '978-5-17-166534-0' и '9785171665340'
    считаются одинаковыми, а '' и '' — одинаковыми пустыми.
    """
    if not isbn or not isinstance(isbn, str):
        return ''
    # Оставляем только цифры и X, переводим в верхний регистр
    normalized = re.sub(r'[^0-9Xx]', '', isbn.strip().upper())
    return normalized


# ---------- ЧТЕНИЕ ВХОДНОГО ФАЙЛА ----------

def _iter_json_objects(text):
    """Потоково выдаёт JSON-объекты верхнего уровня из произвольного текста.

    Корректно работает с:
      • [ {...}, {...} ]    — обычный JSON-массив
      • { ... }\\n{ ... }    — NDJSON (по объекту на строку)
      • { ... }\\n\\n{ ... }  — pretty-printed NDJSON, как в books100.json

    Считает глубину { и }, корректно игнорирует скобки внутри строк
    (в т. ч. с экранированными кавычками \\").
    """
    n = len(text)
    i = 0
    depth = 0
    start = -1
    in_str = False
    escape = False

    while i < n:
        ch = text[i]

        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue

        if ch == '"':
            in_str = True
            i += 1
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield text[start:i + 1]
                    start = -1
        # всё остальное (пробелы, переносы, запятые, [ ], :, ...) — игнорируем
        i += 1


def load_records(path):
    """Загрузить список записей из JSON / NDJSON / pretty-NDJSON файла.

    Возвращает (records, errors):
      records — список dict'ов
      errors  — список строк с описаниями нераспарсенных кусков
    """
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    records = []
    errors = []
    for chunk in _iter_json_objects(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError as e:
            errors.append(f'{e.msg} (line {e.lineno}, col {e.colno})')
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            # На всякий случай: если внутри JSON-массива оказался не-dict —
            # оборачиваем, чтобы не потерять (как dict у него не будет isbn).
            records.append({'value': obj})
    return records, errors


# ---------- ДЕДУПЛИКАЦИЯ ----------

def dedupe_by_isbn(records, keep='first'):
    """Удалить полные дубли по ISBN. Без ISBN — никогда не дубликат.

    Args:
        records: список словарей-записей.
        keep: 'first' — оставить первую встреченную запись с данным ISBN
              'last'  — оставить последнюю.

    Returns:
        (deduped, removed_isbn_dupes, kept_no_isbn, dropped_invalid)
    """
    if keep not in ('first', 'last'):
        raise ValueError("keep должен быть 'first' или 'last'")

    # Для 'last' сначала пройдёмся и запомним последнюю запись по каждому ISBN,
    # чтобы потом при обходе сохранить именно её.
    last_by_isbn = {}
    if keep == 'last':
        for item in records:
            key = normalize_isbn(item.get('isbn') if isinstance(item, dict) else None)
            if key:
                last_by_isbn[key] = item

    seen_isbn = set()
    deduped = []
    removed_isbn_dupes = 0
    kept_no_isbn = 0
    dropped_invalid = 0

    for item in records:
        if not isinstance(item, dict):
            # На уровне дедупа нечего сравнивать — оставляем как есть.
            deduped.append(item)
            continue

        key = normalize_isbn(item.get('isbn'))

        if not key:
            # Без валидного ISBN запись не считается дублем — всегда сохраняем.
            kept_no_isbn += 1
            deduped.append(item)
            continue

        if key in seen_isbn:
            removed_isbn_dupes += 1
            continue

        seen_isbn.add(key)
        if keep == 'last':
            deduped.append(last_by_isbn[key])
        else:
            deduped.append(item)

    return deduped, removed_isbn_dupes, kept_no_isbn, dropped_invalid


# ---------- УДАЛЕНИЕ ПОЛЕЙ ----------

def delete_fields(records, fields):
    """Удалить указанные поля (ключи) из каждой записи.

    Args:
        records: список словарей-записей.
        fields: список названий полей для удаления (например ['extras', 'source']).

    Returns:
        Количество записей, в которых было удалено хотя бы одно поле.
    """
    if not fields:
        return 0

    modified_count = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        for field in fields:
            if field in item:
                del item[field]
                modified_count += 1
    return modified_count


# ---------- СОХРАНЕНИЕ ----------

def save_pretty(records, path, add_commas=True):
    """Сохранить список записей в pretty-формате.

    Каждый объект печатается с отступом 2, как в sparseno/books100.json.
    Между объектами — пустая строка.

    Args:
        records: список словарей-записей.
        path: путь к выходному файлу.
        add_commas: если True — добавить запятую после каждой книги
                    (кроме последней). Полезно, чтобы потом обернуть
                    весь вывод в [ ] для валидного JSON-массива.
    """
    with open(path, 'w', encoding='utf-8') as f:
        for i, r in enumerate(records):
            if i > 0:
                if add_commas:
                    f.write(',\n\n')  # запятая и пустая строка-разделитель
                else:
                    f.write('\n')  # пустая строка-разделитель между объектами
            # ensure_ascii=False — чтобы кириллица не превращалась в \uXXXX
            f.write(json.dumps(r, ensure_ascii=False, indent=2))
            f.write('\n')


# ---------- CLI ----------

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]

    # Берём пути из настроек (секция НАСТРОЙКИ в начале файла)
    input_path = INPUT_FILE
    output_path = OUTPUT_FILE
    keep = 'first'
    add_commas = ADD_COMMAS

    # Позиционные аргументы (необязательные): input output [first|last]
    # Переопределяют настройки из файла
    if len(argv) >= 1:
        input_path = argv[0]
    if len(argv) >= 2:
        output_path = argv[1]
    if len(argv) >= 3:
        keep = argv[2].lower()
    if len(argv) >= 4:
        add_commas = argv[3].lower() in ('1', 'true', 'yes', '--commas')

    # Flag --commas can be passed anywhere
    add_commas = add_commas or '--commas' in argv

    if keep not in ('first', 'last'):
        print("Ошибка: keep должен быть 'first' или 'last'")
        return 2

    try:
        records, errors = load_records(input_path)
    except FileNotFoundError:
        print(f"Ошибка: файл {input_path} не найден")
        return 1
    except OSError as e:
        print(f"Ошибка чтения {input_path}: {e}")
        return 1

    if errors:
        print(f"Предупреждение: не удалось распарсить {len(errors)} фрагмент(ов):")
        for e in errors[:5]:
            print(f"  • {e}")
        if len(errors) > 5:
            print(f"  ... и ещё {len(errors) - 5}")

    if not records:
        print(f"Внимание: в {input_path} не найдено ни одной записи")
        save_pretty([], output_path, add_commas=add_commas)
        return 0

    total = len(records)
    deduped, removed, kept_no_isbn, _ = dedupe_by_isbn(records, keep=keep)

    # Удаление полей, указанных в константе DELETE_FIELDS (секция НАСТРОЙКИ)
    if DELETE_FIELDS:
        deleted_count = delete_fields(deduped, DELETE_FIELDS)
        print(f"Удалено полей ({', '.join(DELETE_FIELDS)}): всего {deleted_count} удалений")
        # Считаем, у скольких записей удалили хотя бы одно поле
        records_with_deletions = sum(
            1 for r in deduped
            if isinstance(r, dict) and any(f not in r for f in DELETE_FIELDS)
        )
        if records_with_deletions:
            print(f"  (затронуто записей: {records_with_deletions})")

    # Статистика по ISBN (считаем среди исходных записей)
    isbn_counter = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        k = normalize_isbn(r.get('isbn'))
        if k:
            isbn_counter[k] = isbn_counter.get(k, 0) + 1
    unique_isbn = len(isbn_counter)
    isbn_dup_groups = sum(1 for v in isbn_counter.values() if v > 1)

    save_pretty(deduped, output_path, add_commas=add_commas)

    print(f"Исходный файл:           {input_path}")
    print(f"Всего записей:            {total}")
    print(f"Записей с непустым ISBN:  {total - kept_no_isbn}")
    print(f"Записей без ISBN:         {kept_no_isbn}  (все сохранены, удалять нельзя)")
    print(f"Уникальных ISBN:          {unique_isbn}")
    print(f"ISBN-групп с дублями:     {isbn_dup_groups}")
    print(f"Удалено полных дублей:    {removed}  (по ISBN)")
    print(f"Записей после дедупа:     {len(deduped)}")
    print(f"Режим keep:               {keep}")
    print(f"Результат:                {output_path}")
    print(f"Запятые между книгами:    {'да' if add_commas else 'нет'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
