from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):

    dependencies = [
        ('products', '0011_masterproduct_product_group_product_product_group'),
    ]

    operations = [
        TrigramExtension(),
    ]
