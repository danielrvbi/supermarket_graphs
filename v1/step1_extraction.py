#!/usr/bin/env python
# coding: utf-8

from pydantic import BaseModel, Field
from typing import Literal, List
from datetime import date
import pandas as pd
import tqdm
import json, os
from dotenv import load_dotenv; load_dotenv()
jjson = lambda x: json.dumps(x, indent=4, ensure_ascii=False)
ppjson = lambda x: print(jjson(x))

def save_to_jsonl(receipt: RawReceipt, output_path: str):
    """Appends the parsed Pydantic model to a JSONL file."""
    with open(output_path, 'a', encoding='utf-8') as f:
        f.write(receipt.model_dump_json() + '\n')

def save_processed_history(dic, file_path):
    # 1. Try to load the existing data first
    try:
        with open(file_path, "r") as f:
            existing_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If the file doesn't exist or is completely empty, start fresh
        existing_data = {}

    # 2. Merge the new dictionary into the existing one
    for key, value in dic.items():
        # Only update if the key doesn't exist yet, OR if its current value is None (null in JSON)
        if existing_data.get(key) is None:
            existing_data[key] = value

    # 3. Save the merged data back to the file
    with open(file_path, "w") as f:
        json.dump(existing_data, f, indent=4)

def load_processed_history(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

def load_processed_history_non_empty(file_path):
    with open(file_path, "r") as f:
        res = json.load(f)

    return {k:v for k,v in res.items() if v is not None}

from langchain_ollama import ChatOllama
tavily_key = os.environ.get("TAVILY_KEY",""); bool(tavily_key)

list_ah_raw_files = get_files_by_creation_date("raw_receipts/ah/", False)
list_jumbo_raw_files = get_files_by_creation_date("raw_receipts/jumbo/", False)

ah_processed = load_processed_history_non_empty("processed/ah_processed.json")
jumbo_processed = load_processed_history_non_empty("processed/jumbo_processed.json")

llms = {
    model_name : (
        ChatOllama(
            model=model_name,
            temperature=0,
            keep_alive="4h"
        )
    )

    for model_name in ["mistral-small3.2:24b"]
}

llms["mistral-small3.2:24b"].invoke("hello")

# # Utils

# ## Jumbo Cropped Images
import cv2
import pytesseract
from pytesseract import Output
import re

def crop_receipt_image(image_path: str, output_path: str = None) -> bool:
    """
    Finds the 'Totaal' line in a receipt and crops the image to remove everything below it.
    Saves the cropped image to output_path.
    
    Returns:
        bool: True if cropped successfully, False if 'Totaal' wasn't found.
    """
    if output_path is None:
        output_path = image_path.replace("raw_receipts/jumbo_raw/","raw_receipts/jumbo/")
    
    # 1. Load the image using OpenCV
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image at {image_path}")
        
    # 2. Convert to grayscale for OCR processing
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 3. Get detailed data including text and bounding box coordinates
    custom_config = r'--oem 3 --psm 6'
    # Output.DICT formats the result as a standard Python dictionary
    ocr_data = pytesseract.image_to_data(gray, config=custom_config, output_type=Output.DICT)
    
    crop_y = None
    padding = 30  # Pixels to leave below the 'Totaal' line so it's easy to read
    
    # 4. Iterate through all detected words
    n_boxes = len(ocr_data['text'])
    for i in range(n_boxes):
        word = ocr_data['text'][i].strip()
        
        # Check if the word matches 'Totaal' (case-insensitive)
        if re.search(r'(?i)^totaal', word):
            # Extract the coordinates for this word
            y = ocr_data['top'][i]
            h = ocr_data['height'][i]
            
            # The cutoff point is the top of the word + its height + some padding
            crop_y = y + h + padding
            break  # Stop searching after the first 'Totaal' is found

    # 5. Crop and save the image
    if crop_y is not None:
        img_height = img.shape[0]
        
        # Ensure the crop coordinate doesn't exceed the actual image height
        crop_y = min(crop_y, img_height)
        
        # Crop the image using numpy array slicing [start_y:end_y, start_x:end_x]
        # We take everything from the top (0) down to crop_y, and all X pixels (:)
        cropped_img = img[:crop_y, :]
        
        # Save the new image
        cv2.imwrite(output_path, cropped_img)
        return True
    else:
        # If 'Totaal' was not found, you can choose to save the original or skip
        print(f"Warning: 'Totaal' not found in {image_path}. Image not cropped.")
        return False

# --- Example Usage ---
# success = crop_receipt_image("jumbo_receipt.jpg", "jumbo_receipt_cropped.jpg")
# if success:
#     print("Successfully cropped and saved the image for verification!")for file_path in tqdm.tqdm(list_jumbo_raw_files):
    crop_receipt_image(file_path)
# ## Base Model

class RawItem(BaseModel):
    item_name: str

    measurement_type: Literal[
        "discrete_units",
        "weight_in_grams"
    ]

    measurement_quantity: float
    price_per_measurement_unit: float
    line_total_paid_amount: float

class RawReceipt(BaseModel):
    date_of_purchase: str
    items: List[RawItem]

from pathlib import Path
from datetime import datetime

def get_files_by_creation_date(folder_path=".", oldest_first=True, file_names_only = True, only_types = [".pdf",".png"]):
    """
    Returns a list of tuples containing (file_path, creation_datetime) 
    for all files in the specified folder, sorted by creation date.
    """
    target_dir = Path(folder_path)
    file_data = []

    # Ensure the directory exists to avoid errors
    if not target_dir.is_dir():
        raise ValueError(f"The path '{folder_path}' is not a valid directory.")

    for file_path in target_dir.iterdir():
        if file_path.is_file():
            skip = True
            for filetype in only_types:
                if str(file_path).endswith(filetype):
                    skip = False
                    break

            if skip: continue

            stat = file_path.stat()

            # st_birthtime captures the true creation date natively on macOS
            timestamp = getattr(stat, 'st_birthtime', stat.st_ctime)

            # Convert timestamp to a datetime object for easier handling later
            dt_object = datetime.fromtimestamp(timestamp)
            file_data.append((str(file_path), dt_object))

    # Sort the list by the datetime object (the second item in the tuple)
    # reverse=False (default) gives oldest first. reverse=True gives newest first.
    ordered_list = sorted(file_data, key=lambda x: x[1], reverse=not oldest_first)
    if not file_names_only:
        return ordered_list

    return [i[0] for i in ordered_list]

# # AH

import pdfplumber
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

def extract_text_from_pdf(file_path: str) -> str:
    """Extracts raw text from the PDF, preserving basic layout."""
    raw_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            # layout=True helps the LLM understand columns (e.g., item name vs price)
            raw_text += page.extract_text(layout=True) + "\n"
    return raw_text

def parse_ah_pdf_with_llm(file_path: str, model_name: str = "mistral-small3.2:24b") -> RawReceipt:
    """Uses a local LLM to parse extracted PDF text into structured JSON."""

    # Extract the raw text first
    receipt_text = extract_text_from_pdf(file_path)

    parser = PydanticOutputParser(pydantic_object=RawReceipt)

    prompt = f"""
You are a structured grocery receipt extraction system.

Extract grocery purchase rows from a Dutch Albert Heijn receipt into valid JSON.

{parser.get_format_instructions()}

Extraction Rules:
1. Keep item names EXACTLY as written on the receipt.
2. Do NOT translate, normalize, infer, or expand abbreviations.
3. Extract ONLY information explicitly present on the receipt.
4. Do NOT calculate or derive values.
5. Ignore:
   - BONUSKAART rows
   - promotional text
   - subtotal/payment sections
   - terminal/payment metadata
   - timestamps/store metadata
6. Determine measurement_type:
   - "discrete_units"
   - "weight_in_grams"
7. Quantity extraction:
   - integer amounts like "3" mean:
       measurement_type="discrete_units"
       measurement_quantity=3
   - weights like "0.327KG" mean:
       measurement_type="weight_in_grams"
       measurement_quantity=327
8. Extract price_per_measurement_unit ONLY if explicitly visible in the PRIJS column.
9. Extract line_total_paid_amount ONLY if explicitly visible in the BEDRAG column.
10. If a field is missing on the receipt, return null.
11. Ignore deposit rows like:
   - +STATIEGELD
12. Every purchased grocery item must become exactly one JSON object.
13. Output ONLY valid JSON.
14. Do not output explanations, markdown, or comments.
15. Date in YYYY/MM/DD format

Receipt Text:
{receipt_text}
"""

    return (
        llms[model_name]
        .with_structured_output(RawReceipt)
        .invoke([
            HumanMessage(prompt)
        ])
        .model_dump()
    )

# # Run AH

import json
import tqdm

def process_batch(file_list, extract_function, file_name, model_name="mistral-small3.2:24b"):
    # 1. Load the history to check existing statuses
    # (Assumes load_processed_history is defined elsewhere in your script)
    history = load_processed_history(file_name)

    # 2. Filter the list BEFORE the progress bar
    # Keep only files that haven't been processed yet (where history value is None)
    files_to_process = [f for f in file_list if history.get(f) is None]

    # Early exit if everything is already processed
    if not files_to_process:
        print("Batch complete. No new files required processing.")
        return

    print(f"Found {len(files_to_process)} files to process (skipped {len(file_list) - len(files_to_process)}).")

    # 3. Track new updates and errors from this specific batch
    new_updates = {}
    errors = {}

    # 4. Iterate over ONLY the files that actually need processing
    for file_path in tqdm.tqdm(files_to_process):
        try:
            # Run the LLM extraction
            result = extract_function(file_path, model_name=model_name)

            # Save the result to our batch updates for end-of-batch tracking
            new_updates[file_path] = result

            # --- OPTIMIZED INSTANT SAVE ---
            # Update the in-memory history dictionary
            history[file_path] = result 

            # Dump directly to disk (skips the "read" step to save time)
            with open(file_name, "w") as f:
                json.dump(history, f, indent=4)

        except Exception as e:
            errors[file_path] = str(e)

    # 5. Final summary
    if new_updates:
        print(f"\nBatch complete. Successfully processed and saved {len(new_updates)} new entries to {file_name}.")
    else:
        print("\nBatch complete. No new files were successfully processed.")

    if errors:
        print("\nErrors encountered:")
        for path, error in errors.items():
            print(f"  - {path}: {error}")

process_batch(
    list_ah_raw_files[:],
    parse_ah_pdf_with_llm,
    "processed/ah_processed.json"
)

# ## Review AH

def get_df(file_name):
    return (
        pd.concat([
            (
                pd.Series(v.get("items")).pipe(pd.json_normalize)
                .assign(
                    file_path = k,
                    date_of_purchase = v.get("date_of_purchase")
                )
            )
            for k,v in load_processed_history_non_empty(file_name).items()
        ], ignore_index=True)
        .pipe(lambda df:
            df[ df.columns.tolist()[-2:] + df.columns.tolist()[:-2] ]
        )
    )

df_ah = get_df("processed/ah_processed.json")
df_ah.info()

df_ah.groupby("file_path")["line_total_paid_amount"].sum().reset_index()

pyperclip.copy(jjson(get_df("processed/ah_processed.json").to_dict("records")))

from tavily import TavilyClient

def get_supermarket_product_info(store: Literal["AH","JUMBO"], product_name: str, api_key: str = tavily_key):
    """
    Searches for a specific product's meaning/details at a chosen Dutch retailer.

    Args:
        store (str): 'AH' or 'JUMBO'
        product_name (str): The specific product name to look up.
        api_key (str): Your tavily_key variable.

    Returns:
        str: The AI-generated answer or combined context from the search.
    """
    client = TavilyClient(api_key=api_key)

    # Normalize store name for the query
    full_store_name = "Albert Heijn" if store.upper() == "AH" else store.capitalize()

    # Construct a specific query to get product descriptions/meanings
    search_query = f"{full_store_name} {product_name} product informatie betekenis omschrijving"

    try:
        response = client.search(
            query=search_query,
            search_depth="advanced",
            max_results=3,
            include_answer=True,
            # Focusing on Dutch results helps with accuracy for local supermarket chains
            search_context=True 
        )

        # Priority 1: Tavily's synthesized AI answer
        if response.get('answer'):
            return response['answer']

        # Priority 2: Snippets from the search results
        context = "\n".join([res['content'] for res in response.get('results', [])])
        return context if context else "No specific product information found."

    except Exception as e:
        return f"Tavily Search Error: {str(e)}"

# # Jumbo

import cv2
import pytesseract
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

def extract_text_from_image(image_path: str) -> str:
    """Preprocesses the receipt image and extracts text using Tesseract."""
    # 1. Load the image using OpenCV
    img = cv2.imread(image_path)

    # 2. Convert to grayscale to improve OCR accuracy
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Optional: Apply thresholding if your Jumbo screenshots are noisy/dark
    # _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    # 3. Extract text. 
    # PSM 6 assumes a single uniform block of text, which works well for receipt columns.
    custom_config = r'--oem 3 --psm 6'
    raw_text = pytesseract.image_to_string(gray, config=custom_config)

    return raw_text

class RawItemJumbo(BaseModel):
    item_name: str

    measurement_type: Literal[
        "discrete_units",
        "weight_in_grams"
    ]

    measurement_quantity: float
    line_total_paid_amount: float

class RawReceiptJumbo(BaseModel):
    date_of_purchase: str
    items: List[RawItemJumbo]

def parse_jumbo_image_with_llm(image_path: str, model_name: str = "mistral-small3.2:24b") -> RawReceipt:
    """Uses a local LLM to parse the OCR-extracted text into structured JSON."""

    # Extract the raw text via OCR
    receipt_text = extract_text_from_image(image_path)

    # Initialize the local text model 
    llm = ChatOllama(
        model="llama3.1:8b", 
        temperature=0.0, 
        format="json"
    )

    parser = PydanticOutputParser(pydantic_object=RawReceiptJumbo)

    prompt = f"""
You are a structured grocery receipt extraction system.

Extract grocery purchase rows and the purchase date from a Dutch Jumbo receipt into valid JSON.

{parser.get_format_instructions()}

Extraction Rules:

1. Keep item names EXACTLY as written on the receipt.
2. Do NOT translate, normalize, infer, or expand abbreviations.
3. Extract ONLY information explicitly visible on the receipt.
4. Do NOT calculate or derive values beyond the explicit extraction rules below.
5. Ignore:
   - store address/header metadata
   - loyalty/promotional program sections
   - subtotal/payment sections
   - terminal/payment metadata
   - VAT summaries
   - timestamps not related to purchase date

6. Extract the purchase date exactly as visible on the receipt.

7. Every grocery item MUST contain:
   - item_name
   - measurement_type
   - measurement_quantity
   - line_total_paid_amount

8. Determine measurement_type:
   - "discrete_units"
   - "weight_in_grams"

9. Quantity extraction rules:
   - Rows like:
       "2 X 1,89"
     mean:
       measurement_type="discrete_units"
       measurement_quantity=2

   - Single grocery products without explicit quantity mean:
       measurement_type="discrete_units"
       measurement_quantity=1

10. Weight normalization rules:
   - KG values must be converted into grams:
       0.532KG -> 532

   - gr values remain as grams:
       360gr -> 360

11. Price extraction rules:
   - line_total_paid_amount must always be the visible final item amount.

12. Ignore standalone discount or promotion rows such as:
   - ACTIE ...
   - KORTING ...

13. Every purchased grocery item must become exactly one JSON object.

14. Output ONLY valid JSON.

15. Do not output explanations, markdown, comments, or extra text.

Receipt Text:
{receipt_text}
"""

    return (
        llms["mistral-small3.2:24b"]
        .with_structured_output(RawReceiptJumbo)
        .invoke([
            HumanMessage(prompt)
        ])
        .model_dump()
    )

res = parse_jumbo_image_with_llm("raw_receipts/jumbo/IMG_4833.png", "mistral-small3.2:24b")
pd.DataFrame(res["items"])

# # Jumbo Batch

process_batch(
    list_jumbo_raw_files[:],
    parse_jumbo_image_with_llm,
    "processed/jumbo_processed.json"
)

# # Photo Receipts

processed_jumbo = load_processed_history("processed/jumbo_processed.json")

save_processed_history(processed_jumbo, "processed/jumbo_processed.json")

