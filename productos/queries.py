from datetime import timedelta
from collections import defaultdict

from django.db.models import Count, OuterRef, Subquery, IntegerField, Value, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Lote, Producto, Unidad, Equipo
from movimiento.models import MovimientoItem
from system.models import ConfiguracionSistema


def productos_queryset(sucursal_id=None):
    unidades_subquery = (
        Unidad.objects.filter(lote__producto=OuterRef('pk'), status='disponible')
        .values('lote__producto')
        .annotate(total=Count('id'))
    )

    if sucursal_id is not None:
        unidades_subquery = unidades_subquery.filter(lote__sucursal=sucursal_id)

    return (
        Producto.objects.exclude(status='inactivo')
        .select_related('categoria', 'proveedor')
        .prefetch_related(
            Prefetch(
                'equipos',
                queryset=Equipo.objects.filter(activo=True, marca__activo=True).select_related('marca')
            ),
        )
        .annotate(
            cantidad_disponible=Coalesce(
                Subquery(unidades_subquery.values('total'), output_field=IntegerField()),
                Value(0)
            )
        )
    )


def lotes_queryset(sucursal_id=None):
    qs = Lote.objects.exclude(producto__status='inactivo')

    if sucursal_id is not None:
        qs = qs.filter(sucursal=sucursal_id)

    return (
        qs
        .select_related('producto')
        .prefetch_related(
            Prefetch(
                'producto__equipos',
                queryset=Equipo.objects.filter(activo=True, marca__activo=True).select_related('marca')
            ),
        )
        .annotate(cantidad_restante=Count('unidades', filter=Q(unidades__status='disponible')))
    )


def rendimiento_data(sucursal_id, fecha_inicio=None, fecha_fin=None):
    """Rendimiento real de piezas/consumibles por producto.

    Para cada par (producto, equipo_cliente) se ordenan las salidas aprobadas con
    contador_uso_snapshot y se toman las diferencias consecutivas: cada delta es el
    uso real consumido entre dos entregas. Se compara contra Producto.vida_util
    (uso esperado entre entregas).

    Devuelve una lista de dicts por producto:
        producto_id, codigo_interno, descripcion, vida_util,
        ciclos (nº de deltas), uso_promedio, ratio (uso_promedio / vida_util)
    ratio < 1 => la pieza se consume antes de lo esperado (rinde menos);
    ratio > 1 => dura más de lo esperado.
    """
    items = (
        MovimientoItem.objects.filter(
            movimiento__tipo='salida',
            movimiento__aprobado=True,
            movimiento__sucursal=sucursal_id,
            equipo_cliente__isnull=False,
            contador_uso_snapshot__isnull=False,
        )
        .select_related('producto', 'movimiento')
        .order_by('producto_id', 'equipo_cliente_id', 'movimiento__creado')
    )

    if fecha_inicio:
        items = items.filter(movimiento__creado__date__gte=fecha_inicio)
    if fecha_fin:
        items = items.filter(movimiento__creado__date__lte=fecha_fin)

    # Series (fecha, snapshot) por (producto, equipo_cliente), ya ordenadas por fecha.
    series = defaultdict(list)
    productos_info = {}
    for it in items:
        series[(it.producto_id, it.equipo_cliente_id)].append(
            (it.movimiento.creado, it.contador_uso_snapshot)
        )
        productos_info[it.producto_id] = it.producto

    # Deltas consecutivos por producto: unidades (snapshot) y días (fecha entrega).
    # TODO: el cálculo no considera la cantidad (MovimientoItem.cantidad) de cada
    # salida. Asume 1 pieza por entrega. Si una salida entrega cantidad > 1, el uso
    # real por pieza sería delta / cantidad_de_la_entrega_previa (las piezas que
    # cubrieron ese intervalo). Definir si las N piezas se consumen juntas o se
    # almacenan antes de hacer el cálculo sensible a la cantidad.
    deltas_unid = defaultdict(list)
    deltas_dias = defaultdict(list)
    for (producto_id, _eq), pares in series.items():
        for (c_ant, s_ant), (c_act, s_act) in zip(pares, pares[1:]):
            d_unid = s_act - s_ant
            if d_unid >= 0:
                deltas_unid[producto_id].append(d_unid)
            d_dias = (c_act - c_ant).days
            if d_dias >= 0:
                deltas_dias[producto_id].append(d_dias)

    resultado = []
    for producto_id in set(deltas_unid) | set(deltas_dias):
        producto = productos_info[producto_id]
        fila = {
            'producto_id': producto_id,
            'codigo_interno': producto.codigo_interno,
            'descripcion': producto.descripcion,
            'vida_util_unidades': producto.vida_util_unidades,
            'vida_util_dias': producto.vida_util_dias,
            'ciclos': 0, 'uso_promedio': None, 'ratio': None,
            'ciclos_dias': 0, 'dias_promedio': None, 'ratio_dias': None,
        }
        du = deltas_unid.get(producto_id)
        if du and producto.vida_util_unidades:
            up = sum(du) / len(du)
            fila['ciclos'] = len(du)
            fila['uso_promedio'] = round(up, 2)
            fila['ratio'] = round(up / producto.vida_util_unidades, 2)
        dd = deltas_dias.get(producto_id)
        if dd and producto.vida_util_dias:
            dp = sum(dd) / len(dd)
            fila['ciclos_dias'] = len(dd)
            fila['dias_promedio'] = round(dp, 2)
            fila['ratio_dias'] = round(dp / producto.vida_util_dias, 2)
        # Incluir solo si se computó al menos un ratio.
        if fila['ratio'] is not None or fila['ratio_dias'] is not None:
            resultado.append(fila)

    # Peor rendimiento primero (ratio más bajo disponible).
    resultado.sort(key=lambda r: r['ratio'] if r['ratio'] is not None else r['ratio_dias'])
    return resultado


def reorden_data(sucursal_id):
    """Sugerencias heurísticas de reorden por proveedor.

    NO es predicción con IA: se basa en el consumo promedio mensual histórico.
        consumo_mensual = unidades salidas aprobadas en los últimos N meses / N
        dias_cobertura  = cantidad_disponible / (consumo_mensual / 30)
        sugerir si: cantidad_disponible <= min_stock  O  dias_cobertura < lead_time
        cantidad_sugerida = consumo_mensual * meses_objetivo - cantidad_disponible

    Parámetros configurables vía ConfiguracionSistema (claves):
        reorden_lead_time_dias, reorden_meses_objetivo, reorden_meses_historial.

    Devuelve lista agrupada por proveedor:
        [{proveedor_id, proveedor_nombre, productos: [ {...}, ... ]}]
    """
    # Valores por defecto si no existen las claves en ConfiguracionSistema.
    REORDEN_LEAD_TIME_DIAS = 15
    REORDEN_MESES_OBJETIVO = 2
    REORDEN_MESES_HISTORIAL = 6

    lead_time = ConfiguracionSistema.get_int('reorden_lead_time_dias', REORDEN_LEAD_TIME_DIAS)
    meses_objetivo = ConfiguracionSistema.get_int('reorden_meses_objetivo', REORDEN_MESES_OBJETIVO)
    meses_historial = ConfiguracionSistema.get_int('reorden_meses_historial', REORDEN_MESES_HISTORIAL)

    desde = timezone.now() - timedelta(days=30 * meses_historial)

    # Consumo total por producto en la ventana histórica (salidas aprobadas).
    consumo = (
        MovimientoItem.objects.filter(
            movimiento__tipo='salida',
            movimiento__aprobado=True,
            movimiento__sucursal=sucursal_id,
            movimiento__creado__gte=desde,
        )
        .values('producto_id')
        .annotate(total=Sum('cantidad'))
    )
    consumo_mensual_por_producto = {
        c['producto_id']: (c['total'] or 0) / meses_historial for c in consumo
    }

    productos = productos_queryset(sucursal_id).select_related('proveedor')

    grupos = {}
    for p in productos:
        consumo_mensual = consumo_mensual_por_producto.get(p.pk, 0)

        if consumo_mensual > 0:
            dias_cobertura = p.cantidad_disponible / (consumo_mensual / 30)
        else:
            dias_cobertura = float('inf')

        bajo_minimo = p.cantidad_disponible <= p.min_stock
        sin_cobertura = dias_cobertura < lead_time
        if not (bajo_minimo or sin_cobertura):
            continue

        prov = p.proveedor
        prov_id = prov.pk if prov else None
        if prov_id not in grupos:
            grupos[prov_id] = {
                'proveedor_id': prov_id,
                'proveedor_nombre': prov.nombre if prov else 'Sin proveedor',
                'productos': [],
            }

        grupos[prov_id]['productos'].append({
            'producto_id': p.pk,
            'codigo_interno': p.codigo_interno,
            'descripcion': p.descripcion,
            'cantidad_disponible': p.cantidad_disponible,
            'min_stock': p.min_stock,
            'consumo_mensual': round(consumo_mensual, 2),
            'dias_cobertura': None if dias_cobertura == float('inf') else round(dias_cobertura, 1),
            'cantidad_sugerida': max(0, round(consumo_mensual * meses_objetivo - p.cantidad_disponible)),
        })
    return list(grupos.values())
