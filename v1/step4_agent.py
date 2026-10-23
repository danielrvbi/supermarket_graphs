#!/usr/bin/env python
# coding: utf-8

# In[18]:


import pandas as pd
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from langchain_ollama import ChatOllama
from IPython.display import Markdown


# In[19]:


# 1. Point to your local Gemma 4 model via Ollama
llm = ChatOllama(
    model="gemma4:latest",
    temperature=0,
    keep_alive=-1,
    num_ctx=32768  # Give it a larger context window to ingest df info safely
)

llm.invoke("Hello")


# In[21]:


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


# In[27]:


res = agent.invoke("""
Create a table of monthly spending by supermarket,
pivot it to have each supermarket on each column, then do a total also, so 3 columns in total

What trends do you see?
""")


# In[28]:


Markdown(res["output"])


# In[29]:


res = agent.invoke("""
What are the products we buy the most?
""")


# In[30]:


Markdown(res["output"])


# In[31]:


res = agent.invoke("""
Track the inflation (price per unit) of the most bought products
""")


# In[32]:


Markdown(res["output"])

df.to_excel("final_data.xlsx")
# In[37]:


df["FINAL_CATEGORY"]


# In[ ]:




