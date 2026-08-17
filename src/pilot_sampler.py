import pandas as pd
import numpy as np

def draw_stratified_pilot_sample(df_targets, sample_size=1000):
    """
    Extracts a stratified sample of targeted records for geocoding pilots.
    Proportions:
    - 30% Missing Coordinates
    - 30% Critical City Outliers (>100km)
    - 20% Duplicate coordinate cluster centroids (>=20 count)
    - 10% Pincode mismatch + coordinate issue records
    - 10% Random high-risk records
    """
    seed = 42  # Seed for reproducible pilot sampling
    
    if len(df_targets) <= sample_size:
        print(f"Target list size ({len(df_targets)}) is smaller than requested sample size ({sample_size}). Returning full target list.")
        return df_targets.copy()
        
    # Group definitions (mutually exclusive)
    is_missing = df_targets['COORD_MISSING'] == True
    
    is_city_crit = (
        (df_targets['coordinate_issue_flags'].str.contains('COORD_CITY_MISMATCH_CRITICAL', na=False)) & 
        (~is_missing)
    )
    
    is_centroid = (
        (df_targets['duplicate_coordinate_count'] >= 20) & 
        (~is_missing) & 
        (~is_city_crit)
    )
    
    is_pin_conflict = (
        (df_targets['pincode_issue_flags'].str.contains('MISMATCH|STATE_MISMATCH', na=False)) & 
        (df_targets['coordinate_quality_score'] < 85) & 
        (~is_missing) & 
        (~is_city_crit) & 
        (~is_centroid)
    )
    
    is_other_high_risk = (
        (df_targets['routing_reliability_bucket'] == "HIGH_RISK") & 
        (~is_missing) & 
        (~is_city_crit) & 
        (~is_centroid) & 
        (~is_pin_conflict)
    )
    
    # Separate dataframes
    g1 = df_targets[is_missing]
    g2 = df_targets[is_city_crit]
    g3 = df_targets[is_centroid]
    g4 = df_targets[is_pin_conflict]
    g5 = df_targets[is_other_high_risk]
    
    # Grab remaining fallbacks if any group lacks records
    all_known_indices = pd.concat([g1, g2, g3, g4, g5])['chemist_record_index']
    g_fallback = df_targets[~df_targets['chemist_record_index'].isin(all_known_indices)]
    
    # Target allocations
    targets = {
        1: int(sample_size * 0.30),  # 30% Missing
        2: int(sample_size * 0.30),  # 30% City Outliers
        3: int(sample_size * 0.20),  # 20% Centroids
        4: int(sample_size * 0.10),  # 10% Pincode Mismatches
        5: int(sample_size * 0.10)   # 10% Other High Risk
    }
    
    selected_samples = []
    carry_over = 0
    
    groups = [(1, g1), (2, g2), (3, g3), (4, g4), (5, g5)]
    for gid, gdf in groups:
        allocated = targets[gid] + carry_over
        carry_over = 0
        
        if len(gdf) >= allocated:
            selected_samples.append(gdf.sample(n=allocated, random_state=seed))
        else:
            selected_samples.append(gdf)
            carry_over = allocated - len(gdf)
            
    # Draw from fallback pool if carry-over deficit remains
    if carry_over > 0 and len(g_fallback) > 0:
        draw_count = min(carry_over, len(g_fallback))
        selected_samples.append(g_fallback.sample(n=draw_count, random_state=seed))
        carry_over -= draw_count
        
    # If deficit still exists, draw from any other target record (duplicate check fallback)
    if carry_over > 0:
        already_selected = pd.concat(selected_samples)['chemist_record_index']
        remaining = df_targets[~df_targets['chemist_record_index'].isin(already_selected)]
        if len(remaining) > 0:
            draw_count = min(carry_over, len(remaining))
            selected_samples.append(remaining.sample(n=draw_count, random_state=seed))
            
    # Merge and verify unique records
    df_pilot = pd.concat(selected_samples).drop_duplicates(subset=['chemist_record_index'])
    
    # Print sample distribution log
    print(f"Stratified sampling results (Target: {sample_size}):")
    print(f"  - Missing coords (G1): {len(df_pilot[df_pilot['COORD_MISSING'] == True])} sampled (Target: {targets[1]})")
    print(f"  - City Outliers (G2): {len(df_pilot[df_pilot['coordinate_issue_flags'].str.contains('COORD_CITY_MISMATCH_CRITICAL', na=False)])} sampled (Target: {targets[2]})")
    print(f"  - Centroids/High duplicates (G3): {len(df_pilot[(df_pilot['duplicate_coordinate_count'] >= 20) & (~df_pilot['COORD_MISSING']) & (~df_pilot['coordinate_issue_flags'].str.contains('COORD_CITY_MISMATCH_CRITICAL', na=False))])} sampled (Target: {targets[3]})")
    
    return df_pilot
