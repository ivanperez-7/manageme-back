from django.db import migrations
from django.db.models import Count, Q


def backfill_stock(apps, schema_editor):
    Lote = apps.get_model('productos', 'Lote')
    ProductoStock = apps.get_model('productos', 'ProductoStock')

    for lote in Lote.objects.values('producto_id', 'sucursal_id').annotate(
        total=Count('unidades', filter=Q(unidades__status='disponible'))
    ):
        ProductoStock.objects.update_or_create(
            producto_id=lote['producto_id'],
            sucursal_id=lote['sucursal_id'],
            defaults={'cantidad': lote['total']},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0023_producto_stock'),
    ]

    operations = [
        migrations.RunPython(backfill_stock, migrations.RunPython.noop),
    ]
