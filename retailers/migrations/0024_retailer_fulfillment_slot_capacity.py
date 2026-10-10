# OE-243 fulfillment slot capacity per location.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0023_retailer_pickup_uncollected_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='retailerprofile',
            name='fulfillment_slot_capacity',
            field=models.PositiveIntegerField(
                default=5,
                help_text='Max orders per 30-minute pickup/delivery slot at this location',
            ),
        ),
    ]
