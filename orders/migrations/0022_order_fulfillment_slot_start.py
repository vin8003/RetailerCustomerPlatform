# OE-243 customer-chosen fulfillment slot on unified Order.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0021_order_pickup_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='fulfillment_slot_start',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(
                fields=['retailer', 'fulfillment_slot_start', 'delivery_mode'],
                name='order_retailer_slot_idx',
            ),
        ),
    ]
