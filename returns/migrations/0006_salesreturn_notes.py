from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('returns', '0005_purchasereturn_tax_amount_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesreturn',
            name='notes',
            field=models.TextField(blank=True, default=''),
        ),
    ]
