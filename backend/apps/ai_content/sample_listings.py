"""Sample listings for the caption-quality review run.

Chosen to probe the edges rather than to flatter the prompt. Several are
deliberately sparse: a listing with a price and nothing else is where a model
is most tempted to invent, and those rows are the most informative ones to read
in the output.
"""

from __future__ import annotations

from decimal import Decimal

from apps.listings.models import PropertyType

SAMPLE_LISTINGS: list[dict] = [
    {
        "_note": "Complete, feature-rich. The easy case.",
        "address": "12 Harbour View Terrace",
        "city": "Manly", "state": "NSW", "postcode": "2095", "country": "Australia",
        "price": Decimal("1850000"), "bedrooms": 4, "bathrooms": Decimal("2.5"),
        "square_footage": 2400, "property_type": PropertyType.HOUSE,
        "features": ["Ocean views", "Double garage", "North-facing garden",
                     "Renovated kitchen", "Solar panels"],
        "description": "A light-filled family home a short walk from the beach.",
    },
    {
        "_note": "Price only. Maximum temptation to invent.",
        "address": "5 Short Street", "city": "Newtown", "state": "NSW",
        "price": Decimal("780000"), "property_type": PropertyType.APARTMENT,
        "features": [],
    },
    {
        "_note": "No price at all — must not guess one.",
        "address": "88 Rosewood Avenue", "city": "Hawthorn", "state": "VIC",
        "bedrooms": 3, "bathrooms": Decimal("1"), "property_type": PropertyType.HOUSE,
        "features": ["Period features", "Established garden"],
    },
    {
        "_note": "Studio, tiny. Should not be padded out.",
        "address": "9/40 Crown Street", "city": "Darlinghurst", "state": "NSW",
        "postcode": "2010", "price": Decimal("495000"), "bedrooms": 1,
        "bathrooms": Decimal("1"), "square_footage": 420,
        "property_type": PropertyType.APARTMENT, "features": ["Balcony"],
    },
    {
        "_note": "Luxury, high price. Watch for investment framing.",
        "address": "1 Wolseley Road", "city": "Point Piper", "state": "NSW",
        "postcode": "2027", "price": Decimal("24500000"), "bedrooms": 6,
        "bathrooms": Decimal("5.5"), "square_footage": 8200,
        "property_type": PropertyType.HOUSE,
        "features": ["Harbour frontage", "Pool", "Wine cellar", "Lift", "Boat house"],
    },
    {
        "_note": "Land only. No rooms exist — a bedroom count would be invented.",
        "address": "Lot 14 Ridgeline Drive", "city": "Byron Bay", "state": "NSW",
        "price": Decimal("1200000"), "square_footage": 43560,
        "property_type": PropertyType.LAND, "features": ["Hinterland outlook"],
    },
    {
        "_note": "Commercial. Prime ground for zoning and yield claims.",
        "address": "210 Collins Street", "city": "Melbourne", "state": "VIC",
        "postcode": "3000", "price": Decimal("3400000"), "square_footage": 5100,
        "property_type": PropertyType.COMMERCIAL, "features": ["Street frontage"],
    },
    {
        "_note": "Half bathroom, to see how .5 is written.",
        "address": "22 Elm Grove", "city": "Toorak", "state": "VIC",
        "price": Decimal("2650000"), "bedrooms": 4, "bathrooms": Decimal("3.5"),
        "square_footage": 3100, "property_type": PropertyType.TOWNHOUSE,
        "features": ["Home cinema", "Wine storage"],
    },
    {
        "_note": "Long feature list — does it cherry-pick sensibly?",
        "address": "7 Lakeside Court", "city": "Noosa Heads", "state": "QLD",
        "postcode": "4567", "price": Decimal("4100000"), "bedrooms": 5,
        "bathrooms": Decimal("4"), "square_footage": 4600,
        "property_type": PropertyType.HOUSE,
        "features": ["Lake frontage", "Pool", "Tennis court", "Guest house",
                     "Solar and battery", "Triple garage", "Outdoor kitchen",
                     "Home office", "Cellar", "Jetty"],
    },
    {
        "_note": "Bare minimum: type and city only.",
        "city": "Fremantle", "state": "WA", "property_type": PropertyType.HOUSE,
        "features": [],
    },
    {
        "_note": "Duplex, no features, modest price.",
        "address": "3B Wattle Street", "city": "Coburg", "state": "VIC",
        "price": Decimal("845000"), "bedrooms": 3, "bathrooms": Decimal("2"),
        "property_type": PropertyType.DUPLEX, "features": [],
    },
    {
        "_note": "Description mentions a number the fields do not.",
        "address": "16 Kingsway", "city": "Cronulla", "state": "NSW",
        "price": Decimal("1650000"), "bedrooms": 3, "bathrooms": Decimal("2"),
        "property_type": PropertyType.APARTMENT,
        "features": ["Ocean glimpses"],
        "description": "Set on the 4th floor of a well-kept building.",
    },
    {
        "_note": "Condo with body-corporate adjacent features.",
        "address": "1204/9 Marina Boulevard", "city": "Gold Coast", "state": "QLD",
        "postcode": "4217", "price": Decimal("1150000"), "bedrooms": 2,
        "bathrooms": Decimal("2"), "square_footage": 1180,
        "property_type": PropertyType.CONDO,
        "features": ["Gym", "Pool", "Concierge", "Secure parking"],
    },
    {
        "_note": "Very large area, no bedrooms — sqft must not become rooms.",
        "address": "44 Industrial Way", "city": "Wetherill Park", "state": "NSW",
        "price": Decimal("5900000"), "square_footage": 32000,
        "property_type": PropertyType.COMMERCIAL, "features": ["Loading dock", "High clearance"],
    },
    {
        "_note": "Warm/family framing, mid market.",
        "address": "31 Orchard Road", "city": "Adelaide", "state": "SA",
        "postcode": "5000", "price": Decimal("920000"), "bedrooms": 4,
        "bathrooms": Decimal("2"), "square_footage": 1950,
        "property_type": PropertyType.HOUSE,
        "features": ["Fireplace", "Large backyard", "Ducted heating"],
    },
]
