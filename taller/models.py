# taller/models.py
from django.db import models
from django.utils import timezone # Importar timezone para la fecha de creación

class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, unique=True) # MANTENIDO COMO UNIQUE
    def __str__(self):
        return self.nombre
    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
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
        # La siguiente línea ha sido eliminada para corregir el error
        # self.estado = self.estado.upper()
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
        ('Gasolina/Diesel', 'Gasolina/Diesel'), # <-- NUEVA CATEGORÍA AÑADIDA AQUÍ
        ('Otros', 'Otros'),
        ('Compra de Consumibles', 'Compra de Consumibles'),
    ]
    fecha = models.DateField(auto_now_add=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True) # Referencia directa OK porque Vehiculo está definido antes
    empleado = models.ForeignKey(Empleado, on_delete=models.SET_NULL, null=True, blank=True) # Referencia directa OK porque Empleado está definido antes
    pagado_con_tarjeta = models.BooleanField(default=False)

    def __str__(self):
        display_importe = self.importe if self.importe is not None else 0
        pago = " [TARJETA]" if self.pagado_con_tarjeta else ""
        return f"{self.fecha} - {self.get_categoria_display()} - {display_importe}€{pago}"

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
    fecha = models.DateField(auto_now_add=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255)
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True)
    es_tpv = models.BooleanField(default=False)

    def __str__(self):
        metodo = " [TPV]" if self.es_tpv else ""
        return f"{self.fecha} - {self.get_categoria_display()} - {self.importe}€{metodo}"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Ingreso, self).save(*args, **kwargs)

class Factura(models.Model):
    orden = models.OneToOneField(OrdenDeReparacion, on_delete=models.CASCADE)
    fecha_emision = models.DateField(auto_now_add=True)
    es_factura = models.BooleanField(default=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    def __str__(self):
        documento = "Factura" if self.es_factura else "Recibo"
        return f"{documento} #{self.id} para Orden #{self.orden.id}"

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
        return self.cantidad * self.precio_unitario
    def __str__(self):
        return f"Línea de {self.tipo} para Factura #{self.factura.id}"
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaFactura, self).save(*args, **kwargs)

class TipoConsumible(models.Model):
    nombre = models.CharField(max_length=100)
    unidad_medida = models.CharField(max_length=20)
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
        if self.cantidad > 0:
            self.coste_por_unidad = self.coste_total / self.cantidad
        super().save(*args, **kwargs)
    def __str__(self):
        return f"Compra de {self.cantidad} {self.tipo.unidad_medida} de {self.tipo.nombre} el {self.fecha_compra}"

class UsoConsumible(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.CASCADE)
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    cantidad_usada = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_uso = models.DateField(auto_now_add=True)
    def __str__(self):
        return f"Uso de {self.cantidad_usada} {self.tipo.unidad_medida} en Orden #{self.orden.id}"

class FotoVehiculo(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, related_name='fotos', on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to='fotos_vehiculos/')
    descripcion = models.CharField(max_length=50)
    def __str__(self):
        return f"Foto {self.descripcion} para Orden #{self.orden.id}"
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(FotoVehiculo, self).save(*args, **kwargs)

# --- NUEVOS MODELOS PARA PRESUPUESTOS ---

class Presupuesto(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, help_text="Cliente al que se dirige el presupuesto.")
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True, help_text="Vehículo asociado (opcional, si ya existe).")
    # Campos para datos del vehículo si no existe uno asociado aún
    matricula_nueva = models.CharField(max_length=20, blank=True, null=True, help_text="Matrícula si es un vehículo nuevo.")
    marca_nueva = models.CharField(max_length=50, blank=True, null=True, help_text="Marca si es un vehículo nuevo.")
    modelo_nuevo = models.CharField(max_length=50, blank=True, null=True, help_text="Modelo si es un vehículo nuevo.")

    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    problema_o_trabajo = models.TextField(help_text="Descripción del problema o trabajo a presupuestar.")
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Aceptado', 'Aceptado'),
        ('Rechazado', 'Rechazado'),
        ('Convertido', 'Convertido a Orden'), # Nuevo estado para indicar que se usó para una orden
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente')
    total_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Cálculo total del presupuesto.")

    def __str__(self):
        identificador_vehiculo = self.vehiculo.matricula if self.vehiculo else self.matricula_nueva if self.matricula_nueva else "Sin vehículo especificado"
        return f"Presupuesto #{self.id} - {self.cliente.nombre} ({identificador_vehiculo})"

    def save(self, *args, **kwargs):
        # Convertir a mayúsculas los campos nuevos de vehículo si existen
        if self.matricula_nueva:
            self.matricula_nueva = self.matricula_nueva.upper()
        if self.marca_nueva:
            self.marca_nueva = self.marca_nueva.upper()
        if self.modelo_nuevo:
            self.modelo_nuevo = self.modelo_nuevo.upper()
        self.problema_o_trabajo = self.problema_o_trabajo.upper()

        # Podríamos recalcular el total_estimado aquí si quisiéramos
        # total = self.lineas.aggregate(Sum(F('cantidad') * F('precio_unitario_estimado')))['total'] or Decimal('0.00')
        # self.total_estimado = total # Haría falta importar F y Decimal

        super(Presupuesto, self).save(*args, **kwargs)

class LineaPresupuesto(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, related_name='lineas', on_delete=models.CASCADE)
    TIPO_CHOICES = LineaFactura.TIPO_CHOICES # Reutilizamos las mismas opciones que en Factura
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    precio_unitario_estimado = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total_linea_estimado(self):
        return self.cantidad * self.precio_unitario_estimado

    def __str__(self):
        return f"Línea ({self.tipo}) para Presupuesto #{self.presupuesto.id}"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaPresupuesto, self).save(*args, **kwargs)