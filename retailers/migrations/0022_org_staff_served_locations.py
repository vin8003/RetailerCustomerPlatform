# OE-135 — staff served location scope for retailer order inbox

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0021_org_notifications'),
    ]

    operations = [
        migrations.AddField(
            model_name='orgstaffmembership',
            name='served_location_ids',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    'RetailerProfile ids this staff member may operate on. '
                    'Empty on a multi-location org means no locations until assigned.'
                ),
            ),
        ),
    ]
