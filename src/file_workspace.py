"""Read-only user-selected workspace. No model can expand this grant."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import posixpath
import stat
import time
from typing import Callable
from urllib.parse import unquote
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps


class WorkspaceDenied(ValueError):
    pass


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int


@dataclass(frozen=True)
class ImagePreview:
    png: bytes
    image_format: str
    original_width: int
    original_height: int


class FileWorkspace:
    MAX_READ_BYTES = 1_000_000
    MAX_IMAGE_BYTES = 10_000_000
    MAX_IMAGE_PIXELS = 16_000_000
    MAX_IMAGE_SIDE = 8192
    IMAGE_PREVIEW_SIDE = 1600
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
    MAX_DOCUMENT_BYTES = 25_000_000
    MAX_DOCUMENT_CHARACTERS = 1_000_000
    MAX_PDF_PAGES = 200
    MAX_PDF_PAGE_CONTENT_BYTES = 8_000_000
    MAX_PDF_TOTAL_CONTENT_BYTES = 32_000_000
    MAX_DOCX_XML_BYTES = 5_000_000
    MAX_OFFICE_XML_BYTES = 5_000_000
    MAX_OFFICE_TOTAL_XML_BYTES = 32_000_000
    MAX_OFFICE_SHEETS = 100
    MAX_PRESENTATION_SLIDES = 200
    MAX_OFFICE_CELLS = 200_000
    MAX_RESULTS = 500
    MAX_VISITED = 10000
    BLOCKED = {".astra-history", ".git", ".ssh", ".gnupg", ".aws", ".azure", ".kube", "appdata", ".venv", "__pycache__", "node_modules"}
    SECRET_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx"}

    def __init__(self, root: Path):
        root = Path(os.path.abspath(root))
        self._check_components(root)
        if not root.is_dir() or root.parent == root:
            raise WorkspaceDenied("Выбери конкретную пользовательскую папку, а не весь диск")
        self.root = root.resolve(strict=True)
        for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            protected = os.environ.get(name)
            if protected and self.root.is_relative_to(Path(protected).resolve()):
                raise WorkspaceDenied("Системная папка недоступна")

    @classmethod
    def _check_components(cls, path: Path) -> None:
        for component in (path, *path.parents):
            name = component.name.lower()
            if name in cls.BLOCKED or name.startswith(".astra-") or name == ".env" or name.startswith(".env.") or name in {"credentials", "id_rsa", "id_ed25519"} or component.suffix.lower() in cls.SECRET_SUFFIXES:
                raise WorkspaceDenied("Файл или каталог с секретами исключён")
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise WorkspaceDenied("Ссылки и junction не разрешены")

    def checked(self, relative: str) -> Path:
        rel = Path(relative)
        if rel.is_absolute() or rel.drive or ".." in rel.parts or ":" in relative:
            raise WorkspaceDenied("Нужен относительный путь внутри разрешённой папки")
        candidate = self.root / rel
        self._check_components(candidate)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceDenied("Путь за пределами разрешённой папки")
        if resolved.is_file() and resolved.stat().st_nlink > 1:
            raise WorkspaceDenied("Файлы с внешними hardlink не разрешены в выбранной папке")
        return resolved

    def search(
        self,
        query: str = "",
        *,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> list[FileEntry]:
        """Search the selected workspace with optional cooperative limits.

        ``deadline`` is an absolute ``time.monotonic()`` value. The callback is
        checked between directory entries so a running plan can stop promptly.
        """
        def check_limits() -> None:
            if is_cancelled is not None and is_cancelled():
                raise WorkspaceDenied("Поиск отменён пользователем")
            if deadline is not None and time.monotonic() >= deadline:
                raise WorkspaceDenied("Истёк лимит времени поиска")

        self.checked(".")
        check_limits()
        result: list[FileEntry] = []
        visited = 0
        pending_directories = [self.root]
        needle = query.casefold()
        while pending_directories:
            check_limits()
            directory = pending_directories.pop()
            children: list[Path] = []
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            try:
                with entries:
                    for entry in entries:
                        check_limits()
                        visited += 1
                        if visited > self.MAX_VISITED:
                            return result
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                relative = str(Path(entry.path).relative_to(self.root))
                                self.checked(relative)
                                children.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                        except (OSError, ValueError, WorkspaceDenied):
                            continue

                        if needle not in entry.name.casefold():
                            continue
                        relative = str(Path(entry.path).relative_to(self.root))
                        try:
                            path = self.checked(relative)
                            if path.is_file():
                                result.append(FileEntry(relative, path.stat().st_size))
                        except (OSError, WorkspaceDenied):
                            continue
                        if len(result) >= self.MAX_RESULTS:
                            return result
            except OSError:
                continue

            children.sort(key=lambda path: path.name.casefold(), reverse=True)
            pending_directories.extend(children)
        check_limits()
        return result

    def read_text(self, relative: str) -> str:
        path = self.checked(relative)
        if not path.is_file():
            raise WorkspaceDenied("Выбери обычный файл")
        suffix = path.suffix.casefold()
        limit = self.MAX_DOCUMENT_BYTES if suffix in {".pdf", ".docx", ".xlsx", ".pptx"} else self.MAX_READ_BYTES
        data = self._read_bounded(relative, limit)
        if suffix == ".pdf":
            return self._extract_pdf(data)
        if suffix == ".docx":
            return self._extract_docx(data)
        if suffix == ".xlsx":
            return self._extract_xlsx(data)
        if suffix == ".pptx":
            return self._extract_pptx(data)
        if b"\x00" in data:
            raise WorkspaceDenied("Бинарный файл нельзя прочитать как текст")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise WorkspaceDenied("Пока поддерживаются текстовые файлы UTF-8") from None

    def preview_image(self, relative: str) -> ImagePreview:
        """Decode one explicitly selected image into a bounded, metadata-free PNG."""
        path = self.checked(relative)
        if not path.is_file() or path.suffix.casefold() not in self.IMAGE_SUFFIXES:
            raise WorkspaceDenied("Поддерживается только выбранное обычное изображение")
        data = self._read_bounded(relative, self.MAX_IMAGE_BYTES)
        try:
            with Image.open(BytesIO(data)) as source:
                image_format = source.format or ""
                if image_format not in {"PNG", "JPEG", "BMP", "GIF", "WEBP"}:
                    raise WorkspaceDenied("Формат изображения не поддерживается для preview")
                width, height = source.size
                if (width <= 0 or height <= 0 or width > self.MAX_IMAGE_SIDE or
                        height > self.MAX_IMAGE_SIDE or width * height > self.MAX_IMAGE_PIXELS):
                    raise WorkspaceDenied("Размер изображения превышает безопасный лимит preview")
                source.seek(0)  # GIF preview is deliberately limited to its first frame.
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA" if "A" in source.getbands() else "RGB")
                image.thumbnail((self.IMAGE_PREVIEW_SIDE, self.IMAGE_PREVIEW_SIDE), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="PNG", optimize=False)
                return ImagePreview(output.getvalue(), image_format, width, height)
        except WorkspaceDenied:
            raise
        except Exception as exc:
            raise WorkspaceDenied("Не удалось безопасно декодировать выбранное изображение") from exc

    def _read_bounded(self, relative: str, limit: int) -> bytes:
        path = self.checked(relative)
        info = path.stat()
        if info.st_size > limit:
            raise WorkspaceDenied(f"Файл больше {limit // 1_000_000} МБ; чтение остановлено до разбора")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            current = self.checked(relative).stat()
            opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            if opened_identity != current_identity or len(data) != opened.st_size:
                raise WorkspaceDenied("Файл изменился во время чтения; повтори попытку")
        if len(data) > limit:
            raise WorkspaceDenied("Файл вырос сверх лимита чтения; разбор остановлен")
        return data

    @classmethod
    def _extract_docx(cls, data: bytes) -> str:
        try:
            with zipfile.ZipFile(BytesIO(data)) as package:
                entries = package.infolist()
                if len(entries) > 2000 or sum(item.file_size for item in entries) > 100_000_000:
                    raise WorkspaceDenied("Слишком сложный DOCX-пакет; разбор остановлен")
                document = next((item for item in entries if item.filename == "word/document.xml"), None)
                if document is None or document.file_size > cls.MAX_DOCX_XML_BYTES:
                    raise WorkspaceDenied("DOCX не содержит допустимый основной документ")
                if document.compress_size == 0 and document.file_size or (document.compress_size and document.file_size / document.compress_size > 250):
                    raise WorkspaceDenied("Подозрительный уровень сжатия DOCX; разбор остановлен")
                xml = package.read(document)
        except WorkspaceDenied:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось прочитать структуру DOCX") from exc
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise WorkspaceDenied("DOCX с объявлением XML-сущностей не поддерживается")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise WorkspaceDenied("Основной XML документа DOCX повреждён") from exc
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        body = root.find(namespace + "body")
        if body is None:
            raise WorkspaceDenied("В DOCX не найден основной текст")
        paragraphs = []
        for paragraph in body.iter(namespace + "p"):
            pieces = []
            for node in paragraph.iter():
                if node.tag == namespace + "t" and node.text:
                    pieces.append(node.text)
                elif node.tag == namespace + "tab":
                    pieces.append("\t")
                elif node.tag in {namespace + "br", namespace + "cr"}:
                    pieces.append("\n")
            if pieces:
                paragraphs.append("".join(pieces))
        text = "\n".join(paragraphs).strip()
        if not text:
            raise WorkspaceDenied("В DOCX нет извлекаемого текста")
        if len(text) > cls.MAX_DOCUMENT_CHARACTERS:
            raise WorkspaceDenied("Извлечённый DOCX-текст больше 1 МБ")
        return text

    @classmethod
    def _office_package(cls, data: bytes, label: str) -> zipfile.ZipFile:
        try:
            package = zipfile.ZipFile(BytesIO(data))
            entries = package.infolist()
            if (len(entries) > 2000 or sum(item.file_size for item in entries) > 100_000_000 or
                    len({item.filename for item in entries}) != len(entries)):
                package.close()
                raise WorkspaceDenied(f"Слишком сложный или неоднозначный пакет {label}")
            return package
        except WorkspaceDenied:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied(f"Не удалось прочитать структуру {label}") from exc

    @classmethod
    def _office_xml(cls, package: zipfile.ZipFile, name: str, label: str, total: list[int]) -> ET.Element:
        try:
            info = package.getinfo(name)
        except KeyError as exc:
            raise WorkspaceDenied(f"В {label} не найден обязательный раздел") from exc
        if info.file_size > cls.MAX_OFFICE_XML_BYTES:
            raise WorkspaceDenied(f"XML-раздел {label} превышает 5 МБ")
        if info.compress_size == 0 and info.file_size or (info.compress_size and info.file_size / info.compress_size > 250):
            raise WorkspaceDenied(f"Подозрительный уровень сжатия XML-раздела {label}")
        total[0] += info.file_size
        if total[0] > cls.MAX_OFFICE_TOTAL_XML_BYTES:
            raise WorkspaceDenied(f"XML-содержимое {label} превышает общий лимит 32 МБ")
        try:
            xml = package.read(info)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise WorkspaceDenied(f"Повреждён XML-раздел {label}") from exc
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise WorkspaceDenied(f"XML-сущности в {label} не поддерживаются")
        try:
            return ET.fromstring(xml)
        except ET.ParseError as exc:
            raise WorkspaceDenied(f"XML-раздел {label} повреждён") from exc

    @classmethod
    def _office_relationships(cls, package: zipfile.ZipFile, rels_part: str, label: str, total: list[int]) -> dict[str, str]:
        namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        root = cls._office_xml(package, rels_part, label, total)
        base = posixpath.dirname(posixpath.dirname(rels_part))
        relationships = {}
        for relationship in root.findall(namespace + "Relationship"):
            identity = relationship.get("Id", "")
            target = relationship.get("Target", "")
            if relationship.get("TargetMode", "Internal") == "External":
                continue
            if not identity or not target:
                raise WorkspaceDenied(f"Пустая внутренняя ссылка внутри {label}")
            target = unquote(target).replace("\\", "/")
            if target.startswith("/"):
                part = posixpath.normpath(target.lstrip("/"))
            else:
                part = posixpath.normpath(posixpath.join(base, target))
            if part.startswith("../") or part.startswith("/") or ":" in part or part in {".", ".."}:
                raise WorkspaceDenied(f"Недопустимая ссылка на раздел внутри {label}")
            relationships[identity] = part
        return relationships

    @classmethod
    def _extract_xlsx(cls, data: bytes) -> str:
        main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        total = [0]
        try:
            with cls._office_package(data, "XLSX") as package:
                workbook = cls._office_xml(package, "xl/workbook.xml", "XLSX", total)
                relationships = cls._office_relationships(package, "xl/_rels/workbook.xml.rels", "XLSX", total)
                sheets = workbook.find(main + "sheets")
                if sheets is None or len(sheets) > cls.MAX_OFFICE_SHEETS:
                    raise WorkspaceDenied("XLSX должен содержать не более 100 листов")
                shared = []
                if "xl/sharedStrings.xml" in package.namelist():
                    strings_root = cls._office_xml(package, "xl/sharedStrings.xml", "XLSX", total)
                    shared = ["".join(node.text or "" for node in item.iter(main + "t")) for item in strings_root.findall(main + "si")]
                output = []
                cells_seen = 0
                text_chars = 0
                for index, sheet in enumerate(sheets, 1):
                    name = sheet.get("name", f"Лист {index}")[:120]
                    target = relationships.get(sheet.get(rel_id, ""), "")
                    if not target.startswith("xl/worksheets/") or "/../" in f"/{target}/":
                        raise WorkspaceDenied("Лист XLSX ссылается на недопустимый раздел")
                    worksheet = cls._office_xml(package, target, "XLSX", total)
                    output.append(f"[Лист: {name}]")
                    for cell in worksheet.iter(main + "c"):
                        cells_seen += 1
                        if cells_seen > cls.MAX_OFFICE_CELLS:
                            raise WorkspaceDenied("В XLSX больше 200000 ячеек; чтение остановлено")
                        address = cell.get("r", "")[:24]
                        kind = cell.get("t", "")
                        value_node = cell.find(main + "v")
                        value = value_node.text if value_node is not None and value_node.text else ""
                        if kind == "s" and value:
                            try:
                                value = shared[int(value)]
                            except (ValueError, IndexError):
                                raise WorkspaceDenied("В XLSX повреждён индекс общей строки") from None
                        elif kind == "inlineStr":
                            inline = cell.find(main + "is")
                            value = "".join(node.text or "" for node in inline.iter(main + "t")) if inline is not None else ""
                        elif kind == "b" and value:
                            value = "TRUE" if value == "1" else "FALSE"
                        if not value:
                            formula = cell.find(main + "f")
                            if formula is not None and formula.text:
                                value = "=" + formula.text
                        if value:
                            output.append(f"{address}: {value}")
                            text_chars += len(output[-1])
                            if text_chars > cls.MAX_DOCUMENT_CHARACTERS:
                                raise WorkspaceDenied("Извлечённый XLSX-текст больше 1 МБ")
                text = "\n".join(output).strip()
                if not text:
                    raise WorkspaceDenied("В XLSX нет извлекаемого текста")
                return text
        except WorkspaceDenied:
            raise
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось разобрать XLSX") from exc

    @classmethod
    def _extract_pptx(cls, data: bytes) -> str:
        presentation_ns = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
        rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        drawing_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        total = [0]
        try:
            with cls._office_package(data, "PPTX") as package:
                presentation = cls._office_xml(package, "ppt/presentation.xml", "PPTX", total)
                relationships = cls._office_relationships(package, "ppt/_rels/presentation.xml.rels", "PPTX", total)
                slide_list = presentation.find(presentation_ns + "sldIdLst")
                if slide_list is None or len(slide_list) > cls.MAX_PRESENTATION_SLIDES:
                    raise WorkspaceDenied("PPTX должен содержать не более 200 слайдов")
                output = []
                text_chars = 0
                for number, slide_id in enumerate(slide_list, 1):
                    target = relationships.get(slide_id.get(rel_id, ""), "")
                    if not target.startswith("ppt/slides/") or "/../" in f"/{target}/":
                        raise WorkspaceDenied("Слайд PPTX ссылается на недопустимый раздел")
                    slide = cls._office_xml(package, target, "PPTX", total)
                    words = [node.text or "" for node in slide.iter(drawing_ns + "t")]
                    text = " ".join(" ".join(words).split())
                    if text:
                        output.append(f"[Слайд {number}]\n{text}")
                        text_chars += len(output[-1])
                        if text_chars > cls.MAX_DOCUMENT_CHARACTERS:
                            raise WorkspaceDenied("Извлечённый PPTX-текст больше 1 МБ")
                result = "\n\n".join(output)
                if not result:
                    raise WorkspaceDenied("В PPTX нет извлекаемого текста")
                return result
        except WorkspaceDenied:
            raise
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось разобрать PPTX") from exc

    @classmethod
    def _extract_pdf(cls, data: bytes) -> str:
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise WorkspaceDenied("Зашифрованный PDF не читается без отдельного разрешения")
            if len(reader.pages) > cls.MAX_PDF_PAGES:
                raise WorkspaceDenied("PDF больше 200 страниц; выбери меньший документ")
            extracted = []
            total_content = 0
            total_text = 0
            for index, page in enumerate(reader.pages, 1):
                contents = page.get_contents()
                if contents is not None:
                    size = len(contents.get_data())
                    if size > cls.MAX_PDF_PAGE_CONTENT_BYTES:
                        raise WorkspaceDenied("Страница PDF слишком сложная; разбор остановлен")
                    total_content += size
                    if total_content > cls.MAX_PDF_TOTAL_CONTENT_BYTES:
                        raise WorkspaceDenied("PDF содержит слишком много данных страниц; разбор остановлен")
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted.append(f"[Страница {index}]\n{page_text.strip()}")
                    total_text += len(extracted[-1])
                    if total_text > cls.MAX_DOCUMENT_CHARACTERS:
                        raise WorkspaceDenied("Извлечённый PDF-текст больше 1 МБ")
        except WorkspaceDenied:
            raise
        except Exception as exc:
            raise WorkspaceDenied("Не удалось безопасно разобрать PDF") from exc
        text = "\n\n".join(extracted)
        if not text:
            raise WorkspaceDenied("В PDF нет извлекаемого текста; сканы требуют отдельного OCR")
        return text
