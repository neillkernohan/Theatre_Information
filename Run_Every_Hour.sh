#!/bin/bash

while true; do
    current_minute=$(date +%M)
    # current_second=$(date +%S)
    
    # Convert to decimal to avoid issues with leading zeros
    current_minute=$((10#$current_minute))
    # current_second=$((10#$current_second))
    
    if [[ "$current_minute" -eq 0 ]]; then
        "/Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python Scripts/Theatre_Info/Load_Ticket_Data.sh"
        # Sleep a couple of minutes
        sleep 300
    fi
done
