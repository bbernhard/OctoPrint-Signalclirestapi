# vim: set tabstop=8:expandtab:shiftwidth=4:softtabstop=4
# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.util
from octoprint.events import Events

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
import time
import threading
import subprocess

import websocket
import json

# linking other devices
# https://github.com/AsamK/signal-cli/wiki/Linking-other-devices-(Provisioning)

# signal-cli example within container
# su signal-api
# signal-cli --config /home/.local/share/signal-cli -a {number} listDevices

# generate uuid on new device
# signal-cli --config /home/.local/share/signal-cli link -n "{name}"      

# add device on master
# signal-cli --config /home/.local/share/signal-cli -a {number} addDevice --uri "{uuid}"

def signal_receive_thread(_plugin):
    valid_commands = ("STATUS", "PAUSE", "RESUME", "CANCEL", "GCODE", "CONNECT", "DISCONNECT", "STOP", "RESTART", "SHUTDOWN", "REBOOT")

    helpMsg = (
        "I respond to a number of different commands:\r\n\r\n" +
        "\tstatus\t\t\t\tmachine / job status report\r\n" +
        "\tpause\t\t\t\tpause current job (if active)\r\n" +
        "\tresume\t\t\tresume current job (if paused)\r\n" +
        "\tcancel\t\t\t\tcancel current job (if active)\r\n" +
        "\tgcode ###\t\t\tsend gcode (if connected)\r\n" +
        "\tconnect\t\t\tconnect to machine (if disconnected)\r\n" +
        "\tdisconnect\t\tdisconnect machine (if connected)\r\n" +
        "\tstop\t\t\t\t\tstops Octoprint (and me)\r\n" +
        "\trestart\t\t\t\trestarts Octoprint (and me)\r\n" +
        "\tshutdown\t\tshutdown our server\r\n" +
        "\treboot\t\t\t\treboot our server"
    )

    try:
        api = SignalCliRestApi(_plugin.url, _plugin.sender)
        mode = api.mode()

        # cache our groups
        groups = api.list_groups()

        # use a websocket if json-rpc is enabled
        if mode == "json-rpc":
            ws = websocket.create_connection(_plugin.url.replace("http://", "ws://") + "/v1/receive/" + _plugin.sender)

    except BaseException as e:
        _plugin._logger.error("signal_receive_thread top level: [{}]".format(e))
        time.sleep(1)        
            
    while not _plugin._shutting_down:
        try:
            if _plugin.enabled:
                if mode == "json-rpc":
                    msgs = [ json.loads(ws.recv()) ]
                else:
                    msgs = receive_message(_plugin.url, _plugin.sender)

                for msg in msgs:
                    message = None
                    groupId = None

                    if "envelope" in msg.keys() and "dataMessage" in msg["envelope"].keys():
                        dataMsg = msg["envelope"]["dataMessage"]
                        if "message" in dataMsg.keys(): message = dataMsg["message"].strip().upper()
                        if "groupInfo" in dataMsg.keys() and "groupId" in dataMsg["groupInfo"].keys(): groupId = dataMsg["groupInfo"]["groupId"]

                        if  message is None or message.split(" ")[0] not in valid_commands:
                            _plugin._send_message(helpMsg, snapshot=False)    
                            continue

                        # we only want to respond to messages meant for us
                        if groupId is None or groupId == _plugin._group_id["internal_id"]:
                            _plugin._logger.debug("signal_receive_thread: message=[{}] group=[{}]".format(message, groupId)) 

                            if message == "STATUS":
                                _plugin.on_print_progress("dummy", _plugin._supported_tags["filename"], _plugin._supported_tags["progress"], override=True)
                            elif message == "PAUSE":
                                _plugin._printer.pause_print()
                            elif message == "RESUME":
                                _plugin._printer.resume_print()
                            elif message == "CANCEL":
                                _plugin._printer.cancel_print()
                            elif message.startsWith("GCODE "):
                                _plugin._printer.commands(message.replace("GCODE ", ""))
                            elif message == "CONNECT":
                                _plugin._printer.connect()
                            elif message == "DISCONNECT":
                                _plugin._printer.disconnect()
                            elif message == "STOP":
                                cmd = "sudo service octoprint stop"
                                subprocess.call(cmd, shell=True)
                            elif message == "RESTART":
                                cmd = _plugin._settings.global_get(["server", "commands", "serverRestartCommand"])
                                subprocess.call(cmd, shell=True)
                            elif message == "SHUTDOWN":
                                cmd = _plugin._settings.global_get(["server", "commands", "systemShutdownCommand"])
                                subprocess.call(cmd, shell=True)
                            elif message == "REBOOT":
                                cmd = _plugin._settings.global_get(["server", "commands", "systemRestartCommand"])
                                subprocess.call(cmd, shell=True)

                        else:
                            # try again
                            tries = 0
                            while tries < 2:
                                for group in groups:
                                    if group["internal_id"] == groupId:
                                        _plugin._logger.debug("signal_receive_thread: rejecting message=[{}] group=[{}]".format(message, group["id"]))   
                                        send_message(_plugin.url, _plugin.sender, "Try again", [group["id"]])
                                        tries = 1
                                        time.sleep(44)                                    
                                        break
                                #refresh our groups if not found and try one more time
                                if tries < 1:
                                    groups = api.list_groups()
                                tries = tries + 1
        except BaseException as e:
            _plugin._logger.error("signal_receive_thread: [{}]".format(e))

            # let's try to re-initialize things (this may not go well)
            api = SignalCliRestApi(_plugin.url, _plugin.sender)
            mode = api.mode()
            groups = api.list_groups()
            if mode == "json-rpc":
                ws = websocket.create_connection(_plugin.url.replace("http://", "ws://") + "/v1/receive/" + _plugin.sender)
                time.sleep(1)

        finally:
            if mode != "json-rpc":
                time.sleep(1)
    
    if mode == "json-rpc":
        ws.close()

    _plugin._logger.debug("signal_receive_thread shutdown")

# MODE = normal receive only (do not use this for json-rpc)
def receive_message(url, sender_nr):
    if url is None or sender_nr is None or len(url) == 0 or len(sender_nr) == 0: return
    return SignalCliRestApi(url, sender_nr).receive()

def verify_connection_settings(url, sender_nr, recipients):
    if url is None or url == "":
        raise Exception("REST API URL needs to be set")
    if sender_nr is None or sender_nr == "":
        raise Exception("Sender Number needs to be set")
    if recipients is None or recipients == "":
        raise Exception("Please provide at least one recipient") 

def send_message(url, sender_nr, message, recipients, filenames=[]):
    verify_connection_settings(url, sender_nr, recipients) 
    SignalCliRestApi(url, sender_nr).send_message(message, recipients, filenames=filenames)

def create_group(url, sender_nr, members, name):
    api = SignalCliRestApi(url, sender_nr) 
    group_id = api.create_group(name, members)

    groups = api.list_groups()
    
    for group in groups:
        if group["id"] == group_id:
            return { "id": group_id, "internal_id": group["internal_id"] }

    raise Exception("id mismatch while adding group")

def get_webcam_snapshot(snapshot_url): 
    filename, _ = urlretrieve(snapshot_url, tempfile.gettempdir()+"/snapshot.jpg")
    return filename

def get_supported_tags():
    return {
                "filename": None,
                "elapsed_time": None,
                "host": socket.gethostname(),
                "user": getpass.getuser(),
                "progress": None,
                "reason": "unknown"
           }

class SignalclirestapiPlugin(octoprint.plugin.SettingsPlugin,
                             octoprint.plugin.AssetPlugin,
                             octoprint.plugin.SimpleApiPlugin,
                             octoprint.plugin.TemplatePlugin,
                             octoprint.plugin.EventHandlerPlugin,
                             octoprint.plugin.StartupPlugin,
                             octoprint.plugin.ProgressPlugin):

    def __init__(self):
        self._group_id = None 
        self._shutting_down = False
        self._supported_tags = get_supported_tags()

        self._settings_version = 2
    
    def on_after_startup(self):
        receiveThread = threading.Thread(target=signal_receive_thread, daemon=True, args=(self,)).start()

        if self.create_group_by_printer and not self.printer_group_id is None:
            self._group_id = self.printer_group_id

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
            filamentchangeevent=True,
            printresumedevent=True,
            printstartedeventtemplate="OctoPrint@{host}: {filename}: Job started.",
            printdoneeventtemplate="OctoPrint@{host}: {filename}: Job complete after {elapsed_time}.",
            printpausedeventtemplate="OctoPrint@{host}: {filename}: Job paused!",
            filamentchangeeventtemplate="OctoPrint@{host}: Filament change required!",
            printfailedeventtemplate="OctoPrint@{host}: {filename}: Job failed after {elapsed_time} ({reason})!", 
            printcancelledeventtemplate="OctoPrint@{host}: {filename}: Job cancelled after {elapsed_time}!",
            printresumedeventtemplate="OctoPrint@{host}: {filename}: Job resumed!",
            attachsnapshots=False,
            groupsettings="none",
            sendprintprogress=True,
            printergroupid={},
            progressintervals="20,40,60,80",
            sendprintprogresstemplate="OctoPrint@{host}: {filename}: Progess: {progress}%"
        ) 

    def get_settings_version(self):
        self._logger.debug("__init__: get_settings_version")
        return self._settings_version

    def on_settings_migrate(self, target, current):
        self._logger.debug("__init__: on_settings_migrate target=[{}] current=[{}]".format(target, current))

        # version 1 migration
        if current == None or current == 1:
            if self._settings.get_boolean(["creategroupbyprinter"]):
                self._settings.set(["groupsettings"], "machine" )
            elif self._settings.get_boolean(["creategroupforeveryprint"]):
                self._settings.set(["groupsettings"], "job" )
            else:
                self._settings.set(["groupsettings"], "none" )

            self._settings.remove(["creategroupforeveryprint"])
            self._settings.remove(["creategroupbyprinter"])
            
        self._settings.save()
        self._logger.info("Migrated to settings v%d from v%d", target, 1 if current == None else current)

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

        # we need to clear out group data if groupsettings changed
        if "groupsettings" in data:
            self._settings.set(["printergroupid"], {})
            self._settings.save()
            self._group_id = None
            
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
    def filament_change_event(self):
        return self._settings.get_boolean(["filamentchangeevent"])
    
    @property
    def print_cancelled_event(self):
        return self._settings.get_boolean(["printcancelledevent"])

    @property
    def print_resumed_event(self):
        return self._settings.get_boolean(["printresumedevent"])

    @property
    def create_group_for_every_print(self):
        return self._settings.get(["groupsettings"]) == "job"

    @property
    def create_group_by_printer(self):
        return self._settings.get(["groupsettings"]) == "machine"

    @property
    def printer_group_id(self):
        printergroupid = self._settings.get(["printergroupid"])
        return printergroupid if len(printergroupid) > 0 else None

    @property
    def print_progress_intervals(self):
        return self._settings.get(["progressintervals"]).split(",")

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
    def filament_change_event_template(self):
        return self._settings.get(["filamentchangeeventtemplate"])

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
                group_name = "Job " + str(datetime.now())
                self._group_id = create_group(self.url, self.sender, self.recipients, group_name) 
            except Exception as e:
                self._logger.exception("Couldn't create signal group")

    def _create_printer_group_if_not_exists(self):
        if not self.printer_group_id is None: 
            self._group_id = self.printer_group_id
            return
        try:
            group_name = self._printer_profile_manager.get_current_or_default()["name"]
            self._group_id = create_group(self.url, self.sender, self.recipients, group_name) 
            self._settings.set(["printergroupid"], self._group_id)
            self._settings.save()
        except Exception as e:
            self._logger.exception("Couldn't create signal group")

    def _send_message(self, message, snapshot=True):
        try:
            recipients = self.recipients

            if self.create_group_for_every_print or self.create_group_by_printer:
                if self.create_group_for_every_print and self._group_id is None:
                    self._create_group_if_not_exists()

                if self.create_group_by_printer:
                    self._create_printer_group_if_not_exists()

                if self._group_id is None:
                    self._logger.error("Couldn't send message %s as group does not exist", message)
                    return

                recipients = [self._group_id["id"]]
            
            snapshot_filenames = []
            if self.attach_snapshots and snapshot:
                snapshot_url = self._settings.global_get(["webcam", "snapshot"])

                try:
                    snapshot_filenames.append(get_webcam_snapshot(snapshot_url))
                except Exception as e:
                    self._logger.exception("Couldn't get webcam image...sending without it")
            send_message(self.url, self.sender, message, recipients, snapshot_filenames)
        except Exception as e:
            self._logger.exception("Couldn't send signal message: %s", str(e))         

    def on_event(self, event, payload):
        if event == Events.SHUTDOWN: 
            self._shutting_down = True
            self._logger.debug("triggering receive client shutdown")
            return
            
        if payload is not None:
            if "name" in payload:
                self._supported_tags["filename"] = payload["name"]
            if "time" in payload:
                self._supported_tags["elapsed_time"] = octoprint.util.get_formatted_timedelta(timedelta(seconds=payload["time"]))
            if "reason" in payload:
                self._supported_tags["reason"] = payload["reason"]

        if event == Events.PRINT_STARTED:
            self._supported_tags["progress"] = 0
            if self.create_group_for_every_print: self._group_id = None 

            if self.enabled and self.print_started_event:
                message = self.print_started_event_template.format(**self._supported_tags) 
                self._send_message(message) 
        elif event == Events.PRINT_DONE:
            if self.enabled and self.print_done_event:
                message = self.print_done_event_template.format(**self._supported_tags)
                self._send_message(message)
        elif event == Events.PRINT_FAILED:
            if self.enabled and self.print_failed_event:
                message = self.print_failed_event_template.format(**self._supported_tags)
                self._send_message(message)
        elif event == Events.PRINT_CANCELLED:
            if self.enabled and self.print_cancelled_event:
                message = self.print_cancelled_event_template.format(**self._supported_tags)
                self._send_message(message)
        elif event == Events.PRINT_PAUSED:
            if self.enabled and self.print_paused_event:
                message = self.print_paused_event_template.format(**self._supported_tags)
                self._send_message(message)
        elif event == Events.FILAMENT_CHANGE:
            if self.enabled and self.filament_change_event:
                message = self.filament_change_event_template.format(**self._supported_tags)
                self._send_message(message)
        elif event == Events.PRINT_RESUMED:
            if self.enabled and self.print_resumed_event:
                message = self.print_resumed_event_template.format(**self._supported_tags)
                self._send_message(message)

    def on_print_progress(self, storage, path, progress, override=False):
        if self.enabled and (self.send_print_progress or override):
            self._supported_tags["progress"] = progress
            self._supported_tags["filename"] = path

            if progress is None or progress in (0, 100) or path is None or len(path) == 0: 
                message = "No job is currently active"
            else:  
                message = self.send_print_progress_template.format(**self._supported_tags)

            if str(progress) in self.print_progress_intervals or override:
                self._send_message(message)

    def get_api_commands(self):
        return dict(testMessage=["sender", "recipients", "url"]);

    def on_api_command(self, command, data): 
        if command == "testMessage":
            self._logger.debug(data)
            
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
