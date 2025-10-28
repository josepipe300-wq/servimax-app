# taller/admin.py
from django.contrib import admin
from .models import (
    Cliente,
    Vehiculo,
    OrdenDeReparacion,
    Gasto,
    Empleado,
    Ingreso,
    Factura,
    LineaFactura, # Asegúrate de importar LineaFactura
    TipoConsumible,
    CompraConsumible,
    UsoConsumible, # Asegúrate de importar UsoConsumible
    Presupuesto, # Asegúrate de importar Presupuesto
    LineaPresupuesto, # Asegúrate de importar LineaPresupuesto
    FotoVehiculo, # Asegúrate de importar FotoVehiculo
    TipoConsumibleStock # Importar el nuevo modelo proxy
)
# Importaciones adicionales necesarias para el cálculo en el admin de stock
from django.db.models import Sum
from decimal import Decimal

# Personalización para OrdenDeReparacion (Existente)
class OrdenDeReparacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'vehiculo', 'cliente', 'estado', 'fecha_entrada')
    list_filter = ('estado', 'fecha_entrada')
    search_fields = ('vehiculo__matricula', 'cliente__nombre', 'vehiculo__marca', 'vehiculo__modelo')

# Personalización para CompraConsumible (Existente)
class CompraConsumibleAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'fecha_compra', 'cantidad', 'coste_total', 'coste_por_unidad')
    readonly_fields = ('coste_por_unidad',)

# Personalización para TipoConsumible (Modificada)
class TipoConsumibleAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'unidad_medida', 'nivel_minimo_stock') # Mostrar en la lista
    fields = ('nombre', 'unidad_medida', 'nivel_minimo_stock') # Organizar el formulario de edición

# --- NUEVA CLASE ADMIN PARA STOCK ---
@admin.register(TipoConsumibleStock)
class TipoConsumibleStockAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'unidad_medida', 'stock_actual', 'nivel_minimo_stock', 'alerta_stock')
    # Hacemos que solo se pueda ver, no editar directamente desde aquí
    readonly_fields = ('stock_actual', 'alerta_stock')
    list_filter = ('unidad_medida',) # Opcional: filtro por unidad
    search_fields = ('nombre',) # Opcional: buscador por nombre

    # Para evitar que aparezca el botón "Añadir Stock de Consumible"
    def has_add_permission(self, request):
        return False

    # Opcional: Para evitar que se pueda borrar desde esta vista
    def has_delete_permission(self, request, obj=None):
        return False

# Registramos todos los modelos
admin.site.register(Cliente)
admin.site.register(Vehiculo)
admin.site.register(Gasto)
admin.site.register(Empleado)
admin.site.register(Ingreso)
admin.site.register(Factura)
admin.site.register(LineaFactura)
admin.site.register(TipoConsumible, TipoConsumibleAdmin) # Usar la clase personalizada
admin.site.register(CompraConsumible, CompraConsumibleAdmin) # Usar la clase personalizada
admin.site.register(UsoConsumible)
admin.site.register(OrdenDeReparacion, OrdenDeReparacionAdmin) # Usar la clase personalizada
admin.site.register(Presupuesto)
admin.site.register(LineaPresupuesto)
admin.site.register(FotoVehiculo)

# Nota: TipoConsumibleStock se registra usando el decorador @admin.register arriba