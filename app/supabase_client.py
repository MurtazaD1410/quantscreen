import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def _get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def get_supabase() -> Client:
    return _get_client()
