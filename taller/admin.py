from django.contrib import admin
from .models import (
    Cliente, 
    Vehiculo, 
    OrdenDeReparacion, 
    Gasto, 
    Empleado, 
    Ingreso, 
    Factura,
    TipoConsumible,
    CompraConsumible
)

# Personalización para OrdenDeReparacion
class OrdenDeReparacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'vehiculo', 'cliente', 'estado', 'fecha_entrada')
    list_filter = ('estado', 'fecha_entrada')
    search_fields = ('vehiculo__matricula', 'cliente__nombre', 'vehiculo__marca', 'vehiculo__modelo')

# Personalización para CompraConsumible (para ver el coste autocalculado)
class CompraConsumibleAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'fecha_compra', 'cantidad', 'coste_total', 'coste_por_unidad')
    readonly_fields = ('coste_por_unidad',) # Hacemos que el campo autocalculado no se pueda editar

# Registramos todos los modelos
admin.site.register(Cliente)
admin.site.register(Vehiculo)
admin.site.register(Gasto)
admin.site.register(Empleado)
admin.site.register(Ingreso)
admin.site.register(Factura)
admin.site.register(TipoConsumible) # <-- NUEVO
admin.site.register(CompraConsumible, CompraConsumibleAdmin) # <-- NUEVO y con personalización
admin.site.register(OrdenDeReparacion, OrdenDeReparacionAdmin)