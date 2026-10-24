from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Upper
import django.db.models.deletion


def backfill_supplier_organization(apps, schema_editor):
    Supplier = apps.get_model('retailers', 'Supplier')
    RetailerProfile = apps.get_model('retailers', 'RetailerProfile')
    org_id = RetailerProfile.objects.filter(
        pk=models.OuterRef('retailer_id')
    ).values('organization_id')[:1]
    Supplier.objects.filter(organization_id__isnull=True).update(
        organization_id=models.Subquery(org_id)
    )
    Supplier.objects.filter(gst_number__isnull=True).update(gst_number='')
    Supplier.objects.exclude(gst_number='').update(gst_number=Upper('gst_number'))
    dupes = list(
        Supplier.objects.exclude(gst_number='')
        .exclude(organization_id=None)
        .values('organization_id', 'gst_number')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
    )
    if dupes:
        raise RuntimeError(
            'Cannot add uniq_org_supplier_nonblank_gstin; '
            f'duplicate org GSTINs remain: {dupes}'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0027_supplier_payment_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='organization',
            field=models.ForeignKey(
                blank=True,
                help_text='Denormalized from retailer.organization for org-unique GSTIN.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='suppliers',
                to='retailers.organization',
            ),
        ),
        migrations.AlterField(
            model_name='supplier',
            name='gst_number',
            field=models.CharField(
                blank=True,
                help_text='GSTIN. Optional. Non-blank values are unique per organization.',
                max_length=15,
            ),
        ),
        migrations.RunPython(backfill_supplier_organization, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(
                condition=models.Q(('organization__isnull', False)) & ~models.Q(('gst_number', '')),
                fields=('organization', 'gst_number'),
                name='uniq_org_supplier_nonblank_gstin',
            ),
        ),
    ]
