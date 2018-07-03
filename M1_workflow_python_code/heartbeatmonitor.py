'''
This workflows monitors the acceleration data and detects motion.  If the device shakes past the impact threshold,
we send an email alert and SMS alert to the email and phone number listed. It will send maximum one alert 
per day.
'''
import Store
import FreeSMS
import Email
 
phone_number = "2333333339"
email_address = "youracct@site"
 
alert_message = 'Heads up!  Your heart beat exceeds the threshold level!'
 
impact_threshold =  210
 
heartrate= IONode.get_input('in1')['event_data']['value']
 
# This checks if there was impact, and if it has been more than 24 hours since sending 
# an alert for this device.
if (heartrate > impact_threshold) and not Store.get('sent_alert'):
    log("detected")
    email = Email.Email(sender='alerts@medium.one', display_name='Medium One Alerts',
                recipients=[email_address], subject='Alert: Motion Detected', message=alert_message, attachments=None)
    email.send()
    FreeSMS.sendSMS(phone_number, alert_message) 
    Store.set_data('sent_alert', 'true', ttl=86400) # 86400 seconds = 1 day
else:
    log ("undetected")

