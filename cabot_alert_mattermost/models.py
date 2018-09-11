from django.core.exceptions import ValidationError
from django.db import models
from urlparse import urljoin
from cabot.cabotapp.alert import AlertPlugin, AlertPluginUserData

from os import environ as env

from django.conf import settings
from django.template import Context, Template

import requests


EMOJIS = {
    'WARNING': ":thinking:",
    'ERROR': ":sad-panda:",
    'CRITICAL': ":alert:",
    'PASSING': ":dancing-panda:",
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

        url = urljoin(url, 'api/v4/')

        if service.mattermost_channel_id is not None:
            channel_id = service.mattermost_channel_id
        else:
            channel_id = env.get('MATTERMOST_ALERT_CHANNEL_ID')

        # Headers for the data
        headers = {
            'Authorization': 'Bearer {}'.format(api_token),
            'Content-Type': 'application/json',
        }

        failing_checks = service.all_failing_checks()
        # Send the image messages
        if failing_checks == []:
            return

        # Upload images for all failing checks
        files = []
        for check in failing_checks:
            image = check.get_status_image()
            if image is not None:
                files.append(('check_{}.png'.format(check.id), image))

        # Send the status message
        data = dict(
            channel_id=channel_id,
            message=message,
        )

        # Post all the images, if any, in one shot
        if files:
            images_url = urljoin(url, 'files')
            response = requests.post(
                images_url,
                json=dict(channel_id=channel_id),
                files=dict(files=files),
                headers=headers,
                timeout=30,
            )

            # Don't worry about images getting uploaded
            if response.status_code == 200:
                image_ids = [x['id'] for x in response.json()['file_infos']]
                data['file_ids'] = image_ids

        status_url = urljoin(url, 'posts')
        response = requests.post(status_url, headers=headers, json=data)
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
