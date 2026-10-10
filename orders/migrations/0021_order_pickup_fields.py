# OE-152 shop pickup verification fields on unified Order.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0020_payment_transaction_and_attempt'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='pickup_code',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
        migrations.AddField(
            model_name='order',
            name='pickup_ready_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='cancelled_by',
            field=models.CharField(
                blank=True,
                choices=[
                    ('customer', 'Customer'),
                    ('retailer', 'Retailer'),
                    ('system', 'System'),
                ],
                max_length=50,
                null=True,
            ),
        ),
    ]
