from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0030_merge_20261016_0614'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='email',
            field=models.EmailField(blank=True, default='', help_text='Optional supplier contact email (OE-337).', max_length=254),
        ),
    ]
