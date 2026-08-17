import pandas as pd
import numpy as np
import re

df = pd.read_excel('Chemist_test_HCM.xlsx')
mumbai = df[df['chem_city'].astype(str).str.upper() == 'MUMBAI'].copy()

# Look at coordinate clustering in Mumbai
mumbai_coords = mumbai.groupby(['chem_lat', 'chem_long']).agg({
    'IQVIA ID': ['count', list],
    'chem_name': list,
    'chem_address': list,
    'chem_pincode': list
}).reset_index()

mumbai_coords.columns = ['lat', 'lon', 'count', 'ids', 'names', 'addresses', 'pincodes']
mumbai_coords = mumbai_coords.sort_values('count', ascending=False)

print('=== Top Coordinate Clusters in Mumbai ===')
for _, r in mumbai_coords.head(12).iterrows():
    print(f"Coord ({r['lat']}, {r['lon']}) -> {r['count']} entries:")
    for i in range(min(5, r['count'])):
        print(f"   [{r['ids'][i]}] Name: '{r['names'][i]}' -- Addr: '{str(r['addresses'][i])[:45]}' -- Pin: {r['pincodes'][i]}")
    print()
