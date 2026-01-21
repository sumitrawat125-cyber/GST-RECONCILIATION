import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import re

st.set_page_config(page_title="GST Reconciliation", page_icon="📊", layout="wide")

st.title("📊 GST Reconciliation Tool")
st.markdown("Upload your **GSTR-2B (Portal Download)** and **Purchase Register** files to get reconciliation report")


def clean_invoice_number(invoice):
    """
    Clean invoice number by:
    1. Converting to string
    2. Removing leading/trailing spaces
    3. Removing special characters (-, /, _, spaces, dots, commas, etc.)
    4. Converting to uppercase
    5. Removing leading zeros
    """
    # Convert to string and strip whitespace
    invoice_str = str(invoice).strip()

    # Remove special characters: -, /, _, spaces, dots, commas, etc.
    invoice_cleaned = re.sub(r'[-/_ .,@#$%^&*()\[\]{}]', '', invoice_str)

    # Uppercase
    invoice_cleaned = invoice_cleaned.upper()

    # Remove leading zeros (but keep "0" if everything was zeros)
    invoice_cleaned = invoice_cleaned.lstrip('0') or '0'

    return invoice_cleaned


col1, col2 = st.columns(2)

with col1:
    st.subheader("📁 GSTR-2B (Portal)")
    portal_file = st.file_uploader("Upload GST B2B file", type=['xlsx', 'xls'], key='portal')

with col2:
    st.subheader("📁 Purchase Register (Books)")
    books_file = st.file_uploader("Upload GSTR2 file", type=['xlsx', 'xls'], key='books')

if portal_file and books_file:
    if st.button("🔄 Run Reconciliation", type="primary"):
        with st.spinner("Processing..."):
            # ========= LOAD FILES =========
            df_portal = pd.read_excel(portal_file)
            df_books = pd.read_excel(books_file)

            # ========= INVOICE CLEANING =========
            # Save original invoice numbers
            df_portal['Invoice_Original'] = df_portal['Invoice number'].astype(str)
            df_books['Invoice_Original'] = df_books['VENDOR INVOICE NO'].astype(str)

            # Clean invoice numbers (remove special chars + leading zeros)
            df_portal['Invoice_Clean'] = df_portal['Invoice number'].apply(clean_invoice_number)
            df_books['Invoice_Clean'] = df_books['VENDOR INVOICE NO'].apply(clean_invoice_number)

            # ========= GSTIN CLEANING =========
            df_portal['GSTIN_Clean'] = df_portal['GSTIN of supplier'].astype(str).str.strip().str.upper()
            df_books['GSTIN_Clean'] = df_books['VENDOR GSTIN'].astype(str).str.strip().str.upper()

            # ========= PREPARE AMOUNTS =========
            df_portal['Taxable'] = pd.to_numeric(df_portal['Taxable Value (₹)'], errors='coerce').fillna(0).round(2)
            df_portal['IGST'] = pd.to_numeric(df_portal['Integrated Tax(₹)'], errors='coerce').fillna(0).round(2)
            df_portal['CGST'] = pd.to_numeric(df_portal['Central Tax(₹)'], errors='coerce').fillna(0).round(2)
            df_portal['SGST'] = pd.to_numeric(df_portal['State/UT Tax(₹)'], errors='coerce').fillna(0).round(2)
            df_portal['TotalGST'] = df_portal['IGST'] + df_portal['CGST'] + df_portal['SGST']

            df_books['Taxable'] = pd.to_numeric(df_books['TAXABLE VALUE'], errors='coerce').fillna(0).round(2)
            df_books['CGST'] = pd.to_numeric(df_books['CGST'], errors='coerce').fillna(0).round(2)
            df_books['SGST'] = pd.to_numeric(df_books['SGST'], errors='coerce').fillna(0).round(2)
            df_books['IGST'] = pd.to_numeric(df_books['IGST'], errors='coerce').fillna(0).round(2)
            df_books['TotalGST'] = df_books['CGST'] + df_books['SGST'] + df_books['IGST']

            # ========= GROUP DUPLICATES =========
            portal_agg = {
                'Trade/Legal name': 'first',
                'Invoice Date': 'first',
                'Invoice_Original': 'first',   # keep original invoice
                'Taxable': 'sum',
                'IGST': 'sum',
                'CGST': 'sum',
                'SGST': 'sum',
                'TotalGST': 'sum'
            }
            portal_grouped = df_portal.groupby(['GSTIN_Clean', 'Invoice_Clean']).agg(portal_agg).reset_index()

            books_agg = {
                'VENDOR NAME': 'first',
                'DATE': 'first',
                'Invoice_Original': 'first',   # keep original invoice
                'Taxable': 'sum',
                'IGST': 'sum',
                'CGST': 'sum',
                'SGST': 'sum',
                'TotalGST': 'sum'
            }
            books_grouped = df_books.groupby(['GSTIN_Clean', 'Invoice_Clean']).agg(books_agg).reset_index()

            # ========= BUILD MATCH KEY & MERGE =========
            portal_grouped['Key'] = portal_grouped['GSTIN_Clean'] + '|' + portal_grouped['Invoice_Clean']
            books_grouped['Key'] = books_grouped['GSTIN_Clean'] + '|' + books_grouped['Invoice_Clean']

            comparison = pd.merge(
                portal_grouped,
                books_grouped,
                on='Key',
                how='outer',
                suffixes=('_P', '_B'),
                indicator=True
            )

            comparison['Status'] = comparison['_merge'].map({
                'both': 'MATCHED',
                'left_only': 'MISSING_IN_BOOKS',
                'right_only': 'MISSING_IN_PORTAL'
            })

            # ========= SPLIT DATASETS =========
            matched = comparison[comparison['Status'] == 'MATCHED'].copy()
            matched['Tax_Diff'] = (matched['Taxable_P'] - matched['Taxable_B']).abs()
            matched['GST_Diff'] = (matched['TotalGST_P'] - matched['TotalGST_B']).abs()
            matched['Value_Status'] = matched.apply(
                lambda x: 'PERFECT' if (x['Tax_Diff'] <= 1 and x['GST_Diff'] <= 1) else 'MISMATCH',
                axis=1
            )

            perfect = matched[matched['Value_Status'] == 'PERFECT']
            mismatch = matched[matched['Value_Status'] == 'MISMATCH']
            missing_books = comparison[comparison['Status'] == 'MISSING_IN_BOOKS']
            missing_portal = comparison[comparison['Status'] == 'MISSING_IN_PORTAL']

            # ========= DISPLAY METRICS =========
            st.success("✅ Reconciliation Complete!")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ Perfect Match", len(perfect))
            c2.metric("⚠️ Value Mismatch", len(mismatch))
            c3.metric("❌ Missing in Books", len(missing_books))
            c4.metric("❌ Missing in Portal", len(missing_portal))

            st.info("📝 **Note:** Invoice numbers have been cleaned by removing leading zeros and special characters (-, /, _, spaces, etc.).")

            # ========= CREATE EXCEL REPORT =========
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Summary sheet
                pd.DataFrame({
                    'Category': ['Perfect Match', 'Value Mismatch', 'Missing in Books', 'Missing in Portal'],
                    'Count': [len(perfect), len(mismatch), len(missing_books), len(missing_portal)]
                }).to_excel(writer, sheet_name='Summary', index=False)

                # Perfect Match sheet
                if len(perfect) > 0:
                    perfect_export = pd.DataFrame()
                    perfect_export['Match_Key'] = perfect['Key']
                    perfect_export['GSTIN'] = perfect['GSTIN_Clean_P']
                    # IMPORTANT: After merge with suffixes, use Invoice_Clean_P / _B
                    perfect_export['Invoice_Clean'] = perfect['Invoice_Clean_P']
                    perfect_export['Invoice_Original_Portal'] = perfect['Invoice_Original_P']
                    perfect_export['Invoice_Original_Books'] = perfect['Invoice_Original_B']
                    perfect_export['Supplier'] = perfect['Trade/Legal name']
                    perfect_export['Taxable_Value'] = perfect['Taxable_P']
                    perfect_export['CGST'] = perfect['CGST_P']
                    perfect_export['SGST'] = perfect['SGST_P']
                    perfect_export['IGST'] = perfect['IGST_P']
                    perfect_export['Total_GST'] = perfect['TotalGST_P']
                    perfect_export.to_excel(writer, sheet_name='Perfect_Match', index=False)

                # Value Mismatch sheet
                if len(mismatch) > 0:
                    mismatch_export = pd.DataFrame()
                    mismatch_export['Match_Key'] = mismatch['Key']
                    mismatch_export['GSTIN'] = mismatch['GSTIN_Clean_P']
                    mismatch_export['Invoice_Clean'] = mismatch['Invoice_Clean_P']
                    mismatch_export['Invoice_Original_Portal'] = mismatch['Invoice_Original_P']
                    mismatch_export['Invoice_Original_Books'] = mismatch['Invoice_Original_B']
                    mismatch_export['Supplier'] = mismatch['Trade/Legal name']
                    mismatch_export['Taxable_Portal'] = mismatch['Taxable_P']
                    mismatch_export['Taxable_Books'] = mismatch['Taxable_B']
                    mismatch_export['Taxable_Diff'] = mismatch['Tax_Diff']
                    mismatch_export['GST_Portal'] = mismatch['TotalGST_P']
                    mismatch_export['GST_Books'] = mismatch['TotalGST_B']
                    mismatch_export['GST_Diff'] = mismatch['GST_Diff']
                    mismatch_export.to_excel(writer, sheet_name='Value_Mismatch', index=False)

                # Missing in Books sheet (present in Portal only)
                if len(missing_books) > 0:
                    missing_b = pd.DataFrame()
                    missing_b['Match_Key'] = missing_books['Key']
                    missing_b['GSTIN'] = missing_books['GSTIN_Clean_P']
                    missing_b['Invoice_Clean'] = missing_books['Invoice_Clean_P']
                    missing_b['Invoice_Original'] = missing_books['Invoice_Original_P']
                    missing_b['Supplier'] = missing_books['Trade/Legal name']
                    missing_b['Taxable_Value'] = missing_books['Taxable_P']
                    missing_b['Total_GST'] = missing_books['TotalGST_P']
                    missing_b.to_excel(writer, sheet_name='Missing_in_Books', index=False)

                # Missing in Portal sheet (present in Books only)
                if len(missing_portal) > 0:
                    missing_p = pd.DataFrame()
                    missing_p['Match_Key'] = missing_portal['Key']
                    missing_p['GSTIN'] = missing_portal['GSTIN_Clean_B']
                    missing_p['Invoice_Clean'] = missing_portal['Invoice_Clean_B']
                    missing_p['Invoice_Original'] = missing_portal['Invoice_Original_B']
                    missing_p['Vendor'] = missing_portal['VENDOR NAME']
                    missing_p['Taxable_Value'] = missing_portal['Taxable_B']
                    missing_p['Total_GST'] = missing_portal['TotalGST_B']
                    missing_p.to_excel(writer, sheet_name='Missing_in_Portal', index=False)

            output.seek(0)

            st.download_button(
                label="📥 Download Reconciliation Report",
                data=output,
                file_name="GST_Reconciliation_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

st.markdown("---")
st.markdown("**Note:** Files are processed in memory and not stored anywhere. Safe for confidential data.")
