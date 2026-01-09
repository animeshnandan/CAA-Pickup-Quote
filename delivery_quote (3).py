# app.py (fixes: remove empty load_xlsx; fix partner link f-string; tiny path check polish)

import os, re
from typing import List, Optional
import pandas as pd
import streamlit as st
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="CAA Pickup Quote", page_icon="🚚", layout="centered")

PARTNER_LINK = "https://your-partner-link.example.com"   # update if needed
DEFAULT_XLSX_PATH = APP_DIR / "Pickup zipcode CAA 3 locations.xlsx"

# Accept any sheet whose name contains these numbers (handles $125, "125", etc.)
EXPECTED_PRICES = {175, 200, 225, 250, 325, 525}
REQUIRED_COLUMNS = ["zipcode", "city", "state"]

def _sheet_to_price(sheet_name: str) -> Optional[int]:
    m = re.search(r"(\d+)", sheet_name.replace(",", ""))
    return int(m.group(1)) if m else None

def _cleanframe(df: pd.DataFrame, price: int) -> pd.DataFrame:
    cols_lower = {c.lower(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c not in cols_lower]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found columns: {list(df.columns)}")

    df2 = df.rename(columns={v: k for k, v in cols_lower.items()})
    out = df2.copy()

    out["zipcode"] = (
        out["zipcode"].astype(str).str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d+)", expand=False).fillna("").str.zfill(5)
    )
    out["city"]  = out["city"].astype(str).str.strip().str.upper()
    out["state"] = out["state"].astype(str).str.strip().str.upper()
    out["quote"] = int(price)

    return out[["zipcode", "city", "state", "quote"]]

@st.cache_data(show_spinner=False)
def load_pricing(xlsx_file) -> pd.DataFrame:
    xls = pd.ExcelFile(xlsx_file)
    frames: List[pd.DataFrame] = []
    for sheet in xls.sheet_names:
        price = _sheet_to_price(sheet)
        if price in EXPECTED_PRICES:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
            frames.append(_cleanframe(df, price))
    if not frames:
        return pd.DataFrame(columns=["zipcode", "city", "state", "quote"])

    full = (
        pd.concat(frames, ignore_index=True)
        .dropna(subset=["zipcode"])
        .query("zipcode != ''")
        .sort_values(["zipcode", "quote"], ascending=[True, True])
        .drop_duplicates(subset=["zipcode"], keep="first")
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return full

def lookup_by_zip(df: pd.DataFrame, zipcode: str) -> pd.DataFrame:
    z = str(zipcode).strip()
    if z.isdigit() and len(z) <= 5:
        z = z.zfill(5)
    return df.loc[df["zipcode"] == z]

def lookup_by_city_state(df: pd.DataFrame, city: str, state: str) -> pd.DataFrame:
    return df.loc[(df["city"] == city.strip().upper()) & (df["state"] == state.strip().upper())]

def format_city(city: str) -> str:
    return city.title()

# ------------------------- UI -------------------------
st.title("🚚 CAA Pickup Quote")

if not DEFAULT_XLSX_PATH.exists():
    st.error(f"Pricing file not found at:\n`{DEFAULT_XLSX_PATH}`\n\nPlease place the Excel file there or update the path in the code.")
    st.stop()

with st.spinner("Reading and indexing pricing..."):
    pricing = load_pricing(DEFAULT_XLSX_PATH)

if pricing.empty:
    st.error("No pricing found. Check sheet names ($125, $150, $175) and required columns (zipcode, city, state).")
    st.stop()

st.markdown("Select **ZIP code** or **City & State** below.")
all_states = sorted(pricing["state"].dropna().unique().tolist())

st.divider()
mode = st.radio("Search by:", ["ZIP code", "City & State"], horizontal=True)

if mode == "ZIP code":
    zip_exact = st.text_input(
        "ZIP",
        placeholder="Type 5 digits (e.g., 20855)",
        label_visibility="collapsed",
        max_chars=5,
    )
    zip_digits = re.sub(r"\D", "", zip_exact or "")
    if len(zip_digits) == 5:
        result_df = lookup_by_zip(pricing, zip_digits)
        if result_df.empty:
            st.error(f"No match for ZIP **{zip_digits}**. Refer to our partner: {PARTNER_LINK}")
        else:
            quote = int(result_df["quote"].iloc[0])
            st.success(f"✅ Quote for **{zip_digits}**: **${quote}**")
            st.dataframe(
                result_df[["zipcode", "city", "state", "quote"]]
                .rename(columns={"zipcode": "ZIP", "city": "City", "state": "State", "quote": "Quote ($)"}),
                use_container_width=True
            )
    else:
        st.info("Enter a full 5-digit ZIP to see the quote.")
else:
    col1, col2 = st.columns(2)
    with col1:
        sel_state = st.selectbox(
            "State",
            options=all_states,
            index=None,
            placeholder="Search state…",
            label_visibility="collapsed",
        )
    with col2:
        if sel_state:
            cities_for_state = (
                pricing.loc[pricing["state"] == sel_state, "city"]
                .dropna()
                .unique()
            )
            city_options = sorted([format_city(c) for c in cities_for_state])
        else:
            city_options = []
        sel_city = st.selectbox(
            "City",
            options=city_options,
            index=None,
            placeholder="Search city…",
            label_visibility="collapsed",
        )

    if sel_state and sel_city:
        result_df = lookup_by_city_state(pricing, sel_city, sel_state)
        desc = f"{sel_city}, {sel_state}"

        if result_df.empty:
            st.error(f"No match for **{desc}**. Refer to our partner: {PARTNER_LINK}")
        else:
            min_q, max_q = int(result_df["quote"].min()), int(result_df["quote"].max())
            if min_q == max_q:
                st.success(f"✅ Quote for **{desc}**: **${min_q}**")
            else:
                st.info(f"ℹ️ Multiple matches for **{desc}**. Quote range: **${min_q}–${max_q}**")

            st.dataframe(
                result_df[["zipcode", "quote"]]
                .rename(columns={"zipcode": "ZIP", "quote": "Quote ($)"}),
                use_container_width=True
            )
    else:
        st.info(f"Select a state and city to see quotes, or **[refer to our partner]({PARTNER_LINK})** if you don’t see your area.")

st.divider()
st.markdown(f"Can’t find a location? **[Refer to our partner here]({PARTNER_LINK})**.")
