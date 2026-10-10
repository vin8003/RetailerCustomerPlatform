from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0034_productbatch_expiry_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='app_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Owned-app selling price. Null means fall back to store price.',
                max_digits=10,
                null=True,
                validators=[MinValueValidator(Decimal('0.01'))],
            ),
        ),
    ]
