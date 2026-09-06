# OE-99 / F-0003 — Immutable org-scoped shop audit log

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0018_org_api_keys'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('grant', 'Grant'), ('revoke', 'Revoke'), ('change', 'Change')], max_length=20)),
                ('object_type', models.CharField(max_length=64)),
                ('object_id', models.CharField(max_length=64)),
                ('summary_before', models.JSONField(blank=True, default=dict)),
                ('summary_after', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='org_audit_logs_made', to=settings.AUTH_USER_MODEL)),
                ('location', models.ForeignKey(blank=True, help_text='Shop location when the mutation is location-scoped; null for org-wide.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs', to='retailers.retailerprofile')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audit_logs', to='retailers.organization')),
            ],
            options={
                'db_table': 'org_audit_log',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='orgauditlog',
            index=models.Index(fields=['organization', 'created_at'], name='org_audit_l_organiz_0a1b2c_idx'),
        ),
        migrations.AddIndex(
            model_name='orgauditlog',
            index=models.Index(fields=['organization', 'location', 'created_at'], name='org_audit_l_organiz_3d4e5f_idx'),
        ),
        migrations.AddIndex(
            model_name='orgauditlog',
            index=models.Index(fields=['organization', 'object_type', 'object_id'], name='org_audit_l_organiz_6g7h8i_idx'),
        ),
    ]
