#!/usr/bin/env python
# coding: utf-8

from pydantic import BaseModel, Field
from typing import Literal, List
import datetime as dt
from datetime import date
import pandas as pd, numpy as np
import tqdm
tqdm.tqdm.pandas()
import json, os
from dotenv import load_dotenv; load_dotenv()
from typing import Dict
import pyperclip
jjson = lambda x: json.dumps(x, indent=4, ensure_ascii=False)
ppjson = lambda x: print(jjson(x))

dsc = Dsc = {"ascending":False}
index_merge = {"left_index":True, 'right_index': True}

dict_names: Dict[str, Dict[str, str]] = (
    pd.read_csv("da budget - ElSuper-2.csv")
    .dropna(subset=["Product"])
    .map(lambda x: str(x).strip().upper())
    [["Product", "Producto", "Category", "Subcategory"]]
    .drop_duplicates(subset=["Product"], keep="last")
    .set_index("Product")
    .to_dict(orient="index")
)

pd.Series(dict_names).head(10)

dict_names["AH AARDAPPEL"]

df_asis = (
    pd.read_json("processed/joined_clean_processed.json")
    .assign(
        **{c: lambda df,c=c: df[c].astype("datetime64[ns]")
          for c in ["date_of_purchase", "month_of_purchase"]}
    )
)

df_asis.info()

item_names_original = df_asis["item_name"].unique()
len(item_names_original)

# # Tier 2. Embedding Match

df_asis.head()

df_match2 = (
    df_asis.loc[
        ~df_asis["item_name"].isin(dict_names.keys())   
    ]
    .drop_duplicates(subset=["item_name"])
    [["item_name","supermarket"]]
)

item_names_match2 = df_match2["item_name"].unique().tolist()
len(item_names_match2)

import os
from transformers import AutoModel, AutoTokenizer

def download_and_verify_model(model_name: str = "BAAI/bge-m3"):
    print(f"Checking/Downloading {model_name}...")
    
    # This downloads the tokenizer and model files to your default HF cache (~/.cache/huggingface/)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    
    # Find where HuggingFace stored it locally
    # It usually creates a directory structure matching the hub name
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub/")
    expected_path = os.path.join(cache_dir, f"models--{model_name.replace('/', '--')}")
    
    if os.path.exists(expected_path):
        print(f"\n[SUCCESS] Model is fully cached locally at:")
        print(f"👉 {expected_path}")
    else:
        print("\n[WARNING] Model was loaded, but the expected cache directory wasn't found.")

download_and_verify_model()

import logging
import tqdm
import re
from typing import List, Dict, Any
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# 1. Base config for YOUR logs
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 2. SILENCE NOISY THIRD-PARTY LOGGERS
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("filelock").setLevel(logging.WARNING)

def tier_2_semantic_search(
    item_names_original: List[str],
    dict_names: Dict[str, Dict[str, str]]
) -> Dict[str, Dict[str, Any]]:
    """
    Performs semantic search to match unknown receipt items.
    If the initial score is < 0.50, strips 'AH ' or 'JUMBO ' from the name
    and retries the search, keeping the highest resulting score.
    """
    logger.info("Starting Tier 2 Semantic Search...")

    # Ensure we are only processing strictly unique items
    unmatched_items = list(set(item_names_original) - set(dict_names.keys()))

    if not unmatched_items:
        logger.info("No unmatched items to process.")
        return {}

    logger.info(f"Processing {len(unmatched_items)} unique unmatched items...")

    # Initialize embeddings optimized for Apple Silicon (MPS)
    model_kwargs = {'device': 'mps'}
    encode_kwargs = {'normalize_embeddings': True}

    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs=model_kwargs,
        encode_kwargs=encode_kwargs
    )

    # Create FAISS vector store from known dictionary keys
    known_products_list = list(dict_names.keys())
    metadatas = [dict_names[prod] for prod in known_products_list]

    logger.info("Building FAISS index...")
    vectorstore = FAISS.from_texts(
        texts=known_products_list,
        embedding=embeddings,
        metadatas=metadatas
    )

    results_dict: Dict[str, Dict[str, Any]] = {}
    retry_count = 0
    improvement_count = 0

    # Query the vector store for each unmatched item
    for item in tqdm.tqdm(unmatched_items, desc="Semantic Matching", unit="item"):
        # --- Attempt 1: Full String ---
        results = vectorstore.similarity_search_with_relevance_scores(item, k=1)

        best_score = 0.0
        best_doc = None

        if results:
            best_doc, best_score = results[0]

        # --- Attempt 2: Fallback (Score < 0.50) ---
        if best_score < 0.50:
            # Regex removes 'AH ' or 'JUMBO ' only if they are at the very beginning of the string
            cleaned_item = re.sub(
                r'\s+',
                ' ',
                re.sub(r'\b(?:AH|ALBERT HEIJN|JUMBO)\b', '', item, flags=re.IGNORECASE)
            ).strip()

            # Only run inference again if the string was actually modified
            if cleaned_item != item and cleaned_item:
                retry_count += 1
                retry_results = vectorstore.similarity_search_with_relevance_scores(cleaned_item, k=1)

                if retry_results:
                    retry_doc, retry_score = retry_results[0]

                    # Overwrite if the cleaned string yielded a better semantic match
                    if retry_score > best_score:
                        improvement_count += 1
                        best_score = retry_score
                        best_doc = retry_doc

        # --- Save Final Best Result ---
        if best_doc:
            results_dict[item] = {
                "max_score": float(best_score),
                "closest_object": {
                    "Producto": best_doc.metadata.get("Producto", ""),
                    "Category": best_doc.metadata.get("Category", ""),
                    "Subcategory": best_doc.metadata.get("Subcategory", "")
                }
            }
        else:
            results_dict[item] = {
                "max_score": 0.0,
                "closest_object": {}
            }

    logger.info(f"Tier 2 Complete. Triggered prefix-stripping on {retry_count} items, improving the score for {improvement_count} of them.")
    return results_dict

matches_tier2 = tier_2_semantic_search(
    item_names_original=item_names_match2,
    dict_names=dict_names
)

df_matches_tier2 = (
    pd.Series(matches_tier2)
    .pipe(pd.json_normalize, sep="___")
    .sort_values("max_score",**dsc)
)

df_matches_tier2.head()

# # Tavily Searches

import os
import json
from typing import Dict, Any
from tavily import TavilyClient

CACHE_FILE = "tavily_cache.json"

def search_product_context_tavily(record) -> Dict[str, Any]:
    """
    Queries Tavily to find context, descriptions, or categorization clues 
    for a specific Dutch grocery item. Caches results locally to save API costs.
    """
    tavily_key = os.environ.get("TAVILY_KEY", "")
    if not tavily_key:
        raise ValueError("TAVILY_KEY is missing. Please export it before running Tier 3.")

    item_name = record["item_name"]
    supermarket = record["supermarket"].upper().replace("_"," ")

    # Create the unique cache key requested
    cache_key = f"{supermarket}-{item_name}"

    # ---------------------------------------------------------
    # 1. CHECK CACHE FIRST
    # ---------------------------------------------------------
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                cache_data = json.load(f)
                if cache_key in cache_data:
                    return {
                        "item_name": item_name,
                        "supermarket": supermarket,
                        "tavily_output": cache_data[cache_key]
                    }
            except json.JSONDecodeError:
                # If the file exists but is empty/corrupted, ignore and proceed
                pass

    # ---------------------------------------------------------
    # 2. CALL API IF NOT CACHED
    # ---------------------------------------------------------
    client = TavilyClient(api_key=tavily_key)
    query = f"{supermarket} {item_name} productinformatie"

    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=3,
            include_answer=False
        )

        results = response.get("results", [])
        combined_context = "\n\n".join([
            f"Source: {res.get('url')}\nContent: {res.get('content')}" 
            for res in results
        ])

        output = {
            "query": query,
            "success": True,
            "combined_context": combined_context if combined_context else "No content snippets found.",
            "raw_results": results
        }

    except Exception as e:
        output = {
            "query": query,
            "success": False,
            "combined_context": f"Search failed due to an error: {str(e)}",
            "raw_results": []
        }

    # ---------------------------------------------------------
    # 3. WRITE RESULT TO CACHE FILE
    # ---------------------------------------------------------
    # Read the latest state of the file right before writing 
    # to ensure we don't overwrite other entries.
    current_cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                current_cache = json.load(f)
            except json.JSONDecodeError:
                pass

    current_cache[cache_key] = output

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        # indent=2 makes the JSON file human-readable so you can easily inspect it
        json.dump(current_cache, f, ensure_ascii=False, indent=2)

    return (supermarket, item_name, output)

df_matches_tier2_jsonl = pd.Series(df_match2.to_dict("records"))
df_matches_tier2_jsonl.head()

tavily_res = df_matches_tier2_jsonl.progress_apply(search_product_context_tavily)
tavily_res.head()

df_matches_tier3 = (
    tavily_res
    .pipe(pd.json_normalize, sep="___")
    [["item_name","supermarket","tavily_output___combined_context"]]
    .set_index("item_name")
)

df_matches_tier3.head()

# # LLM Marching

def create_llm_input(row):
    payload = {"item_name": row.name} | row.to_dict()

    if payload.get("max_score")<.70:
        payload = {k:(v if ('closest_object' not in k) and (k!="max_score") else None) for k,v in payload.items()}

    return payload

df_matches_for_llm = (
    pd.merge(
        df_matches_tier2,
        df_matches_tier3,
        **index_merge
    )
    .assign(
        llm_payload = lambda df: df.apply(create_llm_input, axis=1)
    )
)

df_matches_for_llm.info()

from typing import Literal, Dict, Any
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

# Define types dynamically or using Literal
FIXED_CATEGORIES = pd.read_csv("da budget - ElSuper-2.csv")["Category"].dropna().map(lambda x: str(x).strip().upper()).unique().tolist()

# Schema for Layer 1
class Layer1Output(BaseModel):
    category: Literal[*FIXED_CATEGORIES] = Field(description="The single most accurate category matching the item from FIXED_CATEGORIES.")

# Schema for Layer 2
class Layer2Output(BaseModel):
    product_es: str = Field(description="The translated or conceptualized generic name of the product in Spanish.")
    subcategory: str = Field(description="A granular subcategory classification in Spanish matching the nature of the product")

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

llms["mistral-small3.2:24b"].invoke("Hello")

df_matches_for_llm["llm_payload"].iloc[0]

import os
import json
from typing import Dict, Any

CATEGORY_CACHE_FILE = "llm_classify_category.json"

def classify_category(payload: Dict[str, Any], model_name: str = "mistral-small3.2:24b") -> str:
    item_name = payload["item_name"]

    # ---------------------------------------------------------
    # 1. CHECK CACHE FIRST
    # ---------------------------------------------------------
    if os.path.exists(CATEGORY_CACHE_FILE):
        with open(CATEGORY_CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                cache_data = json.load(f)
                if item_name in cache_data:
                    return cache_data[item_name]
            except json.JSONDecodeError:
                # If the file is empty or corrupted, proceed to inference
                pass

    # ---------------------------------------------------------
    # 2. RUN LOCAL LLM INFERENCE
    # ---------------------------------------------------------
    prompt = (
        "You are a strict data classification agent inside an ETL grocery pipeline.\n"
        "Your sole task is to assign the raw item to exactly ONE of these categories:\n"
        f"{FIXED_CATEGORIES}\n\n"
        "Base your decision on the raw product text, supermarket context, and web snippets. "
        "Do not invent categories outside the provided list."
    )

    try:
        # Assuming SystemMessage and HumanMessage are formatted with your prompt and payload context
        res = (
            llms[model_name]
            .with_structured_output(Layer1Output)
            .invoke([
                SystemMessage(prompt),
                HumanMessage(jjson(payload))
            ])
            .model_dump()
            ["category"]
        )

        # ---------------------------------------------------------
        # 3. WRITE RESULT TO CACHE FILE (ONLY IF SUCCESSFUL)
        # ---------------------------------------------------------
        current_cache = {}
        if os.path.exists(CATEGORY_CACHE_FILE):
            with open(CATEGORY_CACHE_FILE, "r", encoding="utf-8") as f:
                try:
                    current_cache = json.load(f)
                except json.JSONDecodeError:
                    pass

        current_cache[item_name] = res

        with open(CATEGORY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_cache, f, ensure_ascii=False, indent=4)

        return res

    except Exception as e:
        # If an error happens, we don't cache anything and fall back gracefully
        return None 

df_matches_for_llm["FINAL_CATEGORY"] = df_matches_for_llm["llm_payload"].progress_apply(classify_category)

import os
import json
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field

SUBCATEGORY_CACHE_FILE = "llm_classify_subcategory.json"

def classify_subcategory(payload: Dict[str, Any], category: str, model_name: str = "mistral-small3.2:24b") -> Dict[str, str]:
    item_name = payload["item_name"]

    # ---------------------------------------------------------
    # 1. CHECK CACHE FIRST
    # ---------------------------------------------------------
    if os.path.exists(SUBCATEGORY_CACHE_FILE):
        with open(SUBCATEGORY_CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                cache_data = json.load(f)
                if item_name in cache_data:
                    return cache_data[item_name]
            except json.JSONDecodeError:
                pass

    # ---------------------------------------------------------
    # 2. DEFINE DYNAMIC SCHEMA (Using Literal Unpacking)
    # ---------------------------------------------------------
    # Fetch the allowed subcategories based on the Layer 1 result
    allowed_subs = category_sub_mapping.get(category, ["GENERAL"])

    class Layer2Output(BaseModel):
        product_es: str = Field(..., description="The generic translated name of the product in Spanish.")
        subcategory: Literal[*allowed_subs] = Field(..., description=f"Must strictly match one of these: {allowed_subs}")

    # ---------------------------------------------------------
    # 3. RUN LOCAL LLM INFERENCE
    # ---------------------------------------------------------
    prompt = (
        "You are an expert grocery taxonomy translation agent.\n"
        f"The item has already been verified to belong to the category: '{category}'.\n"
        "Your job is to:\n"
        "1. Translate/Conceptualize the raw item into a clean, concise Spanish product name ('product_es').\n"
        f"2. Select the most accurate 'subcategory' strictly from this list: {allowed_subs}.\n"
    )

    try:
        res = (
            llms[model_name]
            .with_structured_output(Layer2Output)
            .invoke([
                SystemMessage(prompt),
                HumanMessage(jjson(payload))
            ])
            .model_dump()
        )

        # ---------------------------------------------------------
        # 4. WRITE RESULT TO CACHE FILE (ONLY IF SUCCESSFUL)
        # ---------------------------------------------------------
        current_cache = {}
        if os.path.exists(SUBCATEGORY_CACHE_FILE):
            with open(SUBCATEGORY_CACHE_FILE, "r", encoding="utf-8") as f:
                try:
                    current_cache = json.load(f)
                except json.JSONDecodeError:
                    pass

        current_cache[item_name] = res

        with open(SUBCATEGORY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_cache, f, ensure_ascii=False, indent=4)

        return res

    except Exception as e:
        # If an error happens (e.g., model hallucinates outside the Literal), return None to flag it
        return None

import pandas as pd

category_sub_mapping = (
    pd.read_csv("da budget - ElSuper-2.csv")
    .dropna(subset=["Product"])
    .map(lambda x: str(x).strip().upper())
    [["Category", "Subcategory"]]
    .drop_duplicates(subset=["Subcategory"], keep="last")
    .groupby("Category")["Subcategory"].agg(list)
    .to_dict()
)

# 1. Create a quick wrapper function for the row
def apply_layer_2(row):
    # Pass the payload and the category we just created in Layer 1
    result = classify_subcategory(row["llm_payload"], row["FINAL_CATEGORY"])

    # If the LLM crashed and returned None, return empty fields to prevent errors
    if not result:
        return pd.Series({"product_es": None, "subcategory": None})

    # Wrapping the dictionary in pd.Series forces pandas to expand it into columns
    return pd.Series(result)

# 2. Run progress_apply across the rows (axis=1)
print("Running Layer 2: Spanish Translation & Subcategory...")
new_columns_df = df_matches_for_llm.progress_apply(apply_layer_2, axis=1)

# 3. Assign the newly created columns back to your main DataFrame
df_matches_for_llm[["FINAL_PRODUCTO_ES", "FINAL_SUBCATEGORY"]] = new_columns_df[["product_es", "subcategory"]].map(lambda x: str(x).upper().strip())

df_matches_for_llm["FINAL_SUBCATEGORY"].value_counts()

# # Final Join

df_item_final = (
    pd.concat([
        df_matches_for_llm.iloc[:,-3:].reset_index(names="item_name"),
        (
            pd.read_csv("da budget - ElSuper-2.csv")
            .dropna(subset=["Product"])
            .map(lambda x: str(x).strip().upper())
            [["Product", "Producto", "Category", "Subcategory"]]
            .drop_duplicates(subset=["Product"], keep="last")
            .set_axis(['item_name', 'FINAL_PRODUCTO_ES', 'FINAL_CATEGORY','FINAL_SUBCATEGORY'], axis=1)
        )
    ],ignore_index=True)
)

df_item_final.info()

# 1. Define the mapping of current columns to new names
rename_dict = {
    "month_of_purchase": "Month",
    "date_of_purchase": "Date",
    "FINAL_CATEGORY": "Category",
    "FINAL_PRODUCTO_ES": "Product ES",
    "FINAL_SUBCATEGORY": "Subcategory",
    # Note: 'Product NL' does not have an obvious match in your current columns.
    # I have mapped 'item_name' here, but adjust if needed!
    "item_name": "Product NL",
    "measurement_type": "Meas.",
    "measurement_quantity": "Quantity",
    "price_per_measurement_unit": "PpQ",
    "line_total_paid_amount": "Paid",
    "supermarket": "Store",
}

# 2. Define the exact order you requested
desired_order = [
    "Month",
    "Date",
    "Category",
    "Subcategory",
    "Product ES",
    "Product NL",
    "Meas.",
    "Quantity",
    "PpQ",
    "Paid",
    "Store",
]

df_final = (
    df_asis
    .merge(
        df_item_final,
        on = "item_name",
        how="left"
    )
    .rename(columns=rename_dict)
        [desired_order]
    .sort_values("Date")
    .assign(
        Week=lambda x: x["Date"].dt.isocalendar().year.astype(str)
        + "-W"
        + x["Date"].dt.isocalendar().week.map("{:02d}".format),
        Rank=lambda x: x.groupby("Product NL").cumcount() + 1,
    )[["Month", "Week"] + desired_order[1:] + ["Rank"]]
)

df_final.info()

df_final.to_pickle("final_data.pickle")

df_final.to_excel("final_data.xlsx",index=None)

