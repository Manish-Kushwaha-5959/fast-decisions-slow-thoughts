
# These are simulated values, not live service information.

SERVICE_STATUS = {
    "internet": {
        "status": "operational",
        "message": "The simulated internet service is operating normally."
    },
    "wifi": {
        "status": "operational",
        "message": "The simulated Wi-Fi service is operating normally."
    },
    "vpn": {
        "status": "degraded",
        "message": "The simulated VPN service is experiencing intermittent connectivity."
    },
    "email": {
        "status": "operational",
        "message": "The simulated email service is operating normally."
    },
    "payment_portal": {
        "status": "outage",
        "message": "The simulated payment portal is currently unavailable."
    },
    "student_portal": {
        "status": "operational",
        "message": "The simulated student portal is operating normally."
    }
}


SERVICE_ALIASES = {
    "wi-fi": "wifi",
    "wireless": "wifi",
    "network": "internet",
    "mail": "email",
    "payments": "payment_portal",
    "payment": "payment_portal",
    "student": "student_portal"
}


def check_service_status(service: str) -> dict:
    """
    Return the fixed simulated status of a named service.

    This function does not contact or inspect a real service.
    """
    if not isinstance(service, str) or not service.strip():
        raise ValueError("Service must be a non-empty string.")

    normalized_service = service.strip().lower().replace(" ", "_")
    canonical_service = SERVICE_ALIASES.get(
        normalized_service,
        normalized_service
    )

    result = SERVICE_STATUS.get(canonical_service)

    if result is None:
        return {
            "service": normalized_service,
            "status": "unknown",
            "message": (
                "The requested service is not present in the "
                "simulated service-status dataset."
            ),
            "source": "local_simulation"
        }

    return {
        "service": canonical_service,
        "status": result["status"],
        "message": result["message"],
        "source": "local_simulation"
    }
