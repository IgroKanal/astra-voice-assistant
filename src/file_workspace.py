"""Read-only user-selected workspace. No model can expand this grant."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from html.parser import HTMLParser
import os
from pathlib import Path
import posixpath
import re
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


class _VisibleHTMLTextParser(HTMLParser):
    """Extract bounded visible HTML text without interpreting active content."""

    IGNORED_TAGS = {
        "head", "script", "style", "noscript", "template", "svg", "canvas",
        "iframe", "object", "embed",
    }
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
    BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "dd", "details", "div",
        "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1",
        "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
        "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th",
        "thead", "tr", "ul",
    }

    def __init__(self, check_limits: Callable[[], None]):
        super().__init__(convert_charrefs=True)
        self._check_limits = check_limits
        self._ignored_stack: list[str] = []
        self._parts: list[tuple[str, bool]] = []
        self._pre_depth = 0

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        values = {name.casefold(): value or "" for name, value in attrs}
        if "hidden" in values or values.get("aria-hidden", "").strip().casefold() == "true":
            return True
        style = values.get("style", "")
        return bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", style, re.IGNORECASE))

    def _separator(self) -> None:
        if not self._parts:
            return
        text, preserve = self._parts[-1]
        if text.endswith("\n"):
            return
        if not preserve:
            text = text.rstrip(" ")
            if text:
                self._parts[-1] = (text, preserve)
            else:
                self._parts.pop()
            if not self._parts or self._parts[-1][0].endswith("\n"):
                return
        self._parts.append(("\n", False))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_limits()
        tag = tag.casefold()
        if self._ignored_stack:
            if tag not in self.VOID_TAGS:
                self._ignored_stack.append(tag)
            return
        if tag in self.IGNORED_TAGS or self._is_hidden(attrs):
            if tag not in self.VOID_TAGS:
                self._ignored_stack.append(tag)
            return
        if tag == "pre":
            self._pre_depth += 1
        if tag in self.BLOCK_TAGS:
            self._separator()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_limits()
        tag = tag.casefold()
        if self._ignored_stack:
            if tag not in self.VOID_TAGS:
                self._ignored_stack.append(tag)
            return
        if tag in self.IGNORED_TAGS or self._is_hidden(attrs):
            if tag not in self.VOID_TAGS:
                self._ignored_stack.append(tag)
            return
        if tag in self.BLOCK_TAGS:
            self._separator()

    def handle_endtag(self, tag: str) -> None:
        self._check_limits()
        tag = tag.casefold()
        if self._ignored_stack:
            for index in range(len(self._ignored_stack) - 1, -1, -1):
                if self._ignored_stack[index] == tag:
                    del self._ignored_stack[index:]
                    break
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
        if tag in self.BLOCK_TAGS:
            self._separator()

    def handle_data(self, data: str) -> None:
        self._check_limits()
        if self._ignored_stack or not data:
            return
        if self._pre_depth:
            self._parts.append((data, True))
            return
        data = re.sub(r"[ \t\f\r\n]+", " ", data)
        if data == " ":
            if not self._parts or self._parts[-1][0].endswith((" ", "\n")):
                return
        self._parts.append((data, False))

    def visible_text(self, max_characters: int) -> str:
        parts = list(self._parts)
        while parts and not parts[-1][1] and parts[-1][0] == "\n":
            parts.pop()
        if parts and not parts[0][1]:
            text, preserve = parts[0]
            parts[0] = (text.lstrip(" \t\f\v\n"), preserve)
        if parts and not parts[-1][1]:
            text, preserve = parts[-1]
            parts[-1] = (text.rstrip(" \t\f\v\n"), preserve)
        result = "".join(text.replace("\r\n", "\n").replace("\r", "\n") for text, _ in parts)
        if len(result) > max_characters:
            raise WorkspaceDenied("Извлечённый HTML-текст превышает безопасный лимит")
        return result


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
    OPENABLE_SUFFIXES = {
        ".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
        ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp",
        ".mp3", ".wav", ".m4a", ".mp4", ".avi", ".mkv",
    }
    PLAIN_TEXT_SUFFIXES = frozenset({
        ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".log", ".rst", ".tex", ".diff",
        ".patch", ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".css",
        ".scss", ".sql", ".java", ".c", ".h", ".cc", ".cpp", ".hpp",
        ".cs", ".go", ".rs", ".sh", ".ps1", ".psm1", ".bat", ".cmd",
        ".xaml", ".vue", ".php", ".rb", ".kt", ".swift", ".dart",
        ".gradle", ".properties",
    })
    READABLE_SUFFIXES = PLAIN_TEXT_SUFFIXES | frozenset(
        {".html", ".htm", ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
    )
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

    def find_exact_name(
        self,
        filename: str,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> list[FileEntry]:
        """Find up to two exact basenames; fail closed if the bounded scan is incomplete."""
        if (
            not isinstance(filename, str)
            or not 2 <= len(filename) <= 120
            or filename in {".", ".."}
            or any(not char.isprintable() or char in "/\\:" for char in filename)
        ):
            raise WorkspaceDenied("Нужно указать только точное имя файла, без пути")

        def check_limits() -> None:
            if is_cancelled is not None and is_cancelled():
                raise WorkspaceDenied("Поиск отменён пользователем")
            if deadline is not None and time.monotonic() >= deadline:
                raise WorkspaceDenied("Истёк лимит времени поиска")

        self.checked(".")
        check_limits()
        target = filename.casefold()
        matches: list[FileEntry] = []
        visited = 0
        pending_directories = [self.root]
        while pending_directories:
            check_limits()
            directory = pending_directories.pop()
            children: list[Path] = []
            try:
                entries = os.scandir(directory)
            except OSError as exc:
                raise WorkspaceDenied("Не удалось полностью проверить выбранную папку") from exc
            try:
                with entries:
                    for entry in entries:
                        check_limits()
                        visited += 1
                        if visited > self.MAX_VISITED:
                            raise WorkspaceDenied("Превышен предел просмотра папки; файл не открывался")
                        try:
                            if entry.name.casefold() == target and entry.is_symlink():
                                raise WorkspaceDenied("Ссылочный файл с таким именем нельзя открывать")
                            if entry.is_dir(follow_symlinks=False):
                                relative = str(Path(entry.path).relative_to(self.root))
                                try:
                                    self.checked(relative)
                                except WorkspaceDenied:
                                    continue
                                children.append(Path(entry.path))
                                continue
                            if entry.name.casefold() != target:
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            relative = str(Path(entry.path).relative_to(self.root))
                            path = self.checked(relative)
                            if path.is_file():
                                matches.append(FileEntry(relative, path.stat().st_size))
                                if len(matches) == 2:
                                    return matches
                        except WorkspaceDenied:
                            raise
                        except (OSError, ValueError) as exc:
                            raise WorkspaceDenied("Не удалось полностью проверить выбранную папку") from exc
            except OSError as exc:
                raise WorkspaceDenied("Не удалось полностью проверить выбранную папку") from exc
            children.sort(key=lambda path: path.name.casefold(), reverse=True)
            pending_directories.extend(children)
        check_limits()
        return matches

    def checked_openable_file(self, relative: str) -> Path:
        """Revalidate one selected file immediately before opening its safe document/media type."""
        path = self.checked(relative)
        if not path.is_file() or path.suffix.casefold() not in self.OPENABLE_SUFFIXES:
            raise WorkspaceDenied("Этот тип файла нельзя открывать голосовой командой")
        return path

    def checked_readable_file(self, relative: str) -> Path:
        """Revalidate a selected document/text file without granting permission to launch it."""
        path = self.checked(relative)
        if not path.is_file() or path.suffix.casefold() not in self.READABLE_SUFFIXES:
            raise WorkspaceDenied("Этот тип файла нельзя читать голосовой командой")
        return path

    def read_text(
        self,
        relative: str,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> str:
        """Read a supported document while honoring a plan's shared limits."""
        def check_limits() -> None:
            if is_cancelled is not None and is_cancelled():
                raise WorkspaceDenied("Чтение отменено пользователем")
            if deadline is not None and time.monotonic() >= deadline:
                raise WorkspaceDenied("Истёк лимит времени чтения")

        check_limits()
        path = self.checked(relative)
        if not path.is_file():
            raise WorkspaceDenied("Выбери обычный файл")
        suffix = path.suffix.casefold()
        if suffix not in self.READABLE_SUFFIXES:
            raise WorkspaceDenied("Этот тип файла не поддерживается для чтения")
        document_suffixes = {".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
        limit = (
            self.MAX_DOCUMENT_BYTES
            if suffix in document_suffixes
            else self.MAX_READ_BYTES
        )
        data = self._read_bounded(relative, limit, check_limits=check_limits)
        check_limits()
        if suffix == ".pdf":
            result = self._extract_pdf(data, check_limits=check_limits)
        elif suffix == ".docx":
            result = self._extract_docx(data, check_limits=check_limits)
        elif suffix == ".xlsx":
            result = self._extract_xlsx(data, check_limits=check_limits)
        elif suffix == ".pptx":
            result = self._extract_pptx(data, check_limits=check_limits)
        elif suffix == ".odt":
            result = self._extract_odt(data, check_limits=check_limits)
        elif suffix == ".ods":
            result = self._extract_ods(data, check_limits=check_limits)
        elif suffix == ".odp":
            result = self._extract_odp(data, check_limits=check_limits)
        else:
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                try:
                    result = data.decode("utf-16")
                except UnicodeDecodeError:
                    raise WorkspaceDenied("Не удалось прочитать текст UTF-16") from None
            elif b"\x00" in data:
                raise WorkspaceDenied("Бинарный файл нельзя прочитать как текст")
            else:
                try:
                    result = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    try:
                        result = data.decode("cp1251")
                    except UnicodeDecodeError:
                        raise WorkspaceDenied("Поддерживаются текст UTF-8, UTF-16 с BOM и CP1251") from None
            if suffix in {".html", ".htm"}:
                result = self._extract_html(result, check_limits=check_limits)
        check_limits()
        return result

    @classmethod
    def _extract_html(
        cls,
        source: str,
        *,
        check_limits: Callable[[], None],
    ) -> str:
        parser = _VisibleHTMLTextParser(check_limits)
        try:
            parser.feed(source)
            parser.close()
        except WorkspaceDenied:
            raise
        except Exception as exc:
            raise WorkspaceDenied("Не удалось безопасно разобрать выбранный HTML-файл") from exc
        check_limits()
        return parser.visible_text(cls.MAX_DOCUMENT_CHARACTERS)

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

    def _read_bounded(
        self,
        relative: str,
        limit: int,
        *,
        check_limits: Callable[[], None] | None = None,
    ) -> bytes:
        if check_limits is not None:
            check_limits()
        path = self.checked(relative)
        info = path.stat()
        if info.st_size > limit:
            raise WorkspaceDenied(f"Файл больше {limit // 1_000_000} МБ; чтение остановлено до разбора")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            if check_limits is not None:
                check_limits()
            current = self.checked(relative).stat()
            opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            if opened_identity != current_identity or len(data) != opened.st_size:
                raise WorkspaceDenied("Файл изменился во время чтения; повтори попытку")
        if len(data) > limit:
            raise WorkspaceDenied("Файл вырос сверх лимита чтения; разбор остановлен")
        return data

    @classmethod
    def _extract_docx(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
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
                if check_limits is not None:
                    check_limits()
                xml = package.read(document)
                if check_limits is not None:
                    check_limits()
        except WorkspaceDenied:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось прочитать структуру DOCX") from exc
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise WorkspaceDenied("DOCX с объявлением XML-сущностей не поддерживается")
        try:
            if check_limits is not None:
                check_limits()
            root = ET.fromstring(xml)
            if check_limits is not None:
                check_limits()
        except ET.ParseError as exc:
            raise WorkspaceDenied("Основной XML документа DOCX повреждён") from exc
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        body = root.find(namespace + "body")
        if body is None:
            raise WorkspaceDenied("В DOCX не найден основной текст")
        paragraphs = []
        for paragraph in body.iter(namespace + "p"):
            if check_limits is not None:
                check_limits()
            pieces = []
            for node in paragraph.iter():
                if check_limits is not None:
                    check_limits()
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
    def _office_package(
        cls,
        data: bytes,
        label: str,
        check_limits: Callable[[], None] | None = None,
    ) -> zipfile.ZipFile:
        try:
            if check_limits is not None:
                check_limits()
            package = zipfile.ZipFile(BytesIO(data))
            entries = package.infolist()
            if (len(entries) > 2000 or sum(item.file_size for item in entries) > 100_000_000 or
                    len({item.filename for item in entries}) != len(entries)):
                package.close()
                raise WorkspaceDenied(f"Слишком сложный или неоднозначный пакет {label}")
            if check_limits is not None:
                check_limits()
            return package
        except WorkspaceDenied:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied(f"Не удалось прочитать структуру {label}") from exc

    @classmethod
    def _office_xml(
        cls,
        package: zipfile.ZipFile,
        name: str,
        label: str,
        total: list[int],
        check_limits: Callable[[], None] | None = None,
    ) -> ET.Element:
        try:
            if check_limits is not None:
                check_limits()
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
            if check_limits is not None:
                check_limits()
        except WorkspaceDenied:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise WorkspaceDenied(f"Повреждён XML-раздел {label}") from exc
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise WorkspaceDenied(f"XML-сущности в {label} не поддерживаются")
        try:
            if check_limits is not None:
                check_limits()
            root = ET.fromstring(xml)
            if check_limits is not None:
                check_limits()
            return root
        except ET.ParseError as exc:
            raise WorkspaceDenied(f"XML-раздел {label} повреждён") from exc

    @classmethod
    def _office_relationships(
        cls,
        package: zipfile.ZipFile,
        rels_part: str,
        label: str,
        total: list[int],
        check_limits: Callable[[], None] | None = None,
    ) -> dict[str, str]:
        namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        root = cls._office_xml(package, rels_part, label, total, check_limits)
        base = posixpath.dirname(posixpath.dirname(rels_part))
        relationships = {}
        for relationship in root.findall(namespace + "Relationship"):
            if check_limits is not None:
                check_limits()
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
    def _extract_xlsx(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        total = [0]
        try:
            with cls._office_package(data, "XLSX", check_limits) as package:
                workbook = cls._office_xml(package, "xl/workbook.xml", "XLSX", total, check_limits)
                relationships = cls._office_relationships(package, "xl/_rels/workbook.xml.rels", "XLSX", total, check_limits)
                sheets = workbook.find(main + "sheets")
                if sheets is None or len(sheets) > cls.MAX_OFFICE_SHEETS:
                    raise WorkspaceDenied("XLSX должен содержать не более 100 листов")
                shared = []
                if "xl/sharedStrings.xml" in package.namelist():
                    strings_root = cls._office_xml(package, "xl/sharedStrings.xml", "XLSX", total, check_limits)
                    for item in strings_root.findall(main + "si"):
                        if check_limits is not None:
                            check_limits()
                        pieces = []
                        for node in item.iter(main + "t"):
                            if check_limits is not None:
                                check_limits()
                            pieces.append(node.text or "")
                        shared.append("".join(pieces))
                output = []
                cells_seen = 0
                text_chars = 0
                for index, sheet in enumerate(sheets, 1):
                    if check_limits is not None:
                        check_limits()
                    name = sheet.get("name", f"Лист {index}")[:120]
                    target = relationships.get(sheet.get(rel_id, ""), "")
                    if not target.startswith("xl/worksheets/") or "/../" in f"/{target}/":
                        raise WorkspaceDenied("Лист XLSX ссылается на недопустимый раздел")
                    worksheet = cls._office_xml(package, target, "XLSX", total, check_limits)
                    output.append(f"[Лист: {name}]")
                    for cell in worksheet.iter(main + "c"):
                        if check_limits is not None:
                            check_limits()
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
                            pieces = []
                            if inline is not None:
                                for node in inline.iter(main + "t"):
                                    if check_limits is not None:
                                        check_limits()
                                    pieces.append(node.text or "")
                            value = "".join(pieces)
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
    def _extract_pptx(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        presentation_ns = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
        rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        drawing_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        total = [0]
        try:
            with cls._office_package(data, "PPTX", check_limits) as package:
                presentation = cls._office_xml(package, "ppt/presentation.xml", "PPTX", total, check_limits)
                relationships = cls._office_relationships(package, "ppt/_rels/presentation.xml.rels", "PPTX", total, check_limits)
                slide_list = presentation.find(presentation_ns + "sldIdLst")
                if slide_list is None or len(slide_list) > cls.MAX_PRESENTATION_SLIDES:
                    raise WorkspaceDenied("PPTX должен содержать не более 200 слайдов")
                output = []
                text_chars = 0
                for number, slide_id in enumerate(slide_list, 1):
                    if check_limits is not None:
                        check_limits()
                    target = relationships.get(slide_id.get(rel_id, ""), "")
                    if not target.startswith("ppt/slides/") or "/../" in f"/{target}/":
                        raise WorkspaceDenied("Слайд PPTX ссылается на недопустимый раздел")
                    slide = cls._office_xml(package, target, "PPTX", total, check_limits)
                    words = []
                    for node in slide.iter(drawing_ns + "t"):
                        if check_limits is not None:
                            check_limits()
                        words.append(node.text or "")
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
    def _odf_inline_text(
        cls,
        node: ET.Element,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
        ignored_inline_tags = {
            office_ns + "annotation",
            office_ns + "scripts",
            text_ns + "deletion",
            text_ns + "script",
            text_ns + "tracked-changes",
        }
        pieces = []

        def collect(current: ET.Element) -> None:
            if check_limits is not None:
                check_limits()
            if current.tag in ignored_inline_tags:
                return
            if current.text:
                pieces.append(current.text)
            for child in current:
                if child.tag in ignored_inline_tags:
                    continue
                if child.tag == text_ns + "tab":
                    pieces.append("\t")
                elif child.tag == text_ns + "line-break":
                    pieces.append("\n")
                elif child.tag == text_ns + "s":
                    raw_count = child.get(text_ns + "c", "1")
                    if not raw_count.isdecimal() or len(raw_count) > 3:
                        raise WorkspaceDenied("Некорректный повтор пробела в ODF")
                    count = int(raw_count)
                    if not 1 <= count <= 1000:
                        raise WorkspaceDenied("Слишком много повторных пробелов в ODF")
                    pieces.append(" " * count)
                else:
                    collect(child)
                if child.tail:
                    pieces.append(child.tail)

        collect(node)
        return "".join(pieces)

    @classmethod
    def _odf_paragraphs(
        cls,
        root: ET.Element,
        paragraph_tags: set[str],
        ignored_tags: set[str],
        check_limits: Callable[[], None] | None = None,
    ):
        pending = [root]
        while pending:
            current = pending.pop()
            if check_limits is not None:
                check_limits()
            if current.tag in ignored_tags:
                continue
            if current.tag in paragraph_tags:
                yield current
                continue
            pending.extend(reversed(list(current)))

    @classmethod
    def _odf_repeat_count(cls, node: ET.Element, attribute: str, label: str) -> int:
        table_ns = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
        raw_count = node.get(table_ns + attribute, "1")
        if not raw_count.isdecimal() or len(raw_count) > 6:
            raise WorkspaceDenied(f"Некорректное повторение элемента в {label}")
        count = int(raw_count)
        if not 1 <= count <= cls.MAX_OFFICE_CELLS:
            raise WorkspaceDenied(f"Слишком большое повторение элемента в {label}")
        return count

    @classmethod
    def _extract_odt(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
        text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        ignored_tags = {
            office_ns + "annotation", office_ns + "scripts",
            text_ns + "deletion", text_ns + "script", text_ns + "tracked-changes",
        }
        total = [0]
        try:
            with cls._office_package(data, "ODT", check_limits) as package:
                root = cls._office_xml(package, "content.xml", "ODT", total, check_limits)
                body = root.find(office_ns + "body")
                text_body = body.find(office_ns + "text") if body is not None else None
                if text_body is None:
                    raise WorkspaceDenied("В ODT не найден основной текст")
                output = []
                text_chars = 0
                for node in cls._odf_paragraphs(
                    text_body,
                    {text_ns + "p", text_ns + "h"},
                    ignored_tags,
                    check_limits,
                ):
                    paragraph = cls._odf_inline_text(node, check_limits).strip()
                    if not paragraph:
                        continue
                    output.append(paragraph)
                    text_chars += len(paragraph) + 1
                    if text_chars > cls.MAX_DOCUMENT_CHARACTERS:
                        raise WorkspaceDenied("Извлечённый ODT-текст больше 1 МБ")
                result = "\n".join(output)
                if not result:
                    raise WorkspaceDenied("В ODT нет извлекаемого текста")
                return result
        except WorkspaceDenied:
            raise
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось разобрать ODT") from exc

    @classmethod
    def _extract_ods(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
        text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        table_ns = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
        ignored_tags = {
            "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}annotation",
            "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}scripts",
            text_ns + "deletion", text_ns + "script", text_ns + "tracked-changes",
        }
        total = [0]

        def column_name(index: int) -> str:
            letters = []
            while index:
                index, remainder = divmod(index - 1, 26)
                letters.append(chr(ord("A") + remainder))
            return "".join(reversed(letters))

        try:
            with cls._office_package(data, "ODS", check_limits) as package:
                root = cls._office_xml(package, "content.xml", "ODS", total, check_limits)
                body = root.find(office_ns + "body")
                spreadsheet = body.find(office_ns + "spreadsheet") if body is not None else None
                sheets = spreadsheet.findall(table_ns + "table") if spreadsheet is not None else None
                if sheets is None or not sheets or len(sheets) > cls.MAX_OFFICE_SHEETS:
                    raise WorkspaceDenied("ODS должен содержать от 1 до 100 листов")
                output = []
                cells_seen = 0
                text_chars = 0
                has_content = False
                for sheet_index, sheet in enumerate(sheets, 1):
                    if check_limits is not None:
                        check_limits()
                    sheet_name = sheet.get(table_ns + "name", f"Лист {sheet_index}")[:120]
                    output.append(f"[Лист: {sheet_name}]")
                    row_number = 1
                    for row in sheet.iter(table_ns + "table-row"):
                        if check_limits is not None:
                            check_limits()
                        repeated_rows = cls._odf_repeat_count(row, "number-rows-repeated", "ODS")
                        cells = [
                            cell for cell in row
                            if cell.tag in {table_ns + "table-cell", table_ns + "covered-table-cell"}
                        ]
                        if not cells:
                            row_number += repeated_rows
                            continue
                        repeated_columns = [
                            cls._odf_repeat_count(cell, "number-columns-repeated", "ODS")
                            for cell in cells
                        ]
                        cells_seen += repeated_rows * sum(repeated_columns)
                        if cells_seen > cls.MAX_OFFICE_CELLS:
                            raise WorkspaceDenied("В ODS больше 200000 ячеек; чтение остановлено")
                        for row_offset in range(repeated_rows):
                            if check_limits is not None:
                                check_limits()
                            column_number = 1
                            current_row = row_number + row_offset
                            for cell, repeated_columns_count in zip(cells, repeated_columns):
                                if check_limits is not None:
                                    check_limits()
                                if cell.tag == table_ns + "covered-table-cell":
                                    value = ""
                                else:
                                    paragraphs = [
                                        cls._odf_inline_text(paragraph, check_limits).strip()
                                        for paragraph in cls._odf_paragraphs(
                                            cell, {text_ns + "p"}, ignored_tags, check_limits,
                                        )
                                    ]
                                    value = " ".join(part for part in paragraphs if part)
                                    if not value:
                                        for attribute in (
                                            "string-value", "value", "date-value", "time-value", "boolean-value",
                                        ):
                                            candidate = cell.get(office_ns + attribute)
                                            if candidate:
                                                value = candidate
                                                break
                                    if not value:
                                        formula = cell.get(table_ns + "formula", "")
                                        if formula:
                                            value = "=" + formula
                                if value:
                                    for column_offset in range(repeated_columns_count):
                                        line = f"{column_name(column_number + column_offset)}{current_row}: {value}"
                                        output.append(line)
                                        has_content = True
                                        text_chars += len(line) + 1
                                        if text_chars > cls.MAX_DOCUMENT_CHARACTERS:
                                            raise WorkspaceDenied("Извлечённый ODS-текст больше 1 МБ")
                                column_number += repeated_columns_count
                        row_number += repeated_rows
                result = "\n".join(output).strip()
                if not result or not has_content:
                    raise WorkspaceDenied("В ODS нет извлекаемого текста")
                return result
        except WorkspaceDenied:
            raise
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось разобрать ODS") from exc

    @classmethod
    def _extract_odp(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
        text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
        draw_ns = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
        presentation_ns = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"
        ignored_tags = {
            office_ns + "annotation", office_ns + "scripts",
            text_ns + "deletion", text_ns + "script", text_ns + "tracked-changes",
            presentation_ns + "notes",
        }
        total = [0]
        try:
            with cls._office_package(data, "ODP", check_limits) as package:
                root = cls._office_xml(package, "content.xml", "ODP", total, check_limits)
                body = root.find(office_ns + "body")
                presentation = body.find(office_ns + "presentation") if body is not None else None
                slides = presentation.findall(draw_ns + "page") if presentation is not None else None
                if slides is None or len(slides) > cls.MAX_PRESENTATION_SLIDES:
                    raise WorkspaceDenied("ODP должен содержать не более 200 слайдов")
                output = []
                text_chars = 0
                paragraph_tags = {text_ns + "p", text_ns + "h"}
                for slide_number, slide in enumerate(slides, 1):
                    if check_limits is not None:
                        check_limits()
                    paragraphs = []
                    for node in cls._odf_paragraphs(slide, paragraph_tags, ignored_tags, check_limits):
                        value = cls._odf_inline_text(node, check_limits).strip()
                        if value:
                            paragraphs.append(value)
                    if paragraphs:
                        block = f"[Слайд {slide_number}]\n" + "\n".join(paragraphs)
                        output.append(block)
                        text_chars += len(block) + 1
                        if text_chars > cls.MAX_DOCUMENT_CHARACTERS:
                            raise WorkspaceDenied("Извлечённый ODP-текст больше 1 МБ")
                result = "\n\n".join(output)
                if not result:
                    raise WorkspaceDenied("В ODP нет извлекаемого текста")
                return result
        except WorkspaceDenied:
            raise
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise WorkspaceDenied("Не удалось разобрать ODP") from exc

    @classmethod
    def _extract_pdf(
        cls,
        data: bytes,
        check_limits: Callable[[], None] | None = None,
    ) -> str:
        try:
            if check_limits is not None:
                check_limits()
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data), strict=False)
            if check_limits is not None:
                check_limits()
            if reader.is_encrypted:
                raise WorkspaceDenied("Зашифрованный PDF не читается без отдельного разрешения")
            if len(reader.pages) > cls.MAX_PDF_PAGES:
                raise WorkspaceDenied("PDF больше 200 страниц; выбери меньший документ")
            extracted = []
            total_content = 0
            total_text = 0
            for index, page in enumerate(reader.pages, 1):
                if check_limits is not None:
                    check_limits()
                contents = page.get_contents()
                if contents is not None:
                    size = len(contents.get_data())
                    if check_limits is not None:
                        check_limits()
                    if size > cls.MAX_PDF_PAGE_CONTENT_BYTES:
                        raise WorkspaceDenied("Страница PDF слишком сложная; разбор остановлен")
                    total_content += size
                    if total_content > cls.MAX_PDF_TOTAL_CONTENT_BYTES:
                        raise WorkspaceDenied("PDF содержит слишком много данных страниц; разбор остановлен")
                page_text = page.extract_text() or ""
                if check_limits is not None:
                    check_limits()
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
