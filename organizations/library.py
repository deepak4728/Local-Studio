"""Starter details to collect for common organization categories."""

ORGANIZATION_PROFILE_LIBRARY = {
    "generic": [
        {"key": "phone", "label": "Contact phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Contact email", "type": "email", "placeholder": "hello@example.com"},
        {"key": "website", "label": "Website", "type": "url", "placeholder": "https://example.com"},
        {"key": "address", "label": "Address", "type": "text", "placeholder": "Street, city"},
    ],
    "restaurant": [
        {"key": "phone", "label": "Restaurant phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Order/contact email", "type": "email", "placeholder": "hello@example.com"},
        {"key": "address", "label": "Restaurant address", "type": "text", "placeholder": "Street, city"},
        {"key": "cuisine", "label": "Cuisine or specialties", "type": "text", "placeholder": "Rajasthani, North Indian"},
        {"key": "service_modes", "label": "Service options", "type": "text", "placeholder": "Dine in, takeaway, delivery"},
        {"key": "website", "label": "Website", "type": "url", "placeholder": "https://example.com"},
    ],
    "cafe": [
        {"key": "phone", "label": "Cafe phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Contact email", "type": "email", "placeholder": "hello@example.com"},
        {"key": "address", "label": "Cafe address", "type": "text", "placeholder": "Street, city"},
        {"key": "specialties", "label": "Coffee or food specialties", "type": "text", "placeholder": "Coffee, bakery, brunch"},
        {"key": "service_modes", "label": "Service options", "type": "text", "placeholder": "Dine in, takeaway, delivery"},
    ],
    "hospitality": [
        {"key": "phone", "label": "Guest services phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Reservations email", "type": "email", "placeholder": "stay@example.com"},
        {"key": "address", "label": "Property address", "type": "text", "placeholder": "Street, city"},
        {"key": "property_type", "label": "Property type", "type": "text", "placeholder": "Hotel, guesthouse, homestay"},
        {"key": "guest_services", "label": "Guest services", "type": "text", "placeholder": "Reservations, dining, events"},
    ],
    "restaurant_service": [
        {"key": "phone", "label": "Business phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Contact email", "type": "email", "placeholder": "hello@example.com"},
        {"key": "service_area", "label": "Service area", "type": "text", "placeholder": "Jaipur and nearby areas"},
        {"key": "service_types", "label": "Services offered", "type": "text", "placeholder": "Catering, tiffin, event service"},
        {"key": "website", "label": "Website", "type": "url", "placeholder": "https://example.com"},
    ],
    "retail": [
        {"key": "phone", "label": "Store phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Contact email", "type": "email", "placeholder": "shop@example.com"},
        {"key": "address", "label": "Store address", "type": "text", "placeholder": "Street, city"},
        {"key": "product_categories", "label": "Product categories", "type": "text", "placeholder": "Clothing, home goods"},
        {"key": "website", "label": "Online store", "type": "url", "placeholder": "https://example.com"},
    ],
    "healthcare": [
        {"key": "phone", "label": "Reception phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Appointment email", "type": "email", "placeholder": "care@example.com"},
        {"key": "address", "label": "Clinic address", "type": "text", "placeholder": "Street, city"},
        {"key": "specialties", "label": "Services or specialties", "type": "text", "placeholder": "Dental, general medicine"},
        {"key": "appointment_modes", "label": "Appointment options", "type": "text", "placeholder": "In person, phone, online"},
    ],
    "education": [
        {"key": "phone", "label": "Office phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Admissions email", "type": "email", "placeholder": "admissions@example.com"},
        {"key": "address", "label": "Campus address", "type": "text", "placeholder": "Street, city"},
        {"key": "programs", "label": "Programs or courses", "type": "text", "placeholder": "Languages, computer skills"},
        {"key": "age_group", "label": "Learner age group", "type": "text", "placeholder": "Children, adults, all ages"},
    ],
    "professional_services": [
        {"key": "phone", "label": "Business phone", "type": "tel", "placeholder": "+91 98765 43210"},
        {"key": "email", "label": "Contact email", "type": "email", "placeholder": "hello@example.com"},
        {"key": "address", "label": "Office address", "type": "text", "placeholder": "Street, city"},
        {"key": "expertise", "label": "Services or expertise", "type": "text", "placeholder": "Accounting, design, consulting"},
        {"key": "service_area", "label": "Service area", "type": "text", "placeholder": "Jaipur, remote, nationwide"},
        {"key": "website", "label": "Website", "type": "url", "placeholder": "https://example.com"},
    ],
}


def clean_profile_data(raw_data, business_type):
    """Keep submitted organization details limited to the category library."""
    import json

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data or "{}")
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw_data, dict):
        return {}
    allowed = {field["key"] for field in ORGANIZATION_PROFILE_LIBRARY.get(business_type, ORGANIZATION_PROFILE_LIBRARY["generic"])}
    if business_type == "generic":
        allowed.add("custom_category")
    return {
        key: str(value).strip()[:1000 if key != "custom_category" else 100]
        for key, value in raw_data.items()
        if key in allowed and isinstance(value, (str, int, float)) and str(value).strip()
    }
