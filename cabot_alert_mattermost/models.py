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


class MatterMostAlert(AlertPlugin):
    name = "MatterMost"
    author = "Mahendra M"

    def _send_alert(self, service, message):
        """
        Send an alert with the service status, failing
        checks for a service and images to a Mattermost channel
        :param service: the Service we're alerting for
        :param message: the message to post
        :return: None
        """
        if service.mattermost_instance is not None:
            url = service.mattermost_instance.server_url
            api_token = service.mattermost_instance.api_token
            channel_id = service.mattermost_instance.default_channel_id
        else:
            raise RuntimeError('Mattermost instance not set.')

        if service.mattermost_channel_id:
            channel_id = service.mattermost_channel_id
        if not channel_id:
            raise RuntimeError('Mattermost channel ID not set.')

        url = urljoin(url, 'api/v4/')

        # Headers for the data
        headers = {
            'Authorization': 'Bearer {}'.format(api_token),
        }

        failing_checks = service.all_failing_checks()
        # Send the image messages
        if failing_checks == []:
            return

        # Upload images for all failing checks
        files = []
        failing_checks_with_images = []
        file_ids = []
        for check in failing_checks:
            image = check.get_status_image()
            if image is not None:
                filename = '{}.png'.format(check.name)
                files.append(('files', (filename, image)))
                failing_checks_with_images.append(check)

        # Upload all the images, if any, in one shot
        if len(files) > 0:
            images_url = urljoin(url, 'files')

            response = requests.post(
                images_url,
                data={'channel_id': channel_id},
                files=files,
                headers=headers,
                timeout=30,
            )

            # Don't worry about images getting uploaded
            if response.status_code == 201:
                file_ids = [x['id'] for x in response.json()['file_infos']]
                if not len(file_ids) == len(files):
                    logger.warn('Seems some files failed to upload (server returned %s file IDs, but we sent %s): %s',
                                len(file_ids), len(files), response.json())
            else:
                logger.warn('Images failed to upload, got status code %s: %s',
                            response.status_code, response.json())

        # build attachments
        title = '{service} is {status}'.format(service=service.name, status=service.overall_status)
        color = COLORS.get(service.overall_status)
        attachments = [{
            'fallback': title,  # this is the text that shows in notifications
            'color': color,
            'text': message,
        }]

        response = requests.post(urljoin(url, 'posts'), headers=headers, json={
            'channel_id': channel_id,
            'message': '',
            'file_ids': file_ids,
            'props': {
                'attachments': attachments
            },
        })
        response.raise_for_status()

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
        self._send_alert(service, message)


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
