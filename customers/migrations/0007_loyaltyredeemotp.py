import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0006_loyaltytransaction'),
        ('retailers', '0026_retailerrewardconfig_otp_required_for_redeem'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LoyaltyRedeemOTP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('otp_code', models.CharField(max_length=6)),
                ('is_used', models.BooleanField(default=False)),
                ('attempts', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='loyalty_redeem_otps',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('retailer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='loyalty_redeem_otps',
                    to='retailers.retailerprofile',
                )),
            ],
            options={
                'db_table': 'loyalty_redeem_otp',
            },
        ),
        migrations.AddIndex(
            model_name='loyaltyredeemotp',
            index=models.Index(fields=['customer', 'retailer', 'is_used'], name='loyalty_red_custome_otp_idx'),
        ),
        migrations.AddIndex(
            model_name='loyaltyredeemotp',
            index=models.Index(fields=['expires_at'], name='loyalty_red_expires_otp_idx'),
        ),
    ]
