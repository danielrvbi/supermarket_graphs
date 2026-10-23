#!/usr/bin/env python
# coding: utf-8

# In[102]:


from pydantic import BaseModel, Field
from typing import Literal, List
import datetime as dt
from datetime import date
import pandas as pd, numpy as np
import tqdm
import json, os
from dotenv import load_dotenv; load_dotenv()
jjson = lambda x: json.dumps(x, indent=4, ensure_ascii=False)
ppjson = lambda x: print(jjson(x))



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

tavily_key = os.environ.get("TAVILY_KEY",""); bool(tavily_key)


# In[12]:


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


# # AH

# In[177]:


df_ah = (
    get_df("processed/ah_processed.json")
    .assign(
        item_name = lambda df: df["item_name"].str.strip().str.upper(),
        date_of_purchase = lambda df: df["file_path"].str.extract(r"(\d{4}-\d{2}-\d{2})").astype("datetime64[ns]"),
        month_of_purchase = lambda df: df["date_of_purchase"].dt.strftime("%Y-%m-01").astype("datetime64[ns]"),
        measurement_quantity = lambda df: np.where(
            df["measurement_type"].eq("weight_in_grams"),
            df["measurement_quantity"].div(1000),
            df["measurement_quantity"]
        ),
        supermarket = "albert_heijn"
    )
)
df_ah.info()


# In[178]:


(
    df_ah
    .loc[
        #df_ah["measurement_quantity"].mul(df_ah["price_per_measurement_unit"]).sub(df_ah["line_total_paid_amount"]).apply(abs).gt(.05)
        df_ah["price_per_measurement_unit"].eq(df_ah["line_total_paid_amount"])
        &
        df_ah["measurement_quantity"].ne(1)
        ,
        "line_total_paid_amount"
    ]

) = (
    df_ah
    .loc[
        #df_ah["measurement_quantity"].mul(df_ah["price_per_measurement_unit"]).sub(df_ah["line_total_paid_amount"]).apply(abs).gt(.05)
        df_ah["price_per_measurement_unit"].eq(df_ah["line_total_paid_amount"])
        &
        df_ah["measurement_quantity"].ne(1)
    ]
    .pipe(lambda df: df["measurement_quantity"].mul(df["price_per_measurement_unit"]))
)

(
    df_ah
    .loc[
        df_ah["measurement_quantity"].mul(df_ah["price_per_measurement_unit"]).sub(df_ah["line_total_paid_amount"]).apply(abs).gt(.05)
    ,"measurement_quantity"
    ]
) = (
    df_ah
    .loc[
        df_ah["measurement_quantity"].mul(df_ah["price_per_measurement_unit"]).sub(df_ah["line_total_paid_amount"]).apply(abs).gt(.05)
    ]
    .pipe(lambda df: df["line_total_paid_amount"].div(df["price_per_measurement_unit"]))
)


# # JUMBO

# In[179]:


import pandas as pd
import re

def parse_dutch_dates(dates):
    """
    Parses a list or pandas Series of Dutch date strings into pandas datetime objects.
    Ignores preceding weekdays and handles mixed capitalization.
    """
    # Convert list to pandas Series if necessary
    if not isinstance(dates, pd.Series):
        s = pd.Series(dates)
    else:
        s = dates.copy()

    # Dictionary mapping Dutch month names to numeric strings
    month_map = {
        'januari': '01', 'februari': '02', 'maart': '03',
        'april': '04', 'mei': '05', 'juni': '06',
        'juli': '07', 'augustus': '08', 'september': '09',
        'oktober': '10', 'november': '11', 'december': '12'
    }

    # Lowercase everything to ensure consistent matching
    s = s.str.lower()

    # Extract the day, month name, and year using Regex
    # This automatically ignores any weekday strings (or typos) at the start
    extracted = s.str.extract(r'(?P<day>\d{1,2})\s+(?P<month_name>[a-z]+)\s+(?P<year>\d{4})')

    # Map the Dutch month name to a standard month number
    extracted['month'] = extracted['month_name'].map(month_map)

    # Pad single-digit days with a leading zero (e.g., '6' -> '06')
    extracted['day'] = extracted['day'].str.zfill(2)

    # Reconstruct into a standard ISO format string (YYYY-MM-DD)
    standardized_dates = extracted['year'] + '-' + extracted['month'] + '-' + extracted['day']

    # Convert to pandas datetime objects
    return pd.to_datetime(standardized_dates)


# In[185]:


df_jumbo = (
    get_df("processed/jumbo_processed.json")
    .assign(
        item_name = lambda df: df["item_name"].str.strip().str.upper(),
        measurement_quantity = lambda df: np.where(
            df["measurement_type"].eq("weight_in_grams"),
            df["measurement_quantity"].div(1000),
            df["measurement_quantity"]
        ),
        price_per_measurement_unit = lambda df: df["line_total_paid_amount"].div(df["measurement_quantity"]),
        date_of_purchase = lambda df: df["date_of_purchase"].apply(parse_dutch_dates),
        month_of_purchase = lambda df: df["date_of_purchase"].dt.strftime("%Y-%m-01").astype("datetime64[ns]"),
        supermarket = "jumbo"
    )
)
df_jumbo.info()

#df_jumbo.groupby("file_path")["line_total_paid_amount"].sum().describe()

df_jumbo.sample(10)


# # Join

# In[283]:


df_spmkt = (
    pd.concat([df_ah, df_jumbo],ignore_index=True)
    .loc[lambda df: ~df["item_name"].str.contains("STATI")]
    .assign(
        **{c: lambda df,c=c: df[c].apply(round,ndigits=3)
          for c in ["price_per_measurement_unit","line_total_paid_amount","measurement_quantity"]}
    )
)

df_spmkt.info()


# In[291]:


def _clean_single_row(row: pd.Series) -> pd.Series:
    """
    Applies specific edge case logic to a single receipt row.
    Leaves the row AS-IS if no specific logic matches.
    """
    raw_name = str(row.get('item_name', '')).upper()
    paid_amount = float(row.get('line_total_paid_amount', 0.0))

    # Edge Case 1 & 2: Scharrelei (Eggs)
    if 'SCHARREL' in raw_name:
        qty_match = re.search(r'(\d+)', raw_name)

        if qty_match:
            # Case 1: Quantity is explicitly in the string
            row['measurement_quantity'] = float(qty_match.group(1))

        elif 5.5 <= paid_amount <= 7.49:
            # Case 2: No quantity in string, but price implies a 20-pack (6.99 ± 0.50)
            row['measurement_quantity'] = 20.0

        elif 2 <= paid_amount <= 3:
            # Case 3: No quantity in string, but price implies a 6-pack (2.49 ± 0.50)
            row['measurement_quantity'] = 6

        # Standardize the product name regardless of which case triggered
        row['item_name'] = 'SCHARRELEI'
        row["price_per_measurement_unit"] = round(paid_amount / row['measurement_quantity'],2)
        return row


    if raw_name not in ["DUVEL 666",'4 FORMAG',"ML","MACH3","HEMA","GR","CL","48+"] and re.findall(r"\d+",raw_name):

        # Ensure paid_amount is treated as a float, defaulting to 0.0 if missing


        # -----------------------------------------
        # Edge Case 3: Mathematical Bundles (e.g., "10+2", "12X330")
        # -----------------------------------------
        match_plus = re.search(r'(\d+)\s*\+\s*(\d+)', raw_name)
        if match_plus:
            row['measurement_quantity'] = float(match_plus.group(1)) + float(match_plus.group(2))
            row['item_name'] = raw_name[:match_plus.start()].strip()
            return row

        match_x = re.search(r'(\d+)\s*X\s*\d+', raw_name)
        if match_x:
            row['measurement_quantity'] = float(match_x.group(1))
            row['item_name'] = raw_name[:match_x.start()].strip()
            return row

        # -----------------------------------------
        # Edge Case 4: Pack Identifiers (ST, FL, BL, P, PK, ROL, RL, SC)
        # -----------------------------------------
        # Captures formats like "6BL", "12P", "8ST", "12ROL"
        match_unit = re.search(r'(\d+)\s*(ST|FL|BL|P|PK|ROL|RL|SC)(?:\b|\s|$)', raw_name)
        if match_unit:
            row['measurement_quantity'] = float(match_unit.group(1))

            # Clean the extracted unit from the item name
            cleaned_name = raw_name.replace(match_unit.group(0), '').strip()

            # Sub-cleaning for paper products: Remove layer counts (e.g., "4LGS", "3 LGS", "2LG")
            cleaned_name = re.sub(r'\d+\s*LGS?', '', cleaned_name).strip()

            # Sub-cleaning: Remove trailing 'P' artifacts left behind (e.g., from "6PK P")
            if cleaned_name.endswith(' P'):
                cleaned_name = cleaned_name[:-2].strip()

            row['item_name'] = cleaned_name
            return row

        # -----------------------------------------
        # Edge Case 5: Trailing Prices & OCR Artifacts
        # -----------------------------------------
        # Cleans appended prices like "HAM DUO P 3,75" or OCR artifacts like "COCA COLA 1,5]"
        match_trailing_num = re.search(r'\s+(\d+[,.]\d{1,2})\]?$', raw_name)
        if match_trailing_num:
            row['item_name'] = raw_name[:match_trailing_num.start()].strip()
            return row


    # Default: Return AS-IS
    return row

def clean_receipt_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main cleaning function to be used with df.pipe().
    Usage: final_df = raw_df.pipe(clean_receipt_data)
    """
    # Create a copy to prevent SettingWithCopy warnings
    df_cleaned = df.copy()

    # Apply row-level transformations across the columns
    if 'item_name' in df_cleaned.columns:
        df_cleaned = df_cleaned.apply(_clean_single_row, axis=1)

    return df_cleaned


# In[292]:


df_spmkt_clean = (
    df_spmkt
    .pipe(clean_receipt_data)
    .assign(
        price_per_measurement_unit = lambda df: df["line_total_paid_amount"].div(df["measurement_quantity"]),
    )
)


# In[299]:


df_spmkt_clean.to_json("processed/joined_clean_processed.json",orient="records",date_format="iso")


# In[ ]:





# In[ ]:





# In[ ]:




