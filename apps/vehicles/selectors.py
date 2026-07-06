from typing import List
from apps.vehicles.models import Vehicle

def get_vehicles_by_fcai_category(fcai_category: str) -> List[Vehicle]:
    """
    Returns a list of all vehicles matching the given FCAI category.
    Used primarily by the rating engine to fetch peers.
    """
    return list(Vehicle.objects.filter(fcai_category=fcai_category))
