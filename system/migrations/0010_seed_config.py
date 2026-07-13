from django.db import migrations


SEED = [
    ('reorden_lead_time_dias', '15',
     'Días de espera (lead time) del proveedor para las sugerencias de reorden.'),
    ('reorden_meses_objetivo', '2',
     'Meses de inventario objetivo al calcular la cantidad sugerida de reorden.'),
    ('reorden_meses_historial', '6',
     'Meses de historial de consumo usados para el promedio de reorden.'),
    ('alerta_old_product_dias', '365',
     'Días de antigüedad de un lote para alertar "producto sin rotación".'),
    ('alerta_unusual_multiplicador', '3',
     'Múltiplo del promedio histórico para marcar un "movimiento inusual".'),
    ('alerta_high_rotation_top_n', '10',
     'Cantidad de productos top a marcar como "alta rotación".'),
]


def seed(apps, schema_editor):
    ConfiguracionSistema = apps.get_model('system', 'ConfiguracionSistema')
    for clave, valor, descripcion in SEED:
        # No sobrescribe valores ya ajustados por un admin.
        ConfiguracionSistema.objects.get_or_create(
            clave=clave, defaults={'valor': valor, 'descripcion': descripcion}
        )


def unseed(apps, schema_editor):
    ConfiguracionSistema = apps.get_model('system', 'ConfiguracionSistema')
    ConfiguracionSistema.objects.filter(clave__in=[c for c, _, _ in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('system', '0009_alter_registroactividad_accion'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
