import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(page_title="GST Reconciliation", page_icon="📊", layout="wide")

st.title("📊 GST Reconciliation Tool")
st.markdown("Upload your **GSTR-2B (Portal Download)** and **Purchase Register** files to get reconciliation report")

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
            # Load files
            df_portal = pd.read_excel(portal_file)
            df_books = pd.read_excel(books_file)
            
            # Clean invoice numbers
            df_portal['Invoice_Clean'] = df_portal['Invoice number'].astype(str).str.strip().str.replace('-', '').str.replace(' ', '').str.upper()
            df_books['Invoice_Clean'] = df_books['VENDOR INVOICE NO'].astype(str).str.strip().str.replace('-', '').str.replace(' ', '').str.upper()
            
            df_portal['GSTIN_Clean'] = df_portal['GSTIN of supplier'].astype(str).str.strip().str.upper()
            df_books['GSTIN_Clean'] = df_books['VENDOR GSTIN'].astype(str).str.strip().str.upper()
            
            # Prepare amounts
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
            
            # Group duplicates
            portal_agg = {'Trade/Legal name': 'first', 'Invoice Date': 'first', 'Taxable': 'sum', 'IGST': 'sum', 'CGST': 'sum', 'SGST': 'sum', 'TotalGST': 'sum'}
            portal_grouped = df_portal.groupby(['GSTIN_Clean', 'Invoice_Clean']).agg(portal_agg).reset_index()
            
            books_agg = {'VENDOR NAME': 'first', 'DATE': 'first', 'Taxable': 'sum', 'IGST': 'sum', 'CGST': 'sum', 'SGST': 'sum', 'TotalGST': 'sum'}
            books_grouped = df_books.groupby(['GSTIN_Clean', 'Invoice_Clean']).agg(books_agg).reset_index()
            
            # Matching
            portal_grouped['Key'] = portal_grouped['GSTIN_Clean'] + '|' + portal_grouped['Invoice_Clean']
            books_grouped['Key'] = books_grouped['GSTIN_Clean'] + '|' + books_grouped['Invoice_Clean']
            
            comparison = pd.merge(portal_grouped, books_grouped, on='Key', how='outer', suffixes=('_P', '_B'), indicator=True)
            comparison['Status'] = comparison['_merge'].map({'both': 'MATCHED', 'left_only': 'MISSING_IN_BOOKS', 'right_only': 'MISSING_IN_PORTAL'})
            
            matched = comparison[comparison['Status'] == 'MATCHED'].copy()
            matched['Tax_Diff'] = abs(matched['Taxable_P'] - matched['Taxable_B'])
            matched['GST_Diff'] = abs(matched['TotalGST_P'] - matched['TotalGST_B'])
            matched['Value_Status'] = matched.apply(lambda x: 'PERFECT' if (x['Tax_Diff'] <= 1 and x['GST_Diff'] <= 1) else 'MISMATCH', axis=1)
            
            perfect = matched[matched['Value_Status'] == 'PERFECT']
            mismatch = matched[matched['Value_Status'] == 'MISMATCH']
            missing_books = comparison[comparison['Status'] == 'MISSING_IN_BOOKS']
            missing_portal = comparison[comparison['Status'] == 'MISSING_IN_PORTAL']
            
            # Display results
            st.success("✅ Reconciliation Complete!")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("✅ Perfect Match", len(perfect))
            col2.metric("⚠️ Value Mismatch", len(mismatch))
            col3.metric("❌ Missing in Books", len(missing_books))
            col4.metric("❌ Missing in Portal", len(missing_portal))
            
            # Create Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Summary Sheet
                pd.DataFrame({
                    'Category': ['Perfect Match', 'Value Mismatch', 'Missing in Books', 'Missing in Portal'], 
                    'Count': [len(perfect), len(mismatch), len(missing_books), len(missing_portal)]
                }).to_excel(writer, sheet_name='Summary', index=False)
                
                # Perfect Match Sheet
                if len(perfect) > 0:
                    perfect_export = pd.DataFrame()
                    perfect_export['GSTIN'] = perfect['GSTIN_Clean_P']
                    perfect_export['Invoice_No'] = perfect['Invoice_Clean']
                    perfect_export['Supplier'] = perfect['Trade/Legal name']
                    perfect_export['Taxable_Value'] = perfect['Taxable_P']
                    perfect_export['CGST'] = perfect['CGST_P']
                    perfect_export['SGST'] = perfect['SGST_P']
                    perfect_export['IGST'] = perfect['IGST_P']
                    perfect_export['Total_GST'] = perfect['TotalGST_P']
                    perfect_export.to_excel(writer, sheet_name='Perfect_Match', index=False)
                
                # Value Mismatch Sheet
                if len(mismatch) > 0:
                    mismatch_export = pd.DataFrame()
                    mismatch_export['GSTIN'] = mismatch['GSTIN_Clean_P']
                    mismatch_export['Invoice_No'] = mismatch['Invoice_Clean']
                    mismatch_export['Supplier'] = mismatch['Trade/Legal name']
                    mismatch_export['Taxable_Portal'] = mismatch['Taxable_P']
                    mismatch_export['Taxable_Books'] = mismatch['Taxable_B']
                    mismatch_export['Taxable_Diff'] = mismatch['Tax_Diff']
                    mismatch_export['GST_Portal'] = mismatch['TotalGST_P']
                    mismatch_export['GST_Books'] = mismatch['TotalGST_B']
                    mismatch_export['GST_Diff'] = mismatch['GST_Diff']
                    mismatch_export.to_excel(writer, sheet_name='Value_Mismatch', index=False)
                
                # Missing in Books Sheet
                if len(missing_books) > 0:
                    missing_b = pd.DataFrame()
                    missing_b['GSTIN'] = missing_books['GSTIN_Clean_P']
                    missing_b['Invoice_No'] = missing_books['Invoice_Clean']
                    missing_b['Supplier'] = missing_books['Trade/Legal name']
                    missing_b['Taxable_Value'] = missing_books['Taxable_P']
                    missing_b['Total_GST'] = missing_books['TotalGST_P']
                    missing_b.to_excel(writer, sheet_name='Missing_in_Books', index=False)
                
                # Missing in Portal Sheet
                if len(missing_portal) > 0:
                    missing_p = pd.DataFrame()
                    missing_p['GSTIN'] = missing_portal['GSTIN_Clean_B']
                    missing_p['Invoice_No'] = missing_portal['Invoice_Clean']
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
