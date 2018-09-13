Cabot Mattermost Plugin
=====

This is an alert plugin for the cabot service monitoring tool.
It allows you to alert users by their user handle in a [Mattermost](https://mattermost.com/) room.

## Installation

Enter the cabot virtual environment.

```bash
pip install cabot-alert-mattermost
foreman stop
# Add cabot_alert_mattermost to the installed apps in settings.py
foreman run python manage.py syncdb
foreman start
```

# Use

Open the admin panel and add a `matter most instance`.
You'll need the server URL, an API token, and a webhook. You may need to talk to your admin for the last two.

Add the `Mattermost` alert type to the service you want to alert on. =
Make sure you also select a `Mattermost instance` and enter a `Mattermost room ID`.
You can get the room ID from the Mattermost client from the "View Info" link in the channel name dropdown.
