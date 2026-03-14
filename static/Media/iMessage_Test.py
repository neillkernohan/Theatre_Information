import subprocess

def get_last_message_applescript():
    # AppleScript to get the text of the last message in the first chat.
    # Depending on your setup, you may need to iterate over chats or filter by participant.
    script = r'''
    tell application "Messages"
        -- This gets the first chat in your sidebar; you may need to adjust 
        -- which 'chat' you want, or loop through 'chats'.
        set theLastChat to item 1 of (get chats)
        set theMessage to the text of the last message of theLastChat
        return theMessage
    end tell
    '''
    
    # Run the AppleScript via osascript
    output = subprocess.check_output(["osascript", "-e", script], text=True).strip()
    return output

if __name__ == "__main__":
    try:
        last_message = get_last_message_applescript()
        print("Last message:", last_message)
    except subprocess.CalledProcessError as e:
        print("Error reading last message:", e)
