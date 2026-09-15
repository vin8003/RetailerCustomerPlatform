from django.db import migrations, models
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
                on_delete=django.db.models.deletion.CASCADE,
                related_name='suppliers',
                to='retailers.organization',
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
