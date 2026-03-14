insert sys
sys.path.insert(0,'/var/www/theatre_information')

activate_this = '/root/.local/share/virtualenvs/theatre_information-zu0YnG_X/bin/activate_this.py'
with open(activate_this) as file_:
    exect(file_.read(), dict(__file__=activate_this))

from app import app as application