# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import cabot_alert_mattermost.models


class Migration(migrations.Migration):

    dependencies = [
        ('cabotapp', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MatterMostAlert',
            fields=[
                ('alertplugin_ptr', models.OneToOneField(parent_link=True, auto_created=True, primary_key=True, serialize=False, to='cabotapp.AlertPlugin')),
            ],
            options={
                'abstract': False,
            },
            bases=('cabotapp.alertplugin',),
        ),
        migrations.CreateModel(
            name='MatterMostAlertUserData',
            fields=[
                ('alertpluginuserdata_ptr', models.OneToOneField(parent_link=True, auto_created=True, primary_key=True, serialize=False, to='cabotapp.AlertPluginUserData')),
                ('mattermost_alias', models.CharField(blank=True, max_length=50, validators=[cabot_alert_mattermost.models.validate_mattermost_alias])),
            ],
            options={
                'abstract': False,
            },
            bases=('cabotapp.alertpluginuserdata',),
        ),
    ]
