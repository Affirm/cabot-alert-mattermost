from django.core.exceptions import ValidationError
from django.db import models
from urlparse import urljoin
from cabot.cabotapp.alert import AlertPlugin, AlertPluginUserData

from os import environ as env

from django.conf import settings
from django.template import Context, Template

import requests
import logging

logger = logging.getLogger(__name__)

# name of the Cabot MM user, so it can add itself to channels
CABOT_USERNAME = env.get('MATTERMOST_CABOT_USERNAME', 'cabot')

EMOJIS = {
    'WARNING': ":thinking:",
    'ERROR': ":sad-panda:",
    'CRITICAL': ":alert:",
    'PASSING': ":dancing-panda:",
}

COLORS = {
    'WARNING': '#FFFF00',
    'ERROR': '#FF0000',
    'CRITICAL': '#FF0000',
    'PASSING': '#00FF00',
}

MESSAGE_TEMPLATE_NORMAL = '''
{% spaceless %}
{% url 'service' pk=service.id as service_uri %}
{% with scheme|add:'://'|add:host|add:service_uri as service_url %}
### {{ service.name | safe }}
[Service]({{ service_url }}) is back to normal {{ emoji }}
{% endwith %}
{% if alert %}
{% for alias in users %} @{{ alias }}{% endfor %} :point_up:
{% endif %}
{% endspaceless %}
'''

MESSAGE_TEMPLATE_ALERT = '''
{% spaceless %}
{% url 'service' pk=service.id as service_uri %}
{% with scheme|add:'://'|add:host|add:service_uri as service_url %}
### {{ service.name | safe }}
**[Service]({{ service_url }}) is reporting {{ status }}** {{ emoji }}
{% endwith %}
##### Failing checks
{% for check in service.all_failing_checks %}
{% if check.check_category == 'Jenkins check' %}
* [{{ check.name }}]({{ jenkins_api }}job/{{ check.name }}/{{ check.last_result.job_number }}/console) {{ check.last_result.error | default:'' | safe }}
{% else %}
{% url 'check' pk=check.id as check_uri %}
{% with scheme|add:'://'|add:host|add:check_uri as check_url %}
* [{{ check.name }}]({{ check_url }}) - {{ check.last_result.error | default:'' | safe }}
{% endwith %}
{% endif %}
{% endfor %}
{% if alert %}
{% for alias in users %} @{{ alias }}{% endfor %} :point_up:
{% endif %}
{% endspaceless %}
'''


def _check_response(response):
    # type: (requests.Response) -> None
    """Raise for status, but include the full response in the exception since MM gives us nice error messages"""
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise requests.HTTPError(e.message + ', response body: ' + response.text, response=response)


def _get_mm_api_for_service(service):
    """
    :param service: the service to pull from (to get MM instance, etc...)
    :return: a tuple of (api_endpoint_url, http_headers, channel_id)
    """
    if service.mattermost_instance is not None:
        server_url = service.mattermost_instance.server_url
        api_token = service.mattermost_instance.api_token
        channel_id = service.mattermost_instance.default_channel_id
    else:
        raise RuntimeError('Mattermost instance not set.')

    if service.mattermost_channel_id:
        channel_id = service.mattermost_channel_id
    if not channel_id:
        raise RuntimeError('Mattermost channel ID not set.')

    api_url = urljoin(server_url, 'api/v4/')
    headers = {
        'Authorization': 'Bearer {}'.format(api_token),
    }
    return api_url, headers, channel_id


class MatterMostAlert(AlertPlugin):
    name = "MatterMost"
    author = "Mahendra M"

    def _add_users_to_channel(self, url, headers, channel_id, users_to_add):
        """
        Adds the given list of usernames to the given channel_id.
        Silently continues if some usernames can't be found on MM. Logs a warning if a user is found, but can't be added
        to the channel (e.g. if our bot doesn't have permissions for this channel).
        :param url: MM api v4 endpoint
        :param headers: HTTP headers (w/ api token)
        :param channel_id: channel ID to add users to
        :param users_to_add: list of usernames to add to the channel
        :return: None
        """
        if len(users_to_add) == 0:
            return

        # first, map usernames -> user ids, since the channels API requires ids
        # note that any usernames that can't be found are just not included in the response
        # for example, ["i_dont_exist", "i_exist", ""] returns [{"username": "i_exist", "id": "123123", ...}]
        response = requests.post(urljoin(url, 'users/usernames'), headers=headers, json=users_to_add)
        _check_response(response)

        for user in response.json():
            # can't find any bulk API for adding users to channel, so we do it one at a time
            username = user['username']
            user_id = user['id']

            # if the user is already in the channel, this API call seems to just do nothing
            response = requests.post(urljoin(url, 'channels/{}/members'.format(channel_id)),
                                     headers=headers, json={'user_id': user_id})
            if response.status_code != 201:
                logger.warn("Could not add user %s, id %s to channel id %s. "
                            "Does the Cabot user have admin permissions in this channel?\n[%s] %s",
                            username, user_id, channel_id, response.status_code, response.text)

    def _upload_files(self, url, headers, channel_id, files, timeout=30):
        """
        Upload a list of files to MM.
        :param url: MM api v4 endpoint
        :param headers: HTTP headers (w/ api token)
        :param channel_id: channel ID to add users to
        :param files: list of files as ('filename', data) tuples
        :param timeout: timeout for uploading all files (default 30s)
        :return: list of MM file IDs
        """
        if len(files) == 0:
            return []

        # convert to a list of ('files', ('filename', <data>))
        # (can't use dict form because we have multiple values for the 'files' key...)
        files = [('files', (f[0], f[1])) for f in files]

        response = requests.post(
            urljoin(url, 'files'),
            data={'channel_id': channel_id},
            files=files,
            headers=headers,
            timeout=timeout,
        )
        _check_response(response)

        file_ids = [x['id'] for x in response.json()['file_infos']]
        if not len(file_ids) == len(files):
            logger.warn('It seems some files failed to upload (server returned %s file IDs, but we sent %s): %s',
                        len(file_ids), len(files), response.json())
        return file_ids

    def _send_alert(self, service, message, users_to_add=[]):
        """
        Send an alert with the service status, failing checks for a service and images to a Mattermost channel
        :param service: the Service we're alerting for
        :param message: the message to post
        :param users_to_add: MM usernames to ensure are in the channel (so @mentions work)
                             note that CABOT_USERNAME is automatically added to this list
                             (i.e. Cabot will add itself to any channels it sends messages to)
        :return: None
        """
        url, headers, channel_id = _get_mm_api_for_service(service)

        # ensure users we're going to @mention are in the channel (including the Cabot user)
        # if the Cabot user isn't in the channel, we won't be able to send the message
        try:
            self._add_users_to_channel(url, headers, channel_id, users_to_add + [CABOT_USERNAME])
        except:
            logger.exception('Failed to add users to the channel.')

        failing_checks = service.all_failing_checks()

        # Upload images for all failing checks
        file_ids = []
        try:
            files = []
            for check in failing_checks:
                image = check.get_status_image()
                if image is not None:
                    filename = '{}.png'.format(check.name)
                    files.append((filename, image))
            file_ids = self._upload_files(url, headers, channel_id, files)
        except:
            # continue anyway, just don't put any images in the message
            logger.exception('Failed to get/upload images.')

        # post in the channel
        response = requests.post(urljoin(url, 'posts'), headers=headers, json={
            'channel_id': channel_id,
            'message': '',
            'file_ids': file_ids,
            'props': {
                'attachments': [{
                    'fallback': '{} is {}'.format(service.name, service.overall_status),  # this shows in notifications
                    'color': COLORS.get(service.overall_status),
                    'text': message,
                }]
            },
        })
        _check_response(response)

    def send_alert(self, service, users, duty_officers):
        alert = True
        users = list(users) + list(duty_officers)
        aliases = [
            u.mattermost_alias for u in
            MatterMostAlertUserData.objects.filter(user__user__in=users)
        ]

        current_status = service.overall_status
        old_status = service.old_overall_status

        template = MESSAGE_TEMPLATE_NORMAL \
            if current_status == service.PASSING_STATUS \
            else MESSAGE_TEMPLATE_ALERT

        emoji = EMOJIS.get(current_status)

        if current_status == service.WARNING_STATUS:
            # Don't alert at all for WARNING
            alert = False
        if current_status == service.ERROR_STATUS:
            if old_status == service.ERROR_STATUS:
                # Don't alert repeatedly for ERROR
                alert = False
        if current_status == service.PASSING_STATUS:
            if old_status == service.WARNING_STATUS:
                # Don't alert for recovery from WARNING status
                alert = False

        jenkins_api = urljoin(settings.JENKINS_API, '/')
        c = Context({
            'service': service,
            'users': aliases,
            'host': settings.WWW_HTTP_HOST,
            'scheme': settings.WWW_SCHEME,
            'alert': alert,
            'jenkins_api': jenkins_api,
            'status': current_status,
            'emoji': emoji,
        })

        message = Template(template).render(c)
        self._send_alert(service, message, aliases)


def validate_mattermost_alias(alias):
    if alias.startswith('@'):
        raise ValidationError('Do not include a leading @ in your Mattermost alias.')


class MatterMostAlertUserData(AlertPluginUserData):
    '''
    This provides the Mattermost alias for each user.
    Each object corresponds to a User
    '''
    name = "MatterMost Plugin"
    mattermost_alias = models.CharField(max_length=50, blank=True, validators=[validate_mattermost_alias])

    def is_configured(self):
        return bool(self.mattermost_alias)
