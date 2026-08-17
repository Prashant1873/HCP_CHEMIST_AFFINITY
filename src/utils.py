# Utilities and logging configurations for doctor-chemist mapping tool
import logging
import os
import sys

def setup_logger(name: str = "doctor_chemist_matcher") -> logging.Logger:
    """
    Sets up a consolidated logger that outputs to the console with human-readable formatting.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger


def filter_by_city(df, city_str):
    """
    Filters a DataFrame by city name(s), supporting comma-separated cities (e.g. 'Mumbai,Pune').
    Checks across city columns, address/location/region columns, and numeric pincode prefixes.
    """
    import pandas as pd
    if df is None or df.empty or not city_str:
        return df if df is not None else pd.DataFrame()
        
    city_filters = [c.strip() for c in str(city_str).split(",") if c.strip()]
    if not city_filters:
        return df
        
    mask = pd.Series(False, index=df.index)
    
    for filt in city_filters:
        filt_clean = "".join(c for c in filt.lower() if c.isalnum())
        if not filt_clean:
            continue
            
        filt_mask = pd.Series(False, index=df.index)
        
        # 1. Match city columns
        for col in df.columns:
            if "city" in col.lower():
                filt_mask |= df[col].astype(str).apply(
                    lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                )
                
        # 2. Match address / location / division / region columns
        for col in df.columns:
            if any(k in col.lower() for k in ["addr", "location", "division", "region", "circle"]):
                filt_mask |= df[col].astype(str).apply(
                    lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                )
                
        # 3. Numeric pincode prefix fallback if digits provided
        if filt.isdigit():
            for col in df.columns:
                if "pin" in col.lower() or "zip" in col.lower():
                    filt_mask |= df[col].astype(str).str.startswith(filt)
                    
        mask |= filt_mask
        
    return df[mask].reset_index(drop=True)

