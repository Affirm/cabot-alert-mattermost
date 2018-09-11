Cabot Mattermost Plugin
=====

This is an alert plugin for the cabot service monitoring tool. It allows you to alert users by their user handle in a hipchat room.

## Installation

Enter the cabot virtual environment.
    $ pip install cabot-alert-mattermost
    $ foreman stop
Add cabot_alert_mattermost to the installed apps in settings.py
    $ foreman run python manage.py syncdb
    $ foreman start
