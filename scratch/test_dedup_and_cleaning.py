import pandas as pd
import numpy as np
import re
from difflib import SequenceMatcher

def clean_str(s):
    if pd.isna(s): return ""
    s = str(s).upper()
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def normalize_store_name(name):
    s = clean_str(name)
    # Remove generic suffixes for deduplication comparison
    suffixes = [
        'MEDICAL AND GENERAL STORE', 'MEDICAL & GENERAL STORE', 'MEDICAL & GEN STORE',
        'MEDICAL AND GEN STORE', 'MEDICAL & GENERAL STORES', 'MEDICAL AND GENERAL STORES',
        'MEDICAL & GEN STORES', 'MEDICAL GEN STORES', 'MEDICAL STORE', 'MEDICAL STORES',
        'MED & GEN STORE', 'MED GEN STORE', 'MED & GEN STORES', 'MED GEN STORES',
        'CHEMIST & DRUGGIST', 'CHEMISTS & DRUGGISTS', 'CHEMIST AND DRUGGIST',
        'CHEMISTS', 'CHEMIST', 'DRUGGISTS', 'DRUGGIST', 'PHARMACY', 'PHARMACIES',
        'MEDICO', 'MEDICOS', 'MEDICALS', 'MEDICAL', 'STORE', 'STORES', 'AGENCY', 'AGENCIES',
        'PVT LTD', 'LTD', 'PROP', 'M S'
    ]
    for suf in sorted(suffixes, key=len, reverse=True):
        if s.endswith(' ' + suf) or s == suf:
            s = s[:-len(suf)].strip()
    return s

def string_sim(a, b):
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()

df = pd.read_excel('Chemist_test_HCM.xlsx')
mumbai = df[df['chem_city'].astype(str).str.upper() == 'MUMBAI'].copy()
print(f"Loaded {len(mumbai)} Mumbai chemists.")

mumbai['norm_name'] = mumbai['chem_name'].apply(normalize_store_name)
mumbai['clean_addr'] = mumbai['chem_address'].apply(clean_str)
mumbai['clean_pin'] = mumbai['chem_pincode'].astype(str).str.split('.').str[0].str.zfill(6)

# Test 1: Exact Lat/Lon with Similar Normalized Name
exact_loc_groups = mumbai.groupby(['chem_lat', 'chem_long'])
print(f"Total unique coordinate pairs in Mumbai: {len(exact_loc_groups)}")

same_loc_same_store = 0
same_loc_diff_store = 0
large_cluster_stores = 0

for (lat, lon), grp in exact_loc_groups:
    if len(grp) == 1:
        continue
    if len(grp) > 5:
        large_cluster_stores += len(grp)
        continue
    # Check pairwise name similarity within the location
    names = grp['norm_name'].tolist()
    is_same = False
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            if string_sim(names[i], names[j]) > 0.75 or names[i] == names[j] or names[i] in names[j] or names[j] in names[i]:
                is_same = True
                break
    if is_same:
        same_loc_same_store += len(grp)
    else:
        same_loc_diff_store += len(grp)

print(f"Same Coordinates + Highly Similar Store Name (Multi-IQVIA duplicates): ~{same_loc_same_store} records")
print(f"Same Coordinates + Different Store Name (Small co-location / shared address): ~{same_loc_diff_store} records")
print(f"Suspicious Large Coordinate Clusters (> 5 unrelated chemists at exact same point): {large_cluster_stores} records")

# Test 2: Same Pincode + Near Identical Store Name
pin_groups = mumbai.groupby('clean_pin')
duplicate_across_pins = 0
for pin, grp in pin_groups:
    if len(grp) <= 1: continue
    sorted_names = grp.sort_values('norm_name')
    # check consecutive
    prev_row = None
    for idx, row in sorted_names.iterrows():
        if prev_row is not None:
            n1 = prev_row['norm_name']
            n2 = row['norm_name']
            if n1 and n2 and (n1 == n2 or string_sim(n1, n2) > 0.85):
                duplicate_across_pins += 1
        prev_row = row

print(f"Same Pincode + Near Identical Store Name: {duplicate_across_pins} pairs/records")
