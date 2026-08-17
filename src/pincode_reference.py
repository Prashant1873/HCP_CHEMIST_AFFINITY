import os
import urllib.request
import pandas as pd
import numpy as np

# Pincode repository raw URL
PINCODE_URL = "https://raw.githubusercontent.com/dropdevrahul/pincodes-india/main/pincode.csv"

def download_pincode_master(dest_path):
    """
    Downloads pincode.csv from dropdevrahul/pincodes-india and saves it locally.
    """
    print(f"Pincode reference not found locally. Attempting to download from {PINCODE_URL}...")
    
    # Ensure parent directory exists
    dir_name = os.path.dirname(dest_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
        
    try:
        # User-agent header to avoid blocking
        req = urllib.request.Request(
            PINCODE_URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
            data = response.read()
            out_file.write(data)
        print(f"Successfully downloaded and cached pincode master to {dest_path}")
        return True
    except Exception as e:
        print(f"Error downloading pincode master: {e}")
        return False

def load_pincode_reference(filepath):
    """
    Loads and aggregates the pincode reference CSV.
    Returns an optimized hash map (dict) for O(1) lookups.
    """
    if not os.path.exists(filepath):
        success = download_pincode_master(filepath)
        if not success:
            print("WARNING: Pincode reference file could not be loaded or downloaded. Pincode validation will be bypassed.")
            return {}
            
    print(f"Loading and indexing pincode reference data from {filepath}...")
    try:
        # Load the CSV
        df = pd.read_csv(filepath, dtype={'Pincode': str}, low_memory=False)
        
        # Clean columns
        df['Pincode'] = df['Pincode'].fillna('').astype(str).str.strip().str.zfill(6)
        df['StateName'] = df['StateName'].fillna('').astype(str).str.strip().str.upper()
        df['District'] = df['District'].fillna('').astype(str).str.strip().str.upper()
        df['OfficeName'] = df['OfficeName'].fillna('').astype(str).str.strip().str.upper()
        
        # Numeric lat/long conversion
        df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        
        # Aggregate by Pincode:
        # State: pick the most common (mode) state for the pincode
        # District: pick the most common district
        # Post Offices: join unique post office names
        # Lat/Long: calculate median coordinates
        
        agg_funcs = {
            'StateName': lambda x: x.value_counts().index[0] if len(x.value_counts()) > 0 else '',
            'District': lambda x: x.value_counts().index[0] if len(x.value_counts()) > 0 else '',
            'OfficeName': lambda x: ", ".join(sorted(list(set(x)))),
            'Latitude': 'median',
            'Longitude': 'median'
        }
        
        df_agg = df.groupby('Pincode').agg(agg_funcs).reset_index()
        
        # Build dictionary for O(1) lookup
        pincode_dict = {}
        for _, row in df_agg.iterrows():
            pin = row['Pincode']
            pincode_dict[pin] = {
                'state': row['StateName'],
                'district': row['District'],
                'post_offices': row['OfficeName'],
                'lat': row['Latitude'] if not pd.isna(row['Latitude']) else None,
                'long': row['Longitude'] if not pd.isna(row['Longitude']) else None,
                'source': 'pincodes-india GitHub'
            }
            
        print(f"Indexed {len(pincode_dict)} unique Indian pincodes successfully.")
        return pincode_dict
        
    except Exception as e:
        print(f"Error parsing pincode reference: {e}")
        return {}
