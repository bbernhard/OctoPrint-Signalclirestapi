/*
 * View model for OctoPrint-Signalclirestapi
 *
 * Author: Bernhard
 * License: AGPLv3
 */
$(function() {
    function SignalclirestapiViewModel(parameters) {
        var self = this;

		$("#testMessageButtonLoadingSpinner").hide();

		/*self.testActive = ko.observable(false);
        self.testResult = ko.observable(false);
        self.testSuccessful = ko.observable(false);
        self.testMessage = ko.observable();

		self.testActive(false);
		self.testResult(false);
		self.testSuccessful(false);
		self.testMessage("");*/
    }

	self.testMessage = function(data) {
		$("#testMessageButtonLoadingSpinner").show();
		$("#testMessageInfo").text("");

		var recipients = $("#recipientsInput").val();
		var sender = $("#senderInput").val();
		var url = $("#urlInput").val();
		console.log("bla")
		//Octoprint.simpleApiCommand("signalclirestapi", "testMessage", {});
		$.ajax({
			url: API_BASEURL + "plugin/signalclirestapi",
			type: "POST",
			dataType: "json",
			data: JSON.stringify({
				command: "testMessage",
				sender: sender,
				recipients: recipients,	
				url: url
			}),
			contentType: "application/json; charset=UTF-8",
			success: function(response) {
				$("#testMessageButtonLoadingSpinner").hide();
				if (!response.success && response.hasOwnProperty("msg")) {
					$("#testMessageInfo").text(response.msg);
				} else {
					$("#testMessageInfo").text("Unexpected error");
				}
			}
		});
    };

    /* view model class, parameters for constructor, container to bind to
     * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
     * and a full list of the available options.
     */
    OCTOPRINT_VIEWMODELS.push({
        construct: SignalclirestapiViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ ],
        // Elements to bind to, e.g. #settings_plugin_signalclirestapi, #tab_plugin_signalclirestapi, ...
        elements: [ ]
    });
});
