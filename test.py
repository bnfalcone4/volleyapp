import pandas as pd
import streamlit as st

st.title('VolleyApp')

df = pd.DataFrame([{'A':1}])

st.write(df.to_string())