# Configuration module for doctor-chemist mapping tool

# Earth Radius in Kilometers for Haversine distance
EARTH_RADIUS_KM = 6371.0088

# India approximate bounding box
INDIA_LAT_MIN = 6.0
INDIA_LAT_MAX = 38.0
INDIA_LON_MIN = 68.0
INDIA_LON_MAX = 98.0

# Inverted coordinate ranges (latitude matches India longitude range, longitude matches India latitude range)
INVERT_LAT_MIN = 68.0
INVERT_LAT_MAX = 98.0
INVERT_LON_MIN = 6.0
INVERT_LON_MAX = 38.0

# Search Defaults
DEFAULT_CANDIDATE_K = 50
DEFAULT_FINAL_N = 5
DEFAULT_MAX_DISTANCE_KM = 1.0  # Hard filter: exclude any chemist farther than 1 km (1000 meters)
VERIFY_PINCODES_DEFAULT = True  # Run GeoJSON pincode boundary validation by default

# Potential latitude column names
LATITUDE_COLUMNS = [
    "latitude", "lat", "doctor_lat", "dr_lat", "chemist_lat", 
    "retailer_lat", "hcp_lat", "Latitude", "LATITUDE", "Lat", "LAT"
]

# Potential longitude column names
LONGITUDE_COLUMNS = [
    "longitude", "lon", "lng", "long", "doctor_lon", "doctor_lng", 
    "dr_lon", "dr_lng", "chemist_lon", "chemist_lng", "retailer_lon", 
    "retailer_lng", "Longitude", "LONGITUDE", "Lon", "LON", "LNG", "Long"
]

# Potential doctor identifier columns
DOCTOR_ID_COLUMNS = [
    "doctor_id", "dr_id", "hcp_id", "customer_id", "client_doctor_id", 
    "doctor_code", "dr_code", "Doc ID", "doc_id", "doctor_key", "dr_key"
]

# Potential doctor name columns
DOCTOR_NAME_COLUMNS = [
    "doctor_name", "dr_name", "hcp_name", "customer_name", 
    "DOCTOR NAME", "dr_name_clean", "name", "Name"
]

# Potential chemist identifier columns
CHEMIST_ID_COLUMNS = [
    "chemist_id", "retailer_id", "account_id", "outlet_id", "store_id", 
    "chemist_code", "retailer_code", "IQVIA ID", "iqvia_id", "chemist_key"
]

# Potential chemist name columns
CHEMIST_NAME_COLUMNS = [
    "chemist_name", "retailer_name", "outlet_name", "store_name", 
    "chem_name", "retailer_name_clean", "name", "Name"
]

# Potential pincode columns
PINCODE_COLUMNS = [
    "pincode", "pin", "pin_code", "zip", "zip_code", 
    "Pincode", "chem_pincode", "doctor_pincode"
]

# Potential city column names
CITY_COLUMNS = [
    "city", "chem_city", "chemist_city", "Doctor City", "doctor_city", 
    "dr_city", "City", "CITY", "chemist_chem_city"
]

# Pincode GeoJSON validation settings
DEFAULT_PINCODE_GEOJSON = "india_pincode.geojson"
DEFAULT_PINCODE_TOLERANCE_KM = 0.5  # Allowed distance (km) outside polygon boundary for GPS jitter / border leniency

# Generic Name Filtering settings
EXCLUDE_GENERIC_CHEMIST_NAMES = True  # Automatically filter generic names like Chemist, Medical, Pharmacy, Drug Store
ADDITIONAL_GENERIC_KEYWORDS = []  # Extra user-specified keywords to exclude


