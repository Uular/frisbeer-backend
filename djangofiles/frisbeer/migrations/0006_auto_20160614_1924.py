# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2016-06-14 19:24
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frisbeer', '0005_player_rank'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='rank',
            field=models.CharField(default='', max_length=50),
        ),
    ]
