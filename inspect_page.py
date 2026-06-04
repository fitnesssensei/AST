"""
Временный скрипт для анализа HTML-структуры страницы книги на ast.ru
"""
import asyncio
from playwright.async_api import async_playwright

async def inspect():
    url = "https://ast.ru/book/zvezdy-iz-pepla-873454/"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        
        await page.goto(url, timeout=90000, wait_until="networkidle")
        await asyncio.sleep(3)
        
        # Получаем полный HTML
        html = await page.content()
        
        # Сохраняем HTML в файл для анализа
        with open("/Users/rustamismagilov/Desktop/AST/page_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        
        print(f"HTML сохранён, размер: {len(html)} байт")
        
        # Попробуем найти ключевые элементы через JavaScript
        elements = await page.evaluate("""() => {
            const results = {};
            
            // Название книги
            const titleEl = document.querySelector('h1');
            results.title = titleEl ? titleEl.textContent.trim() : null;
            
            // Автор
            const authorEl = document.querySelector('[data-product-param="author"]');
            results.author = authorEl ? authorEl.textContent.trim() : null;
            
            // ISBN
            const isbnEl = document.querySelector('[data-product-param="isbn"]');
            if (!isbnEl) {
                const allSpans = document.querySelectorAll('span');
                for (const span of allSpans) {
                    if (span.textContent.includes('ISBN')) {
                        results.isbn = span.textContent.trim();
                        break;
                    }
                }
            } else {
                results.isbn = isbnEl.textContent.trim();
            }
            
            // Описание
            const descEl = document.querySelector('[data-product-param="description"]');
            results.description = descEl ? descEl.textContent.trim() : null;
            
            // Обложка
            const imgEl = document.querySelector('.product-picture img') || document.querySelector('[data-product-param="cover"] img');
            results.cover = imgEl ? imgEl.src : null;
            
            // Серия
            const seriesEl = document.querySelector('[data-product-param="series"]');
            results.series = seriesEl ? seriesEl.textContent.trim() : null;
            
            // Характеристики
            const chars = {};
            const charItems = document.querySelectorAll('.product-params__item, .product-params-item, .product-info__param');
            charItems.forEach(item => {
                const label = item.querySelector('.product-params__label, .param-label, .product-info__label');
                const value = item.querySelector('.product-params__value, .param-value, .product-info__value');
                if (label && value) {
                    chars[label.textContent.trim()] = value.textContent.trim();
                }
            });
            results.characteristics = chars;
            
            // Все текстовые блоки с важными данными
            const bodyText = document.body.innerText;
            results.bodyText = bodyText.substring(0, 3000);
            
            return results;
        }""")
        
        for key, value in elements.items():
            print(f"\n=== {key} ===")
            print(value)
        
        await browser.close()

asyncio.run(inspect())
