from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='EmailOTPVerification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('otp_code', models.CharField(max_length=6)),
                ('secret_key', models.CharField(max_length=32)),
                ('purpose', models.CharField(choices=[('signup', 'Signup'), ('password_reset', 'Password Reset')], max_length=20)),
                ('is_verified', models.BooleanField(default=False)),
                ('attempts', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='authentication.user')),
            ],
            options={
                'db_table': 'email_otp_verification',
            },
        ),
        migrations.AddIndex(
            model_name='emailotpverification',
            index=models.Index(fields=['email', 'purpose'], name='email_otp_verif_email_1f8df8_idx'),
        ),
        migrations.AddIndex(
            model_name='emailotpverification',
            index=models.Index(fields=['expires_at'], name='email_otp_verif_expires_c843a0_idx'),
        ),
    ]
