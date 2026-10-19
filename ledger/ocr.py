"""Local OCR for scanned statements via the Windows built-in engine; no data leaves the machine."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

SCALE = 300 / 72


def available() -> bool:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except ImportError:
        return False
    return OcrEngine.is_language_supported(Language("zh-Hant-TW"))


def _rows(words: list[tuple[float, float, float, float, str]]) -> list[str]:
    """Group OCR words into visual rows by vertical overlap, then order left to right."""
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for word in sorted(words, key=lambda w: (w[1] + w[3] / 2, w[0])):
        for row in rows:
            top = min(w[1] for w in row)
            bottom = max(w[1] + w[3] for w in row)
            overlap = min(bottom, word[1] + word[3]) - max(top, word[1])
            # Thousands commas sit half a line low; partial overlap still belongs to the row.
            if overlap >= 0.3 * min(word[3], bottom - top):
                row.append(word)
                break
        else:
            rows.append([word])
    lines = []
    for row in sorted(rows, key=lambda r: min(w[1] for w in r)):
        row.sort(key=lambda w: w[0])
        height = sorted(w[3] for w in row)[len(row) // 2]
        text = row[0][4]
        for previous, word in zip(row, row[1:]):
            gap = word[0] - (previous[0] + previous[2])
            # Windows OCR splits CJK into single-character words; only real column gaps become spaces.
            text += (" " if gap > height * 0.8 or _separate(previous[4], word[4], gap / height) else "") + word[4]
        lines.append(text)
    return lines


def _separate(left: str, right: str, gap: float) -> bool:
    if _is_cjk(left[-1]) or _is_cjk(right[0]):
        return False
    if left[-1] in ",.·/:-" or right[0] in ",.·/:-":
        return False
    return gap > 0.25


def _is_cjk(char: str) -> bool:
    return "\u3000" <= char <= "\u9fff" or "\uff00" <= char <= "\uffef"


async def _recognize(images) -> list[str]:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = OcrEngine.try_create_from_language(Language("zh-Hant-TW"))
    lines = []
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(buffer.getvalue())
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        bitmap = await (await BitmapDecoder.create_async(stream)).get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        words = [(w.bounding_rect.x, w.bounding_rect.y, w.bounding_rect.width, w.bounding_rect.height, w.text)
                 for line in result.lines for w in line.words]
        lines.extend(_rows(words))
    return lines


def pdf_lines(path: str | Path) -> list[str]:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        images = [page.render(scale=SCALE).to_pil().convert("RGB") for page in pdf]
    finally:
        pdf.close()
    return asyncio.run(_recognize(images))
