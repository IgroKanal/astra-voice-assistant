"""Bounded public-web search and page reading for explicit research requests."""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import http.client
import ipaddress
import math
import re
import socket
import ssl
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import parse_qs, quote, quote_plus, urljoin, urlsplit, urlunsplit


class WebResearchDenied(ValueError):
    """Raised when a web operation exceeds its explicit grant or safe limits."""


class WebGrantDenied(WebResearchDenied):
    """Raised when the explicit web capability is missing, expired, or exhausted."""


@dataclass(frozen=True)
class WebSearchHit:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class WebPage:
    title: str
    url: str
    text: str


@dataclass(frozen=True)
class WebResearchResult:
    query: str
    hits: tuple[WebSearchHit, ...]
    pages: tuple[WebPage, ...]


@dataclass(frozen=True)
class _HTTPResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _strip_controls(value: str) -> str:
    return "".join(
        char for char in value
        if char in "\r\n\t" or not unicodedata.category(char).startswith("C")
    )


class WebResearchGrant:
    """Short-lived, quota-limited read-only Internet capability."""

    SCOPES = frozenset({"search", "read"})
    MAX_TTL_SECONDS = 60 * 60
    MAX_REQUESTS = 100

    def __init__(self, scopes: set[str] | frozenset[str] | tuple[str, ...] | list[str], *,
                 ttl_seconds: int | float = 15 * 60, max_requests: int = 20):
        if not isinstance(scopes, (set, frozenset, tuple, list)):
            raise WebResearchDenied("Сетевые операции должны быть разрешены явно")
        try:
            clean_scopes = frozenset(scopes)
        except TypeError:
            raise WebGrantDenied("Сетевые разрешения должны быть простыми именами") from None
        if (not clean_scopes or any(not isinstance(scope, str) for scope in clean_scopes)
                or not clean_scopes.issubset(self.SCOPES)):
            raise WebGrantDenied("Доступны только отдельные права поиска и чтения страниц")
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not 1 <= ttl_seconds <= self.MAX_TTL_SECONDS or not math.isfinite(ttl_seconds)):
            raise WebGrantDenied("Сетевое разрешение должно действовать от 1 секунды до 1 часа")
        if type(max_requests) is not int or not 1 <= max_requests <= self.MAX_REQUESTS:
            raise WebGrantDenied("Лимит сетевых запросов должен быть от 1 до 100")
        self._scopes = clean_scopes
        self._expires_at = time.monotonic() + float(ttl_seconds)
        self._max_requests = max_requests
        self._requests = 0
        self._revoked = False
        self._lock = threading.RLock()

    @property
    def requests_remaining(self) -> int:
        with self._lock:
            return max(0, self._max_requests - self._requests)

    def consume(self, scope: str) -> None:
        with self._lock:
            if self._revoked:
                raise WebGrantDenied("Сетевое разрешение отозвано")
            if time.monotonic() >= self._expires_at:
                raise WebGrantDenied("Срок сетевого разрешения истёк")
            if scope not in self._scopes:
                raise WebGrantDenied(f"Сетевое право «{scope}» не выдано")
            if self._requests >= self._max_requests:
                raise WebGrantDenied("Исчерпан лимит запросов текущего разрешения")
            self._requests += 1

    def require_active(self, scope: str) -> None:
        with self._lock:
            if self._revoked:
                raise WebGrantDenied("Сетевое разрешение отозвано")
            if time.monotonic() >= self._expires_at:
                raise WebGrantDenied("Срок сетевого разрешения истёк")
            if scope not in self._scopes:
                raise WebGrantDenied(f"Сетевое право «{scope}» не выдано")

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to already validated public DNS answers."""

    def __init__(self, host: str, addresses: tuple[str, ...], timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._validated_addresses = addresses

    def connect(self) -> None:
        last_error: OSError | None = None
        started = time.monotonic()
        for address in self._validated_addresses:
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                sock = socket.create_connection((address, self.port), timeout=remaining)
                sock.settimeout(remaining)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise TimeoutError("Истёк лимит подключения к сайту")


class _HTMLTextParser(HTMLParser):
    IGNORED = {"head", "script", "style", "noscript", "template", "svg", "canvas",
               "iframe", "object", "embed", "nav", "footer", "form"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}
    BLOCK = {"address", "article", "aside", "blockquote", "br", "dd", "details", "div",
             "dl", "dt", "fieldset", "figcaption", "figure", "h1", "h2", "h3", "h4",
             "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section",
             "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"}

    def __init__(self, check_limits: Callable[[], None], max_characters: int):
        super().__init__(convert_charrefs=True)
        self._check_limits = check_limits
        self._max_characters = max_characters
        self._ignored_stack: list[str] = []
        self._title_depth = 0
        self._title: list[str] = []
        self._parts: list[str] = []
        self._characters = 0
        self._tags = 0
        self._pre_depth = 0

    @property
    def title(self) -> str:
        return " ".join(_strip_controls(" ".join(self._title)).split())[:256]

    def _tick(self) -> None:
        self._tags += 1
        if self._tags > 100_000:
            raise WebResearchDenied("HTML страницы превышает лимит элементов")
        self._check_limits()

    def _separator(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        values = {name.casefold(): value or "" for name, value in attrs}
        if "hidden" in values or values.get("aria-hidden", "").strip().casefold() == "true":
            return True
        style = values.get("style", "")
        return bool(re.search(
            r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b",
            style,
            re.IGNORECASE,
        ))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        tag = tag.casefold()
        if tag == "title":
            self._title_depth += 1
        if self._ignored_stack:
            if tag not in self.VOID:
                self._ignored_stack.append(tag)
            return
        if tag in self.IGNORED or self._is_hidden(attrs):
            if tag not in self.VOID:
                self._ignored_stack.append(tag)
            return
        if tag == "pre":
            self._pre_depth += 1
        if tag in self.BLOCK:
            self._separator()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        tag = tag.casefold()
        if tag in self.IGNORED or self._ignored_stack:
            return
        if tag in self.BLOCK:
            self._separator()

    def handle_endtag(self, tag: str) -> None:
        self._tick()
        tag = tag.casefold()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if self._ignored_stack:
            for index in range(len(self._ignored_stack) - 1, -1, -1):
                if self._ignored_stack[index] == tag:
                    del self._ignored_stack[index:]
                    break
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
        if tag in self.BLOCK:
            self._separator()

    def handle_data(self, data: str) -> None:
        self._check_limits()
        if not data:
            return
        if self._title_depth:
            self._title.append(data[:256])
        if self._ignored_stack:
            return
        if self._pre_depth:
            text = _strip_controls(data)
        else:
            text = re.sub(r"[ \t\f\r\n]+", " ", _strip_controls(data))
            if text == " " and (not self._parts or self._parts[-1].endswith((" ", "\n"))):
                return
        remaining = self._max_characters - self._characters
        if remaining <= 0:
            return
        text = text[:remaining]
        self._parts.append(text)
        self._characters += len(text)

    def text(self) -> str:
        return _strip_controls("".join(self._parts)).strip()


class _SearchParser(HTMLParser):
    MAX_TAGS = 100_000

    def __init__(self, check_limits: Callable[[], None]):
        super().__init__(convert_charrefs=True)
        self._check_limits = check_limits
        self._tags = 0
        self._capture: str | None = None
        self._href = ""
        self._parts: list[str] = []
        self._ignored_stack: list[str] = []
        self.results: list[WebSearchHit] = []

    def _tick(self) -> None:
        self._tags += 1
        if self._tags > self.MAX_TAGS:
            raise WebResearchDenied("Страница поисковой выдачи превышает лимит элементов")
        self._check_limits()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        tag = tag.casefold()
        if self._ignored_stack:
            if tag not in _HTMLTextParser.VOID:
                self._ignored_stack.append(tag)
            return
        if tag in {"script", "style", "noscript", "template", "svg", "iframe", "object", "embed"}:
            if tag not in _HTMLTextParser.VOID:
                self._ignored_stack.append(tag)
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "a" and "result__a" in classes and len(self.results) < 20:
            self._capture = "title"
            self._href = values.get("href", "")
            self._parts = []
        elif "result__snippet" in classes and len(self.results) < 20:
            self._capture = "snippet"
            self._parts = []

    def handle_data(self, data: str) -> None:
        self._check_limits()
        if not self._ignored_stack and self._capture is not None and data:
            self._parts.append(_strip_controls(data[:2000]))

    def handle_endtag(self, tag: str) -> None:
        self._tick()
        tag = tag.casefold()
        if self._ignored_stack:
            for index in range(len(self._ignored_stack) - 1, -1, -1):
                if self._ignored_stack[index] == tag:
                    del self._ignored_stack[index:]
                    break
            return
        if self._capture == "title" and tag == "a":
            title = " ".join(" ".join(self._parts).split())[:300]
            target = _unwrap_search_url(self._href)
            if title and target:
                self.results.append(WebSearchHit(title, target, ""))
            self._capture = None
            self._parts = []
        elif self._capture == "snippet" and tag in {"div", "a", "span"}:
            snippet = " ".join(" ".join(self._parts).split())[:600]
            if snippet and self.results:
                previous = self.results[-1]
                self.results[-1] = WebSearchHit(previous.title, previous.url, snippet)
            self._capture = None
            self._parts = []


def _unwrap_search_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    candidate = urljoin("https://html.duckduckgo.com/", value)
    parts = urlsplit(candidate)
    if (parts.hostname and parts.hostname.casefold() in {"duckduckgo.com", "www.duckduckgo.com"}
            and parts.path == "/l/"):
        wrapped = parse_qs(parts.query).get("uddg", [""])[0]
        return wrapped[:4096]
    return candidate[:4096]


class WebResearchClient:
    SEARCH_URL = "https://www.bing.com/search?format=rss"
    MAX_QUERY_CHARACTERS = 500
    MAX_URL_CHARACTERS = 4096
    MAX_BODY_BYTES = 1_000_000
    MAX_PAGE_CHARACTERS = 30_000
    MAX_SEARCH_RESULTS = 10
    MAX_PAGES_PER_RESEARCH = 5
    MAX_REDIRECTS = 3
    REQUEST_TIMEOUT_SECONDS = 12.0
    RESEARCH_TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        grant: WebResearchGrant,
        *,
        resolver: Callable[[str], list[str] | tuple[str, ...]] | None = None,
        requester: Callable[[str, tuple[str, ...], float, int, Callable[[], bool] | None], _HTTPResponse] | None = None,
        search_url: str | None = None,
    ):
        if not isinstance(grant, WebResearchGrant):
            raise WebResearchDenied("Веб-поиск требует явного сетевого разрешения")
        self.grant = grant
        self._resolver = resolver or self._resolve_public_addresses
        self._requester = requester or self._request_pinned
        self.search_url = search_url or self.SEARCH_URL

    @classmethod
    def _validate_query(cls, query: object) -> str:
        if not isinstance(query, str):
            raise WebResearchDenied("Запрос для веб-поиска должен быть текстом")
        query = " ".join(query.split()).strip()
        if not 2 <= len(query) <= cls.MAX_QUERY_CHARACTERS:
            raise WebResearchDenied("Уточни запрос для веб-поиска (от 2 до 500 символов)")
        if any(not char.isprintable() or unicodedata.category(char) in {"Cf", "Cs"} for char in query):
            raise WebResearchDenied("Запрос содержит недопустимые символы")
        return query

    @staticmethod
    def _check_limits(is_cancelled: Callable[[], bool] | None, deadline: float) -> None:
        if is_cancelled is not None:
            try:
                cancelled = bool(is_cancelled())
            except Exception:
                cancelled = True
            if cancelled:
                raise WebResearchDenied("Веб-запрос отменён")
        if time.monotonic() >= deadline:
            raise WebResearchDenied("Истёк общий лимит времени веб-исследования")

    @staticmethod
    def _normalize_url(url: str) -> tuple[str, str, str, tuple[str, ...]]:
        if not isinstance(url, str) or not url or len(url) > WebResearchClient.MAX_URL_CHARACTERS:
            raise WebResearchDenied("Недопустимый адрес страницы")
        if "\\" in url or any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise WebResearchDenied("Адрес содержит управляющие символы")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise WebResearchDenied("Некорректный адрес страницы") from None
        if (parts.scheme.casefold() != "https" or parts.username is not None
                or parts.password is not None or not parts.hostname or port not in (None, 443)):
            raise WebResearchDenied("Разрешены только публичные HTTPS-страницы без учётных данных")
        host = parts.hostname.rstrip(".").casefold()
        if (not host or len(host) > 253
                or host in {"localhost", "localhost.localdomain"}
                or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".onion"))):
            raise WebResearchDenied("Локальные и специальные адреса недоступны")
        try:
            ip = ipaddress.ip_address(host)
            candidates = (str(ip),)
        except ValueError:
            try:
                host = host.encode("idna").decode("ascii")
            except Exception:
                raise WebResearchDenied("Некорректное имя сайта") from None
            candidates = ()
        host_header = f"[{host}]" if ":" in host else host
        path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
        query = quote(parts.query, safe="/%:@-._~!$&'()*+,;=?")
        normalized_url = urlunsplit(("https", host_header, path, query, ""))
        target = path + ("?" + query if query else "")
        return normalized_url, host, target, candidates

    @classmethod
    def _validate_and_resolve(cls, url: str, resolver: Callable[[str], list[str] | tuple[str, ...]]):
        normalized_url, host, _target, candidates = cls._normalize_url(url)
        if not candidates:
            try:
                candidates = tuple(resolver(host))
            except WebResearchDenied:
                raise
            except Exception:
                raise WebResearchDenied("Не удалось проверить адрес сайта") from None
        if not candidates or len(candidates) > 16:
            raise WebResearchDenied("Некорректный ответ DNS для сайта")
        addresses = []
        for candidate in candidates:
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                raise WebResearchDenied("DNS вернул некорректный адрес") from None
            if not address.is_global:
                raise WebResearchDenied("Сайты в локальных и специальных сетях недоступны")
            normalized = str(address)
            if normalized not in addresses:
                addresses.append(normalized)
        return normalized_url, host, tuple(addresses)

    @staticmethod
    def _resolve_public_addresses(host: str) -> list[str]:
        try:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise WebResearchDenied("Не удалось найти адрес сайта") from None
        return list(dict.fromkeys(record[4][0] for record in records))

    @staticmethod
    def _request_pinned(
        url: str,
        addresses: tuple[str, ...],
        timeout: float,
        max_bytes: int,
        is_cancelled: Callable[[], bool] | None,
    ) -> _HTTPResponse:
        parsed = urlsplit(url)
        connection = _PinnedHTTPSConnection(parsed.hostname or "", addresses, timeout)
        deadline = time.monotonic() + timeout
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={
                "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "User-Agent": "AstraVoiceAssistant/3.2 (public read-only research)",
                "Connection": "close",
            })
            response = connection.getresponse()
            headers = {key.casefold(): value for key, value in response.getheaders()}
            body = bytearray()
            while True:
                WebResearchClient._check_limits(is_cancelled, deadline)
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise WebResearchDenied("Истёк лимит времени чтения сайта")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining_time)
                remaining = max_bytes + 1 - len(body)
                if remaining <= 0:
                    break
                chunk = response.read(min(64_000, remaining))
                if not chunk:
                    break
                body.extend(chunk)
            return _HTTPResponse(response.status, headers, bytes(body))
        finally:
            connection.close()

    def _fetch_bytes(
        self,
        url: str,
        *,
        scope: str,
        is_cancelled: Callable[[], bool] | None,
        deadline: float,
    ) -> tuple[str, str, bytes]:
        current = url
        for redirect in range(self.MAX_REDIRECTS + 1):
            self._check_limits(is_cancelled, deadline)
            self.grant.consume(scope)
            normalized, _host, addresses = self._validate_and_resolve(current, self._resolver)
            timeout = min(self.REQUEST_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic()))
            try:
                response = self._requester(normalized, addresses, timeout, self.MAX_BODY_BYTES, is_cancelled)
            except WebResearchDenied:
                raise
            except Exception:
                raise WebResearchDenied("Не удалось загрузить страницу с сайта") from None
            if not isinstance(response, _HTTPResponse):
                raise WebResearchDenied("Некорректный ответ сетевого слоя")
            if 300 <= response.status < 400:
                location = response.headers.get("location", "")
                if redirect >= self.MAX_REDIRECTS or not location:
                    raise WebResearchDenied("Слишком много перенаправлений страницы")
                current = urljoin(normalized, location)
                continue
            if response.status != 200:
                raise WebResearchDenied(f"Сайт вернул HTTP {response.status}")
            if len(response.body) > self.MAX_BODY_BYTES:
                raise WebResearchDenied("Страница превышает лимит 1 МБ")
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
            allowed_media_types = {"text/html", "application/xhtml+xml", "text/plain"}
            if scope == "search":
                allowed_media_types.update({"application/rss+xml", "application/xml", "text/xml"})
            if media_type not in allowed_media_types:
                raise WebResearchDenied("Сайт вернул неподдерживаемый тип содержимого")
            charset = "utf-8"
            for parameter in response.headers.get("content-type", "").split(";")[1:]:
                key, separator, value = parameter.partition("=")
                if separator and key.strip().casefold() == "charset":
                    proposed = value.strip().strip("\"'")[:40]
                    if proposed:
                        charset = proposed
                    break
            try:
                text = response.body.decode(charset, errors="replace")
            except LookupError:
                text = response.body.decode("utf-8", errors="replace")
            return normalized, media_type, text.encode("utf-8")
        raise WebResearchDenied("Слишком много перенаправлений страницы")

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> tuple[WebSearchHit, ...]:
        query = self._validate_query(query)
        if type(max_results) is not int or not 1 <= max_results <= self.MAX_SEARCH_RESULTS:
            raise WebResearchDenied("Число результатов должно быть от 1 до 10")
        if deadline is None:
            deadline = time.monotonic() + self.REQUEST_TIMEOUT_SECONDS
        elif isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise WebResearchDenied("Некорректный лимит времени веб-поиска")
        encoded = quote_plus(query, safe="")
        base = urlsplit(self.search_url)
        base_query = base.query + ("&" if base.query else "") + "q=" + encoded
        search_url = urlunsplit((base.scheme, base.netloc, base.path, base_query, ""))
        _url, media_type, body = self._fetch_bytes(
            search_url,
            scope="search",
            is_cancelled=is_cancelled,
            deadline=deadline,
        )
        text = body.decode("utf-8", errors="replace")
        check_limits = lambda: self._check_limits(is_cancelled, deadline)
        if media_type in {"text/html", "application/xhtml+xml"}:
            parser = _SearchParser(check_limits)
            parser.feed(text)
            parser.close()
            parsed_hits = parser.results
        elif media_type in {"application/rss+xml", "application/xml", "text/xml"}:
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
                raise WebResearchDenied("DTD и XML-сущности в поисковой выдаче запрещены")
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                raise WebResearchDenied("Поисковая служба вернула повреждённый XML") from None
            parsed_hits = []
            for index, item in enumerate(
                node for node in root.iter()
                if node.tag.rsplit("}", 1)[-1].casefold() == "item"
            ):
                if index >= 20:
                    break
                check_limits()
                fields = {
                    child.tag.rsplit("}", 1)[-1].casefold(): "".join(child.itertext())
                    for child in item
                }
                title = " ".join(_strip_controls(fields.get("title", "")).split())[:300]
                target = _strip_controls(fields.get("link", "")).strip()[:4096]
                snippet_raw = fields.get("description", "")
                snippet_parser = _HTMLTextParser(check_limits, 600)
                snippet_parser.feed(snippet_raw)
                snippet_parser.close()
                snippet = " ".join(snippet_parser.text().split())[:600]
                if title and target:
                    parsed_hits.append(WebSearchHit(title, target, snippet))
        else:
            raise WebResearchDenied("Поисковая служба вернула неподдерживаемый формат")
        unique = []
        seen = set()
        for result in parsed_hits:
            try:
                normalized, _host, _target, _literal_addresses = self._normalize_url(result.url)
            except WebResearchDenied:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(WebSearchHit(result.title, normalized, result.snippet))
            if len(unique) >= max_results:
                break
        return tuple(unique)

    def fetch_page(
        self,
        url: str,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> WebPage:
        if deadline is None:
            deadline = time.monotonic() + self.REQUEST_TIMEOUT_SECONDS
        elif isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise WebResearchDenied("Некорректный лимит времени чтения страницы")
        normalized, media_type, body = self._fetch_bytes(
            url,
            scope="read",
            is_cancelled=is_cancelled,
            deadline=deadline,
        )
        text = body.decode("utf-8", errors="replace")
        if media_type == "text/plain":
            plain = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
            plain = "\n".join(line.strip() for line in plain.splitlines()).strip()
            visible, title = plain[:self.MAX_PAGE_CHARACTERS], ""
        else:
            parser = _HTMLTextParser(
                lambda: self._check_limits(is_cancelled, deadline),
                self.MAX_PAGE_CHARACTERS,
            )
            parser.feed(text)
            parser.close()
            visible, title = parser.text(), parser.title
        self._check_limits(is_cancelled, deadline)
        if not visible:
            raise WebResearchDenied("На странице нет извлекаемого видимого текста")
        return WebPage(title or normalized, normalized, visible)

    def research(
        self,
        query: str,
        *,
        max_results: int = 5,
        max_pages: int = 3,
        is_cancelled: Callable[[], bool] | None = None,
        deadline: float | None = None,
    ) -> WebResearchResult:
        query = self._validate_query(query)
        if type(max_pages) is not int or not 1 <= max_pages <= self.MAX_PAGES_PER_RESEARCH:
            raise WebResearchDenied("За один запрос можно прочитать от 1 до 5 страниц")
        now = time.monotonic()
        default_deadline = now + self.RESEARCH_TIMEOUT_SECONDS
        if deadline is None:
            deadline = default_deadline
        elif isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise WebResearchDenied("Некорректный лимит времени веб-исследования")
        else:
            try:
                if not math.isfinite(deadline):
                    raise WebResearchDenied("Некорректный лимит времени веб-исследования")
            except OverflowError:
                raise WebResearchDenied("Некорректный лимит времени веб-исследования") from None
            deadline = min(float(deadline), default_deadline)
        if deadline <= now:
            raise WebResearchDenied("Истёк общий лимит времени веб-исследования")
        hits = self.search(
            query,
            max_results=max_results,
            is_cancelled=is_cancelled,
            deadline=deadline,
        )
        pages = []
        failures = 0
        for hit in hits:
            if len(pages) >= max_pages:
                break
            self._check_limits(is_cancelled, deadline)
            try:
                pages.append(self.fetch_page(hit.url, is_cancelled=is_cancelled, deadline=deadline))
            except WebGrantDenied:
                raise
            except WebResearchDenied:
                self._check_limits(is_cancelled, deadline)
                self.grant.require_active("read")
                failures += 1
                continue
        if hits and not pages and failures:
            raise WebResearchDenied("Не удалось безопасно прочитать ни одну страницу результатов")
        return WebResearchResult(query, hits, tuple(pages))
