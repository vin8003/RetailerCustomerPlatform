# Generated manually for OE-98 / F-0002 shop staff roles

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def bootstrap_existing_orgs(apps, schema_editor):
    """Backfill Admin/Cashier roles + owner Admin membership for existing orgs."""
    Organization = apps.get_model('retailers', 'Organization')
    OrgRole = apps.get_model('retailers', 'OrgRole')
    OrgStaffMembership = apps.get_model('retailers', 'OrgStaffMembership')

    admin_perms = sorted(['org.update', 'roles.manage', 'staff.manage'])
    for org in Organization.objects.all().iterator():
        admin_role, _ = OrgRole.objects.get_or_create(
            organization_id=org.pk,
            slug='admin',
            defaults={
                'name': 'Admin',
                'permissions': admin_perms,
                'is_system': True,
            },
        )
        OrgRole.objects.get_or_create(
            organization_id=org.pk,
            slug='cashier',
            defaults={
                'name': 'Cashier',
                'permissions': [],
                'is_system': True,
            },
        )
        OrgStaffMembership.objects.get_or_create(
            organization_id=org.pk,
            user_id=org.owner_id,
            defaults={
                'role_id': admin_role.pk,
                'is_active': True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0016_organization'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(max_length=50)),
                ('permissions', models.JSONField(default=list, help_text='List of permission catalog codes granted by this role.')),
                ('is_system', models.BooleanField(default=False, help_text='Bootstrap roles (admin/cashier) that cannot be deleted.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='roles', to='retailers.organization')),
            ],
            options={
                'db_table': 'org_role',
            },
        ),
        migrations.CreateModel(
            name='OrgStaffMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_memberships', to='retailers.organization')),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='memberships', to='retailers.orgrole')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='org_staff_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'org_staff_membership',
            },
        ),
        migrations.CreateModel(
            name='OrgStaffRoleAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('grant', 'Grant'), ('revoke', 'Revoke'), ('change', 'Change')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='staff_role_audits_made', to=settings.AUTH_USER_MODEL)),
                ('from_role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='retailers.orgrole')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_role_audits', to='retailers.organization')),
                ('target_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_role_audits_received', to=settings.AUTH_USER_MODEL)),
                ('to_role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='retailers.orgrole')),
            ],
            options={
                'db_table': 'org_staff_role_audit',
            },
        ),
        migrations.AddIndex(
            model_name='orgrole',
            index=models.Index(fields=['organization'], name='org_role_organiz_7f0b1a_idx'),
        ),
        migrations.AddConstraint(
            model_name='orgrole',
            constraint=models.UniqueConstraint(fields=('organization', 'slug'), name='uniq_org_role_slug'),
        ),
        migrations.AddIndex(
            model_name='orgstaffmembership',
            index=models.Index(fields=['organization', 'is_active'], name='org_staff_m_organiz_a1b2c3_idx'),
        ),
        migrations.AddIndex(
            model_name='orgstaffmembership',
            index=models.Index(fields=['user'], name='org_staff_m_user_id_d4e5f6_idx'),
        ),
        migrations.AddConstraint(
            model_name='orgstaffmembership',
            constraint=models.UniqueConstraint(fields=('organization', 'user'), name='uniq_org_staff_user'),
        ),
        migrations.AddIndex(
            model_name='orgstaffroleaudit',
            index=models.Index(fields=['organization', 'created_at'], name='org_staff_r_organiz_g7h8i9_idx'),
        ),
        migrations.RunPython(bootstrap_existing_orgs, migrations.RunPython.noop),
    ]
