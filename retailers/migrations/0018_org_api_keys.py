# Generated manually for OE-182 / F-0006 org API keys + scope audit

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def expand_admin_permissions(apps, schema_editor):
    """Ensure system Admin roles include api_keys.manage after catalog growth."""
    OrgRole = apps.get_model('retailers', 'OrgRole')
    desired = sorted([
        'org.update',
        'roles.manage',
        'staff.manage',
        'api_keys.manage',
    ])
    for role in OrgRole.objects.filter(slug='admin', is_system=True).iterator():
        if sorted(role.permissions or []) != desired:
            role.permissions = desired
            role.save(update_fields=['permissions', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('retailers', '0017_org_staff_roles'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgApiKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('prefix', models.CharField(help_text='Public key prefix used for lookup (not secret).', max_length=16, unique=True)),
                ('key_hash', models.CharField(max_length=64)),
                ('scopes', models.JSONField(default=list, help_text='List of partner API scope codes granted to this key.')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='org_api_keys_created', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to='retailers.organization')),
            ],
            options={
                'db_table': 'org_api_key',
            },
        ),
        migrations.CreateModel(
            name='OrgApiKeyAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('grant', 'Grant'), ('revoke', 'Revoke'), ('change', 'Change')], max_length=20)),
                ('key_prefix', models.CharField(blank=True, max_length=16)),
                ('scopes_before', models.JSONField(blank=True, default=list)),
                ('scopes_after', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='org_api_key_audits_made', to=settings.AUTH_USER_MODEL)),
                ('api_key', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audits', to='retailers.orgapikey')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_key_audits', to='retailers.organization')),
            ],
            options={
                'db_table': 'org_api_key_audit',
            },
        ),
        migrations.AddIndex(
            model_name='orgapikey',
            index=models.Index(fields=['organization', 'is_active'], name='org_api_key_organiz_7a1b2c_idx'),
        ),
        migrations.AddIndex(
            model_name='orgapikey',
            index=models.Index(fields=['prefix'], name='org_api_key_prefix_8d3e4f_idx'),
        ),
        migrations.AddIndex(
            model_name='orgapikeyaudit',
            index=models.Index(fields=['organization', 'created_at'], name='org_api_key_organiz_9a5b6c_idx'),
        ),
        migrations.RunPython(expand_admin_permissions, migrations.RunPython.noop),
    ]
