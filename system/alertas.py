from datetime import timedelta

from django.db.models import Count, F
from django.utils import timezone

from movimiento.models import MovimientoItem
from productos.models import Producto
from productos.queries import productos_queryset

from .models import AlertaInventario, ConfiguracionSistema


def _crear_si_no_existe(producto, tipo, mensaje, sucursal_id):
    if not AlertaInventario.objects.filter(
        producto=producto, tipo_alerta=tipo, resuelto=False, sucursal_id=sucursal_id
    ).exists():
        AlertaInventario.objects.create(
            producto=producto, tipo_alerta=tipo, mensaje=mensaje, sucursal_id=sucursal_id
        )
        return True
    return False


def generar_low_stock(sucursal_id):
    productos = productos_queryset(sucursal_id=sucursal_id)

    ids_bajos = set(
        productos.filter(cantidad_disponible__lte=F('min_stock'))
        .values_list('pk', flat=True)
    )

    alertas_existentes = AlertaInventario.objects.filter(
        tipo_alerta='low_stock', resuelto=False, sucursal_id=sucursal_id
    )

    creadas = 0
    for p in productos.filter(pk__in=ids_bajos):
        if not alertas_existentes.filter(producto=p).exists():
            AlertaInventario.objects.create(
                producto=p, tipo_alerta='low_stock', sucursal_id=sucursal_id,
                mensaje=(
                    f"{p.descripcion}: {p.cantidad_disponible} uds disponibles "
                    f"(mínimo: {p.min_stock})"
                )
            )
            creadas += 1

    resueltas = alertas_existentes.exclude(producto__in=ids_bajos).update(resuelto=True)

    return creadas, resueltas


def generar_old_product(sucursal_id):
    dias = ConfiguracionSistema.get_int('alerta_old_product_dias', 365)
    hace_limite = timezone.now() - timedelta(days=dias)

    ids_antiguos = set(
        Producto.objects.filter(
            status='activo',
            lotes__fecha_entrada__lt=hace_limite,
            lotes__sucursal=sucursal_id,
            lotes__unidades__status='disponible',
        ).values_list('pk', flat=True).distinct()
    )

    alertas_existentes = AlertaInventario.objects.filter(
        tipo_alerta='old_product', resuelto=False, sucursal_id=sucursal_id
    )

    creadas = 0
    for p in Producto.objects.filter(pk__in=ids_antiguos).only('pk', 'descripcion'):
        if not alertas_existentes.filter(producto=p).exists():
            AlertaInventario.objects.create(
                producto=p, tipo_alerta='old_product', sucursal_id=sucursal_id,
                mensaje=(
                    f"{p.descripcion} tiene lotes con más de {dias} días de antigüedad "
                    f"con existencias disponibles."
                )
            )
            creadas += 1

    resueltas = alertas_existentes.exclude(producto__in=ids_antiguos).update(resuelto=True)

    return creadas, resueltas


def generar_unusual_movement(sucursal_id):
    now = timezone.now()
    hace_30_dias = now - timedelta(days=30)
    hace_6_meses = now - timedelta(days=180)

    movs_recientes = (
        MovimientoItem.objects.filter(
            movimiento__tipo='salida',
            movimiento__aprobado=True,
            movimiento__sucursal=sucursal_id,
            movimiento__creado__gte=hace_30_dias,
        )
        .values('producto_id')
        .annotate(total=Count('id'))
    )

    counts_recientes = {m['producto_id']: m['total'] for m in movs_recientes}

    multiplicador = ConfiguracionSistema.get_int('alerta_unusual_multiplicador', 3)

    creadas = 0
    for producto_id, total_actual in counts_recientes.items():
        hist_items = MovimientoItem.objects.filter(
            movimiento__tipo='salida',
            movimiento__aprobado=True,
            movimiento__sucursal=sucursal_id,
            movimiento__creado__gte=hace_6_meses,
            movimiento__creado__lt=hace_30_dias,
            producto_id=producto_id,
        ).count()

        hist_promedio = hist_items / 6 if hist_items > 0 else 0

        if hist_promedio > 0 and total_actual > hist_promedio * multiplicador:
            try:
                producto = Producto.objects.only('pk', 'descripcion').get(pk=producto_id)
            except Producto.DoesNotExist:
                continue

            mensaje = (
                f"{producto.descripcion}: {total_actual} salidas en 30 días "
                f"(promedio histórico: {hist_promedio:.1f} mensual)"
            )
            if _crear_si_no_existe(producto, 'unusual_movement', mensaje, sucursal_id):
                creadas += 1

    return creadas, 0


def generar_high_rotation(sucursal_id, top_n=None):
    if top_n is None:
        top_n = ConfiguracionSistema.get_int('alerta_high_rotation_top_n', 10)
    now = timezone.now()
    hace_30_dias = now - timedelta(days=30)

    top_productos = list(
        MovimientoItem.objects.filter(
            movimiento__aprobado=True,
            movimiento__sucursal=sucursal_id,
            movimiento__creado__gte=hace_30_dias,
        )
        .values('producto_id')
        .annotate(total=Count('id'))
        .order_by('-total')[:top_n]
    )

    creadas = 0
    for entry in top_productos:
        try:
            producto = Producto.objects.only('pk', 'descripcion').get(pk=entry['producto_id'])
        except Producto.DoesNotExist:
            continue

        mensaje = (
            f"{producto.descripcion}: {entry['total']} movimientos en los últimos "
            f"30 días (alta rotación)"
        )
        if _crear_si_no_existe(producto, 'high_rotation', mensaje, sucursal_id):
            creadas += 1

    top_ids = [entry['producto_id'] for entry in top_productos]
    resueltas = AlertaInventario.objects.filter(
        tipo_alerta='high_rotation', resuelto=False, sucursal_id=sucursal_id
    ).exclude(producto_id__in=top_ids).update(resuelto=True)

    return creadas, resueltas
