import pandas as pd
import numpy as np
from src.utils import haversine_distance_vectorized

def validate_coordinates(df, config, pincode_ref_data=None):
    """
    Performs fully vectorized coordinate validation checks, city outlier detection,
    coordinate duplicate clustering, and calculates coordinate quality scores.
    """
    # 1. Establish basic flags
    df['COORD_MISSING'] = df['numeric_original_lat'].isna() | df['numeric_original_long'].isna()
    
    # Original string exists but conversion is NaN
    df['COORD_INVALID_FORMAT'] = (df['original_lat'] != '') & (df['original_lat'] != '-') & df['numeric_original_lat'].isna()
    df['COORD_INVALID_FORMAT'] = df['COORD_INVALID_FORMAT'] | ((df['original_long'] != '') & (df['original_long'] != '-') & df['numeric_original_long'].isna())
    
    # Outside world limits
    df['COORD_OUTSIDE_WORLD'] = (~df['COORD_MISSING']) & (
        (df['numeric_original_lat'] < -90) | (df['numeric_original_lat'] > 90) |
        (df['numeric_original_long'] < -180) | (df['numeric_original_long'] > 180)
    )
    
    # India bounding box check
    lat_min = config.india_bbox["lat_min"]
    lat_max = config.india_bbox["lat_max"]
    long_min = config.india_bbox["long_min"]
    long_max = config.india_bbox["long_max"]
    
    df['COORD_OUTSIDE_INDIA'] = (~df['COORD_MISSING']) & (
        (df['numeric_original_lat'] < lat_min) | (df['numeric_original_lat'] > lat_max) |
        (df['numeric_original_long'] < long_min) | (df['numeric_original_long'] > long_max)
    )
    
    # Lat-Long Swap Check
    # Swap check is triggered if lat is in longitude range and long is in latitude range
    df['COORD_LAT_LONG_INVERTED'] = (~df['COORD_MISSING']) & (
        (df['numeric_original_lat'] >= long_min) & (df['numeric_original_lat'] <= long_max) &
        (df['numeric_original_long'] >= lat_min) & (df['numeric_original_long'] <= lat_max)
    )
    
    df['corrected_lat_if_swapped'] = np.where(df['COORD_LAT_LONG_INVERTED'], df['numeric_original_long'], np.nan)
    df['corrected_long_if_swapped'] = np.where(df['COORD_LAT_LONG_INVERTED'], df['numeric_original_lat'], np.nan)
    
    # Determine working coordinates for routing and distance calculations
    df['working_lat'] = np.where(df['COORD_LAT_LONG_INVERTED'], df['corrected_lat_if_swapped'], df['numeric_original_lat'])
    df['working_long'] = np.where(df['COORD_LAT_LONG_INVERTED'], df['corrected_long_if_swapped'], df['numeric_original_long'])
    
    # Filter for coordinates inside India
    df['in_india_bounds'] = (~df['working_lat'].isna()) & (
        (df['working_lat'] >= lat_min) & (df['working_lat'] <= lat_max) &
        (df['working_long'] >= long_min) & (df['working_long'] <= long_max)
    )
    
    # 2. City Median Outlier Detection
    # Filter valid coordinates inside India
    valid_coords_df = df[df['in_india_bounds']].copy()
    
    if len(valid_coords_df) > 0:
        # Calculate median per normalized city
        city_medians = valid_coords_df.groupby('normalized_city')[['working_lat', 'working_long']].median().reset_index()
        city_medians.columns = ['normalized_city', 'city_median_lat', 'city_median_long']
        
        # Calculate count of valid coordinates per city
        city_counts = valid_coords_df.groupby('normalized_city').size().reset_index()
        city_counts.columns = ['normalized_city', 'city_valid_count']
        
        # Merge back
        df = df.merge(city_medians, on='normalized_city', how='left')
        df = df.merge(city_counts, on='normalized_city', how='left')
        df['city_valid_count'] = df['city_valid_count'].fillna(0).astype(int)
    else:
        df['city_median_lat'] = np.nan
        df['city_median_long'] = np.nan
        df['city_valid_count'] = 0
        
    # Calculate Haversine distance to city median centroid
    has_median = df['working_lat'].notna() & df['city_median_lat'].notna()
    df['dist_to_city_median'] = np.nan
    if has_median.any():
        df.loc[has_median, 'dist_to_city_median'] = haversine_distance_vectorized(
            df.loc[has_median, 'working_lat'], df.loc[has_median, 'working_long'],
            df.loc[has_median, 'city_median_lat'], df.loc[has_median, 'city_median_long']
        )
        
    # Set outliers (minimum sample size of 5 for statistics)
    df['COORD_CITY_MISMATCH_WARNING'] = (df['city_valid_count'] >= 5) & (df['dist_to_city_median'] > config.city_outlier_warning_km)
    df['COORD_CITY_MISMATCH_CRITICAL'] = (df['city_valid_count'] >= 5) & (df['dist_to_city_median'] > config.city_outlier_critical_km)
    df['COORD_CITY_MISMATCH'] = df['COORD_CITY_MISMATCH_CRITICAL'] | df['COORD_CITY_MISMATCH_WARNING']
    
    # 3. Duplicate Coordinate Cluster Detection
    df['rounded_lat'] = df['working_lat'].round(6)
    df['rounded_long'] = df['working_long'].round(6)
    
    # Combine coordinate strings
    has_coords = df['working_lat'].notna()
    df['coord_key'] = ""
    df.loc[has_coords, 'coord_key'] = df.loc[has_coords, 'rounded_lat'].astype(str) + "," + df.loc[has_coords, 'rounded_long'].astype(str)
    
    # Group coordinates
    coord_counts = df[has_coords].groupby('coord_key').size().reset_index()
    coord_counts.columns = ['coord_key', 'duplicate_coordinate_count']
    
    df = df.merge(coord_counts, on='coord_key', how='left')
    df['duplicate_coordinate_count'] = df['duplicate_coordinate_count'].fillna(0).astype(int)
    
    # Assign duplicate cluster levels
    df['COORD_DUPLICATE_CLUSTER'] = (df['duplicate_coordinate_count'] >= config.duplicate_coordinate_threshold) & (df['duplicate_coordinate_count'] < config.duplicate_coordinate_high_threshold)
    df['COORD_DUPLICATE_CLUSTER_HIGH'] = (df['duplicate_coordinate_count'] >= config.duplicate_coordinate_high_threshold)
    df['COORD_DUPLICATE_CLUSTER_CRITICAL'] = (df['duplicate_coordinate_count'] >= config.duplicate_coordinate_centroid_threshold)
    
    # Set cluster labels
    df['duplicate_coordinate_cluster_level'] = "NONE"
    df.loc[df['duplicate_coordinate_count'] >= config.duplicate_coordinate_threshold, 'duplicate_coordinate_cluster_level'] = "LOW"
    df.loc[df['duplicate_coordinate_count'] >= config.duplicate_coordinate_high_threshold, 'duplicate_coordinate_cluster_level'] = "HIGH"
    df.loc[df['duplicate_coordinate_count'] >= config.duplicate_coordinate_centroid_threshold, 'duplicate_coordinate_cluster_level'] = "CENTROID"

    # 4. Centroid Suspicion (Pincode & City)
    # City centroid suspicion: rounded working coordinates match the city median exactly
    # and duplicate cluster is high (>= 20)
    df['COORD_CITY_CENTROID_SUSPECTED'] = False
    is_city_centroid = (
        (~df['working_lat'].isna()) & 
        (~df['city_median_lat'].isna()) & 
        (df['working_lat'].round(4) == df['city_median_lat'].round(4)) & 
        (df['working_long'].round(4) == df['city_median_long'].round(4)) &
        (df['duplicate_coordinate_count'] >= config.duplicate_coordinate_high_threshold)
    )
    df.loc[is_city_centroid, 'COORD_CITY_CENTROID_SUSPECTED'] = True
    
    # Pincode centroid suspicion: if reference data exists and working coordinates match the reference pincode coordinates exactly
    # and duplicate count >= 5
    df['COORD_PINCODE_CENTROID_SUSPECTED'] = False
    
    if pincode_ref_data:
        # Vectorized lookup for pincode coordinates
        # Map validated pincode from reference database
        ref_lat_map = {k: v['lat'] for k, v in pincode_ref_data.items() if v['lat'] is not None}
        ref_long_map = {k: v['long'] for k, v in pincode_ref_data.items() if v['long'] is not None}
        
        df['ref_pin_lat'] = df['original_pincode'].map(ref_lat_map)
        df['ref_pin_long'] = df['original_pincode'].map(ref_long_map)
        
        is_pin_centroid = (
            (~df['working_lat'].isna()) &
            (~df['ref_pin_lat'].isna()) &
            (df['working_lat'].round(4) == df['ref_pin_lat'].round(4)) &
            (df['working_long'].round(4) == df['ref_pin_long'].round(4)) &
            (df['duplicate_coordinate_count'] >= config.duplicate_coordinate_threshold)
        )
        df.loc[is_pin_centroid, 'COORD_PINCODE_CENTROID_SUSPECTED'] = True
        
        # Cleanup temp columns
        df = df.drop(columns=['ref_pin_lat', 'ref_pin_long'])
        
    df['COORD_CENTROID_SUSPECTED'] = df['COORD_CITY_CENTROID_SUSPECTED'] | df['COORD_PINCODE_CENTROID_SUSPECTED'] | df['COORD_DUPLICATE_CLUSTER_CRITICAL']
    
    # 5. Pincode Mismatch check (if pincode reference coordinates are far from working coordinates)
    df['COORD_PINCODE_MISMATCH'] = False
    if pincode_ref_data:
        ref_lat_map = {k: v['lat'] for k, v in pincode_ref_data.items() if v['lat'] is not None}
        ref_long_map = {k: v['long'] for k, v in pincode_ref_data.items() if v['long'] is not None}
        df['ref_pin_lat'] = df['original_pincode'].map(ref_lat_map)
        df['ref_pin_long'] = df['original_pincode'].map(ref_long_map)
        
        has_pin_coords = df['working_lat'].notna() & df['ref_pin_lat'].notna()
        df['dist_to_pincode'] = np.nan
        if has_pin_coords.any():
            df.loc[has_pin_coords, 'dist_to_pincode'] = haversine_distance_vectorized(
                df.loc[has_pin_coords, 'working_lat'], df.loc[has_pin_coords, 'working_long'],
                df.loc[has_pin_coords, 'ref_pin_lat'], df.loc[has_pin_coords, 'ref_pin_long']
            )
            # Flag mismatch if distance > 15 km (since pincodes are small)
            df.loc[has_pin_coords & (df['dist_to_pincode'] > 15.0), 'COORD_PINCODE_MISMATCH'] = True
            
        df = df.drop(columns=['ref_pin_lat', 'ref_pin_long'])
        
    # State mismatch for coordinates
    df['COORD_STATE_MISMATCH'] = False
    # If state name and pincode state mismatch, coordinates might match state or not.
    # We will check city mismatch critical as a proxy since we already calculated city distance.
    
    # 6. Score Calculation
    df['coordinate_quality_score'] = 100
    
    # Apply deductions
    df.loc[df['COORD_MISSING'], 'coordinate_quality_score'] -= 50
    df.loc[df['COORD_INVALID_FORMAT'], 'coordinate_quality_score'] -= 50
    df.loc[df['COORD_OUTSIDE_WORLD'], 'coordinate_quality_score'] -= 50
    df.loc[df['COORD_OUTSIDE_INDIA'], 'coordinate_quality_score'] -= 50
    
    # Outlier deductions
    df.loc[df['COORD_CITY_MISMATCH_CRITICAL'], 'coordinate_quality_score'] -= 40
    # Deduct only warning if not already deducted critical
    df.loc[df['COORD_CITY_MISMATCH_WARNING'] & ~df['COORD_CITY_MISMATCH_CRITICAL'], 'coordinate_quality_score'] -= 25
    
    # Pincode mismatch
    df.loc[df['COORD_PINCODE_MISMATCH'], 'coordinate_quality_score'] -= 30
    
    # Duplicate cluster deductions
    df.loc[df['COORD_DUPLICATE_CLUSTER_CRITICAL'], 'coordinate_quality_score'] -= 40
    df.loc[df['COORD_DUPLICATE_CLUSTER_HIGH'] & ~df['COORD_DUPLICATE_CLUSTER_CRITICAL'], 'coordinate_quality_score'] -= 25
    df.loc[df['COORD_DUPLICATE_CLUSTER'] & ~df['COORD_DUPLICATE_CLUSTER_HIGH'] & ~df['COORD_DUPLICATE_CLUSTER_CRITICAL'], 'coordinate_quality_score'] -= 15
    
    # Centroid / inversion deductions
    df.loc[df['COORD_CENTROID_SUSPECTED'], 'coordinate_quality_score'] -= 20
    df.loc[df['COORD_LAT_LONG_INVERTED'], 'coordinate_quality_score'] -= 15  # lat-long swap detected (but we will correct it)
    
    df['coordinate_quality_score'] = df['coordinate_quality_score'].clip(lower=0, upper=100)
    
    # 7. Aggregate flags into a string column
    def make_coord_flags(row):
        flg = []
        if row['COORD_MISSING']: flg.append('COORD_MISSING')
        if row['COORD_INVALID_FORMAT']: flg.append('COORD_INVALID_FORMAT')
        if row['COORD_OUTSIDE_WORLD']: flg.append('COORD_OUTSIDE_WORLD')
        if row['COORD_OUTSIDE_INDIA']: flg.append('COORD_OUTSIDE_INDIA')
        if row['COORD_LAT_LONG_INVERTED']: flg.append('COORD_LAT_LONG_INVERTED')
        if row['COORD_CITY_MISMATCH_CRITICAL']: flg.append('COORD_CITY_MISMATCH_CRITICAL')
        elif row['COORD_CITY_MISMATCH_WARNING']: flg.append('COORD_CITY_MISMATCH_WARNING')
        if row['COORD_STATE_MISMATCH']: flg.append('COORD_STATE_MISMATCH')
        if row['COORD_PINCODE_MISMATCH']: flg.append('COORD_PINCODE_MISMATCH')
        if row['COORD_DUPLICATE_CLUSTER_CRITICAL']: flg.append('COORD_CENTROID_SUSPECTED')
        elif row['COORD_DUPLICATE_CLUSTER_HIGH']: flg.append('COORD_DUPLICATE_CLUSTER_HIGH')
        elif row['COORD_DUPLICATE_CLUSTER']: flg.append('COORD_DUPLICATE_CLUSTER')
        if row['COORD_CITY_CENTROID_SUSPECTED']: flg.append('COORD_CITY_CENTROID_SUSPECTED')
        if row['COORD_PINCODE_CENTROID_SUSPECTED']: flg.append('COORD_PINCODE_CENTROID_SUSPECTED')
        
        # Geocode flag required if score is low or coordinates are problematic
        if row['COORD_MISSING'] or row['COORD_INVALID_FORMAT'] or row['COORD_OUTSIDE_INDIA'] or row['COORD_CITY_MISMATCH_CRITICAL'] or row['COORD_DUPLICATE_CLUSTER_HIGH']:
            flg.append('REGEOCODE_REQUIRED')
            
        return ", ".join(flg) if flg else ""
        
    df['coordinate_issue_flags'] = df.apply(make_coord_flags, axis=1)
    
    return df
