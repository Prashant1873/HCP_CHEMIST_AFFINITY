import pandas as pd
import numpy as np

def apply_safe_corrections(df):
    """
    Applies the correction engine logic. Assigns final coordinates, coordinate source,
    recommended action, routing eligibility, and manual review priority.
    """
    # 1. Initialize final coordinate columns and coordinate source
    df['final_lat'] = np.nan
    df['final_long'] = np.nan
    df['coordinate_source'] = "NO_USABLE_COORDINATE"
    
    # Identify records with swapped coordinates
    is_swapped = df['COORD_LAT_LONG_INVERTED'] == True
    
    # Identify records where geocoding results exist
    has_geocoding = df['geocoding_attempted_flag'] == True
    geocode_success = has_geocoding & (~df['geocoding_result_lat'].isna()) & (~df['geocoding_result_long'].isna())
    
    # Assign final coordinates using precedence:
    # A. If geocoded coordinate is available (meaning original coordinates were missing or corrected)
    # B. If lat-long was swapped and corrected
    # C. Else use original numeric coordinates if available
    
    # Calculate for each row
    for i, row in df.iterrows():
        lat = np.nan
        lon = np.nan
        source = "NO_USABLE_COORDINATE"
        
        # Check if original coordinate exists and has no critical issues
        orig_lat = row['numeric_original_lat']
        orig_long = row['numeric_original_long']
        has_orig = not pd.isna(orig_lat) and not pd.isna(orig_long)
        
        # Determine if original is "clean"
        is_clean_orig = has_orig and (row['coordinate_quality_score'] >= 85.0) and (not row['COORD_OUTSIDE_INDIA'])
        is_acceptable_orig = has_orig and (row['coordinate_quality_score'] >= 40.0) and (not row['COORD_OUTSIDE_INDIA'])
        
        if row['geocoding_attempted_flag'] and not pd.isna(row['geocoding_result_lat']):
            lat = row['geocoding_result_lat']
            lon = row['geocoding_result_long']
            q_type = row.get('geocoding_result_type', '')
            
            if q_type == 'full_address_name':
                source = "REGEOCODED_FULL_ADDRESS"
            elif q_type == 'full_address':
                source = "REGEOCODED_CLEAN_ADDRESS"
            elif q_type == 'locality_city':
                source = "REGEOCODED_LOCALITY_CITY_PINCODE"
            else:
                source = "PINCODE_CENTROID_FALLBACK"
                
        elif row['COORD_LAT_LONG_INVERTED']:
            lat = row['corrected_lat_if_swapped']
            lon = row['corrected_long_if_swapped']
            source = "ORIGINAL_CORRECTED_LATLONG_SWAP"
            
        elif has_orig:
            lat = orig_lat
            lon = orig_long
            if is_clean_orig:
                source = "ORIGINAL_ACCEPTED_HIGH_CONFIDENCE"
            else:
                source = "ORIGINAL_ACCEPTED_WITH_FLAGS"
                
        df.at[i, 'final_lat'] = lat
        df.at[i, 'final_long'] = lon
        df.at[i, 'coordinate_source'] = source

    # 2. Recommended Action Logic
    df['recommended_action'] = "MANUAL_REVIEW_REQUIRED"
    
    # Conditions
    is_high = df['quality_bucket'] == "HIGH"
    is_medium = df['quality_bucket'] == "MEDIUM"
    is_low = df['quality_bucket'] == "LOW"
    is_critical = df['quality_bucket'] == "CRITICAL"
    
    # Check flags
    has_coord_issue = df['COORD_MISSING'] | df['COORD_INVALID_FORMAT'] | df['COORD_OUTSIDE_INDIA']
    has_city_outlier_crit = df['COORD_CITY_MISMATCH_CRITICAL']
    has_pin_state_mismatch = df['pincode_issue_flags'].str.contains('PINCODE_STATE_MISMATCH').fillna(False)
    has_addr_crit = df['address_issue_flags'].str.contains('ADDRESS_MISSING|ADDRESS_TOO_SHORT|ADDRESS_GENERIC').fillna(False)
    
    # Assign actions
    df.loc[is_high, 'recommended_action'] = "KEEP"
    df.loc[is_medium, 'recommended_action'] = "KEEP_WITH_FLAG"
    
    # Auto-corrected action
    is_autocorrected = (
        (df['coordinate_source'] == "ORIGINAL_CORRECTED_LATLONG_SWAP") |
        (df['city_state_normalization_flags'].str.contains('CITY_NORMALIZED|STATE_NORMALIZED').fillna(False)) |
        (df['pincode_status'] == "VALID_BUT_ADDRESS_MISMATCH")
    )
    df.loc[is_autocorrected & (is_high | is_medium), 'recommended_action'] = "AUTO_CORRECTED"
    
    # Specific reviews based on main issue
    df.loc[has_coord_issue, 'recommended_action'] = "REGEOCODE_REQUIRED"
    df.loc[has_pin_state_mismatch, 'recommended_action'] = "PINCODE_REVIEW_REQUIRED"
    df.loc[has_addr_crit, 'recommended_action'] = "ADDRESS_REVIEW_REQUIRED"
    df.loc[has_city_outlier_crit, 'recommended_action'] = "COORDINATE_REVIEW_REQUIRED"
    
    # Severe combinations
    multiple_severe = (
        (has_coord_issue.astype(int) + has_pin_state_mismatch.astype(int) + has_addr_crit.astype(int) + has_city_outlier_crit.astype(int)) >= 2
    )
    df.loc[multiple_severe | is_critical, 'recommended_action'] = "MANUAL_REVIEW_REQUIRED"
    
    # No usable coordinates
    no_coords = df['final_lat'].isna() | df['final_long'].isna()
    df.loc[no_coords, 'recommended_action'] = "NO_USABLE_COORDINATE"
    
    # 3. Routing Eligibility Logic
    df['eligible_for_routing_flag'] = False
    
    # Eligible if coordinates are present, valid numbers, and not completely out of world limits
    valid_final_coords = (
        (~df['final_lat'].isna()) & 
        (~df['final_long'].isna()) &
        (df['final_lat'] >= -90.0) & (df['final_lat'] <= 90.0) &
        (df['final_long'] >= -180.0) & (df['final_long'] <= 180.0)
    )
    df.loc[valid_final_coords, 'eligible_for_routing_flag'] = True

    # 3.5. Business Routing Reliability & Risk Classification
    # Identify severe coordinate issues that increase risk regardless of quality score
    has_severe_coord = (
        (df['COORD_OUTSIDE_INDIA'] == True) |
        (df['COORD_CITY_MISMATCH_CRITICAL'] == True) |
        (df['COORD_CENTROID_SUSPECTED'] == True) |
        (df['COORD_DUPLICATE_CLUSTER_HIGH'] == True)
    )
    
    df['routing_reliability_bucket'] = "HIGH_RISK"
    
    # Apply rules
    df.loc[is_high & (~has_severe_coord) & (df['eligible_for_routing_flag'] == True), 'routing_reliability_bucket'] = "HIGH_RELIABILITY"
    df.loc[is_medium & (~has_severe_coord) & (df['eligible_for_routing_flag'] == True), 'routing_reliability_bucket'] = "MODERATE_RELIABILITY"
    df.loc[is_low & (~has_severe_coord) & (df['eligible_for_routing_flag'] == True), 'routing_reliability_bucket'] = "LOW_RELIABILITY"
    df.loc[is_critical | has_severe_coord | (df['eligible_for_routing_flag'] == False), 'routing_reliability_bucket'] = "HIGH_RISK"
    
    # Map to action / risk flags
    df['routing_risk_flag'] = "REVIEW_BEFORE_USE"
    df.loc[df['routing_reliability_bucket'] == "HIGH_RELIABILITY", 'routing_risk_flag'] = "USE"
    df.loc[df['routing_reliability_bucket'] == "MODERATE_RELIABILITY", 'routing_risk_flag'] = "USE_WITH_CAUTION"
    
    # 4. Manual Review Priority
    df['manual_review_priority'] = "NONE"
    
    # P1_CRITICAL: CRITICAL quality bucket, or MANUAL_REVIEW_REQUIRED, or multiple severe issues
    is_p1 = is_critical | (df['recommended_action'] == "MANUAL_REVIEW_REQUIRED") | multiple_severe
    df.loc[is_p1, 'manual_review_priority'] = "P1_CRITICAL"
    
    # P2_HIGH_RISK: LOW quality bucket, or coordinate mismatch critical, or geocode mismatch with original
    # (If geocoded lat/long differs significantly from original)
    dist_diff = np.nan
    has_both_latlong = (~df['numeric_original_lat'].isna()) & (~df['geocoding_result_lat'].isna())
    if has_both_latlong.any():
        from src.utils import haversine_distance_vectorized
        dist_diff = haversine_distance_vectorized(
            df['numeric_original_lat'], df['numeric_original_long'],
            df['geocoding_result_lat'], df['geocoding_result_long']
        )
    is_p2 = (~is_p1) & (is_low | has_city_outlier_crit | (dist_diff > 2.0))
    df.loc[is_p2, 'manual_review_priority'] = "P2_HIGH_RISK"
    
    # P3_MEDIUM_RISK: MEDIUM quality bucket, or pincode-state mismatch, or high coordinate duplicates count >= 20
    is_p3 = (~is_p1) & (~is_p2) & (is_medium | has_pin_state_mismatch | (df['duplicate_coordinate_count'] >= 20))
    df.loc[is_p3, 'manual_review_priority'] = "P3_MEDIUM_RISK"
    
    # P4_LOW_RISK: Other minor warnings
    is_p4 = (~is_p1) & (~is_p2) & (~is_p3) & (
        df['COORD_CITY_MISMATCH_WARNING'] | 
        df['address_issue_flags'].str.contains('ADDRESS_WEAK|ADDRESS_GENERIC').fillna(False) |
        (df['duplicate_coordinate_count'] >= 5)
    )
    df.loc[is_p4, 'manual_review_priority'] = "P4_LOW_RISK"
    
    # Keep NONE for perfect keeps
    df.loc[df['recommended_action'] == "KEEP", 'manual_review_priority'] = "NONE"
    
    return df
