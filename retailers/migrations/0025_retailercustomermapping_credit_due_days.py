from django.db import migrations, models
from django.db.models import F, OuterRef, Subquery
from django.db.models.functions import Coalesce


def backfill_outstanding_since(apps, schema_editor):
    Mapping = apps.get_model('retailers', 'RetailerCustomerMapping')
    Ledger = apps.get_model('retailers', 'CustomerLedger')
    oldest_sale = (
        Ledger.objects.filter(mapping_id=OuterRef('pk'), transaction_type='SALE')
        .order_by('created_at')
        .values('created_at')[:1]
    )
    Mapping.objects.filter(
        current_balance__gt=0,
        outstanding_since__isnull=True,
    ).update(
        outstanding_since=Coalesce(Subquery(oldest_sale), F('updated_at')),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0024_retailer_fulfillment_slot_capacity'),
    ]

    operations = [
        migrations.AddField(
            model_name='retailercustomermapping',
            name='credit_due_days',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Days after outstanding opens before new credit sales lock. Null = no due-days lock.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='retailercustomermapping',
            name='outstanding_since',
            field=models.DateTimeField(
                blank=True,
                help_text='When running khata balance last became positive. Cleared when balance returns to zero.',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_outstanding_since, migrations.RunPython.noop),
    ]
