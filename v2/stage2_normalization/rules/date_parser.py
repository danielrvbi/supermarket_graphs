"""
Date parsing and standardization rules.

Ported from V1:
- parse_dutch_dates() for Jumbo receipts
- Date extraction from AH filenames
"""

import re
from datetime import datetime
from typing import Optional


# Dutch month name mapping
DUTCH_MONTH_MAP = {
    'januari': '01', 'februari': '02', 'maart': '03',
    'april': '04', 'mei': '05', 'juni': '06',
    'juli': '07', 'augustus': '08', 'september': '09',
    'oktober': '10', 'november': '11', 'december': '12'
}


def parse_dutch_date(date_str: str) -> Optional[str]:
    """
    Parse Dutch date strings into ISO format (YYYY-MM-DD).

    Handles formats like:
        "Dinsdag 12 mei 2026" -> "2026-05-12"
        "maandag 19 januari 2026" -> "2026-01-19"
        "2) maandag 19 januari 2026" -> "2026-01-19" (with OCR artifacts)

    Ported from V1 parse_dutch_dates().

    Args:
        date_str: Dutch date string

    Returns:
        ISO date string (YYYY-MM-DD) or None if parsing fails
    """
    if not date_str:
        return None

    s = str(date_str).lower().strip()

    # Extract day, month name, and year using regex
    # This automatically ignores any weekday strings or OCR artifacts at the start
    extracted = re.search(r'(\d{1,2})\s+([a-z]+)\s+(\d{4})', s)

    if not extracted:
        return None

    day = extracted.group(1).zfill(2)
    month_name = extracted.group(2)
    year = extracted.group(3)

    # Map Dutch month name to number
    month = DUTCH_MONTH_MAP.get(month_name)
    if not month:
        return None

    return f"{year}-{month}-{day}"


def standardize_date(date_str: str, store: str = "ah") -> Optional[str]:
    """
    Standardize date to ISO format (YYYY-MM-DD).

    For AH: dates are typically "YYYY/MM/DD" or "DD-MM-YYYY"
    For Jumbo: dates are Dutch text like "Dinsdag 12 mei 2026"

    Args:
        date_str: Raw date string from receipt
        store: "ah" or "jumbo"

    Returns:
        ISO date string (YYYY-MM-DD) or None if parsing fails
    """
    if not date_str:
        return None

    s = str(date_str).strip()

    # Already ISO format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s

    # AH format: YYYY/MM/DD
    if re.match(r'^\d{4}/\d{2}/\d{2}$', s):
        return s.replace('/', '-')

    # AH format: DD-MM-YYYY or DD/MM/YYYY
    match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$', s)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Try Dutch date parsing (for Jumbo)
    dutch_date = parse_dutch_date(s)
    if dutch_date:
        return dutch_date

    # Try common datetime parsing as fallback
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def get_month_of_purchase(date_iso: Optional[str]) -> Optional[str]:
    """
    Extract month start date (YYYY-MM-01) from ISO date.

    Args:
        date_iso: ISO date string (YYYY-MM-DD)

    Returns:
        Month start date (YYYY-MM-01) or None
    """
    if not date_iso or not re.match(r'^\d{4}-\d{2}-\d{2}$', date_iso):
        return None
    return f"{date_iso[:7]}-01"


def extract_date_from_filename(filename: str) -> Optional[str]:
    """
    Extract date from AH receipt filename.

    AH filenames look like: "AH_kassabon_2024-03-08_1621_1080.pdf"

    Args:
        filename: Receipt filename or path

    Returns:
        ISO date string (YYYY-MM-DD) or None
    """
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    return None
