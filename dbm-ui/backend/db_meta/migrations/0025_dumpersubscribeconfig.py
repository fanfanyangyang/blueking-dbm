# Generated by Django 3.2.19 on 2023-11-13 09:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db_meta", "0024_machine_bk_agent_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="DumperSubscribeConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creator", models.CharField(max_length=64, verbose_name="创建人")),
                ("create_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updater", models.CharField(max_length=64, verbose_name="修改人")),
                ("update_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("bk_biz_id", models.IntegerField(help_text="关联的业务id，对应cmdb")),
                ("name", models.CharField(help_text="订阅配置名", max_length=128)),
                (
                    "receiver_type",
                    models.CharField(
                        choices=[("redis", "redis"), ("kafka", "kafka")], help_text="数据接收端类型", max_length=32
                    ),
                ),
                ("receiver", models.CharField(help_text="接收端域名(IP)", max_length=255)),
                (
                    "subscribe",
                    models.JSONField(help_text="订阅库表信息 eg: [{'db_name': 'xx', 'table_names': [....]}, ...]"),
                ),
            ],
            options={
                "verbose_name": "dumper数据订阅配置",
                "verbose_name_plural": "dumper数据订阅配置",
                "unique_together": {("bk_biz_id", "name")},
            },
        ),
    ]
