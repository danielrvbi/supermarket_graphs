#!/usr/bin/env python
# coding: utf-8

import pandas as pd
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from langchain_ollama import ChatOllama
from IPython.display import Markdown

# 1. Point to your local Gemma 4 model via Ollama
llm = ChatOllama(
    model="gemma4:latest",
    temperature=0,
    keep_alive=-1,
    num_ctx=32768  # Give it a larger context window to ingest df info safely
)

llm.invoke("Hello")

# 2. Load your data
df = pd.read_pickle("final_data.pickle")

# 3. Initialize the agent using standard tool-calling
agent = create_pandas_dataframe_agent(
    llm,
    df,
    agent_type="tool-calling",
    allow_dangerous_code=True,
    verbose=True
)

# Test it out
# agent.invoke({"input": "What is the average value in the total expenditure column?"})

res = agent.invoke("""
Create a table of monthly spending by supermarket,
pivot it to have each supermarket on each column, then do a total also, so 3 columns in total

What trends do you see?
""")

Markdown(res["output"])

res = agent.invoke("""
What are the products we buy the most?
""")

Markdown(res["output"])

res = agent.invoke("""
Track the inflation (price per unit) of the most bought products
""")

Markdown(res["output"])

df.to_excel("final_data.xlsx")

df["FINAL_CATEGORY"]

