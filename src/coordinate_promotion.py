import pandas as pd
import numpy as np
import time

def calculate_proposed_fields(df):
    """
    Computes proposed coordinate, source, reliability bucket, risk flag, and score 
    columns for every target record based on the acceptance decision.
    """
    df['proposed_final_lat'] = df['final_lat']
    df['proposed_final_long'] = df['final_long']
    df['proposed_coordinate_source'] = df['coordinate_source']
    df['proposed_routing_reliability_bucket'] = df['routing_reliability_bucket']
    df['proposed_routing_risk_flag'] = df['routing_risk_flag']
    df['proposed_overall_location_confidence_score'] = df['overall_location_confidence_score']
    
    for idx, row in df.iterrows():
        decision = row.get('geocoding_acceptance_decision', '')
        
        if decision in ["ACCEPT_REPLACE_FINAL_COORDS", "ACCEPT_WITH_CAUTION", "PINCODE_CENTROID_ONLY"]:
            # Coordinate replaced by candidate geocode
            lat = row['geocoding_result_lat']
            lon = row['geocoding_result_long']
            precision = row['geocoding_result_type']
            
            df.at[idx, 'proposed_final_lat'] = lat
            df.at[idx, 'proposed_final_long'] = lon
            
            # Map source code
            if precision in ["SHOP_LEVEL", "BUILDING_LEVEL"]:
                src = "REGEOCODED_FULL_ADDRESS"
            elif precision == "STREET_LEVEL":
                src = "REGEOCODED_CLEAN_ADDRESS"
            elif precision == "LOCALITY_LEVEL":
                src = "REGEOCODED_LOCALITY_CITY_PINCODE"
            else:
                src = "PINCODE_CENTROID_FALLBACK"
                
            df.at[idx, 'proposed_coordinate_source'] = src
            
            # Calculate new confidence score
            # 25% Address Score + 25% Pincode Score + 50% Coordinate Precision Base
            addr_score = row.get('address_quality_score', 100.0)
            pin_score = row.get('pincode_quality_score', 100.0)
            
            coord_base = 50.0
            if precision in ["SHOP_LEVEL", "BUILDING_LEVEL"]:
                coord_base = 95.0
            elif precision == "STREET_LEVEL":
                coord_base = 85.0
            elif precision == "LOCALITY_LEVEL":
                coord_base = 65.0
            elif precision == "PINCODE_LEVEL":
                coord_base = 45.0
                
            new_score = 0.25 * addr_score + 0.25 * pin_score + 0.50 * coord_base
            new_score = round(min(100.0, max(0.0, new_score)), 2)
            df.at[idx, 'proposed_overall_location_confidence_score'] = new_score
            
            # Reliability Bucket mapping
            if decision == "PINCODE_CENTROID_ONLY":
                bucket = "HIGH_RISK"
                r_flag = "REVIEW_BEFORE_USE"
            else:
                if new_score >= 85.0:
                    bucket = "HIGH_RELIABILITY"
                    r_flag = "USE"
                elif new_score >= 65.0:
                    bucket = "MODERATE_RELIABILITY"
                    r_flag = "USE_WITH_CAUTION"
                elif new_score >= 40.0:
                    bucket = "LOW_RELIABILITY"
                    r_flag = "REVIEW_BEFORE_USE"
                else:
                    bucket = "HIGH_RISK"
                    r_flag = "REVIEW_BEFORE_USE"
                    
            df.at[idx, 'proposed_routing_reliability_bucket'] = bucket
            df.at[idx, 'proposed_routing_risk_flag'] = r_flag
            
    return df

def promote_proposed_coordinates(df, apply_updates=False):
    """
    If apply_updates is True, promotes the proposed fields to active final fields.
    Saves the old coordinates in previous_final_lat/previous_final_long and sets timestamps.
    """
    df['previous_final_lat'] = df['final_lat']
    df['previous_final_long'] = df['final_long']
    df['previous_coordinate_source'] = df['coordinate_source']
    df['coordinate_update_timestamp'] = ""
    df['coordinate_update_reason'] = ""
    
    if not apply_updates:
        # Proposed values remain strictly separate
        return df
        
    print("Promoting approved geocoding candidates to final coordinate fields...")
    
    # Identify promoted rows
    promoted_mask = df['geocoding_acceptance_decision'].isin([
        "ACCEPT_REPLACE_FINAL_COORDS", "ACCEPT_WITH_CAUTION", "PINCODE_CENTROID_ONLY"
    ])
    
    # Update active fields for promoted records
    df.loc[promoted_mask, 'final_lat'] = df.loc[promoted_mask, 'proposed_final_lat']
    df.loc[promoted_mask, 'final_long'] = df.loc[promoted_mask, 'proposed_final_long']
    df.loc[promoted_mask, 'coordinate_source'] = df.loc[promoted_mask, 'proposed_coordinate_source']
    df.loc[promoted_mask, 'routing_reliability_bucket'] = df.loc[promoted_mask, 'proposed_routing_reliability_bucket']
    df.loc[promoted_mask, 'routing_risk_flag'] = df.loc[promoted_mask, 'proposed_routing_risk_flag']
    df.loc[promoted_mask, 'overall_location_confidence_score'] = df.loc[promoted_mask, 'proposed_overall_location_confidence_score']
    
    # Set update log fields
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    df.loc[promoted_mask, 'coordinate_update_timestamp'] = now_str
    df.loc[promoted_mask, 'coordinate_update_reason'] = df.loc[promoted_mask, 'geocoding_acceptance_reason']
    
    return df
