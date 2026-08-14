# Module for handling road distance computations via OSRM or Simulation
import time
import requests
import random
from typing import Tuple, Optional
from src.utils import setup_logger

logger = setup_logger("routing_engine")

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
    timeout_sec: float = 5.0
) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Queries local OSRM endpoint to compute driving road distance between two points.
    
    Url format: {endpoint}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false
    Note that OSRM requires coordinates in [longitude, latitude] order.
    
    Returns:
        (road_distance_km, road_distance_status, error_message)
    """
    # Clean endpoint format
    base_url = endpoint.rstrip('/')
    
    # OSRM expects: lon1,lat1;lon2,lat2
    url = f"{base_url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    
    attempt = 0
    while attempt <= retries:
        try:
            response = requests.get(url, timeout=timeout_sec)
            
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
                # Retry for server-side errors or bad HTTP statuses
                logger.warning(
                    f"OSRM returned status {response.status_code} for URL {url}. "
                    f"Attempt {attempt + 1}/{retries + 1}."
                )
                
        except (requests.exceptions.RequestException, Exception) as e:
            logger.warning(
                f"Request failed: {str(e)} for URL {url}. "
                f"Attempt {attempt + 1}/{retries + 1}."
            )
            
        attempt += 1
        if attempt <= retries:
            time.sleep(0.5)  # Wait briefly before retrying
            
    # All attempts exhausted
    error_summary = f"Connection failed after {retries + 1} attempts."
    return None, "failed", error_summary

def query_graphhopper_road_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    endpoint: str = "http://localhost:8989",
    retries: int = 2,
    timeout_sec: float = 5.0
) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Queries local GraphHopper endpoint to compute driving road distance between two points.
    
    Url format: {endpoint}/route?point={lat1},{lon1}&point={lat2},{lon2}&profile=car&locale=en&points_encoded=false
    
    Returns:
        (road_distance_km, road_distance_status, error_message)
    """
    base_url = endpoint.rstrip('/')
    url = f"{base_url}/route?point={lat1},{lon1}&point={lat2},{lon2}&profile=car&locale=en&points_encoded=false"
    
    attempt = 0
    while attempt <= retries:
        try:
            response = requests.get(url, timeout=timeout_sec)
            
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
                
                logger.warning(
                    f"GraphHopper returned status {response.status_code} for URL {url}. "
                    f"Attempt {attempt + 1}/{retries + 1}."
                )
                
        except (requests.exceptions.RequestException, Exception) as e:
            err_msg = str(e)
            logger.warning(
                f"Request failed: {err_msg} for URL {url}. "
                f"Attempt {attempt + 1}/{retries + 1}."
            )
            
        attempt += 1
        if attempt <= retries:
            time.sleep(0.5)
            
    return None, "failed", f"Connection failed: {err_msg}"

