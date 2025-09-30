"""
Location Service for QR Check-In Feature

Validates GPS coordinates against terminal locations using Haversine distance formula.
Supports multi-location validation with terminal-specific radius settings.
"""

import json
import math
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.models import Device


class LocationService:
    """Service for GPS validation and distance calculations"""

    def __init__(self):
        # Earth's radius in meters
        self.EARTH_RADIUS_METERS = 6371000

    def haversine_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """
        Calculate distance between two GPS coordinates using Haversine formula

        Args:
            lat1: Latitude of point 1 (degrees)
            lon1: Longitude of point 1 (degrees)
            lat2: Latitude of point 2 (degrees)
            lon2: Longitude of point 2 (degrees)

        Returns:
            Distance in meters
        """
        # Convert degrees to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Haversine formula
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = (
            math.sin(dlat / 2) ** 2 +
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))

        distance = self.EARTH_RADIUS_METERS * c
        return distance

    def get_terminal_location(
        self,
        terminal_id: int,
        db: Session
    ) -> Dict[str, any]:
        """
        Get terminal location data from Device metadata

        Args:
            terminal_id: ID of the terminal device
            db: Database session

        Returns:
            Dict containing:
            - latitude: Terminal GPS latitude
            - longitude: Terminal GPS longitude
            - radius: Validation radius in meters
            - location_name: Human-readable location name

        Raises:
            HTTPException: If terminal not found or has invalid GPS data
        """
        # Find terminal device
        terminal = db.query(Device).filter(
            Device.id == terminal_id,
            Device.device_type == "qr_terminal"
        ).first()

        if not terminal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบเครื่อง QR terminal ID {terminal_id}"
            )

        # Parse device metadata
        try:
            metadata = json.loads(terminal.device_metadata) if terminal.device_metadata else {}
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ข้อมูล GPS ของเครื่องไม่ถูกต้อง"
            )

        # Extract GPS data
        gps_data = metadata.get("gps", {})
        latitude = gps_data.get("latitude")
        longitude = gps_data.get("longitude")
        radius = gps_data.get("radius", 200)  # Default 200m radius

        if latitude is None or longitude is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="เครื่อง QR terminal ไม่มีข้อมูล GPS"
            )

        return {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius,
            "location_name": gps_data.get("location_name", f"Terminal {terminal_id}")
        }

    def validate_gps_location(
        self,
        user_lat: float,
        user_lon: float,
        user_accuracy: Optional[float],
        terminal_id: int,
        db: Session
    ) -> Dict[str, any]:
        """
        Validate user GPS location against terminal location

        Args:
            user_lat: User's GPS latitude
            user_lon: User's GPS longitude
            user_accuracy: GPS accuracy in meters (optional)
            terminal_id: ID of the terminal device
            db: Database session

        Returns:
            Dict containing:
            - valid: True if within radius
            - distance: Distance from terminal in meters
            - terminal_location: Terminal location data
            - message: Validation result message

        Raises:
            HTTPException: If GPS accuracy is insufficient
        """
        # Check GPS accuracy
        max_accuracy = 50  # Maximum 50m accuracy required
        if user_accuracy and user_accuracy > max_accuracy:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ความแม่นยำของ GPS ไม่เพียงพอ ({user_accuracy:.1f}m > {max_accuracy}m) กรุณาลองใหม่ในที่โล่ง"
            )

        # Get terminal location
        terminal_location = self.get_terminal_location(terminal_id, db)

        # Calculate distance
        distance = self.haversine_distance(
            user_lat,
            user_lon,
            terminal_location["latitude"],
            terminal_location["longitude"]
        )

        # Validate within radius
        allowed_radius = terminal_location["radius"]
        is_valid = distance <= allowed_radius

        result = {
            "valid": is_valid,
            "distance": round(distance, 2),
            "allowed_radius": allowed_radius,
            "terminal_location": terminal_location,
            "message": (
                f"อยู่ในพื้นที่ {terminal_location['location_name']} ({distance:.1f}m)"
                if is_valid
                else f"อยู่นอกพื้นที่ {terminal_location['location_name']} ({distance:.1f}m > {allowed_radius}m)"
            )
        }

        return result

    def validate_multiple_locations(
        self,
        user_lat: float,
        user_lon: float,
        user_accuracy: Optional[float],
        db: Session
    ) -> Dict[str, any]:
        """
        Validate user GPS against all available QR terminals

        Useful for mobile check-in where user might be near any terminal.

        Args:
            user_lat: User's GPS latitude
            user_lon: User's GPS longitude
            user_accuracy: GPS accuracy in meters (optional)
            db: Database session

        Returns:
            Dict containing:
            - valid: True if within any terminal's radius
            - nearest_terminal: Closest terminal data
            - all_terminals: List of all terminals with distances

        Raises:
            HTTPException: If no QR terminals found or GPS accuracy insufficient
        """
        # Check GPS accuracy
        max_accuracy = 50
        if user_accuracy and user_accuracy > max_accuracy:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ความแม่นยำของ GPS ไม่เพียงพอ ({user_accuracy:.1f}m > {max_accuracy}m)"
            )

        # Get all QR terminals
        terminals = db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        if not terminals:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบเครื่อง QR terminal ในระบบ"
            )

        # Calculate distances to all terminals
        terminal_distances = []
        nearest_valid_terminal = None
        min_distance = float('inf')

        for terminal in terminals:
            try:
                # Get terminal location
                terminal_location = self.get_terminal_location(terminal.id, db)

                # Calculate distance
                distance = self.haversine_distance(
                    user_lat,
                    user_lon,
                    terminal_location["latitude"],
                    terminal_location["longitude"]
                )

                is_within_radius = distance <= terminal_location["radius"]

                terminal_data = {
                    "terminal_id": terminal.id,
                    "location_name": terminal_location["location_name"],
                    "distance": round(distance, 2),
                    "radius": terminal_location["radius"],
                    "valid": is_within_radius
                }

                terminal_distances.append(terminal_data)

                # Track nearest valid terminal
                if is_within_radius and distance < min_distance:
                    min_distance = distance
                    nearest_valid_terminal = terminal_data

            except HTTPException:
                # Skip terminals with invalid GPS data
                continue

        # Sort by distance
        terminal_distances.sort(key=lambda x: x["distance"])

        return {
            "valid": nearest_valid_terminal is not None,
            "nearest_terminal": nearest_valid_terminal or terminal_distances[0] if terminal_distances else None,
            "all_terminals": terminal_distances
        }


# Global service instance
location_service = LocationService()
