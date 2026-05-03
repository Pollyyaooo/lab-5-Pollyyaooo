"""
GIX equipment return log — Streamlit app for Maason Kao.
Logs returned assets to Supabase and exports BlueTally-compatible CSV.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

st.set_page_config(page_title="GIX Equipment Returns", layout="wide")

st.markdown(
    """
    <style>
    :root {
      font-size: 17px;
    }
    html,
    body {
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
        Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .stApp {
      font-family: inherit;
      font-size: 1.08rem;
      color: #1a1a1a;
    }
    .stApp h1 {
      font-size: clamp(2.1rem, 4vw, 2.6rem);
      font-weight: 700;
      letter-spacing: -0.02em;
      line-height: 1.2;
    }
    .stApp h2 {
      font-size: clamp(1.4rem, 2.6vw, 1.75rem);
      font-weight: 650;
      line-height: 1.3;
    }
    .stApp h3 {
      font-size: 1.25rem;
      font-weight: 600;
    }
    .stApp [data-testid="stCaptionContainer"] {
      font-size: 1rem;
      opacity: 0.9;
    }
    .stApp label,
    .stApp [data-baseweb="typo-label-small"],
    .stApp [data-baseweb="typo-label-medium"],
    .stApp [data-baseweb="typo-label-large"] {
      font-size: 1.02rem !important;
    }
    .stApp button,
    .stApp [data-baseweb="button"] {
      font-size: 1.04rem !important;
    }
    .stApp .stMetric label,
    .stApp .stMetric [data-testid="stMetricLabel"] {
      font-size: 1rem !important;
    }
    .stApp .stMetric [data-testid="stMetricValue"] {
      font-size: 2rem !important;
    }
    .stApp .stTextInput input,
    .stApp .stSelectbox [data-baseweb="select"],
    .stApp [data-baseweb="textarea"] textarea {
      font-size: 1.05rem !important;
    }
    .stApp [data-testid="stDataFrame"] {
      font-size: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("GIX — Equipment return log")
st.caption("Maason Kao · Quick log for returned equipment · BlueTally CSV export")

if "show_logged_success" not in st.session_state:
    st.session_state["show_logged_success"] = False


def get_supabase_client() -> Client | None:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error(
            "Missing Supabase configuration. Add SUPABASE_URL and SUPABASE_KEY to your .env file."
        )
        return None
    try:
        return create_client(url, key)
    except Exception:
        st.error("Could not connect to Supabase. Check your URL and key in .env.")
        return None


def fetch_assets(client: Client) -> tuple[list, bool]:
    try:
        response = client.table("assets").select("*").order("returned_at", desc=True).execute()
        data = response.data
        assert isinstance(data, list)
        return data, True
    except Exception:
        st.error(
            "Could not load assets from the database. Check your connection, credentials, and "
            "that the `assets` table exists."
        )
        return [], False


def insert_asset(
    client: Client,
    *,
    asset_tag: str,
    product_name: str,
    category: str,
    condition: str,
    notes: str | None,
) -> bool:
    payload: dict = {
        "asset_tag": asset_tag.strip(),
        "product_name": product_name.strip(),
        "category": category,
        "condition": condition,
        "returned_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes and notes.strip():
        payload["notes"] = notes.strip()

    try:
        client.table("assets").insert(payload).execute()
        return True
    except Exception:
        st.error("Could not save this asset. Please try again.")
        return False


def bluetally_csv_bytes(rows: list) -> bytes:
    export_df = pd.DataFrame(
        [{"asset_name": r["product_name"], "asset_tag": r["asset_tag"]} for r in rows],
        columns=["asset_name", "asset_tag"],
    )
    assert len(export_df.columns) == 2
    return export_df.to_csv(index=False).encode("utf-8")


OPENFOODFACTS_API = "https://world.openfoodfacts.org/api/v0/product/{upc}.json"
OPENFOODFACTS_USER_AGENT = "GIX-EquipmentReturn/1.0 (Streamlit; equipment log)"


def shorten_product_name_to_five_words(name: str) -> str:
    words = name.split()
    return " ".join(words[:5])


def fetch_openfoodfacts_product_name(upc: str) -> str | None:
    """Return full product name or None if not found. Raises on network/IO errors."""
    code = upc.strip()
    url = OPENFOODFACTS_API.format(upc=code)
    request = Request(
        url,
        headers={"User-Agent": OPENFOODFACTS_USER_AGENT},
    )
    with urlopen(request, timeout=20) as response:
        assert response.getcode() == 200
        payload = json.loads(response.read().decode("utf-8"))
        assert "status" in payload

    if payload.get("status") != 1:
        return None
    product = payload.get("product")
    if not isinstance(product, dict):
        return None
    raw = product.get("product_name")
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip()


supabase = get_supabase_client()

if st.session_state.pop("show_logged_success", False):
    st.success("Asset logged successfully.")

left_col, right_col = st.columns(2, gap="large")

with left_col:
    st.subheader("Add new asset")
    if supabase is None:
        st.info("Configure `.env` to use the form below.")
    else:
        upc_barcode = st.text_input(
            "UPC barcode",
            placeholder="e.g. 737628064502",
            key="form_upc_barcode",
        )
        if st.button("Look up product name"):
            with st.spinner("Looking up product..."):
                if not str(upc_barcode).strip():
                    st.error("Product not found")
                else:
                    try:
                        full_name = fetch_openfoodfacts_product_name(str(upc_barcode))
                    except Exception:
                        st.error("Lookup failed, please enter name manually")
                    else:
                        if full_name is None:
                            st.error("Product not found")
                        else:
                            st.session_state["form_product_name"] = shorten_product_name_to_five_words(
                                full_name
                            )
                            st.rerun()

        with st.form("add_asset_form", clear_on_submit=False):
            asset_tag = st.text_input("Asset tag", placeholder="e.g. GIX-00123", key="form_asset_tag")
            if st.session_state.get("form_err_asset_tag"):
                st.error("This field is required")
            product_name = st.text_input(
                "Product name", placeholder="e.g. Laptop Dell XPS 15", key="form_product_name"
            )
            if st.session_state.get("form_err_product_name"):
                st.error("This field is required")
            category = st.selectbox("Category", ["Makerspace", "IT", "Other"], key="form_category")
            condition = st.selectbox(
                "Condition", ["Good", "Damaged", "Unknown"], key="form_condition"
            )
            notes = st.text_input("Notes (optional)", placeholder="Optional details", key="form_notes")

            submitted = st.form_submit_button("Add asset")

        if submitted:
            tag_ok = bool(str(asset_tag).strip())
            name_ok = bool(str(product_name).strip())
            st.session_state["form_err_asset_tag"] = not tag_ok
            st.session_state["form_err_product_name"] = not name_ok
            if not tag_ok or not name_ok:
                st.rerun()
            st.session_state["form_err_asset_tag"] = False
            st.session_state["form_err_product_name"] = False

            if insert_asset(
                supabase,
                asset_tag=asset_tag,
                product_name=product_name,
                category=category,
                condition=condition,
                notes=notes,
            ):
                st.session_state["form_asset_tag"] = ""
                st.session_state["form_product_name"] = ""
                st.session_state["form_upc_barcode"] = ""
                st.session_state["form_notes"] = ""
                st.session_state["form_category"] = "Makerspace"
                st.session_state["form_condition"] = "Good"
                st.session_state["show_logged_success"] = True
                st.rerun()

assets: list = []
assets_ok = False
if supabase is not None:
    assets, assets_ok = fetch_assets(supabase)

with right_col:
    st.subheader("Current session log")
    if supabase is None:
        st.metric("Total assets", 0)
        st.dataframe(pd.DataFrame(), use_container_width=True, hide_index=True)
        _, dl_col = st.columns([3, 1])
        with dl_col:
            st.download_button(
                label="Download BlueTally CSV",
                data="asset_name,asset_tag\n",
                file_name="bluetally_assets.csv",
                mime="text/csv",
                disabled=True,
                use_container_width=True,
                help="Two columns: asset_name, asset_tag (matches BlueTally import).",
            )
    else:
        st.metric("Total assets", len(assets))
        if assets:
            st.dataframe(pd.DataFrame(assets), use_container_width=True, hide_index=True)
        else:
            st.dataframe(pd.DataFrame(), use_container_width=True, hide_index=True)
            if assets_ok:
                st.caption("No assets logged yet.")
        _, dl_col = st.columns([3, 1])
        with dl_col:
            st.download_button(
                label="Download BlueTally CSV",
                data=bluetally_csv_bytes(assets),
                file_name="bluetally_assets.csv",
                mime="text/csv",
                disabled=not assets_ok,
                use_container_width=True,
                help="Two columns: asset_name, asset_tag (matches BlueTally import).",
            )
