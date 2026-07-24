from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from organizacion.models import Cliente, EquipoCliente
from productos.models import Producto, ProductoStock
from utils.validators import validar_factura_entrada
from .utils import compute_vida_util_usage


class Movimiento(models.Model):
    MOV_TYPES = [
        ('entrada', 'Entrada de inventario'),
        ('salida', 'Salida de inventario'),
    ]

    tipo = models.CharField(max_length=10, choices=MOV_TYPES)
    creado = models.DateTimeField(default=timezone.now)
    creado_por = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='movimientos_creados'
    )

    aprobado = models.BooleanField(default=False)
    aprobado_fecha = models.DateTimeField(blank=True, null=True)
    user_aprueba = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='movimientos_aprobados'
    )
    comentarios = models.TextField(blank=True, null=True)
    sucursal = models.ForeignKey('organizacion.Sucursal', on_delete=models.PROTECT, related_name='movimientos')

    class Meta:
        ordering = ['-creado']
        verbose_name = 'Movimiento'
        verbose_name_plural = 'Movimientos'

    def __str__(self):
        return f'Movimiento {self.id} ({self.tipo})'

    @transaction.atomic
    def approve(self, user):
        if self.items.exclude(producto__status='activo').exists():
            raise ValueError('No se pueden aprobar movimientos con productos inactivos.')

        if user.profile.rol != 'admin':
            raise PermissionError('Solo administradores pueden aprobar movimientos.')
        if not user.profile.sucursales.filter(id=self.sucursal_id).exists():
            raise PermissionError('No tienes permisos para aprobar movimientos de esta sucursal.')
        if self.aprobado:
            raise ValueError('Movimiento ya aprobado.')

        if hasattr(self, 'detalle_entrada'):
            pass
            # validar_factura_entrada(self.detalle_entrada.numero_factura, self.items.all())

        self.aprobado = True
        self.aprobado_fecha = timezone.now()
        self.user_aprueba = user
        self.save()

        # Procesar cada item según el tipo de movimiento
        if hasattr(self, 'detalle_entrada'):
            for item in self.items.all():
                stock, _ = ProductoStock.objects.select_for_update().get_or_create(
                    producto=item.producto,
                    sucursal=self.sucursal,
                    defaults={'cantidad': 0},
                )
                stock.cantidad = F('cantidad') + item.cantidad
                stock.save(update_fields=['cantidad'])
        elif hasattr(self, 'detalle_salida'):
            es_renta = self.detalle_salida.subtipo == 'renta'
            for item in self.items.all():
                if es_renta:
                    item.verificar_vida_util()
                stock = ProductoStock.objects.select_for_update().get(
                    producto=item.producto,
                    sucursal=self.sucursal,
                )
                if stock.cantidad < item.cantidad:
                    raise ValueError(
                        f'No hay suficientes unidades de {item.producto.codigo_interno} '
                        f'({stock.cantidad} disponibles, {item.cantidad} requeridas).'
                    )
                stock.cantidad = F('cantidad') - item.cantidad
                stock.save(update_fields=['cantidad'])
        else:
            raise RuntimeError('Movimiento sin detalle asociado.')


class DetalleEntrada(models.Model):
    movimiento = models.OneToOneField(
        Movimiento, on_delete=models.CASCADE, related_name='detalle_entrada'
    )
    numero_factura = models.CharField(max_length=100)
    recibido_por = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-movimiento__creado']
        verbose_name = 'Detalles de entrada'
        verbose_name_plural = 'Detalles de entradas'

    def __str__(self):
        return f'Detalle Entrada de Movimiento {self.movimiento.id}'


class DetalleSalida(models.Model):
    SUBTIPOS = [
        ('venta', 'Venta'),
        ('renta', 'Renta'),
    ]

    movimiento = models.OneToOneField(
        Movimiento, on_delete=models.CASCADE, related_name='detalle_salida'
    )
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='salidas_inventario')
    tecnico = models.CharField(max_length=120, blank=True, null=True)
    subtipo = models.CharField(max_length=10, choices=SUBTIPOS)

    class Meta:
        ordering = ['-movimiento__creado']
        verbose_name = 'Detalles de salida'
        verbose_name_plural = 'Detalles de salidas'

    def __str__(self):
        return f'Detalle Salida de Movimiento {self.movimiento.id}'


class MovimientoItem(models.Model):
    movimiento = models.ForeignKey(
        Movimiento, on_delete=models.CASCADE, related_name='items'
    )
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()

    # Campos únicamente para movimientos de salida
    equipo_cliente = models.ForeignKey(
        EquipoCliente, on_delete=models.SET_NULL, null=True, blank=True
    )
    contador_uso_snapshot = models.PositiveIntegerField(null=True, blank=True)
    cambio_anticipado = models.BooleanField(default=False)
    motivo_cambio = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'{self.producto.codigo_interno} x {self.cantidad}'

    # Salida
    def verificar_vida_util(self):
        if not self.equipo_cliente:
            raise ValueError(f'Item {self.producto.codigo_interno} no tiene equipo_cliente asignado.')

        usage = compute_vida_util_usage(
            producto=self.producto,
            equipo_cliente=self.equipo_cliente,
            movimiento_creado=self.movimiento.creado,
            exclude_item_pk=self.pk,
        )

        if not usage['alcanzada'] and not self.cambio_anticipado:
            raise ValueError(
                f'{self.producto.codigo_interno} aún no alcanza su vida útil entre entregas '
                f'({usage["mensaje"]}). Use cambio anticipado para forzar.'
            )

        self.contador_uso_snapshot = self.equipo_cliente.contador_uso
        self.save(update_fields=['contador_uso_snapshot'])

    class Meta:
        ordering = ['-movimiento__creado', 'producto__codigo_interno']
        verbose_name = 'Item de movimiento'
        verbose_name_plural = 'Items de movimientos'
