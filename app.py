from flask import Flask, request, jsonify, session, redirect, url_for, render_template
import mysql.connector
from datetime import datetime, timedelta, timezone, time as dt_time, date
from dateutil import tz
import re
from zoneinfo import ZoneInfo
import os
import os.path
import csv
import time
from decimal import Decimal
import json
from dotenv import load_dotenv

import random

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

used_colors = set()

def select_season():
    # Today's date
    today = date.today()
    
    # Define the start of each season
    seasons = [
        {"start": date(2025, 7, 1), "label": "2025-07-01"},
        {"start": date(2024, 7, 1), "label": "2024-07-01"},
        {"start": date(2023, 7, 1), "label": "2023-07-01"}
    ]
    
    # Check which season today's date falls into
    for season in seasons:
        season_end = date(season["start"].year + 1, 6, 30)  # June 30th of the next year
        if season["start"] <= today <= season_end:
            return season["label"]
    
    return "Current date does not fall within the defined seasons."

def dynamic_colors():
    while True:  # Keep trying until we find a new color
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        color = f"rgb({r},{g},{b})"
        
        if color not in used_colors:
            used_colors.add(color)
            return color

default_timezone = ZoneInfo("America/New_York")

# Regex pattern for ISO 8601 datetime format with timezone
datetime_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-\d{2}:\d{2}$"
# Regex pattern for ISO 8601 date format
date_pattern = r"^\d{4}-\d{2}-\d{2}$"


def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        # Handles datetime with timezone
        return datetime.strptime(date_str[:10], "%Y-%m-%d")

def combine_events(events):
    combined_events = []
    i = 0
    while i < len(events):
        current_event = events[i]
        if current_event['title'] == 'Booked All Day':
            # Try to combine with following events
            j = i + 1
            while j < len(events):
                next_event = events[j]
                if next_event['title'] == 'Booked All Day' and current_event['end']  == next_event['start']:
                    # Extend the current event's end date to the next event's end date
                    current_event['end'] = next_event['end']
                    j += 1
                else:
                    break
            i = j
        else:
            i += 1
        combined_events.append(current_event)
    return combined_events

def check_string_format(s):
    if re.match(datetime_pattern, s):
        return "datetime with timezone"
    elif re.match(date_pattern, s):
        return "date only"
    else:
        return "unknown format"
    
def parse_date_with_timezone(date_str):
    """Parse a date string and return a timezone-aware datetime object."""
    # Assuming date_str is in ISO 8601 format; adjust parsing as needed
    return datetime.fromisoformat(date_str).replace(tzinfo=default_timezone)

def parse_date_utc(date_time):
    return date_time.replace(tzinfo=timezone.utc).isoformat()
    
def categorize_event_time(start_str, end_str):
    # Parse the ISO 8601 formatted strings into datetime objects
    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)

    # Define the category time ranges
    morning_start, morning_end = start_dt.replace(hour=9, minute=0), start_dt.replace(hour=12, minute=0)
    afternoon_start, afternoon_end = start_dt.replace(hour=13, minute=0), start_dt.replace(hour=17, minute=0)
    evening_start, evening_end = start_dt.replace(hour=18, minute=0), start_dt.replace(hour=22, minute=0)

    categories = set()

    # Check if the event spans morning, afternoon, or evening
    if start_dt < morning_end and end_dt > morning_start:
        categories.add("morning")
    if start_dt < afternoon_end and end_dt > afternoon_start:
        categories.add("afternoon")
    if start_dt < evening_end and end_dt > evening_start:
        categories.add("evening")

    # Determine if the event spans multiple categories
    if len(categories) > 1:
        return "spans " + ", ".join(categories)
    elif len(categories) == 1:
        return categories.pop()
    else:
        return "does not fall into the defined categories"
    
def get_fiscal_year_start(input_date):
    # Check if the month is before July (the start of the fiscal year)
    if input_date.month < 7:
        # If before July, the fiscal year would have started on July 1 of the previous year
        return date(input_date.year - 1, 7, 1)
    else:
        # Otherwise, it starts on July 1 of the current year
        return date(input_date.year, 7, 1)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", 'cW3(sP1;tJ4#mX2<sL6!uB1&zR0~gX4%')  # Needed for session management

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/SeasonTotals')
def SeasonTotals():
    Theatre_Information_DB = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )

    data = Theatre_Information_DB.cursor()

    data.callproc('Get_Seasons')
    for result in data.stored_results():
        seasons = result.fetchall()

    this_season = request.args.get('this_season', type=str)
    if request.args.get('showsOnly', 'false') == 'true':
        shows_only = 1
    else:
        shows_only = 0

    if this_season == None:
        this_season=select_season()

    current_season_date = datetime.strptime(this_season, '%Y-%m-%d').date()
    last_season_date = datetime(year=current_season_date.year - 1, month=current_season_date.month, day=current_season_date.day).date()
    last_season = last_season_date.strftime('%Y-%m-%d')

    Updates_Cursor = Theatre_Information_DB.cursor()
    Updates_Cursor.execute("SELECT Update_date_time FROM Theatre_Information.Updates order by Update_date_time desc limit 1;")
    update_data=Updates_Cursor.fetchall()
    last_update = update_data[0][0] if update_data else 'Not available'
    formatted_update = last_update.strftime('%B %-d, %Y at %-I:%M %p')
    print(this_season)
    data.callproc('GetTicketTotals', (this_season, shows_only))
    for result in data.stored_results():
        ticket_data = result.fetchall()

    data.callproc('GetSeasonTotals', (this_season, shows_only))
    for result in data.stored_results():
        season_data = result.fetchall()

    data.callproc('GetSeasonTotals', (last_season, shows_only))
    for result in data.stored_results():
        last_season_data = result.fetchall()

    data.callproc('GetSeasonExpenses', (this_season, shows_only))
    for result in data.stored_results():
        this_season_expenses = result.fetchall()

    data.callproc('GetSeasonExpenses', (last_season, shows_only))
    for result in data.stored_results():
        last_season_expenses = result.fetchall()
    print(last_season)

    data.callproc('GetSubscriptions2', (this_season,))
    for result in data.stored_results():
        this_season_subscriptions = result.fetchall()

    data.callproc('GetSubscriptions2', (last_season,))
    for result in data.stored_results():
        last_season_subscriptions = result.fetchall()        
    
    data.callproc('GetTicketSalesPast14Days')
    for result in data.stored_results():
        past14days = result.fetchall()

    return render_template('SeasonTotals.html', 
        formatted_update=formatted_update,
        this_season=this_season,
        seasons=seasons, 
        ticket_data=ticket_data,
        season_data=season_data,
        last_season_data=last_season_data, 
        this_season_expenses=this_season_expenses,
        last_season_expenses=last_season_expenses,
        this_season_subscriptions=this_season_subscriptions,
        last_season_subscriptions=last_season_subscriptions,
        shows_only=shows_only,
        past14days=past14days)

@app.route('/TotalSales')
def TotalSales():
    Ticket_Data_DB = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )

    data = Ticket_Data_DB.cursor()

    data.callproc('GetTicketTotals', ('2023-07-01',0))
    for result in data.stored_results():
        ticket_data = result.fetchall()

    data.callproc('GetSeasonTotals', ('2023-07-01',0))
    for result in data.stored_results():
        season_data = result.fetchall()

    data.callproc('GetSeasonTotals', ('2022-07-01',0))
    for result in data.stored_results():
        last_season_data = result.fetchall()
    
    data.callproc('GetCommentsSeasonCount', ('2023-07-01',))
    for result in data.stored_results():
        comments_season_count = result.fetchall()

    data.callproc('GetDayAverages')
    for result in data.stored_results():
        dayaverages = result.fetchall()

    Subscription_Cursor = Ticket_Data_DB.cursor()
    Subscription_Cursor.callproc('GetSubscriptions', ('2023-07-01',))
    for result in Subscription_Cursor.stored_results():
        subscription_data = result.fetchall()

    Updates_Cursor = Ticket_Data_DB.cursor()
    Updates_Cursor.execute("SELECT Update_date_time FROM Theatre_Information.Updates order by Update_date_time desc limit 1;")
    update_data=Updates_Cursor.fetchall()
    last_update = update_data[0][0] if update_data else 'Not available'
    # Your code to fetch last_update from the database...

    # Parse and format the datetime
    
    # last_update is assumed to be a datetime.datetime object
    formatted_update = last_update.strftime('%B %-d, %Y at %-I:%M %p')

    # Then render the template with formatted_update

    return render_template('TotalSales.html', data=ticket_data, season_data=season_data, last_season_data=last_season_data, subscription_data = subscription_data, formatted_update=formatted_update, comments_season_count=comments_season_count, dayaverages=dayaverages)

@app.route('/ShowDetail')
def GetShowDetail():
    show_name = request.args.get('show_name', default="Anne of Green Gables - The Musical", type=str)  # Getting show_name from the query parameters

    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )

    total_start_time = time.time()
    cursor = db.cursor()
    
    # safe_show_name = show_name.replace("'", "''")
    show_name = show_name.replace("'", "\'")  # Escape single quotes for SQL
    cursor.callproc('GetCombinedData',[show_name,])
    """     
    found_results = False

    for i, result in enumerate(cursor.stored_results()):
        data = result.fetchall()
        if data:
            found_results = True
            print(f"Result set {i}:")
            for row in data:
                print(row)
        else:
            print(f"Result set {i} returned no data.") 


    if not found_results:
        print("No data returned at all.")
    """
    for i, result in enumerate(cursor.stored_results()):
        if i == 0: #GetShowTickets
            tickets = result.fetchall()
        elif i == 1: #GetShowTotalTickets
            totaltickets = result.fetchall()
        elif i == 2: #GetShowPerformanceCount
            showperformancecount = result.fetchall()
        elif i == 3: #GetShowRevenue
            revenue = result.fetchall()
        elif i == 4: #GetShowTotalRevenue
            totalrevenue = result.fetchall()
        elif i == 5: #GetShowType
            showtype = result.fetchall()
        elif i == 6: #GetAverageTicketsRevenueBeforeOpening
            averageticketsrevenueopening = result.fetchall()
        elif i == 7: #GetAverageTicketsRevenueBeforeClosing
            averageticketsrevenueclosing = result.fetchall()
        elif i == 8: #GetTopShow
            topshow = result.fetchall()
        elif i == 9: #GetShowRank
            showrank = result.fetchall()
        elif i == 10: #GetOpeningClosingDates
            openingclosingdates = result.fetchall()
        elif i == 11: #GetAverageTicketsRevenueFinal
            getaverageticketsrevenuefinal = result.fetchall()
        elif i == 12: #GetRankedShowListbyTickets
            rankedshowlistbytickets = result.fetchall()
        elif i == 13: #GetRankedShowListbyProfit
            rankedshowlistbyprofit = result.fetchall()
        elif i == 14: #Last_Two_Weeks_Tickets
            lasttwoweekstickets = result.fetchall()
        elif i == 15: #GetCityCount
            citycount = result.fetchall()
        elif i == 16: #GetCityforSeason
            citycountforseason = result.fetchall()
        elif i == 17: #GetCityCountForLastSeason
            citycountforlastseason = result.fetchall()
        elif i == 18: #GetPersonTypesbyShow
            persontypes = result.fetchall()
        elif i == 19: #GetBuyerInfo
            buyerinfo = result.fetchall()
        elif i == 20: #GetCommentsCount
            commentscount = result.fetchall()
        elif i == 21: #AverageTicketsSold
            averageticketssold = result.fetchall()
        elif i == 22: #AverageTicketsPerDay
            averageticketsperday = result.fetchall()
        elif i == 23: #GetCommentsLastFiveDays2
            getcommentslastfivedays=result.fetchall()
            getcommentslastfivedays_column_headings = [column[0] for column in result.description]
        elif i == 24: #GetPreviousShowDataBeforeOpening2
            previousshowdatabeforeopening = result.fetchall()
        elif i == 25: #GetTicketSalesOverTimeOneShow
            ticketsalesovertimeoneshow = result.fetchall()
        elif i == 26: #GetOtherShowsInSeason
            othershowsinseason = result.fetchall()
        
    cursor.execute("SELECT Update_date_time FROM Theatre_Information.Updates order by Update_date_time desc limit 1;")
    update_data=cursor.fetchall()
    last_update = update_data[0][0] if update_data else 'Not available'
            
    formatted_update = last_update.strftime('%B %-d, %Y at %-I:%M %p')

    ticketsalesovertimedatasets = []
    cursor.callproc('GetOtherShowsinSeason',[show_name,])
    for result in cursor.stored_results():
        Other_Shows = result.fetchall()
    for Show in Other_Shows:
        cursor.callproc('GetTicketSalesOverTimeOtherShow',[show_name, Show[0]])
        for result in cursor.stored_results():
            data = result.fetchall()
            data_just_numbers = []
            for item in data:
                data_just_numbers.append(float(item[1]))
            ticketsalesovertimedatasets.append({
                "label": Show[0],
                "data": data_just_numbers,
                "fill": False,
                "borderColor": dynamic_colors(),
                "tension": "0.1"
            })

    data_list = []
    cursor.callproc('GetShowsinSeason',['2023-07-01',])
    for result in cursor.stored_results():
        Other_Shows = result.fetchall()
    for Show in Other_Shows:
        cursor.callproc('GetTicketSalesOverTimeOtherShow',[show_name, Show[0]])
        for result in cursor.stored_results():
            data = result.fetchall()
            if len(data_list) > 0:
                for i in range(len(data)):
                    data_list[i].append(float(data[i][1]))
            else:
                for date, value in data:
                    data_list.append([float(value),])
    lastseasonsaverages = []
    for values in data_list:
        total = 0
        counter = 0
        for value in values:
            total = total + value
            counter = counter + 1
        lastseasonsaverages.append(total/counter)
    ticketsalesovertimedatasets.append({
            "label": "Last season\'s average for the same time frame",
            "data": lastseasonsaverages,
            "fill": False,
            "borderColor": 'rgb(75,192,192)',
            "tension": "0.1"
        })
        
    # Get the current datetime
    now = datetime.now()

    # Create datetime objects for the specific times of the openingclosingdates
    print(openingclosingdates)
    eight_pm_opening_date = datetime.combine(openingclosingdates[0][0].date(), dt_time(19, 30))  # Opening date at 8 PM
    eight_thirty_closing_date = datetime.combine(openingclosingdates[0][1].date(), dt_time(20, 30))  # Closing date at 8:30 PM

    # Compare the current time with the specified times
    if now < eight_pm_opening_date:
        message1 = (
            "Other shows of the type '" + showtype[0][0] + "' have sold an average of " + 
            str(round(averageticketsrevenueopening[0][0], 0)) + " tickets and have made $" +
            str(round(averageticketsrevenueopening[0][1], 2)) + " by this time before opening. " + 
            "'" + show_name + "' is at " + str(round(totaltickets[0][0]/averageticketsrevenueopening[0][0],1)) + " times average tickets sold and " + str(round(totalrevenue[0][0]/averageticketsrevenueopening[0][1],1)) + " times average revenue right now."
        )

        if previousshowdatabeforeopening[0][0] != 'Special':
            message4 = (
                "The last show of type '" + 
                previousshowdatabeforeopening[0][0] + "', '" + 
                previousshowdatabeforeopening[0][1] + "', had sold " + 
                str(round(previousshowdatabeforeopening[0][2],0)) + " tickets and made $" + 
                str(round(previousshowdatabeforeopening[0][3],2)) + " by this time before opening (" + 
                str(round(previousshowdatabeforeopening[0][4],0)) + " days). '" + 
                show_name + "' is at " + 
                str(round(totaltickets[0][0]/previousshowdatabeforeopening[0][2],1)) + " times tickets sold and " + 
                str(round(totalrevenue[0][0]/previousshowdatabeforeopening[0][3],1)) + " times revenue right now." 
            )
        else:
            message4 = ''

        if show_name == topshow[0][0]:
            message2 = (
                "'" + show_name + "' is the top-rated show for this category."
            )
        else:
            message2 = (
                "'" + show_name + "' is at " + str(round(totaltickets[0][0]/topshow[0][1]*100,1)) + "% of the tickets sales and " + str(round(totalrevenue[0][0]/topshow[0][2]*100,1)) + "% of the revenue of the top-rated show in this category, '" + topshow[0][0] + "'."
            )
    elif eight_pm_opening_date <= now < eight_thirty_closing_date:
        message1 = (
            "This show has now opened. Other shows of the type '" + showtype[0][0] + "' have sold an average of " +
            str(round(averageticketsrevenueclosing[0][0], 0)) + " tickets and have made $" +
            str(round(averageticketsrevenueclosing[0][1], 2)) + " by this time before closing. " +
            "'" + show_name + " is at " + str(round(totaltickets[0][0]/averageticketsrevenueclosing[0][0],1)) + " times average tickets sold and " + str(round(totalrevenue[0][0]/averageticketsrevenueclosing[0][1],1)) + " times average revenue right now."
        )
        if show_name == topshow[0][0]:
            message2 = (
                "'" + show_name + "' is the top-rated show for this category."
            )
        else:
            message2 = (
                "'" + show_name + "' is at " + str(round(totaltickets[0][0]/topshow[0][1]*100,1)) + "% of the tickets sales and " + str(round(totalrevenue[0][0]/topshow[0][2]*100,1)) + "\% of the revenue of the top-rated show in this category, '" + topshow[0][0] + "'."
            )
        message4 = (
            "The last show of type '" + 
            previousshowdatabeforeopening[0][0] + "', '" + 
            previousshowdatabeforeopening[0][1] + "', had sold " + 
            str(round(previousshowdatabeforeopening[0][2],0)) + " tickets and made $" + 
            str(round(previousshowdatabeforeopening[0][3],2)) + " by this time before opening (" + 
            str(round(previousshowdatabeforeopening[0][4],0)) + " days). 'On Golden Pond' is at " + 
            str(round(totaltickets[0][0]/previousshowdatabeforeopening[0][2],1)) + " times tickets sold and " + 
            str(round(totalrevenue[0][0]/previousshowdatabeforeopening[0][3],1)) + " times revenue right now." 
                )
    else:
        message1 = (
            f"This show has now closed. Other shows of the type '{showtype[0][0]}' sold an average of "
            f"{round(getaverageticketsrevenuefinal[0][0], 0)} tickets and made $"
            f"{round(getaverageticketsrevenuefinal[0][1], 2):,.2f}. "
            f"'{show_name}' ended at {round(totaltickets[0][0]/getaverageticketsrevenuefinal[0][0],1)} times average tickets sold and {round(totalrevenue[0][0]/getaverageticketsrevenuefinal[0][1],1)} times average revenue. "
        )
        if show_name == topshow[0][0]:
            message2 = (
                "'" + show_name + "' is the top-rated show for this category."
            )
        else:
            message2 = (
                "'" + show_name + "' is at " + str(round(totaltickets[0][0]/topshow[0][1]*100,1)) + "% of the tickets sales and " + str(round(totalrevenue[0][0]/topshow[0][2]*100,1)) + "\% of the revenue of the top-rated show in this category, '" + topshow[0][0] + "'."
            )
        message4 = (
            "The last show of type '" + 
            previousshowdatabeforeopening[0][0] + "', '" + 
            previousshowdatabeforeopening[0][1] + "', had sold " + 
            str(round(previousshowdatabeforeopening[0][2],0)) + " tickets and made $" + 
            str(round(previousshowdatabeforeopening[0][3],2)) + " by this time before opening (" + 
            str(round(previousshowdatabeforeopening[0][4],0)) + " days). 'On Golden Pond' is at " + 
            str(round(totaltickets[0][0]/previousshowdatabeforeopening[0][2],1)) + " times tickets sold and " + 
            str(round(totalrevenue[0][0]/previousshowdatabeforeopening[0][3],1)) + " times revenue right now." 
                )
    message3 = (
        f"'{show_name}' is ranked at { showrank[0][0] } out of { showrank[0][1] } for the type '{ showtype[0][0] }'."
    )

    return render_template('ShowDetail.html', 
        show_name=show_name,
        tickets=tickets, 
        revenue=revenue, 
        totaltickets=totaltickets, 
        showperformancecount=showperformancecount,
        totalrevenue=totalrevenue,
        showtype=showtype,
        averageticketsrevenue=averageticketsrevenueopening,
        topshow=topshow,
        formatted_update=formatted_update, 
        message1=message1,
        message2=message2,
        message3=message3,
        message4=message4,
        rankedshowlistbytickets=rankedshowlistbytickets,
        rankedshowlistbyprofit=rankedshowlistbyprofit,
        lasttwoweekstickets=lasttwoweekstickets,
        citycount=citycount,
        citycountforseason=citycountforseason,
        citycountforlastseason=citycountforlastseason,
        persontypes=persontypes,
        buyerinfo=buyerinfo,
        commentscount=commentscount,
        averageticketssold=averageticketssold,
        averageticketsperday=averageticketsperday,
        getcommentslastfivedays=getcommentslastfivedays,
        getcommentslastfivedays_column_headings=getcommentslastfivedays_column_headings,
        ticketsalesovertimeoneshow=ticketsalesovertimeoneshow,
        lastseasonsaverages=lastseasonsaverages,
        ticketsalesovertimedatasets=ticketsalesovertimedatasets
    )

@app.route('/Check_Calendar')
def Check_Calendar():

    # Specify the path to your CSV file
    csv_file_path = 'events.csv'  # Make sure to adjust this to your CSV file's actual path

    # Initialize an empty list to store the data
    events = []

    # Open and read the CSV file
    with open(csv_file_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        
        # Iterate over each row in the CSV and add it to the list
        for row in reader:
            # If 'allDay' exists in the row, convert its string representation back to a boolean
            if 'allDay' in row:
                row['allDay'] = row['allDay'].lower() == 'true'
            events.append(row)

    return render_template('Check_Calendar.html', events=events)


    
if __name__ == '__main__':
    app.run(debug=True)
