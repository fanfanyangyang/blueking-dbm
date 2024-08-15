# Generated by Django 3.2.25 on 2024-08-19 02:31

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("db_meta", "0040_auto_20240702_0757"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="cluster",
            unique_together={("immute_domain",), ("bk_biz_id", "immute_domain", "cluster_type", "db_module_id")},
        ),
        migrations.AlterUniqueTogether(
            name="dbmodule",
            unique_together={("db_module_name", "bk_biz_id", "cluster_type")},
        ),
    ]
