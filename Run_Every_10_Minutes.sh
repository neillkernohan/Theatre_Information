#!/bin/bash

while true; do
    current_minute=$(date +%M)
    if [ $((10#$current_minute % 10)) -eq 0 ]; then
        /Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python\ Scripts/Theatre_Info/Load_Ticket_Data.sh
        sleep 600  # Sleep for 10 minutes
    else
        sleep 30  # Sleep for a shorter period and check again
    fi
done
