# Module for entity resolution, pharmacy deduplication, and multi-IQVIA ID consolidation
import re
import math
from difflib import SequenceMatcher
from typing import Tuple, List, Dict, Set, Optional, Any
import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
from src.utils import setup_logger
from src import config

logger = setup_logger("entity_resolver")

# Common business suffixes in Indian pharmacy store names (sorted by length descending)
BUSINESS_SUFFIXES = [
    'MEDICAL AND GENERAL STORES',
    'MEDICAL AND GENERAL STORE',
    'MEDICAL & GENERAL STORES',
    'MEDICAL & GENERAL STORE',
    'MEDICAL AND GEN STORES',
    'MEDICAL AND GEN STORE',
    'MEDICAL & GEN STORES',
    'MEDICAL & GEN STORE',
    'MEDICAL GEN STORES',
    'MEDICAL GEN STORE',
    'MED AND GEN STORES',
    'MED AND GEN STORE',
    'MED & GEN STORES',
    'MED & GEN STORE',
    'MED GEN STORES',
    'MED GEN STORE',
    'CHEMIST AND DRUGGIST',
    'CHEMISTS AND DRUGGISTS',
    'CHEMIST & DRUGGIST',
    'CHEMISTS & DRUGGISTS',
    'CHEMIST AND DRUGGISTS',
    'CHEMISTS & DRUG',
    'CHEMIST & DRUG',
    'DRUG AND CHEMIST',
    'DRUG & CHEMIST',
    'MEDICINE STORE',
    'MEDICINE STORES',
    'MEDICINE SHOP',
    'MEDICINE CENTRE',
    'MEDICINE CENTER',
    'MEDICINE CORNER',
    'MEDICINE HOUSE',
    'MEDICINE HALL',
    'MEDICAL CENTRE',
    'MEDICAL CENTER',
    'MEDICAL CORNER',
    'MEDICAL HOUSE',
    'MEDICAL HALL',
    'MEDICAL STORES',
    'MEDICAL STORE',
    'DRUG STORES',
    'DRUG STORE',
    'DRUG STRORE',
    'DRUGSTORES',
    'DRUGSTORE',
    'PHARMACY STORE',
    'PHARMACIES',
    'PHARMACY',
    'CHEMISTS',
    'CHEMIST',
    'DRUGGISTS',
    'DRUGGIST',
    'MEDICOS',
    'MEDICO',
    'MEDICALS',
    'MEDICAL',
    'AUSHADHI KENDRA',
    'AUSHADHI STORE',
    'AUSHADHI',
    'DAVAKHANA',
    'AGENCIES',
    'AGENCY',
    'DISTRIBUTORS',
    'DISTRIBUTOR',
    'ENTERPRISES',
    'ENTERPRISE',
    'PVT LTD',
    'PVT. LTD.',
    'PVT.LTD.',
    'PRIVATE LIMITED',
    'LIMITED',
    'LTD.',
    'LTD',
    'PROP.',
    'PROP',
    'M/S',
    'M/S.',
    'CO.',
    'CO',
    'AND CO',
    '& CO',
    '& SONS',
    'AND SONS',
    '& BROTHERS',
    'AND BROTHERS',
    '& BROS',
    'AND BROS'
]

# Common generic pharmacy keywords to strip when identifying distinctive brand name
GENERIC_PHARMACY_TOKENS = {
    'MEDICAL', 'MED', 'MEDS', 'MEDICALS', 'MEDICO', 'MEDICOS',
    'CHEMIST', 'CHEMISTS', 'DRUGGIST', 'DRUGGISTS',
    'PHARMACY', 'PHARMACIES', 'DRUG', 'DRUGS',
    'STORE', 'STORES', 'SHOP', 'SHOPS',
    'CENTRE', 'CENTER', 'CORNER', 'HALL', 'HOUSE', 'BHANDAR', 'KENDRA', 'POINT', 'COUNTER',
    'AGENCIES', 'AGENCY', 'DISTRIBUTORS', 'DISTRIBUTOR', 'ENTERPRISES', 'ENTERPRISE',
    'TRADERS', 'TRADER', 'RETAILER', 'RETAILERS', 'WHOLESALER', 'WHOLESALERS',
    'PVT', 'LTD', 'LIMITED', 'PRIVATE', 'PROP', 'MS', 'CO', 'COMPANY',
    'AND', 'THE', 'A', 'AN', 'GENERAL', 'GEN', 'SUPER', 'PLUS', 'NEW'
}

# Spelling variation maps for Indian store names
SPELLING_NORMALIZATION = {
    r'\bBHATIA\b': 'BHATIA',
    r'\bBHATIYA\b': 'BHATIA',
    r'\bSHREE\b': 'SHRI',
    r'\bSRI\b': 'SHRI',
    r'\bSHREEJI\b': 'SHRIJI',
    r'\bLAXMI\b': 'LAKSHMI',
    r'\bMAHALAXMI\b': 'MAHALAKSHMI',
    r'\bJAI\b': 'JAY',
    r'\bAUM\b': 'OM',
    r'\bCHANDER\b': 'CHANDRA',
    r'\bSANJIVANI\b': 'SANJEEVANI',
    r'\bGANESH\b': 'GANESHA',
    r'\bBALAJI\b': 'BALAJEE',
}


def clean_alphanumeric(text: Any) -> str:
    """Removes punctuation and normalizes whitespace."""
    if pd.isna(text) or text is None:
        return ""
    s = str(text).upper()
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_chemist_name(name: Any) -> str:
    """
    Strips generic business descriptors, suffixes, prefixes, and normalizes
    common phonetic variations to extract the distinctive core brand name.
    
    Examples:
        "BHATIYA MEDICAL" -> "BHATIA"
        "BHATIA MEDICAL STORES" -> "BHATIA"
        "BHATIA MEDICAL&SUPER STORES" -> "BHATIA"
        "BON BON MEDICAL & GENERAL STORE" -> "BON BON"
        "GEMINI MEDICO" -> "GEMINI"
        "SHREE SAI MEDICAL STORE" -> "SHRI SAI"
        "M/S NOBLE CHEMIST" -> "NOBLE"
    """
    clean = clean_alphanumeric(name)
    if not clean:
        return ""
        
    # Strip leading prefixes like "M S ", "MS ", "THE ", "A ", "AN "
    clean = re.sub(r'^(THE|A|AN|MS|M\s*S|M\s*/\s*S)\s+', '', clean).strip()
    
    # Apply phonetic/spelling normalization
    for pattern, replacement in SPELLING_NORMALIZATION.items():
        clean = re.sub(pattern, replacement, clean)
        
    # Tokenize and filter out generic pharmacy business words
    tokens = clean.split()
    distinctive_tokens = [t for t in tokens if t not in GENERIC_PHARMACY_TOKENS]
    
    if distinctive_tokens:
        result = " ".join(distinctive_tokens)
    else:
        # If all tokens were generic words (e.g. "MEDICAL STORE"), keep original cleaned
        result = clean
        
    return result.strip()


def calculate_name_similarity(name1: str, name2: str) -> float:
    """
    Computes a robust similarity score between two normalized chemist store names.
    Combines Levenshtein ratio, token-set overlap, and substring matching.
    """
    n1 = normalize_chemist_name(name1)
    n2 = normalize_chemist_name(name2)
    
    if not n1 or not n2:
        raw1 = clean_alphanumeric(name1)
        raw2 = clean_alphanumeric(name2)
        if raw1 and raw2 and raw1 == raw2:
            return 1.0
        return 0.0
        
    # Exact match after normalization
    if n1 == n2:
        return 1.0
        
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    
    # Direct token subset containment
    if tokens1 and tokens2:
        if tokens1.issubset(tokens2) or tokens2.issubset(tokens1):
            return 0.90
            
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        if union:
            jaccard = len(intersection) / len(union)
            if jaccard >= 0.60:
                return jaccard
                
    # Direct substring containment (e.g. "BHATIA" in "BHATIYA")
    if n1 in n2 or n2 in n1:
        shorter = min(len(n1), len(n2))
        longer = max(len(n1), len(n2))
        if shorter >= 3:
            return max(shorter / longer, 0.85)
            
    # SequenceMatcher ratio
    seq_ratio = SequenceMatcher(None, n1, n2).ratio()
    return seq_ratio


def clean_address_tokens(address: Any) -> Set[str]:
    """Extracts significant alphanumeric tokens from an address string."""
    clean = clean_alphanumeric(address)
    tokens = set(clean.split())
    # Remove single characters and common noise words
    noise = {'ROAD', 'RD', 'MARG', 'SHOP', 'NO', 'NEAR', 'OPP', 'BEHIND', 'FLOOR', 'BLDG', 'BUILDING', 'CHS', 'CHS LTD', 'LTD'}
    return {t for t in tokens if len(t) > 1 and t not in noise}


def are_addresses_similar(addr1: Any, addr2: Any) -> bool:
    """Checks if two address strings share substantial unique street/building tokens."""
    t1 = clean_address_tokens(addr1)
    t2 = clean_address_tokens(addr2)
    if not t1 or not t2:
        return False
    overlap = t1.intersection(t2)
    min_len = min(len(t1), len(t2))
    if min_len == 0:
        return False
    # If >= 60% of tokens match or >= 3 specific tokens match
    return (len(overlap) / min_len >= 0.60) or (len(overlap) >= 3)


class UnionFind:
    """Disjoint Set Union (DSU) data structure for clustering entities."""
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, i: int) -> int:
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            if self.rank[root_i] < self.rank[root_j]:
                self.parent[root_i] = root_j
            elif self.rank[root_i] > self.rank[root_j]:
                self.parent[root_j] = root_i
            else:
                self.parent[root_j] = root_i
                self.rank[root_i] += 1


def resolve_and_deduplicate_chemists(
    df: pd.DataFrame,
    lat_col: str = "chemist_latitude",
    lon_col: str = "chemist_longitude",
    name_col: str = "chemist_name",
    id_col: str = "chemist_id",
    pin_col: str = "chemist_pincode",
    addr_col: Optional[str] = None,
    spatial_proximity_m: float = 30.0,
    name_similarity_threshold: float = 0.70
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Multi-pass entity resolution and deduplication engine that consolidates
    multiple IQVIA IDs and near-duplicate records of the same physical pharmacy.
    
    Returns:
        Tuple of:
            - canonical_df: Deduplicated master DataFrame (1 row per physical pharmacy)
            - merged_aliases_df: Audit DataFrame of secondary records consolidated
            - summary: Dictionary of consolidation statistics
    """
    if df.empty:
        return df.copy(), pd.DataFrame(), {
            "total_input_records": 0,
            "canonical_entities": 0,
            "merged_duplicate_records": 0,
            "deduplication_rate_pct": 0.0,
            "multi_id_entities_count": 0
        }
        
    df_work = df.copy().reset_index(drop=True)
    n_records = len(df_work)
    dsu = UnionFind(n_records)
    
    # Ensure standard string representations
    names = df_work[name_col].astype(str).tolist()
    ids = df_work[id_col].astype(str).tolist()
    pins = df_work[pin_col].astype(str).str.split('.').str[0].tolist() if pin_col in df_work.columns else [""] * n_records
    
    # Auto-detect address column if present
    if not addr_col:
        for cand in ["chem_address", "chemist_address", "address", "Address"]:
            if cand in df_work.columns:
                addr_col = cand
                break
    addresses = df_work[addr_col].astype(str).tolist() if addr_col and addr_col in df_work.columns else [""] * n_records
    
    lats = pd.to_numeric(df_work[lat_col], errors='coerce').values
    lons = pd.to_numeric(df_work[lon_col], errors='coerce').values
    
    norm_names = [normalize_chemist_name(nm) for nm in names]
    
    # -------------------------------------------------------------
    # PASS 1: Exact Coordinate Groups
    # Group records by (lat, lon) and merge if names or addresses match
    # -------------------------------------------------------------
    coord_groups: Dict[Tuple[float, float], List[int]] = {}
    for i in range(n_records):
        lat = lats[i]
        lon = lons[i]
        if np.isnan(lat) or np.isnan(lon):
            continue
        # Round slightly to 6 decimal places (~10cm precision) to handle float representation
        key = (round(lat, 6), round(lon, 6))
        if key not in coord_groups:
            coord_groups[key] = []
        coord_groups[key].append(i)
        
    for key, group_indices in coord_groups.items():
        if len(group_indices) <= 1:
            continue
        # Pairwise comparison within the same exact coordinate
        for a_idx in range(len(group_indices)):
            i = group_indices[a_idx]
            for b_idx in range(a_idx + 1, len(group_indices)):
                j = group_indices[b_idx]
                
                # Check normalized name similarity
                sim = calculate_name_similarity(names[i], names[j])
                if sim >= name_similarity_threshold:
                    dsu.union(i, j)
                elif are_addresses_similar(addresses[i], addresses[j]) and sim >= 0.50:
                    dsu.union(i, j)
                    
    # -------------------------------------------------------------
    # PASS 2: Micro-Spatial Proximity (GPS Jitter <= spatial_proximity_m)
    # Using BallTree on Haversine distance
    # -------------------------------------------------------------
    valid_coords_mask = ~np.isnan(lats) & ~np.isnan(lons)
    valid_indices = np.where(valid_coords_mask)[0]
    
    if len(valid_indices) > 1 and spatial_proximity_m > 0:
        lat_rad = np.radians(lats[valid_indices])
        lon_rad = np.radians(lons[valid_indices])
        coords_rad = np.column_stack((lat_rad, lon_rad))
        
        radius_rad = (spatial_proximity_m / 1000.0) / config.EARTH_RADIUS_KM
        tree = BallTree(coords_rad, metric='haversine')
        
        neighbor_indices = tree.query_radius(coords_rad, r=radius_rad)
        
        for k_idx, neighbors in enumerate(neighbor_indices):
            i = valid_indices[k_idx]
            for n_sub in neighbors:
                j = valid_indices[n_sub]
                if i >= j:
                    continue
                    
                # Must share the same pincode if available
                pin_i = pins[i]
                pin_j = pins[j]
                if pin_i and pin_j and pin_i != pin_j:
                    continue
                    
                sim = calculate_name_similarity(names[i], names[j])
                if sim >= name_similarity_threshold:
                    dsu.union(i, j)
                elif are_addresses_similar(addresses[i], addresses[j]) and sim >= 0.60:
                    dsu.union(i, j)
                    
    # -------------------------------------------------------------
    # PASS 3: Same Pincode + Exact Normalized Name (within 500m)
    # -------------------------------------------------------------
    pincode_name_groups: Dict[Tuple[str, str], List[int]] = {}
    for i in range(n_records):
        pin = pins[i]
        norm_nm = norm_names[i]
        if pin and norm_nm and len(norm_nm) >= 4:
            key = (pin, norm_nm)
            if key not in pincode_name_groups:
                pincode_name_groups[key] = []
            pincode_name_groups[key].append(i)
            
    for key, group_indices in pincode_name_groups.items():
        if len(group_indices) <= 1:
            continue
        first_idx = group_indices[0]
        for other_idx in group_indices[1:]:
            # Check spatial plausibility (must be within 500m in the same pincode)
            dist_km = math.sqrt(
                ((lats[first_idx] - lats[other_idx]) * 111.0)**2 +
                ((lons[first_idx] - lons[other_idx]) * 111.0 * math.cos(math.radians(lats[first_idx])))**2
            ) if not np.isnan(lats[first_idx]) and not np.isnan(lats[other_idx]) else 999.0
            
            if dist_km <= 0.5:  # Within 500 meters
                dsu.union(first_idx, other_idx)

    # -------------------------------------------------------------
    # CONSOLIDATE CLUSTERS INTO CANONICAL MASTER RECORDS
    # -------------------------------------------------------------
    clusters: Dict[int, List[int]] = {}
    for i in range(n_records):
        root = dsu.find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(i)
        
    canonical_rows = []
    audit_rows = []
    
    for cluster_id, member_indices in clusters.items():
        members = df_work.iloc[member_indices]
        
        # Elect Canonical Representative:
        # Prefer row with the most complete name, valid coordinates, and cleanest address
        best_idx = member_indices[0]
        best_score = -1
        
        for idx in member_indices:
            row = df_work.iloc[idx]
            score = 0
            nm = str(row.get(name_col, ""))
            if len(nm) > 5:
                score += min(len(nm), 30)
            if pd.notna(row.get(lat_col)) and pd.notna(row.get(lon_col)):
                score += 50
            if addr_col and pd.notna(row.get(addr_col)) and len(str(row.get(addr_col))) > 10:
                score += 20
            if score > best_score:
                best_score = score
                best_idx = idx
                
        canonical_row = df_work.iloc[best_idx].copy()
        
        # Collect all aliased IQVIA IDs and names
        all_ids = [ids[idx] for idx in member_indices if ids[idx] and ids[idx] != "nan"]
        unique_ids = list(dict.fromkeys(all_ids))  # Preserve order, unique
        
        all_names = [names[idx] for idx in member_indices if names[idx] and names[idx] != "nan"]
        unique_names = list(dict.fromkeys(all_names))
        
        canonical_row["aliased_iqvia_ids"] = " | ".join(unique_ids)
        canonical_row["alias_count"] = len(unique_ids)
        canonical_row["all_alias_names"] = " | ".join(unique_names)
        canonical_row["entity_cluster_id"] = f"PHARM_ENT_{cluster_id:06d}"
        
        canonical_rows.append(canonical_row)
        
        # If cluster merged multiple rows, log secondary rows to audit DataFrame
        if len(member_indices) > 1:
            for idx in member_indices:
                if idx != best_idx:
                    audit_row = df_work.iloc[idx].copy()
                    audit_row["canonical_iqvia_id"] = canonical_row[id_col]
                    audit_row["canonical_name"] = canonical_row[name_col]
                    audit_row["consolidation_reason"] = "MULTI_IQVIA_DUPLICATE_PHARMACY"
                    audit_row["entity_cluster_id"] = canonical_row["entity_cluster_id"]
                    audit_rows.append(audit_row)
                    
    canonical_df = pd.DataFrame(canonical_rows).reset_index(drop=True)
    merged_aliases_df = pd.DataFrame(audit_rows).reset_index(drop=True) if audit_rows else pd.DataFrame()
    
    total_in = len(df_work)
    total_out = len(canonical_df)
    merged_count = len(merged_aliases_df)
    dedup_pct = round((merged_count / total_in * 100), 2) if total_in > 0 else 0.0
    
    summary = {
        "total_input_records": total_in,
        "canonical_entities": total_out,
        "merged_duplicate_records": merged_count,
        "deduplication_rate_pct": dedup_pct,
        "multi_id_entities_count": int((canonical_df["alias_count"] > 1).sum()) if "alias_count" in canonical_df.columns else 0
    }
    
    logger.info(
        f"Entity Resolution & Deduplication: Consolidated {total_in} records into "
        f"{total_out} distinct physical pharmacy entities (merged {merged_count} duplicate IQVIA records / {dedup_pct}%)."
    )
    
    return canonical_df, merged_aliases_df, summary
