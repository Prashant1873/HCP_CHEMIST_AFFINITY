def classify_precision_from_nominatim_raw(data_item):
    """
    Classifies a raw Nominatim API response result dict into precision levels:
    SHOP_LEVEL, BUILDING_LEVEL, STREET_LEVEL, LOCALITY_LEVEL, PINCODE_LEVEL, CITY_LEVEL, STATE_LEVEL, UNKNOWN
    """
    if not data_item:
        return "UNKNOWN"
        
    class_name = str(data_item.get('class', '')).lower()
    type_name = str(data_item.get('type', '')).lower()
    address = data_item.get('address', {})
    
    # 1. Shop Level: specific shop, amenity, healthcare, office, tourism, or pharmaceutical tags
    if (class_name in ["shop", "amenity", "office", "craft", "healthcare", "tourism"] or 
        type_name in ["pharmacy", "chemist", "drugstore", "hospital", "clinic", "doctors"]):
        return "SHOP_LEVEL"
        
    # 2. Building Level: house, building, residential, house number exists
    if type_name in ["house", "building", "yes", "residential"] or "house_number" in address:
        return "BUILDING_LEVEL"
        
    # 3. Street Level: highway class, road type, etc.
    if class_name == "highway" or type_name in ["road", "street", "footway", "residential", "trunk", "primary"]:
        return "STREET_LEVEL"
        
    # 4. Locality Level: suburb, neighbourhood, village, hamlet, ward
    if type_name in ["suburb", "neighbourhood", "village", "hamlet", "locality", "quarter", "borough", "ward"] or "suburb" in address:
        return "LOCALITY_LEVEL"
        
    # 5. Pincode Level: postcode centroids
    if type_name == "postcode" or class_name == "place" and type_name == "postcode" or "postcode" in address:
        return "PINCODE_LEVEL"
        
    # 6. City Level: city, town, city district, district
    if type_name in ["city", "town", "city_district", "district"] or "city" in address:
        return "CITY_LEVEL"
        
    # 7. State Level: state, administrative boundary
    if type_name in ["state", "province"] or "state" in address:
        return "STATE_LEVEL"
        
    return "UNKNOWN"

def get_fallback_precision_by_query_type(query_type):
    """
    Maps legacy/generic query types to precision classes as a fallback.
    """
    q_type = str(query_type).lower()
    
    if q_type == "full_address_name":
        return "SHOP_LEVEL"
    elif q_type == "full_address":
        return "STREET_LEVEL"
    elif q_type == "locality_city":
        return "LOCALITY_LEVEL"
    elif q_type in ["pincode_centroid", "pincode"]:
        return "PINCODE_LEVEL"
    elif q_type in ["city_centroid", "city"]:
        return "CITY_LEVEL"
    elif q_type in ["state_centroid", "state"]:
        return "STATE_LEVEL"
        
    return "UNKNOWN"
