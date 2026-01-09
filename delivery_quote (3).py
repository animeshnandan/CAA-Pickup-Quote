# app.py
# Streamlit Delivery Quote Finder
# - ZIP search uses 🔍 Search button
# - City/State search uses 🔍 Search button (city updates immediately after state selection)
# - Search history shown (deduped: repeat searches update/move existing entry)
# - Fixes leading-zero ZIPs (e.g., 01002) that Excel may store as 1002

import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent

# -------------------------
# Config
# -------------------------
st.set_page_config(page_title="CAA Pickup Quote", page_icon="🚚", layout="centered")

PARTNER_LINK = "https://your-partner-link.example.com"  # update if needed
DEFAULT_XLSX_PATH = APP_DIR / "Pickup zipcode CAA 3 locations.xlsx"

EXPECTED_PRICES = {175, 200, 225, 250, 325, 525}
REQUIRED_COLUMNS = ["zipcode", "city", "state"]

STATE_NAME_TO_ABBR = {
    "NEW JERSEY": "NJ",
    "NEW HAMPSHIRE": "NH",
    "MASSACHUSETTS": "MA",
}

# -------------------------
# Helpers
# -------------------------
def _sheet_to_price(sheet_name: str) -> Optional[int]:
    m = re.search(r"(\d+)", (sheet_name or "").replace(",", ""))
    return int(m.group(1)) if m else None

def _normalize_zip(z: Any) -> str:
    """
    Return a 5-digit ZIP or '' if invalid.
    IMPORTANT: supports leading-zero ZIPs that Excel may convert to numbers.
      - 01002 stored as 1002 -> "01002"
      - 20855-1234 -> "20855"
      - 20855.0 -> "20855"
    """
    if z is None:
        return ""

    s = str(z).strip()
    s = re.sub(r"\.0$", "", s)  # handle "20855.0"

    digits = re.sub(r"\D", "", s)  # keep only digits
    if not digits:
        return ""

    # If Excel dropped a leading zero, we may get 1-4 digits; pad to 5.
    if len(digits) <= 5:
        return digits.zfill(5)

    # ZIP+4 or longer strings: take first 5 digits
    return digits[:5].zfill(5)

def _normalize_state(s: Any) -> str:
    if s is None:
        return ""
    t = str(s).strip().upper()
    if t in STATE_NAME_TO_ABBR:
        return STATE_NAME_TO_ABBR[t]
    letters = re.sub(r"[^A-Z]", "", t)
    return letters[:2] if len(letters) >= 2 else ""

def _cleanframe(df: pd.DataFrame, price: int) -> pd.DataFrame:
    cols_lower = {c.lower().strip(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if c not in cols_lower]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    df2 = df.rename(columns={cols_lower[k]: k for k in cols_lower})
    out = df2.copy()

    out["zipcode"] = out["zipcode"].apply(_normalize_zip)
    out["city"] = out["city"].astype(str).str.strip().str.upper()
    out["state"] = out["state"].apply(_normalize_state)
    out["quote"] = int(price)

    out = out[["zipcode", "city", "state", "quote"]]
    out = out.dropna(subset=["zipcode", "city", "state"])
    out = out[(out["zipcode"] != "") & (out["state"] != "") & (out["city"] != "")]
    return out

@st.cache_data(show_spinner=False)
def load_pricing(xlsx_file: str) -> pd.DataFrame:
    try:
        xls = pd.ExcelFile(xlsx_file, engine="openpyxl")
    except ImportError as e:
        raise ImportError(
            "Missing dependency: openpyxl.\n\n"
            "Fix:\n"
            "  - Local: pip install openpyxl\n"
            "  - Streamlit Cloud: add 'openpyxl' to requirements.txt\n"
        ) from e

    frames: List[pd.DataFrame] = []
    for sheet in xls.sheet_names:
        price = _sheet_to_price(sheet)
        if price in EXPECTED_PRICES:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str, engine="openpyxl")
            frames.append(_cleanframe(df, price))

    if not frames:
        return pd.DataFrame(columns=["zipcode", "city", "state", "quote"])

    full = pd.concat(frames, ignore_index=True)

    # Keep lowest quote per ZIP
    full = (
        full.sort_values(["zipcode", "quote"], ascending=[True, True])
        .drop_duplicates(subset=["zipcode"], keep="first")
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return full

def lookup_by_zip(df: pd.DataFrame, zipcode: Any) -> pd.DataFrame:
    z = _normalize_zip(zipcode)
    if not z:
        return df.iloc[0:0]
    return df.loc[df["zipcode"] == z]

def lookup_by_city_state(df: pd.DataFrame, city_title: str, state: str) -> pd.DataFrame:
    c = (city_title or "").strip().upper()
    s = _normalize_state(state)
    if not c or not s:
        return df.iloc[0:0]
    return df.loc[(df["city"] == c) & (df["state"] == s)]

def format_city(city_upper: str) -> str:
    return str(city_upper).title()

def upsert_history(history: List[Dict[str, Any]], key: Tuple[Any, ...], record: Dict[str, Any], max_len: int = 25):
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
    del history[max_len:]

# -------------------------
# Session State
# -------------------------
if "zip_history" not in st.session_state:
    st.session_state.zip_history = []
if "cs_history" not in st.session_state:
    st.session_state.cs_history = []

st.session_state.setdefault("cs_state", None)
st.session_state.setdefault("cs_city", None)

# -------------------------
# UI
# -------------------------
st.title("🚚 CAA Pickup Quote")

if not DEFAULT_XLSX_PATH.exists():
    st.error(f"Pricing file not found:\n`{DEFAULT_XLSX_PATH}`")
    st.stop()

try:
    pricing = load_pricing(str(DEFAULT_XLSX_PATH))
except Exception as e:
    st.error("Failed to load pricing Excel.")
    st.exception(e)
    st.stop()

if pricing.empty:
    st.error("No pricing found. Check Excel sheet names and columns (zipcode, city, state).")
    st.stop()

st.markdown("Search by **ZIP code** or **City & State**.")
st.divider()

mode = st.radio("Search by:", ["ZIP code", "City & State"], horizontal=True)

all_states = sorted(pricing["state"].dropna().unique().tolist())

# -------------------------
# ZIP code mode
# -------------------------
if mode == "ZIP code":
    zip_input = st.text_input(
        "ZIP",
        placeholder="Enter 5-digit ZIP",
        max_chars=10,  # allow ZIP+4 paste
        label_visibility="collapsed",
        key="zip_input",
    )
    submitted = st.button("🔍 Search", key="zip_search_btn")

    if submitted:
        norm_zip = _normalize_zip(zip_input)
        if not norm_zip:
            st.warning("Please enter a valid ZIP (up to 5 digits).")
        else:
            result = lookup_by_zip(pricing, norm_zip)
            if result.empty:
                st.error(f"No match for ZIP **{norm_zip}**")
                upsert_history(st.session_state.zip_history, key=(norm_zip,), record={"zip": norm_zip, "result": "No match"})
            else:
                quote = int(result["quote"].iloc[0])
                st.success(f"✅ Quote for **{norm_zip}**: **${quote}**")
                st.dataframe(
                    result.rename(columns={"zipcode": "ZIP", "city": "City", "state": "State", "quote": "Quote ($)"}),
                    use_container_width=True,
                )
                upsert_history(st.session_state.zip_history, key=(norm_zip,), record={"zip": norm_zip, "result": f"${quote}"})

    if st.session_state.zip_history:
        st.divider()
        st.subheader("Recent ZIP searches")
        for item in st.session_state.zip_history[:10]:
            st.write(f"{item['zip']} — {item['result']}")
        if st.button("Clear ZIP history"):
            st.session_state.zip_history = []
            st.rerun()

# -------------------------
# City & State mode
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

    if sel_state:
        cities_upper = (
            pricing.loc[pricing["state"] == sel_state, "city"]
            .dropna()
            .unique()
            .tolist()
        )
        cities_upper = sorted(cities_upper)
        city_options_title = [format_city(c) for c in cities_upper]
    else:
        city_options_title = []

    if st.session_state.get("cs_city") and st.session_state["cs_city"] not in city_options_title:
        st.session_state["cs_city"] = None

    with col2:
        sel_city_title = st.selectbox(
            "City",
            options=city_options_title,
            index=None,
            placeholder="Search city…",
            label_visibility="collapsed",
            key="cs_city",
        )

    submitted = st.button("🔍 Search", key="cs_search_btn")

    if submitted:
        if not sel_state or not sel_city_title:
            st.warning("Select both state and city.")
        else:
            result = lookup_by_city_state(pricing, sel_city_title, sel_state)
            desc = f"{sel_city_title}, {sel_state}"

            if result.empty:
                st.error(f"No match for **{desc}**")
                upsert_history(st.session_state.cs_history, key=(sel_state, sel_city_title), record={"desc": desc, "result": "No match"})
            else:
                min_q, max_q = int(result["quote"].min()), int(result["quote"].max())
                result_text = f"${min_q}" if min_q == max_q else f"${min_q}–${max_q}"

                st.success(f"✅ Quote for **{desc}**: **{result_text}**")
                st.dataframe(
                    result[["zipcode", "quote"]].rename(columns={"zipcode": "ZIP", "quote": "Quote ($)"}),
                    use_container_width=True,
                )
                upsert_history(st.session_state.cs_history, key=(sel_state, sel_city_title), record={"desc": desc, "result": result_text})

    if st.session_state.cs_history:
        st.divider()
        st.subheader("Recent City/State searches")
        for item in st.session_state.cs_history[:10]:
            st.write(f"{item['desc']} — {item['result']}")
        if st.button("Clear City/State history"):
            st.session_state.cs_history = []
            st.rerun()

st.divider()
st.markdown(f"Can’t find a location? **[Refer to our partner here]({PARTNER_LINK})**.")
