"""Parse RFC 822 email files into task drafts."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import PurePosixPath


MAX_IMPORTED_DESCRIPTION_LENGTH = 10_000
MAX_IMPORTED_HEADER_LENGTH = 500
_TRUNCATION_NOTE = "\n\n[Email body truncated. The original email is attached.]"


@dataclass(frozen=True)
class EmailTaskDraft:
    title: str
    description: str


class _EmailHtmlTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "ol",
        "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
    _IGNORED_TAGS = {"head", "script", "style", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        elif not self._ignored_depth and tag == "img":
            alt = next((value for name, value in attrs if name == "alt"), None)
            if alt:
                self.parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag: str):
        if tag in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self._ignored_depth:
            self.parts.append(data)


def _clean_header(value: object) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    )
    return re.sub(r"\s+", " ", text).strip()


def _part_text(part: Message) -> str:
    try:
        value = part.get_content()
    except (LookupError, UnicodeError, TypeError):
        payload = part.get_payload(decode=True)
        if not payload:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset, errors="replace")
        except LookupError:
            value = payload.decode("utf-8", errors="replace")

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _body_text(message: Message) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""

    value = _part_text(part)
    if part.get_content_type() == "text/html":
        parser = _EmailHtmlTextParser()
        parser.feed(value)
        parser.close()
        value = "".join(parser.parts)

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def parse_eml_message(content: bytes, filename: str = "email.eml") -> EmailTaskDraft:
    """Return a safe, plain-text task draft from one RFC 822 message."""
    separator = b"\r\n\r\n" if b"\r\n\r\n" in content else b"\n\n"
    header_block, found_separator, _ = content.partition(separator)
    if not found_separator:
        raise ValueError("This file is not a supported email message (.eml).")

    header_names = {
        match.group(1).decode("ascii", errors="ignore").lower()
        for line in header_block.splitlines()
        if (match := re.match(rb"^([!#$%&'*+.^_`|~0-9A-Za-z-]+):", line))
    }
    if not header_names.intersection({"from", "to", "date", "subject", "message-id", "mime-version"}):
        raise ValueError("This file is not a supported email message (.eml).")

    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as error:
        raise ValueError("Questline could not read this email message.") from error

    subject = _clean_header(message.get("subject"))
    fallback = PurePosixPath((filename or "").replace("\\", "/")).stem
    title = (subject or _clean_header(fallback) or "Email without a subject")[:200]

    metadata = []
    for label, header in (("From", "from"), ("To", "to"), ("Date", "date")):
        value = _clean_header(message.get(header))
        if value:
            metadata.append(f"{label}: {value[:MAX_IMPORTED_HEADER_LENGTH]}")

    body = _body_text(message)
    description_parts = ["\n".join(metadata)] if metadata else []
    if body:
        description_parts.append(body)
    else:
        description_parts.append("[No text body is available. The original email is attached.]")

    description = "\n\n".join(description_parts)
    if len(description) > MAX_IMPORTED_DESCRIPTION_LENGTH:
        body_budget = max(
            0,
            MAX_IMPORTED_DESCRIPTION_LENGTH - len("\n\n".join(description_parts[:-1])) - 2 - len(_TRUNCATION_NOTE),
        )
        truncated_body = body[:body_budget].rstrip() + _TRUNCATION_NOTE
        description_parts[-1] = truncated_body
        description = "\n\n".join(description_parts)
        description = description[:MAX_IMPORTED_DESCRIPTION_LENGTH]

    return EmailTaskDraft(title=title, description=description)
