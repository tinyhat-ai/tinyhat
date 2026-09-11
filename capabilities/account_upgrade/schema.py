"""Public tool inputs; the platform validates personal details and consent."""

from .tool import APPROVALS

SCHEMA = {
    "type": "object",
    "description": "Upgrade this Computer's existing individual owner for Stripe Projects. Check status first. Submit only accurate human-provided details and express acceptance of the displayed current terms. Does not purchase services or grant spending credit.",
    "properties": {
        "action": {"type": "string", "enum": ["status", "submit", "continue", "verification_link"]},
        "individual": {
            "type": "object",
            "additionalProperties": False,
            "required": ["given_name", "surname", "date_of_birth", "phone", "country", "address"],
            "properties": {
                "given_name": {"type": "string", "maxLength": 100},
                "surname": {"type": "string", "maxLength": 100},
                "date_of_birth": {
                    "type": "string",
                    "description": "Human's YYYY-MM-DD date of birth, age 18 or older.",
                },
                "phone": {"type": "string", "pattern": r"^\+[1-9][0-9]{7,14}$"},
                "country": {"type": "string", "minLength": 2, "maxLength": 2},
                "address": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["line1", "city", "postal_code"],
                    "properties": {
                        "line1": {"type": "string", "maxLength": 200},
                        "line2": {"type": ["string", "null"], "maxLength": 200},
                        "city": {"type": "string", "maxLength": 100},
                        "state": {"type": ["string", "null"], "maxLength": 100},
                        "postal_code": {"type": "string", "maxLength": 32},
                    },
                },
            },
        },
        "consent": {
            "type": "object",
            "additionalProperties": False,
            "description": "All points must be covered by the human's one express approval. A token or Computer assignment alone is not consent.",
            "required": ["terms_version", *APPROVALS],
            "properties": {
                "terms_version": {
                    "type": "string",
                    "description": "Exact version returned by status and presented to the human.",
                },
                **{key: {"type": "boolean", "enum": [True]} for key in APPROVALS},
            },
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}
