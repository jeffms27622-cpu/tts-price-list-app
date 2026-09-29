"""
TTS Price List App
====================
App internal untuk Sin (Asin) - menghitung harga jual produk ATK
(harga dasar + ongkir) berdasarkan kota/kecamatan tujuan, otomatis
menentukan kategori pengiriman REGPACK (<10kg) atau BIGPACK (>=10kg).

Data disimpan di Google Sheets (3 tab): Produk, REGPACK, BIGPACK.
Lihat README.md untuk cara setup Google Sheets & credentials.

Changelog perbaikan:
- Validasi 'Harga Dasar' kosong (sebelumnya hanya berat yang dicek -> bisa crash/NaN)
- Simpan produk: buang baris kosong, wajib ada 'Nama Produk', NaN ditulis sebagai
  sel kosong ke Sheets, error handling saat simpan (sebelumnya gagal diam-diam)
- Opsi radio dijamin unik (nama produk/kecamatan duplikat tidak bikin pilihan kabur)
- Helper fmt_rp() supaya format Rupiah konsisten & aman dari NaN
- Loading spinner + info jumlah data yang terbaca, tombol 'Muat ulang data'
- Tab Pricelist: produk tanpa harga dasar tidak lagi crash math.ceil(NaN),
  tetapi ditandai 'Harga dasar belum diisi'
- Penjelasan rumus yang lebih jelas di setiap tab
"""

import math
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from rapidfuzz import process, fuzz, utils

st.set_page_config(page_title="TTS Price List", page_icon="📦", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.readonly"]

BIGPACK_THRESHOLD_KG = 10   # >= ini pakai BIGPACK, di bawahnya REGPACK
MIN_BILLABLE_KG = 1         # minimum ongkir dihitung 1kg

PRODUK_COLS = ["Kode", "Nama Produk", "Kategori", "Harga Dasar", "Berat (gram)"]
RATE_COLS = ["Destination District", "Pulau", "Tarif per kg"]


# ---------------------------------------------------------------------------
# Helper umum
# ---------------------------------------------------------------------------

def fmt_rp(x) -> str:
    """Format angka jadi 'Rp12.500'. Aman terhadap NaN/None."""
    try:
        if x is None or pd.isna(x):
            return "-"
        return f"Rp{float(x):,.0f}"
    except (TypeError, ValueError):
        return "-"


# ---------------------------------------------------------------------------
# Koneksi Google Sheets
# ---------------------------------------------------------------------------

@st.cache_resource
def get_gspread_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource
def get_spreadsheet():
    client = get_gspread_client()
    return client.open_by_key(st.secrets["SHEET_ID"])


def _ws(name):
    return get_spreadsheet().worksheet(name)


@st.cache_data(ttl=120)
def load_sheet(name, expected_cols):
    ws = _ws(name)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=expected_cols)
    else:
        # pastikan semua kolom ekspektasi ada ( Sheets bisa kehilangan kolom
        # yang isinya semua kosong )
        for c in expected_cols:
            if c not in df.columns:
                df[c] = None
    return df


def save_produk(df: pd.DataFrame):
    ws = _ws("Produk")

    # normalisasi: NaN -> "" supaya tidak tertulis 'nan' di Sheets
    out = df[PRODUK_COLS].copy()
    out = out.where(pd.notna(out), "")

    ws.clear()
    ws.update([PRODUK_COLS] + out.astype(object).values.tolist())
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# Helper perhitungan
# ---------------------------------------------------------------------------

def hitung_ongkir(berat_total_kg: float, district_row_regpack, district_row_bigpack):
    """Kembalikan (kategori, berat_billable, tarif_per_kg, ongkir) atau None kalau kecamatan tidak ditemukan di kategori yang relevan."""
    billable = max(MIN_BILLABLE_KG, math.ceil(berat_total_kg))
    kategori = "BIGPACK" if billable >= BIGPACK_THRESHOLD_KG else "REGPACK"
    row = district_row_bigpack if kategori == "BIGPACK" else district_row_regpack
    if row is None:
        return kategori, billable, None, None
    tarif = float(row["Tarif per kg"])
    ongkir = billable * tarif
    return kategori, billable, tarif, ongkir


def pilih_tarif(berat_kg: float, row_reg, row_big):
    """Pilih tabel tarif: >= 10kg BIGPACK, di bawahnya REGPACK. Return (kategori, tarif_per_kg atau None)."""
    kategori = "BIGPACK" if berat_kg >= BIGPACK_THRESHOLD_KG else "REGPACK"
    row = row_big if kategori == "BIGPACK" else row_reg
    if row is None:
        return kategori, None
    return kategori, float(row["Tarif per kg"])


def hitung_ongkir_prorata(berat_kg: float, tarif_per_kg: float):
    """Ongkir per satuan barang, dibagi rata per gram (tanpa pembulatan & tanpa minimum 1kg).
    Dipakai untuk harga pricelist per satuan supaya barang ringan (misal pulpen 10gr) wajar."""
    return berat_kg * tarif_per_kg


def bulatkan_harga(x: float, kelipatan: int = 100):
    """Bulatkan ke atas ke kelipatan Rp100 supaya harga pricelist rapi."""
    return math.ceil(x / kelipatan) * kelipatan


def cari_district(nama_dicari, df_regpack, df_bigpack):
    """Fuzzy match nama kecamatan/kota ke daftar Destination District di kedua tabel."""
    semua_district = pd.concat([
        df_regpack[["Destination District"]],
        df_bigpack[["Destination District"]],
    ]).drop_duplicates()["Destination District"].tolist()

    if not nama_dicari or not semua_district:
        return None, []

    matches = process.extract(nama_dicari, semua_district, scorer=fuzz.WRatio,
                               processor=utils.default_process, limit=5)
    return (matches[0][0] if matches else None), matches


def get_district_row(nama_district, df):
    hit = df[df["Destination District"] == nama_district]
    if hit.empty:
        return None
    return hit.iloc[0]


def cari_produk(nama_dicari, df_produk):
    if df_produk.empty or not nama_dicari:
        return []
    pilihan = df_produk["Nama Produk"].tolist()
    matches = process.extract(nama_dicari, pilihan, scorer=fuzz.WRatio,
                               processor=utils.default_process, limit=8)
    return matches


def opsi_unik(matches):
    """Ambil label pilihan dari hasil fuzzy match, dijamin unik & urut skor."""
    seen = set()
    hasil = []
    for m in matches:
        label = m[0]
        if label not in seen:
            seen.add(label)
            hasil.append(label)
    return hasil


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("📦 TTS Price List — Harga Jual + Ongkir")

try:
    with st.spinner("Memuat data dari Google Sheets..."):
        df_produk = load_sheet("Produk", PRODUK_COLS)
        df_regpack = load_sheet("REGPACK", RATE_COLS)
        df_bigpack = load_sheet("BIGPACK", RATE_COLS)
except Exception as e:
    st.error(
        "Gagal konek ke Google Sheets. Cek kembali SHEET_ID dan credentials di "
        "Streamlit secrets (lihat README.md).\n\nDetail error: " + str(e)
    )
    st.stop()

for col in ["Harga Dasar", "Berat (gram)"]:
    if col in df_produk.columns:
        df_produk[col] = pd.to_numeric(df_produk[col], errors="coerce")
for col in ["Tarif per kg"]:
    df_regpack[col] = pd.to_numeric(df_regpack[col], errors="coerce")
    df_bigpack[col] = pd.to_numeric(df_bigpack[col], errors="coerce")

top1, top2 = st.columns([4, 1])
with top1:
    st.caption(
        f"📊 Terbaca: **{len(df_produk)}** produk · "
        f"**{len(df_regpack)}** kecamatan REGPACK · **{len(df_bigpack)}** kecamatan BIGPACK"
    )
with top2:
    if st.button("🔄 Muat ulang data", help="Kosongkan cache & ambil ulang data dari Google Sheets"):
        st.cache_data.clear()
        st.rerun()

tab_hitung, tab_pricelist, tab_produk = st.tabs(
    ["🧮 Hitung Harga", "📋 Generate Pricelist per Kota", "🗂️ Kelola Produk"]
)

# ---------------------------------------------------------------------------
# TAB 1: Hitung Harga
# ---------------------------------------------------------------------------
with tab_hitung:
    st.subheader("Hitung harga jual untuk 1 pesanan")

    col1, col2 = st.columns(2)

    with col1:
        cari_p = st.text_input("Cari produk", placeholder="misal: kertas a4 75gr")
        produk_terpilih = None
        if cari_p:
            hasil_p = cari_produk(cari_p, df_produk)
            if hasil_p:
                opsi_p = opsi_unik(hasil_p)
                pilihan_p = st.radio("Pilih produk yang cocok:", opsi_p, index=0)
                produk_terpilih = df_produk[df_produk["Nama Produk"] == pilihan_p].iloc[0]
            else:
                st.warning("Produk tidak ditemukan. Cek tab 'Kelola Produk'.")

    with col2:
        cari_d = st.text_input("Kota/kecamatan tujuan", placeholder="misal: cipondoh tangerang")
        district_terpilih = None
        if cari_d:
            _, hasil_d = cari_district(cari_d, df_regpack, df_bigpack)
            if hasil_d:
                opsi_d = opsi_unik(hasil_d)
                district_terpilih = st.radio("Pilih kecamatan yang cocok:", opsi_d, index=0)
            else:
                st.warning("Kecamatan tidak ditemukan di data ongkir.")

    qty = st.number_input("Qty", min_value=1, value=1, step=1)

    if produk_terpilih is not None and district_terpilih:
        berat_satuan = produk_terpilih["Berat (gram)"]  # gram per satuan jual
        harga_dasar = produk_terpilih["Harga Dasar"]

        if pd.isna(berat_satuan):
            st.error(
                f"Berat produk '{produk_terpilih['Nama Produk']}' belum diisi. "
                "Isi dulu di tab 'Kelola Produk' supaya ongkir bisa dihitung."
            )
        elif pd.isna(harga_dasar):
            st.error(
                f"Harga dasar produk '{produk_terpilih['Nama Produk']}' belum diisi. "
                "Isi dulu di tab 'Kelola Produk'."
            )
        else:
            berat_total = berat_satuan * qty / 1000  # konversi gram -> kg
            row_reg = get_district_row(district_terpilih, df_regpack)
            row_big = get_district_row(district_terpilih, df_bigpack)
            kategori, billable, tarif, ongkir = hitung_ongkir(berat_total, row_reg, row_big)

            if tarif is None:
                st.error(
                    f"Kecamatan '{district_terpilih}' tidak ada di tabel {kategori}. "
                    "Cek kembali data ongkir."
                )
            else:
                # (A) Harga per satuan untuk pricelist: ongkir dibagi rata per gram
                berat_unit_kg = berat_satuan / 1000
                ongkir_prorata_unit = hitung_ongkir_prorata(berat_unit_kg, tarif)
                harga_unit_pricelist = bulatkan_harga(harga_dasar + ongkir_prorata_unit)

                # (B) Estimasi ongkir aktual untuk pesanan ini (dibulatkan ke atas, min 1kg)
                total_harga_aktual = (harga_dasar * qty) + ongkir

                st.success("Perhitungan berhasil")

                st.markdown("#### 🏷️ Harga per satuan (untuk pricelist)")
                p1, p2, p3 = st.columns(3)
                p1.metric("Harga dasar", fmt_rp(harga_dasar))
                p2.metric("Ongkir per satuan", fmt_rp(ongkir_prorata_unit),
                          help=f"{berat_satuan:,.0f} gram x {fmt_rp(tarif)}/kg, dibagi rata per gram")
                p3.metric("Harga jual per satuan", fmt_rp(harga_unit_pricelist))

                st.markdown("#### 🚚 Estimasi ongkir pesanan ini (untuk quotation)")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Kategori", kategori)
                c2.metric("Berat ditagih", f"{billable} kg",
                          help=f"Berat asli {berat_total * 1000:,.0f} gram, dibulatkan ke atas (min. {MIN_BILLABLE_KG} kg)")
                c3.metric("Tarif/kg", fmt_rp(tarif))
                c4.metric("Ongkir aktual", fmt_rp(ongkir))

                st.divider()
                st.metric(f"Total pesanan (qty {qty}) dengan ongkir aktual", fmt_rp(total_harga_aktual))
                if ongkir > ongkir_prorata_unit * qty:
                    st.caption(
                        f"ℹ️ Ongkir aktual lebih besar dari ongkir per-gram x qty "
                        f"({fmt_rp(ongkir_prorata_unit * qty)}) karena berat pesanan masih di bawah "
                        f"minimum {MIN_BILLABLE_KG} kg atau dibulatkan ke atas. Pertimbangkan minimal order."
                    )

# ---------------------------------------------------------------------------
# TAB 2: Generate Pricelist per Kota
# ---------------------------------------------------------------------------
with tab_pricelist:
    st.subheader("Generate harga semua produk untuk 1 kota tujuan")
    st.caption(
        "Ongkir dibagi rata per gram dari tarif standar per 1 kg (tanpa minimum 1 kg), "
        f"harga dibulatkan ke atas kelipatan Rp100. Kategori ongkir per produk ditentukan "
        f"dari berat 1 satuan (>= {BIGPACK_THRESHOLD_KG} kg -> BIGPACK)."
    )

    cari_d2 = st.text_input("Kota/kecamatan tujuan", key="pricelist_district",
                             placeholder="misal: surabaya")
    district_terpilih2 = None
    if cari_d2:
        _, hasil_d2 = cari_district(cari_d2, df_regpack, df_bigpack)
        if hasil_d2:
            opsi_d2 = opsi_unik(hasil_d2)
            district_terpilih2 = st.radio("Pilih kecamatan:", opsi_d2, index=0, key="radio_pricelist")
        else:
            st.warning("Kecamatan tidak ditemukan di data ongkir.")

    if district_terpilih2:
        row_reg2 = get_district_row(district_terpilih2, df_regpack)
        row_big2 = get_district_row(district_terpilih2, df_bigpack)

        hasil_rows = []
        for _, p in df_produk.iterrows():
            if pd.isna(p["Berat (gram)"]):
                hasil_rows.append({
                    "Kode": p["Kode"], "Nama Produk": p["Nama Produk"],
                    "Kategori Ongkir": "-", "Harga Jual": None,
                    "Catatan": "Berat belum diisi",
                })
                continue
            if pd.isna(p["Harga Dasar"]):
                hasil_rows.append({
                    "Kode": p["Kode"], "Nama Produk": p["Nama Produk"],
                    "Kategori Ongkir": "-", "Harga Jual": None,
                    "Catatan": "Harga dasar belum diisi",
                })
                continue
            berat_unit_kg = p["Berat (gram)"] / 1000
            kategori, tarif = pilih_tarif(berat_unit_kg, row_reg2, row_big2)
            if tarif is None:
                hasil_rows.append({
                    "Kode": p["Kode"], "Nama Produk": p["Nama Produk"],
                    "Kategori Ongkir": kategori, "Harga Jual": None,
                    "Catatan": f"Kecamatan tidak ada di tabel {kategori}",
                })
            else:
                ongkir_unit = hitung_ongkir_prorata(berat_unit_kg, tarif)
                harga_jual = bulatkan_harga(p["Harga Dasar"] + ongkir_unit)
                hasil_rows.append({
                    "Kode": p["Kode"], "Nama Produk": p["Nama Produk"],
                    "Berat (gram)": p["Berat (gram)"],
                    "Kategori Ongkir": kategori,
                    "Harga Dasar": p["Harga Dasar"],
                    "Ongkir/satuan": round(ongkir_unit),
                    "Harga Jual": harga_jual,
                    "Catatan": "",
                })

        df_hasil = pd.DataFrame(hasil_rows)
        st.dataframe(df_hasil, use_container_width=True, hide_index=True)
        csv = df_hasil.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download sebagai CSV", csv,
                            file_name=f"pricelist_{district_terpilih2}.csv", mime="text/csv")

# ---------------------------------------------------------------------------
# TAB 3: Kelola Produk
# ---------------------------------------------------------------------------
with tab_produk:
    st.subheader("Tambah / edit produk")
    st.caption(
        "Produk boleh ditambahkan sebelum beratnya diketahui — kosongkan kolom "
        "'Berat (gram)' dan isi belakangan. Isi dalam GRAM (misal pulpen 10, kertas 1 dus 12000). Selama berat kosong, harga ongkirnya "
        "belum bisa dihitung."
    )

    edited = st.data_editor(
        df_produk,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Harga Dasar": st.column_config.NumberColumn(format="Rp%d"),
            "Berat (gram)": st.column_config.NumberColumn(format="%d gr"),
        },
        key="editor_produk",
    )

    if st.button("💾 Simpan perubahan produk", type="primary"):
        missing = [c for c in PRODUK_COLS if c not in edited.columns]
        if missing:
            st.error(f"Kolom hilang: {missing}")
        else:
            # buang baris yang benar-benar kosong / tanpa nama produk
            bersih = edited.copy()
            bersih["Nama Produk"] = bersih["Nama Produk"].astype(str).str.strip()
            tanpa_nama = bersih[bersih["Nama Produk"].isin(["", "nan", "None"])]
            if not tanpa_nama.empty:
                st.warning(
                    f"{len(tanpa_nama)} baris tanpa 'Nama Produk' tidak disimpan."
                )
                bersih = bersih[~bersih["Nama Produk"].isin(["", "nan", "None"])]

            if bersih.empty:
                st.error("Tidak ada produk tersisa untuk disimpan.")
            else:
                try:
                    save_produk(bersih)
                except Exception as e:
                    st.error(f"Gagal menyimpan ke Google Sheets: {e}")
                else:
                    st.success(f"Tersimpan: {len(bersih)} produk ke Google Sheets.")
                    st.rerun()
