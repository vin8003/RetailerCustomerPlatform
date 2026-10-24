from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0033_purchaseinvoice_bill_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='productbatch',
            name='expiry_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='productbatch',
            index=models.Index(
                fields=['product', 'is_active', 'expiry_date'],
                name='product_bat_product_exp_idx',
            ),
        ),
    ]
