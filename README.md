# OctoPrint-Signalclirestapi

A Signal Messenger Integration for [Octorpint](https://octoprint.org/) which supports Signal Messenger Groups and uses the [signal-messenger-rest-api docker image](https://github.com/bbernhard/signal-cli-rest-api).

## Features

* Allows to create separate Signal Messenger groups for every print
* Support for `Print Started`, `Print Stopped`, `Print Paused`, `Print Resumed`, `Print Cancelled`, `Print Failed` events
* Support for webcam snapshots
* Support for periodic print progress notifications. 

## Why signal-cli-rest-api?

The main advantage of the [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) is, that you don't necessarily need to run it on the same host system as Octoprint. That means, you can register one phone number with the `signal-cli-rest-api` and use that for various type of notifications in your house (e.g: Octoprint, Home Assistant, etc.)

## Docker Container Setup

In order to use this Octoprint Plugin, you need to have a running `signal-cli-rest-api` docker container somewhere. The following [guide](https://github.com/bbernhard/signal-cli-rest-api/blob/master/doc/OCTOPRINT.md) describes how you can set one up.

## Octoprint Plugin Installation

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/bbernhard/OctoPrint-Signalclirestapi/archive/master.zip


## Octoprint Plugin Configuration

Please make sure to specify the correct `REST API URL` in the configuration!

<img src="https://raw.githubusercontent.com/bbernhard/Octoprint-Signalclirestapi/master/doc/config1.png" width="500">
<img src="https://raw.githubusercontent.com/bbernhard/Octoprint-Signalclirestapi/master/doc/config2.png" width="500">
<img src="https://raw.githubusercontent.com/bbernhard/Octoprint-Signalclirestapi/master/doc/config3.png" width="500">
<img src="https://raw.githubusercontent.com/bbernhard/Octoprint-Signalclirestapi/master/doc/config4.png" width="500">
