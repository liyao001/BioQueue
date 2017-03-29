/*!
* Copyright (c) 2013 Profoundis Labs Pvt. Ltd., and individual contributors.
*
* All rights reserved.
*/
/*
 * An autosuggest textbox control.
 * @class
 * @scope public
 */
function AutoSuggestControl(id_or_element /*:HTMLInputElement*/) {
    this.provider /*:SuggestionProvider*/ = new wordSuggestions();
    /**
     * The textbox to capture, specified by element_id.
     * @scope private
     */
    this.textbox /*:HTMLInputElement*/ = typeof id_or_element == "string" ? document.getElementById(id_or_element) : id_or_element;
    //this.textbox /*:HTMLInputElement*/ = typeof id_or_element == "string" ? $(id_or_element) : id_or_element;

    //initialize the control
    this.init();

}


/**
 * Autosuggests one or more suggestions for what the user has typed.
 * If no suggestions are passed in, then no autosuggest occurs.
 * @scope private
 * @param aSuggestions An array of suggestion strings.
 */
AutoSuggestControl.prototype.autosuggest = function (aSuggestions /*:Array*/) {

    //make sure there's at least one suggestion

    if (aSuggestions.length > 0) {
            this.typeAhead(aSuggestions[0]);
    }
};


/**
 * Handles keyup events.
 * @scope private
 * @param oEvent The event object for the keyup event.
 */
AutoSuggestControl.prototype.handleKeyUp = function (oEvent /*:Event*/) {

    var iKeyCode = oEvent.keyCode;
    var evtobj = oEvent;
    window.eventobj = evtobj;
    if ((iKeyCode != 16 && iKeyCode < 32) || (iKeyCode >= 33 && iKeyCode <= 46) || (iKeyCode >= 112 && iKeyCode <= 123) || (iKeyCode == 65 && evtobj.ctrlKey) || (iKeyCode == 90 && evtobj.ctrlKey)) {
        //ignore
        if (iKeyCode == 90 && evtobj.ctrlKey) {
            // window.getSelection().deleteFromDocument();
            // TODO: need to find a way to select the rest of the text and delete.
        }
    } else {
        //request suggestions from the suggestion provider
        this.provider.requestSuggestions(this)
    }
};

/**
 * Initializes the textarea with event handlers for
 * auto suggest functionality.
 * @scope private
 */
AutoSuggestControl.prototype.init = function () {

    //save a reference to this object
    var oThis = this;
    //assign the onkeyup event handler
    lastDate = new Date();
    oThis.textbox.onkeyup = function (oEvent) {

        //check for the proper location of the event object
        if (!oEvent) {
            oEvent = window.event;
        }
        newDate = new Date();
        if (newDate.getTime() > lastDate.getTime() + 200) {
                oThis.handleKeyUp(oEvent);
                lastDate = newDate;
        }
        };

};

/**
 * Selects a range of text in the textarea.
 * @scope public
 * @param iStart The start index (base 0) of the selection.
 * @param iLength The number of characters to select.
 */
AutoSuggestControl.prototype.selectRange = function (iStart /*:int*/, iLength /*:int*/) {
    //use text ranges for Internet Explorer
    if (this.textbox.createTextRange) {
        var oRange = this.textbox.createTextRange();
        oRange.moveStart("character", iStart);
        oRange.moveEnd("character", iLength);
        oRange.select();

    //use setSelectionRange() for Mozilla
    } else if (this.textbox.setSelectionRange) {
        this.textbox.setSelectionRange(iStart, iLength);
    }

    //set focus back to the textbox
    this.textbox.focus();
};

/**
 * Inserts a suggestion into the textbox, highlighting the
 * suggested part of the text.
 * @scope private
 * @param sSuggestion The suggestion for the textbox.
 */
AutoSuggestControl.prototype.typeAhead = function (sSuggestion /*:String*/) {

    //check for support of typeahead functionality
    if (this.textbox.createTextRange || this.textbox.setSelectionRange){
        var lastSpace = this.textbox.value.lastIndexOf(" ");
        var lastQuote = this.textbox.value.lastIndexOf("'");
        var lastHypen = this.textbox.value.lastIndexOf("-");
        var lastDoubleQuote = this.textbox.value.lastIndexOf('"');
        var lastEnter = this.textbox.value.lastIndexOf("\n");
        var lastIndex = Math.max(lastSpace, lastEnter, lastQuote, lastHypen, lastDoubleQuote) + 1;
        var contentStripped = this.textbox.value.substring(0, lastIndex);
        var lastWord = this.textbox.value.substring(lastIndex, this.textbox.value.length);
        this.textbox.value = contentStripped + sSuggestion; //.replace(lastWord,"");
        var start = this.textbox.value.length - sSuggestion.replace(lastWord,"").length;
        var end = this.textbox.value.length;
        this.selectRange(start, end);
        }
};



/**
 * Request suggestions for the given autosuggest control.
 * @scope protected
 * @param oAutoSuggestControl The autosuggest control to provide suggestions for.
 */
wordSuggestions.prototype.requestSuggestions = function (oAutoSuggestControl /*:AutoSuggestControl*/) {
    var aSuggestions = [];
    var sTextbox = oAutoSuggestControl.textbox.value;
    var sTextboxSplit = sTextbox.split(/[\s,]+/);
    var sTextboxLast = sTextboxSplit[sTextboxSplit.length-1];
    var sTextboxValue = sTextboxLast;
    if (sTextboxValue.length > 0){
        //search for matching words
        for (var i=0; i < this.words.length; i++) {
            if (this.words[i].indexOf(sTextboxValue) == 0) {
                if (this.words[i].indexOf(sTextboxValue) == 0){
                    aSuggestions.push(this.words[i]);
                }
                else if (this.words[i].indexOf(sTextboxValue.charAt(0) + sTextboxValue.slice(1)) == 0) {
                    aSuggestions.push(this.words[i].charAt(0) + this.words[i].slice(1));
                }
            }
        }
    }

    //provide suggestions to the control
    oAutoSuggestControl.autosuggest(aSuggestions);
};
/**
 * Provides suggestions for each word.
 * @class
 * @scope public
 */
function wordSuggestions() {
    this.words = ['{InputFile}', '{LastOutput}', '{Job}', '{ThreadN}', '{Output:', '{LastOutput:', '{Uploaded:', '{Suffix:', '{Workspace}', '{History:'];
}
