"""
Jumbo image preprocessing: crop and OCR using pytesseract.

Jumbo receipts are screenshots/images that need OCR to extract text.
"""

import re
from pathlib import Path
from typing import Optional

import cv2
import pytesseract
from pytesseract import Output

from v2.stage1_extraction.jumbo.state import JumboPipelineState


def crop_receipt_image(image_path: str, output_path: str = None) -> Optional[str]:
    """
    Crop a Jumbo receipt image to remove everything below the 'Totaal' line.

    This removes payment metadata, QR codes, and other non-essential content.

    Args:
        image_path: Path to the original image
        output_path: Path to save cropped image (None = in-memory only)

    Returns:
        Path to cropped image, or None if cropping failed
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image at {image_path}")

    # Convert to grayscale for OCR
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Get detailed OCR data with bounding boxes
    custom_config = r'--oem 3 --psm 6'
    ocr_data = pytesseract.image_to_data(gray, config=custom_config, output_type=Output.DICT)

    crop_y = None
    padding = 30  # Pixels to leave below the 'Totaal' line

    # Find the 'Totaal' line
    n_boxes = len(ocr_data['text'])
    for i in range(n_boxes):
        word = ocr_data['text'][i].strip()
        if re.search(r'(?i)^totaal', word):
            y = ocr_data['top'][i]
            h = ocr_data['height'][i]
            crop_y = y + h + padding
            break

    if crop_y is not None:
        img_height = img.shape[0]
        crop_y = min(crop_y, img_height)
        cropped_img = img[:crop_y, :]

        if output_path:
            cv2.imwrite(output_path, cropped_img)
            return output_path
        return cropped_img
    else:
        # 'Totaal' not found, return original
        return image_path


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from a Jumbo receipt image using pytesseract OCR.

    Args:
        image_path: Path to the image file

    Returns:
        Extracted text
    """
    # Try to crop first (removes noise below Totaal)
    try:
        cropped = crop_receipt_image(image_path)
        if isinstance(cropped, str):
            img = cv2.imread(cropped)
        else:
            img = cropped
    except Exception:
        img = cv2.imread(image_path)

    if img is None:
        raise ValueError(f"Could not load image at {image_path}")

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Extract text with PSM 6 (uniform block of text)
    custom_config = r'--oem 3 --psm 6'
    raw_text = pytesseract.image_to_string(gray, config=custom_config)

    return raw_text


def estimate_ocr_quality(image_path: str) -> float:
    """
    Estimate OCR quality by checking text extraction confidence.

    Returns:
        Quality score 0.0-1.0
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return 0.0

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        custom_config = r'--oem 3 --psm 6'
        ocr_data = pytesseract.image_to_data(gray, config=custom_config, output_type=Output.DICT)

        confidences = [int(c) for c in ocr_data['conf'] if int(c) > 0]
        if not confidences:
            return 0.5

        avg_conf = sum(confidences) / len(confidences)
        return avg_conf / 100.0

    except Exception:
        return 0.5


def preprocess_node(state: JumboPipelineState) -> JumboPipelineState:
    """
    LangGraph node: Preprocess Jumbo image receipt.

    Crops image and extracts text using OCR.
    """
    receipt_path = state["receipt_path"]

    try:
        raw_text = extract_text_from_image(receipt_path)
        ocr_quality = estimate_ocr_quality(receipt_path)

        return {
            **state,
            "raw_text": raw_text,
            "ocr_quality_score": ocr_quality,
            "processing_steps": state.get("processing_steps", []) + ["preprocess"],
        }
    except Exception as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"OCR preprocessing failed: {str(e)}"],
            "ocr_quality_score": 0.0,
            "processing_steps": state.get("processing_steps", []) + ["preprocess_failed"],
        }
