from __future__ import annotations

import base64
from pathlib import Path

import pymupdf as fitz


class PDFImageRenderer:
    """将 PDF 页面渲染为可直接用于多模态模型的图片数据。"""

    def get_total_pages(self, pdf_path: str) -> int:
        """返回 PDF 总页数。"""
        document = fitz.open(pdf_path)
        try:
            return int(document.page_count)
        finally:
            document.close()

    def render_pages_to_base64(self, pdf_path: str, start_page: int, end_page: int, dpi: int = 200) -> list[str]:
        """将指定页码范围渲染为 base64 PNG 数据 URI 列表。"""
        if start_page < 1:
            raise ValueError(f"start_page 必须从 1 开始，当前为 {start_page}")
        if end_page < start_page:
            raise ValueError(f"end_page 不能小于 start_page: {start_page} > {end_page}")
        if dpi <= 0:
            raise ValueError(f"dpi 必须为正整数，当前为 {dpi}")

        document = fitz.open(pdf_path)
        try:
            total_pages = int(document.page_count)
            if end_page > total_pages:
                raise ValueError(f"end_page 超出 PDF 总页数: {end_page} > {total_pages}")

            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            images: list[str] = []

            for page_number in range(start_page, end_page + 1):
                page_index = page_number - 1
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                try:
                    png_bytes = pixmap.tobytes("png")
                finally:
                    pixmap = None
                encoded = base64.b64encode(png_bytes).decode("ascii")
                images.append(f"data:image/png;base64,{encoded}")

            return images
        finally:
            document.close()
