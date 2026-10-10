from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0026_retailerrewardconfig_otp_required_for_redeem'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='payment_terms',
            field=models.CharField(
                blank=True,
                help_text='Vendor payment terms (e.g. Net 30, COD). Changes require purchasing.terms.',
                max_length=80,
            ),
        ),
        migrations.AlterField(
            model_name='supplier',
            name='gst_number',
            field=models.CharField(
                blank=True,
                help_text='GSTIN. Optional. Duplicate non-blank values are flagged per organization.',
                max_length=15,
            ),
        ),
        migrations.AddIndex(
            model_name='supplier',
            index=models.Index(fields=['gst_number'], name='supplier_gst_num_8c1e4a_idx'),
        ),
    ]
