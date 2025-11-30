# taller/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal

class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, unique=True)
    
    TIPO_DOCUMENTO_CHOICES = [
        ('DNI', 'DNI'),
        ('NIE', 'NIE'),
        ('NIF', 'NIF (Empresas)'),
    ]
    tipo_documento = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES, default='DNI', null=True, blank=True)
    documento_fiscal = models.CharField(max_length=20, null=True, blank=True, help_text="Número de DNI, NIE o NIF")
    direccion_fiscal = models.CharField(max_length=255, null=True, blank=True, help_text="Calle, Número, Piso, Puerta")
    codigo_postal_fiscal = models.CharField(max_length=10, null=True, blank=True)
    ciudad_fiscal = models.CharField(max_length=100, null=True, blank=True)
    provincia_fiscal = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        if self.documento_fiscal: self.documento_fiscal = self.documento_fiscal.upper()
        if self.direccion_fiscal: self.direccion_fiscal = self.direccion_fiscal.upper()
        if self.ciudad_fiscal: self.ciudad_fiscal = self.ciudad_fiscal.upper()
        if self.provincia_fiscal: self.provincia_fiscal = self.provincia_fiscal.upper()
        super(Cliente, self).save(*args, **kwargs)

class Vehiculo(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    kilometraje = models.IntegerField(default=0)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.matricula})"
    def save(self, *args, **kwargs):
        self.matricula = self.matricula.upper()
        self.marca = self.marca.upper()
        self.modelo = self.modelo.upper()
        super(Vehiculo, self).save(*args, **kwargs)

class OrdenDeReparacion(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE)
    fecha_entrada = models.DateTimeField(auto_now_add=True)
    problema = models.TextField()
    presupuesto_origen = models.OneToOneField('Presupuesto', on_delete=models.SET_NULL, null=True, blank=True, related_name='orden_generada')
    ESTADO_CHOICES = [
        ('Recibido', 'Recibido'),
        ('En Diagnostico', 'En Diagnóstico'),
        ('Esperando Piezas', 'Esperando Piezas'),
        ('En Reparacion', 'En Reparación'),
        ('Listo para Recoger', 'Listo para Recoger'),
        ('Entregado', 'Entregado'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Recibido')
    def __str__(self):
        return f"Orden #{self.id} - {self.vehiculo.matricula} ({self.cliente.nombre})"
    def save(self, *args, **kwargs):
        self.problema = self.problema.upper()
        super(OrdenDeReparacion, self).save(*args, **kwargs)

class Empleado(models.Model):
    nombre = models.CharField(max_length=100)
    def __str__(self):
        return self.nombre
    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        super(Empleado, self).save(*args, **kwargs)

class Gasto(models.Model):
    CATEGORIA_CHOICES = [
        ('Repuestos', 'Repuestos'),
        ('Sueldos', 'Sueldos'),
        ('Herramientas', 'Herramientas'),
        ('Suministros', 'Suministros'),
        ('Gasolina/Diesel', 'Gasolina/Diesel'),
        ('Otros', 'Otros'),
        ('Compra de Consumibles', 'Compra de Consumibles'),
    ]
    
    METODO_PAGO_CHOICES = [
        ('EFECTIVO', 'Efectivo (Caja)'),
        ('CUENTA_ERIKA', 'Cuenta Erika (Compartida)'),
        ('CUENTA_TALLER', 'Cuenta Taller (Nueva)'),
    ]
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')
    
    fecha = models.DateField(default=timezone.now)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    
    # --- VINCULACIÓN: Ahora se permite vincular a Orden (Preferido) o Vehículo (Histórico) ---
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)
    # ---------------------------------------------------------------------------------------

    empleado = models.ForeignKey(Empleado, on_delete=models.SET_NULL, null=True, blank=True)
    pagado_con_tarjeta = models.BooleanField(default=False)

    def __str__(self):
        display_importe = self.importe if self.importe is not None else 0
        return f"{self.fecha} - {self.get_categoria_display()} - {display_importe}€ [{self.get_metodo_pago_display()}]"

    def save(self, *args, **kwargs):
        if self.descripcion:
            self.descripcion = self.descripcion.upper()
        super(Gasto, self).save(*args, **kwargs)

class Ingreso(models.Model):
    CATEGORIA_CHOICES = [
        ('Taller', 'Pago de Cliente (Taller)'),
        ('Grua', 'Servicio de Grúa'),
        ('Otras Ganancias', 'Otras Ganancias'),
        ('Otros', 'Otros Ingresos'),
    ]
    
    METODO_PAGO_CHOICES = [
        ('EFECTIVO', 'Efectivo (Caja)'),
        ('CUENTA_ERIKA', 'Cuenta Erika (Compartida)'),
        ('CUENTA_TALLER', 'Cuenta Taller (Nueva)'),
    ]
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')

    fecha = models.DateField(default=timezone.now)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255)
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True)
    es_tpv = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.fecha} - {self.get_categoria_display()} - {self.importe}€ [{self.get_metodo_pago_display()}]"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Ingreso, self).save(*args, **kwargs)

class Factura(models.Model):
    orden = models.OneToOneField(OrdenDeReparacion, on_delete=models.CASCADE)
    fecha_emision = models.DateField(auto_now_add=True)
    es_factura = models.BooleanField(default=True)
    numero_factura = models.IntegerField(null=True, blank=True, unique=True, editable=False)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    notas_cliente = models.TextField(null=True, blank=True, help_text="Notas adicionales para el cliente")

    def __str__(self):
        if self.es_factura:
            return f"Factura Nº {self.numero_factura} para Orden #{self.orden.id}"
        else:
            return f"Recibo #{self.id} para Orden #{self.orden.id}"

    def save(self, *args, **kwargs):
        if self.notas_cliente:
            self.notas_cliente = self.notas_cliente.upper()
        super(Factura, self).save(*args, **kwargs)

class LineaFactura(models.Model):
    factura = models.ForeignKey(Factura, related_name='lineas', on_delete=models.CASCADE)
    TIPO_CHOICES = [
        ('Repuesto', 'Repuesto'),
        ('Consumible', 'Consumible'),
        ('Externo', 'Trabajo Externo'),
        ('Mano de Obra', 'Mano de Obra'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    @property
    def total_linea(self):
        return (self.cantidad or 0) * (self.precio_unitario or 0)
    def __str__(self):
        return f"Línea de {self.tipo} para Factura #{self.factura.id}"
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaFactura, self).save(*args, **kwargs)

class TipoConsumible(models.Model):
    nombre = models.CharField(max_length=100)
    unidad_medida = models.CharField(max_length=20)
    nivel_minimo_stock = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    def __str__(self):
        return self.nombre
    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        self.unidad_medida = self.unidad_medida.upper()
        super(TipoConsumible, self).save(*args, **kwargs)

class CompraConsumible(models.Model):
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    fecha_compra = models.DateField()
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    coste_total = models.DecimalField(max_digits=10, decimal_places=2)
    coste_por_unidad = models.DecimalField(max_digits=10, decimal_places=4, editable=False)
    def save(self, *args, **kwargs):
        if self.cantidad and self.cantidad > 0 and self.coste_total is not None:
            self.coste_por_unidad = self.coste_total / self.cantidad
        else:
             self.coste_por_unidad = Decimal('0.0000')
        super().save(*args, **kwargs)
    def __str__(self):
        return f"Compra de {self.cantidad} {self.tipo.unidad_medida}"

class UsoConsumible(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.CASCADE)
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    cantidad_usada = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_uso = models.DateField(default=timezone.now)
    def __str__(self):
        return f"Uso de {self.cantidad_usada} {self.tipo.unidad_medida}"

class FotoVehiculo(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, related_name='fotos', on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to='fotos_vehiculos/')
    descripcion = models.CharField(max_length=50)
    def __str__(self):
        return f"Foto {self.descripcion} para Orden #{self.orden.id}"
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(FotoVehiculo, self).save(*args, **kwargs)

class Presupuesto(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)
    matricula_nueva = models.CharField(max_length=20, blank=True, null=True)
    marca_nueva = models.CharField(max_length=50, blank=True, null=True)
    modelo_nuevo = models.CharField(max_length=50, blank=True, null=True)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    problema_o_trabajo = models.TextField()
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Aceptado', 'Aceptado'),
        ('Rechazado', 'Rechazado'),
        ('Convertido', 'Convertido a Orden'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente')
    aplicar_iva = models.BooleanField(default=True, help_text="Si marcado, se aplica el 21% de IVA y se muestran datos fiscales.")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Presupuesto #{self.id} - {self.cliente.nombre}"

    def save(self, *args, **kwargs):
        if self.matricula_nueva: self.matricula_nueva = self.matricula_nueva.upper()
        if self.marca_nueva: self.marca_nueva = self.marca_nueva.upper()
        if self.modelo_nuevo: self.modelo_nuevo = self.modelo_nuevo.upper()
        self.problema_o_trabajo = self.problema_o_trabajo.upper()
        super(Presupuesto, self).save(*args, **kwargs)

class LineaPresupuesto(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, related_name='lineas', on_delete=models.CASCADE)
    TIPO_CHOICES = LineaFactura.TIPO_CHOICES
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    precio_unitario_estimado = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total_linea_estimado(self):
        return (self.cantidad or 0) * (self.precio_unitario_estimado or 0)

    def __str__(self):
        return f"Línea ({self.tipo}) para Presupuesto #{self.presupuesto.id}"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaPresupuesto, self).save(*args, **kwargs)

class TipoConsumibleStock(TipoConsumible):
    class Meta:
        proxy = True
        verbose_name = "Stock de Consumible"
        verbose_name_plural = "Stocks de Consumibles"
    @property
    def stock_actual(self):
        total_comprado = CompraConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad'))['total'] or Decimal('0.00')
        total_usado_ordenes = UsoConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad_usada'))['total'] or Decimal('0.00')
        total_ajustado = AjusteStockConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad_ajustada'))['total'] or Decimal('0.00')
        return (total_comprado - total_usado_ordenes + total_ajustado).quantize(Decimal('0.01'))
    @property
    def alerta_stock(self):
        if self.nivel_minimo_stock is not None and self.stock_actual <= self.nivel_minimo_stock: return "⚠️ BAJO"
        return "✅ OK" if self.nivel_minimo_stock is not None else "N/A"

class AjusteStockConsumible(models.Model):
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE, verbose_name="Tipo de Consumible")
    cantidad_ajustada = models.DecimalField(max_digits=10, decimal_places=2)
    motivo = models.CharField(max_length=255)
    fecha_ajuste = models.DateField(default=timezone.now, verbose_name="Fecha del Ajuste")
    class Meta:
        verbose_name = "Ajuste de Stock"
        verbose_name_plural = "Ajustes de Stock"
        ordering = ['-fecha_ajuste', '-id']
    def save(self, *args, **kwargs):
        self.motivo = self.motivo.upper()
        super().save(*args, **kwargs)