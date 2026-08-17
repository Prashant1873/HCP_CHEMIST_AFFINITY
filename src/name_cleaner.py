# Module for identifying and filtering generic, placeholder, and unbranded chemist/store names
import re
import pandas as pd
from typing import Tuple, List, Dict, Set, Optional, Any
from src.utils import setup_logger
from src import config

logger = setup_logger("name_cleaner")

# Regex patterns for pure generic names, descriptors, and common misspellings (case-insensitive)
DEFAULT_GENERIC_PATTERNS = [
    # Basic single & plural generic terms (with optional leading article "The" / "A" / "An")
    r'^(the\s+|a\s+|an\s+)?chemist(s)?(\s+shop)?$',
    r'^(the\s+|a\s+|an\s+)?medical(s)?(\s+(store(s)?|hall|agency|centre|center|corner|shop|counter))?$',
    r'^(the\s+|a\s+|an\s+)?pharmacy(\s+(store(s)?|shop|counter))?$',
    r'^(the\s+|a\s+|an\s+)?pharmacies$',
    # Drug store variations including typos like "drug strore", "drugstores"
    r'^(the\s+|a\s+|an\s+)?drug\s*st(ore|rore)(s)?$',
    r'^(the\s+|a\s+|an\s+)?drug(s)?(\s+(store(s)?|shop|house|center|centre))?$',
    r'^(the\s+|a\s+|an\s+)?druggist(s)?$',
    r'^(the\s+|a\s+|an\s+)?chemist(s)?\s*(&|and|\+)\s*druggist(s)?$',
    r'^(the\s+|a\s+|an\s+)?druggist(s)?\s*(&|and|\+)\s*chemist(s)?$',
    # Medicine store / shop / center / hall
    r'^(the\s+|a\s+|an\s+)?medicine(s)?(\s+(store(s)?|shop|house|centre|center|corner|hall|bhandar|agency|point|counter))?$',
    r'^(the\s+|a\s+|an\s+)?medico(s)?(\s+(store(s)?|shop|centre|center))?$',
    r'^(the\s+|a\s+|an\s+)?apothecary$',
    r'^(the\s+|a\s+|an\s+)?retailer(s)?(\s+(store(s)?|shop))?$',
    r'^(the\s+|a\s+|an\s+)?trader(s)?(\s+(store(s)?|shop))?$',
    r'^(the\s+|a\s+|an\s+)?distributor(s)?$',
    r'^(the\s+|a\s+|an\s+)?wholesaler(s)?$',
    # Generic medicine & government schemes
    r'^(the\s+|a\s+|an\s+)?generic\s*(medicine|pharmacy|drug|medical)?(s)?(\s+(store(s)?|shop|centre|center))?$',
    r'^(the\s+|a\s+|an\s+)?(pradhan\s+mantri\s+)?jan\s+aushadhi(\s+(kendra|store(s)?|shop|centre|center))?$',
    r'^(the\s+|a\s+|an\s+)?pmbjp(\s+(kendra|store(s)?))?$',
    r'^(the\s+|a\s+|an\s+)?davakhana$',
    r'^(the\s+|a\s+|an\s+)?aushadhi(\s+(kendra|bhandar|store(s)?))?$',
    r'^(the\s+|a\s+|an\s+)?aushadhalaya$',
    r'^(the\s+|a\s+|an\s+)?dispensary$',
    # Placeholders, missing indicators, single letters, pure digits, and symbols
    r'^(unknown|na|n\s*a|n/a|null|none|test|sample|dummy|unnamed|no\s*name|nil|not\s*available|undefined|temp|temporary|xyz|abc|demo)$',
    r'^[\.\-_/\\,.:;\'"()\[\]{}|!@#$%^&*+=<>?~`\d\s]+$',
    r'^[a-zA-Z]$'  # Single letter names like "C", "A", "X"
]

COMPILED_GENERIC_REGEX = re.compile('|'.join(DEFAULT_GENERIC_PATTERNS), re.IGNORECASE)


def is_generic_name(
    name: Any,
    additional_keywords: Optional[List[str]] = None,
    compiled_regex: Optional[re.Pattern] = None
) -> Tuple[bool, str]:
    """
    Determines whether a given name is a generic placeholder or lacks distinctive branding.
    
    Args:
        name: Store/chemist name string
        additional_keywords: Optional list of additional custom keywords to flag as generic
        compiled_regex: Optional pre-compiled regex pattern
        
    Returns:
        Tuple of (is_generic: bool, reason: str)
    """
    if pd.isna(name) or name is None:
        return True, "MISSING_OR_BLANK_NAME"
        
    raw_name = str(name).strip()
    if not raw_name:
        return True, "MISSING_OR_BLANK_NAME"
        
    # Check custom user keywords first if supplied
    if additional_keywords:
        lower_raw = raw_name.lower()
        for kw in additional_keywords:
            if lower_raw == kw.lower().strip():
                return True, f"CUSTOM_GENERIC_KEYWORD ('{raw_name}')"
                
    # Normalize string: remove extra whitespace and non-alphanumeric punctuation except & and +
    normalized = re.sub(r'[^\w\s&+]', ' ', raw_name).strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    
    if not normalized:
        return True, f"ONLY_PUNCTUATION_OR_SYMBOLS ('{raw_name}')"
        
    # Test against compiled generic regex
    pattern = compiled_regex or COMPILED_GENERIC_REGEX
    if pattern.match(normalized):
        return True, f"GENERIC_PLACEHOLDER_NAME ('{raw_name}')"
        
    # Check if purely digits
    digits_only = re.sub(r'\D', '', normalized)
    if len(digits_only) == len(normalized.replace(' ', '')):
        return True, f"PURELY_NUMERIC_NAME ('{raw_name}')"
        
    return False, ""


def filter_generic_names(
    df: pd.DataFrame,
    name_col: str,
    role: str = "chemist",
    additional_keywords: Optional[List[str]] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Filters out records with generic/placeholder names from a DataFrame.
    
    Args:
        df: Input DataFrame
        name_col: Name of the column containing store/chemist names
        role: Entity role ('chemist', 'doctor')
        additional_keywords: Optional list of additional custom generic keywords
        
    Returns:
        Tuple of:
            - clean_df: DataFrame with non-generic, branded records retained
            - generic_df: DataFrame of flagged & removed generic records
            - summary: Dictionary with filtering metrics and statistics
    """
    if df.empty or name_col not in df.columns:
        return df.copy(), pd.DataFrame(), {
            "total_records": len(df),
            "retained_records": len(df),
            "generic_excluded_records": 0,
            "generic_percentage": 0.0
        }
        
    df_work = df.copy()
    
    is_generic_flags = []
    reasons = []
    
    for _, val in df_work[name_col].items():
        flag, reason = is_generic_name(val, additional_keywords=additional_keywords)
        is_generic_flags.append(flag)
        reasons.append(reason)
        
    df_work["is_generic_name"] = is_generic_flags
    df_work["generic_exclusion_reason"] = reasons
    
    generic_mask = df_work["is_generic_name"] == True
    generic_df = df_work[generic_mask].copy().reset_index(drop=True)
    clean_df = df_work[~generic_mask].copy().drop(columns=["is_generic_name", "generic_exclusion_reason"]).reset_index(drop=True)
    
    total = len(df_work)
    generic_count = len(generic_df)
    clean_count = len(clean_df)
    generic_pct = round((generic_count / total * 100), 2) if total > 0 else 0.0
    
    # Value counts of top generic names excluded
    top_excluded = generic_df[name_col].value_counts().head(10).to_dict() if generic_count > 0 else {}
    
    summary = {
        "role": role,
        "name_column": name_col,
        "total_records": total,
        "retained_records": clean_count,
        "generic_excluded_records": generic_count,
        "generic_percentage": generic_pct,
        "top_excluded_names": top_excluded
    }
    
    logger.info(
        f"Generic name filter for {role}: retained {clean_count}/{total} distinctive records. "
        f"Excluded {generic_count} ({generic_pct}%) generic/placeholder names."
    )
    
    return clean_df, generic_df, summary
