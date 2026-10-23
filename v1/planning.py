#!/usr/bin/env python
# coding: utf-8

# In[96]:


import pandas as pd
from typing import (
Literal,
List,
Tuple
)
import os, json, pyperclip
from pydantic import BaseModel
from datetime import date
from dotenv import load_dotenv; load_dotenv()


# In[ ]:





# In[39]:


tavily_key = os.environ.get("TAVILY_KEY",""); bool(tavily_key)


# In[40]:


class RawItem(BaseModel):
    product_name: str
    quantity_type: Literal["units","grams"]
    paid_amount: float
    quantity_price: float # price per g, OR price per unit

class RawReceipt(BaseModel): # This is applied per image
    date_of_purchase: date
    items: List[BaseItem]


FIXED_CATEGORIES = ['Frutas & Verduras', 'Lácteos', 'Carnes', 'Bebidas', 
                    'Panadería', 'Hogar', 'Pasta/Sopas', 'Snacks', 'Dulces', 'Higiene', 'Salud']

# After extraction, this is applied per product, per receipt. Because price can change between dates
class FinalItem(BaseModel):
    date_of_purchase: date
    product_name_raw: str # same as raw_base_model
    product_name_es: str 
    category: Literal[*FIXED_CATEGORIES]
    sub_category: str # No use of LITERAL, but still try to get the already classified data, to not invent new ones very time

    quantity_type: Literal["units","grams"]
    paid_amount: float
    quantity_price: float # price per g, OR price per unit




# In[29]:


df_names = (
    pd.read_csv("da budget - ElSuper-2.csv").dropna(subset=["Product"])
    .groupby(["Product","Producto","Category","Subcategory"]).size()
    .sort_values(ascending=False)

)

df_names.head(10)


# # Project Context: Dutch Grocery Receipt Pipeline
# 
# ## Overview
# We are building a robust ETL pipeline to parse, aggregate, and classify two years of grocery receipts from Albert Heijn and Jumbo. The goal is to transform unstructured files (images and PDFs) into structured data, classify products into Spanish categories, and maintain an expandable dataset. The architecture is specifically optimized for local AI execution on an Apple Silicon environment (M3 Max, 36GB RAM) to ensure complete financial data privacy and fast, local LLM inference. If results are not good, then as last resort we default to Ollama Cloud models.
# 
# ## Tech Stack & Tooling
# * **Orchestration & LLM Integration:** Python, LangChain, Ollama (running local models for parsing and classification tasks).
# * **Data Validation:** Pydantic (Strict schema enforcement for JSON/JSONL outputs).
# * **Extraction Tools:** `pdfplumber` and Regex for precise PDF text extraction; OCR (EasyOCR/Tesseract) or VLM for images.
# * **Data Manipulation:** Pandas (for flattening aggregations, joining tables, and managing the historical lookup tables).
# * **Embeddings (Classification):** Lightweight local vector store (e.g., Chroma/FAISS with `https://huggingface.co/BAAI/bge-m3`).
# 
# ## Data Sources
# 1.  **Jumbo Receipts:** Digital screenshots/images. Requires OCR or Vision models to handle multi-line text splits.
# 2.  **Albert Heijn Receipts:** PDF files. Text can be cleanly extracted via `pdfplumber`, bypassing OCR.
# 3.  **Historical Dictionary:** Existing dataset of ~719 classified products containing: `Product (Dutch)`, `Producto (Spanish)`, `Category`, `Subcategory`, and frequency count.
# 
# ## Architecture / Pipeline Steps
# 
# ### Step 1 & 2: Extraction Layer
# Parse receipts into a structured format (saved as JSONL per file).
# * **AH Parsing Logic:** Extract text with layout preservation, parse rows to identify quantities, descriptions, and prices, feed to local LLM for structured output
# * **Jumbo Parsing Logic:** Extract text blocks via OCR, feed to local LLM with structured output.
# * *Target Schema:*
#     ```python
#     from pydantic import BaseModel
#     from typing import Literal, List
#     from datetime import date
# 
#     class RawItem(BaseModel):
#         product_name: str
#         quantity_type: Literal["units","grams"]
#         paid_amount: float
#         quantity_price: float # price per g, OR price per unit
#         
#     class RawReceipt(BaseModel):
#         date_of_purchase: date
#         items: List[RawItem]
#     ```
# 
# ### Step 3: Aggregation Layer
# Load all JSONL files, map them to Pydantic objects, and flatten into a unified `raw_table` (Pandas DataFrame) for downstream processing.
# 
# ### Step 4: Classification Layer
# Map raw Dutch products to translated, categorized formats using a 3-Tier Matching Engine:
# 1.  **Tier 1 (Exact Match):** Fast dictionary lookup against the historical 719-item database.
# 2.  **Tier 2 (Semantic Search):** Vector similarity search for minor variations (e.g., abbreviations).
# 3.  **Tier 3 (Local LLM Fallback):** Pass unknown items to local LLM via Ollama to translate and assign to `FIXED_CATEGORIES`, then save back to the lookup table. Agent MUST use knowledge or TAVILY tool to confirm product info.
# 
# * *Target Schema:*
#     ```python
#     FIXED_CATEGORIES = ['Frutas & Verduras', 'Lácteos', 'Carnes', 'Bebidas', 
#                         'Panadería', 'Hogar', 'Pasta/Sopas', 'Snacks', 'Dulces', 'Higiene', 'Salud']
# 
#     class FinalItem(BaseModel):
#         date_of_purchase: date
#         product_name_raw: str
#         product_name_es: str 
#         category: Literal[*FIXED_CATEGORIES]
#         sub_category: str 
#         quantity_type: Literal["units","grams"]
#         paid_amount: float
#         quantity_price: float 
#     ```
# 
# ## Current State & Next Steps
# * *Status:* Planning phase completed. Target schemas and pipeline architecture defined.
# * *Next Action:* Implement the specific extraction scripts (either Jumbo Image parser or AH PDF parser) and test against sample files.

# In[73]:


category_sub_mapping = (
    pd.read_csv("da budget - ElSuper-2.csv")
    .dropna(subset=["Product"])
    .map(lambda x: str(x).strip().upper())
    [["Category", "Subcategory"]]
    .drop_duplicates(subset=["Subcategory"], keep="last")
    .groupby("Category")["Subcategory"].agg(list)
    .to_dict()
)


# In[76]:


category_sub_mapping.keys()


# In[75]:


category_sub_mapping["BEBIDAS"]


# In[92]:


with open("llm_classify_category.json", "r") as f:
    wiri = pd.Series(json.load(f))

print(wiri.shape)


# In[ ]:





# In[93]:


pd.Series(wiri).value_counts()


# In[100]:


pyperclip.copy(json.dumps(wiri.iloc[50:100].to_dict(), indent=4, ensure_ascii=False))


# In[ ]:





# In[ ]:





# In[ ]:




