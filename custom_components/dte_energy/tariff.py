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
        # The page repeats these labels for the current, cancelled, and
        # retired rate books. The current rate-book links appear first, so
        # retain the first match for each section instead of overwriting it
        # with a later retired/cancelled-book link.
        if (
            "sheets a-1.00 through c" in normalized
            and "adjustments" not in result
        ):
            result["adjustments"] = urljoin(MPSC_DTE_RATE_BOOK_PAGE, href)
        elif (
            "sheets d1 through end" in normalized
            and "rates" not in result
        ):
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


def _normalized(text: str) -> str:
    """Collapse PDF extraction whitespace for resilient tariff parsing."""
    return " ".join(text.replace("\u00a0", " ").split())


def _money(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _parse_rider18(text: str) -> dict[str, Any]:
    """Parse residential Rider 18 base outflow credits from the rate book."""
    normalized = _normalized(text)
    match = re.search(
        r"STANDARD CONTRACT RIDER NO\.\s*18\b.*?DISTRIBUTED GENERATION PROGRAM",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return {"available": False, "rates": {}, "diagnostic": "rider18_heading_not_found"}

    segment = normalized[match.start():]
    end_match = re.search(
        r"STANDARD CONTRACT RIDER NO\.\s*20\b",
        segment,
        re.IGNORECASE,
    )
    if end_match:
        segment = segment[:end_match.start()]

    # PDF text extraction can interleave table headers/columns differently
    # across MPSC revisions. Once Rider 18 itself is located, parse the whole
    # rider segment rather than requiring one exact extracted header string.
    table = segment

    rates: dict[str, dict[str, float | None]] = {
        "D1.2": {
            "summer_on_peak": _money(
                r"D1\.2\s+Time-of-Day\s+Summer\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "summer_off_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Summer\s+Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "winter_on_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Winter\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "winter_off_peak": _money(
                r"D1\.2\s+Time-of-Day.*?Winter\s+Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
        },
        "D1.7": {
            "summer_on_peak": _money(
                r"D1\.7\s+Time-of-Day\s+Summer\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "summer_off_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Summer\s+Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "winter_on_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Winter\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "winter_off_peak": _money(
                r"D1\.7\s+Time-of-Day.*?Winter\s+Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
        },
        "D1.8": {
            "critical_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic)\s+Peak\s+Pricing\s+Critical\s+Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "on_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic)\s+Peak\s+Pricing.*?On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "mid_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic)\s+Peak\s+Pricing.*?Mid-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "off_peak": _money(
                r"D1\.8\s+(?:Dynamic|Dymanic)\s+Peak\s+Pricing.*?Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
        },
        "D1.9": {
            "on_peak": _money(
                r"D1\.9\s+Elec\.\s*Vehicle\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "off_peak": _money(
                r"D1\.9\s+Elec\.\s*Vehicle.*?Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
        },
        "D1.11": {
            "jun_sep_on_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU\s+June-Sept\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "jun_sep_off_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?June-Sept\s+Off-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "oct_may_on_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?Oct-May\s+On-Peak:\s*\$0?([0-9.]+)",
                table,
            ),
            "oct_may_off_peak": _money(
                r"D1\.11\s+Stan\.\s*TOU.*?Oct-May\s+Off-Peak:\s*\$0*([0-9.]+)",
                table,
            ),
        },
        "D1.13": {
            "jun_sep_on_peak": _money(
                r"D1\.13\s+Overnight\s+Savers\s+On-Peak:\s*June-Sept:\s*\$0?([0-9.]+)",
                table,
            ),
            "oct_may_on_peak": _money(
                r"D1\.13\s+Overnight\s+Savers\s+On-Peak:.*?Oct-May:\s*\$0?([0-9.]+)",
                table,
            ),
            "jun_sep_off_peak": _money(
                r"D1\.13\s+Overnight\s+Savers.*?Off-Peak:\s*June-Sept:\s*\$0?([0-9.]+)",
                table,
            ),
            "oct_may_off_peak": _money(
                r"D1\.13\s+Overnight\s+Savers.*?Off-Peak:.*?Oct-May:\s*\$0?([0-9.]+)",
                table,
            ),
            "super_off_peak": _money(
                r"D1\.13\s+Overnight\s+Savers.*?Super\s+Off-Peak:\s*June-Sept:\s*\$0?([0-9.]+)",
                table,
            ),
        },
    }

    rates = {
        schedule: values
        for schedule, values in rates.items()
        if any(value is not None for value in values.values())
    }

    effective_match = re.search(
        r"Effective for service rendered on\s+.*?after\s+"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        segment[:2200],
        re.IGNORECASE,
    )

    result = {
        "available": bool(rates),
        "effective_date": effective_match.group(1) if effective_match else None,
        "rates": rates,
        "unit": "USD/kWh",
        "note": "Base Rider 18 outflow credit; add the applicable PSCR factor.",
    }
    if not rates:
        result["diagnostic"] = "rider18_rates_not_found"
    return result


def _parse_pscr(text: str) -> dict[str, Any]:
    """Parse monthly actual PSCR factors from Sheet C-62.00."""
    normalized = _normalized(text)
    marker = re.search(
        r"C8\.1\s+Power Supply Cost Recovery \(PSCR\) Clause",
        normalized,
        re.IGNORECASE,
    )
    if not marker:
        return {
            "available": False,
            "actual_cents_per_kwh": {},
            "diagnostic": "pscr_clause_not_found",
        }

    segment = normalized[marker.start():]
    years_match = re.search(
        r"calendar years\s+(20\d{2})\s+and\s+(20\d{2}).*?"
        r"\1\s+\2\s+Billing Month",
        segment,
        re.IGNORECASE,
    )
    if not years_match:
        return {
            "available": False,
            "actual_cents_per_kwh": {},
            "diagnostic": "pscr_year_table_not_found",
        }

    years = [years_match.group(1), years_match.group(2)]
    table = segment[years_match.start():]
    months = (
        "January February March April May June July August "
        "September October November December"
    ).split()

    actual: dict[str, dict[str, float]] = {years[0]: {}, years[1]: {}}
    for index, month in enumerate(months):
        next_month = months[index + 1] if index + 1 < len(months) else None
        if next_month:
            row_match = re.search(
                rf"{month}\s+(.*?)(?=\s+{next_month}\s+)",
                table,
                re.IGNORECASE,
            )
        else:
            row_match = re.search(
                rf"{month}\s+(.*?)(?=\s+The Company will file)",
                table,
                re.IGNORECASE,
            )
        if not row_match:
            continue

        numbers = [
            float(value)
            for value in re.findall(r"-?[0-9]+(?:\.[0-9]+)?", row_match.group(1))
        ]
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
