
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def approve_existing_items(apps, schema_editor):
    Item = apps.get_model('listings', 'Item')
    Item.objects.all().update(moderation_status='approved')


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0003_claim'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='moderation_rejection_reason',
            field=models.TextField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='item',
            name='moderation_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='item',
            name='moderation_reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_items',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='moderation_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending review'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                ],
                db_index=True,
                default='pending',
                max_length=20,
            ),
        ),
        migrations.RunPython(
            approve_existing_items,
            migrations.RunPython.noop,
        ),
    ]
