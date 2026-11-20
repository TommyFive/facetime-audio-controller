-- FaceTime Audio UI controls through NotificationCenter AX on macOS 27.2.
-- All controls fail closed for unknown targets or multiple possible actions.
-- One target is fixed at build time.
on run argv
  if (count of argv) is not 1 then error "Usage: facetime-ax-control.applescript status|confirm|hangup|cancel-pending|dismiss-unavailable"
  set operationName to item 1 of argv as text
  if operationName is not in {"status", "confirm", "hangup", "cancel-pending", "dismiss-unavailable"} then error "Invalid action"
  set wantedAddress to system attribute "FACETIME_RECIPIENT"
  if wantedAddress is "" then error "RECIPIENT_NOT_CONFIGURED"
  set results to {}
  set pendingActions to {}
  set cancelActions to {}
  set endActions to {}
  set unavailableActions to {}
  tell application "System Events"
    if not (exists process "NotificationCenter") then
      if operationName is "status" then return "STATE=UNKNOWN reason=NotificationCenter-not-running"
      error "NO_NOTIFICATION_CENTER: no control action taken"
    end if
    tell process "NotificationCenter"
      -- Snapshot the current window list. NotificationCenter creates/destroys
      -- windows during FaceTime transitions, which can invalidate AX indexes.
      set uiWindows to windows
      repeat with win in uiWindows
        try
        set targetCount to 0
        set hintCount to 0
        set nCall to 0
        set nCancel to 0
        set nEnd to 0
        set nUnavailable to 0
        set callBtns to {}
        set cancelBtns to {}
        set endBtns to {}
        set titleLine to ""
        -- IMPORTANT: materialize the AX element list first. Direct 'repeat with'
        -- over an unevaluated 'entire contents' specifier silently misses controls.
        set elementsFound to entire contents of win
        set transientElementError to false
        repeat with elem in elementsFound
          set rr to ""
          set dd to ""
          try
            set rr to role of elem
          on error errMsg number errCode
            if errCode is -1719 or errCode is -1728 then set transientElementError to true
          end try
          try
            set dd to description of elem
          on error errMsg number errCode
            if errCode is -1719 or errCode is -1728 then set transientElementError to true
          end try
          if dd is missing value then set dd to ""
          if rr is "AXStaticText" then
            if dd contains wantedAddress and ((length of dd) is less than or equal to ((length of wantedAddress) + 4)) then
              set targetCount to targetCount + 1
            end if
            if dd is "Zum Anrufen klicken" then set hintCount to hintCount + 1
            if dd is "ist nicht verfügbar" then set nUnavailable to nUnavailable + 1
            if dd starts with "FaceTime-Audio" then set titleLine to dd
          else if rr is "AXButton" then
            if dd is "Anruf" then
              set nCall to nCall + 1
              set end of callBtns to contents of elem
            end if
            if dd is "Abbrechen" then
              set nCancel to nCancel + 1
              set end of cancelBtns to contents of elem
            end if
            if dd is "Beenden" then
              set nEnd to nEnd + 1
              set end of endBtns to contents of elem
            end if
          end if
        end repeat
        if transientElementError then error "TRANSIENT_UI: AX elements changed during scan" number -1719
        if targetCount > 0 then
          set detectedState to "UNRECOGNIZED"
          if targetCount is hintCount and targetCount is nCall and targetCount is nCancel and nEnd is 0 then
            if targetCount is 1 then
              set detectedState to "PENDING_CONFIRMATION"
            else
              set detectedState to "MULTIPLE_PENDING count=" & targetCount
            end if
          else if targetCount is 1 and nUnavailable is 1 and hintCount is 0 and nCall is 1 and nCancel is 1 and nEnd is 0 then
            set detectedState to "UNAVAILABLE"
          else if targetCount is 1 and nEnd is 1 and nCall is 0 and titleLine starts with "FaceTime-Audio" then
            if titleLine contains ":" and titleLine contains "–" then
              set detectedState to "CONNECTED"
            else
              set detectedState to "DIALING_OR_RINGING"
            end if
          end if
          set end of results to detectedState & " target=" & wantedAddress & " label=" & titleLine
          if detectedState is "PENDING_CONFIRMATION" then set end of pendingActions to item 1 of callBtns
          if detectedState is "UNAVAILABLE" then set end of unavailableActions to item 1 of cancelBtns
          if detectedState is "CONNECTED" or detectedState is "DIALING_OR_RINGING" then set end of endActions to item 1 of endBtns
          if targetCount is hintCount and targetCount is nCall and targetCount is nCancel and nEnd is 0 then
            if (count of cancelBtns) > 0 then set end of cancelActions to item 1 of cancelBtns
          end if
        end if
        on error errMsg number errCode
          if errCode is -1719 or errCode is -1728 then
            if operationName is "status" then return "STATE=TRANSIENT_UI reason=window-index-change"
            error "TRANSIENT_UI: window index changed; no action taken"
          end if
          error errMsg number errCode
        end try
      end repeat
      if (count of results) is 0 then
        if operationName is "status" then return "STATE=NO_CALL_UI target=" & wantedAddress & " (not proof that no call exists)"
        error "NO_MATCHING_CALL_CARD: no action taken"
      end if
      if operationName is "status" then
        if (count of results) is not 1 then return "STATE=AMBIGUOUS target=" & wantedAddress & " windows=" & (count of results)
        return "STATE=" & (item 1 of results)
      end if
      if operationName is "confirm" then
        if (count of results) is not 1 or (count of pendingActions) is not 1 then
          error "NOT_ONE_PENDING_CARD: " & (item 1 of results) & " (no action taken)"
        end if
        click (item 1 of pendingActions)
        return "CONFIRM_CLICK_SENT target=" & wantedAddress & " (call not yet connected)"
      end if
      if operationName is "hangup" then
        if (count of results) is not 1 or (count of endActions) is not 1 then
          error "NOT_ONE_ACTIVE_CALL: " & (item 1 of results) & " (no action taken)"
        end if
        click (item 1 of endActions)
        return "HANGUP_CLICK_SENT target=" & wantedAddress & " (disconnect not yet verified)"
      end if
      if operationName is "dismiss-unavailable" then
        if (count of results) is not 1 or (count of unavailableActions) is not 1 then
          error "NOT_ONE_UNAVAILABLE_CARD: no action taken"
        end if
        click (item 1 of unavailableActions)
        return "UNAVAILABLE_DISMISS_CLICK_SENT target=" & wantedAddress & " (verify clear state separately)"
      end if
      if operationName is "cancel-pending" then
        if (count of results) is not 1 or (count of cancelActions) is not 1 then
          error "NOT_VALID_PENDING_CARDS: no action taken"
        end if
        -- Each pending card in this window has exactly one matching fixed target;
        -- click one 'Abbrechen' and require reinspection for remaining cards.
        click (item 1 of cancelActions)
        return "PENDING_CANCEL_CLICK_SENT target=" & wantedAddress & " (one prompt)"
      end if
    end tell
  end tell
end run
