"""Pure fare/pricing calculations.

Extracted from views.py: these are side-effect-free functions (no request, no
DB writes) so they are trivially unit-testable and reusable by the service layer.
"""
import logging
import re
from decimal import Decimal

from .models import AddOn

logger = logging.getLogger(__name__)


def calculate_cargo_price(weight_kg, cargo_type):
    try:
        weight_kg = Decimal(str(weight_kg))
        if weight_kg <= 0:
            raise ValueError("Weight must be positive")

        base_rate = Decimal('5.00')  # base price per kg

        # Multipliers for cargo categories
        type_multiplier = {
            'Light Cargo': Decimal('1.2'),   # parcels, boxes
            'Heavy Cargo': Decimal('2.0'),   # machinery, materials
            'Bulk Cargo': Decimal('1.5'),    # produce, sand, fuel
            'Livestock': Decimal('2.5')      # animals require special handling
        }

        multiplier = type_multiplier.get(cargo_type, Decimal('1.0'))
        return weight_kg * base_rate * multiplier

    except (ValueError, TypeError) as e:
        logger.error(
            f"Invalid cargo weight or type: weight_kg={weight_kg}, cargo_type={cargo_type}, error={str(e)}"
        )
        raise ValueError("Invalid cargo weight or type")


def calculate_addon_price(addon_type, quantity):
    try:
        quantity = int(quantity)
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if addon_type not in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            raise ValueError(f"Invalid add-on type: {addon_type}")
        prices = {
            'premium_seating': Decimal('20.00'),
            'priority_boarding': Decimal('10.00'),
            'cabin': Decimal('50.00'),
            'meal_breakfast': Decimal('15.00'),
            'meal_lunch': Decimal('15.00'),
            'meal_dinner': Decimal('15.00'),
            'meal_snack': Decimal('5.00')
        }
        return prices.get(addon_type, Decimal('0.00')) * Decimal(quantity)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid addon quantity: addon_type={addon_type}, quantity={quantity}, error={str(e)}")
        raise ValueError("Invalid addon quantity")


def calculate_passenger_price(adults, children, infants, schedule):
    base_fare = schedule.route.base_fare or Decimal('35.50')
    return (
        Decimal(adults) * base_fare +
        Decimal(children) * base_fare * Decimal('0.5') +
        Decimal(infants) * base_fare * Decimal('0.1')
    )


def calculate_vehicle_price(vehicle_type, dimensions):
    try:
        # Example pricing logic based on vehicle type and dimensions
        base_price = Decimal('50.00')  # Base price for vehicles
        type_multiplier = {
            'car': Decimal('1.0'),
            'sedan': Decimal('1.0'),
            'truck': Decimal('1.5'),
            'van': Decimal('1.5'),
            'motorcycle': Decimal('0.5')
        }
        multiplier = type_multiplier.get(vehicle_type.lower(), Decimal('1.0'))

        # Optional: Adjust price based on dimensions (e.g., LxWxH in cm)
        if dimensions and re.match(r'^\d+x\d+x\d+$', dimensions):
            length, width, height = map(int, dimensions.split('x'))
            volume = length * width * height / 1_000_000  # Convert to cubic meters
            volume_surcharge = Decimal(volume) * Decimal('10.00')  # $10 per cubic meter
        else:
            volume_surcharge = Decimal('0.00')

        return base_price * multiplier + volume_surcharge
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid vehicle data: vehicle_type={vehicle_type}, dimensions={dimensions}, error={str(e)}")
        raise ValueError("Invalid vehicle type or dimensions")


def calculate_total_price(adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons,
                          add_vehicle=False, vehicle_type=None, vehicle_dimensions=None):
    passenger_price = calculate_passenger_price(adults, children, infants, schedule)
    cargo_price = calculate_cargo_price(weight_kg, cargo_type) if add_cargo and cargo_type and weight_kg else Decimal('0.00')
    vehicle_price = calculate_vehicle_price(vehicle_type, vehicle_dimensions) if add_vehicle and vehicle_type and vehicle_dimensions else Decimal('0.00')
    addon_price = sum(calculate_addon_price(addon['type'], addon['quantity']) for addon in addons)
    return passenger_price + cargo_price + vehicle_price + addon_price
