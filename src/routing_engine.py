# Module for handling road distance computations via OSRM, GraphHopper, or Simulation
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random
import threading
from typing import Tuple, Optional
from src.utils import setup_logger

logger = setup_logger("routing_engine")

# Thread-local storage for HTTP sessions
_local_storage = threading.local()

def get_routing_session() -> requests.Session:
    """Returns a thread-local requests.Session with connection pooling and retries."""
    if not hasattr(_local_storage, "session"):
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _local_storage.session = session
    return _local_storage.session


def simulate_road_distance(air_distance_km: float) -> float:
    """
    Simulates driving road distance based on air distance.
    Applies a standard circuity factor (1.15x to 1.50x) plus small random noise.
    """
    if air_distance_km <= 0:
        return 0.0
    circuity = random.uniform(1.15, 1.50)
    noise = random.uniform(0.01, 0.20)
    return (air_distance_km * circuity) + noise


def query_osrm_road_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    endpoint: str = "http://localhost:5000",
    retries: int = 2,
    timeout_sec: float = 5.0,
    session: Optional[requests.Session] = None
) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Queries local OSRM endpoint to compute driving road distance between two points.
    Url format: {endpoint}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false
    """
    base_url = endpoint.rstrip('/')
    url = f"{base_url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    http_client = session or get_routing_session()
    
    err_summary = "Unknown error"
    attempt = 0
    while attempt <= retries:
        try:
            response = http_client.get(url, timeout=timeout_sec)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                    distance_meters = data["routes"][0]["distance"]
                    distance_km = distance_meters / 1000.0
                    return distance_km, "success", None
                else:
                    err_msg = f"OSRM error code: {data.get('code', 'Unknown')}"
                    return None, "failed", err_msg
            else:
                err_summary = f"OSRM status {response.status_code}"
                logger.warning(f"OSRM returned status {response.status_code} for URL {url}. Attempt {attempt + 1}/{retries + 1}.")
                
        except (requests.exceptions.RequestException, Exception) as e:
            err_summary = str(e)
            logger.warning(f"Request failed: {err_summary} for URL {url}. Attempt {attempt + 1}/{retries + 1}.")
            
        attempt += 1
        if attempt <= retries:
            time.sleep(0.3)
            
    return None, "failed", f"Connection failed after {retries + 1} attempts: {err_summary}"


def query_graphhopper_road_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    endpoint: str = "http://localhost:8989",
    retries: int = 2,
    timeout_sec: float = 5.0,
    session: Optional[requests.Session] = None
) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Queries local GraphHopper endpoint to compute driving road distance between two points.
    Url format: {endpoint}/route?point={lat1},{lon1}&point={lat2},{lon2}&profile=car&locale=en&points_encoded=false
    """
    base_url = endpoint.rstrip('/')
    url = f"{base_url}/route?point={lat1},{lon1}&point={lat2},{lon2}&profile=car&locale=en&points_encoded=false"
    http_client = session or get_routing_session()
    
    err_msg = "Unknown error"
    attempt = 0
    while attempt <= retries:
        try:
            response = http_client.get(url, timeout=timeout_sec)
            
            if response.status_code == 200:
                data = response.json()
                if "paths" in data and len(data["paths"]) > 0:
                    distance_meters = data["paths"][0]["distance"]
                    distance_km = distance_meters / 1000.0
                    return distance_km, "success", None
                else:
                    return None, "failed", "GraphHopper returned empty paths list"
            else:
                try:
                    err_json = response.json()
                    err_msg = err_json.get("message", f"HTTP status {response.status_code}")
                except Exception:
                    err_msg = f"HTTP status {response.status_code}"
                
                logger.warning(f"GraphHopper returned status {response.status_code} for URL {url}. Attempt {attempt + 1}/{retries + 1}.")
                
        except (requests.exceptions.RequestException, Exception) as e:
            err_msg = str(e)
            logger.warning(f"Request failed: {err_msg} for URL {url}. Attempt {attempt + 1}/{retries + 1}.")
            
        attempt += 1
        if attempt <= retries:
            time.sleep(0.3)
            
    return None, "failed", f"Connection failed: {err_msg}"
