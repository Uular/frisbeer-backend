# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-05-31 16:08
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frisbeer', '0016_auto_20170531_1606'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='players',
            field=models.ManyToManyField(through='frisbeer.GamePlayerRelation', to='frisbeer.Player'),
        ),
    ]
