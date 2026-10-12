"""Bounded, text-only EML/MBOX decoding. No attachment or URL execution."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import stat
from zoneinfo import ZoneInfo

from app.security.policies import BoundaryError

MAX_UPLOAD = 10 * 1024 * 1024
MAX_MESSAGE = 1024 * 1024
MAX_MESSAGES = 200


class TextHTML(HTMLParser):
    blocked = {"script", "style", "head", "iframe", "object", "embed", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.hidden.append(tag)
        if not self.hidden and tag in {"p", "br", "div", "li", "tr", "h1", "h2"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


@dataclass(frozen=True)
class ParsedMail:
    external_id: str
    canonical_hash: str
    message_id: str | None
    subject: str
    sender: str
    body_text: str
    received_at: datetime | None
    date_status: str
    warnings: tuple[str, ...]
    locator: str


def clean_text(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def decode_message(raw, timezone_name, locator):
    if len(raw) > MAX_MESSAGE:
        raise BoundaryError("MESSAGE_TOO_LARGE", 413)
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not any(message.get(name) for name in ["From", "Subject", "Date", "Message-ID"]):
        raise BoundaryError("INVALID_MAIL", 422)
    warnings = []
    if message.defects:
        warnings.append("MIME_DEFECT")
    subject = str(message.get("Subject", "（无主题）"))[:1000]
    addresses = getaddresses([str(message.get("From", ""))])
    sender = addresses[0][1] if addresses and addresses[0][1] else str(message.get("From", "（未知发件人）"))[:200]
    # get_body chooses the message's main text, not forwarded message attachments.
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None and message.get_content_type() in {"text/plain", "text/html"} and message.get_content_disposition() != "attachment":
        body = message
    text = ""
    if body is not None:
        payload = body.get_payload(decode=True) or b""
        charset = body.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
            warnings.append("UNKNOWN_CHARSET")
        if "\ufffd" in text:
            warnings.append("CHARSET_REPLACED")
        if body.get_content_type() == "text/html":
            parser = TextHTML()
            parser.feed(text)
            text = "".join(parser.parts)
    text = clean_text(text)
    if len(text) > 32000:
        raise BoundaryError("MAIL_TEXT_TOO_LARGE", 413)
    if not text:
        warnings.append("EMPTY_BODY")
    received, date_status = None, "unknown"
    try:
        if message.get("Date"):
            received = parsedate_to_datetime(str(message["Date"]))
            if received.tzinfo is None:
                received = received.replace(tzinfo=ZoneInfo(timezone_name))
                date_status = "assumed_timezone"
                warnings.append("HEADER_TIMEZONE_ASSUMED")
            else:
                date_status = "known"
            received = received.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        received = None
    if received is None:
        warnings.append("HEADER_DATE_UNKNOWN")
        date_status = "unknown"
    mid = str(message.get("Message-ID", "")).strip()[:250] or None
    material = "\0".join([subject, sender, text, received.isoformat() if received else ""])
    canonical = hashlib.sha256(material.encode()).hexdigest()
    external = "mid:" + hashlib.sha256((sender + "\0" + mid).encode()).hexdigest() if mid else "content:" + canonical
    return ParsedMail(external, canonical, mid, subject, sender, text, received, date_status, tuple(warnings), locator)


def parse_upload(raw, filename, timezone_name):
    if len(raw) > MAX_UPLOAD:
        raise BoundaryError("UPLOAD_TOO_LARGE", 413)
    if not filename or len(filename) > 120 or any(character in filename for character in ["/", "\\", "\x00"]):
        raise BoundaryError("INVALID_FILENAME", 422)
    suffix = Path(filename).suffix.lower()
    if suffix == ".eml":
        parts = [raw]
    elif suffix == ".mbox":
        # mbox envelope lines; escaped >From body lines never become boundaries.
        envelopes = list(re.finditer(rb"(?m)^From \S+ (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [^\r\n]+\r?\n", raw))
        if not envelopes or raw[:envelopes[0].start()].strip():
            raise BoundaryError("INVALID_MBOX", 422)
        if len(envelopes) > MAX_MESSAGES:
            raise BoundaryError("TOO_MANY_MESSAGES", 413)
        parts = [raw[item.end():envelopes[index + 1].start() if index + 1 < len(envelopes) else len(raw)] for index, item in enumerate(envelopes)]
        parts = [re.sub(rb"(?m)^>(>*From )", rb"\1", part) for part in parts]
    else:
        raise BoundaryError("UNSUPPORTED_MAIL_FORMAT", 422)
    mails, errors, seen = [], [], set()
    for index, part in enumerate(parts):
        try:
            mail = decode_message(part, timezone_name, f"{filename}#{index + 1}")
            if mail.canonical_hash not in seen:
                mails.append(mail)
                seen.add(mail.canonical_hash)
        except BoundaryError as error:
            errors.append({"position": index + 1, "code": error.code})
    return mails, {"total": len(parts), "duplicates_in_file": len(parts) - len(mails) - len(errors), "errors": errors}


def selected_files(root: Path, selected=None):
    """CLI-only explicit scope, flat directory; reject symlinks and junctions."""
    root = root.absolute()
    for component in [root, *root.parents]:
        info = component.lstat()
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise BoundaryError("LINKED_PATH_REJECTED")
    resolved = root.resolve(strict=True)
    candidates = selected if selected is not None else sorted(root.iterdir())
    result = []
    for file in candidates:
        file = Path(file)
        if file.is_symlink() or getattr(file.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise BoundaryError("LINKED_PATH_REJECTED")
        target = file.resolve(strict=True)
        if not target.is_relative_to(resolved):
            raise BoundaryError("PATH_OUTSIDE_SCOPE")
        if target.is_file() and target.suffix.lower() in {".eml", ".mbox"}:
            result.append(target)
    if len(result) > 20 or sum(file.stat().st_size for file in result) > MAX_UPLOAD:
        raise BoundaryError("IMPORT_SCOPE_TOO_LARGE", 413)
    return result
