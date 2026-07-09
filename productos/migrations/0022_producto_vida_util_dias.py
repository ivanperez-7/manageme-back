import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0021_fill_and_fix_lote_sucursal'),
    ]

    operations = [
        # Rename unidades: preserva datos existentes (todos eran por unidades).
        migrations.RenameField(
            model_name='producto',
            old_name='vida_util',
            new_name='vida_util_unidades',
        ),
        migrations.AlterField(
            model_name='producto',
            name='vida_util_unidades',
            field=models.PositiveIntegerField(
                default=1, null=True, blank=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name='producto',
            name='vida_util_dias',
            field=models.PositiveIntegerField(
                null=True, blank=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddConstraint(
            model_name='producto',
            constraint=models.CheckConstraint(
                condition=models.Q(vida_util_unidades__isnull=False) | models.Q(vida_util_dias__isnull=False),
                name='producto_vida_util_al_menos_uno',
            ),
        ),
    ]
