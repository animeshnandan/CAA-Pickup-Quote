# app.py
# Streamlit Delivery Quote Finder
# - ZIP search uses 🔍 Search button
# - City/State search uses 🔍 Search button (city updates immediately after state selection)
# - Search history shown (deduped: repeat searches update/move existing entry)
# - Clear history buttons only
#
# Run:
#   pip install streamlit pandas openpyxl
#   streamlit run app.py

import os
import re
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import streamlit as st

# -------------------------
# Config
# -------------------------
st.set_page_config(page_title="CAA Pickup Quote", page_icon="🚚", layout="centered")

PARTNER_LINK = "https://your-partner-link.example.com"   # update if needed
DEFAULT_XLSX_PATH = APP_DIR / "Pickup zipcode CAA 3 locations.xlsx"

EXPECTED_PRICES = {175, 200, 225, 250, 325, 525}
REQUIRED_COLUMNS = ["zipcode", "city", "state"]

# -------------------------
# Helpers
# -------------------------
def _sheet_to_price(sheet_name: str) -> Optional[int]:
    m = re.search(r"(\d+)", sheet_name.replace(",", ""))
    return int(m.group(1)) if m else None

def _cleanframe(df: pd.DataFrame, price: int) -> pd.DataFrame:
    cols_lower = {c.lower(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c not in cols_lower]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df2 = df.rename(columns={v: k for k, v in cols_lower.items()})
    out = df2.copy()

    out["zipcode"] = (
        out["zipcode"].astype(str).str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d+)", expand=False).fillna("").str.zfill(5)
    )
    out["city"] = out["city"].astype(str).str.strip().str.upper()
    out["state"] = out["state"].astype(str).str.strip().str.upper()
    out["quote"] = int(price)

    return out[["zipcode", "city", "state", "quote"]]

@st.cache_data(show_spinner=False)
def load_pricing(xlsx_file: str) -> pd.DataFrame:
    xls = pd.ExcelFile(xlsx_file)
    frames: List[pd.DataFrame] = []

    for sheet in xls.sheet_names:
        price = _sheet_to_price(sheet)
        if price in EXPECTED_PRICES:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
            frames.append(_cleanframe(df, price))

    if not frames:
        return pd.DataFrame(columns=["zipcode", "city", "state", "quote"])

    return (
        pd.concat(frames, ignore_index=True)
        .dropna(subset=["zipcode"])
        .query("zipcode != ''")
        .sort_values(["zipcode", "quote"], ascending=[True, True])
        .drop_duplicates(subset=["zipcode"], keep="first")
        .reset_index(drop=True)
    )

def lookup_by_zip(df: pd.DataFrame, zipcode: str) -> pd.DataFrame:
    return df.loc[df["zipcode"] == zipcode]

def lookup_by_city_state(df: pd.DataFrame, city: str, state: str) -> pd.DataFrame:
    # pricing stores upper-case
    return df.loc[(df["city"] == city.upper()) & (df["state"] == state.upper())]

def format_city(city: str) -> str:
    return city.title()

def upsert_history(history: List[Dict[str, Any]], key: Tuple[Any, ...], record: Dict[str, Any], max_len: int = 25):
    """
    Deduped history: if key already exists, remove old entry and insert updated record at top.
    """
    idx = None
    for i, item in enumerate(history):
        if item.get("_key") == key:
            idx = i
            break
    if idx is not None:
        history.pop(idx)

    record2 = dict(record)
    record2["_key"] = key
    history.insert(0, record2)

    del history[max_len:]  # truncate in-place

# -------------------------
# Session State
# -------------------------
if "zip_history" not in st.session_state:
    st.session_state.zip_history: List[Dict[str, Any]] = []

if "cs_history" not in st.session_state:
    st.session_state.cs_history: List[Dict[str, Any]] = []

# Keep current selectors in session_state so the City dropdown updates immediately
st.session_state.setdefault("cs_state", None)
st.session_state.setdefault("cs_city", None)

# -------------------------
# UI
# -------------------------
st.title("🚚 CAA Pickup Quote")

if not os.path.exists(DEFAULT_XLSX_PATH):
    st.error(f"Pricing file not found:\n`{DEFAULT_XLSX_PATH}`")
    st.stop()

pricing = load_pricing(DEFAULT_XLSX_PATH)

if pricing.empty:
    st.error("No pricing found. Check Excel sheet names and columns.")
    st.stop()

st.markdown("Search by **ZIP code** or **City & State**.")
st.divider()

mode = st.radio("Search by:", ["ZIP code", "City & State"], horizontal=True)

all_states = sorted(pricing["state"].dropna().unique())

# -------------------------
# ZIP code mode
# -------------------------
if mode == "ZIP code":
    zip_input = st.text_input(
        "ZIP",
        placeholder="Enter 5-digit ZIP",
        max_chars=5,
        label_visibility="collapsed",
        key="zip_input",
    )
    submitted = st.button("🔍 Search", key="zip_search_btn")

    zip_digits = re.sub(r"\D", "", zip_input or "")

    if submitted:
        if len(zip_digits) != 5:
            st.warning("Please enter a valid 5-digit ZIP.")
        else:
            result = lookup_by_zip(pricing, zip_digits)
            if result.empty:
                st.error(f"No match for ZIP **{zip_digits}**")
                upsert_history(
                    st.session_state.zip_history,
                    key=(zip_digits,),
                    record={"zip": zip_digits, "result": "No match"},
                )
            else:
                quote = int(result["quote"].iloc[0])
                st.success(f"✅ Quote for **{zip_digits}**: **${quote}**")
                st.dataframe(
                    result.rename(columns={
                        "zipcode": "ZIP", "city": "City", "state": "State", "quote": "Quote ($)"
                    }),
                    use_container_width=True
                )
                upsert_history(
                    st.session_state.zip_history,
                    key=(zip_digits,),
                    record={"zip": zip_digits, "result": f"${quote}"},
                )

    if st.session_state.zip_history:
        st.divider()
        st.subheader("Recent ZIP searches")
        for item in st.session_state.zip_history[:10]:
            st.write(f"{item['zip']} — {item['result']}")

        if st.button("Clear ZIP history"):
            st.session_state.zip_history = []
            st.rerun()

# -------------------------
# City & State mode (CITY UPDATES IMMEDIATELY AFTER STATE SELECTION)
# -------------------------
else:
    col1, col2 = st.columns(2)

    with col1:
        sel_state = st.selectbox(
            "State",
            options=all_states,
            index=None,
            placeholder="Search state…",
            label_visibility="collapsed",
            key="cs_state",
        )

    # Build city options based on selected state (this now updates immediately on change)
    if sel_state:
        cities_for_state_raw = (
            pricing.loc[pricing["state"] == sel_state, "city"]
            .dropna()
            .unique()
            .tolist()
        )
        city_options = sorted([format_city(c) for c in cities_for_state_raw])
    else:
        city_options = []

    # If state changed and previously selected city isn't in new list, clear city selection
    if st.session_state.get("cs_city") and st.session_state["cs_city"] not in city_options:
        st.session_state["cs_city"] = None

    with col2:
        sel_city = st.selectbox(
            "City",
            options=city_options,
            index=None,
            placeholder="Search city…",
            label_visibility="collapsed",
            key="cs_city",
        )

    submitted = st.button("🔍 Search", key="cs_search_btn")

    if submitted:
        if not sel_state or not sel_city:
            st.warning("Select both state and city.")
        else:
            result = lookup_by_city_state(pricing, sel_city, sel_state)
            desc = f"{sel_city}, {sel_state}"

            if result.empty:
                st.error(f"No match for **{desc}**")
                upsert_history(
                    st.session_state.cs_history,
                    key=(sel_state, sel_city),
                    record={"desc": desc, "result": "No match"},
                )
            else:
                min_q, max_q = int(result["quote"].min()), int(result["quote"].max())
                result_text = f"${min_q}" if min_q == max_q else f"${min_q}–${max_q}"

                st.success(f"✅ Quote for **{desc}**: **{result_text}**")
                st.dataframe(
                    result[["zipcode", "quote"]].rename(columns={"zipcode": "ZIP", "quote": "Quote ($)"}),
                    use_container_width=True
                )

                upsert_history(
                    st.session_state.cs_history,
                    key=(sel_state, sel_city),
                    record={"desc": desc, "result": result_text},
                )

    if st.session_state.cs_history:
        st.divider()
        st.subheader("Recent City/State searches")
        for item in st.session_state.cs_history[:10]:
            st.write(f"{item['desc']} — {item['result']}")

        if st.button("Clear City/State history"):
            st.session_state.cs_history = []
            st.rerun()
