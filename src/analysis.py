# Module for calculating capture rate validations and summaries
import pandas as pd
import numpy as np
from typing import Tuple
from src.utils import setup_logger

logger = setup_logger("analysis")

def calculate_capture_rate_analysis(
    df_with_road: pd.DataFrame,
    final_n: int = 5
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generates:
    1. A detailed capture analysis per doctor:
       - doctor_id
       - max_air_rank_needed_for_road_top_5
       - road_top_5_available_within_air_top_10
       - road_top_5_available_within_air_top_20
       - road_top_5_available_within_air_top_30
       - road_top_5_available_within_air_top_50
    2. An aggregated capture summary:
       - candidate_k
       - doctors_fully_captured_count
       - doctors_total
       - capture_rate
    """
    logger.info("Starting candidate K capture rate analysis...")
    
    # Filter to only successful route calculations
    df_success = df_with_road[df_with_road["road_distance_status"] == "success"].copy()
    
    if df_success.empty:
        logger.warning("No successful route calculations found. Capture rate analysis will be empty.")
        empty_analysis = pd.DataFrame(columns=[
            "doctor_id", "max_air_rank_needed_for_road_top_5",
            "road_top_5_available_within_air_top_10", "road_top_5_available_within_air_top_20",
            "road_top_5_available_within_air_top_30", "road_top_5_available_within_air_top_50"
        ])
        empty_summary = pd.DataFrame(columns=[
            "candidate_k", "doctors_fully_captured_count", "doctors_total", "capture_rate"
        ])
        return empty_analysis, empty_summary

    doctor_ids = df_with_road["doctor_id"].unique()
    rows_detail = []
    
    for doc_id in doctor_ids:
        doc_df = df_success[df_success["doctor_id"] == doc_id]
        
        if doc_df.empty:
            # No successful road calculations for this doctor
            continue
            
        # Sort by road distance to identify the "true" top 5 road-distance chemists
        doc_road_sorted = doc_df.sort_values(by="road_distance_km")
        
        # Take the top N (usually 5) road distance chemists
        n_actual = min(final_n, len(doc_road_sorted))
        road_top_n = doc_road_sorted.head(n_actual)
        
        # Find the air-distance ranks of these top N road-distance chemists
        air_ranks = road_top_n["air_distance_rank"].values
        max_air_rank = int(air_ranks.max()) if len(air_ranks) > 0 else 0
        
        # Check capture status within K = 10, 20, 30, 50
        rows_detail.append({
            "doctor_id": doc_id,
            "max_air_rank_needed_for_road_top_5": max_air_rank,
            "road_top_5_available_within_air_top_10": 1 if max_air_rank <= 10 else 0,
            "road_top_5_available_within_air_top_20": 1 if max_air_rank <= 20 else 0,
            "road_top_5_available_within_air_top_30": 1 if max_air_rank <= 30 else 0,
            "road_top_5_available_within_air_top_50": 1 if max_air_rank <= 50 else 0
        })
        
    df_detail = pd.DataFrame(rows_detail)
    
    # Generate aggregated summary
    summary_list = []
    total_docs = len(df_detail)
    
    for k in [10, 20, 30, 50]:
        col_name = f"road_top_5_available_within_air_top_{k}"
        if col_name in df_detail.columns:
            captured_count = int(df_detail[col_name].sum())
        else:
            captured_count = 0
            
        rate = (captured_count / total_docs * 100) if total_docs > 0 else 0.0
        
        summary_list.append({
            "candidate_k": k,
            "doctors_fully_captured_count": captured_count,
            "doctors_total": total_docs,
            "capture_rate": f"{rate:.1f}%"
        })
        
    df_summary = pd.DataFrame(summary_list)
    
    logger.info("Capture rate analysis completed.")
    return df_detail, df_summary
