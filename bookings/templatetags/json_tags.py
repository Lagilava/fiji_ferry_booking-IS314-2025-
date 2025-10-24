# bookings/templatetags/json_tags.py
from django import template
import json

register = template.Library()

@register.filter
def to_json(value):
    try:
        return json.dumps(value)
    except TypeError:
        # fallback for non-serializable objects
        if hasattr(value, '_perm_cache'):
            return json.dumps(dict(value))
        return json.dumps(str(value))

