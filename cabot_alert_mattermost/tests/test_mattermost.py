# -*- coding: utf-8 -*-
from cabot.cabotapp.alert import AlertPlugin
from cabot.cabotapp.models_plugins import MatterMostInstance
from cabot.plugin_test_utils import PluginTestCase
from mock import patch, call

from cabot.cabotapp.models import Service, UserProfile
from cabot_alert_mattermost import models


class TestMattermostAlerts(PluginTestCase):
    def setUp(self):
        super(TestMattermostAlerts, self).setUp()

        self.alert = AlertPlugin.objects.get(title=models.MatterMostAlert.name)
        self.service.alerts.add(self.alert)
        self.service.save()

        self.mm_instance = MatterMostInstance.objects.create(name='Test MM Instance',
                                                             server_url='https://mattermost.org',
                                                             api_token='SOME-TOKEN',
                                                             default_channel_id='default-channel')
        self.service.mattermost_instance = self.mm_instance
        self.service.mattermost_channel_id = 'better-channel'

        self.plugin = models.MatterMostAlert.objects.get()

        # self.user's service key is user_key
        models.MatterMostAlertUserData.objects.create(user=self.user.profile, mattermost_alias='testuser_alias')

    def test_get_mm_api_for_service(self):
        url, headers, channel_id = models._get_mm_api_for_service(self.service)
        self.assertEqual(url, 'https://mattermost.org/api/v4/')
        self.assertEqual(headers, {
            'Authorization': 'Bearer SOME-TOKEN',
        })
        self.assertEqual(channel_id, 'better-channel')

    @patch('cabot_alert_mattermost.models.requests')
    @patch('cabot_alert_mattermost.models.MatterMostAlert._add_users_to_channel')
    @patch('cabot_alert_mattermost.models.MatterMostAlert._upload_files')
    def test_passing_to_error(self, upload_files, add_users, requests):
        upload_files.side_effect = lambda a, b, c, files: [str(i) for i, _ in enumerate(files)]

        self.run_checks([(self.es_check, False, False)], Service.PASSING_STATUS)

        add_users.assert_has_calls([
            call('https://mattermost.org/api/v4/',
                 {'Authorization': 'Bearer SOME-TOKEN'},
                 'better-channel',
                 ['testuser_alias', 'cabot']),
        ])
        upload_files.assert_has_calls([
            call('https://mattermost.org/api/v4/',
                 {'Authorization': 'Bearer SOME-TOKEN'},
                 'better-channel',
                 [('ES Metric Check.png', self.es_check.get_status_image())]),
        ])
        requests.post.assert_has_calls([
            call('https://mattermost.org/api/v4/posts', headers={'Authorization': 'Bearer SOME-TOKEN'},
                 json={
                     'channel_id': 'better-channel',
                     'message': '',
                     'file_ids': ['0'],
                     'props': {
                         'attachments': [{
                             'color': '#FF0000',
                             'text': u'\n'
                                     u'### Service\n'
                                     u'**[Service](http://localhost/service/2194/) is reporting ERROR** :sad-panda:'
                                     u'\n\n'
                                     u'##### Failing checks\n\n\n\n\n'
                                     u'* [ES Metric Check](http://localhost/check/10104/) - \n\n\n\n\n\n'
                                     u' @testuser_alias :point_up:\n\n\n'
                                     u'Someone tell [dolores@affirm.com](http://localhost/user/{}/profile/'
                                     u'MatterMost%20Plugin) to add their MM alias to their profile! :angry:\n'
                                     .format(self.duty_officer.pk),
                             'fallback': 'Service is ERROR'
                         }]
                     }
                 }),
            call().raise_for_status(),
        ])

    @patch('cabot_alert_mattermost.models.MatterMostAlert._send_alert')
    def test_passing_to_warning(self, send_alert):
        self.transition_service_status(Service.PASSING_STATUS, Service.WARNING_STATUS)
        send_alert.assert_has_calls([
            call(self.service, '\n'
                               '### Service\n'
                               '**[Service](http://localhost/service/2194/) is reporting WARNING** :thinking:\n\n'
                               '##### Failing checks\n', ['testuser_alias']),
        ])
