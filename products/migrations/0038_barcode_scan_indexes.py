from django.db import migrations, models

GIN_INDEXES = (
    ('product_extra_barcodes_gin', 'product'),
    ('product_batch_extra_barcodes_gin', 'product_batch'),
)


def create_gin_indexes(apps, schema_editor):
    """jsonb containment (``additional_barcodes @> '["code"]'``) for scans; PostgreSQL only."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    for name, table in GIN_INDEXES:
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (additional_barcodes jsonb_path_ops)'
        )


def drop_gin_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for name, _table in GIN_INDEXES:
        schema_editor.execute(f'DROP INDEX IF EXISTS {name}')


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0037_alter_productinventorylog_log_type'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['retailer', 'barcode'], name='product_retailer_barcode_idx'),
        ),
        migrations.RunPython(create_gin_indexes, drop_gin_indexes),
    ]
