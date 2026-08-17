import pandas as pd
import numpy as np

def identify_geocoding_targets(df):
    """
    Selects records that require geocoding based on missing/wrong coordinates,
    city outliers, duplicate centroids, or overall low quality.
    Adds 'geocoding_required_reason' and 'geocoding_priority' columns.
    """
    targets_mask = pd.Series(False, index=df.index)
    reasons = []
    
    # 1. No Usable Coordinate / Missing
    is_missing = (df['coordinate_source'] == "NO_USABLE_COORDINATE") | (df['COORD_MISSING'] == True)
    
    # 2. High Risk Reliability
    is_high_risk = df['routing_reliability_bucket'] == "HIGH_RISK"
    
    # 3. Critical city mismatch outlier (>100 km)
    is_city_crit = df['coordinate_issue_flags'].str.contains('COORD_CITY_MISMATCH_CRITICAL', na=False)
    
    # 4. Outside India
    is_outside_india = df['coordinate_issue_flags'].str.contains('COORD_OUTSIDE_INDIA', na=False)
    
    # 5. Centroid Suspected
    is_centroid = df['coordinate_issue_flags'].str.contains('COORD_CENTROID_SUSPECTED|COORD_CITY_CENTROID_SUSPECTED|COORD_PINCODE_CENTROID_SUSPECTED', na=False)
    
    # 6. Duplicate cluster high (>=20)
    is_dup_high = df['coordinate_issue_flags'].str.contains('COORD_DUPLICATE_CLUSTER_HIGH', na=False)
    
    # 7. Extreme duplicate coordinate cluster count (>=100)
    is_dup_100 = df['duplicate_coordinate_count'] >= 100
    
    # 8. Low coordinate quality score (<40)
    is_low_coord_score = df['coordinate_quality_score'] < 40
    
    # 9. Low overall location confidence score (<65)
    is_low_overall_score = df['overall_location_confidence_score'] < 65
    
    # 10. Address/Pincode Mismatch suggests coordinate may be wrong
    is_pin_conflict = df['pincode_issue_flags'].str.contains('PINCODE_STATE_MISMATCH', na=False)
    is_coord_pin_conflict = df['coordinate_issue_flags'].str.contains('COORD_PINCODE_MISMATCH', na=False)
    has_conflict = (is_pin_conflict | is_coord_pin_conflict) & (df['coordinate_quality_score'] < 85)

    # Combine masks
    targets_mask = (
        is_missing | is_high_risk | is_city_crit | is_outside_india | 
        is_centroid | is_dup_high | is_dup_100 | is_low_coord_score | 
        is_low_overall_score | has_conflict
    )
    
    df_targets = df[targets_mask].copy()
    
    if len(df_targets) == 0:
        df_targets['geocoding_required_reason'] = ""
        df_targets['geocoding_priority'] = ""
        return df_targets
        
    # Helper to calculate reasons and priority for each row
    reasons_list = []
    priorities_list = []
    
    # Vectorized reasoning for speed on 145k+ records
    for i, row in df_targets.iterrows():
        r = []
        # Reasons mapping
        if row['COORD_MISSING'] or row['coordinate_source'] == "NO_USABLE_COORDINATE":
            r.append("COORD_MISSING")
        if "COORD_OUTSIDE_INDIA" in str(row['coordinate_issue_flags']):
            r.append("COORD_OUTSIDE_INDIA")
        if "COORD_CITY_MISMATCH_CRITICAL" in str(row['coordinate_issue_flags']):
            r.append("COORD_CITY_MISMATCH_CRITICAL")
        if "COORD_CITY_CENTROID_SUSPECTED" in str(row['coordinate_issue_flags']) or "COORD_PINCODE_CENTROID_SUSPECTED" in str(row['coordinate_issue_flags']) or "COORD_CENTROID_SUSPECTED" in str(row['coordinate_issue_flags']):
            r.append("COORD_CENTROID_SUSPECTED")
        if row['duplicate_coordinate_count'] >= 100:
            r.append("EXTREME_DUPLICATE_CLUSTER")
        elif "COORD_DUPLICATE_CLUSTER_HIGH" in str(row['coordinate_issue_flags']):
            r.append("COORD_DUPLICATE_CLUSTER_HIGH")
        if row['coordinate_quality_score'] < 40:
            r.append("LOW_COORD_SCORE")
        if row['overall_location_confidence_score'] < 65:
            r.append("LOW_OVERALL_SCORE")
        if "PINCODE_STATE_MISMATCH" in str(row['pincode_issue_flags']) or "COORD_PINCODE_MISMATCH" in str(row['coordinate_issue_flags']):
            r.append("PINCODE_LOCATION_CONFLICT")
            
        reasons_str = ", ".join(r) if r else "LOW_CONFIDENCE_FLAGGED"
        reasons_list.append(reasons_str)
        
        # Priority mapping
        # P1_CRITICAL: missing coordinates, coordinate outside India, severe city mismatch >100 km, or no usable coordinate
        if (row['COORD_MISSING'] or row['coordinate_source'] == "NO_USABLE_COORDINATE" or 
            "COORD_OUTSIDE_INDIA" in str(row['coordinate_issue_flags']) or 
            "COORD_CITY_MISMATCH_CRITICAL" in str(row['coordinate_issue_flags'])):
            priorities_list.append("P1_CRITICAL")
            
        # P2_HIGH: high-risk records with coordinates, duplicate coordinate cluster >=100, centroid suspected, or pincode-state mismatch plus coordinate issue
        elif (row['routing_reliability_bucket'] == "HIGH_RISK" or 
              row['duplicate_coordinate_count'] >= 100 or 
              "COORD_CENTROID_SUSPECTED" in str(row['coordinate_issue_flags']) or 
              ("PINCODE_STATE_MISMATCH" in str(row['pincode_issue_flags']) and row['coordinate_quality_score'] < 85)):
            priorities_list.append("P2_HIGH")
            
        # P3_MEDIUM: duplicate coordinate cluster >=20, city mismatch warning >50 km, or low overall score but usable coordinates
        elif (row['duplicate_coordinate_count'] >= 20 or 
              "COORD_CITY_MISMATCH_WARNING" in str(row['coordinate_issue_flags']) or 
              row['overall_location_confidence_score'] < 65):
            priorities_list.append("P3_MEDIUM")
            
        # P4_LOW: medium confidence records with minor warnings
        else:
            priorities_list.append("P4_LOW")
            
    df_targets['geocoding_required_reason'] = reasons_list
    df_targets['geocoding_priority'] = priorities_list
    
    return df_targets
