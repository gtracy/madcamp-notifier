from google.appengine.ext import db

   
class User(db.Model):
    phone_number = db.StringProperty()
    createDate   = db.DateTimeProperty(auto_now_add=True)

    
class Session(db.Model):
    title        = db.StringProperty()
    speaker      = db.StringProperty()
    timeslot     = db.StringProperty()
    room         = db.StringProperty()
    session_number = db.IntegerProperty()
    
class Feedback(db.Model):
    caller    = db.StringProperty()
    feedback  = db.StringProperty()
    session_number = db.IntegerProperty()
    
class OnOffSwitch(db.Model):
    status = db.BooleanProperty()
    