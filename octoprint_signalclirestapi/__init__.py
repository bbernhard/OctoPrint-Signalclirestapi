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
import os
import requests
#
# register a new device
# signal-cli --config /home/.local/share/signal-cli  -a ACCOUNT register --voice
#
# with captcha
# https://github.com/AsamK/signal-cli/wiki/Registration-with-captcha
#
# signal-cli --config /home/.local/share/signal-cli -a {number} register --voice --captcha {captcha}
#
# verify
# signal-cli --config /home/.local/share/signal-cli -a {number} verify {code}
#
# linking other devices
# https://github.com/AsamK/signal-cli/wiki/Linking-other-devices-(Provisioning)
#
# signal-cli example within container
# su signal-api
# signal-cli --config /home/.local/share/signal-cli -a {number} listDevices
#
# generate uuid on new device
# signal-cli --config /home/.local/share/signal-cli link -n "{name}"      
#
# add device on master
# signal-cli --config /home/.local/share/signal-cli -a {number} addDevice --uri "{uuid}"
#
class ReceiveThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        super(ReceiveThread, self).__init__(*args, **kwargs)

        self._plugin = None
        self._api = None
        self._websocket = None

    # must be called before start
    def set_plugin(self, plugin):
        self._plugin = plugin

    def restart(self):
        self.shutdown(releasePlugin=False)
 
    def shutdown(self, releasePlugin=True):
        try:
            if self._websocket:
                self._websocket.close()
        except Exception as e:
            self._plugin._logger.exception("ReceiveThread: shutdown exception: [{}]".format(e))
        finally:
            self._websocket = None
            self._api = None
            if releasePlugin: self._plugin = None
        
    def run(self):
        valid_commands = ("STATUS", "PAUSE", "RESUME", "CANCEL", "GCODE", "TOOL", "BED", "CHAMBER", "CONNECT", "DISCONNECT", "SHELL", "STOP", "RESTART", "SHUTDOWN", "REBOOT")
        helpMsg = (
            "I respond to a number of different commands:\n\n" +
            "\tstatus\t\t\t\tmachine / job status\n" +
            "\tpause\t\t\t\tpause current job\n" +
            "\tresume\t\t\tresume current job\n" +
            "\tcancel\t\t\t\tcancel current job\n" +
            "\tgcode ###\t\tsend gcode\n" +
            "\ttool ###\t\t\ttool temperature\n" +
            "\tbed ###\t\t\tbed temperature\n" +
            "\tchamber ###\tchamber temperature\n" +
            "\tconnect\t\t\tconnect to machine\n" +
            "\tdisconnect\t\tdisconnect machine\n" +
            "\tshell ###\t\t\texecute command\n" +
            "\tstop\t\t\t\t\tstops Octoprint\n" +
            "\trestart\t\t\t\trestarts Octoprint\n" +
            "\tshutdown\t\tshutdown our server\n" +
            "\treboot\t\t\t\treboot our server"
        )
        mode = None

        while self._plugin:
            try:
                if self._plugin.enabled:
                    if not self._api:
                        self._api = SignalCliRestApi(self._plugin.url, self._plugin.sender)
                        mode = self._api.mode()

                    # use a websocket if json-rpc is enabled
                    if not self._websocket and mode == "json-rpc":
                        self._websocket = websocket.create_connection(self._plugin.url.replace("http://", "ws://") + "/v1/receive/" + self._plugin.sender)

                    if mode == "json-rpc":
                        msgs = [ json.loads(self._websocket.recv()) ]
                    else:
                        msgs = receive_message(self._plugin.url, self._plugin.sender)

                    for msg in msgs:
                        message = None
                        groupId = None

                        if "envelope" in msg.keys() and "dataMessage" in msg["envelope"].keys():
                            dataMsg = msg["envelope"]["dataMessage"]
                            if "message" in dataMsg.keys(): message = dataMsg["message"]

                            # only process a message if it isn't empty
                            if message: 
                                message = message.strip() 
                            else: 
                                self._plugin._logger.debug("ReceiveThread: dropping empty message")
                                continue

                            # set the group id if the message is from one
                            if "groupInfo" in dataMsg.keys() and "groupId" in dataMsg["groupInfo"].keys(): groupId = dataMsg["groupInfo"]["groupId"]

                            # we only want to respond to messages meant for us
                            if groupId is None or groupId == self._plugin._group_id["internal_id"]:
                                self._plugin._logger.debug("ReceiveThread: message=[{}] group=[{}]".format(message, groupId)) 

                                # display a help message if we receive something we do not understand
                                command = "" if message is None else message.split(" ")[0]
                                if command.upper() not in valid_commands:
                                    self._plugin._send_message(helpMsg, snapshot=False)    
                                    continue

                                if command.upper() == "STATUS":
                                    self._plugin.on_demand_status_report()
                                elif command.upper() == "PAUSE":
                                    self._plugin._printer.pause_print()
                                elif command.upper() == "RESUME":
                                    self._plugin._printer.resume_print()
                                elif command.upper() == "CANCEL":
                                    self._plugin._printer.cancel_print()
                                elif command.upper() == "GCODE":
                                    self._plugin._printer.commands(message.replace(command + " ", ""))
                                elif command.upper() == "TOOL":
                                    self._plugin._printer.set_temperature("tool0", float(message.replace(command + " ", "")))
                                elif command.upper() == "BED":
                                    self._plugin._printer.set_temperature("bed", float(message.replace(command + " ", "")))
                                elif command.upper() == "CHAMBER":
                                    self._plugin._printer.set_temperature("chamber", float(message.replace(command + " ", "")))
                                elif command.upper() == "CONNECT":
                                    self._plugin._printer.connect()
                                elif command.upper() == "DISCONNECT":
                                    self._plugin._printer.disconnect()
                                elif command.upper() == "SHELL":
                                    subprocess.call(message.replace(command + " ", ""), shell=True)
                                elif command.upper() == "STOP":
                                    cmd = "sudo service octoprint stop"
                                    subprocess.call(cmd, shell=True)
                                elif command.upper() == "RESTART":
                                    cmd = self._plugin._settings.global_get(["server", "commands", "serverRestartCommand"])
                                    subprocess.call(cmd, shell=True)
                                elif command.upper() == "SHUTDOWN":
                                    cmd = self._plugin._settings.global_get(["server", "commands", "systemShutdownCommand"])
                                    subprocess.call(cmd, shell=True)
                                elif command.upper() == "REBOOT":
                                    cmd = self._plugin._settings.global_get(["server", "commands", "systemRestartCommand"])
                                    subprocess.call(cmd, shell=True)
                            else:
                                self._plugin._logger.debug("signal_receive_thread dropping message [{}]".format("message"))
            except BaseException as e:
                if self._plugin:
                    self._plugin._logger.warn("ReceiveThread: main loop exception: [{}]".format(e))
                    time.sleep(5)
                    self.restart()
            finally:
                if (self._plugin and not self._plugin.enabled) or (self._api and mode != "json-rpc"):
                    time.sleep(1)
    
        self.shutdown()
        self._plugin._logger.debug("signal_receive_thread shutdown")

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

def defer_send_message(_plugin, message, snapshot, snapshot_as_gif):
    try:
        _plugin._logger.debug("defer_send_message: preparing message")

        recipients = _plugin.recipients

        # check group settings and set group id if applicible 
        if _plugin.create_group_for_every_print or _plugin.create_group_by_printer:
            if _plugin.create_group_for_every_print and _plugin._group_id is None:
                _plugin._create_group_if_not_exists()

            if _plugin.create_group_by_printer:
                _plugin._create_printer_group_if_not_exists()

            # this should never happen
            if _plugin._group_id is None:
                _plugin._logger.warn("Cannot send message due to missing group id - using recipient list instead")
            else:
                recipients = [_plugin._group_id["id"]]

        # typing indicator - turn on
        for recipient in recipients:
            requests.put(_plugin.url + "/v1/typing-indicator/" + _plugin.sender, json={"recipient": recipient})

        snapshot_filenames = []
        if _plugin.attach_snapshots and snapshot:
            try:
                if not snapshot_as_gif:
                    snapshot_filenames.append(get_webcam_snapshot(_plugin.snapshot_url))
                else:
                    gif = get_webcam_animated_gif(_plugin)
                    if gif: snapshot_filenames.append(gif)
            except BaseException as e:
                _plugin._logger.exception("Could not get webcam image...sending without it: [{}]".format(e))

        _plugin._logger.debug("defer_send_message: sending message")

        # typing indicator - turn on again
        for recipient in recipients:
            requests.put(_plugin.url + "/v1/typing-indicator/" + _plugin.sender, json={"recipient": recipient})

        send_message(_plugin.url, _plugin.sender, message, recipients, snapshot_filenames)

        # typing indicator - turn off
        for recipient in recipients:
            requests.delete(_plugin.url + "/v1/typing-indicator/" + _plugin.sender, json={"recipient": recipient})

        _plugin._logger.debug("defer_send_message: messge sent")
    except BaseException as e:
        if "Group not found" in str(e):
            _plugin._logger.warning("group does not exist - trying again with recipient list")
            _plugin._printer_group_id = None
            _plugin._group_id = None
            _plugin._settings.set(["printergroupid"], {})
            _plugin._settings.save()
            try:
                send_message(_plugin.url, _plugin.sender, message, _plugin.recipients, snapshot_filenames)
                _plugin._logger.debug("defer_send_message: messge sent")
            except BaseException as e:
                _plugin._logger.exception("Could not send signal message after clearing group_id: []".format(e))    
        else:
            _plugin._logger.exception("Could not send signal message: [{}]".format(e))    
    finally:
        if snapshot_as_gif and snapshot_filenames:
            os.remove(snapshot_filenames[0])

def send_message(url, sender_nr, message, recipients, filenames=[]):
    verify_connection_settings(url, sender_nr, recipients) 
    SignalCliRestApi(url, sender_nr).send_message(message, recipients, filenames=filenames)

def create_group(_plugin, name):
    api = SignalCliRestApi(_plugin.url, _plugin.sender) 
    group_id = api.create_group(name, _plugin.recipients)

    groups = api.list_groups()

    for group in groups:
        if group["id"] == group_id:
            return { "id": group_id, "internal_id": group["internal_id"] }

    raise Exception("id mismatch while adding group")

def get_webcam_snapshot(snapshot_url): 
    filename, _ = urlretrieve(snapshot_url, tempfile.gettempdir()+"/snapshot.jpg")
    return filename

# inspired by Octoprint Telegram
# https://github.com/fabianonline/OctoPrint-Telegram
def get_webcam_animated_gif(_plugin):
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "static", "gifcache")
    if not os.path.exists(path): os.mkdir(path)

    filename = "stream-" + str(time.time()) + ".gif"
    fullpath = os.path.join(path, filename)

    flipH = _plugin._settings.global_get(["webcam", "flipH"])
    flipV = _plugin._settings.global_get(["webcam", "flipV"])
    rotate = _plugin._settings.global_get(["webcam", "rotate90"])

    # ffmpeg -t 10 -y -threads 1 -i http://octopi-s1pro/webcam/?action=stream -filter_complex "fps=23,scale=-1:720" output.gif
    args =  [
                _plugin.ffmpeg_path, 
                "-t", str(_plugin.gif_duration), 
                "-y", 
                "-threads", "1", 
                "-i", _plugin.stream_url,
                "-filter_complex"
            ]

    filter_complex = "fps={},scale=-1:{}".format(_plugin.gif_framerate, _plugin.gif_resolution.replace("p", ""))

    if flipV:
        filter_complex = filter_complex + ",vflip"
    if flipH:
        filter_complex = filter_complex + ",hflip"
    if rotate:
            filter_complex = filter_complex + ",transpose=1"

    args.append(filter_complex)
    args.append(fullpath)

    result = subprocess.run(args)
    _plugin._logger.debug("get_webcam_animated_gif: [{}]".format(result))

    if os.path.exists(fullpath):
        return fullpath
    
    return None

def get_supported_tags():
    return {
                "filename": None,
                "elapsed_time": None,
                "host": socket.gethostname(),
                "user": getpass.getuser(),
                "progress": None,
                "reason": "unknown",
                "state": "unknown",
                "tool_temp_actual": 0,
                "tool_temp_target": 0,
                "bed_temp_actual": 0,
                "bed_temp_target": 0,
                "chamber_temp_actual": 0,
                "chamber_temp_target": 0,
                "new_line": "\n",
                "degrees": "\u00B0"
           }

class SignalclirestapiPlugin(octoprint.plugin.SettingsPlugin,
                             octoprint.plugin.AssetPlugin,
                             octoprint.plugin.SimpleApiPlugin,
                             octoprint.plugin.TemplatePlugin,
                             octoprint.plugin.EventHandlerPlugin,
                             octoprint.plugin.ProgressPlugin):

    def __init__(self):
        self._receiveThread = None
        self._group_id = None 
        self._printer_group_id = None
        self._supported_tags = get_supported_tags()

        self._settings_version = 2
    
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
            sendprintprogresstemplate="OctoPrint@{host}: {filename}: Progess: {progress}%",
            notitysystemevents=False,
            notityconnnectionevents=False,
            statusreporttemplate="OctoPrint@{host}{new_line}Machine State: {state}{new_line}Job State: {filename} / {progress}{new_line}Tool Temperature: {tool_temp_actual}{degrees} / {tool_temp_target}{degrees}{new_line}Bed Temperature: {bed_temp_actual}{degrees} / {bed_temp_target}{degrees}",
            snapshotasgif=False,
            gifduration=5,
            gifframerate=10,
            gifresolution="480p"
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
        # we need to clear out group data if a couple key settings have changed
        if "groupsettings" in data or "url" in data or "sendernr" in data or "recipientnrs" in data:
            self._settings.set(["printergroupid"], {})
            self._settings.save()
            self._printer_group_id = None
            self._group_id = None
            self._receiveThread.restart()

    @property
    def enabled(self):
        return self._settings.get_boolean(["enabled"])

    @property
    def notity_system_events(self):
        return self._settings.get_boolean(["notitysystemevents"])

    @property
    def notity_connnection_events(self):
        return self._settings.get_boolean(["notityconnnectionevents"])

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
    def print_progress_intervals(self):
        return self._settings.get(["progressintervals"]).split(",")

    @property
    def attach_snapshots(self):
        return self._settings.get_boolean(["attachsnapshots"])

    @property
    def snapshot_url(self):
        return self._settings.global_get(["webcam", "snapshot"])
    
    @property
    def snapshot_as_gif(self):
        return self._settings.get_boolean(["snapshotasgif"])
    
    @property
    def gif_duration(self):
        return self._settings.get(["gifduration"])
    
    @property
    def gif_framerate(self):
        return self._settings.get(["gifframerate"])
    
    @property
    def gif_resolution(self):
        return self._settings.get(["gifresolution"])
    
    @property
    def stream_url(self):
        url = self._settings.global_get(["webcam", "stream"])
        if not url.startswith("http"): url = "http://localhost" + url
        return url
    
    @property
    def ffmpeg_path(self):
        return self._settings.global_get(["webcam", "ffmpeg"])
    
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

    @property
    def send_status_report_template(self):
        return self._settings.get(["statusreporttemplate"])

    def _create_group_if_not_exists(self):
        if self._group_id is None:
            try:
                group_name = "Job " + str(datetime.now())
                self._group_id = create_group(self, group_name) 
                self._logger.debug("_create_group_if_not_exists: new group created")
            except Exception as e:
                self._logger.exception("_create_group_if_not_exists: Couldn't create signal group: {}".format(e))

    def _create_printer_group_if_not_exists(self):
        if self._printer_group_id:
            self._group_id = self._printer_group_id
            return
        try:
            group_name = self._printer_profile_manager.get_current_or_default()["name"]
            self._printer_group_id = create_group(self, group_name) 
            self._group_id = self._printer_group_id
            self._settings.set(["printergroupid"], self._printer_group_id)
            self._settings.save()
            self._logger.debug("_create_printer_group_if_not_exists: new group created")
        except Exception as e:
            self._logger.exception("_create_printer_group_if_not_exists: Couldn't create signal group: {}".format(e))

    def _send_message(self, message, snapshot=True, snapshot_as_gif=False):
        # run on its own thread to prevent blocking of OctoPrint
        self._logger.debug("_send_message: deferring message")
        threading.Thread(target=defer_send_message, args=(self, message, snapshot, snapshot_as_gif)).start()
     
    def on_event(self, event, payload):
        # populate tags managed via event payload data
        if payload is not None:
            if "name" in payload:
                self._supported_tags["filename"] = payload["name"]
            if "time" in payload:
                self._supported_tags["elapsed_time"] = octoprint.util.get_formatted_timedelta(timedelta(seconds=payload["time"]))
            if "reason" in payload:
                self._supported_tags["reason"] = payload["reason"]

        # populate tags managed elsewhere
        self.update_supported_tags()

        # special cases for PRINT_STARTED, STARTUP, and SHUTDOWN
        if event == Events.PRINT_STARTED:
            self._supported_tags["progress"] = 0
            if self.create_group_for_every_print: self._group_id = None 
            if self.enabled and self.print_started_event:
                message = self.print_started_event_template.format(**self._supported_tags) 
                self._send_message(message) 
            return
        elif event == Events.STARTUP:
            self._printer_group_id = self._settings.get(["printergroupid"])
            if not self._printer_group_id: self._printer_group_id = None

            self._receiveThread = ReceiveThread()
            self._receiveThread.daemon = True
            self._receiveThread.set_plugin(self)
            self._receiveThread.start() 

            if self.create_group_by_printer and self._printer_group_id:
                self._group_id = self._printer_group_id

            if self.enabled and self.notity_system_events:
                self._send_message("OctoPrint@{host}: Started".format(**self._supported_tags))

            return
        elif event == Events.SHUTDOWN: 
            if self.enabled and self.notity_system_events:
                self._send_message("OctoPrint@{host}: Shutting down".format(**self._supported_tags))        
            self._receiveThread.shutdown()
            self._receiveThread.join()
            self._logger.debug("shutdown complete")
            return
            
        # bail if notifications are not enabled
        if not self.enabled:
            return

        if event == Events.CONNECTED and self.notity_connnection_events:
            self._send_message("OctoPrint@{host}: Connected".format(**self._supported_tags))
        elif event == Events.DISCONNECTED and self.notity_connnection_events:
            self._send_message("OctoPrint@{host}: Disconnected".format(**self._supported_tags))
        elif event == Events.PRINT_DONE and self.print_done_event:
            message = self.print_done_event_template.format(**self._supported_tags)
            self._send_message(message)
        elif event == Events.PRINT_FAILED and self.print_failed_event:
            message = self.print_failed_event_template.format(**self._supported_tags)
            self._send_message(message)
        elif event == Events.PRINT_CANCELLED and self.print_cancelled_event:
            message = self.print_cancelled_event_template.format(**self._supported_tags)
            self._send_message(message)
        elif event == Events.PRINT_PAUSED and self.print_paused_event:
            message = self.print_paused_event_template.format(**self._supported_tags)
            self._send_message(message)
        elif event == Events.FILAMENT_CHANGE and self.filament_change_event:
            message = self.filament_change_event_template.format(**self._supported_tags)
            self._send_message(message)
        elif event == Events.PRINT_RESUMED and self.print_resumed_event:
            message = self.print_resumed_event_template.format(**self._supported_tags)
            self._send_message(message)

    def on_print_progress(self, storage, path, progress):
        if self.enabled and self.send_print_progress:
            self._supported_tags["progress"] = progress
            self._supported_tags["filename"] = path

            # populate tags managed elsewhere
            self.update_supported_tags()

            if str(progress) in self.print_progress_intervals:
                message = self.send_print_progress_template.format(**self._supported_tags)
                self._send_message(message, snapshot_as_gif=self.snapshot_as_gif)

    def on_demand_status_report(self):
        if self.enabled:
            # populate tags managed elsewhere
            self.update_supported_tags()
            tags = self._supported_tags.copy()

            if self._printer.is_printing() or self._printer.is_paused() or self._printer.is_pausing():
                tags["progress"] = "{}%".format(self._supported_tags["progress"])
            else:
                tags["filename"] = "*"
                tags["progress"] = "*"

            message = self.send_status_report_template.format(**tags)
            self._send_message(message, snapshot_as_gif=self.snapshot_as_gif)

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

    def update_supported_tags(self):
        self._supported_tags["state"] = self._printer.get_state_string()

        temps = self._printer.get_current_temperatures()
        if temps:
            if "tool0" in temps.keys():
                self._supported_tags["tool_temp_actual"] = temps["tool0"]["actual"]
                self._supported_tags["tool_temp_target"] = temps["tool0"]["target"]
            if "bed" in temps.keys():
                self._supported_tags["bed_temp_actual"] = temps["bed"]["actual"]
                self._supported_tags["bed_temp_target"] = temps["bed"]["target"]
            if "chamber" in temps.keys():
                self._supported_tags["chamber_temp_actual"] = temps["chamber"]["actual"]
                self._supported_tags["chamber_temp_target"] = temps["chamber"]["target"]
        else:
                self._supported_tags["tool_temp_actual"] = "*"
                self._supported_tags["tool_temp_target"] = "*"
                self._supported_tags["bed_temp_actual"] = "*"
                self._supported_tags["bed_temp_target"] = "*"
                self._supported_tags["chamber_temp_actual"] = "*"
                self._supported_tags["chamber_temp_target"] = "*"


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
