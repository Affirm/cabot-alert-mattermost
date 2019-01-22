Cabot Mattermost Plugin
=====

This is an alert plugin for the Cabot service monitoring tool.
It allows you to alert users by their user handle in a [Mattermost](https://mattermost.com/) room.

**This plugin is designed to work with the [Affirm/cabot](https://github.com/Affirm/cabot) fork.** See [issue 12](https://github.com/Affirm/cabot-alert-mattermost/issues/12) for more info.

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
