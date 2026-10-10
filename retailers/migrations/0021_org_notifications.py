# Generated manually for OE-183 / F-0005

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0020_payment_transaction_and_attempt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('retailers', '0020_org_module_flags'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgNotificationConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('default_channel', models.CharField(default='push', help_text='Default channel when no per-type override is set.', max_length=16)),
                ('disabled_types', models.JSONField(blank=True, default=list, help_text='Non-statutory notification type codes disabled for this org.')),
                ('channel_overrides', models.JSONField(blank=True, default=dict, help_text='Optional map of notification_type -> channel code.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notification_config', to='retailers.organization')),
            ],
            options={
                'db_table': 'org_notification_config',
            },
        ),
        migrations.CreateModel(
            name='OrgNotificationDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(max_length=64)),
                ('event_name', models.CharField(max_length=64)),
                ('channel', models.CharField(max_length=16)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')], default='pending', max_length=16)),
                ('retry_count', models.PositiveSmallIntegerField(default=0)),
                ('last_error', models.TextField(blank=True, default='')),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_deliveries', to='retailers.retailerprofile')),
                ('order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_deliveries', to='orders.order')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notification_deliveries', to='retailers.organization')),
                ('recipient_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_deliveries_received', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'org_notification_delivery',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='orgnotificationdelivery',
            index=models.Index(fields=['organization', 'created_at'], name='org_notif_org_created_idx'),
        ),
        migrations.AddIndex(
            model_name='orgnotificationdelivery',
            index=models.Index(fields=['organization', 'status'], name='org_notif_org_status_idx'),
        ),
        migrations.AddIndex(
            model_name='orgnotificationdelivery',
            index=models.Index(fields=['order', 'notification_type'], name='org_notif_order_type_idx'),
        ),
    ]
