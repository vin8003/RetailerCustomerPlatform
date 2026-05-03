from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def backfill_payment_transactions(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    PaymentTransaction = apps.get_model('orders', 'PaymentTransaction')

    for order in Order.objects.all().iterator():
        rows = []
        breakdown = [
            ('cash', order.cash_amount or Decimal('0.00')),
            ('upi', order.upi_amount or Decimal('0.00')),
            ('card', order.card_amount or Decimal('0.00')),
            ('credit', order.credit_amount or Decimal('0.00')),
        ]
        for method, amount in breakdown:
            if amount and amount > 0:
                rows.append((method, amount))

        if not rows:
            total = order.total_amount or Decimal('0.00')
            if total > 0:
                fallback_method = order.payment_mode if order.payment_mode in {'cash', 'upi', 'card', 'credit', 'cash_pickup'} else 'cash'
                rows.append((fallback_method, total))

        for method, amount in rows:
            PaymentTransaction.objects.create(
                order=order,
                method=method,
                amount=amount,
                reference_id=order.payment_reference_id,
                status=order.payment_status,
                metadata={'source': 'legacy_backfill'}
            )


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0019_alter_order_card_amount_alter_order_cash_amount_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('cash', 'Cash'), ('cash_pickup', 'Cash on Pickup'), ('upi', 'UPI'), ('online', 'Online App Payment'), ('card', 'Card'), ('credit', 'Credit (Udhaar)'), ('split', 'Split Payment')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
                ('reference_id', models.CharField(blank=True, max_length=100, null=True)),
                ('status', models.CharField(choices=[('pending_payment', 'Pending Payment'), ('pending_verification', 'Pending Verification'), ('verified', 'Verified'), ('failed', 'Failed')], default='pending_payment', max_length=50)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='payment_transactions', to='orders.order')),
            ],
            options={'db_table': 'payment_transaction', 'ordering': ['-created_at', '-id']},
        ),
        migrations.CreateModel(
            name='PaymentAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_status', models.CharField(blank=True, choices=[('pending_payment', 'Pending Payment'), ('pending_verification', 'Pending Verification'), ('verified', 'Verified'), ('failed', 'Failed')], max_length=50, null=True)),
                ('new_status', models.CharField(choices=[('pending_payment', 'Pending Payment'), ('pending_verification', 'Pending Verification'), ('verified', 'Verified'), ('failed', 'Failed')], max_length=50)),
                ('reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('attempted_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='payment_attempts', to=settings.AUTH_USER_MODEL)),
                ('order', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='payment_attempts', to='orders.order')),
            ],
            options={'db_table': 'payment_attempt', 'ordering': ['-created_at', '-id']},
        ),
        migrations.RunPython(backfill_payment_transactions, migrations.RunPython.noop),
    ]
