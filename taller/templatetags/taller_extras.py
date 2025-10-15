from django import template
from taller.models import Gasto

register = template.Library()

@register.filter(name='get_class_name')
def get_class_name(value):
    return value.__class__.__name__

@register.filter(name='is_gasto')
def is_gasto(class_name):
    return class_name == 'Gasto'