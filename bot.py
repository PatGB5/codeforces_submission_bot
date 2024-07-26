import requests
import json
import time
import logging
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
import hashlib
import asyncio
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
API_KEY = os.environ['CF_API_KEY']
API_SECRET = os.environ['CF_API_SECRET']

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionary to store user sessions
user_sessions = {}

def generate_api_sig(method_name, params, secret):
    rand = 'abcdef'
    sorted_params = '&'.join([f'{k}={v}' for k, v in sorted(params.items())])
    string_to_hash = f'{rand}/{method_name}?{sorted_params}#{secret}'
    sha512_hash = hashlib.sha512(string_to_hash.encode()).hexdigest()
    return f'{rand}{sha512_hash}'

def get_cf_data(handle, count='10'):
    method_name = 'user.status'
    params = {
        'apiKey': API_KEY,
        'handle': handle,
        'time': str(int(time.time())),
        'count': count
    }
    apiSig = generate_api_sig(method_name, params, API_SECRET)
    url = f"https://codeforces.com/api/{method_name}?{'&'.join([f'{k}={v}' for k, v in params.items()])}&apiSig={apiSig}"
    response = requests.get(url)
    data = response.json()
    return data if data.get('result') else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text("Welcome! Please enter your Codeforces handle.")
    user_sessions[user_id] = {'state': 'waiting_for_handle'}
    
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
        await update.message.reply_text("Monitoring stopped. Use /start to begin again.")
    else:
        await update.message.reply_text("You're not currently monitoring any submissions.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message_text = update.message.text

    if user_id not in user_sessions:
        await update.message.reply_text("Please start the bot with /start command.")
        return

    state = user_sessions[user_id]['state']

    if state == 'waiting_for_handle':
        user_sessions[user_id]['handle'] = message_text
        user_sessions[user_id]['state'] = 'waiting_for_sheet_id'
        await update.message.reply_text("First give this email:\nparth-testing-account@cf-submission-bot.iam.gserviceaccount.com\n access as editor to your google sheet document.\nEnter the your google sheet id(which is present in the url bteeween d/ and /edit).")
    
    elif state == 'waiting_for_sheet_id':
        user_sessions[user_id]['sheet_id'] = message_text
        user_sessions[user_id]['state'] = 'initializing'
        await update.message.reply_text("Setup complete! Initializing submission tracking...")
        asyncio.create_task(initialize_submission_tracking(update, context))
    
    else:
        await update.message.reply_text("I'm already monitoring submissions. Use /stop to stop monitoring.")

async def initialize_submission_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    handle = user_sessions[user_id]['handle']
    
    # Get the most recent submission
    response = get_cf_data(handle, count='1')
    if response and response['status'] == 'OK' and response['result']:
        initial_submission_id = response['result'][0]['id']
        user_sessions[user_id]['initial_submission_id'] = initial_submission_id
        user_sessions[user_id]['state'] = 'ready'
        await update.message.reply_text("Initialization complete. Now monitoring for new submissions.")
        asyncio.create_task(monitor_submissions(update, context))
    else:
        await update.message.reply_text("Failed to initialize. Please try /start again.")
        del user_sessions[user_id]

async def monitor_submissions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    handle = user_sessions[user_id]['handle']
    sheet_id = user_sessions[user_id]['sheet_id']
    last_submission_id = user_sessions[user_id]['initial_submission_id']

    while user_id in user_sessions and user_sessions[user_id]['state'] == 'ready':
        new_submissions = await check_for_new_submissions(handle, last_submission_id)
        if new_submissions:
            last_submission_id = new_submissions[0]['id']
            messages = send_new_submission(new_submissions, handle)
            for message in messages:
                await update.message.reply_text(message)
            append_to_google_sheet(new_submissions, handle, sheet_id)
        await asyncio.sleep(10)

async def check_for_new_submissions(handle, last_submission_id):
    response = get_cf_data(handle)
    if response and response['status'] == 'OK':
        submissions = response['result']
        new_submissions = []
        for submission in submissions:
            if submission['id'] == last_submission_id:
                break
            new_submissions.append(submission)
        return list(reversed(new_submissions))  # Reverse to get chronological order
    return None

def send_new_submission(submissions, handle):
    messages = []
    for submission in submissions:
        verdict = submission['verdict']
        problem = submission['problem']
        problem_name = problem['name']
        problem_rating = problem.get('rating', 'Not Available')
        problem_tags = problem['tags']
        message = f"New submission by {handle}\nProblem: {problem_name}\nRated: {problem_rating}\nTags: {problem_tags}\nVerdict: {verdict}\n"
        messages.append(message)
    return messages

def append_to_google_sheet(submissions, handle, sheet_id):
    # Implementation remains the same as before
    # Make sure to use the sheet_id from the user's session
    service_account_info = {
    "type": os.environ["GOOGLE_TYPE"],
    "project_id": os.environ["GOOGLE_PROJECT_ID"],
    "private_key_id": os.environ["GOOGLE_PRIVATE_KEY_ID"],
    "private_key": os.environ["GOOGLE_PRIVATE_KEY"].replace('\\n', '\n'),
    "client_email": os.environ["GOOGLE_CLIENT_EMAIL"],
    "client_id": os.environ["GOOGLE_CLIENT_ID"],
    "auth_uri": os.environ["GOOGLE_AUTH_URI"],
    "token_uri": os.environ["GOOGLE_TOKEN_URI"],
    "auth_provider_x509_cert_url": os.environ["GOOGLE_AUTH_PROVIDER_X509_CERT_URL"],
    "client_x509_cert_url": os.environ["GOOGLE_CLIENT_X509_CERT_URL"],
    "universe_domain": os.environ["GOOGLE_UNIVERSE_DOMAIN"]
    }

    creds = Credentials.from_service_account_info(service_account_info)
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    # Read existing data from the sheet
    result = sheet.values().get(spreadsheetId=sheet_id, range='Sheet1!A2:F').execute()
    existing_values = result.get('values', [])

    # Prepare new submission data
    new_values = []
    for submission in submissions:
        verdict = submission['verdict']
        problem = submission['problem']
        problem_name = problem['name']
        problem_rating = problem.get('rating', 'Not Available')
        problem_tags = ", ".join(problem['tags'])
        row = [handle, problem_name, problem_rating, problem_tags, verdict, time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(submission['creationTimeSeconds']))]
        new_values.append(row)

    # Filter out rows with the same problem name and verdict other than "OK"
    problem_names = {row[1] for row in new_values}
    filtered_values = [row for row in existing_values if row[1] not in problem_names or row[4] == 'OK' and verdict != 'OK']

    # Combine filtered existing data with new data
    combined_values = filtered_values + new_values

    # Clear the existing data
    sheet.values().clear(spreadsheetId=sheet_id, range='Sheet1!A2:F').execute()

    # Append combined data
    body = {'values': combined_values}
    result = sheet.values().append(
        spreadsheetId=sheet_id,
        range='Sheet1!A2',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()
    print('{0} cells appended.'.format(result.get('updates').get('updatedCells')))
    pass

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()