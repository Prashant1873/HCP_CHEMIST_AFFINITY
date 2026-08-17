import pandas as pd
import numpy as np

def compute_overall_confidence(row):
    """
    Computes overall location confidence score based on component scores and geocoding validation.
    """
    addr_score = row.get('address_quality_score', 100.0)
    pin_score = row.get('pincode_quality_score', 100.0)
    coord_score = row.get('coordinate_quality_score', 100.0)
    
    geo_attempted = row.get('geocoding_attempted_flag', False)
    rev_attempted = row.get('reverse_geocode_attempted_flag', False)
    
    # Check if geocoding or reverse geocoding validation is present
    if geo_attempted or rev_attempted:
        geo_val_score = 0.0
        
        geo_conf = row.get('geocoding_confidence_score', 0.0)
        # Convert 0-1 geocoding confidence to 0-100 scale
        if not pd.isna(geo_conf):
            geo_conf = geo_conf * 100.0
        else:
            geo_conf = 0.0
            
        rev_conf = row.get('reverse_geocode_match_score', 0.0)
        if pd.isna(rev_conf):
            rev_conf = 0.0
            
        if geo_attempted and rev_attempted:
            geo_val_score = (geo_conf + rev_conf) / 2.0
        elif geo_attempted:
            geo_val_score = geo_conf
        else:
            geo_val_score = rev_conf
            
        overall = (coord_score * 0.45) + (pin_score * 0.25) + (addr_score * 0.25) + (geo_val_score * 0.05)
    else:
        # Redistribute 5% to Address (2.5%) and Pincode (2.5%)
        overall = (coord_score * 0.45) + (pin_score * 0.275) + (addr_score * 0.275)
        
    return float(np.clip(overall, 0.0, 100.0))

def assign_quality_bucket(score):
    """
    Categorizes the overall location confidence score into a quality bucket.
    """
    if pd.isna(score):
        return "CRITICAL"
    if score >= 85.0:
        return "HIGH"
    elif score >= 65.0:
        return "MEDIUM"
    elif score >= 40.0:
        return "LOW"
    else:
        return "CRITICAL"

def calculate_confidence_scores(df):
    """
    Applies score calculations and quality bucket assignments to the entire dataframe.
    """
    df['overall_location_confidence_score'] = df.apply(compute_overall_confidence, axis=1)
    df['quality_bucket'] = df['overall_location_confidence_score'].apply(assign_quality_bucket)
    return df
