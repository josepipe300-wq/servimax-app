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
    LineaFactura,
    TipoConsumible,
    CompraConsumible,
    UsoConsumible,
    Presupuesto,
    LineaPresupuesto,
    FotoVehiculo,
    TipoConsumibleStock,
    AjusteStockConsumible,  # <-- Con su coma
    Cita                    # <-- El nuevo modelo limpio
)
from django.db.models import Sum
from decimal import Decimal
from .models import Empleado, Asistencia, AdelantoSueldo

# Personalización para OrdenDeReparacion
class OrdenDeReparacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'vehiculo', 'cliente', 'estado', 'fecha_entrada')
    list_filter = ('estado', 'fecha_entrada')
    search_fields = ('vehiculo__matricula', 'cliente__nombre', 'vehiculo__marca', 'vehiculo__modelo')

# Personalización para CompraConsumible
class CompraConsumibleAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'fecha_compra', 'cantidad', 'coste_total', 'coste_por_unidad')
    readonly_fields = ('coste_por_unidad',)

# Personalización para TipoConsumible
class TipoConsumibleAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'unidad_medida', 'nivel_minimo_stock')
    fields = ('nombre', 'unidad_medida', 'nivel_minimo_stock')

# --- NUEVA CLASE ADMIN PARA AJUSTES ---
@admin.register(AjusteStockConsumible)
class AjusteStockConsumibleAdmin(admin.ModelAdmin):
    list_display = ('fecha_ajuste', 'tipo', 'cantidad_ajustada', 'motivo')
    list_filter = ('tipo', 'fecha_ajuste')
    search_fields = ('tipo__nombre', 'motivo')

# Clase Admin para la vista de Stock (Existente)
@admin.register(TipoConsumibleStock)
class TipoConsumibleStockAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'unidad_medida', 'stock_actual', 'nivel_minimo_stock', 'alerta_stock')
    readonly_fields = ('stock_actual', 'alerta_stock')
    list_filter = ('unidad_medida',)
    search_fields = ('nombre',)

    def has_add_permission(self, request):
        return False
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
admin.site.register(TipoConsumible, TipoConsumibleAdmin)
admin.site.register(CompraConsumible, CompraConsumibleAdmin)
admin.site.register(UsoConsumible)
admin.site.register(OrdenDeReparacion, OrdenDeReparacionAdmin)
admin.site.register(Presupuesto)
admin.site.register(LineaPresupuesto)
admin.site.register(FotoVehiculo)

# --- NUEVO: Panel de control para las Citas ---
@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'nombre_cliente', 'vehiculo_info', 'estado', 'presupuesto')
    list_filter = ('estado', 'fecha_hora')
    search_fields = ('nombre_cliente', 'vehiculo_info', 'motivo')
    date_hierarchy = 'fecha_hora'


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ('empleado', 'fecha', 'hora_entrada', 'hora_salida', 'pagado')
    list_filter = ('fecha', 'pagado', 'empleado')
    search_fields = ('empleado__nombre',)

@admin.register(AdelantoSueldo)
class AdelantoSueldoAdmin(admin.ModelAdmin):
    list_display = ('empleado', 'fecha', 'importe', 'motivo', 'liquidado')
    list_filter = ('liquidado', 'empleado', 'fecha')