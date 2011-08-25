import os
import wsgiref.handlers
import logging

from google.appengine.api.taskqueue import Task
from google.appengine.api import mail
from google.appengine.api import memcache

from google.appengine.ext import webapp
from google.appengine.ext import db

from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util

from google.appengine.runtime import DeadlineExceededError
 
from twilio import twiml
from twilio import TwilioRestException
from twilio.rest import TwilioRestClient
import configuration

from dataModel import *

import gdata.docs.service
import gdata.spreadsheet.service
import gdata.spreadsheet.text_db


class CallHandler(webapp.RequestHandler):
    def post(self):
        
        # extract the message and phone
        message = self.request.get('Body')
        phone = self.request.get('From')
        
        # the first word tells us everything...
        first = message.lower().split()[0]
        
        # the admin gets extra special commands to control the app
        if phone == configuration.ADMIN_PHONE:
          if first == 'stop':
            systemSwitch(False)
          elif first == 'start':
            systemSwitch(True)
          return
            
        # interrogate the message to figure out what to do
        if first == 'signup':
          # if signup request, create a new user
          signupUser(phone)
          response = "Sweet - you're in! We'll send you schedule reminders all day."
        elif first.isdigit() or first.find('#') > -1:
          # if the first word is a number, assume it's feedback
          storeFeedback(first,message,phone)
          response = "Thanks for sharing your feedback!"
        else:
          # else, tell the caller we don't know what they're saying
          response = "Snap! We don't know what to do with this. Any feedback should start with the session number"
          sendEmail(message,phone)
          
        r = twiml.Response()
        r.sms(response)
        self.response.out.write(str(r))
        
## end CallHandler

class CronHandler(webapp.RequestHandler):

    def post(self,time_slot=""):
        logging.debug('running cron for timeslot %s' % time_slot)
        if systemIsOn() is False:
            logging.error('bailing... the system is turned off')
            return
                        
        # grab the row of data out of the spreadsheet
        results = getResults(time_slot)
        messages = getMessages(results)

        # cycle over all the users and send them a message
        users = db.GqlQuery("select * from User").fetch(200)
        for u in users:
            # send the SMS out with a background task
            task = Task(url='/sendsmstask', 
                        params={'phone':u.phone_number,
                                'msg_one':msg_one,
                                'msg_two':msg_two,
                                'msg_three':msg_three,
                               })
            task.add('smssender')

        
## end CronHandler

class BrowserHandler(webapp.RequestHandler):
    """
    A Test handler to excercise the code in the browser
    rather than via SMS
    time_slot Specifies the spreadsheet row to lookup in the Google Doc
    """
    def get(self,time_slot=""):
    
        results = getResults(time_slot)
        messages = getMessages(results)
        
        descriptions = ''
        for key in results.keys():
          descriptions += '<p>%s :: %s</p>' % (key,results[key])

        template_values = {'status':systemIsOn(),
                           'descriptions':descriptions,
                           'msg_one':messages[0],
                           'msg_two':messages[1],
                           'msg_three':messages[2],
                          }
        path = os.path.join(os.path.dirname(__file__), 'templates/testing.html')
        self.response.out.write(template.render(path, template_values))

## end BrowserHandler


class SendSMSTask(webapp.RequestHandler):
    def post(self):
      phone = self.request.get('phone')
      
      messages = []
      if len(self.request.get('msg_one')) > 0:
        messages.append(self.request.get('msg_one'))
      if len(self.request.get('msg_two')) > 0:
        messages.append(self.request.get('msg_two'))
      if len(self.request.get('msg_three')) > 0:
        messages.append(self.request.get('msg_three'))
      
      # run through the list of messages and send out the text messages
      for msg in messages:
        try:
            client = TwilioRestClient(configuration.TWILIO_ACCOUNT_SID,
                                      configuration.TWILIO_AUTH_TOKEN)
            logging.debug('sending message - %s - to %s' % (msg,phone))
            message = client.sms.messages.create(to=phone,
                                                 from_=configuration.TWILIO_CALLER_ID,
                                                 body=msg)
        except TwilioRestException,te:
            logging.error('Unable to send SMS message! %s'%te)
        
## end SendMSMSTask

def getMessages(results):

    msg_one = ''
    msg_two = ''
    msg_three = ''
    if results['time'] == 'LUNCH':
      msg_one = 'Lunch is now being served in the Lobby!'
    elif results['time'] == 'MIXER':
      msg_one = 'Meet up on the ninth floor for lightening talks!'
    else:
      msg_one = '%s on 1st Floor :: %s (big) :: %s (small)' % (results['time'],results['big'],results['small'])
      msg_two = '%s on 8th Floor :: %s (front) :: %s (back)' % (results['time'], results['murfiefront'], results['murfieback'])
      msg_three = '%s on 9th Floor :: %s (front) :: %s (back)' % (results['time'], results['front'], results['back'])

    return [msg_one,msg_two,msg_three]
    
## end getMessages()

def signupUser(phone):
    user = User()
    user.phone_number = phone
    user.put()

## end signupUser()

def storeFeedback(first,message,phone):
    if first.find('#') > -1 and len(first) > 1:
      session = first.split('#')[1]
    elif first.isdigit():
      session = first
    else:
      session = -1
    
    feedback = Feedback()
    feedback.caller = phone
    feedback.session_number = int(session)
    feedback.feedback = message
    feedback.put()

## end storeFeedback()

def sendEmail(message_string,phone):
    try:       
        # send email 
        message = mail.EmailMessage()
        message.sender = configuration.EMAIL_SENDER_ADDRESS                
        message.subject = 'madcamp notification error'
        message.to = configuration.EMAIL_SENDER_ADDRESS
        message.body = message_string + '\n' + phone
        message.send()

    except DeadlineExceededError, e:
        logging.error("DeadlineExceededError exception!?! Try to set status and return normally")
        logging.error(e)
        self.response.clear()
        self.response.set_status(200)

## end sendEmail()

    
def getResults(row_number):
        client = gdata.spreadsheet.text_db.DatabaseClient(configuration.GOOGLE_EMAIL,
                                                          configuration.GOOGLE_PASSWORD)
        if client is None:
            logging.error('unable to create a client object for Doc connection')
            return

        databases = client.GetDatabases(configuration.GOOGLE_DOC_KEY,
                                        configuration.GOOGLE_DOC_TITLE)
        results = {}
        if len(databases) != 1:
            logging.error("database query is broken!?! can't find the document")
        for db in databases:
            logging.info("looking at a database")
            tables = db.GetTables(name=configuration.GOOGLE_DOC_TAB)
            results = {}
            for t in tables:
                if t:
                    record = t.GetRecord(row_number=(int(row_number)-1))
                    if record:
                        logging.debug('we found results!')
                        for k in record.content.keys():
                          logging.debug('key: %s   value: %s' % (k,record.content[k]))
                          results[k] = record.content[k]

                else:
                    logging.error("couldn't find the table!?!")

 
        return results

def systemIsOn():

    on = memcache.get('onoffswitch')
    if on is None:
        status = db.GqlQuery('select * from OnOffSwitch').get()
        if status is None:
          status = OnOffSwitch()
          status.status = True
          status.put()
          on = True
        else:
          on = status.status
          memcache.set('onoffswitch',on)

    return on

## end systemIsOn()

def systemSwitch(on):
    status = db.GqlQuery('select * from OnOffSwitch').get()
    if status is None:
      status = OnOffSwitch()
    status.status = on
    status.put()
    memcache.set('onoffswitch',on)

## end systemSwitch()



def main():
  logging.getLogger().setLevel(logging.DEBUG)
    
  application = webapp.WSGIApplication([('/schedule/cron/(.*)', CronHandler),
                                        ('/sendsmstask', SendSMSTask),
                                        ('/inbound/sms', CallHandler),
                                        ('/test/(.*)', BrowserHandler),
                                        ],
                                       debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
