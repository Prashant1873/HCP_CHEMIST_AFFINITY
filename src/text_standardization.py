import re

# Indian address abbreviations dictionary for expansion
# Pre-compile regex patterns for performance on 145k+ records
ABBREVIATIONS = {
    # Note: using \b for word boundaries. For special symbols like N/, we handle manually or with customized regex.
    re.compile(r'\bN/\b', re.IGNORECASE): 'NEAR',
    re.compile(r'\bNR\b', re.IGNORECASE): 'NEAR',
    re.compile(r'\bO/\b', re.IGNORECASE): 'OPPOSITE',
    re.compile(r'\bOPP\b', re.IGNORECASE): 'OPPOSITE',
    re.compile(r'\bRD\b', re.IGNORECASE): 'ROAD',
    re.compile(r'\bST\b', re.IGNORECASE): 'STREET',
    re.compile(r'\bMKT\b', re.IGNORECASE): 'MARKET',
    re.compile(r'\bCLNY\b', re.IGNORECASE): 'COLONY',
    re.compile(r'\bHOSP\b', re.IGNORECASE): 'HOSPITAL',
    re.compile(r'\bCHWK\b', re.IGNORECASE): 'CHOWK',
    re.compile(r'\bXING\b', re.IGNORECASE): 'CROSSING',
    re.compile(r'\bPO\b', re.IGNORECASE): 'POST OFFICE',
    re.compile(r'\bPS\b', re.IGNORECASE): 'POLICE STATION',
    re.compile(r'\bBLDG\b', re.IGNORECASE): 'BUILDING',
    re.compile(r'\bAPPT\b', re.IGNORECASE): 'APARTMENT',
    re.compile(r'\bFLT\b', re.IGNORECASE): 'FLAT',
    re.compile(r'\bCTR\b', re.IGNORECASE): 'CENTER',
    re.compile(r'\bCOMP\b', re.IGNORECASE): 'COMPLEX',
    re.compile(r'\bLNM\b', re.IGNORECASE): 'LANDMARK',
    re.compile(r'\bSTN\b', re.IGNORECASE): 'STATION',
    re.compile(r'\bBUS STD\b', re.IGNORECASE): 'BUS STAND',
    re.compile(r'\bMED\b', re.IGNORECASE): 'MEDICAL',
    re.compile(r'\bPHARMA\b', re.IGNORECASE): 'PHARMACY'
}

def clean_general_text(text):
    """
    Performs standard string cleaning: collapses spaces, handles non-breaking spaces, and standardizes punctuation.
    """
    if not isinstance(text, str):
        return ""
    
    # Replace non-breaking spaces (\xa0) with normal spaces
    text = text.replace('\xa0', ' ').replace('\u200b', ' ')
    
    # Standardize punctuation (multiple commas, repeated spaces, etc.)
    text = re.sub(r'[,;]+', ',', text)  # Collapse multiple commas
    text = re.sub(r'\s+', ' ', text)     # Collapse spaces
    
    return text.strip()

def expand_abbreviations(text):
    """
    Replaces common Indian address abbreviations with full word equivalents.
    """
    if not text:
        return ""
    
    # Apply abbreviation expansion
    for pattern, replacement in ABBREVIATIONS.items():
        text = pattern.sub(replacement, text)
        
    # Collapse any new spacing issues introduced by replacements
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_phone_numbers(text):
    """
    Extracts Indian mobile and landline numbers from text using regex.
    """
    if not text:
        return ""
    
    # Pattern for 10-digit mobile numbers (with optional +91, 91 or 0 prefix)
    # and landline formats like 080-2345678 or 044 12345678
    phone_pattern = r'(?:\+?91[-.\s]?)?[6-9]\d{9}|\b0\d{2,4}[-.\s]?\d{6,8}\b|\b\d{10}\b'
    
    phones = re.findall(phone_pattern, text)
    
    # Clean phone formats (keep numbers only)
    cleaned_phones = []
    for phone in phones:
        digits_only = re.sub(r'\D', '', phone)
        # Normalize to standard 10 digit if it has +91/91/0 prefix and is 11/12 digits
        if len(digits_only) == 12 and digits_only.startswith('91'):
            digits_only = digits_only[2:]
        elif len(digits_only) == 11 and digits_only.startswith('0'):
            digits_only = digits_only[1:]
            
        # Avoid duplicate extractions
        if digits_only and digits_only not in cleaned_phones:
            cleaned_phones.append(digits_only)
            
    return ", ".join(cleaned_phones)

def standardize_chemist_name(name):
    """
    Cleans chemist name for standardization.
    """
    name_clean = clean_general_text(name)
    return name_clean.upper()

def process_address(address):
    """
    Applies text cleaning, abbreviations, phone number extraction, and generates matching tokens.
    Returns a dictionary of address processing outputs.
    """
    # 1. Clean general text
    addr_clean = clean_general_text(address)
    
    # 2. Extract phone numbers before expanding abbreviations (just in case)
    phones = extract_phone_numbers(addr_clean)
    
    # 3. Expand abbreviations
    addr_expanded = expand_abbreviations(addr_clean)
    
    # 4. Tokenize (for matching & audit)
    # Clean words: letters and digits only
    words = re.findall(r'\b[A-Z0-9]+\b', addr_expanded.upper())
    tokens = ", ".join(words)
    
    return {
        'cleaned_address': addr_expanded.upper(),
        'address_tokens': tokens,
        'extracted_phone_numbers': phones
    }
