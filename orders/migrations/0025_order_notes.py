from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0024_merge_20261016_0614'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='notes',
            field=models.TextField(blank=True, default=''),
        ),
    ]
