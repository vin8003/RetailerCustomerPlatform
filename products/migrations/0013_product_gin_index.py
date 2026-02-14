from django.db import migrations
import django.contrib.postgres.indexes
import django.contrib.postgres.search

class Migration(migrations.Migration):

    dependencies = [
        ('products', '0012_enable_trigram_extension'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='product',
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.search.SearchVector('name', 'product_group', 'description', 'tags'),
                name='product_search_vector_idx',
            ),
        ),
    ]
