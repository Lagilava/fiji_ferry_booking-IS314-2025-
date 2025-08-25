from django import template

register = template.Library()

@register.filter
def div(value, arg):
    """Divides value by arg and returns the quotient."""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def mod(value, arg):
    """Returns the remainder of value divided by arg."""
    try:
        return float(value) % float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''