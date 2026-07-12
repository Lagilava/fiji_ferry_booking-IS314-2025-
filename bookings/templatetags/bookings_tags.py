from django import template

register = template.Library()


@register.filter
def lookup(value, key):
    """
    Safely retrieves a value from a dictionary, list, or object by key or index.

    Usage in template:
        {{ my_dict|lookup:"key" }}
        {{ my_list|lookup:"0" }}
        {{ my_object|lookup:"attribute" }}
    """
    try:
        if isinstance(value, dict):
            return value.get(key)
        elif isinstance(value, (list, tuple)) and str(key).isdigit():
            index = int(key)
            return value[index] if 0 <= index < len(value) else None
        else:
            return getattr(value, key)
    except (KeyError, AttributeError, IndexError, TypeError, ValueError):
        return None


@register.filter(name="replace")
def replace_filter(value, args):
    """
    Replaces all occurrences of a substring with another string.

    Usage in template:
        {{ my_string|replace:"old,new" }}

    Example:
        {{ "Fiji Ferry"|replace:"Fiji,Suva" }} → "Suva Ferry"
    """
    if not isinstance(value, str):
        return value

    try:
        old, new = args.split(",", 1)
    except ValueError:
        # Incorrect format passed, e.g. missing comma
        return value

    return value.replace(old, new)


@register.filter
def split(value, delimiter=","):
    """
    Splits a string by the given delimiter and returns a list.

    Example:
        {% for num in "1,2,3"|split:"," %}
            {{ num }}
        {% endfor %}
    """
    if not isinstance(value, str):
        return []
    return value.split(delimiter)


@register.filter
def times(value):
    """
    Returns a range from 0 to value-1.
    Usage: {% for i in 5|times %}
    """
    try:
        return range(int(value))
    except (ValueError, TypeError):
        return range(0)

@register.filter
def dict_get(d, key):
    """Safely get a dictionary value by key"""
    if not isinstance(d, dict):
        return ""
    return d.get(key, "")

@register.filter
def zip(a, b):
    return zip(a, b)

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def duration_hm(td):
    """
    Render a timedelta as a compact crossing time.
    Usage: {{ route.estimated_duration|duration_hm }} -> "4h" or "4h 30m"
    """
    try:
        total_minutes = int(td.total_seconds() // 60)
    except (AttributeError, TypeError):
        return ""
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"

@register.filter(name='mul')
def mul(value, arg):
    """
    Multiplies a numeric value by a given argument.
    Usage: {{ number|mul:factor }}
    Example: {{ 2|mul:150 }} -> 300
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
