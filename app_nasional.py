"""
TTS Penawaran Nasional
=======================
App khusus Asin untuk bikin penawaran pengiriman ke SELURUH INDONESIA.
Beda dengan topan.py (yang untuk penawaran reguler Jabodetabek), app ini
otomatis menghitung ongkos kirim berdasarkan kota/kecamatan tujuan, berat
barang, dan tarif REGPACK (<10kg) / BIGPACK (>=10kg).

Sumber data:
- database_barang.csv       -> Nama Barang; Satuan; Harga; Berat (gram)
- Google Sheet "Antrean Penawaran TTS", tab "REGPACK" & "BIGPACK" -> tarif ongkir
- Penawaran yang terkirim disimpan di tab "Antrean_Nasional_Asin" (sheet yang sama)

Aturan bisnis (sudah dikonfirmasi):
- 1 penawaran = 1 kota/kecamatan tujuan untuk semua barang di keranjang
- Ongkir dihitung dari TOTAL berat semua barang di keranjang (bukan per barang)
- Ongkir kena PPN 11% juga (masuk subtotal sebelum PPN dihitung)
- Barang yang beratnya belum diisi di database TIDAK BISA dimasukkan ke keranjang
- Minimum ongkir dihitung 1kg, dibulatkan ke atas
"""

import os
import io
import math
import time
import hashlib
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from fpdf import FPDF
from rapidfuzz import process, fuzz, utils

# =========================================================
# KONFIGURASI
# =========================================================
COMPANY_NAME = "PT. THEA THEO STATIONARY"
SLOGAN = "Office & School Supplies Solution"
ADDR = "Komp. Ruko Modernland Cipondoh Blok. AR No. 27, Tangerang"
OFFICE_PHONE = "(021) 55780659"

MARKETING_NAME = "Asin"
MARKETING_TITLE = "Koordinator Sales & Marketing"
MARKETING_WA = "0815-8199-775"
MARKETING_EMAIL = "alattulis.tts@gmail.com"

SPREADSHEET_NAME = "Antrean Penawaran TTS"
SHEET_TAB = "Antrean_Nasional_Asin"
SHEET_HEADERS = ["Waktu", "Customer", "UP", "WA", "Kota Tujuan",
                 "Kategori Ongkir", "Berat Total (gram)", "Ongkir",
                 "Pesanan", "Status"]

BIGPACK_THRESHOLD_KG = 10
MIN_BILLABLE_KG = 1
PPN_RATE = 0.11

COLOR_NAVY = (0, 40, 85)
COLOR_GOLD = (184, 134, 11)
COLOR_TEXT = (30, 30, 30)

st.set_page_config(page_title=f"{COMPANY_NAME} — Nasional", layout="wide",
                    page_icon="🚚", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=Playfair+Display:wght@700&display=swap');
html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; -webkit-tap-highlight-color: transparent; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
.stApp { background: linear-gradient(135deg, #f0f4f8 0%, #e8edf5 50%, #f5f0e8 100%); min-height: 100vh; }
.block-container { padding: 0.6rem 0.8rem 3rem 0.8rem !important; max-width: 100% !important; }
@media (min-width: 768px) { .block-container { padding: 1.2rem 2.5rem 3rem 2.5rem !important; max-width: 1280px !important; margin: 0 auto !important; } }
.top-header { background: linear-gradient(135deg, #002855 0%, #004080 60%, #002855 100%); border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; border-bottom: 4px solid #B8860B; box-shadow: 0 8px 32px rgba(0,40,85,0.3); }
.top-header-title { font-family: 'Playfair Display', serif; font-size: 1.25rem; font-weight: 700; color: white; margin: 0; }
.top-header-subtitle { font-size: 0.68rem; color: #B8860B; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600; margin-top: 3px; }
@media (min-width: 768px) { .top-header { padding: 28px 36px; border-radius: 16px; margin-bottom: 28px; } .top-header-title { font-size: 1.85rem; } }
.section-title { font-family: 'Playfair Display', serif; font-size: 1rem; color: #002855; font-weight: 700; border-left: 4px solid #B8860B; padding-left: 10px; margin: 14px 0 10px 0; }
.stTextInput > div > div > input, .stNumberInput > div > div > input { color: #1e1e1e !important; border-radius: 10px !important; border: 1.5px solid #c8d6e5 !important; background: white !important; min-height: 48px !important; }
.stButton > button { min-height: 48px !important; border-radius: 10px !important; font-weight: 700 !important; letter-spacing: 0.06em !important; text-transform: uppercase !important; width: 100% !important; }
.stButton > button[kind="primary"] { background: linear-gradient(135deg, #002855 0%, #004080 100%) !important; color: white !important; border: none !important; border-bottom: 3px solid #B8860B !important; }
.stButton > button:not([kind="primary"]) { background: white !important; color: #002855 !important; border: 1.5px solid #002855 !important; }
@media (min-width: 768px) { .stButton > button { width: auto !important; } }
.stDownloadButton > button { min-height: 48px !important; border-radius: 10px !important; font-weight: 700 !important; width: 100% !important; }
@media (min-width: 768px) { .stDownloadButton > button { width: auto !important; } }
[data-testid="stMetric"] { background: white !important; border: 1px solid #e0e8f0 !important; border-radius: 14px !important; padding: 12px 14px !important; box-shadow: 0 2px 12px rgba(0,40,85,0.07) !important; border-top: 3px solid #B8860B !important; }
[data-testid="stMetricValue"] { font-weight: 800 !important; color: #002855 !important; }
.price-info-box { background: linear-gradient(135deg, #002855, #004080); color: white; border-radius: 12px; padding: 12px 16px; font-weight: 700; font-size: 0.88rem; border-left: 4px solid #B8860B; margin: 8px 0; line-height: 1.8; }
.price-info-box span { color: #f0c040; font-size: 1rem; }
.pwd-box { background: white; border-radius: 16px; padding: 28px 24px; border: 1px solid #e0e8f0; border-top: 4px solid #B8860B; box-shadow: 0 6px 24px rgba(0,40,85,0.12); }
hr { border: none !important; background: linear-gradient(90deg, transparent, #B8860B, transparent) !important; height: 2px !important; margin: 14px 0 !important; }

/* ── FIX KONTRAS: label, caption, tab, radio, markdown kadang ketimpa warna
   tema default Streamlit (jadi pudar/putih di atas background terang kita) ── */
section.main .stTextInput > label, section.main .stTextInput label,
section.main .stSelectbox > label, section.main .stSelectbox label,
section.main .stNumberInput > label, section.main .stNumberInput label,
section.main .stRadio > label, section.main .stRadio label,
div[data-testid="stForm"] label, div[class*="stTextInput"] label,
div[class*="stSelectbox"] label, div[class*="stNumberInput"] label {
    font-weight: 600 !important; font-size: 0.78rem !important;
    letter-spacing: 0.06em !important; text-transform: uppercase !important;
    color: #002855 !important; opacity: 1 !important; visibility: visible !important;
}
.stTextInput > div > div > input::placeholder,
.stNumberInput > div > div > input::placeholder {
    color: #9fb3c8 !important; opacity: 1 !important;
}
section.main .stMarkdown p, section.main .stMarkdown strong,
section.main [data-testid="stMarkdownContainer"] p,
section.main [data-testid="stMarkdownContainer"] strong { color: #1e1e1e !important; }
section.main [data-testid="stCaptionContainer"] p, section.main .stCaption p { color: #5a7a9a !important; }
section.main [data-testid="stExpander"] p, section.main [data-testid="stExpander"] span,
section.main [data-testid="stExpander"] strong, section.main [data-testid="stExpander"] li { color: #1e1e1e !important; }
[data-testid="stTabs"] button p, [data-testid="stTabs"] [data-baseweb="tab"] p {
    color: #002855 !important; font-weight: 700 !important;
}
[data-testid="stRadio"] label p, [data-baseweb="radio"] label { color: #1e1e1e !important; }
[data-testid="stAlert"] p { color: #1e1e1e !important; }
[data-testid="stMetricLabel"] { color: #5a7a9a !important; }
</style>
""", unsafe_allow_html=True)


# =========================================================
# LOGIN SEDERHANA (1 orang saja)
# =========================================================
def _nasional_password():
    if "nasional_password" in st.secrets:
        return st.secrets["nasional_password"]
    return "asin123"  # GANTI sebelum deploy kalau belum diisi lewat secrets


def require_login():
    if st.session_state.get("nasional_auth"):
        return True
    st.markdown("<br>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown('<div class="pwd-box">', unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center; margin-bottom:24px;">
            <div style="font-size:2.8rem;">🔐</div>
            <div style="font-family:'Playfair Display',serif;font-size:1.15rem;color:#002855;font-weight:700;margin-top:10px;">Penawaran Nasional</div>
            <div style="font-size:0.82rem;color:#7a9ab8;margin-top:6px;">Khusus Asin</div>
        </div>
        """, unsafe_allow_html=True)
        pwd = st.text_input("🔑 Password", type="password", key="nasional_pwd_field")
        if st.button("🚀 MASUK", use_container_width=True, type="primary"):
            if pwd == _nasional_password():
                st.session_state.nasional_auth = True
                st.rerun()
            else:
                st.error("❌ Password salah.")
        st.markdown('</div>', unsafe_allow_html=True)
    return False


# =========================================================
# GOOGLE SHEETS (REGPACK / BIGPACK / Antrean_Nasional_Asin)
# =========================================================
def get_creds():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    return Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    client = gspread.authorize(get_creds())
    return client.open(SPREADSHEET_NAME)


@st.cache_data(ttl=300)
def load_rate_table(tab_name):
    ws = get_spreadsheet().worksheet(tab_name)
    df = pd.DataFrame(ws.get_all_records())
    if "Tarif per kg" in df.columns:
        df["Tarif per kg"] = pd.to_numeric(df["Tarif per kg"], errors="coerce")
    return df


@st.cache_resource(show_spinner=False)
def get_nasional_worksheet():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=SHEET_TAB, rows=500, cols=len(SHEET_HEADERS))
        ws.append_row(SHEET_HEADERS)
    if not ws.get_all_values():
        ws.append_row(SHEET_HEADERS)
    return ws


# =========================================================
# DATABASE BARANG (Nama Barang; Satuan; Harga; Berat (gram))
# =========================================================
REQUIRED_DB_COLS = ["Nama Barang", "Harga", "Satuan"]
OPTIONAL_DB_COLS = ["Berat (gram)"]


def _normalize_col(c):
    c = str(c).replace("\ufeff", "").strip()
    c = c.replace("_", " ")
    return " ".join(c.split())


@st.cache_data(ttl=300)
def load_db():
    empty_df = pd.DataFrame(columns=REQUIRED_DB_COLS + OPTIONAL_DB_COLS)
    if not os.path.exists("database_barang.csv"):
        return empty_df
    for sep in (None, ";", ",", "\t"):
        try:
            kwargs = dict(engine="python", on_bad_lines="skip")
            kwargs["sep"] = sep
            df = pd.read_csv("database_barang.csv", **kwargs)
            df.columns = [_normalize_col(c) for c in df.columns]
            col_map = {c.lower(): c for c in df.columns}
            rename_dict = {}
            for req in REQUIRED_DB_COLS + OPTIONAL_DB_COLS:
                if req.lower() in col_map:
                    rename_dict[col_map[req.lower()]] = req
            df = df.rename(columns=rename_dict)
            if all(c in df.columns for c in REQUIRED_DB_COLS):
                df["Harga"] = pd.to_numeric(df["Harga"], errors="coerce").fillna(0)
                df["Nama Barang"] = df["Nama Barang"].astype(str).str.strip()
                df["Satuan"] = df["Satuan"].astype(str).str.strip()
                if "Berat (gram)" not in df.columns:
                    df["Berat (gram)"] = pd.NA
                df["Berat (gram)"] = pd.to_numeric(df["Berat (gram)"], errors="coerce")
                return df
        except Exception:
            continue
    st.error("⚠️ Gagal membaca database_barang.csv. Pastikan kolom 'Nama Barang', 'Harga', 'Satuan' ada.")
    return empty_df


# =========================================================
# HELPER PENCARIAN
# =========================================================
def fmt_rp(x) -> str:
    try:
        if x is None or pd.isna(x):
            return "-"
        return f"Rp{float(x):,.0f}"
    except (TypeError, ValueError):
        return "-"


def search_barang(searchterm, df_barang):
    if not searchterm or len(searchterm) < 2:
        return []
    kw = searchterm.strip().lower()
    sub = [n for n in df_barang["Nama Barang"].tolist() if kw in n.lower()]
    if sub:
        return sub[:50]
    fuzzy = process.extract(searchterm, df_barang["Nama Barang"].tolist(),
                             scorer=fuzz.WRatio, processor=utils.default_process, limit=30)
    return [m[0] for m in fuzzy if m[1] > 35]


def search_district(searchterm, df_reg, df_big):
    if not searchterm:
        return []
    semua = pd.concat([df_reg[["Destination District"]], df_big[["Destination District"]]]
                       ).drop_duplicates()["Destination District"].tolist()
    matches = process.extract(searchterm, semua, scorer=fuzz.WRatio,
                               processor=utils.default_process, limit=6)
    seen, hasil = set(), []
    for m in matches:
        if m[0] not in seen:
            seen.add(m[0])
            hasil.append(m[0])
    return hasil


def get_district_row(nama, df):
    hit = df[df["Destination District"] == nama]
    return None if hit.empty else hit.iloc[0]


# =========================================================
# HITUNG ONGKIR UNTUK 1 PESANAN (berdasarkan total berat SEMUA barang)
# =========================================================
def hitung_ongkir_order(items, kota_row_reg, kota_row_big):
    """items: list of dict dengan key 'Berat (gram)' (berat per final unit, SUDAH memperhitungkan
    konversi satuan seperti Lusin/Dus) dan 'Qty'. Return dict hasil atau None kalau kota tidak ada."""
    total_gram = sum(float(it["Berat (gram)"]) * int(it["Qty"]) for it in items)
    total_kg = total_gram / 1000
    billable = max(MIN_BILLABLE_KG, math.ceil(total_kg))
    kategori = "BIGPACK" if billable >= BIGPACK_THRESHOLD_KG else "REGPACK"
    row = kota_row_big if kategori == "BIGPACK" else kota_row_reg
    if row is None:
        return None
    tarif = float(row["Tarif per kg"])
    ongkir = billable * tarif
    return {
        "total_gram": total_gram, "total_kg": total_kg, "billable_kg": billable,
        "kategori": kategori, "tarif": tarif, "ongkir": ongkir,
    }


def item_key(row_idx, nama_barang):
    h = hashlib.md5(nama_barang.encode()).hexdigest()[:8]
    return f"n{row_idx}_{h}"


# =========================================================
# PDF
# =========================================================
class PenawaranPDF(FPDF):
    def __init__(self, total_pages=1):
        super().__init__()
        self.total_pages = total_pages

    def header(self):
        self.set_fill_color(*COLOR_NAVY); self.rect(0, 0, 210, 52, 'F')
        self.set_fill_color(255, 255, 255); self.rect(10, 6, 44, 40, 'F')
        self.set_fill_color(*COLOR_GOLD); self.rect(58, 0, 3, 52, 'F')
        if os.path.exists("logo.png"):
            self.image("logo.png", 13, 10, 38)
        self.set_y(10); self.set_x(66)
        self.set_font('Arial', 'B', 17); self.set_text_color(255, 255, 255)
        self.cell(0, 8, COMPANY_NAME, ln=1)
        self.set_x(66); self.set_font('Arial', 'B', 8.5); self.set_text_color(*COLOR_GOLD)
        self.cell(0, 5, "  ".join(SLOGAN.upper()), ln=1)
        self.set_y(29); self.set_x(66); self.set_font('Arial', '', 7.5); self.set_text_color(210, 220, 235)
        self.cell(0, 4.5, ADDR, ln=1)
        self.set_x(66); self.cell(0, 4.5, f"Office: {OFFICE_PHONE}  |  WA: {MARKETING_WA}", ln=1)
        self.set_x(66); self.cell(0, 4.5, f"Email: {MARKETING_EMAIL}", ln=1)
        self.set_fill_color(*COLOR_GOLD); self.rect(0, 52, 210, 2.5, 'F')
        self.set_y(62)

    def footer(self):
        self.set_y(-18)
        self.set_fill_color(*COLOR_GOLD); self.rect(0, self.get_y(), 210, 1.5, 'F')
        self.set_fill_color(*COLOR_NAVY); self.rect(0, self.get_y() + 1.5, 210, 17, 'F')
        self.set_y(-14); self.set_font('Arial', 'B', 8); self.set_text_color(255, 255, 255)
        self.cell(0, 5, SLOGAN.upper(), 0, 1, 'C')
        self.set_font('Arial', '', 7); self.set_text_color(*COLOR_GOLD)
        self.cell(0, 4, f"{COMPANY_NAME}  |  {ADDR}  |  Hal. {self.page_no()} / {self.total_pages}", 0, 0, 'C')


def draw_table_header(pdf):
    pdf.set_fill_color(*COLOR_NAVY); pdf.set_text_color(255, 255, 255); pdf.set_font('Arial', 'B', 9)
    pdf.set_draw_color(*COLOR_GOLD); pdf.set_line_width(0.4)
    pdf.cell(10, 10, 'NO', border=1, align='C', fill=True)
    pdf.cell(76, 10, 'DESKRIPSI', border=1, align='C', fill=True)
    pdf.cell(16, 10, 'QTY', border=1, align='C', fill=True)
    pdf.cell(18, 10, 'SATUAN', border=1, align='C', fill=True)
    pdf.cell(30, 10, 'HARGA', border=1, align='C', fill=True)
    pdf.cell(30, 10, 'TOTAL', border=1, align='C', fill=True)
    pdf.ln()


def generate_pdf(no_surat, nama_cust, pic, kota_tujuan, df_order, subtotal, ppn, grand_total):
    def _render(pdf):
        pdf.set_margins(10, 70, 10); pdf.set_auto_page_break(auto=True, margin=28); pdf.add_page()
        pdf.set_y(62); pdf.set_font('Arial', 'B', 26); pdf.set_text_color(*COLOR_NAVY)
        pdf.cell(0, 10, "QUOTATION", ln=1, align='R')
        pdf.set_draw_color(*COLOR_GOLD); pdf.set_line_width(0.8); pdf.line(10, pdf.get_y(), 200, pdf.get_y()); pdf.ln(2)
        waktu = datetime.utcnow() + timedelta(hours=7); expiry = waktu + timedelta(days=7)
        pdf.set_font('Arial', '', 8.5); pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, f"No. Surat   : {no_surat}", ln=1, align='R')
        pdf.cell(0, 5, f"Tanggal      : {waktu.strftime('%d %B %Y')}", ln=1, align='R')
        pdf.cell(0, 5, f"Berlaku s/d  : {expiry.strftime('%d %B %Y')}", ln=1, align='R')
        pdf.ln(4)
        pdf.set_x(10); pdf.set_font('Arial', 'B', 7.5); pdf.set_text_color(*COLOR_GOLD)
        pdf.cell(90, 5, "DITUJUKAN KEPADA:", ln=1)
        pdf.set_x(10); pdf.set_font('Arial', 'B', 13); pdf.set_text_color(*COLOR_NAVY)
        pdf.cell(90, 7, str(nama_cust).upper(), ln=1)
        pdf.set_x(10); pdf.set_font('Arial', '', 9); pdf.set_text_color(*COLOR_TEXT)
        pdf.cell(90, 5, f"U/P: {pic}", ln=1)
        pdf.set_x(10); pdf.cell(90, 5, f"Tujuan Kirim: {kota_tujuan}", ln=1)
        pdf.ln(6)

        draw_table_header(pdf); pdf.set_font('Arial', '', 9); pdf.set_text_color(*COLOR_TEXT)
        for i, row in df_order.iterrows():
            if pdf.get_y() > 170:
                pdf.add_page(); draw_table_header(pdf); pdf.set_font('Arial', '', 9); pdf.set_text_color(*COLOR_TEXT)
            pdf.set_fill_color(240, 245, 252) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            pdf.set_draw_color(180, 195, 215); pdf.set_line_width(0.2)
            pdf.cell(10, 8, str(i + 1), border=1, align='C', fill=True)
            pdf.cell(76, 8, f" {str(row['Nama Barang'])}", border=1, align='L', fill=True)
            pdf.cell(16, 8, str(row['Qty']), border=1, align='C', fill=True)
            pdf.cell(18, 8, str(row['Satuan']), border=1, align='C', fill=True)
            pdf.cell(30, 8, f"Rp {row['Harga']:,.0f}", border=1, align='R', fill=True)
            pdf.cell(30, 8, f"Rp {row['Total_Row']:,.0f}", border=1, align='R', fill=True)
            pdf.ln()

        pdf.ln(4); pdf.set_draw_color(*COLOR_GOLD); pdf.set_line_width(0.6)
        pdf.line(120, pdf.get_y(), 200, pdf.get_y()); pdf.ln(3)
        pdf.set_font('Arial', '', 9); pdf.set_text_color(*COLOR_TEXT); pdf.set_x(120)
        pdf.cell(50, 7, "Sub Total", align='L'); pdf.cell(30, 7, f"Rp {subtotal:,.0f}", align='R', ln=1)
        pdf.set_x(120); pdf.cell(50, 7, "PPN 11%", align='L'); pdf.cell(30, 7, f"Rp {ppn:,.0f}", align='R', ln=1)
        pdf.set_draw_color(*COLOR_NAVY); pdf.set_line_width(0.4); pdf.line(120, pdf.get_y(), 200, pdf.get_y()); pdf.ln(1)
        pdf.set_fill_color(*COLOR_NAVY); pdf.set_text_color(255, 255, 255); pdf.set_font('Arial', 'B', 10)
        pdf.set_x(120); pdf.cell(50, 10, "  GRAND TOTAL", border=0, align='L', fill=True)
        pdf.cell(30, 10, f"Rp {grand_total:,.0f}  ", border=0, align='R', fill=True, ln=1)
        pdf.set_draw_color(*COLOR_GOLD); pdf.set_line_width(0.8); pdf.line(120, pdf.get_y(), 200, pdf.get_y())

        TC_H = 62; BOTTOM = 297 - 28
        if pdf.get_y() + 10 + TC_H > BOTTOM:
            pdf.add_page(); pdf.set_y(68)
        else:
            pdf.ln(10)
        y_tc = pdf.get_y()
        pdf.set_fill_color(248, 250, 253); pdf.set_draw_color(*COLOR_NAVY); pdf.set_line_width(0.4)
        pdf.rect(10, y_tc, 120, TC_H, 'DF')
        pdf.set_y(y_tc + 3); pdf.set_x(13); pdf.set_font('Arial', 'B', 9); pdf.set_text_color(*COLOR_NAVY)
        pdf.cell(116, 5, "SYARAT & KETENTUAN:", ln=1)
        pdf.set_draw_color(*COLOR_GOLD); pdf.set_line_width(0.5); pdf.line(13, pdf.get_y(), 127, pdf.get_y()); pdf.ln(2)
        pdf.set_x(13); pdf.set_font('Arial', '', 8.5); pdf.set_text_color(50, 50, 50)
        terms = (
            "1. Harga sudah termasuk ongkos kirim ke tujuan yang tertera.\n"
            "2. Harga dapat berubah sewaktu-waktu tanpa pemberitahuan.\n"
            "3. Penawaran berlaku 7 hari dari tanggal surat.\n"
            "4. Estimasi pengiriman menyesuaikan tarif ekspedisi ke wilayah tujuan.\n"
            "5. Pembayaran ditransfer HANYA ke rekening berikut:\n"
            "   Bank       : Bank BCA\n"
            "   No. Rek    : 658 033 8818\n"
            "   Atas Nama  : PT THEA THEO STATIONARY"
        )
        pdf.set_x(13); pdf.multi_cell(114, 5.2, terms)

        pdf.set_y(y_tc + 3); pdf.set_x(138); pdf.set_font('Arial', 'B', 8.5); pdf.set_text_color(*COLOR_GOLD)
        pdf.cell(60, 5, "Hormat Kami,", ln=1)
        ttd_path = "ttd_clean.png"
        if os.path.exists(ttd_path):
            pdf.image(ttd_path, x=133, y=pdf.get_y() + 1, w=45)
            pdf.set_y(pdf.get_y() + 1 + 35)
        else:
            pdf.ln(36)
        pdf.set_x(138); pdf.set_font('Arial', 'B', 12); pdf.set_text_color(*COLOR_NAVY)
        pdf.cell(60, 7, MARKETING_NAME.upper(), ln=1)
        pdf.set_x(138); pdf.set_font('Arial', 'I', 8.5); pdf.set_text_color(*COLOR_TEXT)
        pdf.cell(60, 4.5, MARKETING_TITLE, ln=1)
        pdf.set_x(138); pdf.set_font('Arial', '', 8.5)
        pdf.cell(60, 5, f"WA    : {MARKETING_WA}", ln=1)
        pdf.set_x(138); pdf.cell(60, 5, f"Email : {MARKETING_EMAIL}", ln=1)

    pdf1 = PenawaranPDF(total_pages=99); _render(pdf1); total_pages = pdf1.page
    pdf2 = PenawaranPDF(total_pages=total_pages); _render(pdf2)
    return pdf2.output(dest='S').encode('latin-1')


# =========================================================
# EXCEL
# =========================================================
def generate_excel(no_surat, nama_cust, pic, kota_tujuan, df_order, subtotal, ppn, grand_total):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book; ws = wb.add_worksheet('Quotation')
        f_navy = wb.add_format({'bg_color': '#002855', 'font_color': 'white', 'bold': True, 'font_size': 18, 'valign': 'vcenter'})
        f_gold = wb.add_format({'font_color': '#B8860B', 'bold': True, 'font_size': 10})
        f_white = wb.add_format({'font_color': 'white', 'font_size': 9})
        f_head = wb.add_format({'bg_color': '#002855', 'font_color': 'white', 'bold': True, 'border': 1, 'align': 'center'})
        f_border = wb.add_format({'border': 1})
        f_money = wb.add_format({'border': 1, 'num_format': '#,##0'})
        f_label = wb.add_format({'bold': True, 'align': 'right'})
        f_grand = wb.add_format({'bg_color': '#002855', 'font_color': 'white', 'bold': True, 'num_format': '#,##0', 'align': 'right'})
        ws.set_column('A:A', 5); ws.set_column('B:B', 45); ws.set_column('C:C', 10)
        ws.set_column('D:D', 10); ws.set_column('E:E', 15); ws.set_column('F:F', 18)
        for r in range(5):
            ws.write_blank(r, 0, '', f_navy)
        ws.merge_range('B2:F2', COMPANY_NAME, f_navy)
        ws.write('B3', "  ".join(SLOGAN.upper()), f_gold)
        ws.write('B4', f"{ADDR} | Office: {OFFICE_PHONE}", f_white)
        ws.write('B5', f"WhatsApp: {MARKETING_WA} | Email: {MARKETING_EMAIL}", f_white)
        ws.write('B7', "PREPARED FOR:", f_gold)
        ws.write('B8', str(nama_cust).upper(), wb.add_format({'bold': True, 'font_size': 12}))
        ws.write('B9', f"Attention: {pic}")
        ws.write('B10', f"Tujuan Kirim: {kota_tujuan}")
        ws.write('F7', "QUOTATION", wb.add_format({'bold': True, 'font_size': 20, 'align': 'right', 'font_color': '#002855'}))
        ws.write('F8', f"Ref: {no_surat}", wb.add_format({'align': 'right'}))
        ws.write('F9', f"Date: {(datetime.utcnow() + timedelta(hours=7)).strftime('%d %B %Y')}", wb.add_format({'align': 'right'}))
        header_row = 12
        for c, label in enumerate(['NO', 'DESCRIPTION', 'QTY', 'UNIT', 'PRICE', 'TOTAL']):
            ws.write(header_row, c, label, f_head)
        r = header_row + 1
        for i, row in df_order.iterrows():
            ws.write(r, 0, i + 1, f_border); ws.write(r, 1, row['Nama Barang'], f_border)
            ws.write(r, 2, row['Qty'], f_border); ws.write(r, 3, row['Satuan'], f_border)
            ws.write(r, 4, row['Harga'], f_money); ws.write(r, 5, row['Total_Row'], f_money)
            r += 1
        r += 1
        ws.write(r, 4, "Sub Total", f_label); ws.write(r, 5, subtotal, f_money); r += 1
        ws.write(r, 4, "VAT (PPN 11%)", f_label); ws.write(r, 5, ppn, f_money); r += 1
        ws.write(r, 4, "GRAND TOTAL", f_label); ws.write(r, 5, grand_total, f_grand)
        ws.write(r + 3, 0, MARKETING_NAME, wb.add_format({'bold': True}))
        ws.write(r + 4, 0, MARKETING_TITLE, wb.add_format({'italic': True, 'font_color': '#002855'}))
    return output.getvalue()


# =========================================================
# HEADER
# =========================================================
def render_header(title, subtitle=""):
    st.markdown(f"""
    <div class="top-header">
        <div class="top-header-title">{title}</div>
        <div class="top-header-subtitle">{subtitle if subtitle else SLOGAN}</div>
    </div>
    """, unsafe_allow_html=True)


# =========================================================
# SESSION STATE
# =========================================================
if "cart" not in st.session_state:
    st.session_state.cart = []
if "nasional_auth" not in st.session_state:
    st.session_state.nasional_auth = False
if "widget_id" not in st.session_state:
    st.session_state.widget_id = 0

render_header("🚚 Penawaran Nasional", "Khusus pengiriman ke luar Jabodetabek")

if not require_login():
    st.stop()

top_l, top_r = st.columns([4, 1])
top_l.success(f"✅ Login sebagai **{MARKETING_NAME}**")
if top_r.button("🚪 Logout", use_container_width=True):
    st.session_state.nasional_auth = False
    st.rerun()

try:
    with st.spinner("Memuat data..."):
        df_barang = load_db()
        df_reg = load_rate_table("REGPACK")
        df_big = load_rate_table("BIGPACK")
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

st.caption(f"📊 {len(df_barang)} produk · {len(df_reg)} kecamatan REGPACK · {len(df_big)} kecamatan BIGPACK")

tab_buat, tab_dash = st.tabs(["📝 Buat Penawaran", "📊 Dashboard"])

# ---------------------------------------------------------------------------
# TAB: BUAT PENAWARAN
# ---------------------------------------------------------------------------
with tab_buat:
    st.markdown('<div class="section-title">👤 Data Pelanggan & Tujuan Kirim</div>', unsafe_allow_html=True)
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        nama_toko = c1.text_input("🏢 Nama Perusahaan / Toko", placeholder="PT. Contoh Maju Bersama")
        up_nama = c2.text_input("👤 Nama Penerima (UP)", placeholder="Bapak / Ibu ...")
        wa_nomor = c3.text_input("📞 Nomor WhatsApp", placeholder="08xx-xxxx-xxxx")

        cari_d = st.text_input("📍 Kota/Kecamatan Tujuan", placeholder="misal: denpasar, jayapura, makassar")
        kota_tujuan = None
        if cari_d:
            opsi_d = search_district(cari_d, df_reg, df_big)
            if opsi_d:
                kota_tujuan = st.radio("Pilih kecamatan:", opsi_d, index=0, key="radio_kota")
            else:
                st.warning("Kecamatan tidak ditemukan di data ongkir.")

    st.markdown('<div class="section-title">📦 Tambah Barang ke Keranjang</div>', unsafe_allow_html=True)
    with st.container(border=True):
        cari_p = st.text_input("🔍 Cari nama barang (min. 2 huruf)",
                                key=f"cari_p_{st.session_state.widget_id}")
        pilihan_barang = None
        if cari_p and len(cari_p) >= 2:
            opsi_p = search_barang(cari_p, df_barang)
            if opsi_p:
                pilihan_barang = st.radio("Pilih barang:", opsi_p, index=0,
                                           key=f"radio_p_{st.session_state.widget_id}")
            else:
                st.info("Barang tidak ditemukan.")

        if pilihan_barang:
            row_m = df_barang[df_barang["Nama Barang"] == pilihan_barang].iloc[0]
            h_master = float(row_m["Harga"])
            satuan_db = str(row_m["Satuan"]).strip()
            berat_master = row_m["Berat (gram)"]

            if pd.isna(berat_master):
                st.error(
                    f"⚠️ Berat untuk '{pilihan_barang}' belum diisi di database. "
                    "Barang ini TIDAK BISA dimasukkan ke keranjang sampai beratnya diisi "
                    "(lewat menu 'Update Database Barang' di Dashboard)."
                )
            else:
                c1, c2 = st.columns(2)
                mode_c = c1.selectbox(f"Satuan (Default: {satuan_db})",
                                       ["Sesuai Database", "Lusin (12)", "Dus", "Box", "Pack", "Set"],
                                       key=f"m_c_{st.session_state.widget_id}")
                mult_c = 1
                sat_final = satuan_db
                if mode_c == "Lusin (12)":
                    mult_c = 12
                    sat_final = "Lusin"
                elif mode_c in ["Dus", "Box", "Pack", "Set"]:
                    isi_c = st.number_input(f"Isi per {mode_c}", min_value=1, value=10,
                                             key=f"isi_c_{st.session_state.widget_id}")
                    mult_c = isi_c
                    sat_final = mode_c

                qty_c = c2.number_input(f"Jumlah ({sat_final})", min_value=1, value=1,
                                         key=f"qty_c_{st.session_state.widget_id}")
                h_jual_c = int(h_master * mult_c)
                berat_final_c = float(berat_master) * mult_c  # gram per 1 satuan final (misal per dus)

                st.markdown(f"""
                <div class="price-info-box">
                    💰 Harga: <span>Rp {h_jual_c:,.0f}</span> / {sat_final}<br>
                    ⚖️ Berat: <span>{berat_final_c:,.0f} gram</span> / {sat_final}<br>
                    🔢 Qty: <span>{int(qty_c)} {sat_final}</span> &nbsp;|&nbsp;
                    💵 Total: <span>Rp {int(qty_c * h_jual_c):,.0f}</span>
                </div>
                """, unsafe_allow_html=True)

                if st.button("➕ Masukkan ke Keranjang", use_container_width=True, type="primary"):
                    st.session_state.cart = [x for x in st.session_state.cart if x["Nama Barang"] != pilihan_barang]
                    st.session_state.cart.append({
                        "Nama Barang": pilihan_barang, "Qty": int(qty_c),
                        "Harga": float(h_jual_c), "Satuan": sat_final,
                        "Berat (gram)": berat_final_c,
                        "Total_Row": float(qty_c * h_jual_c),
                    })
                    st.session_state.widget_id += 1
                    st.toast(f"✅ Ditambahkan: {pilihan_barang}")
                    time.sleep(0.2)
                    st.rerun()

    if st.session_state.cart:
        st.markdown(f'<div class="section-title">🛒 Keranjang ({len(st.session_state.cart)} item)</div>', unsafe_allow_html=True)

        for i, item in enumerate(st.session_state.cart):
            with st.container(border=True):
                st.markdown(
                    f"<span style='color:#002855;font-weight:700;'>{item['Nama Barang']}</span><br>"
                    f"<span style='color:#5a7a9a;font-size:0.8rem;'>@ Rp {item['Harga']:,.0f} / {item['Satuan']} "
                    f"&middot; {item['Berat (gram)']:,.0f} gram/{item['Satuan']}</span>",
                    unsafe_allow_html=True
                )
                ca, cb = st.columns([3, 1])
                ca.markdown(f"🔢 {item['Qty']} {item['Satuan']} &middot; Rp {item['Total_Row']:,.0f}",
                            unsafe_allow_html=True)
                if cb.button("✕ Hapus", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()

        subtotal_barang = sum(x["Total_Row"] for x in st.session_state.cart)

        if not kota_tujuan:
            st.warning("⚠️ Pilih kota/kecamatan tujuan dulu di atas untuk menghitung ongkir.")
        else:
            row_reg = get_district_row(kota_tujuan, df_reg)
            row_big = get_district_row(kota_tujuan, df_big)
            hasil = hitung_ongkir_order(st.session_state.cart, row_reg, row_big)

            if hasil is None:
                st.error(f"Kecamatan '{kota_tujuan}' tidak ditemukan di tabel ongkir.")
            else:
                subtotal = subtotal_barang + hasil["ongkir"]
                ppn = subtotal * PPN_RATE
                grand = subtotal + ppn

                st.markdown("---")
                m1, m2, m3 = st.columns(3)
                m1.metric("Subtotal Barang", fmt_rp(subtotal_barang))
                m2.metric(f"Ongkir ({hasil['kategori']}, {hasil['billable_kg']} kg)", fmt_rp(hasil["ongkir"]),
                          help=f"Total berat {hasil['total_gram']:,.0f} gram, tarif {fmt_rp(hasil['tarif'])}/kg")
                m3.metric("Subtotal + Ongkir", fmt_rp(subtotal))
                m4, m5 = st.columns(2)
                m4.metric("PPN 11%", fmt_rp(ppn))
                m5.metric("GRAND TOTAL", fmt_rp(grand))

                st.divider()
                if st.button("🚀 KIRIM / SIMPAN PENAWARAN", use_container_width=True, type="primary"):
                    if not nama_toko:
                        st.error("⚠️ Nama Toko/Perusahaan wajib diisi!")
                    else:
                        ws = get_nasional_worksheet()
                        wkt = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
                        ws.append_row([
                            wkt, nama_toko, up_nama, wa_nomor, kota_tujuan,
                            hasil["kategori"], hasil["total_gram"], hasil["ongkir"],
                            str(st.session_state.cart), "Pending",
                        ])
                        st.balloons()
                        st.success(f"✅ Penawaran untuk **{nama_toko}** ke **{kota_tujuan}** tersimpan!")
                        st.session_state.cart = []
                        time.sleep(1)
                        st.rerun()

        if st.button("🗑️ Kosongkan Keranjang", use_container_width=True):
            st.session_state.cart = []
            st.rerun()

# ---------------------------------------------------------------------------
# TAB: DASHBOARD
# ---------------------------------------------------------------------------
with tab_dash:
    with st.expander("📁 Update Database Barang (.csv)", expanded=False):
        st.caption(
            "Upload file CSV baru untuk mengganti database produk. Wajib ada kolom "
            "'Nama Barang', 'Satuan', 'Harga', dan sebaiknya 'Berat (gram)' "
            "supaya ongkir bisa dihitung."
        )
        up_f = st.file_uploader("Pilih file CSV baru:", type=["csv"], key="csv_upload_nasional")
        if up_f and st.button("🚀 Update Database Sekarang", type="primary"):
            with open("database_barang.csv", "wb") as f:
                f.write(up_f.getbuffer())
            st.cache_data.clear()
            st.success("✅ Database berhasil diperbarui!")
            time.sleep(1)
            st.rerun()

    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    ws = get_nasional_worksheet()
    all_vals = ws.get_all_values()
    if len(all_vals) <= 1:
        st.info("Belum ada penawaran nasional yang masuk.")
    else:
        headers = [h.strip() for h in all_vals[0]]
        df_gs = pd.DataFrame(all_vals[1:], columns=headers)
        for c in SHEET_HEADERS:
            if c not in df_gs.columns:
                df_gs[c] = ""
        pending = df_gs[df_gs["Status"].str.lower() == "pending"]

        d1, d2, d3 = st.columns(3)
        d1.metric("Total", len(df_gs))
        d2.metric("Pending", len(pending))
        d3.metric("Selesai", len(df_gs) - len(pending))

        if pending.empty:
            st.success("🎉 Semua penawaran sudah diproses!")
        else:
            for idx, row in pending.iterrows():
                real_row = idx + 2
                try:
                    items = ast_items = pd.eval(row["Pesanan"]) if False else __import__("ast").literal_eval(row["Pesanan"])
                except Exception:
                    items = []
                n_items = len(items)

                with st.expander(f"🏢 {row['Customer']} → {row['Kota Tujuan']} · {n_items} item · {row['Waktu']}",
                                  expanded=False):
                    st.info(
                        f"👤 UP: **{row['UP']}** &nbsp;|&nbsp; 📞 **{row['WA']}** &nbsp;|&nbsp; "
                        f"📍 **{row['Kota Tujuan']}** &nbsp;|&nbsp; 📦 {row['Kategori Ongkir']}"
                    )

                    f_df = pd.DataFrame(items)
                    if not f_df.empty:
                        ongkir_tersimpan = float(row["Ongkir"]) if row["Ongkir"] else 0.0
                        ongkir_row = pd.DataFrame([{
                            "Nama Barang": f"🚚 Ongkos Kirim ke {row['Kota Tujuan']}",
                            "Qty": 1, "Harga": ongkir_tersimpan, "Satuan": "-",
                            "Total_Row": ongkir_tersimpan,
                        }])
                        f_df_cetak = pd.concat([f_df, ongkir_row], ignore_index=True)

                        subt = f_df_cetak["Total_Row"].sum()
                        tax = subt * PPN_RATE
                        gtot = subt + tax

                        st.dataframe(f_df_cetak[["Nama Barang", "Qty", "Satuan", "Harga", "Total_Row"]],
                                     use_container_width=True, hide_index=True)

                        t1, t2 = st.columns(2)
                        t1.metric("Subtotal (barang + ongkir)", fmt_rp(subt))
                        t2.metric("Grand Total", fmt_rp(gtot))

                        no_s = st.text_input("📄 Nomor Surat:", value="/S-TTS/X/2026", key=f"ns_{real_row}")
                        waktu_file = (datetime.utcnow() + timedelta(hours=7)).strftime("%d%m%y_%H%M")
                        safe_cust = "".join(c for c in str(row["Customer"]) if c.isalnum() or c in " -_").strip().replace(" ", "_")

                        b1, b2 = st.columns(2)
                        pdf_data = generate_pdf(no_s, row["Customer"], row["UP"], row["Kota Tujuan"],
                                                 f_df_cetak, subt, tax, gtot)
                        b1.download_button("📩 PDF", pdf_data, file_name=f"Quo_Nasional_{safe_cust}_{waktu_file}.pdf",
                                            use_container_width=True, type="primary", key=f"pdf_{real_row}")
                        xls_data = generate_excel(no_s, row["Customer"], row["UP"], row["Kota Tujuan"],
                                                   f_df_cetak, subt, tax, gtot)
                        b2.download_button("📊 Excel", xls_data, file_name=f"Quo_Nasional_{safe_cust}_{waktu_file}.xlsx",
                                            use_container_width=True, key=f"xls_{real_row}")

                        if st.button("✅ TANDAI SELESAI", key=f"done_{real_row}", type="primary", use_container_width=True):
                            ws.update_cell(real_row, SHEET_HEADERS.index("Status") + 1, "Processed")
                            st.success("Ditandai selesai.")
                            time.sleep(0.5)
                            st.rerun()
