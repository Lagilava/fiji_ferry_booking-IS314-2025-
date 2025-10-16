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