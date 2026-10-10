# OE-152 configurable uncollected pickup policy hours.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0022_org_staff_served_locations'),
    ]

    operations = [
        migrations.AddField(
            model_name='retailerprofile',
            name='pickup_uncollected_hours',
            field=models.PositiveIntegerField(
                default=48,
                help_text='Hours after pickup-ready before uncollected orders expire and ATP is restored',
            ),
        ),
    ]
