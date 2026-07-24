from django.utils import timezone


def compute_vida_util_usage(producto, equipo_cliente, movimiento_creado=None, exclude_item_pk=None):
    """Checks whether a rental item has reached its vida útil thresholds.
    

    Returns a dict:
        - tiene_snapshot_previa (bool)
        - uso_unid (int)
        - uso_dias (int)
        - vu_unid (int | None)
        - vu_dias (int | None)
        - alcanzada (bool) — True if no prior snapshot exists or at least one threshold is met
        - mensaje (str) — human-readable summary when not alcanzada, empty otherwise
    """
    # ponytail: lazy import avoids circular ref (models → utils → models)
    from .models import MovimientoItem

    if movimiento_creado is None:
        movimiento_creado = timezone.now()

    ultima = MovimientoItem.objects.filter(
        producto=producto,
        movimiento__detalle_salida__cliente=equipo_cliente.cliente,
        equipo_cliente=equipo_cliente,
        contador_uso_snapshot__isnull=False,
    )
    if exclude_item_pk is not None:
        ultima = ultima.exclude(pk=exclude_item_pk)
    ultima = ultima.select_related('movimiento').order_by('-movimiento__creado').first()

    if not ultima:
        return {
            'tiene_snapshot_previa': False,
            'uso_unid': 0,
            'uso_dias': 0,
            'vu_unid': producto.vida_util_unidades,
            'vu_dias': producto.vida_util_dias,
            'alcanzada': True,
            'mensaje': '',
        }

    uso_unid = equipo_cliente.contador_uso - ultima.contador_uso_snapshot
    dias = (movimiento_creado - ultima.movimiento.creado).days
    vu_unid = producto.vida_util_unidades
    vu_dias = producto.vida_util_dias

    agotado_unid = vu_unid is not None and uso_unid >= vu_unid
    agotado_dias = vu_dias is not None and dias >= vu_dias
    alcanzada = agotado_unid or agotado_dias

    partes = []
    if vu_unid is not None:
        partes.append(f'{uso_unid}/{vu_unid} unidades')
    if vu_dias is not None:
        partes.append(f'{dias}/{vu_dias} días')

    return {
        'tiene_snapshot_previa': True,
        'uso_unid': uso_unid,
        'uso_dias': dias,
        'vu_unid': vu_unid,
        'vu_dias': vu_dias,
        'alcanzada': alcanzada,
        'mensaje': ', '.join(partes),
    }
