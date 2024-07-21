import requests
import json
import time
import logging
from telegram import Bot
import os
import schedule
import hashlib
import asyncio
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

# TOKEN = os.getenv('TELEGRAM_BOT_TOKEN ')
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
API_KEY = os.environ['CF_API_KEY']
API_SECRET = os.environ['CF_API_SECRET']
SHEET_ID = None

bot = Bot(token=TOKEN)

HANDLE = None

#Function to take handle from user using the telegram bot
async def take_handle():
    # Fetch the latest update to get the current highest update_id
    updates = await bot.get_updates()
    last_update_id = updates[-1].update_id if updates else 0

    # Send the message to the user asking for the handle
    await bot.send_message(chat_id=CHAT_ID, text="Enter the codeforces handle for which you want to get the recent submissions")

    # Continuously check for a new message with a higher update_id
    while True:
        updates = await bot.get_updates(offset=last_update_id + 1)  # Fetch only new updates
        if updates:
            handle = updates[-1].message.text
            return handle
        await asyncio.sleep(1)  # Wait a bit before checking for updates again to avoid spamming the API

#Function to take handle from user using the sheet_id
async def take_sheet_id():
    # Fetch the latest update to get the current highest update_id
    updates = await bot.get_updates()
    last_update_id = updates[-1].update_id if updates else 0

    # Send the message to the user asking for the handle
    await bot.send_message(chat_id=CHAT_ID, text="First give this email:\nparth-testing-account@cf-submission-bot.iam.gserviceaccount.com\n access as editor to your google sheet document.\nEnter the your google sheet id(which is present in the url bteeween d/ and /edit)")

    # Continuously check for a new message with a higher update_id
    while True:
        updates = await bot.get_updates(offset=last_update_id + 1)  # Fetch only new updates
        if updates:
            sheet_id = updates[-1].message.text
            return sheet_id
        await asyncio.sleep(1)  # Wait a bit before checking for updates again to avoid spamming the API


#Function to generate the api signature
def generate_api_sig(method_name, params, secret):
    rand = 'abcdef'  # This can be any random 6 characters
    sorted_params = '&'.join([f'{k}={v}' for k, v in sorted(params.items())])
    string_to_hash = f'{rand}/{method_name}?{sorted_params}#{secret}'
    sha512_hash = hashlib.sha512(string_to_hash.encode()).hexdigest()
    return f'{rand}{sha512_hash}'

#Function to get the recent submissions
def get_cf_data(handle):
    method_name = 'user.status'
    params = {
        'apiKey': API_KEY,
        'handle' : handle ,
        'time': str(int(time.time())),
        'count': '5'
    }
    apiSig = generate_api_sig(method_name, params, API_SECRET)
    url = f"https://codeforces.com/api/{method_name}?{'&'.join([f'{k}={v}' for k, v in params.items()])}&apiSig={apiSig}"
    print("url ==",url)
    response = requests.get(url)
    data = response.json()
    # print("Hello bhau")
    if data.get('result'):
        return data
    else:
        return None
    
    
def get_cf_data2(handle):
    method_name = 'user.status'
    params = {
        'apiKey': API_KEY,
        'handle' : handle ,
        'time': str(int(time.time())),
        'count': '1'
    }
    apiSig = generate_api_sig(method_name, params, API_SECRET)
    url = f"https://codeforces.com/api/{method_name}?{'&'.join([f'{k}={v}' for k, v in params.items()])}&apiSig={apiSig}"
    print("url ==",url)
    response = requests.get(url)
    data = response.json()
    # print(str(data))
    if data.get('result'):
        return data
    else:
        return None
# Store the initial submission id
initial_submission_id = None


async def check_for_new_submissions(a):
    global initial_submission_id
    if(a==0):
        response = get_cf_data2(HANDLE)
    else:
        response = get_cf_data(HANDLE)
    
    if response is None or response['status'] != 'OK':
        logging.error("No new submissions found or an error occurred.")
        return None
    new_submission = response['result']  # Access the list of submissions
    needed_submission = []
    new_submission_id = None
    flag = 0
    for submission in new_submission:
        print("Submission_id ==  ,initial_submission_id = ",submission['id'] , initial_submission_id)
        if submission['id'] == initial_submission_id :  # Check if the submission is the same as the last one
            break
        else:
            if(flag == 0):
                new_submission_id = submission['id']
                flag = 1
            needed_submission.append(submission)
    if(new_submission_id == None):
            return None
    initial_submission_id = new_submission_id
    return needed_submission  # Return a list containing the new submission
    


# Function to send the new submission to the telegram chat
def send_new_submission(new_submission):
    messages = []
    if new_submission:
        for submission in new_submission:
            verdict = submission['verdict']
            problem = submission['problem']
            problem_name = problem['name']
            problem_rating = problem.get('rating', 'Not Available')
            problem_tags = problem['tags']
            message = f"New submission by {HANDLE} \nON Problem: [{problem_name}] \nRated : [{problem_rating}]  \nWith Tags : [{problem_tags}] \nwith verdict: {verdict}\n\n"
            messages.append(message)  
        return messages

def append_to_google_sheet(submissions):
    creds = Credentials.from_service_account_file('/home/parthtokekar/Desktop/dada_help/codeforces_track_submissions/telegram-bot/cf_submission_bot.json')
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    # Read existing data from the sheet
    result = sheet.values().get(spreadsheetId=SHEET_ID, range='Sheet1!A2:F').execute()
    existing_values = result.get('values', [])

    # Prepare new submission data
    new_values = []
    for submission in submissions:
        verdict = submission['verdict']
        problem = submission['problem']
        problem_name = problem['name']
        problem_rating = problem.get('rating', 'Not Available')
        problem_tags = ", ".join(problem['tags'])
        row = [HANDLE, problem_name, problem_rating, problem_tags, verdict, time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(submission['creationTimeSeconds']))]
        new_values.append(row)

    # Filter out rows with the same problem name and verdict other than "OK"
    problem_names = {row[1] for row in new_values}
    filtered_values = [row for row in existing_values if row[1] not in problem_names or row[4] == 'OK']

    # Combine filtered existing data with new data
    combined_values = filtered_values + new_values

    # Clear the existing data
    sheet.values().clear(spreadsheetId=SHEET_ID, range='Sheet1!A2:F').execute()

    # Append combined data
    body = {'values': combined_values}
    result = sheet.values().append(
        spreadsheetId=SHEET_ID,
        range='Sheet1!A2',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()
    print('{0} cells appended.'.format(result.get('updates').get('updatedCells')))


async def main():
    global HANDLE
    try:
        # Wait for up to 60 seconds for a handle to be provided
        HANDLE = await asyncio.wait_for(take_handle(), timeout=120)
    except asyncio.TimeoutError:
        print("No handle provided within 2 minute. Exiting...")
        return  # Exit the function, which ends the program
    
    
    global SHEET_ID
    try:
        # Wait for up to 60 seconds for a handle to be provided
        SHEET_ID = await asyncio.wait_for(take_sheet_id(), timeout=600)
    except asyncio.TimeoutError:
        print("No handle provided within 10 minute. Exiting...")
        return  # Exit the function, which ends the program
    
    
    a = 0
    while True:
        new_submission = await check_for_new_submissions(a)
        a = 1
       # print("New Submission == ", new_submission)
        if new_submission is not None:
            messages = (send_new_submission(new_submission))
            for message in messages:
                await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML')
            append_to_google_sheet(new_submission)
        else:
            print("No new submission to send.")
        await asyncio.sleep(10)  # Wait for 10 seconds before checking again

if __name__ == '__main__':
    asyncio.run(main())






