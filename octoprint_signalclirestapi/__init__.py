# vim: set tabstop=8:expandtab:shiftwidth=4:softtabstop=4
# coding=utf-8
from __future__ import absolute_import

# (Don't forget to remove me)
# This is a basic skeleton for your plugin's __init__.py. You probably want to adjust the class name of your plugin
# as well as the plugin mixins it's subclassing from. This is really just a basic skeleton to get you started,
# defining your plugin as a template plugin, settings and asset plugin. Feel free to add or remove mixins
# as necessary.
#
# Take a look at the documentation on what other plugin mixins are available.

import octoprint.plugin
import octoprint.util
import flask
from pysignalclirestapi import SignalCliRestApi
from datetime import datetime, timedelta

try:
    from urllib.request import urlretrieve
except ImportError:
    from urllib import urlretrieve
import tempfile
import socket
import getpass


def verify_connection_settings(url, sender_nr, recipients):
    if url is None or url == "":
        raise Exception("REST API URL needs to be set")
    if sender_nr is None or sender_nr == "":
        raise Exception("Sender Number needs to be set")
    if recipients is None or recipients == "":
        raise Exception("Please provide at least one recipient") 


def create_group(url, sender_nr, members, name):
    api = SignalCliRestApi(url, sender_nr) 
    group_id = api.create_group(name, members)
    return group_id

def send_message(url, sender_nr, message, recipients, filenames=[]):
    verify_connection_settings(url, sender_nr, recipients) 

    api = SignalCliRestApi(url, sender_nr)
    api.send_message(message, recipients, filenames=filenames)

def get_webcam_snapshot(snapshot_url): 
    filename, _ = urlretrieve(snapshot_url, tempfile.gettempdir()+"/snapshot.jpg")
    return filename

def get_supported_tags():
    return {
                "filename": None,
                "elapsed_time": None,
                "host": socket.gethostname(),
                "user": getpass.getuser(),
                "progress": None
           }

class SignalclirestapiPlugin(octoprint.plugin.SettingsPlugin,
                             octoprint.plugin.AssetPlugin,
                             octoprint.plugin.SimpleApiPlugin,
                             octoprint.plugin.TemplatePlugin,
                             octoprint.plugin.EventHandlerPlugin,
                             octoprint.plugin.ProgressPlugin):

    def __init__(self):
        self._group_id = None 
    
    # ~~ SettingsPlugin mixin

    def on_print_progress(self, storage, path, progress):
        if self.enabled and self.send_print_progress:
            supported_tags = get_supported_tags()
            supported_tags["progress"] = progress
            supported_tags["filename"] = path
            message = self.send_print_progress_template.format(**supported_tags)
            
            if progress == 20:
                self._send_message(message)
            elif progress == 40:
                self._send_message(message)
            elif progress == 60:
                self._send_message(message)
            elif progress == 80:
                self._send_message(message)


    def get_api_commands(self):
        return dict(testMessage=["sender", "recipients", "url"]);

    def get_settings_defaults(self):
        return dict(
            enabled=False,
            url="http://127.0.0.1:8080",
            sendernr="",
            recipientsnrs="",
            printstartedevent=True,
            printdoneevent=True,
            printfailedevent=True,
            printcancelledevent=True,
            printpausedevent=True,
            printresumedevent=True,
            printstartedeventtemplate="OctoPrint@{host}: {filename}: Job started.",
            printdoneeventtemplate="OctoPrint@{host}: {filename}: Job complete after {elapsed_time}.",
            printpausedeventtemplate="OctoPrint@{host}: {filename}: Job paused!",
            printfailedeventtemplate="OctoPrint@{host}: {filename}: Job failed after {elapsed_time} ({reason})!", 
            printcancelledeventtemplate="OctoPrint@{host}: {filename}: Job cancelled after {elapsed_time}!",
            printresumedeventtemplate="OctoPrint@{host}: {filename}: Job resumed!",
            attachsnapshots=False,
            creategroupforeveryprint=True,
            sendprintprogress=True,
            sendprintprogresstemplate="OctoPrint@{host}: {filename}: Progess: {progress}%"
        ) 
        
    @property
    def enabled(self):
        return self._settings.get_boolean(["enabled"])

    @property
    def url(self):
        return self._settings.get(["url"])
    
    @property
    def sender(self):
        return self._settings.get(["sendernr"])
    
    @property
    def recipients(self):
        return self._settings.get(["recipientnrs"]).split(",")

    @property
    def print_done_event(self):
        return self._settings.get_boolean(["printdoneevent"])

    @property
    def print_started_event(self):
        return self._settings.get_boolean(["printstartedevent"])
        
    @property
    def print_failed_event(self):
        return self._settings.get_boolean(["printfailedevent"])
    
    @property
    def print_paused_event(self):
        return self._settings.get_boolean(["printpausedevent"])
    
    @property
    def print_cancelled_event(self):
        return self._settings.get_boolean(["printcancelledevent"])

    @property
    def print_resumed_event(self):
        return self._settings.get_boolean(["printresumedevent"])

    @property
    def create_group_for_every_print(self):
        return self._settings.get_boolean(["creategroupforeveryprint"])

    @property
    def attach_snapshots(self):
        return self._settings.get_boolean(["attachsnapshots"])

    @property
    def send_print_progress(self):
        return self._settings.get_boolean(["sendprintprogress"])

    @property
    def send_print_progress_template(self):
        return self._settings.get(["sendprintprogresstemplate"])

    @property
    def print_started_event_template(self):
        return self._settings.get(["printstartedeventtemplate"])

    @property
    def print_paused_event_template(self):
        return self._settings.get(["printpausedeventtemplate"])

    @property
    def print_cancelled_event_template(self):
        return self._settings.get(["printcancelledeventtemplate"])

    @property
    def print_done_event_template(self):
        return self._settings.get(["printdoneeventtemplate"])

    @property
    def print_resumed_event_template(self):
        return self._settings.get(["printresumedeventtemplate"])

    @property
    def print_failed_event_template(self):
        return self._settings.get(["printfailedeventtemplate"])
        

    def _create_group_if_not_exists(self):
        if self._group_id is None:
            try:
                group_name = "Print " + str(datetime.now())
                self._group_id = create_group(self.url, self.sender, self.recipients, group_name) 
            except Exception as e:
                self._logger.exception("Couldn't create signal group")

    def _send_message(self, message):
        try:
            recipients = self.recipients
            if self.create_group_for_every_print:
                if self._group_id is None:
                    self._logger.error("Couldn't send message %s as group is not existing", message)
                    return
                recipients = [self._group_id]
            
            snapshot_filenames = []
            if self.attach_snapshots:
                snapshot_url = self._settings.global_get(["webcam", "snapshot"])

                try:
                    snapshot_filenames.append(get_webcam_snapshot(snapshot_url))
                except Exception as e:
                    self._logger.exception("Couldn't get webcam image...sending without it")
            send_message(self.url, self.sender, message, recipients, snapshot_filenames)
        except Exception as e:
            self._logger.exception("Couldn't send signal message: %s", str(e))         


    def on_api_command(self, command, data): 
        if command == "testMessage":
            self._logger.info(data)
            
            url = None
            sender_nr = None
            recipients = None
            attach_snapshot = False
            try:
                url = data["url"]
                sender_nr = data["sender"]
                recipients = data["recipients"].split(",")
                if data["attachSnapshot"]:
                    attach_snapshot = True
            except KeyError as e:
                self._logger.error("Couldn't get data: %s" %str(e))
                return

            try:
                snapshot_filenames = []
                message = "Hello from OctoPrint"
                if attach_snapshot:
                    snapshot_url = self._settings.global_get(["webcam", "snapshot"])
                    try:
                        snapshot_filenames.append(get_webcam_snapshot(snapshot_url))
                    except Exception as e:
                        message = "Hello from OctoPrint.\nThere should be a webcam image attached, but your camera seems to be not working. Please check your camera!"
                        self._logger.exception("Sending test message. Couldn't get webcam image...sending without it")

                send_message(url, sender_nr, message, recipients, snapshot_filenames)  
            except Exception as e:
                return flask.jsonify(dict(success=False, msg=str(e)))
            
            return flask.jsonify(dict(success=False, msg="Success! Please check your phone."))

    def on_event(self, event, payload):
        self._logger.info("Received event %s", event)
        supported_tags = get_supported_tags()
        if payload is not None:
            if "name" in payload:
                supported_tags["filename"] = payload["name"]
            if "time" in payload:
                supported_tags["elapsed_time"] = octoprint.util.get_formatted_timedelta(timedelta(seconds=payload["time"]))
        if event == "PrintStarted":
            if self.enabled and self.print_started_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                self._logger.info(supported_tags)
                self._logger.info(self.print_started_event_template)
                message = self.print_started_event_template.format(**supported_tags) 
                self._send_message(message) 
        elif event == "PrintDone":
            if self.enabled and self.print_done_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                message = self.print_done_event_template.format(**supported_tags)
                self._send_message(message)
        elif event == "PrintFailed":
            if self.enabled and self.print_failed_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                message = self.print_failed_event_template.format(**supported_tags)
                self._send_message(message)
        elif event == "PrintCancelled":
            if self.enabled and self.print_cancelled_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                message = self.print_cancelled_event_template.format(**supported_tags)
                self._send_message(message)
        elif event == "PrintPaused":
            if self.enabled and self.print_paused_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                message = self.print_paused_event_template.format(**supported_tags)
                self._send_message(message)
        elif event == "PrintResumed":
            if self.enabled and self.print_resumed_event:
                if self.create_group_for_every_print:
                    self._create_group_if_not_exists()
                message = self.print_resumed_event_template.format(**supported_tags)
                self._send_message(message)

            
    def get_template_configs(self):
        return [
            dict(type="settings", name="Signal Notifications", custom_bindings=False)
        ]

    # ~~ AssetPlugin mixin

    def get_assets(self):
        # Define your plugin's asset files to automatically include in the
        # core UI here.
        return dict(
            js=["js/signalclirestapi.js"],
            css=["css/signalclirestapi.css"],
            less=["less/signalclirestapi.less"]
        )

    # ~~ Softwareupdate hook

    def get_update_information(self):
        # Define the configuration for your plugin to use with the Software Update
        # Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
        # for details.
        return dict(
            signalclirestapi=dict(
                displayName="Signalclirestapi Plugin",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="bbernhard",
                repo="OctoPrint-Signalclirestapi",
                current=self._plugin_version,

                # update method: pip
                pip="https://github.com/bbernhard/OctoPrint-Signalclirestapi/archive/{target_version}.zip"
            )
        )


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Signalclirestapi Plugin"

# Starting with OctoPrint 1.4.0 OctoPrint will also support to run under Python 3 in addition to the deprecated
# Python 2. New plugins should make sure to run under both versions for now. Uncomment one of the following
# compatibility flags according to what Python versions your plugin supports!
# __plugin_pythoncompat__ = ">=2.7,<3" # only python 2
# __plugin_pythoncompat__ = ">=3,<4" # only python 3
__plugin_pythoncompat__ = ">=2.7,<4"  # python 2 and 3


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = SignalclirestapiPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
