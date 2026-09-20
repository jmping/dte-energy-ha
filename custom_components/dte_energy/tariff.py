"""Dynamic DTE tariff source backed by the MPSC-approved rate book."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from io import BytesIO
import logging
import re
from typing import Any
from urllib.parse import urljoin

import aiohttp
from pypdf import PdfReader

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MPSC_DTE_RATE_BOOK_PAGE = (
    "https://www.michigan.gov/mpsc/consumer/electricity/data-price/"
    "electric-rate-books/"
    "mpsc-approved-dte-electric-rate-books-and-cancelled-sheets"
)

_STORE_VERSION = 1

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class _AnchorParser(HTMLParser):
    """Collect anchor href/text pairs from the MPSC rate-book page."""

    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        self._href = values.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        text = " ".join("".join(self._text).split())
        self.anchors.append((self._href, text))
        self._href = None
        self._text = []


class DTETariffManager:
    """Fetch, parse, and retain revisions of DTE tariff data."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}.{entry_id}.tariffs"
        )

    async def async_refresh(self) -> dict[str, Any]:
        """Refresh current MPSC tariff data and retain a revision snapshot."""
        session = async_get_clientsession(self.hass)
        async with session.get(
            MPSC_DTE_RATE_BOOK_PAGE,
            headers=_REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as response:
            response.raise_for_status()
            landing_html = await response.text()

        links = _discover_rate_book_links(landing_html)
        if "rates" not in links or "adjustments" not in links:
            raise ValueError("Could not discover current DTE MPSC rate-book PDFs")

        rates_pdf, adjustments_pdf = await _download_pdfs(session, links)
        source_hash = hashlib.sha256(rates_pdf + adjustments_pdf).hexdigest()

        rates_text, adjustments_text = await self.hass.async_add_executor_job(
            _extract_both_pdf_text, rates_pdf, adjustments_pdf
        )

        current = {
            "source": "Michigan Public Service Commission",
            "source_page": MPSC_DTE_RATE_BOOK_PAGE,
            "rates_pdf": links["rates"],
            "adjustments_pdf": links["adjustments"],
            "source_hash": source_hash,
            "checked_at": dt_util.utcnow().isoformat(),
            "rider18": _parse_rider18(rates_text),
            "pscr": _parse_pscr(adjustments_text),
        }

        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {"snapshots": []}

        snapshots = stored.setdefault("snapshots", [])
        if not isinstance(snapshots, list):
            snapshots = []
            stored["snapshots"] = snapshots

        if not any(
            isinstance(item, dict) and item.get("source_hash") == source_hash
            for item in snapshots
        ):
            snapshots.append(current)
            # Rate-book revisions are infrequent, but cap local storage anyway.
            if len(snapshots) > 50:
                del snapshots[:-50]

        stored["current"] = current
        await self._store.async_save(stored)
        return current

    async def async_load_cached(self) -> dict[str, Any] | None:
        """Return the last successfully parsed tariff snapshot."""
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("current"), dict):
            return stored["current"]
        return None


def _discover_rate_book_links(html: str) -> dict[str, str]:
    """Resolve the current MPSC Section C and Section D rate-book PDFs."""
    parser = _AnchorParser()
    parser.feed(html)

    result: dict[str, str] = {}
    for href, text in parser.anchors:
        normalized = text.lower()
        if "sheets a-1.00 through c" in normalized:
            result["adjustments"] = urljoin(MPSC_DTE_RATE_BOOK_PAGE, href)
        elif "sheets d1 through end" in normalized:
            result["rates"] = urljoin(MPSC_DTE_RATE_BOOK_PAGE, href)

    return result


async def _download_pdfs(
    session: aiohttp.ClientSession, links: dict[str, str]
) -> tuple[bytes, bytes]:
    """Download the current rates and adjustments PDF documents."""
    async def _get(url: str) -> bytes:
        async with session.get(
            url,
            headers=_REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as response:
            response.raise_for_status()
            return await response.read()

    rates_pdf = await _get(links["rates"])
    adjustments_pdf = await _get(links["adjustments"])
    return rates_pdf, adjustments_pdf


def _extract_both_pdf_text(
    rates_pdf: bytes, adjustments_pdf: bytes
) -> tuple[str, str]:
    """Extract text from both PDFs off the Home Assistant event loop."""
    return _extract_pdf_text(rates_pdf), _extract_pdf_text(adjustments_pdf)


def _extract_pdf_text(data: bytes) -> str:
    """Extract normalized text from a PDF."""
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    # Preserve line breaks for diagnostics but make malformed dollar values
    # such as "$00.08728" parseable.
    return text.replace("$00.", "$0.").replace("$.0.", "$0.")


def _money(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return float(match.group(1))


def _parse_rider18(text: str) -> dict[str, Any]:
    """Parse residential Rider 18 base outflow credits from the rate book."""
    start = text.find("STANDARD CONTRACT RIDER NO. 18")
    if start == -1:
        return {"available": False, "rates": {}}

    segment = text[start:]
    # Limit parsing to the Rider 18 section.
    end = segment.find("STANDARD CONTRACT RIDER NO. 20")
    if end != -1:
        segment = segment[:end]

    rates: dict[str, dict[str, float | None]] = {
        "D1.2": {
            "summer_on_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Summer\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "summer_off_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Summer\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "winter_on_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Winter\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "winter_off_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Winter\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
        },
        "D1.7": {
            "summer_on_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Summer\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "summer_off_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Summer\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "winter_on_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Winter\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "winter_off_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Winter\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
        },
        "D1.8": {
            "critical_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic) Peak.*?Critical\s+Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "on_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic) Peak.*?On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "mid_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic) Peak.*?Mid-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "off_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic) Peak.*?Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
        },
        "D1.9": {
            "on_peak": _money(
                r"D1\.9\s+Elec\.\s*Vehicle\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "off_peak": _money(
                r"D1\.9\s+Elec\.\s*Vehicle.*?Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
        },
        "D1.11": {
            "jun_sep_on_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?June-Sept\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "jun_sep_off_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?June-Sept\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "oct_may_on_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?Oct-May\s+On-Peak:\s*\$([0-9.]+)",
                segment,
            ),
            "oct_may_off_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?Oct-May\s+Off-Peak:\s*\$([0-9.]+)",
                segment,
            ),
        },
        "D1.13": {
            "jun_sep_on_peak": _money(
                r"D1\.13\s+Overnight Savers.*?On-Peak:\s*June-Sept:\s*\$([0-9.]+)",
                segment,
            ),
            "oct_may_on_peak": _money(
                r"D1\.13\s+Overnight Savers.*?On-Peak:.*?Oct-May:\s*\$([0-9.]+)",
                segment,
            ),
            "jun_sep_off_peak": _money(
                r"D1\.13\s+Overnight Savers.*?Off-Peak:\s*June-Sept:\s*\$([0-9.]+)",
                segment,
            ),
            "oct_may_off_peak": _money(
                r"D1\.13\s+Overnight Savers.*?Off-Peak:.*?Oct-May:\s*\$([0-9.]+)",
                segment,
            ),
            "super_off_peak": _money(
                r"D1\.13\s+Overnight Savers.*?Super\s+Off-Peak:\s*June-Sept:\s*\$([0-9.]+)",
                segment,
            ),
        },
    }

    # Remove schedules that failed completely rather than publishing an empty
    # rate table as if it were authoritative.
    rates = {
        schedule: values
        for schedule, values in rates.items()
        if any(value is not None for value in values.values())
    }

    table_marker = segment.find("Rate Schedule Outflow Credit")
    effective_context = (
        segment[max(0, table_marker - 1400):table_marker + 200]
        if table_marker != -1
        else segment[:1600]
    )
    effective_match = re.search(
        r"Effective for service rendered on\s+.*?after\s+"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        effective_context,
        re.IGNORECASE | re.DOTALL,
    )

    return {
        "available": bool(rates),
        "effective_date": (
            effective_match.group(1) if effective_match else None
        ),
        "rates": rates,
        "unit": "USD/kWh",
        "note": "Base Rider 18 outflow credit; add the applicable PSCR factor.",
    }


def _parse_pscr(text: str) -> dict[str, Any]:
    """Parse monthly actual PSCR factors from Sheet C-62.00."""
    marker = "Power Supply Cost Recovery (PSCR) Clause"
    start = text.find(marker)
    if start == -1:
        return {"available": False, "actual_cents_per_kwh": {}}

    segment = text[start:start + 12000]
    years_match = re.search(
        r"(20\d{2})\s+(20\d{2})\s+Billing Month",
        segment,
        re.IGNORECASE | re.DOTALL,
    )
    if not years_match:
        return {"available": False, "actual_cents_per_kwh": {}}

    years = [years_match.group(1), years_match.group(2)]
    months = (
        "January February March April May June July August "
        "September October November December"
    ).split()

    actual: dict[str, dict[str, float]] = {years[0]: {}, years[1]: {}}
    for month in months:
        match = re.search(
            rf"{month}\s+((?:[0-9]+(?:\.[0-9]+)?\s*){{2,4}})",
            segment,
            re.IGNORECASE,
        )
        if not match:
            continue
        numbers = [float(value) for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", match.group(1))]
        if len(numbers) >= 2:
            actual[years[0]][month] = numbers[1]
        if len(numbers) >= 4:
            actual[years[1]][month] = numbers[3]

    return {
        "available": any(actual.values()),
        "actual_cents_per_kwh": actual,
        "unit": "cents/kWh",
        "note": (
            "MPSC rate books can lag pending or newly approved PSCR changes; "
            "missing future-month actual factors are left unset."
        ),
    }
