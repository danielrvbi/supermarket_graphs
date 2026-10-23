"""
AH PDF preprocessing: extract text using pdfplumber with layout preservation.
"""

import pdfplumber
from pathlib import Path
from typing import Optional

from v2.stage1_extraction.ah.state import AHPipelineState


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract raw text from an AH PDF, preserving layout.

    Uses layout=True to help the LLM understand columns (item name vs price).

    Args:
        file_path: Path to the PDF file

    Returns:
        Extracted text with layout preserved
    """
    raw_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text(layout=True) + "\n"
    return raw_text


def extract_date_from_filename(file_path: str) -> Optional[str]:
    """
    Extract date from AH filename format: AH_kassabon_YYYY-MM-DD_HHMM_store.pdf

    Args:
        file_path: Path to the PDF file

    Returns:
        Date string in YYYY-MM-DD format, or None
    """
    import re
    filename = Path(file_path).name
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if match:
        return match.group(1)
    return None


def preprocess_node(state: AHPipelineState) -> AHPipelineState:
    """
    LangGraph node: Preprocess AH PDF receipt.

    Extracts text from PDF and extracts date from filename.
    """
    receipt_path = state["receipt_path"]

    try:
        raw_text = extract_text_from_pdf(receipt_path)
        date_from_filename = extract_date_from_filename(receipt_path)

        return {
            **state,
            "raw_text": raw_text,
            "date_from_filename": date_from_filename,
            "processing_steps": state.get("processing_steps", []) + ["preprocess"],
        }
    except Exception as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"Preprocessing failed: {str(e)}"],
            "processing_steps": state.get("processing_steps", []) + ["preprocess_failed"],
        }
