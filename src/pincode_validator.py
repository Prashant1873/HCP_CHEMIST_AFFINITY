# Module for validating coordinates against pincode polygons from GeoJSON
import os
import json
import time
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Union
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from src.utils import setup_logger
from src.data_cleaning import clean_pincode
from src import config

logger = setup_logger("pincode_validator")

# Approximate conversion: 1 degree latitude/longitude in India is ~111 km
DEGREE_TO_KM = 111.0


class PincodeSpatialValidator:
    """
    High-performance spatial validator that verifies if coordinates fall
    within official pincode polygon boundaries loaded from GeoJSON.
    """
    
    def __init__(self, geojson_path: Optional[str] = None):
        self.geojson_path = geojson_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            config.DEFAULT_PINCODE_GEOJSON
        )
        self.pin_to_geom: Dict[str, Any] = {}
        self.pin_to_meta: Dict[str, Dict[str, str]] = {}
        self.pincodes: List[str] = []
        self.geometries: List[Any] = []
        self.tree: Optional[STRtree] = None
        self._is_loaded = False
        
        if os.path.exists(self.geojson_path):
            self.load_geojson()
        else:
            logger.warning(
                f"Pincode GeoJSON file not found at '{self.geojson_path}'. "
                "Pincode boundary validation will not be active until loaded."
            )

    def load_geojson(self, geojson_path: Optional[str] = None) -> bool:
        """
        Loads and parses pincode boundaries from GeoJSON, building spatial indexes.
        """
        path = geojson_path or self.geojson_path
        if not os.path.exists(path):
            logger.error(f"GeoJSON file not found: {path}")
            return False
            
        t0 = time.time()
        logger.info(f"Loading pincode polygon boundaries from '{path}'...")
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read GeoJSON file '{path}': {e}")
            return False
            
        features = data.get("features", [])
        if not features:
            logger.error("No features found in GeoJSON.")
            return False
            
        pin_geoms_dict = {}
        pin_meta_dict = {}
        
        for feat in features:
            props = feat.get("properties", {})
            raw_pin = props.get("Pincode", "")
            pin = clean_pincode(raw_pin)
            if not pin:
                continue
                
            geom_raw = feat.get("geometry")
            if not geom_raw:
                continue
                
            try:
                geom = shape(geom_raw)
                if not geom.is_valid:
                    geom = geom.buffer(0)
            except Exception:
                continue
                
            if pin in pin_geoms_dict:
                try:
                    pin_geoms_dict[pin] = pin_geoms_dict[pin].union(geom)
                except Exception:
                    pass
            else:
                pin_geoms_dict[pin] = geom
                pin_meta_dict[pin] = {
                    "pincode": pin,
                    "office_name": str(props.get("Office_Name", "")).strip(),
                    "division": str(props.get("Division", "")).strip(),
                    "region": str(props.get("Region", "")).strip(),
                    "circle": str(props.get("Circle", "")).strip()
                }
                
        self.pin_to_geom = pin_geoms_dict
        self.pin_to_meta = pin_meta_dict
        self.pincodes = list(pin_geoms_dict.keys())
        self.geometries = [pin_geoms_dict[p] for p in self.pincodes]
        
        # Build STRtree spatial index for fast reverse geocoding
        t_tree_0 = time.time()
        self.tree = STRtree(np.array(self.geometries, dtype=object))
        t_tree_1 = time.time()
        
        self._is_loaded = True
        logger.info(
            f"Successfully indexed {len(self.pincodes)} unique pincode boundaries "
            f"(JSON load + parse: {t_tree_0 - t0:.2f}s, STRtree build: {t_tree_1 - t_tree_0:.3f}s)."
        )
        return True

    @property
    def is_ready(self) -> bool:
        return self._is_loaded and bool(self.pin_to_geom)

    def find_containing_pincode(self, point: Point) -> Optional[str]:
        """
        Finds which pincode polygon physically contains the given (lon, lat) Point.
        """
        if not self.tree:
            return None
        matches = self.tree.query(point, predicate="intersects")
        if len(matches) > 0:
            return self.pincodes[matches[0]]
        return None

    def validate_coordinate(
        self,
        lat: float,
        lon: float,
        stated_pincode: str,
        tolerance_km: float = config.DEFAULT_PINCODE_TOLERANCE_KM
    ) -> Dict[str, Any]:
        """
        Validates a single (lat, lon) coordinate against its stated pincode.
        
        Returns:
            Dict containing:
                - is_valid (bool): Whether coordinate is accepted
                - status (str): Classification code
                - distance_km (float): Distance in km from stated pincode boundary
                - actual_pincode (str): Pincode physically containing the point (if any)
                - actual_office_name (str): Office name of containing pincode
                - actual_circle (str): Circle / State of containing pincode
                - rejection_reason (str): Reason if rejected
        """
        clean_pin = clean_pincode(stated_pincode)
        
        # Check invalid or missing coordinates
        if pd.isna(lat) or pd.isna(lon):
            return {
                "is_valid": False,
                "status": "MISSING_COORDINATES",
                "distance_km": None,
                "actual_pincode": None,
                "actual_office_name": "",
                "actual_circle": "",
                "rejection_reason": "Missing or non-numeric coordinates"
            }
            
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            return {
                "is_valid": False,
                "status": "INVALID_COORDINATES",
                "distance_km": None,
                "actual_pincode": None,
                "actual_office_name": "",
                "actual_circle": "",
                "rejection_reason": "Coordinates cannot be converted to float"
            }

        # Check India bounding box
        if not (config.INDIA_LAT_MIN <= lat <= config.INDIA_LAT_MAX and config.INDIA_LON_MIN <= lon <= config.INDIA_LON_MAX):
            return {
                "is_valid": False,
                "status": "OUTSIDE_INDIA_BOUNDS",
                "distance_km": None,
                "actual_pincode": None,
                "actual_office_name": "",
                "actual_circle": "",
                "rejection_reason": f"Coordinates ({lat:.4f}, {lon:.4f}) are outside India bounding box"
            }

        if not self.is_ready:
            # If GeoJSON not loaded, pass through
            return {
                "is_valid": True,
                "status": "VALIDATOR_NOT_LOADED",
                "distance_km": 0.0,
                "actual_pincode": clean_pin,
                "actual_office_name": "",
                "actual_circle": "",
                "rejection_reason": ""
            }

        pt = Point(lon, lat)
        
        # 1. If stated pincode exists in GeoJSON
        if clean_pin and clean_pin in self.pin_to_geom:
            stated_geom = self.pin_to_geom[clean_pin]
            
            # Check exact containment
            if stated_geom.contains(pt) or stated_geom.intersects(pt):
                return {
                    "is_valid": True,
                    "status": "VALID_INSIDE",
                    "distance_km": 0.0,
                    "actual_pincode": clean_pin,
                    "actual_office_name": self.pin_to_meta[clean_pin]["office_name"],
                    "actual_circle": self.pin_to_meta[clean_pin]["circle"],
                    "rejection_reason": ""
                }
            
            # Distance from boundary in km
            dist_deg = stated_geom.distance(pt)
            dist_km = dist_deg * DEGREE_TO_KM
            
            # Reverse lookup: find where point actually lies
            actual_pin = self.find_containing_pincode(pt)
            act_office = self.pin_to_meta.get(actual_pin, {}).get("office_name", "") if actual_pin else ""
            act_circle = self.pin_to_meta.get(actual_pin, {}).get("circle", "") if actual_pin else ""

            # Check if within tolerance
            if dist_km <= tolerance_km:
                return {
                    "is_valid": True,
                    "status": "VALID_NEARBY",
                    "distance_km": round(dist_km, 3),
                    "actual_pincode": actual_pin or clean_pin,
                    "actual_office_name": act_office or self.pin_to_meta[clean_pin]["office_name"],
                    "actual_circle": act_circle or self.pin_to_meta[clean_pin]["circle"],
                    "rejection_reason": ""
                }
            else:
                reason = (
                    f"Coordinates are {dist_km:.2f} km outside stated pincode {clean_pin} boundary"
                )
                if actual_pin and actual_pin != clean_pin:
                    reason += f" (actual location falls inside pincode {actual_pin} - {act_office}, {act_circle})"
                
                return {
                    "is_valid": False,
                    "status": "MISMATCH_WRONG_PINCODE",
                    "distance_km": round(dist_km, 3),
                    "actual_pincode": actual_pin,
                    "actual_office_name": act_office,
                    "actual_circle": act_circle,
                    "rejection_reason": reason
                }
        
        # 2. If stated pincode is not found in GeoJSON reference database
        actual_pin = self.find_containing_pincode(pt)
        act_office = self.pin_to_meta.get(actual_pin, {}).get("office_name", "") if actual_pin else ""
        act_circle = self.pin_to_meta.get(actual_pin, {}).get("circle", "") if actual_pin else ""

        if not clean_pin:
            # Pincode was empty/missing, but coordinates fall in India
            return {
                "is_valid": True,
                "status": "MISSING_STATED_PINCODE_RETAINED",
                "distance_km": None,
                "actual_pincode": actual_pin,
                "actual_office_name": act_office,
                "actual_circle": act_circle,
                "rejection_reason": ""
            }
        else:
            # Stated pincode is not in GeoJSON reference polygons.
            # Since GeoJSON does not contain this polygon, it is not conclusive evidence of wrong data.
            # Retain the record as valid.
            return {
                "is_valid": True,
                "status": "PINCODE_NOT_IN_REFERENCE_RETAINED",
                "distance_km": None,
                "actual_pincode": actual_pin or clean_pin,
                "actual_office_name": act_office,
                "actual_circle": act_circle,
                "rejection_reason": ""
            }


    def validate_dataframe(
        self,
        df: pd.DataFrame,
        lat_col: str,
        lon_col: str,
        pin_col: Optional[str] = None,
        id_col: Optional[str] = None,
        name_col: Optional[str] = None,
        role: str = "entity",
        tolerance_km: float = config.DEFAULT_PINCODE_TOLERANCE_KM,
        allow_unmapped_pincodes: bool = False
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Validates an entire DataFrame against pincode boundaries.
        
        Args:
            df: Input DataFrame
            lat_col: Name of latitude column
            lon_col: Name of longitude column
            pin_col: Name of pincode column (auto-detected if None)
            id_col: Identifier column name
            name_col: Name column name
            role: Role label (e.g. 'doctor', 'chemist')
            tolerance_km: Maximum allowable distance (km) outside polygon for border leniency
            allow_unmapped_pincodes: If True, keep records whose stated pincode is not in GeoJSON
            
        Returns:
            Tuple of:
                - verified_df: Clean DataFrame with valid coordinates
                - mismatched_df: Flagged/rejected DataFrame with mismatch details
                - summary_metrics: Dictionary of audit statistics
        """
        t0 = time.time()
        df_out = df.copy()
        
        # Auto-detect pin_col if needed
        if not pin_col or pin_col not in df_out.columns:
            for cand in config.PINCODE_COLUMNS:
                if cand in df_out.columns:
                    pin_col = cand
                    break
        
        logger.info(
            f"Validating {len(df_out)} {role} records against GeoJSON boundaries "
            f"(tolerance: {tolerance_km} km)..."
        )
        
        # Pre-allocate diagnostic columns
        is_valid_list = []
        status_list = []
        dist_list = []
        actual_pin_list = []
        actual_office_list = []
        actual_circle_list = []
        reasons_list = []
        
        for idx, row in df_out.iterrows():
            lat = row.get(lat_col)
            lon = row.get(lon_col)
            stated_pin = str(row.get(pin_col, "") if pin_col else "")
            
            res = self.validate_coordinate(
                lat=lat,
                lon=lon,
                stated_pincode=stated_pin,
                tolerance_km=tolerance_km
            )
            
            # Policy on unmapped pincodes
            if res["status"] == "PINCODE_NOT_IN_REFERENCE" and allow_unmapped_pincodes:
                res["is_valid"] = True
                res["rejection_reason"] = ""
            
            is_valid_list.append(res["is_valid"])
            status_list.append(res["status"])
            dist_list.append(res["distance_km"])
            actual_pin_list.append(res["actual_pincode"] or "")
            actual_office_list.append(res["actual_office_name"])
            actual_circle_list.append(res["actual_circle"])
            reasons_list.append(res["rejection_reason"])
            
        df_out["pincode_valid"] = is_valid_list
        df_out["pincode_validation_status"] = status_list
        df_out["distance_to_stated_pincode_km"] = dist_list
        df_out["actual_detected_pincode"] = actual_pin_list
        df_out["actual_office_name"] = actual_office_list
        df_out["actual_circle"] = actual_circle_list
        df_out["pincode_rejection_reason"] = reasons_list
        
        # Separate into verified vs mismatched
        verified_mask = df_out["pincode_valid"] == True
        verified_df = df_out[verified_mask].copy().reset_index(drop=True)
        mismatched_df = df_out[~verified_mask].copy().reset_index(drop=True)
        
        # Compute summary metrics
        status_counts = pd.Series(status_list).value_counts().to_dict()
        total_records = len(df_out)
        verified_count = len(verified_df)
        mismatched_count = len(mismatched_df)
        pass_rate_pct = round((verified_count / total_records * 100), 2) if total_records else 0
        
        summary = {
            "role": role,
            "total_records": total_records,
            "verified_valid_records": verified_count,
            "mismatched_removed_records": mismatched_count,
            "pass_rate_percentage": pass_rate_pct,
            "tolerance_km": tolerance_km,
            "status_breakdown": status_counts,
            "processing_time_sec": round(time.time() - t0, 3)
        }
        
        logger.info(
            f"Validation complete for {role}: {verified_count}/{total_records} verified valid "
            f"({pass_rate_pct}%), {mismatched_count} removed as mismatched in {summary['processing_time_sec']}s."
        )
        
        return verified_df, mismatched_df, summary
