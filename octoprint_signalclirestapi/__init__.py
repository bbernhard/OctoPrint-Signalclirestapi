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
import flask
from pysignalclirestapi import SignalCliRestApi


class SignalclirestapiPlugin(octoprint.plugin.SettingsPlugin,
                             octoprint.plugin.AssetPlugin,
                             octoprint.plugin.SimpleApiPlugin,
                             octoprint.plugin.TemplatePlugin):

    # ~~ SettingsPlugin mixin

    def get_api_commands(self):
        self._logger.info("Manually triggered get_api")
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
            printdoneeventtemplate="OctoPrint@{host}: {filename}: Job complete after {elapsed_time}.",
            printpausedeventtemplate="OctoPrint@{host}: {filename}: Job paused!",
            printfailedeventtemplate="OctoPrint@{host}: {filename}: Job failed after {elapsed_time} ({reason})!",
            attachsnapshots=False,
            creategroupforeveryprint=True
        )

    def _verify_connection_settings(self, url, sender_nr, recipients):
        if url is None or url == "":
            raise Exception("REST API URL needs to be set")
        if sender_nr is None or sender_nr == "":
            raise Exception("Sender Number needs to be set")
        if recipients is None or recipients == "":
            raise Exception("Please provide at least one recipient")   

    def _send_test_message(self, url, sender_nr, recipients, message):
        self._verify_connection_settings(url, sender_nr, recipients) 
        
        api = SignalCliRestApi(url, sender_nr)
        api.send_message(message, recipients.split(","))

    def _send_message(self, message):
        try:
            self._verify_connection_settings(self.url, self.sender, self.recipients) 

            api = SignalCliRestApi(url, sender_nr)
            api.send_message(message, recipients.split(","))
        except Exception as e:
            self._logger.error("Couldn't send signal message: %s" %str(e))
        
    @property
    def enabled(self):
       return self._settings.get("enabled")

    @property
    def url(self):
        return self._settings.get("url")
    
    @property
    def sender(self):
        return self._settings.get("sendernr")
    
    @property
    def recipients(self):
        return self._settings.get("recipientsnrs").split(",")

    @property
    def print_done_event(self):
        return self._settings.get("printdoneevent")

    @property
    def print_started_event(self):
        return self._settings.get("printstartedevent")
        
    @property
    def print_failed_event(self):
        return self._settings.get("printfailedevent")
    
    @property
    def print_paused_event(self):
        return self._settings.get("printpausedevent")
    
    @property
    def print_cancelled_event(self):
        return self._settings.get("printcancelledevent")


    def on_api_command(self, command, data):
        if command == "testMessage":
            self._logger.info(data)
            
            url = None
            sender_nr = None
            recipients = None
            try:
                url = data["url"]
                sender_nr = data["sender"]
                recipients = data["recipients"]
            except KeyError as e:
                self._logger.error("Couldn't get data: %s" %str(e))
                return
            try:
                self._send_test_message(url, sender_nr, recipients, "Hello from OctoPrint")  
            except Exception as e:
                return flask.jsonify(dict(success=False, msg=str(e)))
            
            return flask.jsonify(dict(success=False, msg="Success! Please check your phone."))
        elif command == "PrintStarted":
            if self.enabled and self.print_started_event:
                self._send_message("Print Started") 
        elif command == "PrintDone":
            if self.enabled and self.print_done_event:
                self._send_message("Print Done")
        elif command == "PrintFailed":
            if self.enabled and self.print_failed_event:
                self._send_message("Print Failed")
        elif command == "PrintCancelled":
            if self.enabled and self.print_cancelled_event:
                self._send_message("Print Canceled")
        elif command == "PrintPaused":
            if self.enabled and self.print_paused_event:
                self._send_message("Print Paused")

            
    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=False)
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
