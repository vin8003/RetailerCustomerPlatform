from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('retailers', '0025_retailercustomermapping_credit_due_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='retailerrewardconfig',
            name='otp_required_for_redeem',
            field=models.BooleanField(
                default=False,
                help_text='When true, point burn requires a one-time code on the customer mobile.',
            ),
        ),
    ]
